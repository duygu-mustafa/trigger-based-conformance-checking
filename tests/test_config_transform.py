from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


# Ensure direct execution can import project modules.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from derive import raw_to_event_log
from derive.activity_emitter import emit_activities


class ConfigTransformTests(unittest.TestCase):
    def test_emit_activities_uses_mapping_and_dictionary(self) -> None:
        raw_df = pd.DataFrame(
            [
                {
                    "source_table": "chartevents",
                    "stay_id": 101,
                    "event_time": "2131-01-11 10:00:00",
                    "itemid": 224715,
                    "value_text": "Yes",
                    "value_num": None,
                    "value_uom": None,
                    "label": "SBT Started",
                },
                {
                    "source_table": "chartevents",
                    "stay_id": 101,
                    "event_time": "2131-01-11 10:05:00",
                    "itemid": 220277,
                    "value_text": "97",
                    "value_num": 97,
                    "value_uom": "%",
                    "label": "O2 saturation pulseoxymetry",
                },
                {
                    "source_table": "procedureevents",
                    "stay_id": 101,
                    "event_time": "2131-01-11 10:10:00",
                    "starttime": "2131-01-11 09:00:00",
                    "endtime": "2131-01-11 12:00:00",
                    "itemid": 225792,
                    "value_text": "180",
                    "value_num": 180,
                    "value_uom": "min",
                    "label": "Invasive Ventilation",
                },
            ]
        )

        activity_df = emit_activities(raw_df)
        activities = set(activity_df["activity"].astype(str).tolist())

        # Config-mapped modeled activities.
        self.assertIn("SBTStarted", activities)
        self.assertIn("InvasiveVentilationStarted", activities)
        self.assertIn("InvasiveVentilationEnded", activities)

        # Dictionary-backed measurement labels remain available for data guards.
        self.assertIn("SpO2", activities)

    def test_raw_to_event_log_returns_canonical_columns(self) -> None:
        raw_df = pd.DataFrame(
            [
                {
                    "source_table": "chartevents",
                    "stay_id": 202,
                    "event_time": "2131-01-11 11:00:00",
                    "itemid": 224715,
                    "value_text": "Yes",
                    "value_num": None,
                    "value_uom": None,
                }
            ]
        )

        event_log = raw_to_event_log(raw_df)

        expected_columns = [
            "case_id",
            "activity",
            "timestamp",
            "source_table",
            "itemid",
            "value_raw",
            "value_num",
            "unit",
            "attrs",
            "patient_id",
            "stay_id",
        ]
        self.assertEqual(expected_columns, list(event_log.columns))
        self.assertFalse(event_log.empty)
        self.assertEqual("202", str(event_log.iloc[0]["case_id"]))


if __name__ == "__main__":
    unittest.main()
