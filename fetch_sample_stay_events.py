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


DEFAULT_STAY_IDS = [34961518, 37053432, 30934380, 37510196]


def _run_conformance(df, stay_id: int) -> None:
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

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ICU event-level rows for selected stay IDs")
    parser.add_argument(
        "--out-dir",
        type=str,
        default=".",
        help="Directory where one CSV per stay_id is written",
    )
    parser.add_argument(
        "--skip-conformance",
        action="store_true",
        help="Skip conformance checking",
    )
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for stay_id in DEFAULT_STAY_IDS:
        print(f"\n=== stay_id={stay_id} ===")
        out_csv = out_dir / f"icu_stay_{stay_id}_event_level.csv"

        if out_csv.exists():
            df = pd.read_csv(out_csv, low_memory=False)
            print(f"Loaded existing extract: {out_csv}")
        else:
            df = fetch_icu_events_for_stay(stay_id=stay_id)
            print(f"Fetched rows: {len(df)} for stay_id={stay_id}")
            if len(df) == 0:
                print("No rows returned. Check stay_id, DB schema, or credentials.")
                continue

            df.to_csv(out_csv, index=False)
            print(f"Saved event-level extract to: {out_csv}")

        if not args.skip_conformance:
            _run_conformance(df, stay_id=stay_id)

if __name__ == "__main__":
    main()
