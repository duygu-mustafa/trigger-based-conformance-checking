"""Bundle the case-study result tables the frontend shows into one JSON file.

Steps 01-09 write their tables to `case_study/out/` for the thesis text. The
frontend needs a subset of them, served statically next to `summary.json`: the
deviation-breadth dose-response, the readiness violation causes, the
co-violation matrix, the deviation profiles, the mixed-outcome counts, and the
per-attempt violation trend.

This step only reshapes those files — it recomputes nothing, so the numbers in
the app and the numbers in RESULTS_DIGEST.md cannot drift apart. Run it after
`run_all.sh`.

Usage:
    python case_study/10_frontend_insights.py
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import pandas as pd

from config import OUT_DIR, ROOT, load_constraint_meta

FRONTEND_DATA = ROOT / "frontend" / "public" / "data"
INSIGHTS_FILE = FRONTEND_DATA / "insights.json"

# Mirrors case_study/09: RC-DP-06 is violated in essentially every activation and
# would appear in every profile, so the deviation analyses exclude it. Repeated
# here so the app can say *why* the matrix has six rows and not seven.
SATURATED = ["RC-DP-06"]


def _read_csv(name: str) -> pd.DataFrame:
    path = OUT_DIR / name
    if not path.exists():
        raise SystemExit(
            f"missing {path} — run `bash case_study/run_all.sh` before this step"
        )
    return pd.read_csv(path)


def _read_json(name: str) -> dict:
    path = OUT_DIR / name
    if not path.exists():
        raise SystemExit(
            f"missing {path} — run `bash case_study/run_all.sh` before this step"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _records(df: pd.DataFrame) -> list[dict]:
    """Rows as plain dicts with NaN turned into None (invalid in JSON)."""
    return json.loads(df.to_json(orient="records"))


def _cohort(log: dict, episodes: dict, per_episode: pd.DataFrame) -> dict:
    """Headline counts that frame every other number in the app.

    The shifted-timestamp span is deliberately left out: MIMIC-IV date-shifts
    each patient, so a 104-year window would read as a study period.
    """
    viol = per_episode[
        per_episode["metric"] == "mandatory_violations_per_episode"
    ].iloc[0]
    return {
        "n_events": int(log["n_events"]),
        "n_stays": int(log["n_stays"]),
        "n_patients": int(log["n_patients"]),
        "n_distinct_activities": int(log["n_distinct_activities"]),
        "n_source_tables": int(log["n_source_tables"]),
        "n_model_activities": int(log["n_model_activities_observed"]),
        "n_model_activity_events": int(log["n_model_activity_events"]),
        "model_activity_share": float(log["model_activity_share"]),
        "n_episodes": int(episodes["n_episodes"]),
        "n_episodes_evaluable": int(episodes["n_episodes_evaluable_outcome"]),
        "failure_rate_evaluable": float(episodes["failure_rate_evaluable"]),
        "share_stays_single_episode": float(episodes["share_stays_single_episode"]),
        "median_mandatory_violations": float(viol["median"]),
        "mean_mandatory_violations": float(viol["mean"]),
    }


def _breadth(labels: dict[str, str]) -> dict:
    """Dose-response of readiness-violation breadth against SBT success.

    Two arm families share one table in step 09: `breadth` (number of criteria
    violated) and `sole criterion` (which single criterion was violated, for the
    episodes that violated exactly one).
    """
    outcomes = _read_csv("deviation_profile_outcomes.csv")
    sizes = _read_csv("deviation_profile_sizes.csv")
    overview = _read_json("deviation_patterns_overview.json")

    breadth = outcomes[outcomes["kind"] == "breadth"].copy()
    breadth["arm"] = breadth["arm"].astype(int)
    breadth = breadth.sort_values("arm")

    # The zero-violation arm has no row in the outcome table (it is the
    # reference), so its episode count comes from the size distribution.
    by_size = {int(r["n_violated"]): r for _, r in sizes.iterrows()}
    arms = []
    for _, row in breadth.iterrows():
        size = by_size.get(int(row["arm"]), {})
        arms.append(
            {
                "n_violated": int(row["arm"]),
                "n_episodes": int(row["n_episodes"]),
                "share": float(size.get("share")) if "share" in size else None,
                "success_rate": float(row["success_rate"]),
                "rr_point": float(row["rr_point"]),
                "rr_ci_low": float(row["rr_ci_low"]),
                "rr_ci_high": float(row["rr_ci_high"]),
                "p_raw": float(row["p_raw"]),
            }
        )

    sole = outcomes[outcomes["kind"] == "sole criterion"].copy()
    sole_rows = [
        {
            "constraint_id": str(row["arm"]),
            "label": labels.get(str(row["arm"]), str(row["arm"])),
            "n_episodes": int(row["n_episodes"]),
            "success_rate": float(row["success_rate"]),
            "rr_point": float(row["rr_point"]),
            "rr_ci_low": float(row["rr_ci_low"]),
            "rr_ci_high": float(row["rr_ci_high"]),
            "p_raw": float(row["p_raw"]),
        }
        for _, row in sole.sort_values("rr_point").iterrows()
    ]

    reference = float(breadth["reference_success_rate"].iloc[0])
    zero_arm = by_size.get(0, {})
    return {
        "reference_success_rate": reference,
        "reference_n_episodes": int(zero_arm.get("n_episodes", 0)),
        "arms": arms,
        "sole_criterion": sole_rows,
        "n_criteria_considered": len(sole_rows),
        "mean_criteria_violated": float(overview["mean_criteria_violated"]),
        "share_no_readiness_violation": float(
            overview["share_no_readiness_violation"]
        ),
        "excluded_saturated": SATURATED,
    }


def _profiles() -> dict:
    """Which readiness criteria are violated together, as named profiles."""
    top = _read_csv("deviation_profiles_top.csv")
    overview = _read_json("deviation_patterns_overview.json")
    rows = [
        {
            "profile": str(row["profile"]),
            "members": str(row["profile"]).split("+"),
            "n_episodes": int(row["n_episodes"]),
            "n_criteria": int(row["n_criteria"]),
            "share": float(row["share"]),
        }
        for _, row in top.iterrows()
    ]
    return {
        "top": rows,
        "n_distinct": int(overview["n_distinct_profiles"]),
        "share_single_criterion": float(overview["share_single_criterion_profiles"]),
        "top_profile_share": float(overview["top_profile_share"]),
    }


def _coviolation(labels: dict[str, str]) -> dict:
    """P(column violated | row violated), plus each criterion's own rate."""
    matrix = _read_csv("readiness_coviolation_matrix.csv")
    ids = [c for c in matrix.columns if c != "given_violated"]
    ordered = matrix.set_index("given_violated").loc[ids, ids]

    causes = _read_csv("readiness_violation_causes.csv").set_index("constraint_id")
    marginal = {
        cid: int(causes.loc[cid, "n_violated"]) if cid in causes.index else None
        for cid in ids
    }
    return {
        "ids": ids,
        "labels": {cid: labels.get(cid, cid) for cid in ids},
        "matrix": [[float(v) for v in ordered.loc[cid]] for cid in ids],
        "n_violated": marginal,
        "excluded_saturated": SATURATED,
    }


