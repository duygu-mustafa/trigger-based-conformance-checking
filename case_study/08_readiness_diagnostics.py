"""Why the readiness constraints are violated, and how far from the threshold.

Two questions the aggregate verdicts of step 03 cannot answer.

First, a readiness violation has several possible causes, which the checker
records per activation: no measurement lies in the lookback window
(`undocumented`), the measurement event fired but carries none of the values the
condition reads (`no_payload`), a disjunctive criterion was decided on readings
only some of which are present (`partial_payload`), or the criterion was assessed
on complete readings and not met (`unmet`). Only the last is a statement about
care; the rest are statements about documentation. Each cause is then related to
the episode outcome separately, to see whether only `unmet` violations go along
with failure. The per-rule outcome association of step 04 is then repeated with
each readiness rule split into its `unmet` and documentation arms, which the
frontend's outcome forest shows.

The checker distinguishes `absent` (no measurement anywhere in the evaluated
history) from `stale` (a measurement exists, but only before the lookback). Both
fail the guideline condition identically, and the evaluated history extends only
24 h before the episode start, so `stale` can only occur in episodes whose trial
starts more than 24 h after the episode begins. The split therefore mostly
encodes episode length, and the two are merged here into `undocumented`.

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
    FIG_WIDTH,
    OUT_DIR,
    constraint_label,
    load_constraint_meta,
    save_fig,
    top_legend,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label, calculate_stats

# Ordered from least to most specific, so an episode whose activations disagree is
# reported under the most informative cause any of them produced.
CAUSES = ["undocumented", "no_payload", "partial_payload", "unmet"]
DOCUMENTATION_CAUSES = ["undocumented", "no_payload", "partial_payload"]

# The checker's own causes, ordered the same way, and how they fold into CAUSES.
CHECKER_CAUSES = ["absent", "stale", "no_payload", "partial_payload", "unmet"]
MERGED_CAUSE = {"absent": "undocumented", "stale": "undocumented"}

CAUSE_COLOR = {
    "undocumented": "#9ecae1",
    "no_payload": "#3182bd",
    "partial_payload": "#08519c",
    "unmet": "#d62728",
}

CAUSE_LABEL = {
    "undocumented": "not documented in window",
    "no_payload": "event without a value",
    "partial_payload": "criterion only partly documented",
    "unmet": "assessed and not met",
}

# The reading each readiness criterion is judged on, the threshold it must clear,
# and the direction of conformance. `at_least` means the criterion is met when the
# reading is at or above the threshold; `at_most` when it is at or below. RC-DP-06 has
# no graded reading because its criterion is a categorical bedside score, so it takes
# part in the cause analysis but not in the margin analysis.
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
    "RC-DP-06": {"item": None, "threshold": None, "direction": None,
                 "unit": "mental status"},
}

# Margin analysis needs a graded reading. RC-DP-07 is thresholded at zero on a
# quantity that is either charted as positive or not at all, so its margin has only
# one violating value and no gradation to stratify.
MARGIN_CONSTRAINTS = ["RC-DP-01", "RC-DP-02", "RC-DP-03", "RC-DP-04", "RC-DP-05"]

# The criteria judged on a reading rather than a categorical score.
GRADED_CONSTRAINTS = [cid for cid, spec in CRITERION.items() if spec["item"] is not None]


def _results_path():
    """Prefer the run carrying failure causes; say so when it is missing."""
    if EPISODE_RESULTS_DIAG.exists():
        return EPISODE_RESULTS_DIAG
    raise SystemExit(
        f"{EPISODE_RESULTS_DIAG} not found. Regenerate it with\n"
        "  python main.py --output data/results/full_results_diag/"
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
    if not isinstance(values, dict) or item is None:
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
                present = [c for c in CHECKER_CAUSES if causes.get(c)]
                cause = present[-1] if present else None
                cause = MERGED_CAUSE.get(cause, cause)

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


def _arm_stats(arm: pd.DataFrame, reference: pd.DataFrame) -> dict:
    """Risk ratio of success in `arm` against `reference`, with counts."""
    a = int((arm["outcome_binary"] == 1).sum())
    b = int((arm["outcome_binary"] == 0).sum())
    c = int((reference["outcome_binary"] == 1).sum())
    d = int((reference["outcome_binary"] == 0).sum())
    stats = calculate_stats(a, b, c, d)
    return {
        "n_exposed": a + b,
        "n_reference": c + d,
        "success_rate": a / (a + b) if a + b else math.nan,
        "reference_success_rate": c / (c + d) if c + d else math.nan,
        "rr_point": stats["rr_point"],
        "rr_ci_low": stats["rr_ci_low"],
        "rr_ci_high": stats["rr_ci_high"],
        "p_raw": stats["p_raw"],
    }


def _cause_association(records: pd.DataFrame, min_arm: int = 30) -> pd.DataFrame:
    """Success under a violation, split by why the constraint was violated.

    Exposure is a violation with one cause; the reference arm is the episodes
    where the same constraint was satisfied. If only `unmet` violations go along
    with failure, the documentation causes should sit at a risk ratio near one.
    The row `all_violations` pools the causes and reproduces the unstratified
    association. Bonferroni runs over the per-cause tests that were performed.
    """
    rows: list[dict] = []
    for cid in CRITERION:
        subset = records[
            (records["constraint_id"] == cid) & records["outcome_binary"].notna()
        ]
        satisfied = subset[subset["state"] == "satisfied"]
        violated = subset[subset["state"] == "violated"]
        if satisfied.empty or violated.empty:
            continue
        arms = [("all_violations", violated)]
        arms += [(cause, violated[violated["cause"] == cause]) for cause in CAUSES]
        for cause, arm in arms:
            if len(arm) < min_arm:
                continue
            rows.append({"constraint_id": cid, "cause": cause, **_arm_stats(arm, satisfied)})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    per_cause = out["cause"] != "all_violations"
    n_tests = int(per_cause.sum())
    out["n_tests"] = n_tests
    out["p_bonferroni"] = (out["p_raw"] * n_tests).clip(upper=1.0)
    out["significant"] = per_cause & (out["p_raw"] < 0.05 / n_tests)
    return out


def _split_arm(arm: pd.DataFrame, reference: pd.DataFrame) -> dict:
    """The 2x2 table and both effect measures, in step 04's column names."""
    a = int((arm["outcome_binary"] == 1).sum())
    b = int((arm["outcome_binary"] == 0).sum())
    c = int((reference["outcome_binary"] == 1).sum())
    d = int((reference["outcome_binary"] == 0).sum())
    stats = calculate_stats(a, b, c, d)
    return {
        "n_exposed": a + b,
        "n_unexposed": c + d,
        "a_violated_success": a,
        "b_violated_failure": b,
        "c_satisfied_success": c,
        "d_satisfied_failure": d,
        "p_raw": stats["p_raw"],
        "or": stats["or_point"],
        "or_ci_low": stats["or_ci_low"],
        "or_ci_high": stats["or_ci_high"],
        "rr": stats["rr_point"],
        "rr_ci_low": stats["rr_ci_low"],
        "rr_ci_high": stats["rr_ci_high"],
        "used_continuity_correction": min(a, b, c, d) == 0,
    }


