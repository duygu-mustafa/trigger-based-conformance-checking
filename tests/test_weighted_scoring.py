from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.weighted_scoring import (
    Constraint,
    ViolationInstance,
    compute_threshold_severity,
    compute_trace_scores,
    compute_w_max,
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

        # t1: c_threshold severity 0.5 => 0.75^2 * 0.5 = 0.28125
        # c_control has two control-flow violations, but capped at w_max^2 = 0.25
        # denominator = 0.75^2 + 0.25 = 0.8125
        # score = 1 - (0.28125 + 0.25)/0.8125 = 0.346153846...
        self.assertTrue(math.isclose(float(t1["score"]), 0.34615384615384615, rel_tol=1e-9))

        # t2: only c_control is applicable and has no violation => score 1.0
        self.assertEqual(float(t2["score"]), 1.0)

        t1_control = detail[(detail["case_id"] == "t1") & (detail["constraint_id"] == "c_control")].iloc[0]
        self.assertEqual(float(t1_control["W_t_c"]), 0.25)


if __name__ == "__main__":
    unittest.main()
