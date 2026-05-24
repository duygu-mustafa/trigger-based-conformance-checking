"""Regression test for correlation_condition support in Declare rule checker.

Tests that:
1. The rule loader accepts `correlation_condition` as an alias for `target_condition`
2. The checker evaluates date-based correlation conditions correctly
3. Next-calendar-day matching works as expected for RC-TM-02 style rules
"""

import pandas as pd
from datetime import datetime, timedelta
import unittest
from pathlib import Path
import sys

# Allow running this test file directly without setting PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.types import DeclareConstraint, DeclareTemplate, DataCondition, DeclareModel
from conformance.checker import check_log_conformance
from conformance.results import ConformanceOutcome
from conformance.rules import load_model_from_yaml


class TestCorrelationCondition(unittest.TestCase):
    """Test suite for correlation_condition support."""
    
    @staticmethod
    def create_test_trace(events):
        """Helper to create a simple trace DataFrame from event tuples.
        
        Args:
            events: List of (case_id, activity, timestamp, value_raw) tuples
        
        Returns:
            DataFrame with canonical event log schema
        """
        rows = []
        for case_id, activity, timestamp, value_raw in events:
            rows.append({
                'case_id': case_id,
                'activity': activity,
                'timestamp': pd.Timestamp(timestamp),
                'value_raw': value_raw,
                'value_num': None,
                'itemid': None,
            })
        return pd.DataFrame(rows)
    
    def test_next_day_correlation_condition_satisfied(self):
        """Test that a next-calendar-day correlation condition is satisfied when target occurs on next day."""
        
        # Create events: SBTFailed on day 1, SBTStarted on day 2
        base_date = datetime(2024, 1, 1)
        events = [
            ("case1", "SBTFailed", base_date, "Failure"),
            ("case1", "SBTStarted", base_date + timedelta(days=1, hours=5), "Yes"),
        ]
        trace_df = self.create_test_trace(events)
        
        # Create constraint with next-day correlation condition
        constraint = DeclareConstraint(
            template=DeclareTemplate.RESPONSE,
            activation="SBTFailed",
            target="SBTStarted",
            correlation_cond=DataCondition("date(target_ts) == date(activation_ts) + timedelta(days=1)"),
            label="test-next-day-satisfied",
        )
        constraint.id = "TEST-NextDay-01"
        
        model = DeclareModel(name="test", constraints=[constraint])
        results = check_log_conformance(trace_df, model)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].case_id, "case1")
        self.assertEqual(len(results[0].constraint_results), 1)
        
        result = results[0].constraint_results[0]
        self.assertEqual(result.constraint_id, "TEST-NextDay-01")
        self.assertEqual(result.outcome, ConformanceOutcome.SATISFIED, 
                        f"Expected SATISFIED but got {result.outcome}. Reason: {result.violation_reason}")
    
    def test_next_day_correlation_condition_violated_same_day(self):
        """Test that same-day target violates the next-calendar-day correlation condition."""
        
        # Create events: SBTFailed and SBTStarted on the same day
        base_date = datetime(2024, 1, 1)
        events = [
            ("case1", "SBTFailed", base_date, "Failure"),
            ("case1", "SBTStarted", base_date + timedelta(hours=2), "Yes"),
        ]
        trace_df = self.create_test_trace(events)
        
        # Create constraint with next-day correlation condition
        constraint = DeclareConstraint(
            template=DeclareTemplate.RESPONSE,
            activation="SBTFailed",
            target="SBTStarted",
            correlation_cond=DataCondition("date(target_ts) == date(activation_ts) + timedelta(days=1)"),
            label="test-same-day-violated",
        )
        constraint.id = "TEST-NextDay-02"
        
        model = DeclareModel(name="test", constraints=[constraint])
        results = check_log_conformance(trace_df, model)
        
        self.assertEqual(len(results), 1)
        result = results[0].constraint_results[0]
        self.assertEqual(result.constraint_id, "TEST-NextDay-02")
        self.assertEqual(result.outcome, ConformanceOutcome.VIOLATED, 
                        f"Expected VIOLATED but got {result.outcome}. Reason: {result.violation_reason}")
    
    def test_next_day_correlation_condition_violated_two_days_later(self):
        """Test that two-days-later target violates the next-calendar-day correlation condition."""
        
        # Create events: SBTFailed on day 1, SBTStarted on day 3
        base_date = datetime(2024, 1, 1)
        events = [
            ("case1", "SBTFailed", base_date, "Failure"),
            ("case1", "SBTStarted", base_date + timedelta(days=2, hours=5), "Yes"),
        ]
        trace_df = self.create_test_trace(events)
        
        # Create constraint with next-day correlation condition
        constraint = DeclareConstraint(
            template=DeclareTemplate.RESPONSE,
            activation="SBTFailed",
            target="SBTStarted",
            correlation_cond=DataCondition("date(target_ts) == date(activation_ts) + timedelta(days=1)"),
            label="test-two-days-violated",
        )
        constraint.id = "TEST-NextDay-03"
        
        model = DeclareModel(name="test", constraints=[constraint])
        results = check_log_conformance(trace_df, model)
        
        self.assertEqual(len(results), 1)
        result = results[0].constraint_results[0]
        self.assertEqual(result.constraint_id, "TEST-NextDay-03")
        self.assertEqual(result.outcome, ConformanceOutcome.VIOLATED, 
                        f"Expected VIOLATED but got {result.outcome}. Reason: {result.violation_reason}")
    
    def test_correlation_condition_yaml_alias(self):
        """Test that the YAML loader accepts correlation_condition as a field alias."""
        
        # Create a minimal YAML config with correlation_condition field
        yaml_path = Path("/tmp/test_correlation_condition.yaml")
        yaml_content = """
version: 1
model:
  name: test
  constraints:
    - id: TEST-YAML-01
      label: "Test correlation_condition alias"
      template: RESPONSE
      activation: ActivityA
      target: ActivityB
      correlation_condition: "target_ts > activation_ts"
"""
        yaml_path.write_text(yaml_content)
        
        try:
            model = load_model_from_yaml(yaml_path)
            self.assertEqual(len(model.constraints), 1)
            constraint = model.constraints[0]
            self.assertEqual(constraint.id, "TEST-YAML-01")
            self.assertIsNotNone(constraint.correlation_cond, 
                                "correlation_condition should be parsed into correlation_cond")
            self.assertEqual(constraint.correlation_cond.expression, "target_ts > activation_ts")
        finally:
            yaml_path.unlink(missing_ok=True)
    
    def test_rc_tm_02_readiness_model(self):
        """Regression test: verify the updated RC-TM-02 rule in readiness_assessment.yaml loads correctly."""
        
        yaml_path = Path(__file__).parent.parent / "configs" / "declare" / "readiness_assessment.yaml"
        
        if not yaml_path.exists():
            self.skipTest(f"readiness_assessment.yaml not found at {yaml_path}")
        
        model = load_model_from_yaml(yaml_path)
        
        # Find RC-TM-02 constraint
        rc_tm_02 = None
        for constraint in model.constraints:
            if constraint.id == "RC-TM-02":
                rc_tm_02 = constraint
                break
        
        self.assertIsNotNone(rc_tm_02, "RC-TM-02 constraint should be in readiness model")
        self.assertEqual(rc_tm_02.template, DeclareTemplate.RESPONSE, 
                        f"RC-TM-02 should use RESPONSE template, got {rc_tm_02.template}")
        self.assertEqual(rc_tm_02.activation, "SBTFailed", "RC-TM-02 activation should be SBTFailed")
        self.assertEqual(rc_tm_02.target, "SBTStarted", "RC-TM-02 target should be SBTStarted")
        self.assertIsNotNone(rc_tm_02.correlation_cond, "RC-TM-02 should have a correlation_cond")
        # The condition should reference date arithmetic
        self.assertIn("date", rc_tm_02.correlation_cond.expression.lower(),
                     "RC-TM-02 correlation_cond should reference date function")

    def test_rc_tm_02_early_and_late_templates_load(self):
        """Regression test: verify RC-TM-02-early/late load with expected templates and guards."""

        yaml_path = Path(__file__).parent.parent / "configs" / "declare" / "readiness_assessment.yaml"

        if not yaml_path.exists():
            self.skipTest(f"readiness_assessment.yaml not found at {yaml_path}")

        model = load_model_from_yaml(yaml_path)
        by_id = {constraint.id: constraint for constraint in model.constraints}

        early = by_id.get("RC-TM-02-early")
        late = by_id.get("RC-TM-02-late")

        self.assertIsNotNone(early, "RC-TM-02-early constraint should be in readiness model")
        self.assertIsNotNone(late, "RC-TM-02-late constraint should be in readiness model")

        self.assertEqual(early.template, DeclareTemplate.NOT_RESPONSE)
        self.assertEqual(early.activation, "SBTFailed")
        self.assertEqual(early.target, "SBTStarted")
        self.assertIsNotNone(early.correlation_cond)
        self.assertIn("date(target_ts) == date(activation_ts)", early.correlation_cond.expression)

        self.assertEqual(late.template, DeclareTemplate.RESPONSE)
        self.assertEqual(late.activation, "SBTFailed")
        self.assertEqual(late.target, "SBTStarted")
        self.assertIsNotNone(late.correlation_cond)
        self.assertIn("date(target_ts) <= date(activation_ts) + timedelta(days=1)", late.correlation_cond.expression)

    def test_rc_tm_02_early_and_late_runtime_behavior(self):
        """Regression test: ensure early and late retry rules evaluate as intended."""

        constraints = [
            DeclareConstraint(
                template=DeclareTemplate.NOT_RESPONSE,
                activation="SBTFailed",
                target="SBTStarted",
                correlation_cond=DataCondition("date(target_ts) == date(activation_ts)"),
                label="RC-TM-02-early",
            ),
            DeclareConstraint(
                template=DeclareTemplate.RESPONSE,
                activation="SBTFailed",
                target="SBTStarted",
                correlation_cond=DataCondition("date(target_ts) <= date(activation_ts) + timedelta(days=1)"),
                label="RC-TM-02-late",
            ),
        ]

        constraints[0].id = "RC-TM-02-early"
        constraints[1].id = "RC-TM-02-late"
        model = DeclareModel(name="test-early-late", constraints=constraints)

        base = datetime(2024, 1, 1, 8, 0, 0)

        # Same-day retry: violates early rule, still satisfies no-later-than-next-day rule.
        same_day = self.create_test_trace([
            ("same-day", "SBTFailed", base, "Failure"),
            ("same-day", "SBTStarted", base + timedelta(hours=6), "Yes"),
        ])

        # Next-day retry: satisfies both rules.
        next_day = self.create_test_trace([
            ("next-day", "SBTFailed", base, "Failure"),
            ("next-day", "SBTStarted", base + timedelta(days=1, hours=2), "Yes"),
        ])

        # Delayed retry (> next day): satisfies early rule, violates late rule.
        too_late = self.create_test_trace([
            ("too-late", "SBTFailed", base, "Failure"),
            ("too-late", "SBTStarted", base + timedelta(days=2, hours=1), "Yes"),
        ])

        all_traces = pd.concat([same_day, next_day, too_late], ignore_index=True)
        results = check_log_conformance(all_traces, model)

        outcomes: dict[str, dict[str, ConformanceOutcome]] = {}
        for trace_result in results:
            by_constraint: dict[str, ConformanceOutcome] = {}
            for cr in trace_result.constraint_results:
                by_constraint[cr.constraint_id] = cr.outcome
            outcomes[trace_result.case_id] = by_constraint

        self.assertEqual(outcomes["same-day"]["RC-TM-02-early"], ConformanceOutcome.VIOLATED)
        self.assertEqual(outcomes["same-day"]["RC-TM-02-late"], ConformanceOutcome.SATISFIED)

        self.assertEqual(outcomes["next-day"]["RC-TM-02-early"], ConformanceOutcome.SATISFIED)
        self.assertEqual(outcomes["next-day"]["RC-TM-02-late"], ConformanceOutcome.SATISFIED)

        self.assertEqual(outcomes["too-late"]["RC-TM-02-early"], ConformanceOutcome.SATISFIED)
        self.assertEqual(outcomes["too-late"]["RC-TM-02-late"], ConformanceOutcome.VIOLATED)


if __name__ == "__main__":
    unittest.main(verbosity=2)

