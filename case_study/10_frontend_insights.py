"""Bundle the case-study result tables the frontend shows into one JSON file.

Steps 01-09 write their tables to `case_study/out/` for the thesis text. The
frontend needs a subset of them, served statically next to `summary.json`: the
deviation-breadth dose-response, the readiness violation causes, the
co-violation matrix, the deviation profiles, the mixed-outcome counts, and the
per-attempt violation trend.

It also writes `drilldown.json`, the per-rule split behind the Rule Drill-down
view: for each readiness constraint, satisfied against violated, and the
violations by cause, each group with its outcome association, readings, attempt
position and example stays.

This step only reshapes those files — it recomputes no statistic, so the numbers
in the app and the numbers in RESULTS_DIGEST.md cannot drift apart. Group counts,
histograms and example stays are plain group-bys over step 08's per-activation
records; every risk ratio is read from the step 04/08 tables. Run it after
`run_all.sh`.

Usage:
    python case_study/10_frontend_insights.py
"""

from __future__ import annotations

import importlib
import json
import re
import time
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import yaml

from config import (
    DECLARE_DIR,
    EPISODE_RESULTS,
    EPISODE_RESULTS_DIAG,
    OUT_DIR,
    ROOT,
    load_constraint_meta,
)
from derive.statistical_analysis import _binarize_label

# Step 08 owns the readiness criteria and the cause vocabulary; reuse them so the
# drill-down cannot disagree with the thesis tables. The module name starts with a
# digit, so it cannot be imported with a plain import statement.
_diagnostics = importlib.import_module("08_readiness_diagnostics")
CRITERION = _diagnostics.CRITERION
CAUSES = _diagnostics.CAUSES
CAUSE_LABEL = _diagnostics.CAUSE_LABEL
MARGIN_CONSTRAINTS = _diagnostics.MARGIN_CONSTRAINTS

FRONTEND_DATA = ROOT / "frontend" / "public" / "data"
INSIGHTS_FILE = FRONTEND_DATA / "insights.json"
DRILLDOWN_FILE = FRONTEND_DATA / "drilldown.json"
FREQUENCY_FILE = FRONTEND_DATA / "frequency_detail.json"
ITEM_DICTIONARY = ROOT / "configs" / "item_dictionary.yaml"

# Episode context the checker attaches to every forensics record. Shown only when
# the rule's own condition reads it (SBT-TM-02 reads hours_since_stay_start).
CONTEXT_KEYS = {
    "hours_since_stay_start", "hours_since_intubation", "ventilation_duration_hours",
    "sbt_duration_min", "gap_hours",
}
FREQUENCY_BINS = 30
MIN_HISTOGRAM_VALUES = 20

# As in case_study/09: later attempts are pooled into the last bucket.
MAX_ATTEMPT_BUCKET = 5
EXAMPLES_PER_GROUP = 6
HISTOGRAM_BINS = 40
SEED = 42

# The criterion each readiness constraint checks, worded as in Table 6.1, with the
# target activity whose most recent reading decides it.
CRITERION_TEXT = {
    "RC-DP-01": ("OxygenationMeasured",
                 "PaO2/FiO2 ≥ 150, or SpO2 ≥ 90 % on FiO2 ≤ 40 % and PEEP ≤ 5 cmH2O"),
    "RC-DP-02": ("pHMeasured", "Arterial pH > 7.25"),
    "RC-DP-03": ("HemoglobinMeasured", "Hemoglobin ≥ 7 g/dL"),
    "RC-DP-04": ("TemperatureMeasured", "Temperature ≤ 38 °C"),
    "RC-DP-05": ("VasopressorMeasured", "NE-equivalent dose ≤ 0.1 µg/kg/min"),
    "RC-DP-06": ("MentalStatusMeasured", "RASS level of consciousness = “No”, or SAS ∈ {3, 4}"),
    "RC-DP-07": ("InspiratoryEffortMeasured", "Spontaneous tidal volume > 0 mL"),
}

# What each cause means for one activation, in the words the app shows.
CAUSE_MEANING = {
    "satisfied": "The most recent reading in the 24 h before the trial met the criterion.",
    "undocumented": "No reading was charted in the 24 h before the trial started.",
    "no_payload": "A measurement event was charted, but without the value the criterion reads.",
    "partial_payload": "The criterion needs several readings; only some of them were charted.",
    "unmet": "The reading was charted and did not meet the threshold.",
}

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
        # The shares below are over the graded criteria only (RC-DP-06 excluded),
        # as in the thesis figure.
        "n_violated_graded": int(overview["n_violated_graded"]),
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


