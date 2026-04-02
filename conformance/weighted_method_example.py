"""Synthetic example for weighted fuzzy conformance and outcome calibration."""

from __future__ import annotations

import numpy as np
import pandas as pd

from conformance.outcome_postprocessing import (
    compare_guideline_vs_empirical_weights,
    fit_constraint_outcome_logit,
    fit_score_outcome_logit,
)
from conformance.weighted_scoring import (
    Constraint,
    ViolationInstance,
    compute_trace_scores,
    constraints_to_frame,
)


def build_synthetic_inputs() -> tuple[list[Constraint], list[ViolationInstance], pd.DataFrame]:
    """Build small synthetic inputs for formulas (3.1)-(3.5)."""

    constraints = [
        Constraint(
            constraint_id="c_rsbi",
            template_type="THRESHOLD",
            metadata_scores={"clinical_consequence": 1.0, "unnoticed_frequency": 0.8, "must_not": 1.0},
            theta=105.0,
            theta_crit=150.0,
        ),
        Constraint(
            constraint_id="c_response",
            template_type="RESPONSE",
            metadata_scores={"clinical_consequence": 0.7, "unnoticed_frequency": 0.6, "must_not": 0.8},
        ),
        Constraint(
            constraint_id="c_nif",
            template_type="THRESHOLD",
            metadata_scores={"clinical_consequence": 1.0, "unnoticed_frequency": 1.0, "must_not": 1.0},
            theta=-20.0,
            theta_crit=-10.0,
        ),
    ]

    violations = [
        ViolationInstance(case_id="t1", constraint_id="c_rsbi", violation_type="threshold", x=120.0),
        ViolationInstance(case_id="t1", constraint_id="c_response", violation_type="control-flow"),
        ViolationInstance(case_id="t2", constraint_id="c_rsbi", violation_type="threshold", x=151.0),
        ViolationInstance(case_id="t2", constraint_id="c_response", violation_type="control-flow"),
        ViolationInstance(case_id="t2", constraint_id="c_response", violation_type="control-flow"),
        ViolationInstance(case_id="t3", constraint_id="c_rsbi", violation_type="threshold", x=90.0),
    ]

    # Open-world applicability C_t: only listed constraints are considered for each trace.
    applicable_constraints = pd.DataFrame(
        [
            {"case_id": "t1", "constraint_id": "c_rsbi"},
            {"case_id": "t1", "constraint_id": "c_response"},
            {"case_id": "t2", "constraint_id": "c_rsbi"},
            {"case_id": "t2", "constraint_id": "c_response"},
            {"case_id": "t2", "constraint_id": "c_nif"},
            {"case_id": "t3", "constraint_id": "c_rsbi"},
            {"case_id": "t3", "constraint_id": "c_nif"},
        ]
    )

    return constraints, violations, applicable_constraints


def run_example() -> None:
    """Run a compact end-to-end demo with synthetic data."""

    constraints, violations, applicable = build_synthetic_inputs()

    scores, detail = compute_trace_scores(
        constraints=constraints,
        violations=violations,
        applicable_constraints=applicable,
    )
    print("Per-trace score results:")
    print(scores)
    print("\nPer-trace, per-constraint penalties W_t(c):")
    print(detail.sort_values(["case_id", "constraint_id"]).reset_index(drop=True))

    # Synthetic outcomes for optional post-processing.
    score_outcome = scores[["case_id", "score"]].copy()
    score_outcome["y"] = [0, 1, 0]

    # Build x_{t,c} matrix from detail using normalized W_t(c).
    x_matrix = detail.copy()
    x_matrix["x_tc"] = np.where(
        x_matrix["w_max_sq"] > 0,
        x_matrix["W_t_c"] / x_matrix["w_max_sq"],
        0.0,
    )
    wide = (
        x_matrix.pivot(index="case_id", columns="constraint_id", values="x_tc")
        .fillna(0.0)
        .reset_index()
    )
    wide = wide.merge(score_outcome[["case_id", "y"]], on="case_id", how="left")

    try:
        fit_score = fit_score_outcome_logit(score_outcome, score_col="score", outcome_col="y")
        print("\nFormula (3.6) coefficient beta_1:", float(fit_score.coefficients["score"]))
        print("Formula (3.6) p-value for beta_1:", float(fit_score.p_values["score"]))

        _, empirical = fit_constraint_outcome_logit(wide, outcome_col="y", case_id_col="case_id")
        guideline = constraints_to_frame(constraints)[["constraint_id", "w_max"]]
        comparison, summary = compare_guideline_vs_empirical_weights(guideline, empirical)
        print("\nGuideline vs empirical weights:")
        print(comparison)
        print("Summary:", summary)
    except RuntimeError as exc:
        print("\nOutcome post-processing skipped:", exc)


if __name__ == "__main__":
    run_example()
