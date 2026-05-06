"""
Pharma Compliance Pipeline – CLI Entry Point

Usage
-----
    python main.py <path_to_pdf>

Example
-------
    python main.py "extract-call.pdf"
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # load .env before importing settings-dependent modules

from config import settings  # noqa: E402 (after load_dotenv)
from src.models.schemas import ValidationStatus  # noqa: E402
from src.pipeline.orchestrator import PharmaCompliancePipeline  # noqa: E402

# -- Logging setup ----------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-28s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(settings.outputs_dir / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("main")

# -- Default query ----------------------------------------------------------

DEFAULT_QUERY = (
    "Extract all tables containing numerical data related to Environmental Monitoring, "
    "Purified Water System, Batch Manufacturing Formula, and Product Quality parameters. "
    "Validate the extracted values against predefined compliance ranges and provide a "
    "statistical summary with process capability analysis."
)


# -- Display helpers --------------------------------------------------------

def _separator(char: str = "-", width: int = 80) -> str:
    return char * width


def _print_header() -> None:
    print()
    print(_separator("="))
    print("  Pharma Compliance Agentic Pipeline  |  Multi-Agent Document Processing")
    print(_separator("="))
    print()


def _print_results(output) -> None:
    """Pretty-print the pipeline results to stdout."""

    # Summary block
    print()
    print(_separator())
    print("  PIPELINE RESULTS SUMMARY")
    print(_separator())
    print(f"  Document       : {output.document_path}")
    print(f"  Total records  : {output.total_records}")
    print(f"  PASS           : {output.pass_count}")
    print(f"  FAIL           : {output.fail_count}")
    print(f"  Pass rate      : {output.overall_pass_rate:.1f} %")
    print(_separator())

    # Validation table header
    print()
    print(
        f"  {'STATUS':<7}  {'PARAMETER':<38}  {'VALUE':>9}  {'UNIT':<9}"
        f"  {'RAG':^5}  COMPLIANCE RULE"
    )
    print(_separator("-"))

    for r in output.validation_report:
        icon = "PASS  " if r.validation_status == ValidationStatus.PASS else "FAIL  "
        if r.validation_status == ValidationStatus.WARNING:
            icon = "WARN  "
        if r.validation_status == ValidationStatus.NOT_APPLICABLE:
            icon = "N/A   "

        rag_icon = "Y" if r.rag_verified else "N"
        dev = f" Δ={r.deviation:.3f}" if r.deviation is not None else ""
        print(
            f"  {icon:<7}  {r.parameter[:38]:<38}  {str(r.extracted_value):>9}"
            f"  {r.unit[:9]:<9}  {rag_icon:^5}  {r.compliance_range[:35]}{dev}"
        )

    # Statistical summaries
    if output.analytical_summary.statistical_summaries:
        print()
        print(_separator())
        print("  STATISTICAL SUMMARIES")
        print(_separator("-"))
        print(
            f"  {'PARAMETER':<35}  {'N':>4}  {'MEAN':>9}  {'SD':>8}"
            f"  {'CPK':>6}  {'COMPLIANCE':>11}"
        )
        print(_separator("-"))
        for s in output.analytical_summary.statistical_summaries:
            cpk_s = f"{s.cpk:.3f}" if s.cpk is not None else "   N/A"
            print(
                f"  {s.parameter[:35]:<35}  {s.count:>4}  {s.mean:>9.4f}  {s.std_dev:>8.4f}"
                f"  {cpk_s:>6}  {s.compliance_rate:>10.1f}%"
            )

    # Insights
    if output.analytical_summary.insights:
        print()
        print(_separator())
        print("  ANALYTICAL INSIGHTS")
        print(_separator("-"))
        for line in output.analytical_summary.insights.splitlines():
            print(f"  {line}")

    # Failures
    if output.analytical_summary.critical_failures:
        print()
        print(_separator())
        print(f"  CRITICAL FAILURES ({len(output.analytical_summary.critical_failures)})")
        print(_separator("-"))
        for f in output.analytical_summary.critical_failures[:20]:
            print(f"  > {f}")

    # Plots
    if output.analytical_summary.plot_paths:
        print()
        print(_separator())
        print("  GENERATED PLOTS")
        print(_separator("-"))
        for p in output.analytical_summary.plot_paths:
            print(f"  [PLOT] {p}")

    print()
    print(_separator("="))
    print("  Pipeline complete.")
    print(_separator("="))
    print()


# -- Main -------------------------------------------------------------------

def main() -> None:
    _print_header()

    if len(sys.argv) < 2:
        print("Usage : python main.py <path_to_pdf> [optional_query]")
        print("Example: python main.py data/pqr_report.pdf")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        logger.error("File not found: %s", pdf_path)
        sys.exit(1)

    query = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_QUERY

    pipeline = PharmaCompliancePipeline()
    output = pipeline.run(str(pdf_path), query)
    _print_results(output)


if __name__ == "__main__":
    main()
