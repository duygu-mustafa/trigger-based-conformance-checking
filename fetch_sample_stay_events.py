"""CLI example: fetch timestamped ICU events for one stay_id."""

from __future__ import annotations

import argparse
import gc
import sys
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

# Allow running this file directly: python fetch_sample_stay_events.py
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.fetch_events import fetch_icu_events_for_stay
from conformance.rules import build_readiness_assessment_model, build_sbt_execution_model
from conformance.checker import check_log_conformance
from conformance.outcome_postprocessing import build_model_level_regression_frame
from conformance.results import ConformanceOutcome, TraceResult
from conformance.weighted_scoring import compute_trace_scores, load_constraints_with_weights
from derive.reintubation import detect_intubation_after_sbt
from derive import raw_to_event_log


DEFAULT_STAY_IDS = [34961518, 37053432, 30934380, 37510196]


def _parse_stay_ids_arg(raw: str | None) -> list[int] | None:
    if raw is None or not str(raw).strip():
        return None

    out: list[int] = []
    for token in str(raw).split(","):
        t = token.strip()
        if not t:
            continue
        out.append(int(t))
    return out


def _duckdb_scan_relation(cache_file: Path) -> str:
    cache_str = str(cache_file).replace("'", "''")
    suffixes = [s.lower() for s in cache_file.suffixes]

    if cache_file.suffix.lower() in {".parquet", ".pq"}:
        return f"read_parquet('{cache_str}')"
    if suffixes[-2:] == [".csv", ".gz"] or cache_file.suffix.lower() in {".csv", ".gz"}:
        return f"read_csv_auto('{cache_str}', compression='auto')"

    raise ValueError(
        f"Unsupported cache file format for {cache_file}. Use .csv/.csv.gz or .parquet/.pq"
    )


def _cache_stay_ids(cache_file: Path) -> list[int]:
    scan = _duckdb_scan_relation(cache_file)
    with duckdb.connect() as con:
        rows = con.execute(
            f"""
            SELECT DISTINCT TRY_CAST(stay_id AS BIGINT) AS stay_id
            FROM {scan}
            WHERE TRY_CAST(stay_id AS BIGINT) IS NOT NULL
            ORDER BY stay_id
            """
        ).fetchall()
    return [int(r[0]) for r in rows]


def _cache_stay_ids_with_sbt(cache_file: Path, sbt_itemid: int = 224715) -> list[int]:
    """Filter cache stay_ids to only those with at least one SBT Started event."""
    scan = _duckdb_scan_relation(cache_file)
    with duckdb.connect() as con:
        rows = con.execute(
            f"""
            SELECT DISTINCT TRY_CAST(stay_id AS BIGINT) AS stay_id
            FROM {scan}
            WHERE TRY_CAST(stay_id AS BIGINT) IS NOT NULL
              AND TRY_CAST(itemid AS BIGINT) = ?
            ORDER BY stay_id
            """,
            [sbt_itemid],
        ).fetchall()
    return [int(r[0]) for r in rows]


def _load_single_stay_from_cache(cache_file: Path, stay_id: int) -> pd.DataFrame:
    scan = _duckdb_scan_relation(cache_file)
    with duckdb.connect() as con:
        return con.execute(
            f"""
            SELECT *
            FROM {scan}
            WHERE TRY_CAST(stay_id AS BIGINT) = ?
            """,
            [int(stay_id)],
        ).df()


def _resolve_stay_ids(
    *,
    requested_stay_ids: list[int] | None,
    cache_stay_ids: list[int] | None,
    max_stays: int | None,
    sample_seed: int,
) -> list[int]:
    if cache_stay_ids is not None:
        available = sorted(cache_stay_ids)
        if requested_stay_ids is None:
            selected = available
        else:
            available_set = set(available)
            selected = [sid for sid in requested_stay_ids if sid in available_set]
            missing = [sid for sid in requested_stay_ids if sid not in available_set]
            if missing:
                preview = ", ".join(str(x) for x in missing[:10])
                suffix = "" if len(missing) <= 10 else " ..."
                print(f"Requested stay_ids not found in cache ({len(missing)}): {preview}{suffix}")
    else:
        selected = requested_stay_ids if requested_stay_ids is not None else list(DEFAULT_STAY_IDS)

    if max_stays is not None and max_stays >= 0 and len(selected) > max_stays:
        if cache_stay_ids is not None and requested_stay_ids is None:
            selected = (
                pd.Series(selected)
                .sample(n=max_stays, random_state=sample_seed)
                .astype(int)
                .tolist()
            )
            selected = sorted(selected)
        else:
            selected = selected[:max_stays]

    return selected





def _append_tracking_rows(tracking_path: Path, rows: list[dict[str, object]], write_header: bool) -> bool:
    if not rows:
        return write_header

    tracking_df = pd.DataFrame(rows)
    tracking_df.to_csv(tracking_path, mode="a", index=False, header=write_header)
    return False


