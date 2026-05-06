"""
Agent 2 – Validation Agent (Compliance Validator)

Responsibilities
----------------
1. Rule-based validation: match each data point to a ComplianceRule from the
   embedded knowledge base and apply NMT / NLT / range checks deterministically.
2. RAG verification: confirm that the extracted value appears in the raw document
   (retrieved via the vector store) to guard against Agent 1 hallucinations.
3. LLM fallback: for parameters not covered by the knowledge base, delegate
   validation logic to the LLM with the embedded rule context in the system prompt.
4. Produce a ValidationResult (PASS / FAIL / WARNING / N/A) for every data point.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from src.agents.base_agent import BaseAgent
from src.core.compliance_rules import COMPLIANCE_RULES, get_rule_for_parameter
from src.core.vector_store import VectorStore
from src.models.schemas import (
    ComplianceRule,
    ExtractedDataPoint,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System prompt – embeds the full compliance knowledge base
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are Agent 2 – Pharmaceutical Compliance Validator.

You have access to the following standard GMP compliance knowledge base.
These limits apply to any pharmaceutical manufacturing QC / PQR document.

══ ENVIRONMENTAL MONITORING (WHO GMP / ICH Q10) ══════════════════════════════
  • Temperature            : NMT 25 °C  (Not More Than)
  • Relative Humidity      : NMT 60 % RH
  • Differential Pressure  : NLT 1.5 mm of Wc  (Not Less Than)

══ PURIFIED WATER SYSTEM (USP <1231> / USP <643>) ════════════════════════════
  • Microbial Count  : Alert ≤ 25 cfu/ml | Action ≤ 40 cfu/ml | Standard ≤ 100 cfu/ml
  • pH               : 5.0 – 7.0
  • Conductivity     : NMT 1.3 µs/cm
  • Total Organic Carbon (TOC) : NMT 500 ppb

══ OTHER PARAMETERS ══════════════════════════════════════════════════════════
  For parameters not listed above (e.g. assay results, dissolution, content uniformity,
  particle size, microbial limits for finished product), use your pharmaceutical
  regulatory knowledge (ICH Q6A, USP, BP, Ph. Eur.) to determine the appropriate limit.
  If no standard limit can be determined, return status "N/A".

VALIDATION LOGIC
  • PASS    : value is within all applicable limits
  • FAIL    : value violates the primary compliance limit
  • WARNING : value exceeds the alert limit but not the action/primary limit
  • N/A     : no applicable compliance rule exists for this parameter

Return ONLY JSON — no prose:
{"compliance_range": "...", "status": "PASS|FAIL|WARNING|N/A", "deviation": null_or_float}
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Keyword → rule category mappings (for deterministic look-up)
# ─────────────────────────────────────────────────────────────────────────────

_ENV_TEMP_KEYS = {"temperature", "temp"}
_ENV_RH_KEYS = {"humidity", "rh", "relative"}
_ENV_DP_KEYS = {"pressure", "differential", "dp"}
_WATER_MICRO_KEYS = {"microbial", "cfu", "bioburden", "count"}
_WATER_PH_KEYS = {"ph"}
_WATER_COND_KEYS = {"conductivity"}
_WATER_TOC_KEYS = {"organic", "toc", "carbon"}

_VALUE_SUFFIX_MIN = {"_min", " min", "(min)"}
_VALUE_SUFFIX_MAX = {"_max", " max", "(max)"}


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class ValidationAgent(BaseAgent):
    """
    Agent 2: deterministic + RAG + LLM-fallback compliance validation.

    Two-stage validation:
    1. Deterministic rule matching  →  apply NMT / NLT checks in code
    2. RAG cross-check              →  verify value exists in source document
    3. LLM fallback                 →  for unmapped parameters
    """

    def __init__(self, vector_store: VectorStore) -> None:
        super().__init__(name="ValidationAgent", system_prompt=_SYSTEM_PROMPT)
        self._vs = vector_store

    # ── Public API ────────────────────────────────────────────────────────

    def validate_all(
        self, data_points: List[ExtractedDataPoint]
    ) -> List[ValidationResult]:
        """Validate every data point and return a parallel list of ValidationResult."""
        results: List[ValidationResult] = []
        for dp in data_points:
            results.append(self._validate_one(dp))

        pass_n = sum(1 for r in results if r.validation_status == ValidationStatus.PASS)
        fail_n = sum(1 for r in results if r.validation_status == ValidationStatus.FAIL)
        warn_n = sum(1 for r in results if r.validation_status == ValidationStatus.WARNING)
        logger.info(
            "Validation done — PASS: %d | FAIL: %d | WARNING: %d | N/A: %d",
            pass_n, fail_n, warn_n, len(results) - pass_n - fail_n - warn_n,
        )
        return results

    # ── Private helpers ───────────────────────────────────────────────────

    # Parameters that carry no compliance meaning — skip LLM fallback for these
    _NON_COMPLIANCE_PARAMS = {
        "sr. no.", "sr no", "sr.no.", "s.no.", "serial no",
        "item code", "grade", "overages", "overages(%)",
        "quantity for the batch in kg", "quantity for the batch",
    }

    def _has_compliance_meaning(self, parameter: str) -> bool:
        return parameter.lower().strip() not in self._NON_COMPLIANCE_PARAMS

    def _validate_one(self, dp: ExtractedDataPoint) -> ValidationResult:
        """Run the full validation pipeline for a single data point."""

        # Stage 1 – Deterministic rule matching
        rule = self._find_rule(dp.parameter)
        if rule is not None:
            status, deviation, comp_range = self._apply_rule(dp, rule)
        elif not self._has_compliance_meaning(dp.parameter):
            # Skip LLM for known non-compliance metadata columns
            status, deviation, comp_range = (
                ValidationStatus.NOT_APPLICABLE, None, "Not a compliance parameter"
            )
        else:
            # Stage 3 – LLM fallback for unknown but potentially compliance-relevant params
            status, deviation, comp_range = self._llm_validate(dp)

        # Stage 2 – RAG verification (best-effort; does not override verdict)
        rag_ok = self._rag_verify(dp)

        return ValidationResult(
            section_heading=dp.section_heading,
            table_name_id=dp.table_name_id,
            parameter=dp.parameter,
            extracted_value=dp.extracted_value,
            unit=dp.unit,
            compliance_range=comp_range,
            validation_status=status,
            deviation=deviation,
            notes=f"Row: {dp.row_identifier}" if dp.row_identifier else "",
            rag_verified=rag_ok,
        )

    # ── Rule matching ─────────────────────────────────────────────────────

    def _find_rule(self, parameter: str) -> Optional[ComplianceRule]:
        """
        Map a parameter name to a ComplianceRule using keyword matching
        against the standard GMP knowledge base.
        Only standard regulatory parameters are matched here — document-specific
        ingredients or product-specific specs fall through to the LLM fallback.
        """
        p = parameter.lower()

        # Environmental monitoring
        if any(k in p for k in _ENV_TEMP_KEYS):
            return self._pick_rule("environmental_monitoring", "Temperature")
        if any(k in p for k in _ENV_RH_KEYS):
            return self._pick_rule("environmental_monitoring", "Relative Humidity")
        if any(k in p for k in _ENV_DP_KEYS):
            return self._pick_rule("environmental_monitoring", "Differential Pressure")

        # Purified water
        if any(k in p for k in _WATER_MICRO_KEYS):
            return self._pick_rule("purified_water", "Microbial Count")
        if any(k in p for k in _WATER_PH_KEYS):
            return self._pick_rule("purified_water", "pH")
        if any(k in p for k in _WATER_COND_KEYS):
            return self._pick_rule("purified_water", "Conductivity")
        if any(k in p for k in _WATER_TOC_KEYS):
            return self._pick_rule("purified_water", "Total Organic Carbon")

        # No standard rule found — will fall through to LLM fallback
        return None

    def _pick_rule(self, category: str, rule_name: str) -> Optional[ComplianceRule]:
        for rule in COMPLIANCE_RULES.get(category, []):
            if rule.parameter == rule_name:
                return rule
        return None

    # ── Rule application ──────────────────────────────────────────────────

    def _apply_rule(
        self,
        dp: ExtractedDataPoint,
        rule: ComplianceRule,
    ) -> Tuple[ValidationStatus, Optional[float], str]:
        """
        Apply a ComplianceRule deterministically.

        Handles the NMT / NLT asymmetry:
          - For _Max parameters: the observed max must satisfy the NMT limit.
          - For _Min parameters: the observed min must satisfy the NLT limit.
          - When there is no Min/Max suffix, apply all constraints.
        """
        try:
            value = float(dp.extracted_value)  # type: ignore[arg-type]
        except (ValueError, TypeError):
            return ValidationStatus.NOT_APPLICABLE, None, rule.rule_text

        param_lower = dp.parameter.lower()
        is_min_obs = any(param_lower.endswith(s) for s in _VALUE_SUFFIX_MIN)
        is_max_obs = any(param_lower.endswith(s) for s in _VALUE_SUFFIX_MAX)

        status = ValidationStatus.PASS
        deviation: Optional[float] = None

        # ── NMT (max) constraint ───────────────────────────────────────────
        if rule.max_value is not None:
            check_nmt = is_max_obs or (not is_min_obs)
            if check_nmt and value > rule.max_value:
                status = ValidationStatus.FAIL
                deviation = round(value - rule.max_value, 4)

        # ── NLT (min) constraint ───────────────────────────────────────────
        if rule.min_value is not None:
            check_nlt = is_min_obs or (not is_max_obs)
            if check_nlt and value < rule.min_value:
                status = ValidationStatus.FAIL
                deviation = round(rule.min_value - value, 4)

        # ── Alert (soft) limit — only applies if still passing ────────────
        if status == ValidationStatus.PASS and rule.alert_max is not None:
            if value > rule.alert_max:
                status = ValidationStatus.WARNING

        return status, deviation, rule.rule_text

    # ── RAG verification ──────────────────────────────────────────────────

    def _rag_verify(self, dp: ExtractedDataPoint) -> bool:
        """Confirm that the extracted value string exists in the source document."""
        return self._vs.verify_value_in_document(
            value=str(dp.extracted_value),
            parameter=dp.parameter,
            section=dp.section_heading,
        )

    # ── LLM fallback ──────────────────────────────────────────────────────

    def _llm_validate(
        self, dp: ExtractedDataPoint
    ) -> Tuple[ValidationStatus, Optional[float], str]:
        """
        Use the LLM (with the embedded knowledge base in its system prompt)
        to validate a parameter not matched by the rule engine.
        """
        prompt = (
            f"Validate this pharmaceutical data point against your knowledge base:\n\n"
            f"  Parameter       : {dp.parameter}\n"
            f"  Extracted value : {dp.extracted_value} {dp.unit}\n"
            f"  Section heading : {dp.section_heading}\n"
            f"  Context         : {dp.context}\n\n"
            f"Return ONLY JSON: "
            f'{{\"compliance_range\": \"...\", \"status\": \"PASS|FAIL|WARNING|N/A\", '
            f'\"deviation\": null_or_float}}'
        )
        try:
            response = self._call_llm(prompt, max_tokens=256)
            data = self._parse_json_response(response)

            status_str = str(data.get("status", "N/A")).upper().strip()
            try:
                status = ValidationStatus(status_str)
            except ValueError:
                status = ValidationStatus.NOT_APPLICABLE

            deviation = data.get("deviation")
            if deviation is not None:
                try:
                    deviation = float(deviation)
                except (ValueError, TypeError):
                    deviation = None

            return status, deviation, str(data.get("compliance_range", "LLM-inferred"))

        except Exception as exc:
            logger.warning(
                "LLM validation fallback failed for '%s': %s", dp.parameter, exc
            )
            return (
                ValidationStatus.NOT_APPLICABLE,
                None,
                "No compliance rule found",
            )
