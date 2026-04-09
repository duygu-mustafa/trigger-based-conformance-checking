"""Describe rule-violation profiles in failure vs success cohorts.

This script computes, for each rule-specific violation indicator:
- Violation rate in failures (positives) vs successes (negatives)
- Absolute and relative differences between cohorts
- Fisher's exact test p-value and odds ratio

It uses stay-level rows so each patient stay contributes once.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
from scipy.stats import fisher_exact

from run_logistic_regression import _build_stay_level_constraint_matrix


def build_violation_profile(
    tracking_csv: Path,
    *,
    outcome_col: str = "y",
    min_rate_diff: float = 0.10,
) -> tuple[pd.DataFrame, pd.DataFrame, int, int]:
    tracking = pd.read_csv(tracking_csv)
    stay_matrix, feature_cols = _build_stay_level_constraint_matrix(
        tracking,
        outcome_col=outcome_col,
    )

    violated_cols = [c for c in feature_cols if "__violated__" in c]
    required_cols = ["case_id", outcome_col, *violated_cols]
    rows = stay_matrix[required_cols].dropna().copy()
    rows[outcome_col] = rows[outcome_col].astype(int)

    positives = rows[rows[outcome_col] == 1]
    negatives = rows[rows[outcome_col] == 0]

    n_pos = len(positives)
    n_neg = len(negatives)
    if n_pos == 0 or n_neg == 0:
        raise ValueError("Need both outcome classes present to compare cohorts.")

    result_rows = []
    for col in violated_cols:
        a = int(positives[col].sum())  # violated in failures
        b = int(n_pos - a)             # not violated in failures
        c = int(negatives[col].sum())  # violated in successes
        d = int(n_neg - c)             # not violated in successes

        failure_rate = a / n_pos
        success_rate = c / n_neg
        rate_diff = failure_rate - success_rate
        relative_risk = (failure_rate / success_rate) if success_rate > 0 else float("inf")

        odds_ratio, p_value = fisher_exact([[a, b], [c, d]], alternative="two-sided")

        result_rows.append(
            {
                "rule": col,
                "fail_violations": a,
                "fail_non_violations": b,
                "success_violations": c,
                "success_non_violations": d,
                "failure_rate": failure_rate,
                "success_rate": success_rate,
                "rate_diff": rate_diff,
                "relative_risk": relative_risk,
                "fisher_odds_ratio": odds_ratio,
                "fisher_p_value": p_value,
            }
        )

    profile = pd.DataFrame(result_rows).sort_values(
        ["rate_diff", "fisher_p_value"], ascending=[False, True]
    )

    notably_higher = profile[
        (profile["rate_diff"] >= min_rate_diff) & (profile["failure_rate"] > profile["success_rate"])
    ].copy()

    return profile, notably_higher, n_pos, n_neg


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare rule-violation rates in failures vs successes with Fisher tests."
    )
    parser.add_argument(
        "--tracking-csv",
        type=Path,
        default=Path("weighted_scoring_trace_tracking.csv"),
        help="Path to weighted_scoring_trace_tracking.csv",
    )
    parser.add_argument(
        "--outcome-col",
        type=str,
        default="y",
        help="Binary outcome column (1=failure cohort, 0=success cohort).",
    )
    parser.add_argument(
        "--min-rate-diff",
        type=float,
        default=0.10,
        help="Minimum absolute rate difference to label a rule as notably higher in failures.",
    )
    parser.add_argument(
        "--out-all",
        type=Path,
        default=None,
        help="Optional CSV path for the full per-rule profile.",
    )
    parser.add_argument(
        "--out-notable",
        type=Path,
        default=None,
        help="Optional CSV path for rules notably higher in failures.",
    )
    args = parser.parse_args()

    profile, notable, n_pos, n_neg = build_violation_profile(
        args.tracking_csv,
        outcome_col=args.outcome_col,
        min_rate_diff=args.min_rate_diff,
    )

    pd.set_option("display.width", 160)
    pd.set_option("display.max_columns", 20)

    print("=" * 100)
    print("Violation profile by cohort")
    print("=" * 100)
    print(f"Failure cohort (positives): n={n_pos}")
    print(f"Success cohort (negatives): n={n_neg}")
    print()

    print("Per-rule violation rates + Fisher exact test (sorted by rate_diff desc):")
    print(
        profile[
            [
                "rule",
                "failure_rate",
                "success_rate",
                "rate_diff",
                "relative_risk",
                "fisher_odds_ratio",
                "fisher_p_value",
                "fail_violations",
                "success_violations",
            ]
        ].to_string(index=False)
    )

    print()
    print(f"Rules notably higher in failures (rate_diff >= {args.min_rate_diff:.3f}):")
    if notable.empty:
        print("None under this threshold.")
    else:
        print(
            notable[
                [
                    "rule",
                    "failure_rate",
                    "success_rate",
                    "rate_diff",
                    "relative_risk",
                    "fisher_odds_ratio",
                    "fisher_p_value",
                    "fail_violations",
                    "success_violations",
                ]
            ].to_string(index=False)
        )

    if args.out_all is not None:
        profile.to_csv(args.out_all, index=False)
        print(f"\nWrote full profile: {args.out_all}")

    if args.out_notable is not None:
        notable.to_csv(args.out_notable, index=False)
        print(f"Wrote notable rules: {args.out_notable}")


if __name__ == "__main__":
    main()