"""Target selection (method.tex, Def. "Target selection").

Checks the modes any / earliest / latest on the checker (conformance.checker).
Each case states the verdict the definition prescribes. The same cases are run
against the experimental automata engine in experimental/test_automata_target_selection.py.
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.checker import _evaluate_constraint_impl
from conformance.results import ConformanceOutcome
from conformance.types import (
    DataCondition,
    DeclareConstraint,
    DeclareTemplate,
    TimeCondition,
    normalize_target_selection,
)

SAT = ConformanceOutcome.SATISFIED
VIO = ConformanceOutcome.VIOLATED
BASE = pd.Timestamp("2024-01-01")


def trace(events):
    """events: (activity, minute_offset[, attrs]) in trace order; ties keep list order."""
    rows = []
    for ev in events:
        row = {"case_id": "c1", "activity": ev[0], "timestamp": BASE + pd.Timedelta(minutes=ev[1])}
        row.update(ev[2] if len(ev) > 2 else {})
        rows.append(row)
    return pd.DataFrame(rows).sort_values("timestamp", kind="stable").reset_index(drop=True)


def con(template, activation, target, selection, *, cond=None, window=None):
    return DeclareConstraint(
        template=template,
        activation=activation,
        target=target,
        correlation_cond=DataCondition(cond) if cond else None,
        time_condition=TimeCondition(min_seconds=window[0] * 60, max_seconds=window[1] * 60)
        if window
        else None,
        target_selection=selection,
    )


def run_checker(df, c):
    return _evaluate_constraint_impl("c1", df, c)


class TargetSelectionTest(unittest.TestCase):
    engines = {"checker": run_checker}

    def assertVerdicts(self, events, template, activation, target, expected, **kw):
        """expected: {mode: (outcome, num_fulfilled, num_violated)}"""
        df = trace(events)
        for mode, (outcome, n_ful, n_vio) in expected.items():
            c = con(template, activation, target, mode, **kw)
            for name, run in self.engines.items():
                with self.subTest(mode=mode, engine=name):
                    r = run(df, c)
                    self.assertEqual(r.outcome, outcome)
                    self.assertEqual((r.num_fulfilled, r.num_violated), (n_ful, n_vio))

    def test_method_example_response(self):
        # Ex. ex:method_final_value: Response(G, T), window [0, 5), psi = temp < 300.
        # Activation e2 sees <260, 310>; activation e6 sees <250>.
        events = [
            ("T", 0, {"temp": 240}),
            ("G", 1),
            ("T", 2, {"temp": 260}),
            ("T", 4, {"temp": 310}),
            ("G", 10),
            ("T", 11, {"temp": 250}),
        ]
        self.assertVerdicts(
            events, DeclareTemplate.RESPONSE, "G", "T",
            {"any": (SAT, 2, 0), "earliest": (SAT, 2, 0), "latest": (VIO, 1, 1)},
            cond="items['temp'] < 300", window=(0, 4.99),
        )

    def test_precedence_mirror(self):
        # Past-directed: latest = nearest before the activation, earliest = farthest.
        events = [("A", 0, {"v": 100}), ("A", 1, {"v": 10}), ("B", 2)]
        self.assertVerdicts(
            events, DeclareTemplate.PRECEDENCE, "B", "A",
            {"any": (SAT, 1, 0), "earliest": (SAT, 1, 0), "latest": (VIO, 0, 1)},
            cond="items['v'] > 50",
        )

    def test_window_filters_before_selection(self):
        # Response window [2, 10] min: the candidate at +1 is outside phi_tau, so
        # m_1 is the one at +3 (satisfying), not the one at +1 (failing).
        events = [("A", 0), ("B", 1, {"v": 0}), ("B", 3, {"v": 100}), ("B", 20, {"v": 0})]
        self.assertVerdicts(
            events, DeclareTemplate.RESPONSE, "A", "B",
            {"earliest": (SAT, 1, 0), "latest": (SAT, 1, 0)},
            cond="items['v'] > 50", window=(2, 10),
        )

    def test_precedence_window_filters_before_selection(self):
        # Precedence window [-10, -2] min: the candidate 1 min before B is outside
        # phi_tau, so latest selects the one 5 min before B.
        events = [("A", 0, {"v": 100}), ("A", 4, {"v": 0}), ("B", 5)]
        self.assertVerdicts(
            events, DeclareTemplate.PRECEDENCE, "B", "A",
            {"latest": (SAT, 1, 0), "earliest": (SAT, 1, 0)},
            cond="items['v'] > 50", window=(-10, -2),
        )

    def test_tie_resolved_by_trace_order(self):
        # Two candidates share a timestamp; trace order decides m_1 and m_k.
        events = [("A", 0), ("B", 1, {"v": 100}), ("B", 1, {"v": 0})]
        self.assertVerdicts(
            events, DeclareTemplate.RESPONSE, "A", "B",
            {"earliest": (SAT, 1, 0), "latest": (VIO, 0, 1)},
            cond="items['v'] > 50",
        )

    def test_same_timestamp_target_is_no_candidate(self):
        events = [("B", 0, {"v": 0}), ("A", 5), ("B", 5, {"v": 100})]
        self.assertVerdicts(
            events, DeclareTemplate.PRECEDENCE, "A", "B",
            {"latest": (VIO, 0, 1), "earliest": (VIO, 0, 1)},
            cond="items['v'] > 50",
        )

    def test_empty_candidate_sequence_is_violation(self):
        events = [("A", 0), ("B", 30, {"v": 100})]
        self.assertVerdicts(
            events, DeclareTemplate.RESPONSE, "A", "B",
            {"earliest": (VIO, 0, 1), "latest": (VIO, 0, 1)},
            cond="items['v'] > 50", window=(0, 10),
        )

    def test_normalization_and_admission(self):
        self.assertEqual(normalize_target_selection(None, DeclareTemplate.RESPONSE), "any")
        self.assertEqual(normalize_target_selection("last", DeclareTemplate.PRECEDENCE), "latest")
        self.assertEqual(normalize_target_selection("First", DeclareTemplate.RESPONSE), "earliest")
        self.assertEqual(normalize_target_selection("any", DeclareTemplate.CHAIN_RESPONSE), "any")
        for tmpl in (
            DeclareTemplate.CHAIN_RESPONSE,
            DeclareTemplate.ALTERNATE_PRECEDENCE,
            DeclareTemplate.NOT_RESPONSE,
            DeclareTemplate.SUCCESSION,
            DeclareTemplate.RESPONDED_EXISTENCE,
        ):
            with self.subTest(template=tmpl):
                with self.assertRaises(ValueError):
                    normalize_target_selection("latest", tmpl)
        with self.assertRaises(ValueError):
            normalize_target_selection("median", DeclareTemplate.RESPONSE)


if __name__ == "__main__":
    unittest.main()