def _split_association(records: pd.DataFrame, min_arm: int = 30) -> pd.DataFrame:
    """Step 04's per-rule association with the readiness rules split by cause.

    A readiness violation is either a criterion assessed and not met or a gap in
    documentation, and the two are associated with the outcome differently. Each
    readiness rule therefore contributes two arms against the same satisfied
    reference: `unmet`, and `documentation` pooling the three documentation
    causes. The other rules have no data condition on their target, so their only
    failure is a missing action and their step 04 row is kept as it is
    (arm `missing_action`). Bonferroni runs over every row of the combined table,
    so the split costs the readiness rules one extra test each.
    """
    base = pd.read_csv(OUT_DIR / "association_activations_only.csv")
    pooled = base.set_index("constraint_id")
    rows: list[dict] = []
    for cid in CRITERION:
        subset = records[
            (records["constraint_id"] == cid) & records["outcome_binary"].notna()
        ]
        satisfied = subset[subset["state"] == "satisfied"]
        violated = subset[subset["state"] == "violated"]
        arms = [
            ("unmet", violated[violated["cause"] == "unmet"]),
            ("documentation", violated[violated["cause"].isin(DOCUMENTATION_CAUSES)]),
        ]
        for arm_name, arm in arms:
            if len(arm) < min_arm or satisfied.empty:
                continue
            rows.append({
                "constraint_id": cid,
                "label": pooled.loc[cid, "label"],
                "arm": arm_name,
                "outcome_variable": pooled.loc[cid, "outcome_variable"],
                **_split_arm(arm, satisfied),
                "pooled_rr": pooled.loc[cid, "rr"],
                "pooled_rr_ci_low": pooled.loc[cid, "rr_ci_low"],
                "pooled_rr_ci_high": pooled.loc[cid, "rr_ci_high"],
                "pooled_or": pooled.loc[cid, "or"],
                "pooled_or_ci_low": pooled.loc[cid, "or_ci_low"],
                "pooled_or_ci_high": pooled.loc[cid, "or_ci_high"],
                "pooled_significant_bonferroni": pooled.loc[cid, "significant_bonferroni"],
                "degenerate_estimate": False,
            })
    others = base[~base["constraint_id"].isin(CRITERION)].assign(arm="missing_action")
    out = pd.concat([pd.DataFrame(rows), others[[
        "constraint_id", "label", "arm", "outcome_variable", "n_exposed", "n_unexposed",
        "a_violated_success", "b_violated_failure", "c_satisfied_success",
        "d_satisfied_failure", "p_raw", "or", "or_ci_low", "or_ci_high", "rr",
        "rr_ci_low", "rr_ci_high", "used_continuity_correction", "degenerate_estimate",
    ]]], ignore_index=True)
    n_tests = len(out)
    out["n_tests"] = n_tests
    out["p_bonferroni"] = (out["p_raw"] * n_tests).clip(upper=1.0)
    out["significant_bonferroni"] = out["p_raw"] < 0.05 / n_tests
    return out


