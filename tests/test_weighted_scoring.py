from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.results import ConformanceOutcome, ConstraintResult, TraceResult
from conformance.weighted_scoring import (
    Constraint,
    ViolationInstance,
    compute_importance_weight,
    compute_threshold_severity,
    compute_trace_scores,
    compute_w_max,
    score_trace_collection,
    sugeno_kpi,
    trap,
)


class WeightedScoringTests(unittest.TestCase):
    def test_w_max_formula_31(self) -> None:
        critical = Constraint(
            constraint_id="c1",
            template_type="RESPONSE",
            metadata_scores={"a": 1.0, "b": 1.0},
        )
        non_critical = Constraint(
            constraint_id="c2",
            template_type="RESPONSE",
            metadata_scores={"a": 1.0, "b": 0.5},
        )

        self.assertEqual(compute_w_max(critical), 2.0)
        self.assertAlmostEqual(compute_w_max(non_critical), 0.75)

    def test_threshold_severity_formula_32(self) -> None:
        self.assertEqual(compute_threshold_severity(x=100.0, theta=105.0, theta_crit=150.0), 0.0)
        self.assertAlmostEqual(
            compute_threshold_severity(x=127.5, theta=105.0, theta_crit=150.0),
            0.5,
        )
        self.assertEqual(compute_threshold_severity(x=151.0, theta=105.0, theta_crit=150.0), 1.0)

    def test_trace_score_formula_35_with_open_world(self) -> None:
        constraints = [
            Constraint(
                constraint_id="c_threshold",
                template_type="THRESHOLD",
                metadata_scores={"a": 1.0, "b": 0.5},
                theta=10.0,
                theta_crit=20.0,
            ),
            Constraint(
                constraint_id="c_control",
                template_type="RESPONSE",
                metadata_scores={"a": 0.5, "b": 0.5},
            ),
        ]

        violations = [
            ViolationInstance("t1", "c_threshold", "threshold", x=15.0),
            ViolationInstance("t1", "c_control", "control-flow", x=None),
            ViolationInstance("t1", "c_control", "control-flow", x=None),
            ViolationInstance("t2", "c_threshold", "threshold", x=5.0),
        ]

        applicable = pd.DataFrame(
            [
                {"case_id": "t1", "constraint_id": "c_threshold"},
                {"case_id": "t1", "constraint_id": "c_control"},
                {"case_id": "t2", "constraint_id": "c_control"},
            ]
        )

        scores, detail = compute_trace_scores(
            constraints=constraints,
            violations=violations,
            applicable_constraints=applicable,
        )

        t1 = scores[scores["case_id"] == "t1"].iloc[0]
        t2 = scores[scores["case_id"] == "t2"].iloc[0]

        # Legacy weighted scoring still works as before.
        self.assertTrue(math.isclose(float(t1["score"]), 0.34615384615384615, rel_tol=1e-9))
        self.assertEqual(float(t2["score"]), 1.0)

        t1_control = detail[(detail["case_id"] == "t1") & (detail["constraint_id"] == "c_control")].iloc[0]
        self.assertEqual(float(t1_control["W_t_c"]), 0.25)

    def test_fuzzy_trace_scoring_and_kpi(self) -> None:
        constraints = [
            Constraint(
                constraint_id="c1",
                template_type="RESPONSE",
                metadata_scores={"a": 1.0, "b": 1.0},
            ),
            Constraint(
                constraint_id="c2",
                template_type="NOT_CO_EXISTENCE",
                metadata_scores={"a": 0.5, "b": 0.5},
            ),
        ]

        trace_results = [
            TraceResult(
                case_id="t1",
                constraint_results=[
                    ConstraintResult("t1", "c1", ConformanceOutcome.SATISFIED, num_activations=4, num_fulfilled=4, num_violated=0),
                    ConstraintResult("t1", "c2", ConformanceOutcome.VIOLATED, num_activations=4, num_fulfilled=3, num_violated=1),
                ],
            ),
            TraceResult(
                case_id="t2",
                constraint_results=[
                    ConstraintResult("t2", "c1", ConformanceOutcome.SATISFIED, num_activations=2, num_fulfilled=2, num_violated=0),
                    ConstraintResult("t2", "c2", ConformanceOutcome.SATISFIED, num_activations=0, num_fulfilled=0, num_violated=0),
                ],
            ),
        ]

        scores_df, detail_df, kpi = score_trace_collection(trace_results, constraints)

        score_t1 = scores_df[scores_df["case_id"] == "t1"].iloc[0]
        score_t2 = scores_df[scores_df["case_id"] == "t2"].iloc[0]

        # c1 weight = 1.0, c2 weight = 0.5.
        # c1 degree = 1.0, c2 violation rate = 0.25 => trap(...)=0.0 with default negative thresholds.
        self.assertAlmostEqual(float(score_t1["score"]), 2.0 / 3.0, places=9)
        self.assertEqual(float(score_t2["score"]), 1.0)
        self.assertTrue(math.isclose(float(kpi), 2.0 / 3.0, rel_tol=1e-9))

        c1_detail = detail_df[(detail_df["case_id"] == "t1") & (detail_df["constraint_id"] == "c1")].iloc[0]
        self.assertEqual(float(c1_detail["weight"]), 1.0)
        self.assertEqual(float(c1_detail["satisfaction_degree"]), 1.0)
        self.assertEqual(float(c1_detail["weighted_contribution"]), 1.0)

    def test_trap_and_importance_weight(self) -> None:
        self.assertEqual(trap(0.0, 0.0, 0.0, 0.2, 0.5), 1.0)
        self.assertAlmostEqual(trap(0.35, 0.0, 0.0, 0.2, 0.5), 0.5)
        self.assertEqual(compute_importance_weight(Constraint("w", "RESPONSE", {"a": 1.0, "b": 0.0})), 0.5)


if __name__ == "__main__":
    unittest.main()
