from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from conformance.weighted_scoring import load_constraints_with_weights


class WeightedLoaderTests(unittest.TestCase):
    def test_load_constraints_with_weights(self) -> None:
        model_path = PROJECT_ROOT / "configs" / "declare" / "readiness_assessment.yaml"
        weights_path = PROJECT_ROOT / "configs" / "declare" / "weights.yaml"

        constraints = load_constraints_with_weights(
            model_yaml_path=model_path,
            weights_yaml_path=weights_path,
        )

        self.assertTrue(len(constraints) >= 1)
        ids = {c.constraint_id for c in constraints}
        self.assertIn("RC-DP-01", ids)

        rc_dp_01 = next(c for c in constraints if c.constraint_id == "RC-DP-01")
        self.assertEqual(rc_dp_01.template_type, "MP_EXISTENCE")
        self.assertTrue("clinical_consequence" in rc_dp_01.metadata_scores)
        self.assertEqual(rc_dp_01.theta, 150.0)
        self.assertEqual(rc_dp_01.theta_crit, 100.0)


if __name__ == "__main__":
    unittest.main()