def _causes(labels: dict[str, str]) -> dict:
    """Documentation gap vs. genuinely unmet physiology, per readiness criterion.

    `undocumented` / `partial payload` mean the checker never saw a usable
    reading; `unmet` means it saw one and the criterion was not satisfied. Only
    the latter is a care deviation.
    """
    df = _read_csv("readiness_violation_causes.csv")
    overview = _read_json("readiness_diagnostics_overview.json")
    rows = [
        {
            "constraint_id": str(row["constraint_id"]),
            "label": labels.get(str(row["constraint_id"]), str(row["constraint_id"])),
            "n_violated": int(row["n_violated"]),
            "share_undocumented": float(row["share_undocumented"]),
            "share_partial_payload": float(row["share_partial_payload"]),
            "share_unmet": float(row["share_unmet"]),
            "share_documentation": float(row["share_documentation"]),
        }
        for _, row in df.sort_values("share_documentation").iterrows()
    ]
    return {
        "per_constraint": rows,
        "n_activations": int(overview["n_activations"]),
        "n_violated": int(overview["n_violated"]),
        "share_documentation": float(overview["share_violations_documentation"]),
        "share_care": float(overview["share_violations_care"]),
    }


def _mixed_outcomes() -> dict:
    """How often one per-stay outcome label would be wrong for part of the stay."""
    overview = _read_json("mixed_outcomes.json")
    by_count = _read_csv("mixed_outcomes_by_episode_count.csv")
    composition = _read_csv("mixed_outcomes_composition_by_episode_count.csv")
    keep = {
        k: v
        for k, v in overview.items()
        if k != "source"  # absolute path of a machine that is not the user's
    }
    return {
        **keep,
        "by_episode_count": _records(by_count),
        "composition_by_episode_count": _records(composition),
    }


def _attempt_trend(labels: dict[str, str]) -> list[dict]:
    """Violation rate by weaning-attempt index, grouped per constraint."""
    df = _read_csv("violation_by_attempt.csv")
    df["attempt_bucket"] = df["attempt_bucket"].astype(int)
    out = []
    for cid, part in df.groupby("constraint_id", sort=True):
        part = part.sort_values("attempt_bucket")
        buckets = [
            {
                "bucket": int(row["attempt_bucket"]),
                "n_activated": int(row["n_activated"]),
                "n_violated": int(row["n_violated"]),
                "violation_rate": float(row["violation_rate"]),
            }
            for _, row in part.iterrows()
        ]
        rates = [b["violation_rate"] for b in buckets]
        out.append(
            {
                "constraint_id": str(cid),
                "label": labels.get(str(cid), str(cid)),
                "buckets": buckets,
                "n_activated_total": int(part["n_activated"].sum()),
                # Signed span of the trend: how much the rate moves from the
                # first bucket to the last, which is what the app sorts on.
                "delta_first_to_last": float(rates[-1] - rates[0]) if rates else 0.0,
            }
        )
    return sorted(out, key=lambda r: abs(r["delta_first_to_last"]), reverse=True)


def main() -> None:
    t0 = time.perf_counter()
    print("case_study/10_frontend_insights.py")

    meta = load_constraint_meta()
    labels = dict(zip(meta["constraint_id"], meta["label"]))
    groups = dict(zip(meta["constraint_id"], meta["model_group"]))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cohort": _cohort(
            _read_json("log_overview.json"),
            _read_json("episode_overview.json"),
            _read_csv("violations_per_episode.csv"),
        ),
        "breadth": _breadth(labels),
        "profiles": _profiles(),
        "coviolation": _coviolation(labels),
        "causes": _causes(labels),
        "mixed_outcomes": _mixed_outcomes(),
        "attempt_trend": _attempt_trend(labels),
        "violations_per_episode": _records(
            _read_csv("violations_per_episode_histogram.csv")
        ),
        "vacuity_by_group": _records(_read_csv("violation_frequency_by_group.csv")),
        "constraint_labels": labels,
        "constraint_groups": groups,
    }

    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    INSIGHTS_FILE.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    size_kb = INSIGHTS_FILE.stat().st_size / 1024
    print(f"  json   -> {INSIGHTS_FILE} ({size_kb:.1f} KB)")
    print(f"  done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
