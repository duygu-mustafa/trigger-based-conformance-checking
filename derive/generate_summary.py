#!/usr/bin/env python3
"""Generate global conformance summary metrics for the frontend dashboard.

The script scans case JSON files and writes an aggregated summary JSON used by the
frontend Summary view.
"""

from __future__ import annotations

import argparse
import json
import pandas as pd
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def parse_constraint_list(raw_value: Any) -> list[str]:
    if not raw_value or not isinstance(raw_value, str):
        return []
    return [token.strip() for token in raw_value.split(";") if token.strip()]


def classify_outcome(outcome: Any) -> str:
    outcome_str = str(outcome or "").lower()
    if "success" in outcome_str:
        return "success"
    if "failure" in outcome_str:
        return "failure"
    return "unknown"


def safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def safe_float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and value.strip().upper() == "NA":
            return None
        converted = float(value)
        if converted != converted:
            return None
        return converted
    except (TypeError, ValueError):
        return None


def safe_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    value_str = str(value).strip().lower()
    return value_str in {"true", "t", "1", "yes", "y"}


def infer_input_dir(project_root: Path) -> Path:
    public_dir = project_root / "frontend" / "public" / "data"
    src_dir = project_root / "frontend" / "src" / "data"
    if public_dir.exists():
        return public_dir
    return src_dir


def _load_item_labels(project_root: Path) -> dict[str, str]:
    import yaml
    path = project_root / "configs" / "item_dictionary.yaml"
    if not path.exists():
        return {}
    try:
        with path.open("r") as f:
            data = yaml.safe_load(f) or {}
        labels = {}
        sources = data.get("sources", {})
        if isinstance(sources, dict):
            for source_data in sources.values():
                if isinstance(source_data, dict):
                    for iid, label in source_data.items():
                        # Use the label string, stripping comments
                        clean_label = str(label).split("#")[0].strip()
                        labels[str(iid)] = clean_label
        return labels
    except Exception:
        return {}


