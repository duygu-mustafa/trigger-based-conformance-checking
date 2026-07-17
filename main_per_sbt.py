"""CLI for trigger-episode conformance checking.

Each stay is split into episodes using `InvasiveVentilationStarted` as trigger.
Within each episode, conformance is evaluated and reported even if no SBT attempt
was recorded.
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

import time
from runtime_log import track_step, log_step
from conformance.batch_runner import BatchConformanceRunner
from conformance.results import ConformanceOutcome
from conformance.rules import (
    build_failure_correction_model,
    build_readiness_assessment_model,
    build_sbt_execution_model,
)
from conformance.types import DeclareModel
from conformance.checker import (
    evaluate_constraint
)
from derive.pipeline import raw_to_event_log
import json
import math


INT_COMPOSITE_ID = "INT-COMPOSITE-01"
FAILURE_INTERVENTION_ACTIVITIES = {
    "Bronchodilator_Admin",
    "Diuretic_Admin",
    "AfterloadReduction_Admin",
    "ElectrolyteBG_Test",
    "ElectrolyteCorrection_Admin",
    "HormonalLab_Test",
    "HormonalReplacement_Admin",
}


def _assert_intervention_activities_match_mapping() -> None:
    from pathlib import Path as _Path

    mapping = yaml.safe_load(
        (_Path(__file__).resolve().parent / "configs" / "activity_mapping.yaml").read_text()
    )
    mapped_names = set(mapping.get("mappings", {}).keys())
    missing = FAILURE_INTERVENTION_ACTIVITIES - mapped_names
    if missing:
        raise AssertionError(
            f"FAILURE_INTERVENTION_ACTIVITIES names not found in activity_mapping.yaml: {missing}. "
            "Keep main_per_sbt.FAILURE_INTERVENTION_ACTIVITIES in sync with configs/activity_mapping.yaml."
        )


_assert_intervention_activities_match_mapping()


def _build_trigger_episodes(
    df_full: pd.DataFrame,
    window_hours: float | None = None,
    end_event: str | None = None,
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Segment a stay into episodes per method.tex Definition (episode).

    Horizon = earliest of three candidates: next trigger t_next (fallback,
    always applies), fixed window t_Delta (if window_hours set), end-event
    t_phi (first `end_event` strictly after the trigger, if set). Both
    optional boundaries default off -> fallback-only behavior unchanged.
    """
    triggers = (
        df_full[df_full["activity"] == "InvasiveVentilationStarted"]
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if triggers.empty:
        return []

    trace_end_exclusive = df_full.iloc[-1]["timestamp"] + pd.Timedelta(seconds=1)
    windows: list[tuple[pd.Timestamp, pd.Timestamp]] = []
    for idx, row in triggers.iterrows():
        start_ts = row["timestamp"]
        t_next = (
            triggers.iloc[idx + 1]["timestamp"]
            if idx + 1 < len(triggers)
            else trace_end_exclusive
        )
        candidates = [t_next]
        if window_hours is not None:
            candidates.append(start_ts + pd.Timedelta(hours=window_hours))
        if end_event is not None:
            ev = df_full[
                (df_full["activity"] == end_event) & (df_full["timestamp"] > start_ts)
            ]["timestamp"]
            if not ev.empty:
                candidates.append(ev.min())
        windows.append((start_ts, min(candidates)))
    return windows


def _find_latest_failure_before(df_full: pd.DataFrame, ts: pd.Timestamp) -> pd.Timestamp | None:
    prior = df_full[df_full["timestamp"] < ts].copy()
    if prior.empty:
        return None

    failures = prior[prior["activity"].isin(["SBTFailed", "SBTStopped"])].sort_values("timestamp")
    if failures.empty:
        return None
    return failures.iloc[-1]["timestamp"]


# NOTE: manual `_evaluate_sbt_tm_01_outcome` special-case was removed in favor
# of emitting derived `SBTFailed` events and using the generic Declare checker.
# The old helper was intentionally removed to eliminate ad-hoc runtime branches.


def _evaluate_composite_for_attempt(
    df_full: pd.DataFrame,
    sbt_start: pd.Timestamp,
) -> tuple[bool, list[str], str | None]:
    prior_failure_ts = _find_latest_failure_before(df_full, sbt_start)
    if prior_failure_ts is None:
        return False, [], "No prior SBT failure before this non-first attempt"

    window_end = min(prior_failure_ts + pd.Timedelta(hours=24), sbt_start)
    in_window = df_full[
        (df_full["timestamp"] > prior_failure_ts)
        & (df_full["timestamp"] < sbt_start)
        & (df_full["timestamp"] <= window_end)
        & (df_full["activity"].isin(FAILURE_INTERVENTION_ACTIVITIES))
    ]
    interventions = sorted(in_window["activity"].dropna().astype(str).unique().tolist())
    if interventions:
        return True, interventions, None
    return (
        False,
        [],
        "No qualifying failure intervention between prior failure and current SBT start",
    )

def _load_constraint_id_lookup(model_path: Path) -> dict[str, str]:
    with model_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    model_data = data.get("model", {})
    constraints = model_data.get("constraints", data.get("constraints", []))
    lookup: dict[str, str] = {}
    for c in constraints:
        if not isinstance(c, dict): continue
        cid = str(c.get("id", ""))
        if not cid: continue
        lookup[cid] = cid
        label = c.get("label")
        if isinstance(label, str) and label.strip():
            lookup[label.strip()] = cid
    return lookup

def _load_combined_constraint_id_lookup(model_paths: list[Path]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for p in model_paths:
        lookup.update(_load_constraint_id_lookup(p))
    return lookup

def _build_combined_model() -> DeclareModel:
    model = DeclareModel(name="combined_per_sbt")
    for builder in (
        build_readiness_assessment_model,
        build_sbt_execution_model,
        build_failure_correction_model,
    ):
        sub_model = builder()
        for constraint in sub_model.constraints:
            model.add(constraint)
    return model

def export_to_frontend(runner, stay_ids, results_df, output_dir):
    """Export filtered clinical records and conformance results to JSON for the React frontend."""
    print(f"Exporting JSON for frontend visualization to {output_dir}...")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load item whitelist from dictionary to filter out noise measurements
    with Path("configs/item_dictionary.yaml").open("r") as f:
        item_dict = yaml.safe_load(f)
    
    whitelist_ids = set()
    for source in item_dict.get("sources", {}).values():
        whitelist_ids.update(str(k) for k in source.keys())
    
    # Also whitelist derived ventilation/sbt IDs
    whitelist_ids.update(["sbt_status", "derived_invasive_ventilation_start", "derived_invasive_ventilation_end"])
    core_activities = ["InvasiveVentilationStarted", "InvasiveVentilationEnded", "SBTStarted", "SBTFailed", "SBTSucceeded"]

    # 2. Extract constraint definitions keyed by canonical IDs for frontend lookup.
    constraint_defs = {}
    for c in runner.model.constraints:
        cid = getattr(c, "id", None) or c.label
        if not cid:
            continue
        def _subst_activity_names(expr, activation, target):
            if not expr:
                return expr
            result = str(expr)
            if activation:
                result = result.replace("activation_ts", activation)
            if target:
                result = result.replace("target_ts", target)
            return result

        activation_name = c.activation if hasattr(c, "activation") else None
        target_name = c.target if hasattr(c, "target") else None

        constraint_defs[str(cid)] = {
            "id": str(cid),
            "label": c.label or str(cid),
            "description": getattr(c, "description", "") or "",
            "rationale": getattr(c, "rationale", "") or "",
            "template": c.template.name if hasattr(c, "template") else None,
            "activation": activation_name,
            "target": target_name,
            "semantics": getattr(c, "semantics", None),
            "activation_condition": _subst_activity_names(
                getattr(c, "activation_condition_raw", None),
                activation_name,
                target_name,
            ),
            "activation_condition_title": getattr(c, "activation_condition_title", None),
            "target_condition": _subst_activity_names(
                getattr(c, "target_condition_raw", None),
                activation_name,
                target_name,
            ),
            "target_condition_title": getattr(c, "target_condition_title", None),
            "observation_window_hours": getattr(c, "observation_window_hours", None),
            "min_gap_hours": (c.time_condition.min_seconds / 3600.0) if (getattr(c, "time_condition", None) and c.time_condition.min_seconds is not None) else None,
            "max_gap_hours": (c.time_condition.max_seconds / 3600.0) if (getattr(c, "time_condition", None) and c.time_condition.max_seconds is not None) else None,
        }

    # 3. Process each stay
    for stay_id in tqdm(stay_ids, desc="Exporting JSON"):
        # Get only whitelisted events:
        # - Core activities (Ventilation, SBTs)
        # - True modeled activities (mapped or derived)
        # - Measurements for items specifically defined in our clinical dictionary
        df_stay = runner.con.execute(
            f"""
            SELECT * FROM events 
            WHERE {runner._batch_key_column} = ?
              AND (
                activity IN ({','.join(['?' for _ in core_activities])})
                OR (attrs LIKE '%"mapped_activity"%' OR attrs LIKE '%"derived_activity"%')
                OR (itemid IN ({','.join(['?' for _ in whitelist_ids])}))
              )
            """,
            [str(stay_id)] + core_activities + list(whitelist_ids),
        ).df().sort_values("timestamp")
        
        # Format timestamps for JSON
        df_stay["timestamp"] = pd.to_datetime(df_stay["timestamp"]).dt.strftime("%Y-%m-%dT%H:%M:%S")
        
        # Robustly replace NaN/NaT with None for valid JSON nulls
        df_stay = df_stay.astype(object).where(pd.notnull(df_stay), None)
        
        # Get conformance results for this stay
        stay_conformance_df = results_df[results_df["stay_id"] == stay_id].copy()
        
        # Parse violation_forensics and satisfaction_forensics JSON strings back to dict if present
        for col in ["violation_forensics", "satisfaction_forensics"]:
            if col in stay_conformance_df.columns:
                def _parse_forensics(x):
                    if not isinstance(x, str):
                        return {}
                    try:
                        data = json.loads(x)
                        # Recursively replace NaN with None in forensics dict
                        def _clean(obj):
                            if isinstance(obj, dict):
                                return {k: _clean(v) for k, v in obj.items()}
                            elif isinstance(obj, list):
                                return [_clean(i) for i in obj]
                            elif isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
                                return None
                            return obj
                        return _clean(data)
                    except:
                        return {}
                stay_conformance_df[col] = stay_conformance_df[col].apply(_parse_forensics)

        stay_conformance_df = stay_conformance_df.astype(object).where(pd.notnull(stay_conformance_df), None)
        stay_conformance = stay_conformance_df.to_dict(orient="records")

        # Build aggregated violated/satisfied rule lists for this case
        def _parse_semicolon_list(val):
            if not val:
                return []
            if isinstance(val, list):
                return [str(v) for v in val]
            try:
                return [token.strip() for token in str(val).split(";") if token.strip()]
            except Exception:
                return []

        violated_set: set[str] = set()
        satisfied_set: set[str] = set()
        for ep in stay_conformance:
            violated_set.update(_parse_semicolon_list(ep.get("mandatory_violated_constraints")))
            violated_set.update(_parse_semicolon_list(ep.get("info_violated_constraints")))
            satisfied_set.update(_parse_semicolon_list(ep.get("mandatory_satisfied_constraints")))
            satisfied_set.update(_parse_semicolon_list(ep.get("info_satisfied_constraints")))

        # Final JSON structure
        case_json = {
            "case_id": str(stay_id),
            "events": df_stay.to_dict(orient="records"),
            "conformance": stay_conformance,
            "constraint_definitions": constraint_defs,
            "violated_rules": sorted(list(violated_set)),
            "satisfied_rules": sorted(list(satisfied_set)),
        }
        
        output_file = output_dir / f"case_{stay_id}.json"
        with output_file.open("w", encoding="utf-8") as f:
            json.dump(case_json, f, indent=2, default=str)

    # 4. Export a manifest so the frontend can load cases dynamically
    manifest = {"cases": [str(sid) for sid in stay_ids]}
    with (output_dir / "manifest.json").open("w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    print(f"Frontend export complete.")

_OUTPUT_COLUMNS = [
    "stay_id", "episode_index", "episode_start", "episode_end",
    "ventilation_start", "ventilation_end", "sbt_attempt", "sbt_start", "sbt_end",
    "sbt_outcome", "mandatory_violated_constraints", "mandatory_satisfied_constraints",
    "mandatory_vacuous_constraints", "info_violated_constraints", "info_satisfied_constraints",
    "info_vacuous_constraints", "composite_interventions", "composite_note",
    "violation_forensics", "satisfaction_forensics",
    "num_mandatory_violations", "num_mandatory_satisfactions",
]

# ponytail: per-process globals set by _init_worker; avoids repickling the
# DuckDB runner/model for every task submitted to the pool.
_WORKER_RUNNER = None
_WORKER_LOOKUP = None
_WORKER_EPISODE_WINDOW_HOURS: float | None = None
_WORKER_EPISODE_END_EVENT: str | None = None


def _init_worker(
    input_file: Path,
    model_paths: list[Path],
    episode_window_hours: float | None = None,
    episode_end_event: str | None = None,
) -> None:
    global _WORKER_RUNNER, _WORKER_LOOKUP
    global _WORKER_EPISODE_WINDOW_HOURS, _WORKER_EPISODE_END_EVENT
    _WORKER_RUNNER = BatchConformanceRunner(input_file=input_file, model_builder=_build_combined_model)
    _WORKER_LOOKUP = _load_combined_constraint_id_lookup(model_paths)
    _WORKER_EPISODE_WINDOW_HOURS = episode_window_hours
    _WORKER_EPISODE_END_EVENT = episode_end_event


def _process_stay(stay_id: str) -> list[dict]:
    """Compute conformance rows for a single stay. Runs in a worker process."""
    runner = _WORKER_RUNNER
    constraint_id_lookup = _WORKER_LOOKUP
    rows: list[dict] = []

    df_full = runner.con.execute(
        f"SELECT * FROM events WHERE {runner._batch_key_column} = ?",
        [str(stay_id)],
    ).df().sort_values("timestamp")

    if df_full.empty:
        return rows
    df_full = df_full.copy()
    df_full["timestamp"] = pd.to_datetime(df_full["timestamp"], errors="coerce")
    df_full = df_full.dropna(subset=["timestamp"]).sort_values("timestamp")
    if df_full.empty:
        return rows

    # Convert raw stay rows to canonical event log with derived activities
    if not runner._is_event_log_input:
        event_log = raw_to_event_log(df_full)
    else:
        event_log = df_full.copy()

    episodes = _build_trigger_episodes(
        event_log, _WORKER_EPISODE_WINDOW_HOURS, _WORKER_EPISODE_END_EVENT
    )
    if not episodes:
        return rows

    sbt_starts = (
        event_log[event_log["activity"] == "SBTStarted"]
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
    )
    attempt_index = 0
    for episode_idx, (episode_start, episode_end) in enumerate(episodes, start=1):
        episode_df = event_log[
            (event_log["timestamp"] >= episode_start)
            & (event_log["timestamp"] < episode_end)
        ].copy()
        if episode_df.empty:
            continue

        # ponytail: fixed 24h pre-window matches the RC-DP time_condition;
        # derive from constraint.time_condition if windows ever diverge.
        context_df = event_log[
            (event_log["timestamp"] >= episode_start - pd.Timedelta(hours=24))
            & (event_log["timestamp"] < episode_end)
        ].copy()

        sbt_in_episode = sbt_starts[
            (sbt_starts["timestamp"] >= episode_start)
            & (sbt_starts["timestamp"] < episode_end)
        ]
        sbt_start: pd.Timestamp | None = None
        if not sbt_in_episode.empty:
            sbt_start = sbt_in_episode.iloc[0]["timestamp"]
            attempt_index += 1

        # Read the outcome from the derived SBTFailed/SBTSucceeded event
        # (Phase 3 guarantees it falls inside this episode's window) instead
        # of recomputing it here — the emitter is the single source of truth
        # (Phase 8).
        sbt_end: pd.Timestamp | None = None
        if sbt_start is not None:
            outcome_rows = episode_df[
                episode_df["activity"].isin(["SBTFailed", "SBTSucceeded"])
                & (episode_df["timestamp"] >= sbt_start)
            ].sort_values("timestamp")
            if not outcome_rows.empty:
                outcome_row = outcome_rows.iloc[0]
                outcome_val = str(outcome_row["value_raw"])
                attrs = outcome_row.get("attrs")
                attrs = json.loads(attrs) if isinstance(attrs, str) else attrs
                if not isinstance(attrs, dict):  # emitter writes attrs as [dict]
                    attrs = attrs[0] if attrs is not None and len(attrs) else {}
                revent_ts = attrs.get("revent_ts")
                sbt_end = pd.Timestamp(revent_ts) if revent_ts else outcome_row["timestamp"]
                if outcome_row["activity"] == "SBTSucceeded" and attrs.get("right_censored"):
                    outcome_val = "Success (Right-Censored: Stay Ended)"
            else:
                # No outcome event emitted (e.g. synthetic/partial trace) —
                # treat as right-censored at episode end.
                outcome_val = "Success (Right-Censored: Stay Ended)"
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
            # RC-DP-* rules get a 24h pre-episode look-back so criteria measured
            # before InvasiveVentilationStarted are still visible (Phase 5).
            # INT-* response rules get a post-episode look-ahead: SBTFailed sits
            # at the episode's last second (revent_ts - 1s), so correcting
            # interventions charted after reintubation land in the next episode.
            # Only the rule's own target activity is appended, so activations
            # from the next episode (e.g. its SBTFailed) cannot leak in; each
            # rule's max_hours still bounds the actual match.
            if canon_id.startswith("RC-DP-"):
                constraint_trace_df = context_df
            elif is_failure_rule and constraint.target:
                # ponytail: flat 48h = max max_hours in failure_correction.yaml
                lookahead = event_log[
                    (event_log["timestamp"] >= episode_end)
                    & (event_log["timestamp"] < episode_end + pd.Timedelta(hours=48))
                    & (event_log["activity"] == constraint.target)
                ]
                constraint_trace_df = pd.concat([episode_df, lookahead]).sort_values("timestamp")
            else:
                constraint_trace_df = episode_df
            res = evaluate_constraint(
                case_id=str(stay_id),
                trace_df=constraint_trace_df,
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
                f_data = manual_forensics if manual_forensics else ({"deltas": res.violation_deltas, "delay_seconds": res.delay_seconds} if res else None)
                if f_data:
                    violation_forensics[canon_id] = f_data
            elif outcome == ConformanceOutcome.SATISFIED:
                target_satisfied.append(canon_id)
                f_data = manual_forensics if manual_forensics else ({"deltas": res.satisfaction_deltas, "delay_seconds": res.delay_seconds} if res else None)
                if f_data:
                    satisfaction_forensics[canon_id] = f_data

        # INT-COMPOSITE-01 is mandatory only for non-first SBT attempts.
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

        # Find actual ventilation end within this trigger window
        vent_end_rows = episode_df[episode_df["activity"] == "InvasiveVentilationEnded"].sort_values("timestamp")
        vent_end: pd.Timestamp | None = None
        if not vent_end_rows.empty:
            vent_end = vent_end_rows.iloc[0]["timestamp"]
        else:
            # If ongoing, use the last timestamp in the stay
            vent_end = df_full["timestamp"].max()

        rows.append({
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
        })

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/final/icu_event_log_full.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/results/full_results020726/trigger_results_full.csv"))
    parser.add_argument("--resume", action="store_true", help="Skip stays already present in output CSV.")
    parser.add_argument("--workers", type=int, default=4, help="Parallel worker processes (1 = sequential).")
    parser.add_argument(
        "--episode-window-hours",
        type=float,
        default=None,
        help="Fixed observation window (t_Delta) bounding each episode, in hours. "
        "Default: unbounded (episode ends at next trigger).",
    )
    parser.add_argument(
        "--episode-end-event",
        type=str,
        default=None,
        help="Activity label whose first occurrence after the trigger ends the "
        "episode (t_phi). Default: none.",
    )
    args = parser.parse_args()

    runner = BatchConformanceRunner(input_file=args.input, model_builder=_build_combined_model)
    model_paths = [
        Path("configs/declare/readiness_assessment.yaml"),
        Path("configs/declare/sbt_execution.yaml"),
        Path("configs/declare/failure_correction.yaml"),
    ]
    constraint_id_lookup = _load_combined_constraint_id_lookup(model_paths)
    
    stay_ids = runner.get_stay_ids()

    done_ids: set[str] = set()
    if args.resume and args.output.exists():
        existing = pd.read_csv(args.output, usecols=["stay_id"])
        done_ids = set(existing["stay_id"].astype(str))
        print(f"Resuming: {len(done_ids)} stays already done, {len(stay_ids) - len(done_ids)} remaining.")
    else:
        print(f"Processing {len(stay_ids)} stays for trigger-episode analysis...")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    open_mode = "a" if args.resume and args.output.exists() else "w"
    csv_handle = args.output.open(open_mode, newline="", encoding="utf-8")
    writer = csv.DictWriter(csv_handle, fieldnames=_OUTPUT_COLUMNS)
    if open_mode == "w":
        writer.writeheader()

    remaining_ids = [s for s in stay_ids if str(s) not in done_ids]
    _conformance_start = time.time()

    if args.workers <= 1:
        _init_worker(
            args.input, model_paths, args.episode_window_hours, args.episode_end_event
        )
        for stay_id in tqdm(remaining_ids, initial=len(done_ids), total=len(stay_ids)):
            for row in _process_stay(stay_id):
                writer.writerow(row)
            csv_handle.flush()
    else:
        import concurrent.futures as cf

        with cf.ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker,
            initargs=(args.input, model_paths, args.episode_window_hours, args.episode_end_event),
        ) as pool:
            for rows in tqdm(
                pool.map(_process_stay, remaining_ids, chunksize=8),
                initial=len(done_ids),
                total=len(stay_ids),
            ):
                for row in rows:
                    writer.writerow(row)
                csv_handle.flush()

    csv_handle.close()
    log_step("main_per_sbt", "conformance_checking", _conformance_start, n_stays=len(remaining_ids))
    output_df = pd.read_csv(args.output)
    print(f"Saved trigger-episode conformance results to {args.output}")

    # --- AUTOMATIC FRONTEND EXPORT ---
    # Calculate path relative to this script's location to be robust
    base_path = Path(__file__).resolve().parent
    frontend_data_dir = base_path / "frontend" / "public" / "data"
    results_dir = (base_path / args.output).resolve().parent if not args.output.is_absolute() else args.output.parent
    stats_table_path = results_dir / "statistical_analysis_table.csv"
    stats_summary_path = results_dir / "rule_statistics_R2.csv"

    r_script = base_path / "statistics_R.r"
    if not r_script.exists():
        raise FileNotFoundError(f"Missing R statistics script: {r_script}")

    with track_step("main_per_sbt", "r_stats"):
        subprocess.run(
            [
                "Rscript",
                str(r_script),
                str(args.output),
                str(stats_table_path),
                str(stats_summary_path),
            ],
            check=True,
            cwd=base_path,
        )

    # Filter to only stays with actual conformance results
    stays_with_results = sorted(set(output_df["stay_id"].unique()))
    with track_step("main_per_sbt", "frontend_export"):
        export_to_frontend(runner, stays_with_results, output_df, frontend_data_dir)

    # --- AUTOMATIC SUMMARY GENERATION ---
    from derive.generate_summary import build_summary
    with track_step("main_per_sbt", "summary_generation"):
        case_files = sorted(frontend_data_dir.glob("case_*.json"))
        if case_files:
            summary = build_summary(case_files, frontend_data_dir, stats_summary_path if stats_summary_path.exists() else None)
            summary_file = frontend_data_dir / "summary.json"
            with summary_file.open("w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2)
                f.write("\n")
            print(f"Global summary generated at {summary_file}")

    # --- COPY TO data/final/results ---
    with track_step("main_per_sbt", "copy_final"):
        final_dir = base_path / "data" / "final" / "results"
        final_dir.mkdir(parents=True, exist_ok=True)
        for src in [args.output, stats_table_path, stats_summary_path, frontend_data_dir / "summary.json"]:
            if src.exists():
                shutil.copy2(src, final_dir / src.name)
        print(f"Results copied to {final_dir}")

if __name__ == "__main__":
    with track_step("main_per_sbt", "total"):
        main()
