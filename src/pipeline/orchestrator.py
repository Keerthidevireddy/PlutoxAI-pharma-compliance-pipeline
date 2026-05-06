"""
Pipeline Orchestrator

Wires together the four pipeline stages in the correct order:

  Stage 1 – Document Preparation
    DocumentProcessor  →  text/table extraction
    VectorStore        →  index chunks for RAG

  Stage 2 – Agent 1: Extraction
    ExtractionAgent    →  LLM-guided structured data extraction

  Stage 3 – Agent 2: Validation
    ValidationAgent    →  rule-based + RAG + LLM-fallback compliance checks

  Stage 4 – Agent 3: Analytics
    AnalyticalAgent    →  statistics + plots + insight narrative

  Stage 5 – Output
    Save JSON report + plain-text summary to outputs/reports/
"""

from __future__ import annotations

import logging
from datetime import datetime

from config import settings
from src.agents.analytical_agent import AnalyticalAgent
from src.agents.extraction_agent import ExtractionAgent
from src.agents.validation_agent import ValidationAgent
from src.core.document_processor import DocumentProcessor
from src.core.vector_store import VectorStore
from src.models.schemas import PipelineOutput, ValidationStatus

logger = logging.getLogger(__name__)


class PharmaCompliancePipeline:
    """
    End-to-end multi-agent pipeline for pharma compliance document processing.

    Usage
    -----
    >>> pipeline = PharmaCompliancePipeline()
    >>> output = pipeline.run("path/to/document.pdf", query="...")
    """

    def __init__(self) -> None:
        logger.info("Initialising PharmaCompliancePipeline …")

        self._doc_processor = DocumentProcessor(
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
        )

        self._vector_store = VectorStore(
            persist_dir=settings.chroma_persist_dir,
            collection_name=settings.chroma_collection_name,
            embedding_model=settings.embedding_model,
        )

        self._extraction_agent = ExtractionAgent()
        self._validation_agent = ValidationAgent(self._vector_store)
        self._analytical_agent = AnalyticalAgent()

        logger.info("Pipeline ready.")

    # ── Public API ────────────────────────────────────────────────────────

    def run(self, pdf_path: str, query: str) -> PipelineOutput:
        """
        Execute the complete pipeline on a single PDF document.

        Parameters
        ----------
        pdf_path : str | Path
            Path to the pharma compliance PDF document.
        query : str
            Natural-language extraction query (recorded in the output).

        Returns
        -------
        PipelineOutput
            Fully populated Pydantic model; also saved to outputs/reports/.
        """
        logger.info("=" * 60)
        logger.info("PIPELINE START — %s", pdf_path)
        logger.info("QUERY: %s", query[:120])
        logger.info("=" * 60)

        # ── Stage 1: Document Preparation ────────────────────────────────
        logger.info("[Stage 1] Document ingestion & indexing …")
        chunks, tables = self._doc_processor.load_document(pdf_path)
        logger.info("  %d chunks, %d tables extracted", len(chunks), len(tables))
        self._vector_store.index_chunks(chunks)
        logger.info("  Vector store indexed.")

        # ── Stage 2: Agent 1 – Extraction ────────────────────────────────
        logger.info("[Stage 2] Agent 1 – Extraction …")
        extracted = self._extraction_agent.extract_from_tables(tables)
        logger.info("  %d data points extracted.", len(extracted))

        if not extracted:
            logger.warning("  No data points extracted — check the PDF or extraction agent.")

        # ── Stage 3: Agent 2 – Validation ────────────────────────────────
        logger.info("[Stage 3] Agent 2 – Validation …")
        validation_results = self._validation_agent.validate_all(extracted)
        pass_n = sum(1 for r in validation_results if r.validation_status == ValidationStatus.PASS)
        fail_n = sum(1 for r in validation_results if r.validation_status == ValidationStatus.FAIL)
        logger.info("  PASS: %d | FAIL: %d | Total: %d", pass_n, fail_n, len(validation_results))

        # ── Stage 4: Agent 3 – Analytics ─────────────────────────────────
        logger.info("[Stage 4] Agent 3 – Statistical analysis …")
        analytical_summary = self._analytical_agent.analyze(validation_results)
        logger.info(
            "  Overall compliance rate: %.1f%%", analytical_summary.overall_compliance_rate
        )
        logger.info("  Plots generated: %d", len(analytical_summary.plot_paths))

        # ── Stage 5: Output ───────────────────────────────────────────────
        output = PipelineOutput(
            document_path=str(pdf_path),
            query=query,
            extraction_results=extracted,
            validation_report=validation_results,
            analytical_summary=analytical_summary,
            total_records=len(validation_results),
            pass_count=pass_n,
            fail_count=fail_n,
        )

        self._save_reports(output)
        logger.info("=" * 60)
        logger.info("PIPELINE COMPLETE — Pass rate: %.1f%%", output.overall_pass_rate)
        logger.info("=" * 60)

        return output

    # ── Persistence ───────────────────────────────────────────────────────

    def _save_reports(self, output: PipelineOutput) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        # JSON report
        json_path = settings.reports_dir / f"validation_report_{ts}.json"
        with open(json_path, "w", encoding="utf-8") as fh:
            fh.write(output.model_dump_json(indent=2))
        logger.info("JSON report: %s", json_path)

        # Plain-text summary
        txt_path = settings.reports_dir / f"summary_{ts}.txt"
        txt_path.write_text(self._format_text_report(output), encoding="utf-8")
        logger.info("Text summary: %s", txt_path)

    def _format_text_report(self, output: PipelineOutput) -> str:
        bar = "=" * 80
        thin = "-" * 80

        lines = [
            bar,
            "  PHARMA COMPLIANCE PIPELINE – VALIDATION REPORT",
            bar,
            f"  Document  : {output.document_path}",
            f"  Processed : {output.processed_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Query     : {output.query[:100]}",
            "",
            "  OVERALL SUMMARY",
            thin,
            f"  Total records  : {output.total_records}",
            f"  PASS           : {output.pass_count}",
            f"  FAIL           : {output.fail_count}",
            f"  Pass rate      : {output.overall_pass_rate:.1f} %",
            "",
            "  VALIDATION RESULTS",
            thin,
        ]

        for r in output.validation_report:
            icon = "✓" if r.validation_status.value == "PASS" else "✗"
            dev = f"  Δ={r.deviation}" if r.deviation else ""
            lines.append(
                f"  {icon} [{r.validation_status.value:4}]  "
                f"{r.parameter[:38]:38}  "
                f"= {str(r.extracted_value):>8} {r.unit:<8}  "
                f"Rule: {r.compliance_range[:28]}{dev}"
            )

        lines += [
            "",
            "  STATISTICAL SUMMARIES",
            thin,
        ]
        for s in output.analytical_summary.statistical_summaries:
            cpk_str = f"{s.cpk:.3f}" if s.cpk is not None else "N/A"
            lines.append(
                f"  {s.parameter[:35]:35}  "
                f"n={s.count:3}  Mean={s.mean:.3f}  SD={s.std_dev:.3f}  "
                f"Cpk={cpk_str}  Compliance={s.compliance_rate:.1f}%"
            )

        lines += [
            "",
            "  ANALYTICAL INSIGHTS",
            thin,
            output.analytical_summary.insights,
            "",
        ]

        if output.analytical_summary.critical_failures:
            lines += ["  CRITICAL FAILURES", thin]
            for f in output.analytical_summary.critical_failures[:20]:
                lines.append(f"  ► {f}")

        if output.analytical_summary.plot_paths:
            lines += ["", "  GENERATED PLOTS", thin]
            for p in output.analytical_summary.plot_paths:
                lines.append(f"  📊 {p}")

        lines.append(bar)
        return "\n".join(lines)