def _num(value) -> float | None:
    """A float for JSON, with NaN and infinities turned into None."""
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _violation_frequency() -> list[dict]:
    """Activation and violation rate per constraint (Table 6.4)."""
    df = _read_csv("violation_frequency.csv")
    keep = [
        "constraint_id", "label", "model_group", "template", "n_episodes",
        "n_satisfied", "n_violated", "n_vacuous", "n_activated", "activation_rate",
        "violation_rate_activated", "violation_rate_success", "violation_rate_failure",
        "outcome_entangled",
    ]
    return _records(df[keep])


def _association() -> list[dict]:
    """Per-constraint outcome association, vacuous episodes excluded (Table 6.6).

    SBT-TM-02 is flagged rather than dropped: its violation is defined by a
    successful late trial, so its risk ratio is degenerate by construction and the
    app leaves it out of the forest with a footnote, as the thesis table does.
    """
    df = _read_csv("association_activations_only.csv")
    keep = [
        "constraint_id", "label", "outcome_variable", "n_censored", "n_exposed",
        "n_unexposed", "a_violated_success", "b_violated_failure",
        "c_satisfied_success", "d_satisfied_failure", "rr", "rr_ci_low",
        "rr_ci_high", "or", "or_ci_low", "or_ci_high", "p_raw", "p_bonferroni",
        "n_tests", "significant_bonferroni", "degenerate_estimate",
        "used_continuity_correction",
    ]
    out = df[keep].copy()
    out["reference"] = out["outcome_variable"].map(
        {"same_episode": "own", "next_episode": "next"}
    )
    return _records(out.sort_values("rr"))


def _association_split() -> list[dict]:
    """Per-rule association with readiness violations split by cause (step 08).

    Readiness rules carry an `unmet` and a `documentation` arm; every other rule
    keeps its single step 04 estimate as arm `missing_action`.
    """
    out = _read_csv("association_split_by_cause.csv")
    out["reference"] = out["outcome_variable"].map(
        {"same_episode": "own", "next_episode": "next"}
    )
    return _records(out)


def _margin_strata() -> list[dict]:
    """Success by distance of an unmet reading from the threshold (Figure 6.5)."""
    return _records(_read_csv("readiness_margin_association.csv"))


def _cause_profile() -> list[dict]:
    """Success by the worst readiness evidence an episode carries (Section 6.4.5)."""
    return _records(_read_csv("readiness_cause_profile.csv"))


def _ablation() -> dict:
    """Segmentation ablation: verdicts masked and invented without episodes (Table 6.9)."""
    overview = _read_json("ablation_overview.json")
    per = _read_csv("ablation_by_constraint.csv")
    keep = [
        "constraint_id", "label", "model_group", "not_comparable",
        "not_comparable_reason", "stays_flagged_episode_level",
        "stays_flagged_trace_level", "masked_stays", "masking_rate",
        "trace_only_stays", "trace_only_rate", "activation_loss_rate",
        "mean_episodes_per_flagged_stay",
    ]
    rows = per[keep].copy()
    rows["disagreement"] = rows["masked_stays"] + rows["trace_only_stays"]
    return {
        # The absolute path of the machine that ran the ablation means nothing here.
        **{k: v for k, v in overview.items() if k != "ablation_source"},
        "per_constraint": _records(rows.sort_values("disagreement", ascending=False)),
    }


def _episodes_per_stay() -> list[dict]:
    """How many episodes a stay contains, with five and more pooled."""
    df = _read_csv("episodes_per_stay.csv")
    bucket = df["episodes_in_stay"].clip(upper=MAX_ATTEMPT_BUCKET)
    pooled = df.groupby(bucket).agg(n_stays=("n_stays", "sum")).reset_index()
    pooled["share_of_stays"] = pooled["n_stays"] / pooled["n_stays"].sum()
    pooled["label"] = pooled["episodes_in_stay"].astype(int).astype(str)
    pooled.loc[pooled["episodes_in_stay"] == MAX_ATTEMPT_BUCKET, "label"] += "+"
    return _records(pooled)


