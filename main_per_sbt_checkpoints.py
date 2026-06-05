"""CLI for conformance checking over checkpoint snapshots.

This runner scans a checkpoint folder, evaluates each numbered
`icu_event_log.checkpoint_*.parquet` snapshot in ascending order, and writes
each checkpoint's results to disk immediately so memory stays bounded.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
import re
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from conformance.batch_runner import BatchConformanceRunner
from conformance.checker import evaluate_constraint
from derive.pipeline import raw_to_event_log
from conformance.results import ConformanceOutcome

from main_per_sbt import (
    INT_COMPOSITE_ID,
    _build_combined_model,
    _build_trigger_episodes,
    _evaluate_composite_for_attempt,
    _load_combined_constraint_id_lookup,
)


CHECKPOINT_PATTERN = re.compile(r"icu_event_log\.checkpoint_(\d+)\.parquet$")


def _discover_checkpoint_files(checkpoint_dir: Path) -> list[tuple[int, Path]]:
    checkpoints: list[tuple[int, Path]] = []
    for path in checkpoint_dir.iterdir():
        if not path.is_file():
            continue
        match = CHECKPOINT_PATTERN.fullmatch(path.name)
        if not match:
            continue
        checkpoints.append((int(match.group(1)), path))
    return sorted(checkpoints, key=lambda item: item[0])


def _load_checkpoint_results_columns() -> list[str]:
    return [
        "checkpoint_index",
        "checkpoint_file",
        "checkpoint_name",
        "stay_id",
        "episode_index",
        "episode_start",
        "episode_end",
        "ventilation_start",
        "ventilation_end",
        "sbt_attempt",
        "sbt_start",
        "sbt_end",
        "sbt_outcome",
        "mandatory_violated_constraints",
        "mandatory_satisfied_constraints",
        "mandatory_vacuous_constraints",
        "info_violated_constraints",
        "info_satisfied_constraints",
        "info_vacuous_constraints",
        "composite_interventions",
        "composite_note",
        "violation_forensics",
        "satisfaction_forensics",
        "num_mandatory_violations",
        "num_mandatory_satisfactions",
    ]


def _evaluate_stay_for_checkpoint(
    runner: BatchConformanceRunner,
    stay_id: int,
    constraint_id_lookup: dict[str, str],
    checkpoint_index: int,
    checkpoint_file: Path,
) -> list[dict[str, object]]:
    df_full = runner.con.execute(
        f"SELECT * FROM events WHERE {runner._batch_key_column} = ?",
        [str(stay_id)],
    ).df().sort_values("timestamp")

    if df_full.empty:
        return []

    df_full = df_full.copy()
    df_full["timestamp"] = pd.to_datetime(df_full["timestamp"], errors="coerce")
    df_full = df_full.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df_full.empty:
        return []

    # Convert to canonical event log with derived activities if needed
    if not runner._is_event_log_input:
        event_log = raw_to_event_log(df_full)
    else:
        event_log = df_full.copy()

    episodes = _build_trigger_episodes(event_log)
    if not episodes:
        return []

    sbt_starts = (
        event_log[event_log["activity"] == "SBTStarted"]
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
    )
    vent_starts = event_log[event_log["activity"] == "InvasiveVentilationStarted"]

    rows: list[dict[str, object]] = []
    attempt_index = 0
    for episode_idx, (episode_start, episode_end) in enumerate(episodes, start=1):
        episode_df = event_log[
            (event_log["timestamp"] >= episode_start)
            & (event_log["timestamp"] < episode_end)
        ].copy()
        if episode_df.empty:
            continue

        sbt_in_episode = sbt_starts[
            (sbt_starts["timestamp"] >= episode_start)
            & (sbt_starts["timestamp"] < episode_end)
        ]

        sbt_start: pd.Timestamp | None = None
        if not sbt_in_episode.empty:
            sbt_start = sbt_in_episode.iloc[0]["timestamp"]
            attempt_index += 1

        sbt_end: pd.Timestamp | None = None
        if sbt_start is not None:
            outcome_end = sbt_start + pd.Timedelta(hours=48)
            matching_vent = vent_starts[
                (vent_starts["timestamp"] > sbt_start)
                & (vent_starts["timestamp"] <= outcome_end)
            ]

            if not matching_vent.empty:
                outcome_val = "Failure (Reventilated <48h)"
                sbt_end = matching_vent.iloc[0]["timestamp"]
            else:
                last_relevant = df_full[
                    df_full["activity"].isin(
                        ["InvasiveVentilationStarted", "SBTStarted", "SBTCompleted"]
                    )
                ].sort_values("timestamp").iloc[-1:]
                if not last_relevant.empty and last_relevant.iloc[0]["activity"] == "InvasiveVentilationStarted":
                    outcome_val = "Failure (Last State: Invasive Vent)"
                else:
                    outcome_val = "Success (No Revent <48h / Last State: SBT)"
                sbt_end = episode_end
        else:
            outcome_val = "No SBT Attempt"

        mandatory_violated: list[str] = []
        mandatory_satisfied: list[str] = []
        mandatory_vacuous: list[str] = []
        informational_violated: list[str] = []
        informational_satisfied: list[str] = []
        informational_vacuous: list[str] = []
        composite_interventions: list[str] = []
        violation_forensics: dict[str, dict] = {}
        satisfaction_forensics: dict[str, dict] = {}

        for constraint in runner.model.constraints:
            raw_constraint_id = getattr(constraint, "id", None) or constraint.label
            canon_id = constraint_id_lookup.get(raw_constraint_id, raw_constraint_id)
            if not canon_id and constraint.label:
                canon_id = constraint_id_lookup.get(constraint.label, constraint.label)
            if not canon_id:
                continue

            if canon_id == INT_COMPOSITE_ID:
                continue

            is_failure_rule = canon_id.startswith("INT-")
            # Use the general checker for all constraints; derived activities
            # (e.g., an SBTFailed emitted at re-ventilation time) are available
            # in `event_log` so no special-case manual evaluation is required.
            res = evaluate_constraint(
                case_id=str(stay_id),
                trace_df=episode_df,
                constraint=constraint,
            )
            outcome = res.outcome
            manual_forensics = None

            if outcome == ConformanceOutcome.VACUOUS:
                target_vacuous = mandatory_vacuous
                if is_failure_rule:
                    target_vacuous = informational_vacuous
                target_vacuous.append(canon_id)
                continue

            target_violated = mandatory_violated
            target_satisfied = mandatory_satisfied
            if is_failure_rule:
                target_violated = informational_violated
                target_satisfied = informational_satisfied

            if outcome == ConformanceOutcome.VIOLATED:
                target_violated.append(canon_id)
                f_data = (
                    manual_forensics
                    if manual_forensics
                    else ({"deltas": res.violation_deltas, "delay_seconds": res.delay_seconds} if res else None)
                )
                if f_data:
                    violation_forensics[canon_id] = f_data
            elif outcome == ConformanceOutcome.SATISFIED:
                target_satisfied.append(canon_id)
                f_data = (
                    manual_forensics
                    if manual_forensics
                    else ({"deltas": res.satisfaction_deltas, "delay_seconds": res.delay_seconds} if res else None)
                )
                if f_data:
                    satisfaction_forensics[canon_id] = f_data

        composite_reason = None
        if sbt_start is not None and attempt_index > 1:
            composite_ok, composite_interventions, composite_reason = _evaluate_composite_for_attempt(
                df_full=event_log,
                sbt_start=sbt_start,
            )
            if composite_ok:
                mandatory_satisfied.append(INT_COMPOSITE_ID)
            else:
                mandatory_violated.append(INT_COMPOSITE_ID)

        vent_end_rows = episode_df[episode_df["activity"] == "InvasiveVentilationEnded"].sort_values("timestamp")
        vent_end: pd.Timestamp | None = None
        if not vent_end_rows.empty:
            vent_end = vent_end_rows.iloc[0]["timestamp"]
        else:
            vent_end = df_full["timestamp"].max()

        rows.append(
            {
                "checkpoint_index": checkpoint_index,
                "checkpoint_file": str(checkpoint_file),
                "checkpoint_name": checkpoint_file.name,
                "stay_id": stay_id,
                "episode_index": episode_idx,
                "episode_start": str(episode_start),
                "episode_end": str(episode_end),
                "ventilation_start": str(episode_start),
                "ventilation_end": str(vent_end),
                "sbt_attempt": attempt_index if sbt_start is not None else "",
                "sbt_start": str(sbt_start) if sbt_start is not None else "",
                "sbt_end": str(sbt_end) if sbt_end is not None else "",
                "sbt_outcome": outcome_val,
                "mandatory_violated_constraints": ";".join(sorted(set(mandatory_violated))),
                "mandatory_satisfied_constraints": ";".join(sorted(set(mandatory_satisfied))),
                "mandatory_vacuous_constraints": ";".join(sorted(set(mandatory_vacuous))),
                "info_violated_constraints": ";".join(sorted(set(informational_violated))),
                "info_satisfied_constraints": ";".join(sorted(set(informational_satisfied))),
                "info_vacuous_constraints": ";".join(sorted(set(informational_vacuous))),
                "composite_interventions": ";".join(composite_interventions),
                "composite_note": composite_reason or "",
                "violation_forensics": json.dumps(violation_forensics),
                "satisfaction_forensics": json.dumps(satisfaction_forensics),
                "num_mandatory_violations": len(set(mandatory_violated)),
                "num_mandatory_satisfactions": len(set(mandatory_satisfied)),
            }
        )

    return rows


def _append_summary_row(summary_path: Path, row: dict[str, object]) -> None:
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not summary_path.exists()
    fieldnames = [
        "checkpoint_index",
        "checkpoint_file",
        "result_file",
        "stay_count",
        "result_row_count",
        "status",
    ]
    with summary_path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()


def _write_checkpoint_result_file(
    checkpoint_file: Path,
    checkpoint_index: int,
    results_dir: Path,
    constraint_id_lookup: dict[str, str],
) -> dict[str, object]:
    results_dir.mkdir(parents=True, exist_ok=True)
    result_file = results_dir / f"{checkpoint_file.stem}_results.csv"

    runner = BatchConformanceRunner(input_file=checkpoint_file, model_builder=_build_combined_model)
    stay_ids = runner.get_stay_ids()

    columns = _load_checkpoint_results_columns()
    rows_written = 0
    with result_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()

        for stay_id in tqdm(stay_ids, desc=f"{checkpoint_file.name}"):
            rows = _evaluate_stay_for_checkpoint(
                runner=runner,
                stay_id=stay_id,
                constraint_id_lookup=constraint_id_lookup,
                checkpoint_index=checkpoint_index,
                checkpoint_file=checkpoint_file,
            )
            for row in rows:
                writer.writerow(row)
                rows_written += 1
                handle.flush()

    del runner
    gc.collect()

    return {
        "checkpoint_index": checkpoint_index,
        "checkpoint_file": str(checkpoint_file),
        "result_file": str(result_file),
        "stay_count": len(stay_ids),
        "result_row_count": rows_written,
        "status": "ok",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run per-SBT conformance over checkpoint snapshots.")
    parser.add_argument(
        "--checkpoint-dir",
        type=Path,
        required=True,
        default=Path("data/icu_event_log_checkpoints"),
        help="Directory containing icu_event_log.checkpoint_*.parquet snapshots.",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("data/results/checkpoint_trigger_results"),
        help="Directory where per-checkpoint result CSVs will be written.",
    )
    parser.add_argument(
        "--summary-file",
        type=Path,
        default=None,
        help="Optional summary CSV path (default: <results-dir>/checkpoint_summary.csv).",
    )
    parser.add_argument(
        "--max-checkpoints",
        type=int,
        default=None,
        help="Optional limit for how many checkpoints to process.",
    )
    args = parser.parse_args()

    if not args.checkpoint_dir.exists():
        raise FileNotFoundError(f"Checkpoint directory does not exist: {args.checkpoint_dir}")
    if not args.checkpoint_dir.is_dir():
        raise NotADirectoryError(f"Checkpoint path is not a directory: {args.checkpoint_dir}")
    if args.max_checkpoints is not None and args.max_checkpoints <= 0:
        raise ValueError("--max-checkpoints must be > 0 when provided")

    checkpoint_files = _discover_checkpoint_files(args.checkpoint_dir)
    if not checkpoint_files:
        raise RuntimeError(
            f"No checkpoint parquet files found in {args.checkpoint_dir}. Expected icu_event_log.checkpoint_*.parquet"
        )

    if args.max_checkpoints is not None:
        checkpoint_files = checkpoint_files[: args.max_checkpoints]

    model_paths = [
        Path("configs/declare/readiness_assessment.yaml"),
        Path("configs/declare/sbt_execution.yaml"),
        Path("configs/declare/failure_correction.yaml"),
    ]
    constraint_id_lookup = _load_combined_constraint_id_lookup(model_paths)

    summary_path = args.summary_file or (args.results_dir / "checkpoint_summary.csv")
    args.results_dir.mkdir(parents=True, exist_ok=True)

    print(f"Processing {len(checkpoint_files)} checkpoint snapshots from {args.checkpoint_dir}...")
    for checkpoint_index, checkpoint_file in checkpoint_files:
        summary_row = _write_checkpoint_result_file(
            checkpoint_file=checkpoint_file,
            checkpoint_index=checkpoint_index,
            results_dir=args.results_dir,
            constraint_id_lookup=constraint_id_lookup,
        )
        _append_summary_row(summary_path, summary_row)
        print(f"Saved {summary_row['result_row_count']} rows for {checkpoint_file.name} -> {summary_row['result_file']}")

    print(f"Checkpoint summary saved to {summary_path}")


if __name__ == "__main__":
    main()