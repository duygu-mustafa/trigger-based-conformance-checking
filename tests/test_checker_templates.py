from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd


# Ensure direct execution (python tests/test_checker_templates.py) can import project modules.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.checker import (
    evaluate_absence_rule,
    evaluate_alternate_precedence_rule,
    evaluate_alternate_response_rule,
    evaluate_alternate_succession_rule,
    evaluate_chain_precedence_rule,
    evaluate_chain_response_rule,
    evaluate_chain_succession_rule,
    evaluate_co_existence_rule,
    evaluate_constraint,
    evaluate_exactly_rule,
    evaluate_existence_rule,
    evaluate_init_rule,
    evaluate_not_chain_precedence_rule,
    evaluate_not_chain_response_rule,
    evaluate_not_co_existence_rule,
    evaluate_not_precedence_rule,
    evaluate_not_responded_existence_rule,
    evaluate_not_response_rule,
    evaluate_not_succession_rule,
    evaluate_precedence_rule,
    evaluate_responded_existence_rule,
    evaluate_response_rule,
    evaluate_succession_rule,
)
from conformance.results import ConformanceOutcome
from conformance.types import DeclareConstraint, DeclareTemplate, TimeCondition


def _trace(events: list[tuple[str, str]]) -> pd.DataFrame:
    rows = []
    for idx, (ts, activity) in enumerate(events):
        rows.append(
            {
                "case_id": "c1",
                "activity": activity,
                "timestamp": pd.Timestamp(ts),
                "itemid": None,
                "value_num": None,
                "value_raw": None,
                "event_idx": idx,
            }
        )
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