def _case_file(stay_id) -> object:
    return FRONTEND_DATA / f"case_{int(stay_id)}.json"


def _load_episodes() -> pd.DataFrame:
    """Episode verdicts and outcomes, one row per episode."""
    path = EPISODE_RESULTS if EPISODE_RESULTS.exists() else EPISODE_RESULTS_DIAG
    columns = [
        "stay_id", "episode_index", "sbt_attempt", "sbt_outcome", "next_sbt_outcome",
        "mandatory_violated_constraints", "mandatory_satisfied_constraints",
        "mandatory_vacuous_constraints", "info_violated_constraints",
        "info_satisfied_constraints", "info_vacuous_constraints",
    ]
    df = pd.read_csv(path, usecols=columns, low_memory=False)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)
    attempt = pd.to_numeric(df["sbt_attempt"], errors="coerce")
    df["attempt_bucket"] = attempt.clip(upper=MAX_ATTEMPT_BUCKET)
    return df


def _load_readiness_records() -> pd.DataFrame:
    """Step 08's per-activation readiness records.

    Read from its parquet cache when a parquet engine is installed; otherwise
    rebuilt from the diagnostic results with step 08's own function, so the
    records are the same either way.
    """
    path = OUT_DIR / "readiness_records.parquet"
    try:
        return pd.read_parquet(path)
    except ImportError:
        print("  no parquet engine; rebuilding readiness records from "
              f"{EPISODE_RESULTS_DIAG.name}")
    usecols = [
        "stay_id", "episode_index", "sbt_outcome",
        "violation_forensics", "satisfaction_forensics",
    ]
    df = pd.read_csv(EPISODE_RESULTS_DIAG, usecols=usecols, low_memory=False)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    return _diagnostics._episode_records(df)


def _histogram(satisfied: pd.Series, unmet: pd.Series) -> dict | None:
    """Shared bins over the 1st-99th percentile, as in step 08's margin figure."""
    combined = pd.concat([satisfied, unmet]).dropna()
    if combined.empty:
        return None
    low, high = float(combined.quantile(0.01)), float(combined.quantile(0.99))
    if low == high:
        low, high = low - 0.5, high + 0.5
    edges = np.linspace(low, high, HISTOGRAM_BINS + 1)

    def counts(values: pd.Series) -> list[int]:
        clipped = values.dropna().clip(lower=low, upper=high)
        return np.histogram(clipped, bins=edges)[0].astype(int).tolist()

    return {
        "edges": [float(e) for e in edges],
        "satisfied": counts(satisfied),
        "unmet": counts(unmet),
        "n_satisfied_with_reading": int(satisfied.notna().sum()),
        "n_unmet_with_reading": int(unmet.notna().sum()),
    }


def _examples(rows: pd.DataFrame, n: int) -> list[dict]:
    """A few stays from one group whose timeline the app can open."""
    rows = rows[[_case_file(s).exists() for s in rows["stay_id"]]]
    if rows.empty:
        return []
    picked = rows.sample(n=min(n, len(rows)), random_state=SEED)
    return [
        {
            "stay_id": str(int(r.stay_id)),
            "episode_index": int(r.episode_index),
            "value": _num(r.value),
            "outcome": None if pd.isna(r.outcome_binary)
            else ("success" if r.outcome_binary == 1 else "failure"),
        }
        for r in picked.sort_values(["stay_id", "episode_index"]).itertuples(index=False)
    ]


