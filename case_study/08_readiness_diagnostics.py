"""Why the readiness constraints are violated, and how far from the threshold.

Two questions the aggregate verdicts of step 03 cannot answer.

First, a readiness violation has several possible causes, which the checker now
records per activation: the criterion was never charted in the lookback window
(`absent`), it was charted only outside it (`stale`), the measurement event fired
but carries none of the values the condition reads (`no_payload`), a disjunctive
criterion was decided on readings only some of which are present
(`partial_payload`), or the criterion was assessed on complete readings and not
met (`unmet`). Only the last is a statement about care; the rest are statements
about documentation.

Second, an `unmet` violation carries the reading that failed the threshold, so
violations can be ordered by how far past the threshold the trial went. If
trials started just past the threshold do not fare worse than conforming ones
while grossly deviating trials do, the guideline threshold is being crossed
deliberately at the margin rather than breached indiscriminately.

Usage:
    python case_study/08_readiness_diagnostics.py
"""

from __future__ import annotations

import argparse
import json
import math
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    EPISODE_RESULTS,
    EPISODE_RESULTS_DIAG,
    OUT_DIR,
    load_constraint_meta,
    save_fig,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label, calculate_stats

# Ordered from least to most specific, so an episode whose activations disagree is
# reported under the most informative cause any of them produced.
CAUSES = ["absent", "stale", "no_payload", "partial_payload", "unmet"]
DOCUMENTATION_CAUSES = ["absent", "stale", "no_payload", "partial_payload"]

CAUSE_LABEL = {
    "absent": "never charted in window",
    "stale": "charted outside window",
    "no_payload": "event without a value",
    "partial_payload": "criterion only partly documented",
    "unmet": "assessed and not met",
}

# The reading each readiness criterion is judged on, the threshold it must clear,
# and the direction of conformance. `at_least` means the criterion is met when the
# reading is at or above the threshold; `at_most` when it is at or below. RC-DP-06 is
# absent because its criterion is a categorical bedside score with no graded reading.
CRITERION = {
    "RC-DP-01": {"item": "pao2fio2ratio", "threshold": 150.0, "direction": "at_least",
                 "unit": "PaO2/FiO2"},
    "RC-DP-02": {"item": "ph_bg", "threshold": 7.25, "direction": "at_least",
                 "unit": "arterial pH"},
    "RC-DP-03": {"item": "hemoglobin_bg", "threshold": 7.0, "direction": "at_least",
                 "unit": "Hgb (g/dL)"},
    "RC-DP-04": {"item": "223762", "threshold": 38.0, "direction": "at_most",
                 "unit": "temperature (C)"},
    "RC-DP-05": {"item": "norepinephrine_equiv", "threshold": 0.1, "direction": "at_most",
                 "unit": "NE-equivalent (mcg/kg/min)"},
    "RC-DP-07": {"item": "224686", "threshold": 0.0, "direction": "at_least",
                 "unit": "spontaneous tidal volume (mL)"},
}

# Margin analysis needs a graded reading. RC-DP-07 is thresholded at zero on a
# quantity that is either charted as positive or not at all, so its margin has only
# one violating value and no gradation to stratify.
MARGIN_CONSTRAINTS = ["RC-DP-01", "RC-DP-02", "RC-DP-03", "RC-DP-04", "RC-DP-05"]


def _results_path():
    """Prefer the run carrying failure causes; say so when it is missing."""
    if EPISODE_RESULTS_DIAG.exists():
        return EPISODE_RESULTS_DIAG
    raise SystemExit(
        f"{EPISODE_RESULTS_DIAG} not found. Regenerate it with\n"
        "  python main_per_sbt.py --output data/results/full_results_diag/"
        "trigger_results_full.csv --workers 6 --resume --skip-postprocess\n"
        f"It carries the same verdicts as {EPISODE_RESULTS} plus the per-activation "
        "failure causes this script decomposes."
    )


def _parse(blob) -> dict:
    if not isinstance(blob, str) or not blob.strip():
        return {}
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _reading(values: dict, item: str) -> float:
    """The value the condition read for `item`, as a float, or NaN."""
    if not isinstance(values, dict):
        return math.nan
    raw = values.get(item, math.nan)
    try:
        return float(raw)
    except (TypeError, ValueError):
        return math.nan


def _margin(value: float, threshold: float | None, direction: str | None) -> float:
    """Signed distance to the threshold: negative means the criterion is not met."""
    if threshold is None or direction is None or math.isnan(value):
        return math.nan
    return value - threshold if direction == "at_least" else threshold - value


