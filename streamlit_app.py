"""
Streamlit UI for Pharma Compliance Pipeline

A user-friendly web interface for uploading PDF documents, running the
multi-agent pipeline, and visualizing validation results interactively.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import streamlit as st

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from config import settings
from src.models.schemas import ValidationStatus
from src.pipeline.orchestrator import PharmaCompliancePipeline

# ── Page Configuration ─────────────────────────────────────────────────────────

st.set_page_config(
    page_title="Pharma Compliance Pipeline",
    page_icon="💊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1E40AF;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #6B7280;
        margin-bottom: 2rem;
    }
    .metric-card {
        background-color: #F3F4F6;
        padding: 1.5rem;
        border-radius: 0.5rem;
        border-left: 4px solid #3B82F6;
    }
    .status-pass {
        color: #10B981;
        font-weight: 600;
    }
    .status-fail {
        color: #EF4444;
        font-weight: 600;
    }
    .status-warning {
        color: #F59E0B;
        font-weight: 600;
    }
    .status-na {
        color: #6B7280;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Default Query ──────────────────────────────────────────────────────────────

DEFAULT_QUERY = (
    "Extract all tables containing numerical data related to Environmental Monitoring, "
    "Purified Water System, Batch Manufacturing Formula, and Product Quality parameters. "
    "Validate the extracted values against predefined compliance ranges and provide a "
    "statistical summary with process capability analysis."
)

# ── Helper Functions ───────────────────────────────────────────────────────────


def format_status(status: ValidationStatus) -> str:
    """Return HTML-formatted status badge."""
    if status == ValidationStatus.PASS:
        return '<span class="status-pass">✓ PASS</span>'
    elif status == ValidationStatus.FAIL:
        return '<span class="status-fail">✗ FAIL</span>'
    elif status == ValidationStatus.WARNING:
        return '<span class="status-warning">⚠ WARNING</span>'
    else:
        return '<span class="status-na">· N/A</span>'


def display_metrics(output):
    """Display summary metrics in cards."""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            label="Total Records",
            value=output.total_records,
            delta=None,
        )

    with col2:
        st.metric(
            label="PASS",
            value=output.pass_count,
            delta=f"{output.overall_pass_rate}%",
            delta_color="normal",
        )

    with col3:
        st.metric(
            label="FAIL",
            value=output.fail_count,
            delta=f"-{100 - output.overall_pass_rate:.1f}%",
            delta_color="inverse",
        )

    with col4:
        compliance_rate = output.analytical_summary.overall_compliance_rate
        st.metric(
            label="Compliance Rate",
            value=f"{compliance_rate:.1f}%",
            delta="Within limits" if compliance_rate > 90 else "Below target",
            delta_color="normal" if compliance_rate > 90 else "inverse",
        )


def display_validation_table(validation_report):
    """Display validation results in a sortable table."""
    st.subheader("📋 Detailed Validation Results")

    # Filter controls
    col1, col2 = st.columns([1, 3])
    with col1:
        status_filter = st.multiselect(
            "Filter by Status",
            options=["PASS", "FAIL", "WARNING", "N/A"],
            default=["PASS", "FAIL", "WARNING", "N/A"],
        )

    # Build table data
    table_data = []
    for r in validation_report:
        if r.validation_status.value in status_filter:
            table_data.append(
                {
                    "Status": r.validation_status.value,
                    "Parameter": r.parameter,
                    "Value": r.extracted_value,
                    "Unit": r.unit,
                    "Compliance Range": r.compliance_range,
                    "RAG Verified": "✓" if r.rag_verified else "✗",
                    "Deviation": f"{r.deviation:.3f}" if r.deviation is not None else "-",
                }
            )

    if table_data:
        st.dataframe(table_data, use_container_width=True, height=400)
    else:
        st.info("No records match the selected filters.")


def display_statistics(analytical_summary):
    """Display statistical summaries."""
    st.subheader("📊 Statistical Analysis")

    if not analytical_summary.statistical_summaries:
        st.warning("No statistical summaries available.")
        return

    for summary in analytical_summary.statistical_summaries:
        with st.expander(f"📌 {summary.parameter} ({summary.section})"):
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("Count", summary.count)
                st.metric("Mean", f"{summary.mean:.4f}")
                st.metric("Median", f"{summary.median:.4f}")

            with col2:
                st.metric("Std Dev", f"{summary.std_dev:.4f}")
                st.metric("Min", f"{summary.min_value:.4f}")
                st.metric("Max", f"{summary.max_value:.4f}")

            with col3:
                cpk_value = f"{summary.cpk:.3f}" if summary.cpk is not None else "N/A"
                st.metric("Cpk", cpk_value)
                st.metric("Compliance Rate", f"{summary.compliance_rate:.1f}%")

                if summary.trend:
                    st.info(f"Trend: {summary.trend}")


def display_plots(plot_paths):
    """Display generated plots."""
    st.subheader("📈 Visualization")

    if not plot_paths:
        st.warning("No plots generated.")
        return

    cols = st.columns(len(plot_paths))
    for i, plot_path in enumerate(plot_paths):
        with cols[i]:
            if Path(plot_path).exists():
                st.image(str(plot_path), use_container_width=True)
                st.caption(Path(plot_path).stem.replace("_", " ").title())
            else:
                st.error(f"Plot not found: {plot_path}")


def display_insights(analytical_summary):
    """Display AI-generated insights."""
    st.subheader("🔍 Analytical Insights")

    if analytical_summary.insights:
        st.info(analytical_summary.insights)
    else:
        st.warning("No insights available.")

    if analytical_summary.critical_failures:
        st.error("**Critical Failures Detected:**")
        for failure in analytical_summary.critical_failures[:10]:
            st.write(f"- {failure}")


# ── Main App ───────────────────────────────────────────────────────────────────


def main():
    # Header
    st.markdown('<div class="main-header">💊 Pharma Compliance Pipeline</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="sub-header">Multi-Agent AI System for Automated Compliance Validation</div>',
        unsafe_allow_html=True,
    )

    # Sidebar
    with st.sidebar:
        st.header("⚙️ Configuration")

        uploaded_file = st.file_uploader(
            "Upload PDF Document",
            type=["pdf"],
            help="Upload a pharmaceutical QC/PQR report in PDF format",
        )

        query = st.text_area(
            "Extraction Query",
            value=DEFAULT_QUERY,
            height=150,
            help="Describe what data to extract and validate",
        )

        run_pipeline = st.button(
            "🚀 Run Pipeline",
            type="primary",
            use_container_width=True,
            disabled=uploaded_file is None,
        )

        st.divider()

        st.subheader("📖 About")
        st.markdown(
            """
            **Architecture:**
            - **Agent 1**: Extraction Agent (Table & Data Miner)
            - **Agent 2**: Validation Agent (Compliance Validator)
            - **Agent 3**: Analytical Agent (Statistical Analyst)

            **Tech Stack:**
            - Claude Opus 4.7 (LLM)
            - ChromaDB (Vector Store)
            - Sentence Transformers (Embeddings)
            - Matplotlib & Seaborn (Visualization)
            """
        )

        st.divider()
        st.caption(f"Model: {settings.llm_model}")
        st.caption(f"Embedding: {settings.embedding_model}")

    # Main content
    if uploaded_file is None:
        st.info("👈 Upload a PDF document from the sidebar to get started.")
        st.image(
            "https://via.placeholder.com/800x400/1E40AF/FFFFFF?text=Upload+PDF+to+Start",
            use_container_width=True,
        )
        return

    if run_pipeline:
        # Save uploaded file temporarily
        temp_pdf_path = settings.outputs_dir / uploaded_file.name
        with open(temp_pdf_path, "wb") as f:
            f.write(uploaded_file.getbuffer())

        st.success(f"✅ Uploaded: {uploaded_file.name}")

        # Run pipeline with progress indicator
        with st.spinner("🔄 Processing document... This may take 1-2 minutes."):
            try:
                pipeline = PharmaCompliancePipeline()
                output = pipeline.run(str(temp_pdf_path), query)

                st.session_state["last_output"] = output
                st.session_state["last_run"] = datetime.now()

            except Exception as e:
                st.error(f"❌ Pipeline failed: {str(e)}")
                st.exception(e)
                return

        st.success("✅ Pipeline completed successfully!")

    # Display results if available
    if "last_output" in st.session_state:
        output = st.session_state["last_output"]

        st.divider()

        # Summary metrics
        st.header("📊 Summary")
        display_metrics(output)

        st.divider()

        # Tabs for different views
        tab1, tab2, tab3, tab4 = st.tabs(
            ["📋 Validation Results", "📊 Statistics", "📈 Plots", "🔍 Insights"]
        )

        with tab1:
            display_validation_table(output.validation_report)

        with tab2:
            display_statistics(output.analytical_summary)

        with tab3:
            display_plots(output.analytical_summary.plot_paths)

        with tab4:
            display_insights(output.analytical_summary)

        st.divider()

        # Download reports
        st.subheader("💾 Download Reports")
        col1, col2 = st.columns(2)

        with col1:
            json_output = output.model_dump_json(indent=2)
            st.download_button(
                label="📄 Download JSON Report",
                data=json_output,
                file_name=f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json",
                use_container_width=True,
            )

        with col2:
            # Generate text summary
            text_summary = f"""
PHARMA COMPLIANCE PIPELINE – VALIDATION REPORT
{'=' * 80}
Document  : {output.document_path}
Processed : {output.processed_at.strftime('%Y-%m-%d %H:%M:%S')}
Query     : {output.query[:100]}...

OVERALL SUMMARY
{'-' * 80}
Total records  : {output.total_records}
PASS           : {output.pass_count}
FAIL           : {output.fail_count}
Pass rate      : {output.overall_pass_rate} %

VALIDATION RESULTS
{'-' * 80}
"""
            for r in output.validation_report[:50]:  # Limit to first 50
                text_summary += f"\n[{r.validation_status.value}] {r.parameter} = {r.extracted_value} {r.unit}"
                text_summary += f"\n  Rule: {r.compliance_range}\n"

            st.download_button(
                label="📝 Download Text Summary",
                data=text_summary,
                file_name=f"summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                use_container_width=True,
            )


if __name__ == "__main__":
    main()