def _drilldown(records: pd.DataFrame, episodes: pd.DataFrame,
               labels: dict[str, str]) -> dict:
    """Satisfied vs. violated, and the violations by cause, per readiness rule."""
    causes_table = _read_csv("readiness_violation_causes.csv").set_index("constraint_id")
    assoc = _read_csv("readiness_cause_association.csv")
    strata = _read_csv("readiness_margin_association.csv")

    records = records.merge(
        episodes[["stay_id", "episode_index", "attempt_bucket"]],
        on=["stay_id", "episode_index"], how="left",
    )
    records["group"] = np.where(
        records["state"] == "satisfied", "satisfied", records["cause"].fillna("unclassified")
    )

    rules = {}
    for cid, spec in CRITERION.items():
        sub = records[records["constraint_id"] == cid]
        if sub.empty:
            continue
        n_act = len(sub)
        violated = sub[sub["state"] == "violated"]
        n_viol = len(violated)

        # The records must reproduce the thesis table before anything is shown.
        expected = causes_table.loc[cid]
        assert n_viol == int(expected["n_violated"]), (cid, n_viol, expected["n_violated"])
        for cause in CAUSES:
            got = int((violated["cause"] == cause).sum())
            assert got == int(expected[f"n_{cause}"]), (cid, cause, got)

        rule_assoc = assoc[assoc["constraint_id"] == cid].set_index("cause")
        satisfied = sub[sub["group"] == "satisfied"]
        reference_rate = satisfied["outcome_binary"].mean()

        groups = []
        for key in ["satisfied", *CAUSES]:
            arm = sub[sub["group"] == key]
            if arm.empty:
                continue
            row = {
                "key": key,
                "label": "satisfied" if key == "satisfied" else CAUSE_LABEL[key],
                "meaning": CAUSE_MEANING[key],
                "kind": "satisfied" if key == "satisfied"
                else ("care" if key == "unmet" else "documentation"),
                "n": int(len(arm)),
                "share_of_activations": len(arm) / n_act,
                "share_of_violated": None if key == "satisfied" else len(arm) / max(n_viol, 1),
                "success_rate": _num(arm["outcome_binary"].mean()),
                "value_median": _num(arm["value"].median()),
                "margin_median": _num(arm["margin"].median()),
                "rr": None, "rr_ci_low": None, "rr_ci_high": None,
                "p_raw": None, "p_bonferroni": None, "significant": None,
                "n_tests": None,
            }
            # Arms under 30 episodes were not tested in step 08 and carry no RR.
            if key != "satisfied" and key in rule_assoc.index:
                a = rule_assoc.loc[key]
                row.update({
                    "rr": _num(a["rr_point"]), "rr_ci_low": _num(a["rr_ci_low"]),
                    "rr_ci_high": _num(a["rr_ci_high"]), "p_raw": _num(a["p_raw"]),
                    "p_bonferroni": _num(a["p_bonferroni"]),
                    "significant": bool(a["significant"]), "n_tests": int(a["n_tests"]),
                })
            groups.append(row)

        pooled = rule_assoc.loc["all_violations"] if "all_violations" in rule_assoc.index else None
        by_attempt = []
        for bucket, part in sub[sub["attempt_bucket"].notna()].groupby("attempt_bucket"):
            by_attempt.append({
                "bucket": int(bucket),
                "n_activations": int(len(part)),
                "counts": {k: int((part["group"] == k).sum()) for k in ["satisfied", *CAUSES]},
            })

        hist = None
        if spec["item"] is not None:
            hist = _histogram(
                satisfied["value"],
                violated.loc[violated["cause"] == "unmet", "value"],
            )
            if hist is not None:
                hist.update({
                    "threshold": spec["threshold"], "direction": spec["direction"],
                    "unit": spec["unit"],
                })

        target, criterion = CRITERION_TEXT[cid]
        rules[cid] = {
            "constraint_id": cid,
            "label": labels.get(cid, cid),
            "criterion": criterion,
            "template": "Precedence",
            "activation": "SBTStarted",
            "target": target,
            "time_condition": "[0, 24 h] before the trial",
            "target_selection": "latest",
            "unit": spec["unit"],
            "has_margin": cid in MARGIN_CONSTRAINTS,
            "counts": {
                "n_activations": n_act,
                "n_satisfied": int(len(satisfied)),
                "n_violated": n_viol,
                **{f"n_{c}": int((violated["cause"] == c).sum()) for c in CAUSES},
            },
            "reference_success_rate": _num(reference_rate),
            "all_violations": None if pooled is None else {
                "success_rate": _num(pooled["success_rate"]),
                "rr": _num(pooled["rr_point"]), "rr_ci_low": _num(pooled["rr_ci_low"]),
                "rr_ci_high": _num(pooled["rr_ci_high"]), "p_raw": _num(pooled["p_raw"]),
            },
            "groups": groups,
            "histogram": hist,
            "margin_strata": _records(strata[strata["constraint_id"] == cid]),
            "by_attempt": by_attempt,
            "examples": {
                key: _examples(sub[sub["group"] == key], EXAMPLES_PER_GROUP)
                for key in ["satisfied", *CAUSES]
                if (sub["group"] == key).any()
            },
        }

    # Causes are recorded only for the precedence family, and a reading can be
    # "unmet" only where a data condition reads it: the readiness rules.
    unsupported = [
        {"constraint_id": cid, "label": lab}
        for cid, lab in sorted(labels.items()) if cid not in rules
    ]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rules": rules,
        "order": [cid for cid in CRITERION if cid in rules],
        "unsupported": unsupported,
        "unsupported_reason": (
            "Failure causes are recorded only for data-conditioned precedence rules, "
            "so only the readiness constraints can be split into documentation gaps "
            "and unmet criteria."
        ),
    }


