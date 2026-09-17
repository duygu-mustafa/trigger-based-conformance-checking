"""Rule-outcome association with multiple-testing correction and vacuity sensitivity.

Reuses the pipeline's own encoding and statistics functions
(derive/statistical_analysis.py) so the numbers are identical to the committed
results, and adds on top:
  * Bonferroni and Benjamini-Hochberg FDR correction within each vacuity mode
  * clinical-relevance classification (same rule as the frontend)
  * degenerate-estimate flags (zero cell, continuity correction, extreme OR)
  * a side-by-side comparison of the activations-only and pooled-vacuous encodings
  * a PASS/FAIL cross-check of the activations-only encoding against
    data/results/full_results/rule_statistics_R2.csv (the R script's own stats,
    which feeds the frontend)

Orientation (fixed by generate_contingency_table): exposure = constraint VIOLATED,
outcome = SUCCESS. OR < 1 therefore means violation tracks failure (the rule
discriminates), OR > 1 means violation tracks success.

Usage:
    python case_study/04_outcome_association.py [--use-cache]
"""

from __future__ import annotations

import argparse
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from config import (
    EPISODE_RESULTS,
    OUT_DIR,
    REFERENCE_SUMMARY,
    save_fig,
    write_csv,
    write_json,
)
from derive.statistical_analysis import (
    _classify,
    build_case_level_table,
    calculate_stats,
    generate_contingency_table,
    load_conformance_data,
    load_constraint_labels,
    load_inter_episode_rules,
)

MODES = [(False, "activations_only"), (True, "pooled")]
EXTREME_OR = 1e3  # beyond this the estimate is separation, not an effect size


def case_table(df, pool_vacuous: bool, tag: str, use_cache: bool) -> pd.DataFrame:
    cache = OUT_DIR / f"case_level_table_{tag}.parquet"
    if use_cache and cache.exists():
        print(f"[{tag}] reusing {cache.name}")
        return pd.read_parquet(cache)
    table = build_case_level_table(df, pool_vacuous=pool_vacuous)
    table.to_parquet(cache, index=False)
    return table


def analyse(df_cases: pd.DataFrame, inter_rules: set[str], tag: str,
            labels: dict[str, str]) -> pd.DataFrame:
    exclude = {"stay_id", "episode_index", "outcome", "next_outcome"}
    rules = sorted(c for c in df_cases.columns if c not in exclude)

    rows = []
    for rule_id in rules:
        is_inter = rule_id in inter_rules
        outcome_col = "next_outcome" if is_inter else "outcome"
        a, b, c, d, n_censored = generate_contingency_table(df_cases, rule_id, outcome_col)
        if (a + b + c + d) == 0:
            continue
        st = calculate_stats(a, b, c, d)
        rows.append(
            {
                "constraint_id": rule_id,
                "label": labels.get(rule_id, rule_id),
                "vacuous_mode": tag,
                "outcome_variable": "next_episode" if is_inter else "same_episode",
                "exposure": "constraint violated",
                "outcome_coded_1": "success",
                "n_censored": n_censored,
                "n_exposed": a + b,
                "n_unexposed": c + d,
                "a_violated_success": a,
                "b_violated_failure": b,
                "c_satisfied_success": c,
                "d_satisfied_failure": d,
                "p_raw": st["p_raw"],
                "or": st["or_point"],
                "or_ci_low": st["or_ci_low"],
                "or_ci_high": st["or_ci_high"],
                "rr": st["rr_point"],
                "rr_ci_low": st["rr_ci_low"],
                "rr_ci_high": st["rr_ci_high"],
                "used_continuity_correction": st["continuity_correction"],
            }
        )

    out = pd.DataFrame(rows)
    if out.empty:
        return out

    # multiple-testing correction within this mode
    p = out["p_raw"].fillna(1.0).values
    out["p_bonferroni"] = multipletests(p, method="bonferroni")[1]
    out["p_fdr_bh"] = multipletests(p, method="fdr_bh")[1]
    out["n_tests"] = len(out)
    out["significant_raw"] = out["p_raw"] < 0.05
    out["significant_bonferroni"] = out["p_bonferroni"] < 0.05
    out["significant_fdr"] = out["p_fdr_bh"] < 0.05

    out["clinical_relevance"] = [
        _classify(r["or"], r["or_ci_low"], r["or_ci_high"], r["p_raw"])
        for _, r in out.iterrows()
    ]
    out["direction"] = np.where(
        out["or"] < 1, "violation tracks failure", "violation tracks success"
    )
    zero_cell = (
        out[["a_violated_success", "b_violated_failure",
             "c_satisfied_success", "d_satisfied_failure"]].min(axis=1) == 0
    )
    out["degenerate_estimate"] = (
        zero_cell
        | out["used_continuity_correction"]
        | (out["or"] > EXTREME_OR)
        | (out["or"] < 1 / EXTREME_OR)
    )
    return out.sort_values("p_raw").reset_index(drop=True)


