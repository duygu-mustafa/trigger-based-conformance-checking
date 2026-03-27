from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from derive.reintubation import detect_intubation_after_sbt


class ReintubationDetectionTests(unittest.TestCase):
    def test_detects_intubation_after_sbt(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "1", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
                {"case_id": "1", "activity": "Intubation", "timestamp": "2131-01-11 12:00:00"},
            ]
        )

        out = detect_intubation_after_sbt(event_log)
        self.assertEqual(1, len(out))
        self.assertTrue(bool(out.iloc[0]["intubation_after_sbt"]))
        self.assertAlmostEqual(2.0, float(out.iloc[0]["hours_from_sbt_to_intubation"]), places=5)

    def test_ignores_intubation_before_sbt(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "2", "activity": "Intubation", "timestamp": "2131-01-11 09:00:00"},
                {"case_id": "2", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
            ]
        )

        out = detect_intubation_after_sbt(event_log)
        self.assertEqual(1, len(out))
        self.assertFalse(bool(out.iloc[0]["intubation_after_sbt"]))

    def test_handles_multiple_cases(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "1", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
                {"case_id": "1", "activity": "Intubation", "timestamp": "2131-01-11 11:00:00"},
                {"case_id": "2", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
            ]
        )

        out = detect_intubation_after_sbt(event_log).sort_values("case_id").reset_index(drop=True)
        self.assertEqual(["1", "2"], out["case_id"].tolist())
        self.assertEqual([True, False], out["intubation_after_sbt"].tolist())

    def test_requires_intubation_within_48h(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "3", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
                {"case_id": "3", "activity": "Intubation", "timestamp": "2131-01-13 11:00:00"},
            ]
        )

        out = detect_intubation_after_sbt(event_log)
        self.assertEqual(1, len(out))
        self.assertFalse(bool(out.iloc[0]["intubation_after_sbt"]))
        self.assertTrue(pd.isna(out.iloc[0]["hours_from_sbt_to_intubation"]))

    def test_boundary_48h_is_counted(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "4", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
                {"case_id": "4", "activity": "Intubation", "timestamp": "2131-01-13 10:00:00"},
            ]
        )

        out = detect_intubation_after_sbt(event_log)
        self.assertEqual(1, len(out))
        self.assertTrue(bool(out.iloc[0]["intubation_after_sbt"]))
        self.assertAlmostEqual(48.0, float(out.iloc[0]["hours_from_sbt_to_intubation"]), places=5)

    def test_returns_positive_sbt_events_dataframe(self) -> None:
        event_log = pd.DataFrame(
            [
                {"case_id": "5", "activity": "SBTStarted", "timestamp": "2131-01-11 10:00:00"},
                {"case_id": "5", "activity": "SBTStarted", "timestamp": "2131-01-12 10:00:00"},
                {"case_id": "5", "activity": "Intubation", "timestamp": "2131-01-11 16:00:00"},
                {"case_id": "5", "activity": "Intubation", "timestamp": "2131-01-13 09:00:00"},
            ]
        )

        summary, positives = detect_intubation_after_sbt(
            event_log,
            return_positive_sbt_events=True,
        )

        self.assertEqual(1, len(summary))
        self.assertEqual(2, len(positives))
        self.assertEqual("5", str(positives.iloc[0]["case_id"]))
        self.assertIn("sbt_timestamp", positives.columns)
        self.assertIn("matched_intubation_timestamp", positives.columns)


if __name__ == "__main__":
    unittest.main()