def _showcase_stays(episodes: pd.DataFrame, records: pd.DataFrame,
                    top: int = 10) -> list[dict]:
    """Stays that show Figure 1.1 in real data.

    Two or three episodes, a failed attempt before a successful one, and a
    readiness criterion that was charted and unmet in the failed attempt but met
    in the successful one: one stay, one rule, two verdicts, both on recorded
    readings. RC-DP-06 and RC-DP-07 are left out because their violations are
    almost entirely missing documentation (Section 6.4.3), which would make a
    poor example of a deviation in care.
    """
    graded = records[
        records["constraint_id"].isin(MARGIN_CONSTRAINTS)
        & ((records["state"] == "satisfied") | (records["cause"] == "unmet"))
    ]
    by_stay = dict(tuple(graded.groupby("stay_id")))
    all_violations = records[records["state"] == "violated"]
    violations_by_episode = all_violations.groupby(["stay_id", "episode_index"])[
        "constraint_id"
    ].apply(lambda s: sorted(s))

    per_stay = episodes.groupby("stay_id")["episode_index"].transform("size")
    eligible = episodes[per_stay.between(2, 3) & episodes["outcome_binary"].notna()]

    candidates = []
    for stay_id, eps in eligible.groupby("stay_id"):
        states = by_stay.get(stay_id)
        if states is None:
            continue
        eps = eps.sort_values("episode_index")
        failed = eps[eps["outcome_binary"] == 0]
        if failed.empty:
            continue
        first_fail = int(failed["episode_index"].iloc[0])
        later_success = eps[(eps["outcome_binary"] == 1) & (eps["episode_index"] > first_fail)]
        if later_success.empty:
            continue
        success_idx = int(later_success["episode_index"].iloc[0])

        unmet = states[(states["episode_index"] == first_fail) & (states["cause"] == "unmet")]
        met = states[(states["episode_index"] == success_idx) & (states["state"] == "satisfied")]
        flips = unmet.merge(met, on="constraint_id", suffixes=("_failed", "_successful"))
        if flips.empty or not _case_file(stay_id).exists():
            continue
        candidates.append({
            "stay_id": str(int(stay_id)),
            "n_episodes": int(len(eps)),
            "failed_episode": first_fail,
            "successful_episode": success_idx,
            "flips": [
                {
                    "constraint_id": r.constraint_id,
                    "value_failed": _num(r.value_failed),
                    "value_successful": _num(r.value_successful),
                    "unit": CRITERION[r.constraint_id]["unit"],
                }
                for r in flips.itertuples(index=False)
            ],
            "violated_in_failed": violations_by_episode.get((stay_id, first_fail), []),
            "violated_in_successful": violations_by_episode.get((stay_id, success_idx), []),
            "case_file_kb": round(_case_file(stay_id).stat().st_size / 1024, 1),
        })

    # Cleanest first: two episodes, one flipping rule, few other violations in
    # the successful attempt, and a timeline small enough to open instantly.
    candidates.sort(key=lambda c: (
        c["n_episodes"], len(c["flips"]), len(c["violated_in_successful"]),
        c["case_file_kb"],
    ))
    return candidates[:top]


def _rule_configs() -> dict[str, dict]:
    """Raw constraint entries from configs/declare/*.yaml, keyed by id."""
    out = {}
    for cfg in sorted(DECLARE_DIR.glob("*.yaml")):
        if cfg.stem == "weights":
            continue
        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
        constraints = (
            data.get("constraints") or data.get("model", {}).get("constraints") or []
        )
        for c in constraints:
            if isinstance(c, dict) and c.get("id"):
                out[str(c["id"])] = c
    return out


def _item_labels() -> dict[str, str]:
    """itemid / virtual id -> label, flattened over source tables."""
    data = yaml.safe_load(ITEM_DICTIONARY.read_text(encoding="utf-8")) or {}
    out = {}
    for items in (data.get("sources") or {}).values():
        for key, label in (items or {}).items():
            out[str(key)] = str(label)
    return out


