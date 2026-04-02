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


@dataclass(frozen=True)
class Constraint:
    """Declarative constraint metadata used for weighted scoring.

    Implements inputs needed for formulas (3.1) to (3.5).
    """

    constraint_id: str
    template_type: str
    metadata_scores: dict[str, float] = field(default_factory=dict)
    theta: float | None = None
    theta_crit: float | None = None


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
        raise ValueError("Model YAML must contain a top-level 'model' mapping.")

    raw_constraints = model_block.get("constraints")
    if not isinstance(raw_constraints, list):
        raise ValueError("Model YAML must contain model.constraints as a list.")

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

        out.append(
            Constraint(
                constraint_id=str(constraint_id),
                template_type=str(template_type),
                metadata_scores={str(k): float(v) for k, v in metadata_scores.items()},
                theta=float(theta) if theta is not None else None,
                theta_crit=float(theta_crit) if theta_crit is not None else None,
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
    "ViolationInstance",
    "compute_w_max",
    "compute_threshold_severity",
    "compute_violation_severity",
    "compute_violation_weight",
    "load_constraints_with_weights",
    "constraints_to_frame",
    "violations_to_frame",
    "compute_trace_scores",
]