def _episode_records(df: pd.DataFrame) -> pd.DataFrame:
    """One row per (episode, readiness constraint) that was activated.

    Carries the verdict, the failure cause where the verdict is a violation, and
    the reading the correlation condition saw on either side of the verdict.
    """
    rows: list[dict] = []
    for record in df.itertuples(index=False):
        violations = _parse(record.violation_forensics)
        satisfactions = _parse(record.satisfaction_forensics)
        for cid, spec in CRITERION.items():
            forensics = violations.get(cid)
            state = "violated"
            if forensics is None:
                forensics = satisfactions.get(cid)
                state = "satisfied"
            if forensics is None:
                continue

            causes = forensics.get("causes") or {}
            cause = None
            if state == "violated":
                present = [c for c in CAUSES if causes.get(c)]
                cause = present[-1] if present else None

            # A violation reports its readings under "values", a satisfaction under
            # the deltas the condition extracted.
            values = forensics.get("values") if state == "violated" else forensics.get("deltas")
            value = _reading(values or {}, spec["item"])

            rows.append(
                {
                    "stay_id": record.stay_id,
                    "episode_index": record.episode_index,
                    "constraint_id": cid,
                    "state": state,
                    "cause": cause,
                    "value": value,
                    "margin": _margin(value, spec["threshold"], spec["direction"]),
                    "outcome_binary": record.outcome_binary,
                }
            )
    return pd.DataFrame(rows)


def _cause_table(records: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    violated = records[records["state"] == "violated"]
    counts = (
        violated.pivot_table(
            index="constraint_id", columns="cause", values="episode_index", aggfunc="count"
        )
        .reindex(columns=CAUSES)
        .fillna(0)
        .astype(int)
    )
    counts.columns = [f"n_{c}" for c in CAUSES]
    counts["n_violated"] = violated.groupby("constraint_id").size()
    counts["n_unclassified"] = counts["n_violated"] - counts[
        [f"n_{c}" for c in CAUSES]
    ].sum(axis=1)
    counts["n_documentation"] = counts[[f"n_{c}" for c in DOCUMENTATION_CAUSES]].sum(axis=1)
    denominator = counts["n_violated"].replace(0, pd.NA)
    for cause in CAUSES:
        counts[f"share_{cause}"] = counts[f"n_{cause}"] / denominator
    counts["share_documentation"] = counts["n_documentation"] / denominator
    counts["share_care"] = counts["n_unmet"] / denominator

    out = counts.reset_index().merge(
        meta[["constraint_id", "label"]], on="constraint_id", how="left"
    )
    return out.sort_values("share_care", ascending=False)


def _stratified_association(records: pd.DataFrame) -> pd.DataFrame:
    """Success under a violation, by how far the reading missed the threshold.

    Exposure is a violation in one margin stratum; the reference arm is the
    episodes where the same constraint was satisfied. Strata are tertiles of the
    margin among the violations that carry a reading, so "near" is the third of
    violations closest to the threshold.
    """
    rows: list[dict] = []
    for cid in MARGIN_CONSTRAINTS:
        subset = records[
            (records["constraint_id"] == cid) & records["outcome_binary"].notna()
        ]
        satisfied = subset[subset["state"] == "satisfied"]
        unmet = subset[
            (subset["state"] == "violated")
            & (subset["cause"] == "unmet")
            & subset["margin"].notna()
        ]
        if len(unmet) < 30 or satisfied.empty:
            continue

        # Margins here are all negative; the least negative third is the near-miss arm.
        try:
            strata = pd.qcut(
                unmet["margin"], 3, labels=["gross", "moderate", "near"], duplicates="drop"
            )
        except ValueError:
            continue
        unmet = unmet.assign(stratum=strata)

        reference_success = int((satisfied["outcome_binary"] == 1).sum())
        reference_failure = int((satisfied["outcome_binary"] == 0).sum())

        for stratum, arm in unmet.groupby("stratum", observed=True):
            a = int((arm["outcome_binary"] == 1).sum())
            b = int((arm["outcome_binary"] == 0).sum())
            stats = calculate_stats(a, b, reference_success, reference_failure)
            rows.append(
                {
                    "constraint_id": cid,
                    "stratum": str(stratum),
                    "n_violated": a + b,
                    "margin_min": float(arm["margin"].min()),
                    "margin_max": float(arm["margin"].max()),
                    "value_median": float(arm["value"].median()),
                    "success_rate": a / (a + b) if a + b else math.nan,
                    "reference_success_rate": reference_success
                    / max(reference_success + reference_failure, 1),
                    "rr_point": stats["rr_point"],
                    "rr_ci_low": stats["rr_ci_low"],
                    "rr_ci_high": stats["rr_ci_high"],
                    "p_raw": stats["p_raw"],
                }
            )
    return pd.DataFrame(rows)


def _plot_causes(causes: pd.DataFrame) -> None:
    plot_df = causes.sort_values("share_care")
    fig, ax = plt.subplots(figsize=(7.5, max(3.0, 0.45 * len(plot_df))))
    left = np.zeros(len(plot_df))
    palette = {
        "absent": "#9ecae1",
        "stale": "#6baed6",
        "no_payload": "#3182bd",
        "partial_payload": "#08519c",
        "unmet": "#d62728",
    }
    for cause in CAUSES:
        share = plot_df[f"share_{cause}"].astype(float).to_numpy()
        ax.barh(plot_df["constraint_id"], share, left=left,
                color=palette[cause], label=CAUSE_LABEL[cause])
        left = left + np.nan_to_num(share)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Share of violated episodes")
    ax.set_title("Why each readiness constraint is violated")
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.15),
              ncol=len(CAUSES), frameon=False)
    save_fig(fig, "fig_readiness_causes")