def _time_window(cfg: dict) -> str:
    """The rule's time condition in words."""
    tc = cfg.get("time_condition") or {}
    lo, hi = tc.get("min_hours"), tc.get("max_hours")
    if lo is not None and hi is not None and hi <= 0:
        return f"within {abs(lo):g} h before the activation"
    if hi is not None:
        return f"within {hi:g} h after the activation"
    if cfg.get("context_window_post_hours"):
        return f"within {cfg['context_window_post_hours']:g} h after the activation"
    return "anywhere in the episode"


def _condition_threshold(cid: str, key: str, cfg: dict) -> float | None:
    """Threshold on `key`: step 08's criterion, else a literal in the condition."""
    spec = CRITERION.get(cid)
    if spec and spec.get("item") == key:
        return spec.get("threshold")
    for field in ("activation_condition", "correlation_condition", "target_condition"):
        expr = cfg.get(field)
        if not isinstance(expr, str):
            continue
        m = re.search(rf"\b{re.escape(key)}\b\s*(>=|>|<=|<)\s*([0-9.]+)", expr)
        if m:
            return float(m.group(2))
    return None


def _pair_histogram(satisfied: list, violated: list, threshold=None) -> dict | None:
    """Shared-bin histogram of satisfied vs violated values, 1st-99th percentile."""
    sat = np.asarray([v for v in satisfied if v is not None and np.isfinite(v)], float)
    vio = np.asarray([v for v in violated if v is not None and np.isfinite(v)], float)
    if len(sat) + len(vio) < MIN_HISTOGRAM_VALUES:
        return None
    both = np.concatenate([sat, vio])
    lo, hi = np.percentile(both, [1, 99])
    if threshold is not None:
        lo, hi = min(lo, threshold), max(hi, threshold)
    if hi <= lo:
        lo, hi = lo - 0.5, hi + 0.5
    edges = np.linspace(lo, hi, FREQUENCY_BINS + 1)
    return {
        "edges": [round(float(e), 6) for e in edges],
        "satisfied": np.histogram(np.clip(sat, lo, hi), edges)[0].tolist(),
        "violated": np.histogram(np.clip(vio, lo, hi), edges)[0].tolist(),
        "n_satisfied": int(len(sat)),
        "n_violated": int(len(vio)),
        "median_satisfied": _num(np.median(sat)) if len(sat) else None,
        "median_violated": _num(np.median(vio)) if len(vio) else None,
        "threshold": threshold,
    }


