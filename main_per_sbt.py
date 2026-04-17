"""CLI for granular per-SBT conformance checking with improved attribution.
Deduplicated trial timestamps to prevent redundant record generation.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import yaml
from tqdm import tqdm

from conformance.batch_runner import BatchConformanceRunner
from conformance.results import ConformanceOutcome, TraceResult
from conformance.rules import (
    build_failure_correction_model,
    build_readiness_assessment_model,
    build_sbt_execution_model,
)
from conformance.types import DeclareModel, DeclareTemplate
from conformance.checker import (
    evaluate_constraint
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
    parser.add_argument("--input", type=Path, default=Path("icu_event_log.parquet"))
    parser.add_argument("--output", type=Path, default=Path("main_per_sbt.csv"))
    args = parser.parse_args()

    runner = BatchConformanceRunner(input_file=args.input, model_builder=_build_combined_model)
    model_paths = [
        Path("configs/declare/readiness_assessment.yaml"),
        Path("configs/declare/sbt_execution.yaml"),
        Path("configs/declare/failure_correction.yaml"),
    ]
    constraint_id_lookup = _load_combined_constraint_id_lookup(model_paths)
    
    stay_ids = runner.get_stay_ids()
    print(f"Processing {len(stay_ids)} stays for per-SBT analysis...")

    output_rows = []
    for stay_id in tqdm(stay_ids):
        # 1. Load full trace for this stay
        df_full = runner.con.execute(
            f"SELECT * FROM events WHERE {runner._batch_key_column} = ?",
            [str(stay_id)],
        ).df().sort_values("timestamp")
        
        if df_full.empty: continue
        
        # KEY FIX: Deduplicate SBTStarted events at identical timestamps
        sbt_starts_all = df_full[df_full["activity"] == "SBTStarted"].sort_values("timestamp")
        sbt_starts = sbt_starts_all.drop_duplicates(subset=["timestamp"]).copy()
        
        if sbt_starts.empty: continue
        
        intubations = df_full[df_full["activity"] == "Intubation"]
        
        # 2. Iterate through each unique SBT trial
        sbt_list = sbt_starts.reset_index(drop=True)
        for i, sbt_row in sbt_list.iterrows():
            start_ts = sbt_row["timestamp"]
            # Window for reintubation: 48h
            outcome_end = start_ts + pd.Timedelta(hours=48)
            
            # Window for rule attribution: until next SBT or end of trace
            next_start_ts = sbt_list.loc[i+1, "timestamp"] if i+1 < len(sbt_list) else df_full.iloc[-1]["timestamp"] + pd.Timedelta(seconds=1)

            # Clinical Outcome
            matching_intub = intubations[(intubations["timestamp"] > start_ts) & (intubations["timestamp"] <= outcome_end)]
            outcome_val = "Failure (Reintubated <48h)" if not matching_intub.empty else "Success (No Reintub <48h)"

            # Sub-trace for this attempt: events until next SBT start
            df_attempt = df_full[df_full["timestamp"] < next_start_ts].copy()
            
            violated = []
            satisfied = []
            
            for constraint in runner.model.constraints:
                canon_id = constraint_id_lookup.get(constraint.label, constraint.label or constraint.id)
                if not canon_id:
                    canon_id = constraint.id
                
                # Check metrics for this trail prefix
                res = evaluate_constraint(case_id=str(stay_id), trace_df=df_attempt, constraint=constraint)
                
                triggered_now = False
                if res.activation_ts:
                    try:
                        act_ts = pd.to_datetime(res.activation_ts)
                        # Specific to this SBT window
                        if start_ts <= act_ts < next_start_ts:
                            triggered_now = True
                    except:
                        pass
                
                if constraint.template == DeclareTemplate.EXISTENCE:
                    if res.outcome == ConformanceOutcome.SATISFIED:
                        satisfied_previously = False
                        if i > 0:
                            # Evaluate prefix of previous trial to see if it was already satisfied
                            # (Avoids double-counting requirements met earlier)
                            df_prev = df_full[df_full["timestamp"] < start_ts]
                            res_prev = evaluate_constraint(case_id=str(stay_id), trace_df=df_prev, constraint=constraint)
                            if res_prev.outcome == ConformanceOutcome.SATISFIED:
                                satisfied_previously = True
                        if not satisfied_previously:
                            satisfied.append(canon_id)
                    elif res.outcome == ConformanceOutcome.VIOLATED:
                        violated.append(canon_id)
                
                elif triggered_now:
                    if res.outcome == ConformanceOutcome.VIOLATED:
                        violated.append(canon_id)
                    elif res.outcome == ConformanceOutcome.SATISFIED:
                        satisfied.append(canon_id)

            output_rows.append({
                "stay_id": stay_id,
                "sbt_attempt": i + 1,
                "sbt_start": str(start_ts),
                "sbt_outcome": outcome_val,
                "violated_constraints": ";".join(sorted(set(violated))),
                "satisfied_constraints": ";".join(sorted(set(satisfied))),
                "num_violations": len(violated),
                "num_satisfactions": len(satisfied),
            })

    output_df = pd.DataFrame(output_rows)
    output_df.to_csv(args.output, index=False)
    print(f"Saved granular per-SBT results to {args.output}")

if __name__ == "__main__":
    main()
