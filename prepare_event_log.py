"""Build the canonical event log from the raw MIMIC-IV extraction.

Reads the raw event file (database/materialize_all_icu_events.py), converts each
selected stay with derive.pipeline.raw_to_event_log, and writes the canonical
event log (Parquet or CSV). Stays are processed one at a time into a temporary
DuckDB database; progress is checkpointed so an interrupted run can --resume.

Stay selection: by default all stays with a `ventilator_setting` row
(--source-table-filter), randomly sampled unless --use-all-data is given.

Usage:
    python prepare_event_log.py --input data/icu_event_level_sbt.parquet \
        --output data/final/icu_event_log_full.parquet --use-all-data
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd
from tqdm import tqdm

from derive import raw_to_event_log


def _normalize_event_log_for_duckdb(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize object-heavy columns to stable scalar dtypes for DuckDB."""
    out = df.copy()

    # `attrs` may contain Python dicts with varying keys across rows.
    # Store as JSON text to keep schema consistent across batches.
    if "attrs" in out.columns:
        out["attrs"] = out["attrs"].map(
            lambda v: None
            if pd.isna(v)
            else json.dumps(v, sort_keys=True)
            if isinstance(v, (dict, list, tuple))
            else str(v)
        )

    if "case_id" in out.columns:
        out["case_id"] = out["case_id"].astype(str)

    return out


def _create_view(con: duckdb.DuckDBPyConnection, input_file: Path, view_name: str = "raw_events") -> None:
    ext = input_file.suffix.lower()
    file_path = str(input_file).replace("'", "''")

    if ext in {".parquet", ".pq"}:
        con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_parquet('{file_path}')")
    elif ext in {".csv", ".gz"}:
        con.execute(f"CREATE VIEW {view_name} AS SELECT * FROM read_csv_auto('{file_path}')")
    else:
        raise ValueError(f"Unsupported input format: {ext}")


