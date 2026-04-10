"""CLI Entry point for batch conformance checking.

Usage:
    python run_conformance_batch.py --input data/raw/icu_event_level_sbt.parquet --output results.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from conformance.batch_runner import BatchConformanceRunner
from conformance.rules import build_readiness_assessment_model
from conformance.weighted_scoring import load_constraints_with_weights, compute_w_max


def main() -> None:
    parser = argparse.ArgumentParser(description="Run batch conformance checking.")
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Path to the single materialized ICU events file (Parquet or CSV).",
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
        default=50,
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
        
        output_rows = []
        for r in results:
            # Count SBTs (Started events)
            # Results are at the trace level, but we can look at the constraint results
            # to see how many activations occurred for RC-DP-01 (or any readiness constraint)
            # since they all activate on SBTStarted.
            num_sbts = 0
            if r.constraint_results:
                # All RC-DP constraints activate on SBTStarted
                num_sbts = r.constraint_results[0].num_activations
            
            # Count Fails (Violated traces)
            num_fails = 1 if not r.is_conformant else 0
            
            # Compute score (weighted penalty)
            # compute_trace_scores returns a list of ViolationInstance, but we can 
            # use a simpler approach since we have the results.
            # We'll use the scoring logic from weighted_scoring.py if possible,
            # or just calculate a basic weighted sum here.
            total_penalty = 0.0
            violated_ids = []
            for cr in r.constraint_results:
                if cr.outcome.name == "VIOLATED":
                    # Get w_max for this constraint
                    c_obj = next((c for c in scoring_constraints if c.constraint_id == cr.constraint_id), None)
                    if c_obj:
                        total_penalty += compute_w_max(c_obj) * (cr.num_violated / cr.num_activations if cr.num_activations > 0 else 1.0)
                    violated_ids.append(cr.constraint_id)
            
            output_rows.append({
                "stay_id": r.case_id,
                "is_conformant": r.is_conformant,
                "conformance_score": max(0, 100 - (total_penalty * 10)), # Scaled score
                "num_sbts": num_sbts,
                "num_fails": num_fails,
                "violations": ";".join(violated_ids)
            })
            
        df = pd.DataFrame(output_rows)
        df.to_csv(args.output, index=False)
        print(f"Successfully processed {len(results)} stays.")
        print(f"Results saved to {args.output}")
    else:
        print("No results generated.")


if __name__ == "__main__":
    main()