def _frequency_detail(frequency: list[dict], records: pd.DataFrame) -> dict:
    """Per-rule timing and value distributions, satisfied vs violated.

    Built from the per-episode forensics in the results CSV (the same run as the
    thesis tables), binned here so the app never loads the raw arrays. That CSV
    keeps no reading for a violated activation, so the graded readiness rules take
    their criterion reading from step 08's records instead (satisfied vs assessed
    and not met), the same values the drill-down plots.
    """
    configs = _rule_configs()
    item_labels = _item_labels()
    cols = ["violation_forensics", "satisfaction_forensics"]
    raw = pd.read_csv(EPISODE_RESULTS, usecols=cols, dtype=str)

    delays = {}   # cid -> {"satisfied": [...], "violated": [...]}
    values = {}   # cid -> key -> {"satisfied": [...], "violated": [...]}
    for col, state in (("satisfaction_forensics", "satisfied"),
                       ("violation_forensics", "violated")):
        for blob in raw[col].dropna():
            for cid, data in _diagnostics._parse(blob).items():
                if not isinstance(data, dict):
                    continue
                d = data.get("delay_seconds")
                if d is not None:
                    delays.setdefault(cid, {"satisfied": [], "violated": []})[state].append(
                        abs(float(d)) / 3600.0
                    )
                for key, v in (data.get("deltas") or {}).items():
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        continue
                    if "fio2" in key.lower() and 0 < v <= 1:
                        v *= 100.0  # FiO2 charted as a fraction in some rows
                    values.setdefault(cid, {}).setdefault(
                        key, {"satisfied": [], "violated": []}
                    )[state].append(v)

    rules = {}
    for row in frequency:
        cid = row["constraint_id"]
        cfg = configs.get(cid, {})
        condition_text = " ".join(
            str(cfg.get(f) or "")
            for f in ("activation_condition", "correlation_condition", "target_condition")
        )
        spec = CRITERION.get(cid) or {}
        graded_key = spec.get("item")
        if graded_key:
            sub = records[records["constraint_id"] == cid]
            values.setdefault(cid, {})[graded_key] = {
                "satisfied": sub.loc[sub["state"] == "satisfied", "value"].dropna().tolist(),
                "violated": sub.loc[sub["cause"] == "unmet", "value"].dropna().tolist(),
            }
        dists = []
        for key, split in sorted((values.get(cid) or {}).items(),
                                 key=lambda kv: (kv[0] != graded_key, kv[0])):
            if key in CONTEXT_KEYS and key not in condition_text:
                continue
            # Readiness rules: only the criterion reading. The other payload items
            # (SpO2/FiO2/PEEP of RC-DP-01's fallback, RC-DP-06's scores) exist for
            # satisfied activations only and say nothing about the violations.
            if cid in CRITERION and key != graded_key:
                continue
            threshold = _condition_threshold(cid, key, cfg)
            hist = _pair_histogram(split["satisfied"], split["violated"], threshold)
            if hist is None:
                continue
            label = spec.get("unit") if key == graded_key else None
            dists.append({
                "key": key,
                "label": label or item_labels.get(key) or key.replace("_", " "),
                # violated = assessed and not met; documentation gaps carry no value
                "violated_kind": "unmet" if key == graded_key else "violated",
                **hist,
            })
        timing = _pair_histogram(
            (delays.get(cid) or {}).get("satisfied", []),
            (delays.get(cid) or {}).get("violated", []),
        )
        rules[cid] = {
            **row,
            "activation": cfg.get("activation"),
            "target": cfg.get("target"),
            "time_window": _time_window(cfg),
            "condition": cfg.get("correlation_condition_display")
                         or cfg.get("activation_condition_display"),
            "target_selection": cfg.get("target_selection"),
            "outcome_scope": cfg.get("outcome_scope") or "same_episode",
            "timing": timing,
            "values": dists,
        }
    order = [r["constraint_id"] for r in sorted(
        frequency, key=lambda r: -(r.get("violation_rate_activated") or 0)
    )]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "order": order,
        "rules": rules,
    }


def main() -> None:
    t0 = time.perf_counter()
    print("case_study/10_frontend_insights.py")

    meta = load_constraint_meta()
    labels = dict(zip(meta["constraint_id"], meta["label"]))
    groups = dict(zip(meta["constraint_id"], meta["model_group"]))

    episodes = _load_episodes()
    print(f"  loaded {len(episodes):,} episodes")
    records = _load_readiness_records()
    print(f"  loaded {len(records):,} readiness activations")

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
        "violation_frequency": _violation_frequency(),
        "association": _association(),
        "association_split": _association_split(),
        "margin_strata": _margin_strata(),
        "cause_profile": _cause_profile(),
        "ablation": _ablation(),
        "episodes_per_stay": _episodes_per_stay(),
        "showcase_stays": _showcase_stays(episodes, records),
        "constraint_labels": labels,
        "constraint_groups": groups,
    }

    FRONTEND_DATA.mkdir(parents=True, exist_ok=True)
    INSIGHTS_FILE.write_text(
        json.dumps(payload, indent=2, default=str), encoding="utf-8"
    )
    size_kb = INSIGHTS_FILE.stat().st_size / 1024
    print(f"  json   -> {INSIGHTS_FILE} ({size_kb:.1f} KB)")

    drilldown = _drilldown(records, episodes, labels)
    DRILLDOWN_FILE.write_text(
        json.dumps(drilldown, indent=2, default=str), encoding="utf-8"
    )
    size_kb = DRILLDOWN_FILE.stat().st_size / 1024
    print(f"  json   -> {DRILLDOWN_FILE} ({size_kb:.1f} KB)")

    detail = _frequency_detail(payload["violation_frequency"], records)
    FREQUENCY_FILE.write_text(json.dumps(detail, indent=2, default=str), encoding="utf-8")
    size_kb = FREQUENCY_FILE.stat().st_size / 1024
    print(f"  json   -> {FREQUENCY_FILE} ({size_kb:.1f} KB)")
    print(f"  done in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main()