def _export_event_log(output_con: duckdb.DuckDBPyConnection, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    escaped = str(output_path).replace("'", "''")
    ext = output_path.suffix.lower()

    if ext in {".parquet", ".pq"}:
        output_con.execute(
            f"COPY event_log TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    elif ext in {".csv", ".gz"}:
        output_con.execute(
            f"COPY event_log TO '{escaped}' (FORMAT CSV, HEADER TRUE)"
        )
    else:
        raise ValueError("Output must be .parquet/.pq/.csv/.gz")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _state_file_default(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".state.json")


def _backup_dir_default(output_path: Path) -> Path:
    return output_path.parent / f"{output_path.stem}_checkpoints"


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")
    tmp_path.replace(path)


def _load_state(path: Path) -> dict | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _run_signature(args: argparse.Namespace) -> dict:
    pinned = [int(raw_stay_id) for raw_stay_id in (args.pin_stay_id or [])]
    return {
        "input": str(args.input.resolve()),
        "use_all_data": bool(args.use_all_data),
        "sample_source": str(args.sample_source.resolve()),
        "source_table_filter": args.source_table_filter,
        "sample_size": args.sample_size,
        "sample_seed": args.sample_seed,
        "pinned_stay_ids": pinned,
    }


def _event_log_table_exists(output_con: duckdb.DuckDBPyConnection) -> bool:
    row = output_con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_name = 'event_log'
        """
    ).fetchone()
    return bool(row and row[0] > 0)


def _export_checkpoint_backup(
    output_con: duckdb.DuckDBPyConnection,
    output_path: Path,
    backup_dir: Path,
    processed_count: int,
) -> None:
    if not _event_log_table_exists(output_con):
        return

    backup_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_name = f"{output_path.stem}.checkpoint_{processed_count:07d}{output_path.suffix}"
    checkpoint_path = backup_dir / checkpoint_name
    latest_path = backup_dir / f"{output_path.stem}.latest{output_path.suffix}"

    _export_event_log(output_con, checkpoint_path)
    _export_event_log(output_con, latest_path)


def _seed_output_from_checkpoint(
    output_con: duckdb.DuckDBPyConnection,
    checkpoint_path: Path,
) -> int:
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Seed checkpoint does not exist: {checkpoint_path}")

    escaped = str(checkpoint_path).replace("'", "''")
    output_con.execute("DROP TABLE IF EXISTS event_log")
    output_con.execute(f"CREATE TABLE event_log AS SELECT * FROM read_parquet('{escaped}')")

    row = output_con.execute("SELECT COUNT(*) FROM event_log").fetchone()
    return int(row[0]) if row else 0


def _checkpoint_skip_count(path: Path) -> int:
    match = re.search(r"checkpoint_(\d+)", path.stem)
    if not match:
        raise ValueError(
            f"Could not derive skip count from checkpoint name: {path.name}. "
            "Use --seed-skip-count explicitly."
        )
    return int(match.group(1))


def _required_raw_columns(available_columns: set[str]) -> list[str]:
    """Return a minimal raw column set needed by raw_to_event_log."""
    preferred = [
        "source_table",
        "itemid",
        "event_time",
        "value_text",
        "value_num",
        "value_uom",
        "label",
        "case_id",
        "stay_id",
        "subject_id",
        "charttime",
        "starttime",
        "endtime",
        "storetime",
        # fallbacks used by the normalizer
        "value",
        "valuenum",
        "valueuom",
    ]
    selected = [c for c in preferred if c in available_columns]
    # stay_id is mandatory for batching logic
    if "stay_id" not in selected:
        selected.append("stay_id")
    return selected


def _stay_ids_from_source_table(
    source_con: duckdb.DuckDBPyConnection,
    source_table: str,
    source_relation: str = "raw_events",
) -> list[int]:
    """Return distinct stay_ids that have at least one row from a given source table."""
    rows = source_con.execute(
        f"""
        SELECT DISTINCT stay_id
        FROM {source_relation}
        WHERE stay_id IS NOT NULL
          AND source_table = ?
        ORDER BY stay_id
        """,
        [source_table],
    ).fetchall()
    return [int(row[0]) for row in rows]


def _is_memory_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(token in text for token in ["out of memory", "memory", "allocation", "cannot allocate"])


def _process_batch_recursive(
    source_con: duckdb.DuckDBPyConnection,
    output_con: duckdb.DuckDBPyConnection,
    batch: list[int],
    selected_columns: list[str],
    created_table: bool,
    source_relation: str = "raw_events",
) -> bool:
    """Process a batch, splitting recursively when memory pressure occurs."""
    if not batch:
        return created_table

    placeholders = ",".join(["?"] * len(batch))
    column_sql = ", ".join(selected_columns)

    try:
        raw_df = source_con.execute(
            f"SELECT {column_sql} FROM {source_relation} WHERE stay_id IN ({placeholders})",
            batch,
        ).df()

        if raw_df.empty:
            return created_table

        event_log_df = raw_to_event_log(raw_df)
        if event_log_df.empty:
            return created_table

        event_log_df = _normalize_event_log_for_duckdb(event_log_df)

        output_con.register("event_log_batch", event_log_df)
        if not created_table:
            output_con.execute("CREATE TABLE event_log AS SELECT * FROM event_log_batch")
            created_table = True
        else:
            output_con.execute("INSERT INTO event_log SELECT * FROM event_log_batch")
        output_con.unregister("event_log_batch")

        del raw_df, event_log_df
        return created_table
    except Exception as exc:
        # If memory is tight, split the batch and retry recursively.
        if _is_memory_error(exc) and len(batch) > 1:
            mid = len(batch) // 2
            created_table = _process_batch_recursive(
                source_con,
                output_con,
                batch[:mid],
                selected_columns,
                created_table,
                source_relation=source_relation,
            )
            created_table = _process_batch_recursive(
                source_con,
                output_con,
                batch[mid:],
                selected_columns,
                created_table,
                source_relation=source_relation,
            )
            return created_table
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Precompute canonical event-log file from raw ICU events.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/icu_event_level_sbt.parquet"),
        help="Raw ICU events input (Parquet or CSV).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/icu_event_log_full.parquet"),
        help="Output canonical event-log file.",
    )
    parser.add_argument(
        "--use-all-data",
        action="store_true",
        help="Process all candidate stays instead of a random sample.",
    )
    parser.add_argument(
        "--sample-source",
        type=Path,
        default=Path("data/sbt_started_yes_stay_ids.parquet"),
        help="Parquet file with candidate stay_id values; only used when --source-table-filter is empty.",
    )
    parser.add_argument(
        "--source-table-filter",
        type=str,
        default="ventilator_setting",
        help="Restrict processing to stays that contain at least one row from this raw source_table (for example, ventilator_setting).",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Number of random stays to sample (default: all candidates).",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=42,
        help="Random seed for reproducible stay sampling.",
    )
    parser.add_argument(
        "--pin-stay-id",
        action="append",
        default=["35616431", "30031915"],
        help="Stay id to always include in the sampled set (ignored with --use-all-data). "
        "Repeatable; added to the two default example stays.",
    )
    parser.add_argument(
        "--memory-limit",
        type=str,
        default="4GB",
        help="DuckDB memory limit (e.g., 2GB, 4GB).",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from a previous interrupted run if checkpoint state exists.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=None,
        help="Path to resume/checkpoint state JSON (default: <output>.state.json).",
    )
    parser.add_argument(
        "--backup-every",
        type=int,
        default=200,
        help="Export backup snapshot every N processed stays (0 disables periodic backups).",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=None,
        help="Directory for backup checkpoints (default: <output_parent>/<output_stem>_checkpoints).",
    )
    parser.add_argument(
        "--seed-checkpoint",
        type=Path,
        default=None,
        help="Parquet checkpoint used to seed the output event_log table before continuing.",
    )
    parser.add_argument(
        "--seed-skip-count",
        type=int,
        default=None,
        help="Number of candidate stays to skip when resuming from a seeded checkpoint.",
    )
    args = parser.parse_args()

    if args.backup_every < 0:
        raise ValueError("--backup-every must be >= 0")
    if args.seed_skip_count is not None and args.seed_skip_count < 0:
        raise ValueError("--seed-skip-count must be >= 0")
    if args.seed_checkpoint is not None and not args.seed_checkpoint.exists():
        raise FileNotFoundError(f"Seed checkpoint does not exist: {args.seed_checkpoint}")

    state_path = args.state_file or _state_file_default(args.output)
    backup_dir = args.backup_dir or _backup_dir_default(args.output)
    signature = _run_signature(args)

    if not args.input.exists():
        raise FileNotFoundError(f"Input file does not exist: {args.input}")

    if not args.use_all_data and not args.source_table_filter and not args.sample_source.exists():
        raise FileNotFoundError(f"Sample source does not exist: {args.sample_source}")

    source_db_path = args.output.with_suffix(args.output.suffix + ".source.tmp.duckdb")
    output_db_path = args.output.with_suffix(args.output.suffix + ".tmp.duckdb")

    # Rebuild the source DB every run; resume relies on the output DB + state file.
    if source_db_path.exists():
        source_db_path.unlink()
    if not args.resume and output_db_path.exists():
        output_db_path.unlink()
    if not args.resume and state_path.exists():
        state_path.unlink()

    source_con = duckdb.connect(database=str(source_db_path))
    output_con = duckdb.connect(database=str(output_db_path))
    source_con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    output_con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    source_con.execute(f"PRAGMA temp_directory='{args.output.parent.resolve()}'")
    output_con.execute(f"PRAGMA temp_directory='{args.output.parent.resolve()}'")
    created_table = _event_log_table_exists(output_con)

    run_success = False
    interrupted = False
    resume_state = _load_state(state_path) if args.resume else None
    processed_stays: set[int] = set()
    seed_row_count = 0
    effective_seed_checkpoint = args.seed_checkpoint
    effective_seed_skip_count = args.seed_skip_count

    if resume_state:
        prior_seed_checkpoint = resume_state.get("seed_checkpoint")
        prior_seed_skip_count = resume_state.get("seed_skip_count")
        prior_seed_row_count = resume_state.get("seed_row_count")
        if effective_seed_checkpoint is None and prior_seed_checkpoint:
            effective_seed_checkpoint = Path(prior_seed_checkpoint)
        if effective_seed_skip_count is None and prior_seed_skip_count is not None:
            effective_seed_skip_count = int(prior_seed_skip_count)
        if prior_seed_row_count is not None:
            seed_row_count = int(prior_seed_row_count)

    if effective_seed_skip_count is None and effective_seed_checkpoint is not None:
        effective_seed_skip_count = _checkpoint_skip_count(effective_seed_checkpoint)

    try:
        if resume_state:
            prior_signature = resume_state.get("signature")
            if prior_signature != signature:
                raise ValueError(
                    f"State file {state_path} belongs to a different run configuration. "
                    "Use matching args or start fresh without --resume."
                )
            processed_stays = set(int(stay_id) for stay_id in resume_state.get("processed_stays", []))
            if args.seed_checkpoint is not None:
                prior_seed = resume_state.get("seed_checkpoint")
                prior_skip = resume_state.get("seed_skip_count")
                if prior_seed != str(args.seed_checkpoint.resolve()):
                    raise ValueError(
                        f"State file {state_path} belongs to a different seed checkpoint. "
                        "Use matching seed args or start fresh without --resume."
                    )
                if prior_skip != effective_seed_skip_count:
                    raise ValueError(
                        f"State file {state_path} belongs to a different seed skip count. "
                        "Use matching seed args or start fresh without --resume."
                    )
            if processed_stays:
                print(f"Resuming run: {len(processed_stays)} stays already completed.")

        if effective_seed_checkpoint is not None and not created_table:
            seed_row_count = _seed_output_from_checkpoint(output_con, effective_seed_checkpoint)
            created_table = True
            print(
                f"Seeded event_log from {effective_seed_checkpoint} with {seed_row_count} rows."
            )

        _create_view(source_con, args.input)

        columns = {row[1] for row in source_con.execute("PRAGMA table_info('raw_events')").fetchall()}
        if "stay_id" not in columns:
            raise ValueError("Input file must contain stay_id to build event-log batches")
        selected_columns = _required_raw_columns(columns)

        if args.source_table_filter:
            stay_ids = _stay_ids_from_source_table(source_con, args.source_table_filter)
            if not stay_ids:
                raise RuntimeError(
                    f"No stay_ids found for source_table={args.source_table_filter!r}"
                )
            if args.use_all_data:
                print(
                    f"Processing all {len(stay_ids)} stays with source_table={args.source_table_filter!r}"
                )
            else:
                candidate_stays = stay_ids
                print(
                    f"Restricting candidate stays to {len(candidate_stays)} rows with source_table={args.source_table_filter!r}"
                )

                pinned_stays: list[int] = []
                if args.pin_stay_id:
                    candidate_set = set(candidate_stays)
                    missing = []
                    for raw_stay_id in args.pin_stay_id:
                        stay_id = int(raw_stay_id)
                        if stay_id not in candidate_set:
                            missing.append(stay_id)
                        elif stay_id not in pinned_stays:
                            pinned_stays.append(stay_id)
                    if missing:
                        missing_text = ", ".join(str(stay_id) for stay_id in missing)
                        raise ValueError(
                            f"Pinned stay_id(s) not found in overlap candidates: {missing_text}"
                        )

                remaining_candidates = [stay_id for stay_id in candidate_stays if stay_id not in pinned_stays]
                k = min(args.sample_size, len(remaining_candidates)) if args.sample_size is not None else len(remaining_candidates)
                rng = random.Random(args.sample_seed)
                stay_ids = pinned_stays + rng.sample(remaining_candidates, k)

                print(
                    f"Selected {len(stay_ids)} stays "
                    f"(from {len(candidate_stays)} candidate stays filtered by {args.source_table_filter!r})"
                )
        else:
            if args.use_all_data:
                # Get all unique stay_ids from input
                rows = source_con.execute(
                    "SELECT DISTINCT stay_id FROM raw_events WHERE stay_id IS NOT NULL ORDER BY stay_id"
                ).fetchall()
                stay_ids = [int(row[0]) for row in rows]
                print(f"Processing all {len(stay_ids)} stays from input data")
            else:
                # Filter stays by sample-source
                sample_path = str(args.sample_source).replace("'", "''")
                rows = source_con.execute(
                    f"""
                    SELECT DISTINCT r.stay_id
                    FROM raw_events r
                    INNER JOIN read_parquet('{sample_path}') s
                        ON r.stay_id = s.stay_id
                    WHERE r.stay_id IS NOT NULL
                    ORDER BY r.stay_id
                    """
                ).fetchall()
                candidate_stays = [int(row[0]) for row in rows]
                candidate_stays.sort()

                if not candidate_stays:
                    raise RuntimeError("No overlapping stay_ids found between input and sample-source")

                pinned_stays: list[int] = []
                if args.pin_stay_id:
                    candidate_set = set(candidate_stays)
                    missing = []
                    for raw_stay_id in args.pin_stay_id:
                        stay_id = int(raw_stay_id)
                        if stay_id not in candidate_set:
                            missing.append(stay_id)
                        elif stay_id not in pinned_stays:
                            pinned_stays.append(stay_id)
                    if missing:
                        missing_text = ", ".join(str(stay_id) for stay_id in missing)
                        raise ValueError(
                            f"Pinned stay_id(s) not found in overlap candidates: {missing_text}"
                        )

                remaining_candidates = [stay_id for stay_id in candidate_stays if stay_id not in pinned_stays]
                k = min(args.sample_size, len(remaining_candidates)) if args.sample_size is not None else len(remaining_candidates)
                rng = random.Random(args.sample_seed)
                stay_ids = pinned_stays + rng.sample(remaining_candidates, k)

                print(
                    f"Selected {len(stay_ids)} stays "
                    f"(from {len(candidate_stays)} overlap candidates)"
                )

        if effective_seed_skip_count is None:
            effective_seed_skip_count = 0
        if effective_seed_skip_count > 0:
            if effective_seed_skip_count > len(stay_ids):
                raise ValueError(
                    f"Seed skip count {effective_seed_skip_count} exceeds available candidate stays {len(stay_ids)}"
                )
            skipped_seed_stays = stay_ids[:effective_seed_skip_count]
            stay_ids = stay_ids[effective_seed_skip_count:]
            print(
                f"Skipping first {len(skipped_seed_stays)} candidate stays from seeded checkpoint."
            )

        pending_stay_ids = [stay_id for stay_id in stay_ids if stay_id not in processed_stays]
        if processed_stays:
            print(f"Remaining stays to process: {len(pending_stay_ids)}")

        if args.resume and processed_stays and not created_table:
            raise RuntimeError(
                "Resume state exists but event_log table is missing in temp DB. "
                "Remove state/temp files and rerun from scratch."
            )

        if not processed_stays:
            created_at = _utc_now_iso()
            _write_json_atomic(
                state_path,
                {
                    "version": 1,
                    "created_at": created_at,
                    "updated_at": created_at,
                    "signature": signature,
                    "total_stays": len(stay_ids),
                    "processed_stays": [],
                    "output_tmp_db": str(output_db_path.resolve()),
                    "seed_checkpoint": str(effective_seed_checkpoint.resolve()) if effective_seed_checkpoint is not None else None,
                    "seed_skip_count": effective_seed_skip_count,
                    "seed_row_count": seed_row_count,
                },
            )

        for idx, stay_id in enumerate(tqdm(pending_stay_ids, desc="Preparing event log"), start=1):
            created_table = _process_batch_recursive(
                source_con=source_con,
                output_con=output_con,
                batch=[stay_id],
                selected_columns=selected_columns,
                created_table=created_table,
                source_relation="raw_events",
            )

            processed_stays.add(stay_id)
            processed_count = len(processed_stays)
            # Include any seeded skip count so checkpoint filenames reflect absolute progress
            total_processed = processed_count + (effective_seed_skip_count or 0)

            _write_json_atomic(
                state_path,
                {
                    "version": 1,
                    "created_at": (resume_state or {}).get("created_at", _utc_now_iso()),
                    "updated_at": _utc_now_iso(),
                    "signature": signature,
                    "total_stays": len(stay_ids),
                    "processed_stays": sorted(processed_stays),
                    "last_completed_stay_id": stay_id,
                    "output_tmp_db": str(output_db_path.resolve()),
                    "seed_checkpoint": str(effective_seed_checkpoint.resolve()) if effective_seed_checkpoint is not None else None,
                    "seed_skip_count": effective_seed_skip_count,
                    "seed_row_count": seed_row_count,
                },
            )

            # Use absolute processed count (including seed offset) for export trigger and filename
            if args.backup_every > 0 and created_table and (total_processed % args.backup_every == 0 or idx == len(pending_stay_ids)):
                _export_checkpoint_backup(
                    output_con=output_con,
                    output_path=args.output,
                    backup_dir=backup_dir,
                    processed_count=total_processed,
                )
                print(f"Checkpoint backup saved at processed={total_processed}: {backup_dir}")

        if not created_table:
            raise RuntimeError("No event-log rows were generated from input")

        _export_event_log(output_con, args.output)
        print(f"Saved event log: {args.output}")
        run_success = True
    except KeyboardInterrupt:
        interrupted = True
        print("Interrupted by user; checkpoint state and temp DB kept for --resume.")
    finally:
        source_con.close()
        output_con.close()

        if source_db_path.exists():
            source_db_path.unlink()

        if run_success:
            if output_db_path.exists():
                output_db_path.unlink()
            if state_path.exists():
                state_path.unlink()
        elif not interrupted:
            print(
                f"Run failed; resume artifacts kept: temp DB={output_db_path}, state={state_path}"
            )


if __name__ == "__main__":
    main()