"""Equivalence test: old switch-case checker vs. new automata-based checker.

Loads the old _evaluate_constraint_impl from git HEAD and runs it against the
current (automata-based) implementation on synthetic traces for all 24
DeclareTemplate values.  Asserts .outcome matches for each case.
"""

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.checker import _evaluate_constraint_impl as new_impl
from conformance.types import DeclareConstraint, DeclareTemplate


def _load_old_checker():
    proc = subprocess.run(
        ["git", "show", "midterm/frontend:conformance/checker.py"],
        capture_output=True, text=True, cwd=PROJECT_ROOT, check=True,
    )
    tmpdir = tempfile.mkdtemp()
    old_path = os.path.join(tmpdir, "old_checker.py")
    Path(old_path).write_text(proc.stdout)
    spec = importlib.util.spec_from_file_location("old_checker", old_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_OLD = _load_old_checker()
old_impl = _OLD._evaluate_constraint_impl


def make_trace(events):
    """events: list of (activity, minutes_offset)"""
    base = pd.Timestamp("2024-01-01")
    rows = []
    for act, m in events:
        rows.append({
            "case_id": "c1",
            "activity": act,
            "timestamp": base + pd.Timedelta(minutes=m),
            "value_raw": None,
            "value_num": None,
            "itemid": None,
            "source_table": None,
            "unit": None,
            "attrs": None,
            "patient_id": None,
            "stay_id": None,
        })
    return pd.DataFrame(rows)


def con(template, activation, target=None):
    return DeclareConstraint(template=template, activation=activation, target=target)


def cmp(case_id, trace_df, constraint, label=""):
    """Assert old and new produce the same outcome."""
    old_res = old_impl(case_id, trace_df, constraint)
    new_res = new_impl(case_id, trace_df, constraint)
    assert old_res.outcome == new_res.outcome, (
        f"{label or constraint.template.value}: "
        f"old={old_res.outcome} new={new_res.outcome}"
    )


def expect(trace_df, constraint, outcome, label=""):
    """Assert the current checker's outcome where it intentionally departs from the old one."""
    res = new_impl("c1", trace_df, constraint)
    assert res.outcome.value == outcome, f"{label}: got {res.outcome}"


class TestAutomataEquivalence(unittest.TestCase):

    def test_existence(self):
        c = con(DeclareTemplate.EXISTENCE, "A")
        cmp("c1", make_trace([("A", 0)]), c, "EXISTENCE satisfied")
        # AtLeastOne is activated by the trace start, so a missing A is a violation.
        expect(make_trace([("B", 0)]), c, "violated", "EXISTENCE violated")

    def test_absence(self):
        c = con(DeclareTemplate.ABSENCE, "A")
        cmp("c1", make_trace([("B", 0)]), c, "ABSENCE satisfied")
        cmp("c1", make_trace([("A", 0)]), c, "ABSENCE violated")

    def test_at_most_one(self):
        c = con(DeclareTemplate.AT_MOST_ONE, "A")
        cmp("c1", make_trace([("A", 0)]), c, "AT_MOST_ONE satisfied")
        cmp("c1", make_trace([("A", 0), ("A", 1)]), c, "AT_MOST_ONE violated")
        cmp("c1", make_trace([("B", 0)]), c, "AT_MOST_ONE vacuous")

    def test_init(self):
        c = con(DeclareTemplate.INIT, "A")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "INIT satisfied")
        cmp("c1", make_trace([("B", 0), ("A", 1)]), c, "INIT violated")

    def test_end(self):
        c = con(DeclareTemplate.END, "A")
        cmp("c1", make_trace([("B", 0), ("A", 1)]), c, "END satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "END violated")

    def test_responded_existence(self):
        c = con(DeclareTemplate.RESPONDED_EXISTENCE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "RESPONDED_EXISTENCE satisfied")
        cmp("c1", make_trace([("A", 0)]), c, "RESPONDED_EXISTENCE violated")
        cmp("c1", make_trace([("B", 0)]), c, "RESPONDED_EXISTENCE vacuous")

    def test_response(self):
        c = con(DeclareTemplate.RESPONSE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "RESPONSE satisfied")
        cmp("c1", make_trace([("A", 0)]), c, "RESPONSE violated")
        cmp("c1", make_trace([("B", 0)]), c, "RESPONSE vacuous")

    def test_alternate_response(self):
        c = con(DeclareTemplate.ALTERNATE_RESPONSE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1), ("A", 2), ("B", 3)]), c, "ALT_RESPONSE satisfied")
        cmp("c1", make_trace([("A", 0), ("A", 1), ("B", 2)]), c, "ALT_RESPONSE violated")

    def test_chain_response(self):
        c = con(DeclareTemplate.CHAIN_RESPONSE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "CHAIN_RESPONSE satisfied")
        cmp("c1", make_trace([("A", 0), ("C", 1), ("B", 2)]), c, "CHAIN_RESPONSE violated")

    def test_precedence(self):
        c = con(DeclareTemplate.PRECEDENCE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "PRECEDENCE satisfied")
        cmp("c1", make_trace([("B", 0)]), c, "PRECEDENCE violated")
        cmp("c1", make_trace([("A", 0)]), c, "PRECEDENCE vacuous")

    def test_alternate_precedence(self):
        c = con(DeclareTemplate.ALTERNATE_PRECEDENCE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1), ("A", 2), ("B", 3)]), c, "ALT_PRECEDENCE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1), ("B", 2)]), c, "ALT_PRECEDENCE violated")

    def test_chain_precedence(self):
        c = con(DeclareTemplate.CHAIN_PRECEDENCE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "CHAIN_PRECEDENCE satisfied")
        cmp("c1", make_trace([("C", 0), ("A", 1), ("C", 2), ("B", 3)]), c, "CHAIN_PRECEDENCE violated")

    def test_co_existence(self):
        c = con(DeclareTemplate.CO_EXISTENCE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "CO_EXISTENCE satisfied")
        cmp("c1", make_trace([("A", 0)]), c, "CO_EXISTENCE violated")
        expect(make_trace([("C", 0)]), c, "vacuous", "CO_EXISTENCE vacuous")
        cmp("c1", make_trace([("B", 0)]), c, "CO_EXISTENCE violated by target")

    def test_succession(self):
        c = con(DeclareTemplate.SUCCESSION, "A", "B")
        # The old checker required A to be surrounded by B; the thesis reading
        # requires every A to be followed by B and every B to be preceded by A.
        expect(make_trace([("A", 0), ("B", 1)]), c, "satisfied", "SUCCESSION satisfied")
        expect(make_trace([("B", 0), ("A", 1), ("B", 2)]), c, "violated", "SUCCESSION first B unpreceded")
        expect(make_trace([("B", 0)]), c, "violated", "SUCCESSION target only")
        cmp("c1", make_trace([("A", 0)]), c, "SUCCESSION violated")
        cmp("c1", make_trace([("C", 0)]), c, "SUCCESSION vacuous")

    def test_alternate_succession(self):
        c = con(DeclareTemplate.ALTERNATE_SUCCESSION, "A", "B")
        expect(make_trace([("A", 0), ("B", 1), ("A", 2), ("B", 3)]), c, "satisfied", "ALT_SUCCESSION satisfied")
        expect(make_trace([("A", 0), ("B", 1), ("B", 2)]), c, "violated", "ALT_SUCCESSION double B")
        cmp("c1", make_trace([("A", 0), ("A", 1), ("B", 2)]), c, "ALT_SUCCESSION violated")

    def test_chain_succession(self):
        c = con(DeclareTemplate.CHAIN_SUCCESSION, "A", "B")
        expect(make_trace([("A", 0), ("B", 1)]), c, "satisfied", "CHAIN_SUCCESSION satisfied")
        expect(make_trace([("C", 0), ("B", 1)]), c, "violated", "CHAIN_SUCCESSION B not after A")
        cmp("c1", make_trace([("A", 0), ("C", 1), ("B", 2)]), c, "CHAIN_SUCCESSION violated")

    def test_not_responded_existence(self):
        c = con(DeclareTemplate.NOT_RESPONDED_EXISTENCE, "A", "B")
        cmp("c1", make_trace([("A", 0)]), c, "NOT_RESPONDED_EXISTENCE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_RESPONDED_EXISTENCE violated")

    def test_not_response(self):
        c = con(DeclareTemplate.NOT_RESPONSE, "A", "B")
        cmp("c1", make_trace([("A", 0)]), c, "NOT_RESPONSE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_RESPONSE violated")

    def test_not_chain_response(self):
        c = con(DeclareTemplate.NOT_CHAIN_RESPONSE, "A", "B")
        cmp("c1", make_trace([("A", 0), ("C", 1), ("B", 2)]), c, "NOT_CHAIN_RESPONSE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_CHAIN_RESPONSE violated")

    def test_not_precedence(self):
        c = con(DeclareTemplate.NOT_PRECEDENCE, "A", "B")
        cmp("c1", make_trace([("B", 0)]), c, "NOT_PRECEDENCE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_PRECEDENCE violated")

    def test_not_chain_precedence(self):
        c = con(DeclareTemplate.NOT_CHAIN_PRECEDENCE, "A", "B")
        cmp("c1", make_trace([("C", 0), ("B", 1)]), c, "NOT_CHAIN_PRECEDENCE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_CHAIN_PRECEDENCE violated")

    def test_not_co_existence(self):
        c = con(DeclareTemplate.NOT_CO_EXISTENCE, "A", "B")
        cmp("c1", make_trace([("A", 0)]), c, "NOT_CO_EXISTENCE satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_CO_EXISTENCE violated")
        expect(make_trace([("C", 0)]), c, "vacuous", "NOT_CO_EXISTENCE vacuous")
        expect(make_trace([("B", 0)]), c, "vacuous", "NOT_CO_EXISTENCE target only vacuous")

    def test_not_succession(self):
        c = con(DeclareTemplate.NOT_SUCCESSION, "A", "B")
        cmp("c1", make_trace([("A", 0)]), c, "NOT_SUCCESSION satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_SUCCESSION violated")
        expect(make_trace([("B", 0), ("A", 1)]), c, "satisfied", "NOT_SUCCESSION reverse order")
        expect(make_trace([("B", 0)]), c, "satisfied", "NOT_SUCCESSION target only")

    def test_not_chain_succession(self):
        c = con(DeclareTemplate.NOT_CHAIN_SUCCESSION, "A", "B")
        cmp("c1", make_trace([("A", 0), ("C", 1), ("B", 2)]), c, "NOT_CHAIN_SUCCESSION satisfied")
        cmp("c1", make_trace([("A", 0), ("B", 1)]), c, "NOT_CHAIN_SUCCESSION violated")
        expect(make_trace([("B", 0), ("A", 1)]), c, "satisfied", "NOT_CHAIN_SUCCESSION reverse pair")


if __name__ == "__main__":
    unittest.main(verbosity=2)
