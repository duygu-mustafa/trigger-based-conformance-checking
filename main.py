"""CLI Entry point for batch conformance checking.

Usage:
    python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet
    python main.py --input icu_event_log.parquet --output conformance_results.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml

from conformance.batch_runner import BatchConformanceRunner
from conformance.rules import build_readiness_assessment_model
from conformance.weighted_scoring import load_constraints_with_weights, score_trace_collection


def _load_constraint_id_lookup(model_path: Path) -> dict[str, str]:
    """Build lookup from constraint labels/ids to canonical constraint id."""
    with model_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    model = data.get("model", {})
    constraints = model.get("constraints", [])

    lookup: dict[str, str] = {}
    for c in constraints:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not cid:
            continue
        cid = str(cid)
        lookup[cid] = cid
        label = c.get("label")
        if isinstance(label, str) and label.strip():
            lookup[label.strip()] = cid
    return lookup


def _format_id_list(values: list[str]) -> str:
    """Serialize identifiers as a compact, CSV-friendly string."""

    return ";".join(sorted(dict.fromkeys(str(value) for value in values)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch conformance checking.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("icu_event_log.parquet"),
        help="Path to canonical event-log file (recommended) or raw ICU events file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("conformance_results.csv"),
        help="Path to save the aggregated results CSV.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Number of stay_ids to process in each memory-clearing batch.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"Error: Input file {args.input} does not exist.")
        return

    # 1. Initialize the Batch Runner with the Readiness model
    runner = BatchConformanceRunner(
        input_file=args.input,
        model_builder=build_readiness_assessment_model
    )

    # 2. Execute batch processing
    results = runner.run_all(batch_size=args.batch_size)

    # 3. Process results into a flat dataframe for analysis
    if results:
        # Load weights for scoring
        weights_path = Path(__file__).resolve().parent / "configs" / "declare" / "weights.yaml"
        model_path = Path(__file__).resolve().parent / "configs" / "declare" / "readiness_assessment.yaml"

        scoring_constraints = load_constraints_with_weights(model_path, weights_path)
        constraint_id_lookup = _load_constraint_id_lookup(model_path)
        scores_df, detail_df, population_kpi = score_trace_collection(
            trace_results=results,
            constraints=scoring_constraints,
            constraint_id_lookup=constraint_id_lookup,
        )

        score_map = {str(row["case_id"]): float(row["score"]) for _, row in scores_df.iterrows()}
        output_rows = []
        for r in results:
            num_sbts = 0
            if r.constraint_results:
                num_sbts = r.constraint_results[0].num_activations

            num_fails = 1 if not r.is_conformant else 0
            violated_ids = []
            satisfied_ids = []
            for cr in r.constraint_results:
                canonical_id = constraint_id_lookup.get(cr.constraint_id, cr.constraint_id)
                if cr.outcome.name == "VIOLATED":
                    violated_ids.append(canonical_id)
                elif cr.outcome.name == "SATISFIED":
                    satisfied_ids.append(canonical_id)

            trace_score = score_map.get(str(r.case_id), float("nan"))
            output_rows.append({
                "stay_id": r.case_id,
                "is_conformant": r.is_conformant,
                "trace_score": trace_score,
                "conformance_score": float(trace_score * 100.0) if not pd.isna(trace_score) else float("nan"),
                "num_sbts": num_sbts,
                "num_fails": num_fails,
                "num_successes": len(satisfied_ids),
                "violated": _format_id_list(violated_ids),
                "satisfied": _format_id_list(satisfied_ids),
            })

        df = pd.DataFrame(output_rows)
        df.to_csv(args.output, index=False)
        print(f"Successfully processed {len(results)} stays.")
        print(f"Population KPI (Sugeno): {population_kpi:.4f}" if not pd.isna(population_kpi) else "Population KPI (Sugeno): n/a")
        print(f"Results saved to {args.output}")
    else:
        print("No results generated.")


if __name__ == "__main__":
    main()
