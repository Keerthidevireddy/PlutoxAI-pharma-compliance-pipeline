"""
Pydantic v2 data models for the Pharma Compliance Pipeline.

All inter-agent data contracts are defined here to guarantee
type safety and serialisation consistency throughout the pipeline.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional, Union

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────────────────────────


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"          # e.g. alert limit breached but < action limit
    NOT_APPLICABLE = "N/A"       # no rule found for parameter


# ─────────────────────────────────────────────────────────────────────────────
# Compliance Knowledge Base Model
# ─────────────────────────────────────────────────────────────────────────────


class ComplianceRule(BaseModel):
    """A single compliance rule as embedded in Agent 2's knowledge base."""

    parameter: str
    min_value: Optional[float] = None   # NLT (Not Less Than) limit
    max_value: Optional[float] = None   # NMT (Not More Than) limit
    alert_max: Optional[float] = None   # Alert limit (softer NMT)
    alert_min: Optional[float] = None   # Alert limit (softer NLT)
    unit: str = ""
    description: str = ""
    rule_text: str = ""                 # Human-readable form of the rule


# ─────────────────────────────────────────────────────────────────────────────
# Agent 1 Output
# ─────────────────────────────────────────────────────────────────────────────


class ExtractedDataPoint(BaseModel):
    """
    One numerical (or textual) data point extracted by the Extraction Agent.
    Each row×column cell that carries a compliance-relevant value becomes
    its own ExtractedDataPoint.
    """

    section_heading: str = Field(description="Section title where the data was found")
    table_name_id: str = Field(description="Identifier of the source table")
    parameter: str = Field(description="Column/parameter name (e.g. 'Temperature_Max')")
    extracted_value: Union[float, str] = Field(
        description="The extracted value — float preferred, str as fallback"
    )
    unit: str = Field(default="", description="Physical unit (°C, %, cfu/ml …)")
    row_identifier: str = Field(
        default="", description="Human-readable row label (month, area, ingredient …)"
    )
    context: str = Field(
        default="", description="Free-text context to help the validation agent"
    )

    @field_validator("extracted_value", mode="before")
    @classmethod
    def coerce_value(cls, v: object) -> Union[float, str]:
        if isinstance(v, (int, float)):
            return float(v)
        try:
            return float(str(v).replace(",", "").strip())
        except (ValueError, TypeError):
            return str(v)


# ─────────────────────────────────────────────────────────────────────────────
# Agent 2 Output
# ─────────────────────────────────────────────────────────────────────────────


class ValidationResult(BaseModel):
    """
    One validated data point produced by the Validation Agent.
    Includes the original extracted value plus compliance verdict.
    """

    section_heading: str
    table_name_id: str
    parameter: str
    extracted_value: Union[float, str]
    unit: str = ""
    compliance_range: str = Field(
        description="Human-readable rule applied (e.g. 'NMT 25°C')"
    )
    validation_status: ValidationStatus
    deviation: Optional[float] = Field(
        default=None,
        description="Distance from the limit (positive = exceeds / falls short of limit)",
    )
    notes: str = ""
    rag_verified: bool = Field(
        default=False,
        description="True when the value was confirmed in the raw document via RAG",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Agent 3 Output
# ─────────────────────────────────────────────────────────────────────────────


class StatisticalSummary(BaseModel):
    """Per-parameter descriptive statistics computed by the Analytical Agent."""

    parameter: str
    section: str
    count: int
    mean: float
    median: float
    std_dev: float
    min_value: float
    max_value: float
    cpk: Optional[float] = Field(
        default=None,
        description="Process Capability Index — None when limits are unavailable",
    )
    compliance_rate: float = Field(
        description="Percentage of observations that passed validation"
    )
    trend: str = Field(
        default="", description="Linear-regression trend description"
    )


class AnalyticalSummary(BaseModel):
    """Full analytical output produced by the Analytical Agent."""

    generated_at: datetime = Field(default_factory=datetime.now)
    statistical_summaries: list[StatisticalSummary]
    overall_compliance_rate: float
    critical_failures: list[str]
    insights: str
    plot_paths: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Output (root model)
# ─────────────────────────────────────────────────────────────────────────────


class PipelineOutput(BaseModel):
    """Complete output of one pipeline run."""

    document_path: str
    query: str
    processed_at: datetime = Field(default_factory=datetime.now)
    extraction_results: list[ExtractedDataPoint]
    validation_report: list[ValidationResult]
    analytical_summary: AnalyticalSummary
    total_records: int
    pass_count: int
    fail_count: int

    @property
    def overall_pass_rate(self) -> float:
        if self.total_records == 0:
            return 0.0
        return round(self.pass_count / self.total_records * 100, 2)