def crosscheck(activations_only: pd.DataFrame) -> dict:
    """Compare the activations-only a,b,c,d / OR / p against the R script's own
    per-rule stats (rule_statistics_R2.csv, the table that feeds the frontend).

    R only ever computes the activations-only encoding (vacuous cases dropped,
    never pooled — see statistics_R.r), so this checks the one encoding both
    implementations share, not the pooled sensitivity variant, which exists only
    on the Python side.

    OR is intentionally excluded from the pass/fail verdict (reported for
    reference only): R uses fisher.test()'s conditional MLE, Python uses the
    continuity-corrected cross-product ratio (ad/bc) — different estimators
    that diverge by design at zero cells (R -> 0/Inf, Python stays finite).
    a/b/c/d and the Fisher p-value use the same definitions in both and are
    the real "same table, same test" check.
    """
    if not REFERENCE_SUMMARY.exists():
        return {"status": "SKIPPED", "reason": f"{REFERENCE_SUMMARY} missing"}
    ref = pd.read_csv(REFERENCE_SUMMARY)
    merged = activations_only.merge(
        ref,
        left_on=["constraint_id", "outcome_variable"],
        right_on=["rule_name", "outcome_variable"],
        suffixes=("", "_ref"),
    )
    if merged.empty:
        return {"status": "FAIL", "reason": "no overlapping rows with reference"}
    pairs = [
        ("a_violated_success", "a"), ("b_violated_failure", "b"),
        ("c_satisfied_success", "c"), ("d_satisfied_failure", "d"),
    ]
    mismatches = []
    for mine, theirs in pairs:
        bad = merged[merged[mine] != merged[theirs]]
        if not bad.empty:
            mismatches.append({mine: sorted(bad["constraint_id"].unique())})
    # OR uses different estimators in R vs. Python (see docstring) and is
    # reported but not enforced; only the shared table cells and p-value count.
    or_close = np.allclose(merged["or"], merged["or_ref"], rtol=1e-3, equal_nan=True)
    p_close = np.allclose(merged["p_raw"], merged["fisher_p"], rtol=1e-6, equal_nan=True)
    status = "PASS" if not mismatches and p_close else "FAIL"
    return {
        "status": status,
        "n_rows_compared": int(len(merged)),
        "cell_mismatches": mismatches,
        "odds_ratio_matches_approx": bool(or_close),
        "p_value_matches": bool(p_close),
        "reference": str(REFERENCE_SUMMARY),
    }


def forest_plot(df: pd.DataFrame) -> None:
    d = df[df["vacuous_mode"] == "activations_only"].copy()
    d = d.sort_values("or")
    lo = d["or_ci_low"].clip(lower=1e-3)
    hi = d["or_ci_high"].clip(upper=1e3)
    fig, ax = plt.subplots(figsize=(7.5, max(4, 0.34 * len(d))))
    y = np.arange(len(d))
    colors = ["#1f77b4" if s else "#999999" for s in d["significant_fdr"]]
    for yi, (l, h, c) in enumerate(zip(lo, hi, colors)):
        ax.plot([l, h], [yi, yi], color=c, lw=1.5)
    ax.scatter(d["or"].clip(1e-3, 1e3), y, color=colors, zorder=3, s=22,
               marker="D")
    for yi, deg in enumerate(d["degenerate_estimate"]):
        if deg:
            ax.text(1e3, yi, " !", va="center", fontsize=9, color="#d62728")
    ax.axvline(1.0, color="black", lw=0.8, ls="--")
    ax.set_xscale("log")
    ax.set_yticks(y)
    ax.set_yticklabels(d["constraint_id"])
    ax.set_xlabel("Odds ratio (exposure = violated, outcome = success), log scale")
    ax.set_title("Rule-outcome association (activations-only encoding)")
    ax.legend(
        handles=[
            plt.Line2D([], [], color="#1f77b4", marker="D", ls="-", label="FDR-significant"),
            plt.Line2D([], [], color="#999999", marker="D", ls="-", label="not significant"),
            plt.Line2D([], [], color="#d62728", marker="$!$", ls="", label="degenerate / clipped"),
        ],
        fontsize=8,
        loc="lower right",
    )
    save_fig(fig, "fig_forest_or")