def _episode_cause_profile(records: pd.DataFrame) -> pd.DataFrame:
    """Success by the worst readiness evidence an episode carries.

    Only the criteria with a graded reading count. RC-DP-06 is violated in nearly
    every episode for lack of a charted score, so including it would leave almost
    no episode in the reference arm. Each episode is placed in one profile: every
    activated criterion satisfied, violations that are all documentation gaps, or
    at least one criterion assessed and not met. Comparing the latter two against
    the first answers the cause question once per episode, without counting an
    episode again for every criterion it violates.
    """
    scored = records[
        records["outcome_binary"].notna() & records["constraint_id"].isin(GRADED_CONSTRAINTS)
    ]
    keys = ["stay_id", "episode_index"]
    per_episode = scored.groupby(keys).agg(
        outcome_binary=("outcome_binary", "first"),
        n_violated=("state", lambda s: int((s == "violated").sum())),
        n_unmet=("cause", lambda s: int((s == "unmet").sum())),
    )
    per_episode["profile"] = np.select(
        [per_episode["n_violated"] == 0, per_episode["n_unmet"] == 0],
        ["all_satisfied", "documentation_only"],
        default="any_unmet",
    )
    reference = per_episode[per_episode["profile"] == "all_satisfied"]
    rows = []
    for profile in ["all_satisfied", "documentation_only", "any_unmet"]:
        arm = per_episode[per_episode["profile"] == profile]
        row = {"profile": profile, **_arm_stats(arm, reference)}
        if profile == "all_satisfied":
            for key in ("rr_point", "rr_ci_low", "rr_ci_high", "p_raw"):
                row[key] = math.nan
        rows.append(row)
    return pd.DataFrame(rows)


def _plot_causes(causes: pd.DataFrame) -> None:
    # The criteria with a graded reading, as in the thesis table; RC-DP-06 is in the CSV.
    # Ordered by ID from the top, as in the cause association figure.
    plot_df = causes[causes["constraint_id"].isin(GRADED_CONSTRAINTS)].sort_values(
        "constraint_id", ascending=False
    )
    present = [c for c in CAUSES if plot_df[f"n_{c}"].sum() > 0]
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 0.6 + 0.32 * len(plot_df)))
    left = np.zeros(len(plot_df))
    labels = [constraint_label(c) for c in plot_df["constraint_id"]]
    for cause in present:
        share = plot_df[f"share_{cause}"].astype(float).to_numpy()
        # A thin surface-coloured edge separates adjacent segments.
        ax.barh(labels, share, left=left, height=0.7, color=CAUSE_COLOR[cause],
                edgecolor="white", linewidth=1, label=CAUSE_LABEL[cause])
        left = left + np.nan_to_num(share)
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Share of violated episodes")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    top_legend(ax)
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


# Margin strata, ordered from the mildest to the most severe violation. All are
# `unmet` violations, so they share its hue and darken with severity.
STRATUM_ORDER = ["near", "moderate", "gross"]
STRATUM_COLOR = {"near": "#fc9272", "moderate": "#ef3b2c", "gross": "#99000d"}
STRATUM_LABEL = {
    "near": "mild (nearest third)",
    "moderate": "moderate",
    "gross": "severe (farthest third)",
}


def _plot_stratified(strata: pd.DataFrame) -> None:
    if strata.empty:
        return
    _plot_banded_forest(strata, "stratum", STRATUM_ORDER, STRATUM_COLOR, STRATUM_LABEL,
                        "fig_readiness_margin_outcome")


def _plot_cause_association(assoc: pd.DataFrame) -> None:
    if assoc.empty:
        return
    per_cause = assoc[assoc["cause"] != "all_violations"]
    _plot_banded_forest(per_cause, "cause", CAUSES, CAUSE_COLOR, CAUSE_LABEL,
                        "fig_readiness_cause_outcome")


