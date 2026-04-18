"""CLI for trigger-episode conformance checking.

Each stay is split into episodes using `InvasiveVentilationStarted` as trigger.
Within each episode, conformance is evaluated and reported even if no SBT attempt
was recorded.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

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


def _build_trigger_episodes(df_full: pd.DataFrame) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
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
        end_ts = (
            triggers.iloc[idx + 1]["timestamp"]
            if idx + 1 < len(triggers)
            else trace_end_exclusive
        )
        windows.append((start_ts, end_ts))
    return windows


def _find_latest_failure_before(df_full: pd.DataFrame, ts: pd.Timestamp) -> pd.Timestamp | None:
    prior = df_full[df_full["timestamp"] < ts].copy()
    if prior.empty:
        return None

    completed_failed = prior[
        (prior["activity"] == "SBTCompleted")
        & prior.get("value_raw", pd.Series(index=prior.index, dtype=object))
        .astype(str)
        .str.lower()
        .isin(["no", "failure", "failed"])
    ]
    failures = pd.concat(
        [
            prior[prior["activity"].isin(["SBTFailed", "SBTStopped"])],
            completed_failed,
        ],
        axis=0,
    ).sort_values("timestamp")
    if failures.empty:
        return None
    return failures.iloc[-1]["timestamp"]


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

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("data/icu_event_log.parquet"))
    parser.add_argument("--output", type=Path, default=Path("data/results/trigger_results.csv"))
    args = parser.parse_args()

    runner = BatchConformanceRunner(input_file=args.input, model_builder=_build_combined_model)
    model_paths = [
        Path("configs/declare/readiness_assessment.yaml"),
        Path("configs/declare/sbt_execution.yaml"),
        Path("configs/declare/failure_correction.yaml"),
    ]
    constraint_id_lookup = _load_combined_constraint_id_lookup(model_paths)
    
    stay_ids = runner.get_stay_ids()
    print(f"Processing {len(stay_ids)} stays for trigger-episode analysis...")

    output_rows = []
    for stay_id in tqdm(stay_ids):
        # 1. Load full trace for this stay
        df_full = runner.con.execute(
            f"SELECT * FROM events WHERE {runner._batch_key_column} = ?",
            [str(stay_id)],
        ).df().sort_values("timestamp")
        
        if df_full.empty:
            continue
        df_full = df_full.copy()
        df_full["timestamp"] = pd.to_datetime(df_full["timestamp"], errors="coerce")
        df_full = df_full.dropna(subset=["timestamp"]).sort_values("timestamp")
        if df_full.empty:
            continue

        episodes = _build_trigger_episodes(df_full)
        if not episodes:
            continue

        sbt_starts = (
            df_full[df_full["activity"] == "SBTStarted"]
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
        )
        intubations = df_full[df_full["activity"] == "Intubation"]

        attempt_index = 0
        for episode_idx, (episode_start, episode_end) in enumerate(episodes, start=1):
            episode_df = df_full[
                (df_full["timestamp"] >= episode_start)
                & (df_full["timestamp"] < episode_end)
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

            if sbt_start is not None:
                outcome_end = sbt_start + pd.Timedelta(hours=48)
                matching_intub = intubations[
                    (intubations["timestamp"] > sbt_start)
                    & (intubations["timestamp"] <= outcome_end)
                ]
                outcome_val = (
                    "Failure (Reintubated <48h)"
                    if not matching_intub.empty
                    else "Success (No Reintub <48h)"
                )
            else:
                outcome_val = "No SBT Attempt"

            mandatory_violated: list[str] = []
            mandatory_satisfied: list[str] = []
            informational_violated: list[str] = []
            informational_satisfied: list[str] = []
            composite_interventions: list[str] = []

            for constraint in runner.model.constraints:
                canon_id = constraint_id_lookup.get(constraint.label, constraint.label or constraint.id)
                if not canon_id:
                    canon_id = constraint.id
                if not canon_id:
                    continue

                if canon_id == INT_COMPOSITE_ID:
                    continue

                is_failure_rule = canon_id.startswith("INT-")
                res = evaluate_constraint(
                    case_id=str(stay_id),
                    trace_df=episode_df,
                    constraint=constraint,
                )

                if res.outcome == ConformanceOutcome.VACUOUS:
                    continue

                target_violated = mandatory_violated
                target_satisfied = mandatory_satisfied
                if is_failure_rule:
                    target_violated = informational_violated
                    target_satisfied = informational_satisfied

                if res.outcome == ConformanceOutcome.VIOLATED:
                    target_violated.append(canon_id)
                elif res.outcome == ConformanceOutcome.SATISFIED:
                    target_satisfied.append(canon_id)

            # INT-COMPOSITE-01 is mandatory only for non-first SBT attempts.
            composite_reason = None
            if sbt_start is not None and attempt_index > 1:
                composite_ok, composite_interventions, composite_reason = _evaluate_composite_for_attempt(
                    df_full=df_full,
                    sbt_start=sbt_start,
                )
                if composite_ok:
                    mandatory_satisfied.append(INT_COMPOSITE_ID)
                else:
                    mandatory_violated.append(INT_COMPOSITE_ID)

            output_rows.append({
                "stay_id": stay_id,
                "episode_index": episode_idx,
                "episode_start": str(episode_start),
                "episode_end": str(episode_end),
                "sbt_attempt": attempt_index if sbt_start is not None else "",
                "sbt_start": str(sbt_start) if sbt_start is not None else "",
                "sbt_outcome": outcome_val,
                "mandatory_violated_constraints": ";".join(sorted(set(mandatory_violated))),
                "mandatory_satisfied_constraints": ";".join(sorted(set(mandatory_satisfied))),
                "info_violated_constraints": ";".join(sorted(set(informational_violated))),
                "info_satisfied_constraints": ";".join(sorted(set(informational_satisfied))),
                "composite_interventions": ";".join(composite_interventions),
                "composite_note": composite_reason or "",
                "num_mandatory_violations": len(set(mandatory_violated)),
                "num_mandatory_satisfactions": len(set(mandatory_satisfied)),
            })

    output_df = pd.DataFrame(output_rows)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output_df.to_csv(args.output, index=False)
    print(f"Saved trigger-episode conformance results to {args.output}")

if __name__ == "__main__":
    main()
