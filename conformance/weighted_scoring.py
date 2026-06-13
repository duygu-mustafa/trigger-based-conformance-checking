"""Weighted, fuzzy conformance scoring based on thesis Section 3.

This module implements formulas (3.1) to (3.5) from the thesis method.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from typing import Iterable

import numpy as np
import pandas as pd

from conformance.results import ConformanceOutcome, ConstraintResult, TraceResult
from conformance.types import DeclareTemplate, NEGATIVE_TEMPLATES, UNARY_TEMPLATES


@dataclass(frozen=True)
class Constraint:
    """Declarative constraint metadata used for weighted scoring.

    Implements inputs needed for formulas (3.1) to (3.5) and the newer
    fuzzy trace-scoring pipeline.
    """

    constraint_id: str
    template_type: str
    metadata_scores: dict[str, float] = field(default_factory=dict)
    theta: float | None = None
    theta_crit: float | None = None
    count_target: float | None = None
    delta_acc: float | None = None
    delta_unacc: float | None = None
    r_acc: float | None = None
    r_unacc: float | None = None
    aggregation: str = "mean"


@dataclass(frozen=True)
class ViolationInstance:
    """Single violation instance for a trace and constraint.

    Used to compute fuzzy severity in formula (3.2) and effective penalty in
    formula (3.3).
    """

    case_id: str
    constraint_id: str
    violation_type: str
    x: float | None = None
    timestamp: pd.Timestamp | None = None


def _load_yaml_dict(path: str | Path) -> dict[str, Any]:
    """Load a YAML file and return a top-level mapping."""

    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to load model/weights YAML files. Install with `pip install pyyaml`."
        ) from exc

    yaml_path = Path(path)
    with yaml_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Expected top-level mapping in YAML file: {yaml_path}")
    return data


def load_constraints_with_weights(
    model_yaml_path: str | Path,
    weights_yaml_path: str | Path,
    *,
    default_metadata_scores: dict[str, float] | None = None,
) -> list[Constraint]:
    """Build scoring constraints from Declare model YAML + weight YAML.

    Expected model format: `model.constraints` list with fields `id`, `template`.
    Expected weights format:

    ```yaml
    weights:
      CONSTRAINT_ID:
        metadata_scores:
          clinical_consequence: 0.9
          unnoticed_frequency: 0.8
          must_not_vs_should: 0.7
        theta: 105
        theta_crit: 150
    ```

    Theta values are optional and only needed for threshold-style severity.
    """

    model_data = _load_yaml_dict(model_yaml_path)
    weights_data = _load_yaml_dict(weights_yaml_path)

    model_block = model_data.get("model")
    if not isinstance(model_block, dict):
        model_block = {}

    raw_constraints = model_block.get("constraints", model_data.get("constraints"))
    if not isinstance(raw_constraints, list):
        raise ValueError("Model YAML must contain constraints as a list (model.constraints or top-level constraints).")

    raw_weights = weights_data.get("weights", {})
    if raw_weights is None:
        raw_weights = {}
    if not isinstance(raw_weights, dict):
        raise ValueError("Weights YAML must contain a mapping at key 'weights'.")

    out: list[Constraint] = []
    missing: list[str] = []

    for raw in raw_constraints:
        if not isinstance(raw, dict):
            continue

        constraint_id = raw.get("id")
        template_type = raw.get("template")
        if constraint_id is None or template_type is None:
            continue

        entry = raw_weights.get(str(constraint_id), {})
        if entry is None:
            entry = {}
        if not isinstance(entry, dict):
            raise ValueError(f"weights.{constraint_id} must be a mapping.")

        metadata_scores = entry.get("metadata_scores", None)
        if metadata_scores is None:
            if default_metadata_scores is None:
                missing.append(str(constraint_id))
                continue
            metadata_scores = default_metadata_scores

        if not isinstance(metadata_scores, dict) or not metadata_scores:
            raise ValueError(
                f"weights.{constraint_id}.metadata_scores must be a non-empty mapping."
            )

        theta = entry.get("theta")
        theta_crit = entry.get("theta_crit")
        count_target = entry.get("count_target")
        delta_acc = entry.get("delta_acc")
        delta_unacc = entry.get("delta_unacc")
        r_acc = entry.get("r_acc")
        r_unacc = entry.get("r_unacc")
        aggregation = entry.get("aggregation", "mean")

        out.append(
            Constraint(
                constraint_id=str(constraint_id),
                template_type=str(template_type),
                metadata_scores={str(k): float(v) for k, v in metadata_scores.items()},
                theta=float(theta) if theta is not None else None,
                theta_crit=float(theta_crit) if theta_crit is not None else None,
                count_target=float(count_target) if count_target is not None else None,
                delta_acc=float(delta_acc) if delta_acc is not None else None,
                delta_unacc=float(delta_unacc) if delta_unacc is not None else None,
                r_acc=float(r_acc) if r_acc is not None else None,
                r_unacc=float(r_unacc) if r_unacc is not None else None,
                aggregation=str(aggregation),
            )
        )

    if missing:
        preview = ", ".join(sorted(missing)[:8])
        raise ValueError(
            "Missing metadata_scores for constraint IDs in weights YAML. "
            f"Examples: {preview}"
        )

    return out


def compute_w_max(constraint: Constraint) -> float:
    """Compute static maximum weight w_max(c) using formula (3.1).

    If all metadata dimension scores are 1, returns 2; otherwise returns the
    mean of metadata scores.
    """

    if not constraint.metadata_scores:
        raise ValueError(f"Constraint '{constraint.constraint_id}' has no metadata scores.")

    values = np.asarray(list(constraint.metadata_scores.values()), dtype=float)
    if np.any((values < 0.0) | (values > 1.0)):
        raise ValueError(
            f"Constraint '{constraint.constraint_id}' has metadata outside [0, 1]."
        )
    if np.all(np.isclose(values, 1.0)):
        return 2.0
    return float(values.mean())


def compute_importance_weight(constraint: Constraint) -> float:
    """Compute the static importance weight used by the fuzzy trace score.

    Unlike `compute_w_max`, this stays in [0, 1] and is the weight used by the
    weighted-average trace score.
    """

    if not constraint.metadata_scores:
        raise ValueError(f"Constraint '{constraint.constraint_id}' has no metadata scores.")

    values = np.asarray(list(constraint.metadata_scores.values()), dtype=float)
    if np.any((values < 0.0) | (values > 1.0)):
        raise ValueError(
            f"Constraint '{constraint.constraint_id}' has metadata outside [0, 1]."
        )
    return float(values.mean())


def trap(x: float, a: float, b: float, c: float, d: float) -> float:
    """Evaluate a trapezoidal membership function.

    The implementation supports degenerate shoulders such as the common
    `trap(x, 0, 0, c, d)` form used for fuzzy severity on deviations.
    """

    x = float(x)
    a = float(a)
    b = float(b)
    c = float(c)
    d = float(d)

    if d < c:
        raise ValueError("trap requires d >= c.")
    if b < a:
        raise ValueError("trap requires b >= a.")

    # Degenerate left shoulder: full membership starts immediately at `a`.
    if a == b:
        if x <= a:
            return 1.0 if x == a else 0.0
        left = 1.0
    else:
        if x <= a:
            return 0.0
        if x < b:
            return float((x - a) / (b - a))
        left = 1.0

    if x <= c:
        return left
    if x < d:
        if d == c:
            return 0.0
        return float((d - x) / (d - c))
    return 0.0


def _normalise_template_name(template_type: str) -> str:
    normalized = template_type.strip().upper().replace(" ", "_").replace("-", "_")
    aliases = {
        "MP_EXISTENCE": "EXISTENCE",
        "MP_RESPONSE": "RESPONSE",
        "MP_PRECEDENCE": "PRECEDENCE",
        "MP_SUCCESSION": "SUCCESSION",
        "TIMED_RESPONSE": "RESPONSE",
        "TIMED_PRECEDENCE": "PRECEDENCE",
        "TIMED_SUCCESSION": "SUCCESSION",
    }
    return aliases.get(normalized, normalized)


def _is_unary_template(template_type: str) -> bool:
    normalized = _normalise_template_name(template_type)
    return any(template.name == normalized for template in UNARY_TEMPLATES)


def _is_negative_template(template_type: str) -> bool:
    normalized = _normalise_template_name(template_type)
    return any(template.name == normalized for template in NEGATIVE_TEMPLATES)


def _default_rate_thresholds(template_type: str) -> tuple[float, float]:
    if _is_negative_template(template_type):
        return 0.0, 0.10
    return 0.05, 0.20


def _satisfaction_from_violation_rate(
    violation_rate: float,
    template_type: str,
    *,
    r_acc: float | None = None,
    r_unacc: float | None = None,
) -> float:
    acc_default, unacc_default = _default_rate_thresholds(template_type)
    acc = acc_default if r_acc is None else float(r_acc)
    unacc = unacc_default if r_unacc is None else float(r_unacc)
    if unacc < acc:
        raise ValueError(
            f"r_unacc must be greater than or equal to r_acc for template '{template_type}'."
        )
    return trap(float(violation_rate), 0.0, 0.0, acc, unacc)


def _satisfaction_from_count_deviation(
    deviation: float,
    *,
    delta_acc: float | None = None,
    delta_unacc: float | None = None,
) -> float:
    acc = 0.0 if delta_acc is None else float(delta_acc)
    unacc = 0.0 if delta_unacc is None else float(delta_unacc)
    if unacc < acc:
        raise ValueError("delta_unacc must be greater than or equal to delta_acc.")
    return trap(float(deviation), 0.0, 0.0, acc, unacc)


def compute_threshold_severity(x: float, theta: float, theta_crit: float) -> float:
    """Compute fuzzy severity mu(v) for threshold violations with formula (3.2)."""

    if theta_crit <= theta:
        raise ValueError("theta_crit must be strictly greater than theta.")
    if x <= theta:
        return 0.0
    if x > theta_crit:
        return 1.0
    return float((x - theta) / (theta_crit - theta))


def compute_violation_severity(
    violation: ViolationInstance,
    constraint: Constraint,
) -> float:
    """Compute mu(v) in [0,1] for one violation instance.

    Implements formula (3.2):
    - control-flow violations: mu(v) = 1
    - threshold violations: piecewise-linear severity using x, theta, theta_crit
    """

    if violation.violation_type.lower() in {"control-flow", "control_flow", "controlflow"}:
        return 1.0

    if violation.x is None:
        raise ValueError(
            f"Violation for constraint '{violation.constraint_id}' requires observed value x."
        )
    if constraint.theta is None or constraint.theta_crit is None:
        raise ValueError(
            f"Constraint '{constraint.constraint_id}' requires theta and theta_crit for threshold severity."
        )

    return compute_threshold_severity(
        x=float(violation.x),
        theta=float(constraint.theta),
        theta_crit=float(constraint.theta_crit),
    )


def compute_violation_weight(violation: ViolationInstance, constraint: Constraint) -> float:
    """Compute effective violation weight w(v) with formula (3.3)."""

    w_max = compute_w_max(constraint)
    mu = compute_violation_severity(violation=violation, constraint=constraint)
    return float((w_max**2) * mu)


@dataclass(frozen=True)
class TraceScore:
    """Weighted fuzzy score for one trace."""

    case_id: str
    score: float
    total_weight: float
    weighted_sum: float
    constraint_degrees: dict[str, float] = field(default_factory=dict)


def compute_constraint_satisfaction_degree(
    constraint: Constraint,
    result: ConstraintResult,
) -> float | None:
    """Compute the fuzzy satisfaction degree for one constraint result.

    The current implementation uses trace-level counts for relational templates
    and crisp count handling for unary templates. This is the direct bridge
    between the checker output and the weighted-average trace score.
    """

    if result.outcome == ConformanceOutcome.NOT_EVALUATED:
        return None

    normalized = _normalise_template_name(constraint.template_type)
    num_activations = int(result.num_activations)
    num_violated = int(result.num_violated)

    if normalized == "ABSENCE":
        return 1.0 if num_activations == 0 else 0.0

    if normalized == "EXISTENCE":
        return 1.0 if num_activations > 0 else 0.0

    if normalized == "INIT":
        return 1.0 if result.outcome == ConformanceOutcome.SATISFIED else 0.0

    if normalized == "AT_MOST_ONE":
        if constraint.count_target is None:
            return 1.0 if result.outcome == ConformanceOutcome.SATISFIED else 0.0
        deviation = abs(float(num_activations) - float(constraint.count_target))
        return _satisfaction_from_count_deviation(
            deviation,
            delta_acc=constraint.delta_acc,
            delta_unacc=constraint.delta_unacc,
        )

    if num_activations <= 0:
        return 1.0

    violation_rate = float(num_violated) / float(num_activations)
    return _satisfaction_from_violation_rate(
        violation_rate,
        constraint.template_type,
        r_acc=constraint.r_acc,
        r_unacc=constraint.r_unacc,
    )


def score_trace_result(
    trace_result: TraceResult,
    constraints: Iterable[Constraint],
    constraint_id_lookup: dict[str, str] | None = None,
) -> TraceScore:
    """Score one trace using the importance-qualified weighted average."""

    constraints_by_id = {c.constraint_id: c for c in constraints}
    lookup = constraint_id_lookup or {}

    weighted_sum = 0.0
    total_weight = 0.0
    degrees: dict[str, float] = {}

    for result in trace_result.constraint_results:
        canonical_id = lookup.get(result.constraint_id, result.constraint_id)
        constraint = constraints_by_id.get(canonical_id)
        if constraint is None:
            continue

        degree = compute_constraint_satisfaction_degree(constraint, result)
        if degree is None:
            continue

        weight = compute_importance_weight(constraint)
        if weight <= 0.0:
            continue

        degrees[canonical_id] = float(degree)
        weighted_sum += weight * float(degree)
        total_weight += weight

    score = float(weighted_sum / total_weight) if total_weight > 0 else float("nan")
    return TraceScore(
        case_id=str(trace_result.case_id),
        score=score,
        total_weight=float(total_weight),
        weighted_sum=float(weighted_sum),
        constraint_degrees=degrees,
    )


def sugeno_kpi(trace_scores: Iterable[float]) -> float:
    """Aggregate trace scores into a population KPI using the Sugeno integral."""

    values = [float(score) for score in trace_scores if score is not None and not pd.isna(score)]
    if not values:
        return float("nan")

    values.sort(reverse=True)
    count = len(values)
    return float(max(min(values[index], float(index + 1) / float(count)) for index in range(count)))


def score_trace_collection(
    trace_results: Iterable[TraceResult],
    constraints: Iterable[Constraint],
    constraint_id_lookup: dict[str, str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Score all traces and return trace, detail, and KPI frames."""

    constraints_list = list(constraints)
    constraints_by_id = {c.constraint_id: c for c in constraints_list}

    trace_scores: list[dict[str, object]] = []
    detail_rows: list[dict[str, object]] = []

    for trace_result in trace_results:
        trace_score = score_trace_result(
            trace_result=trace_result,
            constraints=constraints_list,
            constraint_id_lookup=constraint_id_lookup,
        )
        trace_scores.append(
            {
                "case_id": trace_score.case_id,
                "score": trace_score.score,
                "weighted_sum": trace_score.weighted_sum,
                "total_weight": trace_score.total_weight,
                "num_scored_constraints": len(trace_score.constraint_degrees),
            }
        )
        for constraint_id, degree in trace_score.constraint_degrees.items():
            constraint = constraints_by_id.get(constraint_id)
            if constraint is None:
                continue
            weight = compute_importance_weight(constraint)
            detail_rows.append(
                {
                    "case_id": trace_score.case_id,
                    "constraint_id": constraint_id,
                    "satisfaction_degree": degree,
                    "weight": weight,
                    "weighted_contribution": degree * weight,
                }
            )

    scores_df = pd.DataFrame(trace_scores)
    detail_df = pd.DataFrame(detail_rows)
    kpi = sugeno_kpi(scores_df["score"].tolist()) if not scores_df.empty else float("nan")
    return scores_df, detail_df, kpi


