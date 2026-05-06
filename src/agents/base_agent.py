"""
Base agent class shared by all three specialised agents.

Provides:
  - A configured Anthropic client
  - A robust _call_llm() wrapper with retry on transient errors
  - A JSON-parsing helper that handles markdown code fences
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import anthropic

from config import settings

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY = 2.0  # seconds


class BaseAgent:
    """
    Abstract base for all pipeline agents.

    Subclasses must set ``name`` and pass a ``system_prompt`` to ``__init__``.
    """

    def __init__(self, name: str, system_prompt: str) -> None:
        self.name = name
        self.system_prompt = system_prompt
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        logger.debug("Agent '%s' initialised", name)

    # ── LLM call ──────────────────────────────────────────────────────────

    def _call_llm(
        self,
        user_message: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> str:
        """
        Call the Claude API with automatic retry on transient API errors.

        Returns the raw text response.
        """
        max_tokens = max_tokens or settings.llm_max_tokens
        temperature = temperature if temperature is not None else settings.llm_temperature

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.messages.create(
                    model=settings.llm_model,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    system=self.system_prompt,
                    messages=[{"role": "user", "content": user_message}],
                )
                return response.content[0].text  # type: ignore[union-attr]

            except anthropic.RateLimitError:
                wait = _RETRY_DELAY * attempt
                logger.warning(
                    "[%s] Rate-limited — waiting %.1f s (attempt %d/%d)",
                    self.name, wait, attempt, _MAX_RETRIES,
                )
                time.sleep(wait)

            except anthropic.APIStatusError as exc:
                if attempt == _MAX_RETRIES:
                    raise
                logger.warning(
                    "[%s] API error %d — retrying (attempt %d/%d): %s",
                    self.name, exc.status_code, attempt, _MAX_RETRIES, exc.message,
                )
                time.sleep(_RETRY_DELAY)

        raise RuntimeError(f"[{self.name}] All {_MAX_RETRIES} LLM attempts failed")

    # ── JSON parsing ──────────────────────────────────────────────────────

    def _parse_json_response(self, response: str) -> Any:
        """
        Parse a JSON value from an LLM response.

        Handles:
          - Bare JSON
          - JSON wrapped in ```json … ``` or ``` … ``` markdown fences
          - Responses where prose precedes the JSON
        """
        # Strip markdown fences
        fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response)
        if fence_match:
            candidate = fence_match.group(1).strip()
        else:
            candidate = response.strip()

        # Direct parse
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

        # Find first JSON structure (array or object)
        bracket_match = re.search(r"(\[[\s\S]*\]|\{[\s\S]*\})", candidate)
        if bracket_match:
            try:
                return json.loads(bracket_match.group(1))
            except json.JSONDecodeError:
                pass

        raise ValueError(
            f"[{self.name}] Could not parse JSON from LLM response:\n{response[:400]}"
        )
