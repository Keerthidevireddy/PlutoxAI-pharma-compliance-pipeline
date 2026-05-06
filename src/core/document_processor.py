"""
Document ingestion and table extraction layer.

Uses pdfplumber for reliable table detection in pharmaceutical PDFs.
Tables and text are both chunked for downstream RAG indexing.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pdfplumber

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Data classes (no Pydantic — pure data carriers at this layer)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DocumentChunk:
    """A text chunk ready for embedding and vector-store indexing."""

    content: str
    metadata: Dict[str, Any]
    chunk_id: str


@dataclass
class ExtractedTable:
    """A table extracted from the PDF, with headers, rows, and section context."""

    section: str
    table_id: str
    headers: List[str]
    rows: List[List[str]]
    raw_text: str           # Plain-text representation for the LLM
    page_num: int
    section_heading: str = ""   # Nearest heading text above the table


# ─────────────────────────────────────────────────────────────────────────────
# Document processor
# ─────────────────────────────────────────────────────────────────────────────


class DocumentProcessor:
    """
    Loads a PDF, extracts text + tables, and produces:
      - A list of DocumentChunk objects for RAG indexing
      - A list of ExtractedTable objects for the Extraction Agent
    """

    # Regex to match section numbers like "3.1", "6.0", "7.0" etc.
    _SECTION_RE = re.compile(
        r"""
        (?:^|\n)                        # start of line
        (\d+\.\d+)                      # section number  e.g. 6.1
        \s+                             # whitespace
        (?:Review\s+of|List\s+of|       # common pharma section openers
           Summary|Evaluation|Results|
           [A-Z][a-z])                  # or any capitalised word
        """,
        re.VERBOSE | re.MULTILINE,
    )

    def __init__(self, chunk_size: int = 400, chunk_overlap: int = 60) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    # ── Public API ────────────────────────────────────────────────────────

    def load_document(
        self, pdf_path: str | Path
    ) -> Tuple[List[DocumentChunk], List[ExtractedTable]]:
        """
        Ingest a PDF document and return:
          - chunks  : for vector-store indexing
          - tables  : for the Extraction Agent
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        all_text_pages: List[str] = []
        all_tables: List[ExtractedTable] = []

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                all_text_pages.append(page_text)

                # ── table extraction ──────────────────────────────────────
                page_tables = page.extract_tables(
                    table_settings={
                        "vertical_strategy": "lines_strict",
                        "horizontal_strategy": "lines_strict",
                        "snap_tolerance": 3,
                    }
                ) or []

                # Fallback to looser strategy if no tables found
                if not page_tables:
                    page_tables = page.extract_tables() or []

                for tbl_idx, raw_table in enumerate(page_tables):
                    et = self._build_extracted_table(
                        raw_table=raw_table,
                        page_num=page_num,
                        tbl_idx=tbl_idx,
                        page_text=page_text,
                    )
                    if et is not None:
                        all_tables.append(et)

        logger.info(
            "Loaded '%s': %d pages, %d tables found",
            pdf_path.name,
            len(all_text_pages),
            len(all_tables),
        )

        # Build text chunks for RAG
        full_text = "\n\n".join(
            f"[Page {i + 1}]\n{t}" for i, t in enumerate(all_text_pages)
        )
        text_chunks = self._create_text_chunks(full_text, pdf_path.name)
        table_chunks = self._tables_to_chunks(all_tables, pdf_path.name)

        return text_chunks + table_chunks, all_tables

    # ── Private helpers ───────────────────────────────────────────────────

    def _build_extracted_table(
        self,
        raw_table: List[List[Optional[str]]],
        page_num: int,
        tbl_idx: int,
        page_text: str,
    ) -> Optional[ExtractedTable]:
        """Clean a raw pdfplumber table and wrap it in ExtractedTable."""
        if not raw_table:
            return None

        # Normalise cells
        cleaned: List[List[str]] = []
        for row in raw_table:
            clean_row = [
                str(cell).strip().replace("\n", " ") if cell is not None else ""
                for cell in row
            ]
            if any(c for c in clean_row):  # skip blank rows
                cleaned.append(clean_row)

        if len(cleaned) < 2:  # need at least header + 1 data row
            return None

        headers = cleaned[0]
        rows = cleaned[1:]

        # Plain-text representation
        col_widths = [
            max(len(str(r[i])) if i < len(r) else 0 for r in cleaned)
            for i in range(len(headers))
        ]
        sep = "-+-".join("-" * w for w in col_widths)

        def fmt_row(row: List[str]) -> str:
            return " | ".join(
                str(row[i]).ljust(col_widths[i]) if i < len(row) else " " * col_widths[i]
                for i in range(len(headers))
            )

        raw_text = fmt_row(headers) + "\n" + sep + "\n"
        raw_text += "\n".join(fmt_row(r) for r in rows)

        section = self._detect_section_number(page_text)
        heading = self._detect_section_heading(page_text)

        return ExtractedTable(
            section=section,
            table_id=f"Table_P{page_num}_{tbl_idx + 1}",
            headers=headers,
            rows=rows,
            raw_text=raw_text,
            page_num=page_num,
            section_heading=heading,
        )

    def _detect_section_number(self, text: str) -> str:
        """Extract the most recent section number from page text."""
        matches = self._SECTION_RE.findall(text)
        return matches[-1] if matches else "unknown"

    def _detect_section_heading(self, text: str) -> str:
        """Extract the full heading text from a section number match."""
        match = re.search(
            r"(\d+\.\d+\s+[A-Za-z][^\n]{5,80})", text, re.MULTILINE
        )
        if match:
            return match.group(1).strip()
        return ""

    def _create_text_chunks(
        self, full_text: str, source: str
    ) -> List[DocumentChunk]:
        """Sliding-window word-level chunking with overlap."""
        words = full_text.split()
        chunks: List[DocumentChunk] = []
        step = self.chunk_size - self.chunk_overlap

        for start in range(0, len(words), step):
            chunk_words = words[start : start + self.chunk_size]
            if not chunk_words:
                break
            chunk_text = " ".join(chunk_words)
            chunks.append(
                DocumentChunk(
                    content=chunk_text,
                    metadata={"source": source, "type": "text", "chunk_index": len(chunks)},
                    chunk_id=f"{source}_text_{len(chunks)}",
                )
            )

        return chunks

    def _tables_to_chunks(
        self, tables: List[ExtractedTable], source: str
    ) -> List[DocumentChunk]:
        """Convert each ExtractedTable into a DocumentChunk for RAG."""
        chunks: List[DocumentChunk] = []
        for tbl in tables:
            heading = tbl.section_heading or f"Section {tbl.section}"
            content = f"[{heading}] [{tbl.table_id}]\n{tbl.raw_text}"
            chunks.append(
                DocumentChunk(
                    content=content,
                    metadata={
                        "source": source,
                        "type": "table",
                        "table_id": tbl.table_id,
                        "section": tbl.section,
                        "page_num": tbl.page_num,
                    },
                    chunk_id=f"{source}_{tbl.table_id}",
                )
            )
        return chunks
