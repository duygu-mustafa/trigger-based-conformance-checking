"""Export per-constraint stats (incl. Bonferroni/FDR) from summary.json to CSV for thesis tables.

Usage: python derive/export_thesis_stats.py [--input frontend/public/data/summary.json] [--output data/results/thesis_constraint_stats.csv]
"""
import argparse
import csv
import json
from pathlib import Path

COLUMNS = [
    "constraint_id", "constraint_label", "template", "rule_class",
    "outcome_variable", "n_censored",
    "count", "count_success", "count_failure", "count_vacuous", "count_satisfied",
    "violation_rate_success", "violation_rate_failure", "rate_diff",
    "n_exposed", "n_unexposed", "a", "b", "c", "d",
    "odds_ratio", "odds_ratio_low", "odds_ratio_high",
    "risk_ratio", "rr_ci_low", "rr_ci_high",
    "p_value_raw", "p_value_bonferroni", "p_value_fdr",
    "is_significant", "is_significant_bonferroni", "is_significant_fdr",
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="frontend/public/data/summary.json")
    parser.add_argument("--output", default="data/results/thesis_constraint_stats.csv")
    args = parser.parse_args()

    summary = json.loads(Path(args.input).read_text(encoding="utf-8"))
    rows = summary["violation_frequency"]
    rows.sort(key=lambda r: (r.get("p_value_raw") is None, r.get("p_value_raw") or 0.0))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} constraints -> {out}")


if __name__ == "__main__":
    main()
