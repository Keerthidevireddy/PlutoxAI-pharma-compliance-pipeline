"""
Agent 3 – Analytical Agent (Data Analyst)

Responsibilities
----------------
- Receives all ValidationResult objects from Agent 2.
- Computes descriptive statistics per parameter group:
    Mean, Median, Standard Deviation, Min, Max, Cpk, Compliance Rate, Trend.
- Generates four publication-quality matplotlib/seaborn plots:
    1. Compliance overview (pie + stacked bar)
    2. Environmental monitoring run charts
    3. Purified water quality trend charts
    4. Parameter distribution histograms
- Calls Claude to produce a concise pharmacological/manufacturing insight paragraph.
- Returns an AnalyticalSummary Pydantic model.
"""

from __future__ import annotations

import logging
from typing import List, Optional

import matplotlib
matplotlib.use("Agg")  # headless / non-interactive backend

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from scipy import stats

from config import settings
from src.agents.base_agent import BaseAgent
from src.core.compliance_rules import COMPLIANCE_RULES
from src.models.schemas import (
    AnalyticalSummary,
    StatisticalSummary,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)
sns.set_theme(style="whitegrid", palette="muted", font_scale=1.0)

_PALETTE = {
    "PASS": "#27ae60",
    "FAIL": "#e74c3c",
    "WARNING": "#f39c12",
    "N/A": "#95a5a6",
}


# ─────────────────────────────────────────────────────────────────────────────
# System prompt
# ─────────────────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """
You are Agent 3 – Pharmaceutical Manufacturing Data Analyst.

You receive statistical summaries of Quality Control (QC) data from a pharma
Product Quality Review (PQR) and produce a concise analytical narrative.

Focus on:
  • Process stability assessment from Cpk values (Cpk ≥ 1.33 = capable)
  • Environmental control quality (temperature, RH, differential pressure)
  • Water system quality trending
  • Compliance rate significance and regulatory implications
  • Risk identification from statistical outliers or failing trends
  • Actionable recommendations where appropriate

