"""
Embedded compliance knowledge base for Agent 2 (Validation Agent).

Rules here are based on standard pharmaceutical GMP regulatory requirements:
  - ICH Q10 / WHO GMP guidelines for manufacturing environments
  - USP <1231> Purified Water specifications
  - USP <643> Total Organic Carbon

These limits apply generically across pharmaceutical QC/PQR documents.
Document-specific values (e.g. ingredient quantities per batch) are intentionally
NOT hardcoded here — Agent 1 extracts them, Agent 2 validates structurally
(e.g. checking that quantities match stated specifications within the document itself).
"""

from __future__ import annotations

from typing import Dict, List, Optional

from src.models.schemas import ComplianceRule


# ─────────────────────────────────────────────────────────────────────────────
# Standard GMP Compliance Knowledge Base
# ─────────────────────────────────────────────────────────────────────────────

COMPLIANCE_RULES: Dict[str, List[ComplianceRule]] = {

    # ── Environmental Monitoring ──────────────────────────────────────────
    # Applies to any classified manufacturing area per WHO GMP / ICH Q10
    "environmental_monitoring": [
        ComplianceRule(
            parameter="Temperature",
            max_value=25.0,
            unit="°C",
            description="Room temperature limit for classified manufacturing areas",
            rule_text="NMT 25°C",
        ),
        ComplianceRule(
            parameter="Relative Humidity",
            max_value=60.0,
            unit="% RH",
            description="Relative humidity limit for classified manufacturing areas",
            rule_text="NMT 60% RH",
        ),
        ComplianceRule(
            parameter="Differential Pressure",
            min_value=1.5,
            unit="mm of Wc",
            description="Minimum positive pressure differential between adjacent areas",
            rule_text="NLT 1.5 mm of Wc",
        ),
    ],

    # ── Purified Water System ─────────────────────────────────────────────
    # USP <1231> and USP <643> specifications
    "purified_water": [
        ComplianceRule(
            parameter="Microbial Count",
            alert_max=25.0,    # alert action limit
            max_value=40.0,    # action limit; standard limit = 100 cfu/ml
            unit="cfu/ml",
            description="Microbial bioburden in purified water",
            rule_text="Alert: NMT 25 cfu/ml | Action: NMT 40 cfu/ml | Standard: NMT 100 cfu/ml",
        ),
        ComplianceRule(
            parameter="pH",
            min_value=5.0,
            max_value=7.0,
            unit="",
            description="pH range for Purified Water (USP <1231>)",
            rule_text="pH 5.0 – 7.0",
        ),
        ComplianceRule(
            parameter="Conductivity",
            max_value=1.3,
            unit="µs/cm",
            description="Electrical conductivity of Purified Water (USP <1231>)",
            rule_text="NMT 1.3 µs/cm",
        ),
        ComplianceRule(
            parameter="Total Organic Carbon",
            max_value=500.0,
            unit="ppb",
            description="Total Organic Carbon in Purified Water (USP <643>)",
            rule_text="NMT 500 ppb",
        ),
    ],
}


# ─────────────────────────────────────────────────────────────────────────────
# Section keyword → rule category mapping
# Matches common section titles found in pharma QC/PQR documents generically.
# Agent 1 uses section heading text to route extracted data to the right rules.
# ─────────────────────────────────────────────────────────────────────────────

SECTION_CATEGORY_KEYWORDS: Dict[str, str] = {
    "temperature":            "environmental_monitoring",
    "relative humidity":      "environmental_monitoring",
    "differential pressure":  "environmental_monitoring",
    "environmental":          "environmental_monitoring",
    "hvac":                   "environmental_monitoring",
    "purified water":         "purified_water",
    "water system":           "purified_water",
    "water quality":          "purified_water",
    "microbial":              "purified_water",
}

# Legacy section-number map kept for backwards compatibility with documents
# that use numbered sections (e.g. 6.0, 7.0). Not specific to any one document.
SECTION_RULES_MAP: Dict[str, str] = {}


def get_category_for_section(section_heading: str) -> str:
    """
    Derive the rule category from a section heading string by keyword matching.
    Returns an empty string if no category is matched.
    """
    heading_lower = section_heading.lower()
    for keyword, category in SECTION_CATEGORY_KEYWORDS.items():
        if keyword in heading_lower:
            return category
    return ""


def get_rules_for_section(section_heading: str) -> List[ComplianceRule]:
    """Return applicable ComplianceRules for a given section heading."""
    category = get_category_for_section(section_heading)
    return COMPLIANCE_RULES.get(category, [])


def get_rule_for_parameter(
    parameter: str, section_heading: str = ""
) -> Optional[ComplianceRule]:
    """
    Best-effort lookup of a ComplianceRule by parameter name.
    Checks section-specific rules first, then falls back to global search.
    """
    param_lower = parameter.lower()

    # Section-specific search
    if section_heading:
        category = get_category_for_section(section_heading)
        if category and category in COMPLIANCE_RULES:
            for rule in COMPLIANCE_RULES[category]:
                if (
                    rule.parameter.lower() in param_lower
                    or param_lower in rule.parameter.lower()
                ):
                    return rule

    # Global search across all categories
    for category_rules in COMPLIANCE_RULES.values():
        for rule in category_rules:
            if (
                rule.parameter.lower() in param_lower
                or param_lower in rule.parameter.lower()
            ):
                return rule

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Generic extraction guidance injected into Agent 1's system prompt
# ─────────────────────────────────────────────────────────────────────────────

EXTRACTION_GUIDANCE: str = """
You are extracting compliance data from a pharmaceutical Quality Control (QC) or
Product Quality Review (PQR) document. The document structure may vary — use the
section headings and table headers to identify what each table contains.

WHAT TO EXTRACT
===============
Focus on tables that contain measured or recorded numerical values. Common sections
in pharma QC documents include (but are not limited to):

1. BATCH MANUFACTURING / BATCH FORMULA sections
   - Extract: ingredient names, input quantities (mg/tablet or kg/batch), overages

2. ENVIRONMENTAL MONITORING sections (Temperature / Relative Humidity / Differential Pressure)
   - Standard GMP limits: Temperature NMT 25°C | RH NMT 60% | DP NLT 1.5 mm of Wc
   - Extract: monitoring area, month/period, Min and Max observed values per parameter

3. PURIFIED WATER / UTILITY SYSTEMS sections
   - Standard limits: Microbial Count alert NMT 25 cfu/ml | pH 5.0–7.0 |
     Conductivity NMT 1.3 µs/cm | TOC NMT 500 ppb
   - Extract: sampling point/month, Min and Max observed values per parameter

4. PRODUCT RELEASE TESTING / IN-PROCESS TESTING sections
   - Extract: test parameter, specification/limit, result/value, unit

5. STABILITY STUDIES sections
   - Extract: time point, storage condition, parameter, result, specification

EXTRACTION RULES
================
1. Create ONE record per (row × measured parameter). Do NOT merge rows.
2. For Min/Max pairs, create separate records with "_Min" and "_Max" suffixes
   e.g. "Temperature_Min", "Temperature_Max".
3. Parse extracted_value as float wherever possible.
4. Use row_identifier to capture what the row represents:
   e.g. "Jan-24 | Area A" for environmental data, "Ingredient Name" for formulas.
5. Populate section_heading from the nearest section title above the table.
6. Return ONLY a valid JSON array — no prose, no markdown, no explanation.
"""