def constraints_to_frame(constraints: Iterable[Constraint]) -> pd.DataFrame:
    """Convert constraints into a DataFrame with precomputed w_max and w_max^2."""

    rows: list[dict[str, object]] = []
    for c in constraints:
        w_max = compute_w_max(c)
        rows.append(
            {
                "constraint_id": c.constraint_id,
                "template_type": c.template_type,
                "theta": c.theta,
                "theta_crit": c.theta_crit,
                "w_max": w_max,
                "w_max_sq": w_max**2,
            }
        )
    out = pd.DataFrame(rows)
    if out["constraint_id"].duplicated().any():
        raise ValueError("Constraint IDs must be unique.")
    return out


def violations_to_frame(violations: Iterable[ViolationInstance]) -> pd.DataFrame:
    """Convert violation instances into a DataFrame."""

    return pd.DataFrame(
        [
            {
                "case_id": v.case_id,
                "constraint_id": v.constraint_id,
                "violation_type": v.violation_type,
                "x": v.x,
                "timestamp": v.timestamp,
            }
            for v in violations
        ]
    )


def compute_trace_scores(
    constraints: Iterable[Constraint] | pd.DataFrame,
    violations: Iterable[ViolationInstance] | pd.DataFrame,
    applicable_constraints: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute per-trace conformance score using formulas (3.1) to (3.5).

    Args:
        constraints: Constraint definitions or equivalent DataFrame.
        violations: Violation instances or equivalent DataFrame.
        applicable_constraints: DataFrame with columns `case_id`,
            `constraint_id` for the set C_t of applicable constraints per trace.
            This encodes the open-world assumption.

    Returns:
        Tuple of:
            - trace_scores: per-trace score and denominator/numerator terms.
            - constraint_penalties: per-trace, per-constraint penalties W_t(c).
    """

    c_df = (
        constraints_to_frame(constraints)
        if not isinstance(constraints, pd.DataFrame)
        else constraints.copy()
    )
    required_c = {"constraint_id", "w_max_sq"}
    if not required_c.issubset(c_df.columns):
        raise ValueError(f"constraints must include columns: {sorted(required_c)}")

    if not isinstance(violations, pd.DataFrame):
        v_df = violations_to_frame(violations)
    else:
        v_df = violations.copy()

    required_a = {"case_id", "constraint_id"}
    if not required_a.issubset(applicable_constraints.columns):
        raise ValueError("applicable_constraints must include case_id and constraint_id.")
    a_df = applicable_constraints[list(required_a)].drop_duplicates().copy()

    # Aggregate instance-level penalties then cap with formula (3.4).
    if v_df.empty:
        vt = pd.DataFrame(columns=["case_id", "constraint_id", "sum_w", "W_t_c"])
    else:
        required_v = {"case_id", "constraint_id", "violation_type"}
        if not required_v.issubset(v_df.columns):
            raise ValueError(f"violations must include columns: {sorted(required_v)}")

        merged = v_df.merge(c_df, on="constraint_id", how="left", validate="many_to_one")
        if merged["w_max_sq"].isna().any():
            missing = sorted(merged.loc[merged["w_max_sq"].isna(), "constraint_id"].unique())
            raise ValueError(f"Violations reference unknown constraints: {missing}")

        vtype = merged["violation_type"].astype(str).str.lower()
        is_control = vtype.isin({"control-flow", "control_flow", "controlflow"})

        mu = np.ones(len(merged), dtype=float)
        threshold_idx = ~is_control
        if threshold_idx.any():
            theta = merged.loc[threshold_idx, "theta"].astype(float)
            theta_crit = merged.loc[threshold_idx, "theta_crit"].astype(float)
            x = merged.loc[threshold_idx, "x"].astype(float)

            if ((theta_crit - theta) <= 0).any():
                bad_ids = sorted(merged.loc[threshold_idx & ((merged["theta_crit"] - merged["theta"]) <= 0), "constraint_id"].unique())
                raise ValueError(f"theta_crit must be greater than theta for constraints: {bad_ids}")

            mu_threshold = np.where(
                x <= theta,
                0.0,
                np.where(x > theta_crit, 1.0, (x - theta) / (theta_crit - theta)),
            )
            mu_threshold = np.clip(mu_threshold, 0.0, 1.0)
            mu[threshold_idx.to_numpy()] = mu_threshold

        merged["mu"] = mu
        merged["w_v"] = merged["w_max_sq"] * merged["mu"]

        vt = (
            merged.groupby(["case_id", "constraint_id"], as_index=False)["w_v"]
            .sum()
            .rename(columns={"w_v": "sum_w"})
            .merge(c_df[["constraint_id", "w_max_sq"]], on="constraint_id", how="left")
        )
        vt["W_t_c"] = np.minimum(vt["w_max_sq"], vt["sum_w"])
        vt = vt[["case_id", "constraint_id", "sum_w", "W_t_c"]]

    # Open-world: only constraints in C_t contribute to denominator and penalty.
    detail = a_df.merge(c_df[["constraint_id", "w_max_sq"]], on="constraint_id", how="left")
    if detail["w_max_sq"].isna().any():
        missing = sorted(detail.loc[detail["w_max_sq"].isna(), "constraint_id"].unique())
        raise ValueError(f"Applicable set references unknown constraints: {missing}")

    detail = detail.merge(vt[["case_id", "constraint_id", "W_t_c"]], on=["case_id", "constraint_id"], how="left")
    detail["W_t_c"] = detail["W_t_c"].fillna(0.0)

    summary = detail.groupby("case_id", as_index=False).agg(
        total_penalty=("W_t_c", "sum"),
        max_penalty=("w_max_sq", "sum"),
        num_applicable_constraints=("constraint_id", "nunique"),
    )
    summary["score"] = np.where(
        summary["max_penalty"] > 0,
        1.0 - (summary["total_penalty"] / summary["max_penalty"]),
        np.nan,
    )
    summary["score"] = summary["score"].clip(0.0, 1.0)

    return summary[["case_id", "score", "total_penalty", "max_penalty", "num_applicable_constraints"]], detail


__all__ = [
    "Constraint",
    "TraceScore",
    "ViolationInstance",
    "compute_w_max",
    "compute_importance_weight",
    "trap",
    "compute_threshold_severity",
    "compute_violation_severity",
    "compute_violation_weight",
    "compute_constraint_satisfaction_degree",
    "score_trace_result",
    "score_trace_collection",
    "sugeno_kpi",
    "load_constraints_with_weights",
    "constraints_to_frame",
    "violations_to_frame",
    "compute_trace_scores",
]