Be precise, scientifically grounded, and concise (max 400 words).
""".strip()


# ─────────────────────────────────────────────────────────────────────────────
# Agent
# ─────────────────────────────────────────────────────────────────────────────


class AnalyticalAgent(BaseAgent):
    """Agent 3: Statistical analysis and visualisation of validated QC data."""

    def __init__(self) -> None:
        super().__init__(name="AnalyticalAgent", system_prompt=_SYSTEM_PROMPT)

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(self, results: List[ValidationResult]) -> AnalyticalSummary:
        """
        Full analytical pipeline:
          1. Convert results → DataFrame
          2. Compute per-parameter statistics
          3. Generate plots
          4. Generate LLM insight narrative
          5. Return AnalyticalSummary
        """
        df = self._to_dataframe(results)

        stat_summaries: List[StatisticalSummary] = []
        if not df.empty:
            numeric_df = df[df["value"].notna()].copy()
            for (section, param_base), grp in numeric_df.groupby(
                ["section_short", "param_base"]
            ):
                if len(grp) < 2:
                    continue
                s = self._compute_stats(grp["value"].values, str(param_base), str(section), grp)
                if s:
                    stat_summaries.append(s)

        # Compliance totals
        total = len(results)
        pass_n = sum(1 for r in results if r.validation_status == ValidationStatus.PASS)
        fail_n = sum(1 for r in results if r.validation_status == ValidationStatus.FAIL)
        overall_rate = round(pass_n / total * 100, 2) if total else 0.0

        critical_failures = [
            (
                f"{r.parameter} [{r.table_name_id}] "
                f"Value={r.extracted_value} {r.unit} | "
                f"Rule: {r.compliance_range} | "
                f"Deviation: {r.deviation}"
            )
            for r in results
            if r.validation_status == ValidationStatus.FAIL
        ]

        # Plots
        plot_paths = self._generate_plots(df, results) if not df.empty else []

        # LLM insights
        insights = self._generate_insights(stat_summaries, critical_failures, overall_rate)

        return AnalyticalSummary(
            statistical_summaries=stat_summaries,
            overall_compliance_rate=overall_rate,
            critical_failures=critical_failures[:30],
            insights=insights,
            plot_paths=plot_paths,
        )

    # ── DataFrame builder ─────────────────────────────────────────────────

    def _to_dataframe(self, results: List[ValidationResult]) -> pd.DataFrame:
        records = []
        for r in results:
            try:
                val: Optional[float] = float(r.extracted_value)  # type: ignore[arg-type]
            except (ValueError, TypeError):
                val = None

            # Derive base parameter name (strip _Min / _Max suffix)
            pb = (
                r.parameter
                .replace("_Min", "").replace("_Max", "")
                .replace("_min", "").replace("_max", "")
                .strip()
            )

            records.append(
                {
                    "section_heading": r.section_heading,
                    "section_short": r.section_heading[:40],
                    "parameter": r.parameter,
                    "param_base": pb,
                    "value": val,
                    "unit": r.unit,
                    "status": r.validation_status.value,
                    "table_id": r.table_name_id,
                }
            )
        return pd.DataFrame(records)

    # ── Statistics ────────────────────────────────────────────────────────

    def _compute_stats(
        self,
        values: np.ndarray,
        parameter: str,
        section: str,
        grp: pd.DataFrame,
    ) -> Optional[StatisticalSummary]:
        try:
            n = len(values)
            mean = float(np.mean(values))
            median = float(np.median(values))
            std = float(np.std(values, ddof=1)) if n > 1 else 0.0
            mn = float(np.min(values))
            mx = float(np.max(values))
            compliance_rate = float(
                grp["status"].eq("PASS").sum() / len(grp) * 100
            )
            cpk = self._cpk(values, parameter)
            trend = self._trend(values)

            return StatisticalSummary(
                parameter=parameter,
                section=section,
                count=n,
                mean=round(mean, 4),
                median=round(median, 4),
                std_dev=round(std, 4),
                min_value=round(mn, 4),
                max_value=round(mx, 4),
                cpk=cpk,
                compliance_rate=round(compliance_rate, 2),
                trend=trend,
            )
        except Exception as exc:
            logger.warning("Stats failed for '%s': %s", parameter, exc)
            return None

    def _cpk(self, values: np.ndarray, parameter: str) -> Optional[float]:
        """
        Process Capability Index.
        Cpk = min( (USL - mean) / 3σ,  (mean - LSL) / 3σ )
        Returns None when limits are unavailable or σ = 0.
        """
        usl = lsl = None
        p = parameter.lower()
        for cat_rules in COMPLIANCE_RULES.values():
            for rule in cat_rules:
                if (
                    rule.parameter.lower() in p
                    or p in rule.parameter.lower()
                ):
                    usl = rule.max_value
                    lsl = rule.min_value
                    break

        if usl is None and lsl is None:
            return None
        if len(values) < 2:
            return None

        mean = np.mean(values)
        std = np.std(values, ddof=1)
        if std == 0:
            return None

        cpu = (usl - mean) / (3 * std) if usl is not None else float("inf")
        cpl = (mean - lsl) / (3 * std) if lsl is not None else float("inf")
        return round(min(cpu, cpl), 3)

    def _trend(self, values: np.ndarray) -> str:
        """Describe linear trend using OLS regression."""
        if len(values) < 3:
            return "insufficient data"
        x = np.arange(len(values), dtype=float)
        slope, _, r, p, _ = stats.linregress(x, values)
        r2 = r ** 2
        if p > 0.05:
            return "stable (no significant trend)"
        direction = "increasing" if slope > 0 else "decreasing"
        strength = "strong" if r2 > 0.7 else "moderate" if r2 > 0.4 else "weak"
        return f"{strength} {direction} trend (R²={r2:.2f}, p={p:.3f})"

    # ── Plot generation ───────────────────────────────────────────────────

    def _generate_plots(
        self, df: pd.DataFrame, results: List[ValidationResult]
    ) -> List[str]:
        paths: List[str] = []

        p = self._plot_compliance_overview(results)
        if p:
            paths.append(p)

        p = self._plot_env_run_charts(df)
        if p:
            paths.append(p)

        p = self._plot_water_trends(df)
        if p:
            paths.append(p)

        p = self._plot_distributions(df)
        if p:
            paths.append(p)

        return paths

    # ── Plot 1: Compliance overview ───────────────────────────────────────

    def _plot_compliance_overview(self, results: List[ValidationResult]) -> Optional[str]:
        try:
            status_counts: dict[str, int] = {}
            for r in results:
                k = r.validation_status.value
                status_counts[k] = status_counts.get(k, 0) + 1

            fig, axes = plt.subplots(1, 2, figsize=(14, 6))

            # Pie
            labels = list(status_counts.keys())
            sizes = list(status_counts.values())
            colors = [_PALETTE.get(l, "#bdc3c7") for l in labels]
            wedge_props = {"edgecolor": "white", "linewidth": 1.5}
            axes[0].pie(
                sizes, labels=labels, colors=colors, autopct="%1.1f%%",
                startangle=90, wedgeprops=wedge_props, pctdistance=0.82,
            )
            axes[0].set_title(
                "Overall Compliance Distribution", fontsize=13, fontweight="bold"
            )

            # Stacked bar by section
            section_data: dict[str, dict[str, int]] = {}
            for r in results:
                sec = r.section_heading[:35]
                section_data.setdefault(sec, {k: 0 for k in _PALETTE})
                section_data[sec][r.validation_status.value] += 1

            secs = list(section_data.keys())
            x = np.arange(len(secs))
            bottom = np.zeros(len(secs))
            for status_key, color in _PALETTE.items():
                vals = [section_data[s].get(status_key, 0) for s in secs]
                axes[1].bar(x, vals, bottom=bottom, label=status_key, color=color, alpha=0.85)
                bottom += np.array(vals, dtype=float)

            axes[1].set_xticks(x)
            axes[1].set_xticklabels(
                [s[:22] for s in secs], rotation=40, ha="right", fontsize=8
            )
            axes[1].set_ylabel("Record count")
            axes[1].set_title("Compliance by Section", fontsize=13, fontweight="bold")
            axes[1].legend(loc="upper right")

            plt.tight_layout()
            path = str(settings.plots_dir / "01_compliance_overview.png")
            fig.savefig(path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            return path
        except Exception as exc:
            logger.error("Plot 01 failed: %s", exc)
            plt.close("all")
            return None

    # ── Plot 2: Environmental run charts ──────────────────────────────────

    def _plot_env_run_charts(self, df: pd.DataFrame) -> Optional[str]:
        try:
            env_kw = "temperature|humidity|pressure|differential"
            env_df = df[
                df["param_base"].str.contains(env_kw, case=False, na=False)
                & df["value"].notna()
            ]
            if env_df.empty:
                return None

            param_configs = [
                ("Temperature", "°C", 25.0, None, "#2980b9"),
                ("Relative Humidity", "% RH", 60.0, None, "#8e44ad"),
                ("Differential Pressure", "mm of Wc", None, 1.5, "#d35400"),
            ]

            fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=False)

            for ax, (param, unit, usl, lsl, color) in zip(axes, param_configs):
                sub = env_df[
                    env_df["param_base"].str.contains(param.split()[0], case=False, na=False)
                ]
                if sub.empty:
                    ax.text(0.5, 0.5, f"No {param} data", ha="center", transform=ax.transAxes)
                    ax.set_title(f"{param} ({unit})")
                    continue

                vals = sub["value"].values
                x = np.arange(len(vals))

                ax.plot(x, vals, "o-", color=color, lw=1.8, ms=5, label="Observed", zorder=3)
                ax.fill_between(x, vals, alpha=0.12, color=color)
                mean_v = np.mean(vals)
                ax.axhline(mean_v, color="navy", ls=":", lw=1.4, label=f"Mean={mean_v:.2f}")

                if usl is not None:
                    ax.axhline(usl, color="red", ls="--", lw=1.8, label=f"Limit NMT {usl}")
                if lsl is not None:
                    ax.axhline(lsl, color="red", ls="--", lw=1.8, label=f"Limit NLT {lsl}")

                ax.set_title(f"{param} Run Chart ({unit})", fontsize=11, fontweight="bold")
                ax.set_ylabel(f"{unit}")
                ax.legend(fontsize=8, loc="upper right")
                ax.set_xlabel("Measurement index")

            plt.suptitle(
                "Environmental Monitoring – Run Charts", fontsize=13, fontweight="bold", y=1.01
            )
            plt.tight_layout()
            path = str(settings.plots_dir / "02_env_run_charts.png")
            fig.savefig(path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            return path
        except Exception as exc:
            logger.error("Plot 02 failed: %s", exc)
            plt.close("all")
            return None

    # ── Plot 3: Purified water quality trends ─────────────────────────────

    def _plot_water_trends(self, df: pd.DataFrame) -> Optional[str]:
        try:
            water_df = df[
                df["section_heading"].str.contains(
                    r"water|microbial|purified|conductivity|pH|TOC|organic carbon",
                    case=False, na=False, regex=True,
                )
                & df["value"].notna()
            ]
            # Fall back to matching water-related parameters directly if section heading
            # detection missed the section (e.g. heading was empty or numeric only)
            if water_df.empty:
                water_df = df[
                    df["param_base"].str.contains(
                        r"microbial|cfu|pH|conductivity|organic|toc",
                        case=False, na=False, regex=True,
                    )
                    & df["value"].notna()
                ]
            if water_df.empty:
                return None

            params_conf = [
                ("Microbial", "cfu/ml", 25.0, "#e74c3c"),
                ("pH", "", None, "#2980b9"),
                ("Conductivity", "µs/cm", 1.3, "#27ae60"),
                ("Organic|TOC|Carbon", "ppb", 500.0, "#8e44ad"),
            ]

            fig, axes = plt.subplots(2, 2, figsize=(14, 10))
            axes = axes.flatten()

            for ax, (kw, unit, limit, color) in zip(axes, params_conf):
                sub = water_df[
                    water_df["param_base"].str.contains(kw, case=False, na=False)
                ]
                if sub.empty:
                    ax.text(0.5, 0.5, f"No {kw} data", ha="center", transform=ax.transAxes)
                    ax.set_title(kw.split("|")[0])
                    continue

                vals = sub["value"].values
                x = np.arange(len(vals))
                ax.plot(x, vals, "o-", color=color, lw=2, ms=6, zorder=3)
                ax.fill_between(x, vals, alpha=0.15, color=color)

                if limit is not None:
                    ax.axhline(limit, color="red", ls="--", lw=2, label=f"Limit: {limit}")

                mean_v = np.mean(vals)
                ax.axhline(mean_v, color="navy", ls=":", lw=1.4, label=f"Mean: {mean_v:.3f}")

                disp = kw.split("|")[0]
                ax.set_title(
                    f"{disp} ({unit})" if unit else disp, fontsize=11, fontweight="bold"
                )
                ax.set_ylabel(unit or "value")
                ax.set_xlabel("Measurement index")
                ax.legend(fontsize=8)

            plt.suptitle(
                "Purified Water Quality – Monthly Trends", fontsize=13, fontweight="bold"
            )
            plt.tight_layout()
            path = str(settings.plots_dir / "03_water_quality_trends.png")
            fig.savefig(path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            return path
        except Exception as exc:
            logger.error("Plot 03 failed: %s", exc)
            plt.close("all")
            return None

    # ── Plot 4: Parameter distributions ───────────────────────────────────

    def _plot_distributions(self, df: pd.DataFrame) -> Optional[str]:
        try:
            num_df = df[df["value"].notna()].copy()
            if num_df.empty:
                return None

            top_params = (
                num_df.groupby("param_base")["value"].count()
                .sort_values(ascending=False)
                .head(6)
                .index.tolist()
            )
            if not top_params:
                return None

            fig, axes = plt.subplots(2, 3, figsize=(15, 10))
            axes = axes.flatten()

            for i, param in enumerate(top_params):
                vals = num_df[num_df["param_base"] == param]["value"].dropna()
                if len(vals) < 2:
                    axes[i].set_visible(False)
                    continue

                axes[i].hist(vals.values, bins=min(12, len(vals)), color="#3498db",
                             edgecolor="white", alpha=0.85, rwidth=0.9)
                axes[i].axvline(vals.mean(), color="#e74c3c", ls="--", lw=2,
                                label=f"Mean {vals.mean():.3f}")
                axes[i].axvline(vals.median(), color="#27ae60", ls=":", lw=2,
                                label=f"Median {vals.median():.3f}")
                axes[i].set_title(param[:30], fontsize=10, fontweight="bold")
                axes[i].set_xlabel("Value")
                axes[i].set_ylabel("Frequency")
                axes[i].legend(fontsize=7)

            for j in range(len(top_params), 6):
                axes[j].set_visible(False)

            plt.suptitle("Parameter Distribution Analysis", fontsize=13, fontweight="bold")
            plt.tight_layout()
            path = str(settings.plots_dir / "04_parameter_distributions.png")
            fig.savefig(path, dpi=150, bbox_inches="tight")
            plt.close(fig)
            return path
        except Exception as exc:
            logger.error("Plot 04 failed: %s", exc)
            plt.close("all")
            return None

    # ── LLM insights ──────────────────────────────────────────────────────

    def _generate_insights(
        self,
        summaries: List[StatisticalSummary],
        failures: List[str],
        compliance_rate: float,
    ) -> str:
        lines = [
            f"  {s.parameter}: n={s.count}, Mean={s.mean}, SD={s.std_dev}, "
            f"Cpk={'N/A' if s.cpk is None else s.cpk}, "
            f"Compliance={s.compliance_rate}%, Trend={s.trend}"
            for s in summaries[:12]
        ]
        stat_text = "\n".join(lines) or "  No numeric summaries available."
        fail_text = "\n".join(f"  • {f}" for f in failures[:10]) or "  None."

        prompt = (
            "Analyze the following pharmaceutical QC statistical data:\n\n"
            f"STATISTICAL SUMMARIES:\n{stat_text}\n\n"
            f"COMPLIANCE FAILURES (top 10):\n{fail_text}\n\n"
            f"OVERALL COMPLIANCE RATE: {compliance_rate:.1f}%\n\n"
            "Provide:\n"
            "1. Process stability assessment (Cpk interpretation)\n"
            "2. Environmental control quality assessment\n"
            "3. Water system quality assessment\n"
            "4. Key risks and observations\n"
            "5. Recommendations (if any)\n"
        )

        try:
            return self._call_llm(prompt, max_tokens=600)
        except Exception as exc:
            logger.warning("LLM insights generation failed: %s", exc)
            return (
                f"Statistical analysis completed. "
                f"Overall compliance rate: {compliance_rate:.1f}%. "
                f"{len(failures)} failure(s) detected."
            )
