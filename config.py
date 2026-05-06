"""
Central configuration for the Pharma Compliance Pipeline.
All settings can be overridden via environment variables or a .env file.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""
    llm_model: str = "claude-opus-4-7"   # override via LLM_MODEL in .env
    llm_max_tokens: int = 4096
    # Use 0.0 for deterministic compliance validation
    llm_temperature: float = 0.0

    # ── Embeddings ────────────────────────────────────────────────────────
    embedding_model: str = "all-MiniLM-L6-v2"

    # ── Vector Store ──────────────────────────────────────────────────────
    chroma_persist_dir: str = "outputs/chroma_db"
    chroma_collection_name: str = "pharma_compliance_docs"

    # ── Document Processing ───────────────────────────────────────────────
    chunk_size: int = 400       # words per chunk
    chunk_overlap: int = 60     # word overlap between chunks

    # ── Performance Optimization ──────────────────────────────────────────
    enable_plots: bool = True   # Set to False for faster demo (plots are optional per assignment)
    enable_rag_verification: bool = True  # Set to False to skip RAG verification (faster but less accurate)

    # ── Paths (resolved at runtime) ───────────────────────────────────────
    @property
    def base_dir(self) -> Path:
        return Path(__file__).parent

    @property
    def outputs_dir(self) -> Path:
        return self.base_dir / "outputs"

    @property
    def reports_dir(self) -> Path:
        return self.outputs_dir / "reports"

    @property
    def plots_dir(self) -> Path:
        return self.outputs_dir / "plots"

    def ensure_dirs(self) -> None:
        """Create all output directories if they do not exist."""
        for d in (self.outputs_dir, self.reports_dir, self.plots_dir):
            d.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_dirs()
