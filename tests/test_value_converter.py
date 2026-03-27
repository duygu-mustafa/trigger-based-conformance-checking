"""Tests for categorical value conversion in the derive pipeline."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from derive.value_converter import convert_categorical_values


class ValueConverterTests(unittest.TestCase):
    def test_sas_scale_conversion(self) -> None:
        """Test Riker-SAS Scale (itemid 223753) string-to-numeric conversion."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 223753,
                    "value_text": "Unarousable",
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "Very Sedated",
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "Calm/Cooperative",
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "Very Agitated",
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "Danger Agitation",
                    "value_num": None,
                },
            ]
        )

        result = convert_categorical_values(raw_df)
        expected_values = [1.0, 2.0, 4.0, 6.0, 7.0]
        actual_values = result["value_num"].tolist()

        self.assertEqual(expected_values, actual_values)

    def test_breathing_pattern_conversion(self) -> None:
        """Test Breathing pattern/effort (itemid 229322) conversion."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 229322,
                    "value_text": "Regular",
                    "value_num": None,
                },
                {
                    "itemid": 229322,
                    "value_text": "Shallow",
                    "value_num": None,
                },
                {
                    "itemid": 229322,
                    "value_text": "Accessory muscle use/retractions",
                    "value_num": None,
                },
                {
                    "itemid": 229322,
                    "value_text": "Gasping efforts",
                    "value_num": None,
                },
            ]
        )

        result = convert_categorical_values(raw_df)
        expected_values = [0.0, 1.0, 2.0, 3.0]
        actual_values = result["value_num"].tolist()

        self.assertEqual(expected_values, actual_values)

    def test_respiratory_effort_conversion(self) -> None:
        """Test Respiratory Effort (itemid 223990) conversion."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 223990,
                    "value_text": "Normal",
                    "value_num": None,
                },
                {
                    "itemid": 223990,
                    "value_text": "Labored",
                    "value_num": None,
                },
                {
                    "itemid": 223990,
                    "value_text": "Apneic",
                    "value_num": None,
                },
            ]
        )

        result = convert_categorical_values(raw_df)
        expected_values = [0.0, 2.0, 3.0]
        actual_values = result["value_num"].tolist()

        self.assertEqual(expected_values, actual_values)

    def test_case_insensitivity(self) -> None:
        """Test that conversion is case-insensitive."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 223753,
                    "value_text": "unarousable",  # lowercase
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "VERY SEDATED",  # uppercase
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "CaLm/CoOpErAtIvE",  # mixed case
                    "value_num": None,
                },
            ]
        )

        result = convert_categorical_values(raw_df)
        expected_values = [1.0, 2.0, 4.0]
        actual_values = result["value_num"].tolist()

        self.assertEqual(expected_values, actual_values)

    def test_unmapped_values_preserved(self) -> None:
        """Test that unmapped items and values are left unchanged."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 220210,  # Not in mappings
                    "value_text": "Some unknown value",
                    "value_num": None,
                },
                {
                    "itemid": 223753,
                    "value_text": "Unknown sedation level",
                    "value_num": 99.0,  # Falls back to existing numeric
                },
            ]
        )

        result = convert_categorical_values(raw_df)
        # First row: 220210 not in mappings, no value_num to keep, should be NaN
        # Second row: not found in mapping, should use existing value_num (99.0)
        self.assertTrue(pd.isna(result.iloc[0]["value_num"]))
        self.assertEqual(99.0, result.iloc[1]["value_num"])

    def test_mixed_itemids(self) -> None:
        """Test conversion in a mixed DataFrame with multiple itemids."""
        raw_df = pd.DataFrame(
            [
                {
                    "itemid": 223753,
                    "value_text": "Calm/Cooperative",
                    "value_num": None,
                },
                {
                    "itemid": 220045,  # HR, not categorical
                    "value_text": "80",
                    "value_num": 80.0,
                },
                {
                    "itemid": 229322,
                    "value_text": "Regular",
                    "value_num": None,
                },
            ]
        )

        result = convert_categorical_values(raw_df)

        self.assertEqual(4.0, result.iloc[0]["value_num"])
        self.assertEqual(80.0, result.iloc[1]["value_num"])
        self.assertEqual(0.0, result.iloc[2]["value_num"])


if __name__ == "__main__":
    unittest.main()