def _collect_constraint_outcome_columns(
    trace_results: list[TraceResult],
    constraint_id_map: dict[str, str] | None = None,
) -> dict[str, dict[str, str]]:
    """Build per-case lists of satisfied and violated constraints."""

    per_case: dict[str, dict[str, set[str]]] = {}
    for tr in trace_results:
        case_id = str(tr.case_id)
        case_bucket = per_case.setdefault(
            case_id,
            {
                "violated": set(),
                "satisfied": set(),
            },
        )
        for cr in tr.constraint_results:
            raw_constraint = str(cr.constraint_id)
            normalized_constraint = (
                constraint_id_map.get(raw_constraint, raw_constraint)
                if constraint_id_map is not None
                else raw_constraint
            )
            if cr.outcome == ConformanceOutcome.VIOLATED:
                case_bucket["violated"].add(normalized_constraint)
            elif cr.outcome == ConformanceOutcome.SATISFIED:
                case_bucket["satisfied"].add(normalized_constraint)

    # Keep CSV compact/deterministic: sorted, semicolon-separated identifiers.
    out: dict[str, dict[str, str]] = {}
    for case_id, bucket in per_case.items():
        out[case_id] = {
            "violated_constraints": ";".join(sorted(bucket["violated"])),
            "satisfied_constraints": ";".join(sorted(bucket["satisfied"])),
        }
    return out


