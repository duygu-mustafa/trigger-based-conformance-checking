from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.outcome_postprocessing import (
    build_model_level_regression_frame,
    build_score_outcome_frame,
)


class OutcomePostprocessingTests(unittest.TestCase):
    def test_build_score_outcome_frame_adds_binary_label(self) -> None:
        score_df = pd.DataFrame(
            [
                {"case_id": "1", "score": 0.25},
                {"case_id": "2", "score": 0.75},
            ]
        )
        reintubation_df = pd.DataFrame(
            [
                {"case_id": "1", "intubation_after_sbt": True},
                {"case_id": "2", "intubation_after_sbt": False},
            ]
        )

        out = build_score_outcome_frame(score_df, reintubation_df)
        self.assertEqual([1, 0], out["y"].tolist())
        self.assertEqual([True, False], out["intubation_after_sbt"].tolist())

    def test_build_model_level_regression_frame_pivots_model_scores(self) -> None:
        tracking_df = pd.DataFrame(
            [
                {
                    "stay_id": 100,
                    "case_id": "100",
                    "model_name": "readiness_assessment",
                    "score": 0.4,
                },
                {
                    "stay_id": 100,
                    "case_id": "100",
                    "model_name": "sbt_execution",
                    "score": 0.8,
                },
            ]
        )
        outcome_df = pd.DataFrame(
            [
                {
                    "stay_id": 100,
                    "case_id": "100",
                    "intubation_after_sbt": True,
                    "hours_from_sbt_to_intubation": 4.5,
                }
            ]
        )

        out = build_model_level_regression_frame(tracking_df, outcome_df)
        self.assertEqual(1, len(out))
        self.assertAlmostEqual(0.4, float(out.iloc[0]["readiness_assessment"]))
        self.assertAlmostEqual(0.8, float(out.iloc[0]["sbt_execution"]))
        self.assertEqual(1, int(out.iloc[0]["y"]))
        self.assertTrue(bool(out.iloc[0]["intubation_after_sbt"]))


if __name__ == "__main__":
    unittest.main()