class TemplateEvaluatorTests(unittest.TestCase):
    def test_each_template_specific_function_satisfied_path(self) -> None:
        cases = [
            (DeclareTemplate.EXISTENCE, evaluate_existence_rule, [("2026-01-01 00:00:00", "A")]),
            (DeclareTemplate.ABSENCE, evaluate_absence_rule, [("2026-01-01 00:00:00", "B")]),
            (DeclareTemplate.EXACTLY, evaluate_exactly_rule, [("2026-01-01 00:00:00", "A")]),
            (DeclareTemplate.INIT, evaluate_init_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.RESPONDED_EXISTENCE, evaluate_responded_existence_rule, [("2026-01-01 00:00:00", "B"), ("2026-01-01 00:01:00", "A")]),
            (DeclareTemplate.RESPONSE, evaluate_response_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.ALTERNATE_RESPONSE, evaluate_alternate_response_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B"), ("2026-01-01 00:02:00", "A"), ("2026-01-01 00:03:00", "B")]),
            (DeclareTemplate.CHAIN_RESPONSE, evaluate_chain_response_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.PRECEDENCE, evaluate_precedence_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.ALTERNATE_PRECEDENCE, evaluate_alternate_precedence_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B"), ("2026-01-01 00:02:00", "A"), ("2026-01-01 00:03:00", "B")]),
            (DeclareTemplate.CHAIN_PRECEDENCE, evaluate_chain_precedence_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.CO_EXISTENCE, evaluate_co_existence_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.SUCCESSION, evaluate_succession_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.ALTERNATE_SUCCESSION, evaluate_alternate_succession_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B"), ("2026-01-01 00:02:00", "A"), ("2026-01-01 00:03:00", "B")]),
            (DeclareTemplate.CHAIN_SUCCESSION, evaluate_chain_succession_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
            (DeclareTemplate.NOT_RESPONDED_EXISTENCE, evaluate_not_responded_existence_rule, [("2026-01-01 00:00:00", "A")]),
            (DeclareTemplate.NOT_RESPONSE, evaluate_not_response_rule, [("2026-01-01 00:00:00", "A")]),
            (DeclareTemplate.NOT_CHAIN_RESPONSE, evaluate_not_chain_response_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "C"), ("2026-01-01 00:02:00", "B")]),
            (DeclareTemplate.NOT_PRECEDENCE, evaluate_not_precedence_rule, [("2026-01-01 00:00:00", "B")]),
            (DeclareTemplate.NOT_CHAIN_PRECEDENCE, evaluate_not_chain_precedence_rule, [("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "C"), ("2026-01-01 00:02:00", "B")]),
            (DeclareTemplate.NOT_CO_EXISTENCE, evaluate_not_co_existence_rule, [("2026-01-01 00:00:00", "A")]),
            (DeclareTemplate.NOT_SUCCESSION, evaluate_not_succession_rule, [("2026-01-01 00:00:00", "A")]),
        ]

        for template, evaluator, events in cases:
            with self.subTest(template=template.name):
                trace_df = _trace(events)
                if template in {
                    DeclareTemplate.EXISTENCE,
                    DeclareTemplate.ABSENCE,
                    DeclareTemplate.EXACTLY,
                    DeclareTemplate.INIT,
                }:
                    constraint = DeclareConstraint(template=template, activation="A")
                else:
                    constraint = DeclareConstraint(template=template, activation="A", target="B")

                result = evaluator(case_id="c1", trace_df=trace_df, constraint=constraint)
                self.assertEqual(result.outcome, ConformanceOutcome.SATISFIED)

    def test_dispatcher_matches_template_specific_function(self) -> None:
        checks = [
            (DeclareTemplate.RESPONSE, evaluate_response_rule, _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]), DeclareConstraint(template=DeclareTemplate.RESPONSE, activation="A", target="B")),
            (DeclareTemplate.PRECEDENCE, evaluate_precedence_rule, _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]), DeclareConstraint(template=DeclareTemplate.PRECEDENCE, activation="A", target="B")),
            (DeclareTemplate.NOT_CO_EXISTENCE, evaluate_not_co_existence_rule, _trace([("2026-01-01 00:00:00", "A")]), DeclareConstraint(template=DeclareTemplate.NOT_CO_EXISTENCE, activation="A", target="B")),
            (DeclareTemplate.EXACTLY, evaluate_exactly_rule, _trace([("2026-01-01 00:00:00", "A")]), DeclareConstraint(template=DeclareTemplate.EXACTLY, activation="A")),
        ]

        for template, evaluator, trace_df, constraint in checks:
            with self.subTest(template=template.name):
                direct = evaluator(case_id="c1", trace_df=trace_df, constraint=constraint)
                dispatched = evaluate_constraint(case_id="c1", trace_df=trace_df, constraint=constraint)
                self.assertEqual(direct, dispatched)

    def test_template_violation_paths(self) -> None:
        cases = [
            (
                "EXISTENCE",
                evaluate_existence_rule,
                DeclareConstraint(template=DeclareTemplate.EXISTENCE, activation="A"),
                _trace([("2026-01-01 00:00:00", "B")]),
                ConformanceOutcome.VACUOUS,
            ),
            (
                "ABSENCE",
                evaluate_absence_rule,
                DeclareConstraint(template=DeclareTemplate.ABSENCE, activation="A"),
                _trace([("2026-01-01 00:00:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "EXACTLY",
                evaluate_exactly_rule,
                DeclareConstraint(template=DeclareTemplate.EXACTLY, activation="A"),
                _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "INIT",
                evaluate_init_rule,
                DeclareConstraint(template=DeclareTemplate.INIT, activation="A"),
                _trace([("2026-01-01 00:00:00", "B"), ("2026-01-01 00:01:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "RESPONSE",
                evaluate_response_rule,
                DeclareConstraint(template=DeclareTemplate.RESPONSE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "PRECEDENCE",
                evaluate_precedence_rule,
                DeclareConstraint(template=DeclareTemplate.PRECEDENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "B"), ("2026-01-01 00:01:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "CO_EXISTENCE",
                evaluate_co_existence_rule,
                DeclareConstraint(template=DeclareTemplate.CO_EXISTENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "NOT_CO_EXISTENCE",
                evaluate_not_co_existence_rule,
                DeclareConstraint(template=DeclareTemplate.NOT_CO_EXISTENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "NOT_RESPONSE",
                evaluate_not_response_rule,
                DeclareConstraint(template=DeclareTemplate.NOT_RESPONSE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "NOT_PRECEDENCE",
                evaluate_not_precedence_rule,
                DeclareConstraint(template=DeclareTemplate.NOT_PRECEDENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A"), ("2026-01-01 00:01:00", "B")]),
                ConformanceOutcome.VIOLATED,
            ),
            (
                "SUCCESSION",
                evaluate_succession_rule,
                DeclareConstraint(template=DeclareTemplate.SUCCESSION, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A")]),
                ConformanceOutcome.VIOLATED,
            ),
        ]

        for label, evaluator, constraint, trace_df, expected in cases:
            with self.subTest(template=label):
                result = evaluator(case_id="c1", trace_df=trace_df, constraint=constraint)
                self.assertEqual(result.outcome, expected)

    def test_vacuous_paths_for_selected_templates(self) -> None:
        cases = [
            (
                "RESPONSE no activation",
                evaluate_response_rule,
                DeclareConstraint(template=DeclareTemplate.RESPONSE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "B")]),
            ),
            (
                "PRECEDENCE no target",
                evaluate_precedence_rule,
                DeclareConstraint(template=DeclareTemplate.PRECEDENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "A")]),
            ),
            (
                "RESPONDED_EXISTENCE no activation",
                evaluate_responded_existence_rule,
                DeclareConstraint(template=DeclareTemplate.RESPONDED_EXISTENCE, activation="A", target="B"),
                _trace([("2026-01-01 00:00:00", "B")]),
            ),
        ]

        for label, evaluator, constraint, trace_df in cases:
            with self.subTest(path=label):
                result = evaluator(case_id="c1", trace_df=trace_df, constraint=constraint)
                self.assertEqual(result.outcome, ConformanceOutcome.VACUOUS)

    def test_response_time_window_violation(self) -> None:
        constraint = DeclareConstraint(
            template=DeclareTemplate.RESPONSE,
            activation="A",
            target="B",
            time_condition=TimeCondition(max_seconds=30),
        )
        trace_df = _trace(
            [
                ("2026-01-01 00:00:00", "A"),
                ("2026-01-01 00:01:00", "B"),
            ]
        )

        result = evaluate_response_rule(case_id="c1", trace_df=trace_df, constraint=constraint)
        self.assertEqual(result.outcome, ConformanceOutcome.VIOLATED)


if __name__ == "__main__":
    unittest.main()