def _build_weighted_inputs_from_results(
    trace_results: list[TraceResult],
    constraint_id_map: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Convert checker outputs to weighted-scoring applicability and violations.

    Open-world applicability is approximated as constraints with at least one
    activation in a trace (num_activations > 0).
    """

    applicable_rows: list[dict[str, str]] = []
    violation_rows: list[dict[str, object]] = []

    for tr in trace_results:
        case_id = str(tr.case_id)
        for cr in tr.constraint_results:
            raw_constraint = str(cr.constraint_id)
            normalized_constraint = (
                constraint_id_map.get(raw_constraint, raw_constraint)
                if constraint_id_map is not None
                else raw_constraint
            )

            # Open-world applicability: constraints without activation do not enter C_t.
            if int(cr.num_activations) > 0 and cr.outcome != ConformanceOutcome.NOT_EVALUATED:
                applicable_rows.append(
                    {
                        "case_id": case_id,
                        "constraint_id": normalized_constraint,
                    }
                )

            if cr.outcome == ConformanceOutcome.VIOLATED:
                # A violation count of zero is possible in edge paths; keep at least one instance.
                n = max(int(cr.num_violated), 1)
                for _ in range(n):
                    violation_rows.append(
                        {
                            "case_id": case_id,
                            "constraint_id": normalized_constraint,
                            "violation_type": "control-flow",
                            "x": None,
                            "timestamp": None,
                        }
                    )

    applicable_df = pd.DataFrame(applicable_rows, columns=["case_id", "constraint_id"]).drop_duplicates()
    violations_df = pd.DataFrame(
        violation_rows,
        columns=["case_id", "constraint_id", "violation_type", "x", "timestamp"],
    )
    return applicable_df, violations_df


def _run_weighted_conformance(
    model_yaml_path: Path,
    trace_results: list[TraceResult],
) -> list[dict[str, object]]:
    """Compute and print weighted fuzzy conformance from checker outputs."""

    weights_yaml_path = PROJECT_ROOT / "configs" / "declare" / "weights.yaml"
    print("\n--- Weighted Conformance Scoring ---")
    tracking_rows: list[dict[str, object]] = []
    all_case_ids = sorted({str(tr.case_id) for tr in trace_results})

    constraint_id_map: dict[str, str] = {}
    try:
        import yaml

        with model_yaml_path.open("r", encoding="utf-8") as f:
            raw_model = yaml.safe_load(f) or {}
        model_block = raw_model.get("model", {}) if isinstance(raw_model, dict) else {}
        constraints_block = model_block.get("constraints", []) if isinstance(model_block, dict) else []
        if isinstance(constraints_block, list):
            for rc in constraints_block:
                if not isinstance(rc, dict):
                    continue
                cid = rc.get("id")
                if cid is None:
                    continue
                cid = str(cid)
                constraint_id_map[cid] = cid
                label = rc.get("label")
                if label is not None:
                    constraint_id_map[str(label)] = cid
    except Exception:
        # Mapping is a convenience; fall back to raw checker identifiers.
        constraint_id_map = {}

    constraint_outcomes = _collect_constraint_outcome_columns(
        trace_results,
        constraint_id_map=constraint_id_map,
    )

    try:
        constraints = load_constraints_with_weights(
            model_yaml_path=model_yaml_path,
            weights_yaml_path=weights_yaml_path,
        )
    except Exception as exc:  # Keep sample CLI robust during exploratory runs.
        print(f"Skipping weighted scoring (constraint/weight load error): {exc}")
        for case_id in all_case_ids:
            case_outcomes = constraint_outcomes.get(case_id, {})
            tracking_rows.append(
                {
                    "model_name": model_yaml_path.stem,
                    "case_id": case_id,
                    "included_in_weighted_score": False,
                    "exclusion_reason": f"weight_load_error: {exc}",
                    "score": None,
                    "violated_constraints": case_outcomes.get("violated_constraints", ""),
                    "satisfied_constraints": case_outcomes.get("satisfied_constraints", ""),
                }
            )
        return tracking_rows

    applicable_df, violations_df = _build_weighted_inputs_from_results(
        trace_results,
        constraint_id_map=constraint_id_map,
    )
    included_case_ids = sorted(applicable_df["case_id"].astype(str).unique().tolist()) if not applicable_df.empty else []
    excluded_case_ids = sorted(set(all_case_ids) - set(included_case_ids))

    if excluded_case_ids:
        preview = ", ".join(excluded_case_ids[:10])
        suffix = "" if len(excluded_case_ids) <= 10 else " ..."
        print(
            "Excluded from weighted score (no applicable constraints / no SBT activation): "
            f"{len(excluded_case_ids)} trace(s): {preview}{suffix}"
        )

    if applicable_df.empty:
        print("No applicable constraints detected (num_activations == 0 for all); no weighted score.")
        for case_id in all_case_ids:
            case_outcomes = constraint_outcomes.get(case_id, {})
            tracking_rows.append(
                {
                    "model_name": model_yaml_path.stem,
                    "case_id": case_id,
                    "included_in_weighted_score": False,
                    "exclusion_reason": "no_applicable_constraints",
                    "score": None,
                    "violated_constraints": case_outcomes.get("violated_constraints", ""),
                    "satisfied_constraints": case_outcomes.get("satisfied_constraints", ""),
                }
            )
        return tracking_rows

    scores, detail = compute_trace_scores(
        constraints=constraints,
        violations=violations_df,
        applicable_constraints=applicable_df,
    )

    print("Per-trace weighted scores:")
    print(scores.sort_values("case_id").to_string(index=False))

    print("\nTop penalties by trace/constraint:")
    shown = detail.sort_values(["case_id", "W_t_c"], ascending=[True, False]).head(20)
    print(shown.to_string(index=False))

    score_map = {str(r["case_id"]): float(r["score"]) for _, r in scores.iterrows()}
    for case_id in all_case_ids:
        case_outcomes = constraint_outcomes.get(case_id, {})
        if case_id in score_map:
            tracking_rows.append(
                {
                    "model_name": model_yaml_path.stem,
                    "case_id": case_id,
                    "included_in_weighted_score": True,
                    "exclusion_reason": None,
                    "score": score_map[case_id],
                    "violated_constraints": case_outcomes.get("violated_constraints", ""),
                    "satisfied_constraints": case_outcomes.get("satisfied_constraints", ""),
                }
            )
        else:
            tracking_rows.append(
                {
                    "model_name": model_yaml_path.stem,
                    "case_id": case_id,
                    "included_in_weighted_score": False,
                    "exclusion_reason": "no_applicable_constraints",
                    "score": None,
                    "violated_constraints": case_outcomes.get("violated_constraints", ""),
                    "satisfied_constraints": case_outcomes.get("satisfied_constraints", ""),
                }
            )

    return tracking_rows


def _run_conformance(df, stay_id: int) -> list[dict[str, object]]:
    print("\n--- Conformance Checking ---")
    # Prepare canonical event log through config-driven mapping.
    event_log = raw_to_event_log(
        df,
        pipeline_config_path=PROJECT_ROOT / "configs" / "pipeline.yaml",
        item_dictionary_path=PROJECT_ROOT / "configs" / "item_dictionary.yaml",
        activity_mapping_path=PROJECT_ROOT / "configs" / "activity_mapping.yaml",
    )
    reintubation_summary = detect_intubation_after_sbt(event_log)
    reintubation_map = {
        str(row["case_id"]): row
        for _, row in reintubation_summary.iterrows()
    }

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

    tracking_rows = []
    tracking_rows.extend(_run_weighted_conformance(
        model_yaml_path=PROJECT_ROOT / "configs" / "declare" / "readiness_assessment.yaml",
        trace_results=results,
    ))

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

    tracking_rows.extend(_run_weighted_conformance(
        model_yaml_path=PROJECT_ROOT / "configs" / "declare" / "sbt_execution.yaml",
        trace_results=results_sbt,
    ))

    for row in tracking_rows:
        row["stay_id"] = stay_id
        case_outcome = reintubation_map.get(str(row["case_id"]), {})
        row["intubation_after_sbt"] = bool(case_outcome.get("intubation_after_sbt", False))
        row["y"] = int(row["intubation_after_sbt"])
        row["hours_from_sbt_to_intubation"] = case_outcome.get("hours_from_sbt_to_intubation")
        row["first_sbt_started_ts"] = case_outcome.get("first_sbt_started_ts")
        row["first_intubation_after_sbt_ts"] = case_outcome.get("first_intubation_after_sbt_ts")
    return tracking_rows

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch ICU event-level rows for selected stay IDs")
    parser.add_argument(
        "--cache-file",
        type=str,
        default="icu_event_level_sbt.parquet",
        help="Path to local unified events file (.csv/.csv.gz or .parquet/.pq). If set, DB fetch is skipped.",
    )
    parser.add_argument(
        "--stay-ids",
        type=str,
        default=None,
        help="Comma-separated stay_ids. If omitted with --cache-file, all stay_ids in cache are used.",
    )
    parser.add_argument(
        "--stay-id-filter-file",
        type=str,
        default="sbt_started_yes_stay_ids.parquet",
        help=(
            "Optional path to a file containing stay_id values to whitelist "
            "(e.g., true SBTStarted=Yes cohort)."
        ),
    )
    parser.add_argument(
        "--max-stays",
        type=int,
        default=None,
        help="Maximum number of stay_ids to process.",
    )
    parser.add_argument(
        "--sample-seed",
        type=int,
        default=42,
        help="Random seed when sampling stay_ids from cache with --max-stays.",
    )
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

    requested_stay_ids = _parse_stay_ids_arg(args.stay_ids)
    cache_path: Path | None = None
    cache_stay_ids: list[int] | None = None
    if args.cache_file is not None:
        cache_path = Path(args.cache_file)
        cache_stay_ids = _cache_stay_ids(cache_path)
        print(f"Discovered {len(cache_stay_ids)} stay_id(s) in cache file: {cache_path}")

        if args.stay_id_filter_file:
            filter_path = Path(args.stay_id_filter_file)
            if filter_path.exists():
                filter_ids = set(_cache_stay_ids(filter_path))
                before = len(cache_stay_ids)
                cache_stay_ids = [sid for sid in cache_stay_ids if sid in filter_ids]
                print(
                    f"Applied stay_id whitelist from {filter_path}: "
                    f"{before} -> {len(cache_stay_ids)} stay_id(s)"
                )
            else:
                print(f"Stay-id filter file not found, skipping: {filter_path}")

    stay_ids = _resolve_stay_ids(
        requested_stay_ids=requested_stay_ids,
        cache_stay_ids=cache_stay_ids,
        max_stays=args.max_stays,
        sample_seed=args.sample_seed,
    )

    if not stay_ids:
        print("No stay_ids selected. Nothing to do.")
        return

    print(f"Processing {len(stay_ids)} stay_id(s).")

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tracking_path = out_dir / "weighted_scoring_trace_tracking.csv"
    regression_path = out_dir / "logistic_regression_ready.csv"
    write_tracking_header = True
    if tracking_path.exists():
        tracking_path.unlink()
    if regression_path.exists():
        regression_path.unlink()

    all_tracking_rows: list[dict[str, object]] = []

    total_stays = len(stay_ids)
    for idx, stay_id in enumerate(stay_ids, start=1):
        print(f"\n=== [{idx}/{total_stays}] stay_id={stay_id} ===")
        if cache_path is not None:
            df = _load_single_stay_from_cache(cache_path, stay_id)
            print(f"Loaded from cache rows: {len(df)} for stay_id={stay_id}")
            if len(df) == 0:
                print("No rows found for stay_id in cache file.")
                continue
        else:
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
            rows = _run_conformance(df, stay_id=stay_id)
            all_tracking_rows.extend(rows)
            write_tracking_header = _append_tracking_rows(tracking_path, rows, write_tracking_header)

        del df
        gc.collect()

    if tracking_path.exists():
        print(f"\nSaved weighted scoring inclusion/exclusion tracking to: {tracking_path}")

    if all_tracking_rows:
        tracking_df = pd.DataFrame(all_tracking_rows)
        outcome_df = tracking_df[
            [
                "stay_id",
                "case_id",
                "intubation_after_sbt",
                "hours_from_sbt_to_intubation",
                "first_sbt_started_ts",
                "first_intubation_after_sbt_ts",
                "y",
            ]
        ].drop_duplicates(subset=["stay_id", "case_id"]) 
        regression_df = build_model_level_regression_frame(tracking_df, outcome_df)
        regression_df.to_csv(regression_path, index=False)
        print(f"Saved logistic-regression-ready table to: {regression_path}")

if __name__ == "__main__":
    main()
