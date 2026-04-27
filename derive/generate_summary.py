#!/usr/bin/env python3
"""Generate global conformance summary metrics for the frontend dashboard.

The script scans case JSON files and writes an aggregated summary JSON used by the
frontend Summary view.
"""

from __future__ import annotations

import argparse
import json
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


def infer_input_dir(project_root: Path) -> Path:
    public_dir = project_root / "frontend" / "public" / "data"
    src_dir = project_root / "frontend" / "src" / "data"
    if public_dir.exists():
        return public_dir
    return src_dir


def build_summary(case_files: list[Path], input_dir: Path) -> dict[str, Any]:
    all_episodes: list[dict[str, Any]] = []
    stay_to_episodes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    violation_counter: Counter[str] = Counter()
    violation_stays: dict[str, set[str]] = defaultdict(set)
    readiness_counter: Counter[str] = Counter()
    constraint_labels: dict[str, str] = {}

    for case_file in case_files:
        with case_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        stay_id = str(payload.get("case_id") or payload.get("stay_id") or "")
        episodes = payload.get("conformance") or []

        definitions = payload.get("constraint_definitions") or {}
        if isinstance(definitions, dict):
            for cid, meta in definitions.items():
                if not isinstance(meta, dict):
                    continue
                label = meta.get("label")
                if label and cid not in constraint_labels:
                    constraint_labels[cid] = str(label)

        for episode in episodes:
            ep = dict(episode)
            ep_stay_id = str(ep.get("stay_id") or stay_id)
            ep["stay_id"] = ep_stay_id
            all_episodes.append(ep)
            stay_to_episodes[ep_stay_id].append(ep)

            for cid in parse_constraint_list(ep.get("mandatory_violated_constraints")):
                violation_counter[cid] += 1
                violation_stays[cid].add(ep_stay_id)
                if cid.startswith("RC-DP-"):
                    readiness_counter[cid] += 1

    total_stays = len(stay_to_episodes)
    total_episodes = len(all_episodes)

    violation_frequency: list[dict[str, Any]] = []
    for cid, count in violation_counter.most_common():
        affected_stays = len(violation_stays[cid])
        violation_frequency.append(
            {
                "constraint_id": cid,
                "constraint_label": constraint_labels.get(cid, cid),
                "count": count,
                "affected_stays": affected_stays,
                "episode_share": round((count / total_episodes), 4) if total_episodes else 0.0,
                "stay_share": round((affected_stays / total_stays), 4) if total_stays else 0.0,
            }
        )

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

    grouped: dict[str, list[dict[str, Any]]] = {"success": [], "failure": [], "unknown": []}
    for ep in all_episodes:
        grouped[classify_outcome(ep.get("sbt_outcome"))].append(ep)

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
            }
        )

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_dir": str(input_dir),
        "total_stays": total_stays,
        "total_episodes": total_episodes,
        "violation_frequency": violation_frequency,
        "readiness_bottlenecks": readiness_bottlenecks,
        "conformance_vs_outcome": conformance_vs_outcome,
        "stay_summaries": stay_summaries,
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

    summary = build_summary(case_files, input_dir)

    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2)
        handle.write("\n")

    print(f"Processed {len(case_files)} case files")
    print(f"Output: {output_file}")


if __name__ == "__main__":
    main()
