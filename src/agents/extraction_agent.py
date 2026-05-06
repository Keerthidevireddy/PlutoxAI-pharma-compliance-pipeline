"""
Agent 1 – Extraction Agent (Table & Data Miner)

Responsibilities
----------------
- Receives all ExtractedTable objects from the document processor.
- For each table, uses an LLM call (Claude) guided by EXTRACTION_GUIDANCE
  to produce a structured list of ExtractedDataPoint objects.
- Falls back to rule-based numeric extraction if the LLM call fails.
"""

from __future__ import annotations

import logging
from typing import List, Union

from src.agents.base_agent import BaseAgent
from src.core.compliance_rules import EXTRACTION_GUIDANCE
from src.core.document_processor import ExtractedTable
from src.models.schemas import ExtractedDataPoint

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = f"""
You are a specialised pharmaceutical data extraction agent (Agent 1 – Table & Data Miner).

Your only task is to read a table from a pharmaceutical Product Quality Review (PQR)
document and return a JSON array of extracted data points.  Do not add any prose or
explanation — return ONLY valid JSON.

{EXTRACTION_GUIDANCE}

OUTPUT SCHEMA (JSON array of objects):
[
  {{
    "section_heading": "<Full section heading text>",
    "table_name_id": "<Table identifier, e.g. Table_P2_1>",
    "parameter": "<parameter name, use _Min / _Max suffixes where applicable>",
    "extracted_value": <float or "string fallback">,
    "unit": "<physical unit or empty string>",
    "row_identifier": "<e.g. 'Mar-23 | Blender III' or ingredient name>",
    "context": "<one sentence describing the measurement>"
  }},
  ...
]
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class ExtractionAgent(BaseAgent):
    """Agent 1: LLM-guided extraction of numerical compliance data from PDF tables."""

    def __init__(self) -> None:
        super().__init__(name="ExtractionAgent", system_prompt=_SYSTEM_PROMPT)

    # ── Public API ────────────────────────────────────────────────────────

    def extract_from_tables(
        self, tables: List[ExtractedTable]
    ) -> List[ExtractedDataPoint]:
        """
        Run extraction over every table.

        Returns a flat list of ExtractedDataPoint, ordered by page / table.
        """
        all_points: List[ExtractedDataPoint] = []

        for tbl in tables:
            logger.info(
                "Extracting from %s (Section %s, Page %d)",
                tbl.table_id, tbl.section, tbl.page_num,
            )
            points = self._extract_single_table(tbl)
            logger.debug("  → %d data points from %s", len(points), tbl.table_id)
            all_points.extend(points)

        logger.info("Extraction complete — %d total data points", len(all_points))
        return all_points

    # ── Private helpers ───────────────────────────────────────────────────

    def _extract_single_table(
        self, tbl: ExtractedTable
    ) -> List[ExtractedDataPoint]:
        """LLM-based extraction for one table, with rule-based fallback."""
        prompt = self._build_prompt(tbl)

        try:
            raw_response = self._call_llm(prompt)
            raw_list = self._parse_json_response(raw_response)

            if not isinstance(raw_list, list):
                raise ValueError("LLM returned non-list JSON")

            return self._parse_data_points(raw_list, tbl)

        except Exception as exc:
            logger.warning(
                "LLM extraction failed for %s: %s — using fallback",
                tbl.table_id, exc,
            )
            return self._fallback_extract(tbl)

    def _build_prompt(self, tbl: ExtractedTable) -> str:
        """Construct the user message for the LLM extraction call."""
        heading = tbl.section_heading or f"Section {tbl.section}"
        return (
            f"Extract all compliance-relevant numerical data from the table below.\n\n"
            f"SECTION HEADING : {heading}\n"
            f"TABLE ID        : {tbl.table_id}\n"
            f"PAGE            : {tbl.page_num}\n\n"
            f"TABLE CONTENT:\n"
            f"{tbl.raw_text}\n\n"
            f"Return ONLY a JSON array.  No text before or after the array."
        )

    def _parse_data_points(
        self, raw_list: list, tbl: ExtractedTable
    ) -> List[ExtractedDataPoint]:
        """Convert raw LLM-returned dicts into ExtractedDataPoint objects."""
        points: List[ExtractedDataPoint] = []
        heading = tbl.section_heading or f"Section {tbl.section}"

        for item in raw_list:
            if not isinstance(item, dict):
                continue
            try:
                val: Union[float, str] = item.get("extracted_value", "")
                try:
                    val = float(str(val).replace(",", "").strip())
                except (ValueError, TypeError):
                    val = str(val)

                dp = ExtractedDataPoint(
                    section_heading=item.get("section_heading", heading),
                    table_name_id=item.get("table_name_id", tbl.table_id),
                    parameter=str(item.get("parameter", "")).strip(),
                    extracted_value=val,
                    unit=str(item.get("unit", "")).strip(),
                    row_identifier=str(item.get("row_identifier", "")).strip(),
                    context=str(item.get("context", "")).strip(),
                )
                if dp.parameter:  # skip empty parameter names
                    points.append(dp)

            except Exception as exc:
                logger.debug("Skipping malformed item %s: %s", item, exc)

        return points

    # Columns that carry index/metadata values, not compliance measurements
    _SKIP_HEADERS = {
        "sr. no.", "sr no", "sr.no.", "s.no.", "s. no.", "serial no",
        "item code", "grade", "overages", "overages(%)", "overages (%)",
        "description", "remarks", "batch no", "batch no.", "batch number",
        "mfr no", "bmr no", "mpr no", "bpr no", "pack size",
        "mfg. date", "exp. date", "mfg date", "exp date",
        "pharmaceutical ingredient", "name",
    }

    def _is_compliance_header(self, header: str) -> bool:
        """Return True only for headers that hold compliance-relevant numeric data."""
        return header.lower().strip() not in self._SKIP_HEADERS

    def _fallback_extract(self, tbl: ExtractedTable) -> List[ExtractedDataPoint]:
        """
        Rule-based fallback: scan numeric cells but skip metadata/index columns
        (Sr. No., Item Code, etc.) that are not compliance measurements.
        """
        points: List[ExtractedDataPoint] = []
        heading = tbl.section_heading or f"Section {tbl.section}"

        for row_idx, row in enumerate(tbl.rows):
            row_label = str(row[0]).strip() if row else f"Row_{row_idx}"
            for header, cell in zip(tbl.headers, row):
                if not self._is_compliance_header(header):
                    continue  # skip index / metadata columns

                clean = str(cell).replace(",", "").strip()
                try:
                    numeric_val = float(clean)
                except (ValueError, TypeError):
                    continue

                points.append(
                    ExtractedDataPoint(
                        section_heading=heading,
                        table_name_id=tbl.table_id,
                        parameter=header.strip(),
                        extracted_value=numeric_val,
                        unit="",
                        row_identifier=row_label,
                        context=f"Fallback extraction — {tbl.table_id} row {row_idx}",
                    )
                )

        logger.info(
            "Fallback extracted %d numeric cells from %s", len(points), tbl.table_id
        )
        return points
