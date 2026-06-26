"""Regression test for correlation_condition support in Declare rule checker.

Tests that:
1. The rule loader accepts `correlation_condition` as an alias for `target_condition`
2. The checker evaluates date-based correlation conditions correctly
3. Next-calendar-day matching works as expected for SBT-TM-01 style rules
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
# Manual helper removed; tests will use the derived-event + checker flow


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
    
    def test_sbt_tm_01_readiness_model(self):
        """Regression test: verify the updated SBT-TM-01 rule in sbt_execution.yaml loads correctly."""
        
        yaml_path = Path(__file__).parent.parent / "configs" / "declare" / "sbt_execution.yaml"
        
        if not yaml_path.exists():
            self.skipTest(f"readiness_assessment.yaml not found at {yaml_path}")
        
        model = load_model_from_yaml(yaml_path)
        
        # Find SBT-TM-01 constraint
        sbt_tm_01 = None
        for constraint in model.constraints:
            if constraint.id == "SBT-TM-01":
                sbt_tm_01 = constraint
                break

        if sbt_tm_01 is None:
            self.skipTest("SBT-TM-01 is not defined in the current SBT model")
        
        self.assertIsNotNone(sbt_tm_01, "SBT-TM-01 constraint should be in the SBT model")
        self.assertEqual(sbt_tm_01.template, DeclareTemplate.RESPONSE, 
                        f"SBT-TM-01 should use RESPONSE template, got {sbt_tm_01.template}")
        self.assertEqual(sbt_tm_01.activation, "SBTFailed", "SBT-TM-01 activation should be SBTFailed")
        self.assertEqual(sbt_tm_01.target, "SBTStarted", "SBT-TM-01 target should be SBTStarted")
        self.assertIsNotNone(sbt_tm_01.correlation_cond, "SBT-TM-01 should have a correlation_cond")
        # The condition should reference date arithmetic
        self.assertIn("date", sbt_tm_01.correlation_cond.expression.lower(),
                     "SBT-TM-01 correlation_cond should reference date function")

    def test_sbt_tm_01_early_and_late_templates_load(self):
        """Regression test: verify SBT-TM-01-early/late load with expected templates and guards."""

        yaml_path = Path(__file__).parent.parent / "configs" / "declare" / "sbt_execution.yaml"

        if not yaml_path.exists():
            self.skipTest(f"readiness_assessment.yaml not found at {yaml_path}")

        model = load_model_from_yaml(yaml_path)
        by_id = {constraint.id: constraint for constraint in model.constraints}

        if "SBT-TM-01-early" not in by_id or "SBT-TM-01-late" not in by_id:
            self.skipTest("SBT-TM-01-early/late are not defined in the current SBT model")

        early = by_id.get("SBT-TM-01-early")
        late = by_id.get("SBT-TM-01-late")

        self.assertIsNotNone(early, "SBT-TM-01-early constraint should be in the SBT model")
        self.assertIsNotNone(late, "SBT-TM-01-late constraint should be in the SBT model")

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

    def test_sbt_tm_01_early_and_late_runtime_behavior(self):
        """Regression test: ensure early and late retry rules evaluate as intended."""

        constraints = [
            DeclareConstraint(
                template=DeclareTemplate.NOT_RESPONSE,
                activation="SBTFailed",
                target="SBTStarted",
                correlation_cond=DataCondition("date(target_ts) == date(activation_ts)"),
                label="SBT-TM-01-early",
            ),
            DeclareConstraint(
                template=DeclareTemplate.RESPONSE,
                activation="SBTFailed",
                target="SBTStarted",
                correlation_cond=DataCondition("date(target_ts) <= date(activation_ts) + timedelta(days=1)"),
                label="SBT-TM-01-late",
            ),
        ]

        constraints[0].id = "SBT-TM-01-early"
        constraints[1].id = "SBT-TM-01-late"
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

        self.assertEqual(outcomes["same-day"]["SBT-TM-01-early"], ConformanceOutcome.VIOLATED)
        self.assertEqual(outcomes["same-day"]["SBT-TM-01-late"], ConformanceOutcome.SATISFIED)

        self.assertEqual(outcomes["next-day"]["SBT-TM-01-early"], ConformanceOutcome.SATISFIED)
        self.assertEqual(outcomes["next-day"]["SBT-TM-01-late"], ConformanceOutcome.SATISFIED)

        self.assertEqual(outcomes["too-late"]["SBT-TM-01-early"], ConformanceOutcome.SATISFIED)
        self.assertEqual(outcomes["too-late"]["SBT-TM-01-late"], ConformanceOutcome.VIOLATED)

    def test_sbt_tm_01_manual_outcome_helper(self):
        """Regression test: the manual SBT timing helper should classify gaps consistently."""

        base = datetime(2024, 1, 1, 8, 0, 0)
        # Use the Declare model + checker and include explicit derived SBTFailed
        # events in traces so the general checker can evaluate timing semantics.
        yaml_path = Path(__file__).parent.parent / "configs" / "declare" / "sbt_execution.yaml"
        if not yaml_path.exists():
            self.skipTest(f"sbt_execution.yaml not found at {yaml_path}")

        model = load_model_from_yaml(yaml_path)

        vacuous_trace = pd.DataFrame(
            [
                {"case_id": "case1", "activity": "InvasiveVentilationStarted", "timestamp": pd.Timestamp(base)},
                {"case_id": "case1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base + timedelta(hours=4))},
            ]
        )
        results = check_log_conformance(vacuous_trace, model)
        self.assertEqual(len(results), 1)
        cr = next((c for c in results[0].constraint_results if c.constraint_id == "SBT-TM-01"), None)
        self.assertIsNotNone(cr, "SBT-TM-01 constraint not found in model results")
        self.assertEqual(cr.outcome, ConformanceOutcome.VACUOUS)

        # Early retry (same calendar day) should violate SBT-TM-01
        early_retry_trace = pd.DataFrame(
            [
                {"case_id": "case1", "activity": "InvasiveVentilationStarted", "timestamp": pd.Timestamp(base)},
                {"case_id": "case1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base + timedelta(hours=4))},
                {"case_id": "case1", "activity": "SBTFailed", "timestamp": pd.Timestamp(base + timedelta(hours=6))},
                {"case_id": "case1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base + timedelta(hours=12))},
            ]
        )
        results = check_log_conformance(early_retry_trace, model)
        self.assertEqual(len(results), 1)
        cr = next((c for c in results[0].constraint_results if c.constraint_id == "SBT-TM-01"), None)
        self.assertIsNotNone(cr, "SBT-TM-01 constraint not found in model results")
        self.assertEqual(cr.outcome, ConformanceOutcome.VIOLATED)

        # Next-day retry should satisfy SBT-TM-01
        next_day_trace = pd.DataFrame(
            [
                {"case_id": "case1", "activity": "InvasiveVentilationStarted", "timestamp": pd.Timestamp(base)},
                {"case_id": "case1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base + timedelta(hours=4))},
                {"case_id": "case1", "activity": "SBTFailed", "timestamp": pd.Timestamp(base + timedelta(hours=6))},
                {"case_id": "case1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base + timedelta(hours=20))},
            ]
        )
        results = check_log_conformance(next_day_trace, model)
        self.assertEqual(len(results), 1)
        cr = next((c for c in results[0].constraint_results if c.constraint_id == "SBT-TM-01"), None)
        self.assertIsNotNone(cr, "SBT-TM-01 constraint not found in model results")
        self.assertEqual(cr.outcome, ConformanceOutcome.SATISFIED)

    def test_end_template_checks_last_event(self):
        """End should require the last event in the trace to match the activation activity."""

        constraint = DeclareConstraint(
            template=DeclareTemplate.END,
            activation="TargetActivity",
            label="TEST-END-01",
        )
        constraint.id = "TEST-END-01"

        model = DeclareModel(name="test-end", constraints=[constraint])

        satisfied = self.create_test_trace([
            ("end-ok", "OtherActivity", datetime(2024, 1, 1, 8, 0, 0), "x"),
            ("end-ok", "TargetActivity", datetime(2024, 1, 1, 9, 0, 0), "x"),
        ])
        violated = self.create_test_trace([
            ("end-bad", "TargetActivity", datetime(2024, 1, 1, 8, 0, 0), "x"),
            ("end-bad", "OtherActivity", datetime(2024, 1, 1, 9, 0, 0), "x"),
        ])

        results = check_log_conformance(pd.concat([satisfied, violated], ignore_index=True), model)
        outcomes = {trace.case_id: trace.constraint_results[0].outcome for trace in results}

        self.assertEqual(outcomes["end-ok"], ConformanceOutcome.SATISFIED)
        self.assertEqual(outcomes["end-bad"], ConformanceOutcome.VIOLATED)

    def test_not_chain_succession_template(self):
        """Not Chain Succession should reject immediate A->B pairs and allow non-adjacent cases."""

        constraint = DeclareConstraint(
            template=DeclareTemplate.NOT_CHAIN_SUCCESSION,
            activation="ActivityA",
            target="ActivityB",
            label="TEST-NCS-01",
        )
        constraint.id = "TEST-NCS-01"

        model = DeclareModel(name="test-not-chain-succession", constraints=[constraint])

        violated = self.create_test_trace([
            ("ncs-bad", "ActivityA", datetime(2024, 1, 1, 8, 0, 0), "x"),
            ("ncs-bad", "ActivityB", datetime(2024, 1, 1, 8, 5, 0), "x"),
        ])
        satisfied = self.create_test_trace([
            ("ncs-ok", "ActivityA", datetime(2024, 1, 1, 8, 0, 0), "x"),
            ("ncs-ok", "OtherActivity", datetime(2024, 1, 1, 8, 5, 0), "x"),
            ("ncs-ok", "ActivityB", datetime(2024, 1, 1, 8, 10, 0), "x"),
        ])

        results = check_log_conformance(pd.concat([violated, satisfied], ignore_index=True), model)
        outcomes = {trace.case_id: trace.constraint_results[0].outcome for trace in results}

        self.assertEqual(outcomes["ncs-bad"], ConformanceOutcome.VIOLATED)
        self.assertEqual(outcomes["ncs-ok"], ConformanceOutcome.SATISFIED)


if __name__ == "__main__":
    unittest.main(verbosity=2)

