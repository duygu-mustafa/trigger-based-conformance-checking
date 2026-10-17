"""Target-selection cases from tests/test_target_selection.py, run on the automata engine.

Cross-checks experimental/automata.py against the verdicts the checker is tested for.
"""

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from experimental.automata import Event, build_automaton_for_constraint
from tests import test_target_selection as base


def run_automaton(df, c):
    aut = build_automaton_for_constraint(c)
    for idx, row in df.iterrows():
        aut.process_event(Event("c1", row["activity"], row["timestamp"], idx), df)
    aut.close_trace(df)
    return aut.to_result("c1", "x")


class AutomataTargetSelectionTest(base.TargetSelectionTest):
    engines = {"automata": run_automaton}


if __name__ == "__main__":
    unittest.main()
