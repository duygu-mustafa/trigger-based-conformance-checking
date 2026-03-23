"""CLI example: fetch timestamped ICU events for one stay_id."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import pandas as pd

# Allow running this file directly: python fetch_sample_stay_events.py
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.fetch_events import fetch_icu_events_for_stay
from conformance.rules import build_readiness_assessment_model, build_sbt_execution_model
from conformance.checker import check_log_conformance
from derive import raw_to_event_log

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ICU event-level rows for a sample stay_id")
    parser.add_argument("--stay-id", type=int, default=37510196, help="ICU stay_id to query")
    parser.add_argument(
        "--out-csv",
        type=str,
        default="icu_stay_37510196_event_level.csv",
        help="Output CSV path",
    )
    args = parser.parse_args()

    # df = fetch_icu_events_for_stay(stay_id=args.stay_id)

    # print(f"Fetched rows: {len(df)} for stay_id={args.stay_id}")
    # if len(df) == 0:
    #     print("No rows returned. Check stay_id, DB schema, or credentials.")
    #     return

    # print("\nColumns:")
    # print(", ".join(df.columns))

    # print("\nFirst 20 rows:")
    # print(df.head(20).to_string(index=False))

    # print("\nRows by source table:")
    # print(df["source_table"].value_counts().to_string())

    # df.to_csv(args.out_csv, index=False)
    # print(f"\nSaved event-level extract to: {args.out_csv}")
    df = pd.read_csv(args.out_csv, low_memory=False)

    print("\n--- Conformance Checking ---")
    # Prepare canonical event log through config-driven mapping.
    event_log = raw_to_event_log(
        df,
        pipeline_config_path=PROJECT_ROOT / "configs" / "pipeline.yaml",
        item_dictionary_path=PROJECT_ROOT / "configs" / "item_dictionary.yaml",
        activity_mapping_path=PROJECT_ROOT / "configs" / "activity_mapping.yaml",
    )

    # Load readiness clinical model
    model_ready = build_readiness_assessment_model()
    print(f"Evaluating model: {model_ready.name}")

    # Run checker
    results = check_log_conformance(event_log, model_ready)

    for trace_result in results:
        print(f"\nTrace ID: {trace_result.case_id}")
        for cr in trace_result.constraint_results:
            status = cr.outcome.name
            print(f"  [{status:9}] {cr.constraint_id}")
            if cr.violation_reason:
                print(f"              Reason: {cr.violation_reason}")

    model_sbt = build_sbt_execution_model()
    print(f"\nEvaluating model: {model_sbt.name}")
    results_sbt = check_log_conformance(event_log, model_sbt)   
    for trace_result in results_sbt:
        print(f"\nTrace ID: {trace_result.case_id}")
        for cr in trace_result.constraint_results:
            status = cr.outcome.name
            print(f"  [{status:9}] {cr.constraint_id}")
            if cr.violation_reason:
                print(f"              Reason: {cr.violation_reason}")

if __name__ == "__main__":
    main()