def comparison_plot(cmp: pd.DataFrame) -> None:
    # Degenerate estimates (separation) would compress the useful range by ten orders
    # of magnitude; they stay in association_comparison.csv but are off the plot.
    d = cmp.dropna(subset=["or_activations_only", "or_pooled"])
    n_dropped = int(d["degenerate_either_mode"].sum())
    d = d[~d["degenerate_either_mode"]]
    fig, ax = plt.subplots(figsize=(5.5, 5))
    flip = d["sign_flip"]
    ax.scatter(d.loc[~flip, "or_activations_only"], d.loc[~flip, "or_pooled"],
               color="#1f77b4", s=30, label="same direction")
    ax.scatter(d.loc[flip, "or_activations_only"], d.loc[flip, "or_pooled"],
               color="#d62728", s=40, marker="^", label="direction flips")
    for _, r in d.iterrows():
        ax.annotate(r["constraint_id"], (r["or_activations_only"], r["or_pooled"]),
                    fontsize=6, xytext=(3, 3), textcoords="offset points")
    lims = [
        min(d["or_activations_only"].min(), d["or_pooled"].min()) * 0.5,
        max(d["or_activations_only"].max(), d["or_pooled"].max()) * 2,
    ]
    ax.plot(lims, lims, color="black", lw=0.8, ls="--")
    ax.axhline(1.0, color="grey", lw=0.6)
    ax.axvline(1.0, color="grey", lw=0.6)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("OR, activations-only encoding")
    ax.set_ylabel("OR, pooled-vacuous encoding")
    ax.set_title(
        "Sensitivity to vacuous-satisfaction handling"
        + (f"\n({n_dropped} degenerate estimates omitted)" if n_dropped else "")
    )
    ax.legend(fontsize=8)
    save_fig(fig, "fig_vacuous_mode_comparison")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-cache", action="store_true",
                        help="reuse cached case-level tables from a previous run")
    args = parser.parse_args()

    t0 = time.time()
    df = load_conformance_data(EPISODE_RESULTS)
    print(f"Loaded {len(df):,} episodes")
    inter_rules = load_inter_episode_rules()
    print(f"Inter-episode rules (scored against the next episode): {sorted(inter_rules)}")
    labels = load_constraint_labels()

    results = {}
    for pool, tag in MODES:
        table = case_table(df, pool, tag, args.use_cache)
        print(f"[{tag}] case-level table: {len(table):,} SBT episodes")
        results[tag] = analyse(table, inter_rules, tag, labels)
        write_csv(results[tag], f"association_{tag}.csv")

    combined = pd.concat(results.values(), ignore_index=True)

    headline = (
        results["activations_only"]
        .query("significant_fdr and not degenerate_estimate")
        .assign(abs_log_or=lambda d: d["or"].apply(lambda v: abs(np.log(v))))
        .sort_values("abs_log_or", ascending=False)
    )
    write_csv(headline, "association_headline.csv")

    # ---- vacuity-mode comparison ----------------------------------------
    wide = combined.pivot_table(
        index=["constraint_id", "outcome_variable"],
        columns="vacuous_mode",
        values=["or", "p_raw", "p_fdr_bh", "n_exposed", "n_unexposed"],
        aggfunc="first",
    )
    wide.columns = [f"{a}_{b}" for a, b in wide.columns]
    cmp = wide.reset_index()
    cmp = cmp.merge(
        results["activations_only"][["constraint_id", "label", "clinical_relevance"]]
        .rename(columns={"clinical_relevance": "relevance_activations_only"}),
        on="constraint_id", how="left",
    ).merge(
        results["pooled"][["constraint_id", "clinical_relevance", "degenerate_estimate"]]
        .rename(
            columns={
                "clinical_relevance": "relevance_pooled",
                "degenerate_estimate": "degenerate_pooled",
            }
        ),
        on="constraint_id", how="left",
    ).merge(
        results["activations_only"][["constraint_id", "degenerate_estimate"]]
        .rename(columns={"degenerate_estimate": "degenerate_activations_only"}),
        on="constraint_id", how="left",
    )
    cmp["degenerate_either_mode"] = (
        cmp["degenerate_activations_only"].fillna(False)
        | cmp["degenerate_pooled"].fillna(False)
    )
    cmp["sign_flip"] = (cmp["or_activations_only"] < 1) != (cmp["or_pooled"] < 1)
    cmp["relevance_changed"] = (
        cmp["relevance_activations_only"] != cmp["relevance_pooled"]
    )
    cmp["log_or_ratio"] = np.log(cmp["or_pooled"] / cmp["or_activations_only"])
    write_csv(cmp, "association_comparison.csv")

    check = crosscheck(results["activations_only"])
    summary = {
        "n_constraints_tested": int(len(results["activations_only"])),
        "n_significant_raw": int(results["activations_only"]["significant_raw"].sum()),
        "n_significant_bonferroni": int(
            results["activations_only"]["significant_bonferroni"].sum()
        ),
        "n_significant_fdr": int(results["activations_only"]["significant_fdr"].sum()),
        "n_degenerate": int(results["activations_only"]["degenerate_estimate"].sum()),
        "n_violation_tracks_failure": int(
            (results["activations_only"]["or"] < 1).sum()
        ),
        "n_violation_tracks_success": int(
            (results["activations_only"]["or"] > 1).sum()
        ),
        "relevance_counts": results["activations_only"]["clinical_relevance"]
        .value_counts()
        .to_dict(),
        "n_sign_flips_between_modes": int(cmp["sign_flip"].sum()),
        "sign_flip_constraints": sorted(cmp.loc[cmp["sign_flip"], "constraint_id"]),
        "n_relevance_changes_between_modes": int(cmp["relevance_changed"].sum()),
        "crosscheck_vs_committed_results": check,
    }
    write_json(summary, "association_overview.json")
    print(f"CROSS-CHECK vs {REFERENCE_SUMMARY.name}: {check['status']}")

    forest_plot(combined)
    comparison_plot(cmp)
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