def build_summary(case_files: list[Path], input_dir: Path, stats_csv: Path | None = None) -> dict[str, Any]:
    # Load stats if provided
    stats_map = {}
    if stats_csv and stats_csv.exists():
        try:
            df_stats = pd.read_csv(stats_csv)
            # Map rule_name to a subset of statistical metrics
            for _, row in df_stats.iterrows():
                cid = str(row.get("rule_name", ""))
                if cid:
                    stats_map[cid] = {
                        "n_exposed": safe_float_or_none(row.get("n_exposed")),
                        "n_unexposed": safe_float_or_none(row.get("n_unexposed")),
                        "a": safe_float_or_none(row.get("a")),
                        "b": safe_float_or_none(row.get("b")),
                        "c": safe_float_or_none(row.get("c")),
                        "d": safe_float_or_none(row.get("d")),
                        "fisher_p": safe_float_or_none(row.get("fisher_p")),
                        "odds_ratio": safe_float_or_none(row.get("or")),
                        "odds_ratio_low": safe_float_or_none(row.get("or_low")),
                        "odds_ratio_high": safe_float_or_none(row.get("or_high")),
                        "risk_ratio": safe_float_or_none(row.get("rr")),
                        "rr_ci_low": safe_float_or_none(row.get("rr_low")),
                        "rr_ci_high": safe_float_or_none(row.get("rr_high")),
                        "p_value_raw": safe_float_or_none(row.get("fisher_p")),
                        "p_value_bonf": safe_float_or_none(row.get("p_bonf")),
                        "p_value_fdr": safe_float_or_none(row.get("p_fdr")),
                        "is_significant_bonf": safe_bool(row.get("sig_bonf")),
                        "is_significant": safe_bool(row.get("sig_fdr"))
                    }
        except Exception as e:
            print(f"Warning: Failed to load stats CSV: {e}")

    all_episodes: list[dict[str, Any]] = []
    stay_to_episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    violation_counter: Counter[str] = Counter()
    violation_stays: dict[str, set[str]] = defaultdict(set)
    readiness_counter: Counter[str] = Counter()
    constraint_labels: dict[str, str] = {}
    constraint_metas: dict[str, dict[str, Any]] = {}
    
    # Track all seen constraints to include non-violated ones
    all_constraint_ids: set[str] = set()
    satisfied_counter: Counter[str] = Counter()
    vacuous_counter: Counter[str] = Counter()
    
    # Track forensics (magnitudes/delays)
    violation_forensics_agg: dict[str, list[dict[str, Any]]] = defaultdict(list)
    satisfaction_forensics_agg: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for case_file in case_files:
        with case_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        stay_id = str(payload.get("case_id") or payload.get("stay_id") or "")
        episodes = payload.get("conformance") or []

        definitions = payload.get("constraint_definitions") or {}
        if isinstance(definitions, dict):
            for cid, meta in definitions.items():
                all_constraint_ids.add(cid)
                if not isinstance(meta, dict):
                    continue
                label = meta.get("label")
                if label and cid not in constraint_labels:
                    constraint_labels[cid] = str(label)
                if cid not in constraint_metas:
                    constraint_metas[cid] = meta

        for episode in episodes:
            ep = dict(episode)
            ep_stay_id = str(ep.get("stay_id") or stay_id)
            ep["stay_id"] = ep_stay_id
            all_episodes.append(ep)
            stay_to_episodes[ep_stay_id].append(ep)

            v_list = parse_constraint_list(ep.get("mandatory_violated_constraints"))
            s_list = parse_constraint_list(ep.get("mandatory_satisfied_constraints"))
            vac_list = parse_constraint_list(ep.get("mandatory_vacuous_constraints"))
            
            for cid in v_list:
                violation_counter[cid] += 1
                violation_stays[cid].add(ep_stay_id)
                all_constraint_ids.add(cid)
                if cid.startswith("RC-DP-"):
                    readiness_counter[cid] += 1
            
            for cid in s_list:
                satisfied_counter[cid] += 1
                all_constraint_ids.add(cid)
                
            for cid in vac_list:
                vacuous_counter[cid] += 1
                all_constraint_ids.add(cid)

            # Collect forensics
            v_forensics = ep.get("violation_forensics") or {}
            for cid, data in v_forensics.items():
                d_copy = dict(data)
                d_copy["outcome"] = ep.get("sbt_outcome")
                violation_forensics_agg[cid].append(d_copy)

            s_forensics = ep.get("satisfaction_forensics") or {}
            for cid, data in s_forensics.items():
                d_copy = dict(data)
                d_copy["outcome"] = ep.get("sbt_outcome")
                satisfaction_forensics_agg[cid].append(d_copy)

    total_stays = len(stay_to_episodes)
    total_episodes = len(all_episodes)

    # Group episodes by outcome to get baseline counts
    grouped: dict[str, list[dict[str, Any]]] = {"success": [], "failure": [], "unknown": []}
    for ep in all_episodes:
        grouped[classify_outcome(ep.get("sbt_outcome"))].append(ep)

    num_success = len(grouped["success"])
    num_failure = len(grouped["failure"])

    violation_frequency: list[dict[str, Any]] = []
    # Count violations per outcome type
    violation_outcome_counter: dict[str, Counter[str]] = {
        "success": Counter(),
        "failure": Counter(),
        "unknown": Counter()
    }
    
    for ep in all_episodes:
        outcome = classify_outcome(ep.get("sbt_outcome"))
        for cid in parse_constraint_list(ep.get("mandatory_violated_constraints")):
            violation_outcome_counter[outcome][cid] += 1

    # Iterate over ALL seen constraints, not just violated ones
    for cid in sorted(all_constraint_ids):
        count = violation_counter[cid]
        affected_stays = len(violation_stays[cid])
        count_success = violation_outcome_counter["success"][cid]
        count_failure = violation_outcome_counter["failure"][cid]
        count_vacuous = vacuous_counter[cid]
        count_satisfied = satisfied_counter[cid]
        
        # Calculate probabilities
        rate_success = round(count_success / num_success, 4) if num_success > 0 else 0.0
        rate_failure = round(count_failure / num_failure, 4) if num_failure > 0 else 0.0
        
        # Lift = P(V|F) / P(V)
        # We only calculate lift if there are SOME violations overall
        total_v = count_success + count_failure
        prob_v = total_v / (num_success + num_failure) if (num_success + num_failure) > 0 else 0.0
        lift_failure = round(rate_failure / prob_v, 3) if prob_v > 0 else 1.0
        
        # Satisfaction Metrics
        # P(S|Success) = count_satisfied_success / num_success
        # But we need to count satisfactions per outcome
        # Let's add that logic
        count_sat_success = sum(1 for ep in grouped["success"] if cid in parse_constraint_list(ep.get("mandatory_satisfied_constraints")))
        count_sat_failure = sum(1 for ep in grouped["failure"] if cid in parse_constraint_list(ep.get("mandatory_satisfied_constraints")))
        
        rate_sat_success = round(count_sat_success / num_success, 4) if num_success > 0 else 0.0
        rate_sat_failure = round(count_sat_failure / num_failure, 4) if num_failure > 0 else 0.0
        
        total_s = count_sat_success + count_sat_failure
        prob_s = total_s / (num_success + num_failure) if (num_success + num_failure) > 0 else 0.0
        lift_success = round(rate_sat_success / prob_s, 3) if prob_s > 0 else 1.0

        # Difference in rates
        rate_diff = round(rate_failure - rate_success, 4)
        
        # Collect forensics statistics
        def summarize_agg(aggregated):
            delays = []
            delay_outcomes = []
            delta_distributions = defaultdict(list)
            delta_outcomes = defaultdict(list)
            
            for f in aggregated:
                d_sec = f.get("delay_seconds")
                outcome = f.get("outcome")
                if d_sec is not None:
                    delays.append(float(d_sec))
                    delay_outcomes.append(outcome)
                
                d = f.get("deltas") or {}
                for k, v in d.items():
                    if isinstance(v, (int, float)):
                        delta_distributions[k].append(float(v))
                        delta_outcomes[k].append(outcome)
            
            return {
                "delays": delays, 
                "delay_outcomes": delay_outcomes,
                "delta_distributions": dict(delta_distributions),
                "delta_outcomes": dict(delta_outcomes)
            }

        forensics_v = summarize_agg(violation_forensics_agg[cid])
        forensics_s = summarize_agg(satisfaction_forensics_agg[cid])

        entry = {
                "constraint_id": cid,
                "constraint_label": constraint_labels.get(cid, cid),
                "rationale": constraint_metas.get(cid, {}).get("rationale", ""),
                "template": constraint_metas.get(cid, {}).get("template", ""),
                "activation_condition": constraint_metas.get(cid, {}).get("activation_condition"),
                "target_condition": constraint_metas.get(cid, {}).get("target_condition"),
                "min_gap_hours": constraint_metas.get(cid, {}).get("min_gap_hours"),
                "max_gap_hours": constraint_metas.get(cid, {}).get("max_gap_hours"),
                "observation_window_hours": constraint_metas.get(cid, {}).get("observation_window_hours"),
                "count": count,
                "count_success": count_success,
                "count_failure": count_failure,
                "count_vacuous": count_vacuous,
                "count_satisfied": count_satisfied,
                "violation_rate_success": rate_success,
                "violation_rate_failure": rate_failure,
                "satisfaction_rate_success": rate_sat_success,
                "satisfaction_rate_failure": rate_sat_failure,
                "lift_success": lift_success,
                "vacuous_share": round(count_vacuous / total_episodes, 4) if total_episodes else 0.0,
                "lift_failure": lift_failure,
                "rate_diff": rate_diff,
                "affected_stays": affected_stays,
                "episode_share": round((count / total_episodes), 4) if total_episodes else 0.0,
                "stay_share": round((affected_stays / total_stays), 4) if total_stays else 0.0,
                "forensics": {
                    "violation": forensics_v,
                    "satisfaction": forensics_s
                }
            }
        
        # Merge stats for this constraint
        entry.update(stats_map.get(cid, {
            "n_exposed": None,
            "n_unexposed": None,
            "a": None,
            "b": None,
            "c": None,
            "d": None,
            "fisher_p": None,
            "odds_ratio": None, 
            "odds_ratio_low": None,
            "odds_ratio_high": None,
            "risk_ratio": None,
            "rr_ci_low": None,
            "rr_ci_high": None,
            "p_value_raw": None,
            "p_value_bonf": None,
            "p_value_fdr": None, 
            "is_significant_bonf": False,
            "is_significant": False
        }))
        violation_frequency.append(entry)

    readiness_bottlenecks: list[dict[str, Any]] = []
    for cid, count in readiness_counter.most_common():
        readiness_bottlenecks.append(
            {
                "constraint_id": cid,
                "constraint_label": constraint_labels.get(cid, cid),
                "count": count,
                "episode_share": round((count / total_episodes), 4) if total_episodes else 0.0,
            }
        )

    conformance_vs_outcome: dict[str, dict[str, Any]] = {}
    for key in ("success", "failure", "unknown"):
        episodes = grouped[key]
        count = len(episodes)
        total_viol = sum(safe_float(ep.get("num_mandatory_violations")) for ep in episodes)
        total_sat = sum(safe_float(ep.get("num_mandatory_satisfactions")) for ep in episodes)
        ratio_sum = 0.0
        for ep in episodes:
            viol = safe_float(ep.get("num_mandatory_violations"))
            sat = safe_float(ep.get("num_mandatory_satisfactions"))
            denom = viol + sat
            ratio_sum += (viol / denom) if denom else 0.0

        conformance_vs_outcome[key] = {
            "episodes": count,
            "avg_mandatory_violations": round((total_viol / count), 3) if count else 0.0,
            "avg_mandatory_satisfactions": round((total_sat / count), 3) if count else 0.0,
            "avg_violation_ratio": round((ratio_sum / count), 4) if count else 0.0,
        }

    stay_summaries: list[dict[str, Any]] = []
    for stay_id in sorted(stay_to_episodes.keys()):
        episodes = stay_to_episodes[stay_id]
        success_count = sum(1 for ep in episodes if classify_outcome(ep.get("sbt_outcome")) == "success")
        failure_count = sum(1 for ep in episodes if classify_outcome(ep.get("sbt_outcome")) == "failure")
        unknown_count = sum(1 for ep in episodes if classify_outcome(ep.get("sbt_outcome")) == "unknown")
        total_viol = sum(safe_float(ep.get("num_mandatory_violations")) for ep in episodes)
        total_sat = sum(safe_float(ep.get("num_mandatory_satisfactions")) for ep in episodes)

        violated_constraints: set[str] = set()
        for ep in episodes:
            violated_constraints.update(parse_constraint_list(ep.get("mandatory_violated_constraints")))

        satisfied_constraints: set[str] = set()
        for ep in episodes:
            satisfied_constraints.update(parse_constraint_list(ep.get("mandatory_satisfied_constraints")))

        overall_outcome = "Mixed/Unknown"
        if success_count > 0 and failure_count == 0:
            overall_outcome = "Success"
        elif failure_count > 0 and success_count == 0:
            overall_outcome = "Failure"
        elif success_count > 0 and failure_count > 0:
            overall_outcome = "Mixed"

        stay_summaries.append(
            {
                "stay_id": stay_id,
                "episodes": len(episodes),
                "success_episodes": success_count,
                "failure_episodes": failure_count,
                "unknown_episodes": unknown_count,
                "overall_outcome": overall_outcome,
                "total_mandatory_violations": int(total_viol),
                "total_mandatory_satisfactions": int(total_sat),
                "avg_mandatory_violations": round((total_viol / len(episodes)), 3) if episodes else 0.0,
                "avg_mandatory_satisfactions": round((total_sat / len(episodes)), 3) if episodes else 0.0,
                "violated_constraints_count": len(violated_constraints),
                "violated_constraints": sorted(list(violated_constraints)),
                "satisfied_constraints": sorted(list(satisfied_constraints)),
            }
        )

    # Load item labels for the frontend
    item_labels = _load_item_labels(input_dir.parents[2])

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "total_stays": total_stays,
        "total_episodes": total_episodes,
        "violation_frequency": violation_frequency,
        "readiness_bottlenecks": readiness_bottlenecks,
        "conformance_vs_outcome": conformance_vs_outcome,
        "stay_summaries": stay_summaries,
        "item_labels": item_labels,
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate conformance summary JSON for frontend")
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=None,
        help="Directory containing case_*.json files (default: frontend/public/data if present, else frontend/src/data)",
    )
    parser.add_argument(
        "--stats-csv",
        type=Path,
        default=None,
        help="Optional CSV file containing statistical results (OR/p-values)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output summary path (default: <input-dir>/summary.json)",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    input_dir = (args.input_dir or infer_input_dir(project_root)).resolve()
    output_file = (args.output or (input_dir / "summary.json")).resolve()

    case_files = sorted(input_dir.glob("case_*.json"))
    if not case_files:
        raise FileNotFoundError(f"No case_*.json files found in: {input_dir}")

    summary = build_summary(case_files, input_dir, args.stats_csv)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(f"Processed {len(case_files)} case files")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
