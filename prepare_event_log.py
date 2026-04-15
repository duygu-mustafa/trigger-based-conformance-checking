"""Precompute canonical event-log rows from raw ICU events.

Usage:
    python prepare_event_log.py --input icu_event_level_sbt.parquet --output icu_event_log.parquet
"""

from __future__ import annotations

import argparse
import json
import random
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


def _create_view(con: duckdb.DuckDBPyConnection, input_file: Path) -> None:
    ext = input_file.suffix.lower()
    file_path = str(input_file).replace("'", "''")

    if ext in {".parquet", ".pq"}:
        con.execute(f"CREATE VIEW raw_events AS SELECT * FROM read_parquet('{file_path}')")
    elif ext in {".csv", ".gz"}:
        con.execute(f"CREATE VIEW raw_events AS SELECT * FROM read_csv_auto('{file_path}')")
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
        default=Path("icu_event_level_sbt.parquet"),
        help="Raw ICU events input (Parquet or CSV).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("icu_event_log.parquet"),
        help="Output canonical event-log file.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Deprecated: processing is forced to one stay_id at a time.",
    )
    parser.add_argument(
        "--sample-source",
        type=Path,
        default=Path("sbt_started_yes_stay_ids.parquet"),
        help="Parquet file containing candidate stay_id values for sampling.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=1000,
        help="Number of random stay_ids to process from sample-source.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=42,
        help="Random seed for reproducible stay sampling.",
    )
    parser.add_argument(
        "--memory-limit",
        type=str,
        default="4GB",
        help="DuckDB memory limit (e.g., 2GB, 4GB).",
    )
    args = parser.parse_args()

    if args.batch_size != 1:
        print("Note: forcing one-stay-at-a-time processing; ignoring --batch-size.")

    if not args.input.exists():
        raise FileNotFoundError(f"Input file does not exist: {args.input}")
    if not args.sample_source.exists():
        raise FileNotFoundError(f"Sample source does not exist: {args.sample_source}")

    source_db_path = args.output.with_suffix(args.output.suffix + ".source.tmp.duckdb")
    output_db_path = args.output.with_suffix(args.output.suffix + ".tmp.duckdb")

    # Clean up stale temp database from interrupted prior runs.
    if source_db_path.exists():
        source_db_path.unlink()
    if output_db_path.exists():
        output_db_path.unlink()

    source_con = duckdb.connect(database=str(source_db_path))
    output_con = duckdb.connect(database=str(output_db_path))
    source_con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    output_con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    source_con.execute(f"PRAGMA temp_directory='{args.output.parent.resolve()}'")
    output_con.execute(f"PRAGMA temp_directory='{args.output.parent.resolve()}'")
    output_con.execute("DROP TABLE IF EXISTS event_log")

    created_table = False

    try:
        _create_view(source_con, args.input)

        columns = {row[1] for row in source_con.execute("PRAGMA table_info('raw_events')").fetchall()}
        if "stay_id" not in columns:
            raise ValueError("Input file must contain stay_id to build event-log batches")
        selected_columns = _required_raw_columns(columns)

        sample_path = str(args.sample_source).replace("'", "''")
        rows = source_con.execute(
            f"""
            SELECT DISTINCT r.stay_id
            FROM raw_events r
            INNER JOIN read_parquet('{sample_path}') s
                ON r.stay_id = s.stay_id
            WHERE r.stay_id IS NOT NULL
            """
        ).fetchall()
        candidate_stays = [int(row[0]) for row in rows]

        if not candidate_stays:
            raise RuntimeError("No overlapping stay_ids found between input and sample-source")

        k = min(args.sample_size, len(candidate_stays))
        rng = random.Random(args.sample_seed)
        stay_ids = rng.sample(candidate_stays, k)

        print(
            f"Selected {len(stay_ids)} random stays "
            f"(from {len(candidate_stays)} overlap candidates)"
        )

        for stay_id in tqdm(stay_ids, desc="Preparing event log"):
            created_table = _process_batch_recursive(
                source_con=source_con,
                output_con=output_con,
                batch=[stay_id],
                selected_columns=selected_columns,
                created_table=created_table,
                source_relation="raw_events",
            )

        if not created_table:
            raise RuntimeError("No event-log rows were generated from input")

        _export_event_log(output_con, args.output)
        print(f"Saved event log: {args.output}")
    finally:
        source_con.close()
        output_con.close()
        if source_db_path.exists():
            source_db_path.unlink()
        if output_db_path.exists():
            output_db_path.unlink()


if __name__ == "__main__":
    main()
