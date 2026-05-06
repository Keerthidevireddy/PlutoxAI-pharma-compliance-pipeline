# Pharma Compliance Agentic Pipeline

An end-to-end, multi-agent Python pipeline for automated extraction, validation, and
statistical analysis of pharmaceutical compliance data from QC / PQR documents.

---

## Architecture

```
PDF Document
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 1 – Document Preparation                                 │
│                                                                 │
│  DocumentProcessor  ──► text chunks + ExtractedTable objects   │
│  VectorStore (ChromaDB + SentenceTransformers)  ──► RAG index  │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 2 – Agent 1: ExtractionAgent (Table & Data Miner)       │
│                                                                 │
│  • Receives ExtractedTable objects from Stage 1                │
│  • Calls Claude with EXTRACTION_GUIDANCE system prompt         │
│  • Produces List[ExtractedDataPoint] (Pydantic v2 models)      │
│  • Rule-based numeric fallback if LLM call fails               │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 3 – Agent 2: ValidationAgent (Compliance Validator)     │
│                                                                 │
│  Three-tier validation strategy:                               │
│   1. Deterministic rule engine  →  embedded knowledge base     │
│      NMT / NLT checks applied in pure Python (no LLM calls)   │
│   2. RAG cross-check            →  VectorStore.verify_value()  │
│      Confirms values appear in the raw source document         │
│   3. LLM fallback               →  for unmapped parameters     │
│  Produces List[ValidationResult] with PASS/FAIL/WARNING/N/A   │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 4 – Agent 3: AnalyticalAgent (Data Analyst)            │
│                                                                 │
│  • Descriptive statistics: Mean, Median, SD, Min, Max          │
│  • Cpk (Process Capability Index)                              │
│  • Linear-regression trend detection                           │
│  • 4 matplotlib/seaborn plots (see Outputs section)           │
│  • LLM-generated pharmacological insight narrative             │
│  Produces AnalyticalSummary                                    │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│  Stage 5 – Output Generation                                    │
│                                                                 │
│  outputs/reports/validation_report_<timestamp>.json            │
│  outputs/reports/summary_<timestamp>.txt                       │
│  outputs/plots/01_compliance_overview.png                      │
│  outputs/plots/02_env_run_charts.png                           │
│  outputs/plots/03_water_quality_trends.png                     │
│  outputs/plots/04_parameter_distributions.png                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Compliance Knowledge Base (Agent 2)

All rules live in `src/core/compliance_rules.py` and are injected verbatim into
Agent 2's system prompt so the LLM has full context at inference time.

| Section | Parameter | Rule |
|---------|-----------|------|
| 6.1 Environmental Monitoring | Temperature | NMT 25 °C |
| 6.1 Environmental Monitoring | Relative Humidity | NMT 60 % RH |
| 6.1 Environmental Monitoring | Differential Pressure | NLT 1.5 mm of Wc |
| 7.0 Purified Water | Microbial Count | Alert ≤ 25 cfu/ml · Action ≤ 40 cfu/ml |
| 7.0 Purified Water | pH | 5.0 – 7.0 |
| 7.0 Purified Water | Conductivity | NMT 1.3 µs/cm |
| 7.0 Purified Water | Total Organic Carbon | NMT 500 ppb |
| 3.2 Batch Formula | Amlodipine Besylate | 13.868 mg/tablet (Nil overage) |
| 3.2 Batch Formula | Olmesartan Medoxomil | 40.000 mg/tablet (Nil overage) |

---

## Project Structure

```
pharma_compliance_pipeline/
├── main.py                         ← CLI entry point
├── config.py                       ← Central settings (pydantic-settings)
├── requirements.txt
├── .env.example                    ← Copy to .env and add API key
│
├── src/
│   ├── models/
│   │   └── schemas.py              ← Pydantic v2 data models (all inter-agent contracts)
│   │
│   ├── core/
│   │   ├── compliance_rules.py     ← Embedded knowledge base + extraction guidance
│   │   ├── document_processor.py   ← PDF ingestion, table extraction, chunking
│   │   └── vector_store.py         ← ChromaDB RAG wrapper
│   │
│   ├── agents/
│   │   ├── base_agent.py           ← Anthropic client, retry logic, JSON parsing
│   │   ├── extraction_agent.py     ← Agent 1
│   │   ├── validation_agent.py     ← Agent 2
│   │   └── analytical_agent.py     ← Agent 3
│   │
│   └── pipeline/
│       └── orchestrator.py         ← Wires all stages together; saves reports
│
└── outputs/
    ├── reports/                    ← JSON + TXT reports (auto-created)
    ├── plots/                      ← PNG visualisations (auto-created)
    ├── chroma_db/                  ← Persistent ChromaDB (auto-created)
    └── pipeline.log
```

---

## Setup & Installation

### Prerequisites
- Python 3.11+
- An Anthropic API key

### 1. Clone / unzip the project

```bash
cd pharma_compliance_pipeline
```

### 2. Create a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### 5. Run the pipeline

```bash
python main.py path/to/your_document.pdf
```

Optional — pass a custom query as a second argument:

```bash
python main.py document.pdf "Extract environmental monitoring data and validate."
```

---

## Output Format

### Validation Report (`validation_report_<ts>.json`)

A JSON array where each entry follows this schema:

```json
{
  "section_heading": "6.1 Review of Temperature, Relative Humidity ...",
  "table_name_id": "Table_P2_1",
  "parameter": "Temperature_Max",
  "extracted_value": 24.1,
  "unit": "°C",
  "compliance_range": "NMT 25°C",
  "validation_status": "PASS",
  "deviation": null,
  "notes": "Row: Oct-23 | Dispensing I",
  "rag_verified": true
}
```

### Analytical Summary

```json
{
  "overall_compliance_rate": 91.3,
  "statistical_summaries": [
    {
      "parameter": "Temperature",
      "count": 26,
      "mean": 21.8,
      "median": 21.9,
      "std_dev": 1.4,
      "cpk": 0.74,
      "compliance_rate": 100.0,
      "trend": "stable (no significant trend)"
    }
  ],
  "critical_failures": ["..."],
  "insights": "...",
  "plot_paths": ["outputs/plots/01_compliance_overview.png", "..."]
}
```

---

## Evaluation Criteria Mapping

| Criterion | Weight | Implementation |
|-----------|--------|----------------|
| Complex Extraction | 35% | `ExtractionAgent` — LLM-guided + rule-based fallback |
| Agentic Design & Validation Logic | 30% | 3-tier validation: deterministic rules → RAG → LLM |
| Code Quality & Modularity | 25% | Pydantic v2 contracts; single-responsibility agents; `BaseAgent` abstraction |
| Analytical Insights (Agent 3) | 10% | 4 plots + Cpk + trend + LLM narrative |

---

## Key Design Decisions

- **Anthropic Claude** (via `anthropic` Python SDK) — deterministic `temperature=0.0` for validation LLM calls; slightly higher for the insight narrative.
- **pdfplumber** — best-in-class for table extraction from pharmaceutical PDFs (handles merged cells, strict-line and loose strategies).
- **ChromaDB + `all-MiniLM-L6-v2`** — lightweight, fully local RAG; no external service required.
- **Pydantic v2** — strict typing for all inter-agent data contracts; native `model_dump_json()` for serialisation.
- **Deterministic rule engine first** — NMT / NLT checks are applied in pure Python; the LLM is only invoked when no rule is matched, reducing cost and hallucination risk.
- **Cpk** — calculated wherever USL/LSL are available from the knowledge base, giving a process-capability dimension beyond simple pass/fail.