def _plot_banded_forest(df: pd.DataFrame, arm_col: str, arm_order: list[str],
                        colors: dict, labels: dict, name: str) -> None:
    """One row group per constraint, one point with its CI per arm.

    Each constraint sits in its own shaded band with its name on the left, so a
    point is read against the band it lies in rather than a shared tick. Used for
    both the cause and the margin association, so the two figures read alike.
    """
    order = sorted(df["constraint_id"].unique())
    present = [a for a in arm_order if a in set(df[arm_col])]

    row_step = 1.0
    band_gap = 0.8
    fig_height = 0.6 + 0.17 * (len(df) + band_gap * len(order))
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, fig_height))

    y = 0.0
    centers: list[float] = []
    for k, cid in enumerate(order):
        rows = df[df["constraint_id"] == cid].set_index(arm_col)
        arms_here = [a for a in present if a in rows.index]
        top = y
        for arm in arms_here:
            row = rows.loc[arm]
            point = float(row["rr_point"])
            low, high = float(row["rr_ci_low"]), float(row["rr_ci_high"])
            ax.errorbar(point, y, xerr=[[point - low], [high - point]], fmt="o",
                        capsize=3, color=colors[arm], markersize=5)
            # The lightest marker colour is too pale for text, so labels use a darker tone.
            ax.annotate(f"{point:.2f}", (high, y), xytext=(4, 0),
                        textcoords="offset points", va="center", fontsize=6.5,
                        color="#4a4a4a")
            y += row_step
        bottom = y - row_step
        if k % 2 == 0:
            ax.axhspan(top - row_step / 2, bottom + row_step / 2,
                       color="#f0f0f0", zorder=0, linewidth=0)
        centers.append((top + bottom) / 2)
        y += band_gap

    ax.axvline(1.0, color="black", linewidth=1)
    x_low = float(df["rr_ci_low"].min())
    x_high = float(df["rr_ci_high"].max())
    ax.set_xlim(min(x_low, 1.0) - 0.03, max(x_high, 1.0) + 0.08)
    ax.grid(axis="y", visible=False)
    ax.set_yticks(centers)
    ax.set_yticklabels([constraint_label(c) for c in order])
    ax.tick_params(axis="y", length=0)
    ax.set_ylim(y - band_gap - row_step / 2, -row_step / 2)
    ax.set_xlabel("Risk ratio of success vs. satisfied")
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    handles = [plt.Line2D([], [], marker="o", linestyle="", color=colors[a],
                          label=labels[a]) for a in present]
    top_legend(ax, handles)
    save_fig(fig, name)


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
        assoc = pd.read_csv(OUT_DIR / "readiness_cause_association.csv")
        _plot_causes(causes)
        _plot_cause_association(assoc)
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

    assoc = _cause_association(records)
    write_csv(assoc, "readiness_cause_association.csv")

    profile = _episode_cause_profile(records)
    write_csv(profile, "readiness_cause_profile.csv")

    write_csv(_split_association(records), "association_split_by_cause.csv")

    # The headline shares cover the criteria with a graded reading, as the cause
    # table in the thesis does; RC-DP-06 is reported in its own row of the CSV.
    graded = causes[causes["constraint_id"].isin(GRADED_CONSTRAINTS)]
    overview = {
        "results_file": str(path),
        "n_episodes": int(len(df)),
        "n_activations": int(len(records)),
        "n_violated": int((records["state"] == "violated").sum()),
        "n_violated_graded": int(graded["n_violated"].sum()),
        "share_violations_documentation": float(
            graded["n_documentation"].sum() / max(graded["n_violated"].sum(), 1)
        ),
        "share_violations_care": float(
            graded["n_unmet"].sum() / max(graded["n_violated"].sum(), 1)
        ),
        "cause_association": {
            f"{row.constraint_id}/{row.cause}": {
                "n": int(row.n_exposed),
                "rr": float(row.rr_point),
                "ci": [float(row.rr_ci_low), float(row.rr_ci_high)],
                "significant": bool(row.significant),
            }
            for row in assoc.itertuples(index=False)
        },
        "episode_profile": {
            row.profile: {
                "n": int(row.n_exposed),
                "success_rate": float(row.success_rate),
                "rr": float(row.rr_point),
                "ci": [float(row.rr_ci_low), float(row.rr_ci_high)],
            }
            for row in profile.itertuples(index=False)
        },
        "constraints_with_margin_strata": sorted(strata["constraint_id"].unique().tolist())
        if not strata.empty
        else [],
    }
    write_json(overview, "readiness_diagnostics_overview.json")

    _plot_causes(causes)
    _plot_cause_association(assoc)
    _plot_margins(records)
    _plot_stratified(strata)

    print(
        "Documentation-attributable share of readiness violations: "
        f"{overview['share_violations_documentation']:.1%}"
    )
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
