"""Tests for the synthetic ground-truth generator.

The generator's output is only useful if the planted verdicts and the planted
outcome model are what they claim to be, so these tests check both against the
checker and against the drawn outcomes.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.checker import evaluate_constraint  # noqa: E402
from evaluation.rtfm_utils import build_trigger_episodes  # noqa: E402
from evaluation.synthetic_log import (  # noqa: E402
    CORRECTNESS_CASES,
    RULES,
    TRIGGER,
    SyntheticLogConfig,
    aggregate_case_truth,
    generate_log,
    rule_model,
)


class TestCorrectnessCatalogue(unittest.TestCase):

    def test_every_case_matches_or_is_documented(self):
        unexplained = []
        for case in CORRECTNESS_CASES:
            observed = evaluate_constraint(
                case_id=case.case_id, trace_df=case.trace(), constraint=case.constraint
            ).outcome
            if observed != case.expected and case.note is None:
                unexplained.append((case.case_id, case.expected.value, observed.value))
        self.assertEqual(unexplained, [], f"undocumented verdict mismatches: {unexplained}")

    def test_catalogue_covers_every_implemented_template(self):
        from conformance.checker import _TEMPLATE_EVALUATORS

        covered = {case.constraint.template for case in CORRECTNESS_CASES}
        missing = sorted(t.name for t in _TEMPLATE_EVALUATORS if t not in covered)
        self.assertEqual(missing, [], f"templates without a correctness case: {missing}")


class TestGenerator(unittest.TestCase):

    def setUp(self):
        self.log, self.truth = generate_log(SyntheticLogConfig(n_cases=150), seed=7)

    def test_deterministic_under_a_fixed_seed(self):
        log2, truth2 = generate_log(SyntheticLogConfig(n_cases=150), seed=7)
        self.assertTrue(self.log.equals(log2))
        self.assertTrue(self.truth.equals(truth2))

    def test_seeds_differ(self):
        _, truth_other = generate_log(SyntheticLogConfig(n_cases=150), seed=8)
        self.assertFalse(self.truth.equals(truth_other))

    def test_episode_verdicts_match_the_planted_ground_truth(self):
        model = rule_model()
        truth = self.truth.set_index(["case_id", "episode_index"])
        mismatches = []
        for case_id, trace in self.log.groupby("case_id", sort=False):
            trace = trace.sort_values("timestamp")
            windows = build_trigger_episodes(trace, TRIGGER)
            self.assertEqual(len(windows), int(truth.loc[case_id, "n_episodes"].iloc[0]))
            for ep_idx, (start_ts, end_ts) in enumerate(windows):
                episode = trace[
                    (trace["timestamp"] >= start_ts) & (trace["timestamp"] < end_ts)
                ]
                planted = truth.loc[(case_id, ep_idx)]
                for constraint in model.constraints:
                    observed = evaluate_constraint(
                        case_id=str(case_id), trace_df=episode, constraint=constraint
                    ).outcome.value
                    if observed != planted[constraint.label]:
                        mismatches.append(
                            (case_id, ep_idx, constraint.label, planted[constraint.label], observed)
                        )
        self.assertEqual(mismatches[:5], [], f"{len(mismatches)} planted verdicts not reproduced")

    def test_multi_episode_cases_are_generated(self):
        counts = self.truth.groupby("case_id").size()
        self.assertGreater((counts > 1).mean(), 0.3)
        self.assertLessEqual(counts.max(), SyntheticLogConfig().max_episodes)

    def test_case_truth_aggregates_episode_truth(self):
        cases = aggregate_case_truth(self.truth)
        self.assertEqual(len(cases), self.truth["case_id"].nunique())
        rid = RULES[0].rule_id
        for _, row in cases.head(20).iterrows():
            episodes = self.truth[self.truth["case_id"] == row["case_id"]][rid]
            expected = (
                "violated" if (episodes == "violated").any()
                else "vacuous" if set(episodes) == {"vacuous"}
                else "satisfied"
            )
            self.assertEqual(row[rid], expected)

    def test_outcome_model_is_unbiased(self):
        """Each rule's marginal risk ratio must equal its planted value.

        Checked on the success probabilities rather than the drawn outcomes, so
        that the assertion measures the model and not the sampling noise. This
        is the property that fails first if the probabilities are ever clipped.
        """
        _, truth = generate_log(SyntheticLogConfig(n_cases=8000), seed=11)
        for rule in RULES:
            violated = truth[truth[rule.rule_id] == "violated"]["p_success"]
            satisfied = truth[truth[rule.rule_id] == "satisfied"]["p_success"]
            realised = violated.mean() / satisfied.mean()
            self.assertAlmostEqual(
                realised, rule.planted_rr, delta=0.05 * rule.planted_rr,
                msg=f"{rule.rule_id}: planted {rule.planted_rr}, realised {realised:.3f}",
            )

    def test_success_probability_never_needs_clipping(self):
        cfg = SyntheticLogConfig()
        self.assertLessEqual(cfg.max_success_probability(), 1.0)
        _, truth = generate_log(cfg.__class__(n_cases=500), seed=3)
        self.assertLessEqual(truth["p_success"].max(), 1.0)

    def test_impossible_configuration_is_rejected(self):
        cfg = SyntheticLogConfig(n_cases=10, p0_success=0.9)
        with self.assertRaises(ValueError):
            generate_log(cfg, seed=1)

    def test_drawn_outcomes_track_the_planted_ratios(self):
        _, truth = generate_log(SyntheticLogConfig(n_cases=8000), seed=11)
        for rule in RULES:
            violated = truth[truth[rule.rule_id] == "violated"]["outcome"]
            satisfied = truth[truth[rule.rule_id] == "satisfied"]["outcome"]
            realised = violated.mean() / satisfied.mean()
            self.assertAlmostEqual(
                realised, rule.planted_rr, delta=0.20 * rule.planted_rr,
                msg=f"{rule.rule_id}: planted {rule.planted_rr}, realised {realised:.2f}",
            )

    def test_wide_schema_without_itemid_column(self):
        """Data conditions must read event attributes, which needs the wide path."""
        self.assertNotIn("itemid", self.log.columns)
        self.assertIn("amount", self.log.columns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
