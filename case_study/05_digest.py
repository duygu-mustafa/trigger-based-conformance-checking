"""Assemble every case-study number into one Markdown digest.

Reads the JSON/CSV artifacts written by steps 01-04 and renders
case_study/RESULTS_DIGEST.md: short tables plus "numbers for prose" bullets that can
be quoted directly in the results section, and an index of the generated figures.

Usage:
    python case_study/05_digest.py
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from config import CASE_STUDY_DIR, FIG_DIR, OUT_DIR

DIGEST = CASE_STUDY_DIR / "RESULTS_DIGEST.md"

FIGURE_CAPTIONS = {
    "fig_activity_frequency": "Top-20 activities by event count; model activities highlighted.",
    "fig_model_activity_frequency": "Event counts of the 24 Declare-model activities.",
    "fig_events_per_stay": "Raw events per stay vs. model-activity events per stay.",
    "fig_episodes_per_stay": "Episodes per stay and episode-duration distribution.",
    "fig_outcome_distribution": "Outcome composition by episode position within a stay.",
    "fig_violation_rates": "Violation rate among activations, split by episode outcome.",
    "fig_activation_coverage": "Violated / satisfied / vacuous share per constraint.",
    "fig_forest_or": "Odds ratios with 95% CI per constraint (activations-only encoding).",
    "fig_vacuous_mode_comparison": "OR under activations-only vs. pooled-vacuous encoding.",
    "fig_mixed_outcomes": "Outcome agreement within a stay, by number of episodes.",
    "fig_ablation_masking": "Stays flagged violated at episode level vs. trace level.",
    "fig_ablation_activations": "Activation count per constraint, episode level vs. trace level.",
}


def load_json(name: str) -> dict:
    path = OUT_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_csv(name: str) -> pd.DataFrame:
    path = OUT_DIR / name
    return pd.read_csv(path) if path.exists() else pd.DataFrame()


def n(value, digits: int = 0) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    if digits == 0:
        return f"{value:,.0f}"
    return f"{value:,.{digits}f}"


def pct(value, digits: int = 1) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "n/a"
    return f"{100 * value:.{digits}f}%"


def md_table(df: pd.DataFrame, columns: dict[str, str], floatfmt: str = "{:.3f}") -> str:
    if df.empty:
        return "_(no data)_\n"
    sub = df[list(columns)].rename(columns=columns).copy()
    for col in sub.columns:
        if pd.api.types.is_float_dtype(sub[col]):
            values = sub[col].dropna()
            integral = bool(len(values)) and bool((values == values.round()).all())
            if integral:
                sub[col] = sub[col].map(lambda v: "" if pd.isna(v) else f"{v:,.0f}")
            else:
                sub[col] = sub[col].map(
                    lambda v: "" if pd.isna(v) else floatfmt.format(v)
                )
        elif pd.api.types.is_integer_dtype(sub[col]):
            sub[col] = sub[col].map(lambda v: f"{v:,}")
    header = "| " + " | ".join(sub.columns) + " |"
    sep = "| " + " | ".join("---" for _ in sub.columns) + " |"
    body = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in sub.values)
    return f"{header}\n{sep}\n{body}\n"


def section_event_log(parts: list[str]) -> None:
    ov = load_json("log_overview.json")
    if not ov:
        parts.append("## 1. Event log\n\n_(run 01_event_log_stats.py)_\n")
        return
    acts = load_csv("activity_frequency.csv")
    model_acts = load_csv("activity_frequency_model_only.csv")
    src = load_csv("source_table_distribution.csv")
    q = load_csv("events_per_stay_quantiles.csv").set_index("metric")

    parts.append("## 1. Event log\n")
    parts.append(
        "Cohort-restricted view of `data/final/icu_event_log_full.parquet`: only the "
        "stays that also appear in the conformance results, so log and conformance "
        "statistics describe the same population.\n"
    )
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(ov['n_events'])} events across {n(ov['n_stays'])} ICU stays "
        f"({n(ov['n_patients'])} distinct patients); one case = one ICU stay.\n"
        f"- {n(ov['n_distinct_activities'])} distinct activity labels drawn from "
        f"{n(ov['n_distinct_itemids'])} MIMIC-IV item ids across "
        f"{n(ov['n_source_tables'])} source tables.\n"
        f"- {n(ov['n_model_activity_events'])} events ({pct(ov['model_activity_share'])}) "
        f"carry one of the {n(ov['n_model_activities_defined'])} activity labels the "
        f"Declare models reason over; the remainder is clinical context.\n"
        f"- All {n(ov['n_model_activities_defined'])} model activities occur in the log "
        f"({'none missing' if not ov.get('model_activities_never_observed') else 'missing: ' + ', '.join(ov['model_activities_never_observed'])}).\n"
        f"- Timestamps span {ov['first_event']} to {ov['last_event']} "
        f"({n(ov['span_years'], 1)} years of *shifted* dates — MIMIC-IV date-shifts each "
        f"patient, so this is not a real observation window and should not be reported "
        f"as a study period).\n"
    )
    for metric, label in [
        ("events_per_stay", "Events per stay"),
        ("model_activity_events_per_stay", "Model-activity events per stay"),
        ("distinct_activities_per_stay", "Distinct activities per stay"),
        ("observed_stay_span_hours", "Observed stay span (h)"),
    ]:
        if metric in q.index:
            r = q.loc[metric]
            parts.append(
                f"- {label}: median {n(r['median'], 1)} "
                f"(IQR {n(r['q1'], 1)}–{n(r['q3'], 1)}, mean {n(r['mean'], 1)}, "
                f"max {n(r['max'], 1)}).\n"
            )
    parts.append("\n**Source tables**\n\n")
    parts.append(
        md_table(
            src.head(10),
            {"source_table": "Source table", "n_events": "Events", "share": "Share",
             "n_itemids": "Item ids"},
        )
    )
    parts.append("\n**Model activities by frequency**\n\n")
    parts.append(
        md_table(
            model_acts.sort_values("n_events", ascending=False),
            {"activity": "Activity", "n_events": "Events",
             "n_stays_with_activity": "Stays", "stay_coverage": "Stay coverage",
             "median_per_stay": "Median per stay"},
        )
    )
    parts.append("\n**Most frequent activities overall (top 10)**\n\n")
    parts.append(
        md_table(
            acts.head(10),
            {"activity": "Activity", "n_events": "Events", "share": "Share",
             "is_model_activity": "Model activity"},
        )
    )


def section_episodes(parts: list[str]) -> None:
    ov = load_json("episode_overview.json")
    if not ov:
        parts.append("\n## 2. Episodes\n\n_(run 02_episode_stats.py)_\n")
        return
    per_stay = load_csv("episodes_per_stay.csv")
    dur = load_csv("episode_durations.csv").set_index("metric")
    outcome = load_csv("outcome_distribution.csv")
    viol = load_csv("violations_per_episode.csv").set_index("metric")

    parts.append("\n## 2. Episodes and segmentation\n")
    parts.append(
        "Stays are split into episodes bounded by `InvasiveVentilationStarted`; "
        "conformance is evaluated per episode.\n"
    )
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(ov['n_episodes'])} episodes derived from {n(ov['n_stays'])} stays "
        f"(mean {n(ov['episodes_per_stay_mean'], 2)} episodes/stay, median "
        f"{n(ov['episodes_per_stay_median'])}, max {n(ov['episodes_per_stay_max'])}).\n"
        f"- {n(ov['n_stays_single_episode'])} stays ({pct(ov['share_stays_single_episode'])}) "
        f"produce exactly one episode; the remainder are re-ventilated at least once.\n"
        f"- {n(ov['n_episodes_with_sbt'])} episodes ({pct(ov['share_episodes_with_sbt'])}) "
        f"contain an SBT attempt and enter the statistical analysis; "
        f"{n(ov['n_stays_with_sbt'])} stays contribute at least one such episode.\n"
        f"- Outcomes among evaluable episodes: {n(ov['n_episodes_success'])} success, "
        f"{n(ov['n_episodes_failure'])} failure "
        f"(failure rate {pct(ov['failure_rate_evaluable'])}); "
        f"{n(ov['n_right_censored_success'])} of the successes are right-censored "
        f"(the stay ended while the patient was still off invasive ventilation).\n"
        f"- Inter-episode rules lose {pct(ov['share_censored_for_inter_episode'])} of "
        f"episodes to censoring: only {n(ov['n_episodes_with_next_outcome'])} episodes "
        f"have a subsequent episode with an evaluable outcome.\n"
    )
    for metric, label in [
        ("episode_duration_hours", "Episode duration (h)"),
        ("ventilation_duration_hours", "Invasive ventilation duration (h)"),
        ("sbt_observation_window_hours",
         "SBT outcome-observation window (h; capped at 48 h, ends with the episode on "
         "failure — not the duration of the breathing trial)"),
    ]:
        if metric in dur.index:
            r = dur.loc[metric]
            parts.append(
                f"- {label}: median {n(r['median'], 1)} "
                f"(IQR {n(r['q1'], 1)}–{n(r['q3'], 1)}, p95 {n(r['p95'], 1)}).\n"
            )
    if "mandatory_violations_per_episode" in viol.index:
        r = viol.loc["mandatory_violations_per_episode"]
        parts.append(
            f"- Mandatory violations per episode: median {n(r['median'], 1)} "
            f"(mean {n(r['mean'], 2)}, IQR {n(r['q1'], 1)}–{n(r['q3'], 1)}, "
            f"max {n(r['max'])}).\n"
        )
    parts.append("\n**Episodes per stay**\n\n")
    parts.append(
        md_table(
            per_stay.head(8),
            {"episodes_in_stay": "Episodes in stay", "n_stays": "Stays",
             "share_of_stays": "Share of stays"},
        )
    )
    parts.append("\n**Outcome distribution**\n\n")
    parts.append(
        md_table(
            outcome,
            {"outcome_class": "Outcome", "n_episodes": "Episodes",
             "share_of_episodes": "Share of all episodes",
             "share_of_sbt_episodes": "Share of SBT episodes"},
        )
    )


def section_mixed_outcomes(parts: list[str]) -> None:
    ov = load_json("mixed_outcomes.json")
    if not ov:
        parts.append(
            "\n## 2b. Mixed outcomes within a stay\n\n_(run 06_mixed_outcomes.py)_\n"
        )
        return
    by_count = load_csv("mixed_outcomes_by_episode_count.csv")

    parts.append("\n## 2b. Mixed outcomes within a stay\n")
    parts.append(
        "A per-stay (trace-global) verdict has to assign one outcome label to the whole "
        "stay. This section quantifies how often that label would necessarily be wrong "
        "for part of the stay: stays containing both a failed and a successful "
        "breathing trial.\n"
    )
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(ov['n_mixed_outcome_stays'])} of {n(ov['n_stays_with_two_or_more_evaluable'])} "
        f"stays with two or more evaluable episodes have mixed outcomes "
        f"({pct(ov['mixed_share_of_two_or_more_evaluable'])}) — "
        f"{pct(ov['mixed_share_of_multi_episode'])} of all "
        f"{n(ov['n_multi_episode_stays'])} multi-episode stays, "
        f"{pct(ov['mixed_share_of_all_stays'])} of the whole {n(ov['n_stays'])}-stay cohort.\n"
        f"- In {pct(ov['mixed_share_of_two_or_more_evaluable'])} of multi-outcome stays a "
        f"global verdict would assign one label to episodes whose true outcomes disagree.\n"
        f"- Even collapsing each mixed stay to its majority outcome (the best case for a "
        f"trace-global label) mislabels {n(ov['n_episodes_mislabelled_by_majority_collapse'])} "
        f"episodes — {pct(ov['share_episodes_mislabelled_within_mixed_stays'])} of the "
        f"episodes inside mixed stays, {pct(ov['share_all_evaluable_episodes_mislabelled'])} "
        f"of all evaluable episodes in the cohort.\n"
        f"- Mixed stays contain a median of {n(ov['failures_per_mixed_stay_median'])} "
        f"failed trials (mean {n(ov['failures_per_mixed_stay_mean'], 2)}).\n"
    )
    parts.append("\n**Outcome agreement by episode count**\n\n")
    parts.append(
        md_table(
            by_count,
            {"episodes_in_stay": "Episodes in stay", "n_stays": "Stays",
             "n_mixed": "Mixed-outcome stays", "mixed_share": "Mixed share"},
        )
    )


def section_ablation(parts: list[str]) -> None:
    ov = load_json("ablation_overview.json")
    if not ov:
        parts.append(
            "\n## 2c. What segmentation buys (trace-global ablation)\n\n"
            "_(run `bash case_study/run_ablation.sh` to produce this section)_\n"
        )
        return
    by_c = load_csv("ablation_by_constraint.csv")
    comparable = by_c[~by_c["not_comparable"]] if "not_comparable" in by_c.columns else by_c

    parts.append("\n## 2c. What segmentation buys (trace-global ablation)\n")
    parts.append(
        "Same clinical model, same stays, evaluated a second time with segmentation "
        "disabled (`main.py --no-segmentation`): one evaluation trace per stay "
        "instead of one per trigger episode. Comparing the two verdicts on the same "
        f"{n(ov['n_stays_compared'])} multi-episode stays isolates what episode-local "
        "evaluation adds, holding the checker, the model, and the population fixed. "
        "This ablation covers the multi-episode subpopulation only — it shows where "
        "segmentation *can* matter, not an average over the whole cohort.\n"
    )
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(ov['total_violations_episode_level'])} stay-level violations at episode "
        f"level collapse to {n(ov['total_violations_trace_level'])} at trace level "
        f"across {n(ov['n_constraints'] - ov['n_constraints_not_comparable'])} comparable "
        f"constraints ({n(ov['n_constraints_not_comparable'])} excluded as not comparable "
        f"— see below).\n"
        f"- {n(ov['total_masked_stays'])} stays are flagged violated at episode level but "
        f"not at trace level: an overall masking rate of "
        f"{pct(ov['overall_masking_rate'])} — a violation in one trial discharged or "
        f"hidden once all trials are pooled into a single trace.\n"
        f"- {n(ov['n_stays_any_constraint_disagrees'])} of {n(ov['n_stays_compared'])} "
        f"stays disagree between the two levels on at least one constraint.\n"
        f"- Mean activation loss under pooling: "
        f"{pct(ov['mean_activation_loss_rate'])} across comparable constraints — "
        f"activations from separate trials merge into a single per-stay activation, "
        f"which is also why vacuity rates drop at trace level.\n"
    )
    if ov.get("not_comparable_constraints"):
        parts.append("- Excluded as not comparable: " + "; ".join(
            f"{k} ({v})" for k, v in ov["not_comparable_constraints"].items()
        ) + ".\n")
    parts.append("\n**Per constraint (comparable only, sorted by masking rate)**\n\n")
    parts.append(
        md_table(
            comparable.sort_values("masking_rate", ascending=False),
            {
                "constraint_id": "ID",
                "stays_flagged_episode_level": "Flagged, episode level",
                "stays_flagged_trace_level": "Flagged, trace level",
                "masked_stays": "Masked",
                "masking_rate": "Masking rate",
                "activation_loss_rate": "Activation loss",
                "mean_episodes_per_flagged_stay": "Mean episodes/flagged stay",
            },
            floatfmt="{:.3g}",
        )
    )
    if "not_comparable" in by_c.columns and by_c["not_comparable"].any():
        parts.append("\n**Not comparable**\n\n")
        parts.append(
            md_table(
                by_c[by_c["not_comparable"]],
                {"constraint_id": "ID", "not_comparable_reason": "Reason",
                 "stays_flagged_episode_level": "Flagged, episode level",
                 "stays_flagged_trace_level": "Flagged, trace level"},
            )
        )


def section_conformance(parts: list[str]) -> None:
    vf = load_csv("violation_frequency.csv")
    if vf.empty:
        parts.append("\n## 3. Conformance profile\n\n_(run 03_violation_frequency.py)_\n")
        return
    by_group = load_csv("violation_frequency_by_group.csv")
    check = load_json("violation_frequency_check.json")

    entangled = vf[vf["outcome_entangled"]]
    top_diff = vf.dropna(subset=["rate_diff"]).sort_values("rate_diff", ascending=False)

    parts.append("\n## 3. Conformance profile (violation frequencies)\n")
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(check.get('n_constraints'))} constraints evaluated over "
        f"{n(check.get('n_episodes'))} episodes; mean violation rate among activations "
        f"{pct(check.get('mean_violation_rate_activated'))}.\n"
        f"- Most-violated constraints (activation-conditional): "
        + ", ".join(
            f"{r.constraint_id} {pct(r.violation_rate_activated)}"
            for r in vf.nlargest(3, "violation_rate_activated").itertuples()
        )
        + ".\n"
        f"- Least-violated: "
        + ", ".join(
            f"{r.constraint_id} {pct(r.violation_rate_activated)}"
            for r in vf.nsmallest(3, "violation_rate_activated").itertuples()
        )
        + ".\n"
    )
    if not top_diff.empty:
        r = top_diff.iloc[0]
        parts.append(
            f"- Largest outcome gap: {r['constraint_id']} is violated in "
            f"{pct(r['violation_rate_failure'])} of failing vs "
            f"{pct(r['violation_rate_success'])} of succeeding episodes "
            f"(difference {pct(r['rate_diff'])}).\n"
        )
    if not entangled.empty:
        parts.append(
            f"- {len(entangled)} constraints activate in only one outcome arm "
            f"({', '.join(entangled['constraint_id'])}) — their trigger and the outcome "
            f"label are entangled, so their association estimates are degenerate and "
            f"must not be read as effects.\n"
        )
    parts.append(
        "- Vacuity varies strongly by model group: "
        + "; ".join(
            f"{r.model_group} {pct(r.vacuity_rate)}" for r in by_group.itertuples()
        )
        + ".\n"
    )
    parts.append("\n**Per constraint**\n\n")
    parts.append(
        md_table(
            vf,
            {
                "constraint_id": "ID", "model_group": "Group", "severity": "Severity",
                "outcome_used": "Outcome used", "n_activated": "Activations",
                "n_vacuous": "Vacuous", "activation_rate": "Activation rate",
                "violation_rate_activated": "Violation rate",
                "violation_rate_success": "Viol. rate (success)",
                "violation_rate_failure": "Viol. rate (failure)",
                "rate_diff": "Difference",
            },
        )
    )
    parts.append("\n**By model group**\n\n")
    parts.append(
        md_table(
            by_group,
            {"model_group": "Group", "n_constraints": "Constraints",
             "n_violated": "Violated", "n_satisfied": "Satisfied",
             "n_vacuous": "Vacuous", "violation_rate_activated": "Violation rate",
             "vacuity_rate": "Vacuity rate"},
        )
    )
    parts.append(
        "\n**Constraint labels**\n\n"
        + md_table(vf, {"constraint_id": "ID", "label": "Clinical rule",
                        "template": "Template", "outcome_scope": "Outcome scope"})
    )


def section_association(parts: list[str]) -> None:
    ov = load_json("association_overview.json")
    if not ov:
        parts.append("\n## 4. Outcome association\n\n_(run 04_outcome_association.py)_\n")
        return
    assoc = load_csv("association_activations_only.csv")
    headline = load_csv("association_headline.csv")

    parts.append("\n## 4. Outcome association\n")
    parts.append(
        "Fisher's exact test per constraint on the 2x2 table of "
        "**exposure = constraint violated** against **outcome = success**. "
        "OR < 1 means violation tracks failure (the constraint discriminates); "
        "OR > 1 means violation tracks success. Rules with "
        "`outcome_scope: next_episode` are scored against the *next* episode's outcome, "
        "which is why their sample is smaller.\n"
    )
    parts.append("**Numbers for prose**\n")
    cc = ov.get("crosscheck_vs_committed_results", {})
    parts.append(
        f"- {n(ov['n_constraints_tested'])} constraints tested; "
        f"{n(ov['n_significant_raw'])} significant at raw p < 0.05, "
        f"{n(ov['n_significant_fdr'])} after Benjamini-Hochberg FDR, "
        f"{n(ov['n_significant_bonferroni'])} after Bonferroni "
        f"(family size = {n(ov['n_constraints_tested'])}).\n"
        f"- {n(ov['n_violation_tracks_failure'])} constraints have OR < 1 "
        f"(violation tracks failure), {n(ov['n_violation_tracks_success'])} have OR > 1.\n"
        f"- Clinical-relevance classification: "
        + ", ".join(f"{k} {v}" for k, v in ov.get("relevance_counts", {}).items())
        + ".\n"
        f"- {n(ov['n_degenerate'])} estimates are degenerate (zero cell, continuity "
        f"correction, or |log OR| beyond the separation threshold) and are excluded "
        f"from the headline table.\n"
        f"- Reproduction check against the committed "
        f"`statistical_results_summary_both.csv`: **{cc.get('status', 'n/a')}** "
        f"({n(cc.get('n_rows_compared'))} rows, cells/OR/p identical).\n"
    )
    parts.append("\n**Headline findings (FDR-significant, non-degenerate, by effect size)**\n\n")
    parts.append(
        md_table(
            headline,
            {"constraint_id": "ID", "label": "Clinical rule",
             "outcome_variable": "Outcome", "n_exposed": "Violated (n)",
             "n_unexposed": "Satisfied (n)", "or": "OR", "or_ci_low": "CI low",
             "or_ci_high": "CI high", "p_fdr_bh": "p (FDR)",
             "clinical_relevance": "Relevance"},
        )
    )
    parts.append("\n**All constraints**\n\n")
    parts.append(
        md_table(
            assoc,
            {"constraint_id": "ID", "outcome_variable": "Outcome",
             "n_censored": "Censored", "a_violated_success": "a", "b_violated_failure": "b",
             "c_satisfied_success": "c", "d_satisfied_failure": "d", "or": "OR",
             "or_ci_low": "CI low", "or_ci_high": "CI high", "rr": "RR",
             "p_raw": "p (raw)", "p_fdr_bh": "p (FDR)", "significant_fdr": "Sig. FDR",
             "degenerate_estimate": "Degenerate"},
            floatfmt="{:.3g}",
        )
    )


def section_sensitivity(parts: list[str]) -> None:
    cmp = load_csv("association_comparison.csv")
    ov = load_json("association_overview.json")
    if cmp.empty:
        parts.append("\n## 5. Vacuity sensitivity\n\n_(run 04_outcome_association.py)_\n")
        return
    parts.append("\n## 5. Sensitivity to vacuous-satisfaction handling\n")
    parts.append(
        "Two encodings of the exposure variable: *activations-only* (vacuous episodes "
        "dropped, the primary analysis) and *pooled* (vacuous counted as satisfied). "
        "Pooling makes exposure partly a proxy for whether the constraint triggered at "
        "all, so divergence between the two columns marks constraints whose apparent "
        "effect is driven by activation frequency rather than by conformance.\n"
    )
    parts.append("**Numbers for prose**\n")
    parts.append(
        f"- {n(ov.get('n_sign_flips_between_modes'))} constraints reverse the direction "
        f"of association between encodings"
        + (
            f" ({', '.join(ov.get('sign_flip_constraints', []))})"
            if ov.get("sign_flip_constraints")
            else ""
        )
        + f"; {n(ov.get('n_relevance_changes_between_modes'))} change relevance class.\n"
    )
    parts.append("\n")
    parts.append(
        md_table(
            cmp.sort_values("or_activations_only"),
            {"constraint_id": "ID", "outcome_variable": "Outcome",
             "n_exposed_activations_only": "Violated (act.-only)",
             "or_activations_only": "OR (act.-only)",
             "n_exposed_pooled": "Violated (pooled)", "or_pooled": "OR (pooled)",
             "sign_flip": "Direction flips", "relevance_changed": "Relevance changes"},
            floatfmt="{:.3g}",
        )
    )


def section_figures(parts: list[str]) -> None:
    parts.append("\n## 6. Figures\n\n")
    rows = []
    for name, caption in FIGURE_CAPTIONS.items():
        if (FIG_DIR / f"{name}.png").exists():
            rows.append(f"| `figures/{name}.png` / `.pdf` | {caption} |")
    parts.append("| File | Shows |\n| --- | --- |\n" + "\n".join(rows) + "\n")


def section_files(parts: list[str]) -> None:
    parts.append("\n## 7. Underlying files\n\n")
    rows = [
        f"| `out/{p.name}` | {p.stat().st_size / 1024:.0f} KB |"
        for p in sorted(OUT_DIR.glob("*"))
        if p.suffix in {".csv", ".json"}
    ]
    parts.append("| File | Size |\n| --- | --- |\n" + "\n".join(rows) + "\n")


def main() -> None:
    parts = [
        "# Case-study results digest\n",
        "SBT conformance checking on MIMIC-IV. Every number below is regenerated by the "
        "scripts in this folder (`bash case_study/run_all.sh`); do not hand-edit this "
        "file.\n",
    ]
    section_event_log(parts)
    section_episodes(parts)
    section_mixed_outcomes(parts)
    section_ablation(parts)
    section_conformance(parts)
    section_association(parts)
    section_sensitivity(parts)
    section_figures(parts)
    section_files(parts)

    text = "\n".join(parts)
    # collapse blank lines between consecutive bullets so lists render as lists
    while True:
        collapsed = re.sub(r"(?m)^(- .*)\n\n(?=- )", r"\1\n", text)
        if collapsed == text:
            break
        text = collapsed
    DIGEST.write_text(text, encoding="utf-8")
    print(f"  digest -> {DIGEST}")


if __name__ == "__main__":
    main()