def _plot_margins(records: pd.DataFrame) -> None:
    present = [c for c in MARGIN_CONSTRAINTS
               if records[(records["constraint_id"] == c) & records["value"].notna()].shape[0]]
    if not present:
        return
    fig, axes = plt.subplots(1, len(present), figsize=(3.1 * len(present), 3.0))
    axes = np.atleast_1d(axes)
    for ax, cid in zip(axes, present):
        spec = CRITERION[cid]
        subset = records[(records["constraint_id"] == cid) & records["value"].notna()]
        satisfied = subset.loc[subset["state"] == "satisfied", "value"]
        unmet = subset.loc[
            (subset["state"] == "violated") & (subset["cause"] == "unmet"), "value"
        ]
        combined = pd.concat([satisfied, unmet])
        if combined.empty:
            continue
        low, high = combined.quantile(0.01), combined.quantile(0.99)
        bins = np.linspace(float(low), float(high), 40)
        ax.hist(satisfied, bins=bins, color="#2ca02c", alpha=0.65, label="satisfied")
        ax.hist(unmet, bins=bins, color="#d62728", alpha=0.65, label="assessed, not met")
        ax.axvline(spec["threshold"], color="black", linestyle="--", linewidth=1)
        ax.set_title(cid, fontsize=9)
        ax.set_xlabel(spec["unit"], fontsize=8)
        ax.tick_params(labelsize=7)
    axes[0].set_ylabel("Activations")
    axes[0].legend(fontsize=7)
    fig.suptitle("Readings at trial start, against the guideline threshold", fontsize=10)
    fig.tight_layout()
    save_fig(fig, "fig_readiness_margins")


def _plot_stratified(strata: pd.DataFrame) -> None:
    if strata.empty:
        return
    order = ["near", "moderate", "gross"]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    width = 0.8 / max(len(order), 1)
    for i, stratum in enumerate(order):
        arm = strata[strata["stratum"] == stratum].set_index("constraint_id")
        arm = arm.reindex(sorted(strata["constraint_id"].unique()))
        x = np.arange(len(arm)) + (i - 1) * width
        err = np.vstack(
            [
                (arm["rr_point"] - arm["rr_ci_low"]).to_numpy(dtype=float),
                (arm["rr_ci_high"] - arm["rr_point"]).to_numpy(dtype=float),
            ]
        )
        ax.errorbar(x, arm["rr_point"].to_numpy(dtype=float), yerr=np.abs(err),
                    fmt="o", capsize=3, label=f"{stratum} the threshold")
    ax.axhline(1.0, color="black", linewidth=1)
    ax.set_xticks(np.arange(strata["constraint_id"].nunique()))
    ax.set_xticklabels(sorted(strata["constraint_id"].unique()))
    ax.set_ylabel("Risk ratio of success vs. satisfied")
    ax.set_title("Does it matter how far past the threshold a trial was started?")
    ax.legend(fontsize=8)
    save_fig(fig, "fig_readiness_margin_outcome")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replot", action="store_true",
        help="Regenerate figures from cached CSVs only, without recomputing.",
    )
    args = parser.parse_args()

    if args.replot:
        causes = pd.read_csv(OUT_DIR / "readiness_violation_causes.csv")
        records = pd.read_parquet(OUT_DIR / "readiness_records.parquet")
        strata = pd.read_csv(OUT_DIR / "readiness_margin_association.csv")
        _plot_causes(causes)
        _plot_margins(records)
        _plot_stratified(strata)
        return

    t0 = time.time()
    path = _results_path()
    usecols = [
        "stay_id", "episode_index", "sbt_outcome",
        "violation_forensics", "satisfaction_forensics",
    ]
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    print(f"Loaded {len(df):,} episodes from {path}")

    records = _episode_records(df)
    print(f"{len(records):,} activated (episode, readiness constraint) pairs")
    records_path = OUT_DIR / "readiness_records.parquet"
    records.to_parquet(records_path, index=False)
    print(f"  parquet-> {records_path}")

    meta = load_constraint_meta()
    causes = _cause_table(records, meta)
    write_csv(causes, "readiness_violation_causes.csv")

    strata = _stratified_association(records)
    write_csv(strata, "readiness_margin_association.csv")

    overview = {
        "results_file": str(path),
        "n_episodes": int(len(df)),
        "n_activations": int(len(records)),
        "n_violated": int((records["state"] == "violated").sum()),
        "share_violations_documentation": float(
            causes["n_documentation"].sum() / max(causes["n_violated"].sum(), 1)
        ),
        "share_violations_care": float(
            causes["n_unmet"].sum() / max(causes["n_violated"].sum(), 1)
        ),
        "constraints_with_margin_strata": sorted(strata["constraint_id"].unique().tolist())
        if not strata.empty
        else [],
    }
    write_json(overview, "readiness_diagnostics_overview.json")

    _plot_causes(causes)
    _plot_margins(records)
    _plot_stratified(strata)

    print(
        "Documentation-attributable share of readiness violations: "
        f"{overview['share_violations_documentation']:.1%}"
    )
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
