"""Cache the per-trigger distributions behind the trigger-sensitivity figures.

trigger_sensitivity.ipynb writes the scalar metrics to
data/trigger_sensitivity.csv but keeps the raw distributions (episodes per case,
events per episode) in memory only. This script recomputes them on the same
working set (same sample size and seed as the notebook), checks that the scalar
metrics reproduce the cached CSV, and stores the distributions so that
thesis_figures.py can redraw the figures without rerunning the sweep.

Usage:
    python evaluation/trigger_distributions.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from evaluation.rtfm_utils import compute_segmentation_metrics  # noqa: E402

DATA_DIR = REPO_ROOT / "evaluation" / "data"
PARQUET_CACHE = DATA_DIR / "rtfm_event_log.parquet"
METRICS_CSV = DATA_DIR / "trigger_sensitivity.csv"
DIST_NPZ = DATA_DIR / "trigger_distributions.npz"

# As in trigger_sensitivity.ipynb.
TRIGGER_CANDIDATES = [
    "Create Fine",
    "Send Fine",
    "Insert Fine Notification",
    "Add penalty",
    "Payment",
    "Appeal to Judge",
]
SAMPLE_N = 20_000
RANDOM_STATE = 42


def main() -> None:
    log = pd.read_parquet(PARQUET_CACHE)
    all_case_ids = log["case_id"].drop_duplicates()
    case_ids = set(all_case_ids.sample(n=SAMPLE_N, random_state=RANDOM_STATE))
    sample = log[log["case_id"].isin(case_ids)].copy()
    print(f"working set: {sample['case_id'].nunique():,} cases / {len(sample):,} events",
          flush=True)

    cached = pd.read_csv(METRICS_CSV, index_col="trigger")
    arrays = {}
    for trigger in TRIGGER_CANDIDATES:
        m = compute_segmentation_metrics(sample, trigger, return_distributions=True)
        arrays[f"{trigger}|eps_per_case"] = np.asarray(m.pop("_dist_eps_per_case"))
        arrays[f"{trigger}|ep_events"] = np.asarray(m.pop("_dist_ep_events"))
        # The sample must be the notebook's: the scalar metrics have to match.
        for key in ("case_coverage", "eps_per_case_mean", "success_share"):
            assert np.isclose(m[key], cached.loc[trigger, key]), (trigger, key)
        print(f"  {trigger}: matches cached metrics", flush=True)

    np.savez_compressed(DIST_NPZ, **arrays)
    print(f"written: {DIST_NPZ}")


if __name__ == "__main__":
    main()
