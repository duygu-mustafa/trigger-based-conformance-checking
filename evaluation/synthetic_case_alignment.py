"""Which episode a case-scoped violation reflects (supports the SE3 discussion).

Under case scope a case carries the outcome of its *final* episode, so a
case-level verdict only carries the planted effect insofar as it reflects that
episode. Masking decides how often it does: for Response, earlier violations are
answered by later targets and the surviving violations sit in the final
episode; for Precedence, an earlier target answers later activations and the
surviving violations sit in the first episode.

For each rule, restricted to multi-episode cases, prints the share of
case-level violations whose final (and first) episode is truly violated, and
the share of case-level satisfactions whose final episode is truly violated.

Usage::

    python evaluation/synthetic_case_alignment.py --reps 5 --cases 1000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from benchmark_synthetic import run_replication  # noqa: E402


def alignment_table(episodes: pd.DataFrame, cases: pd.DataFrame) -> pd.DataFrame:
    rules = sorted(c[: -len("_true")] for c in episodes.columns if c.endswith("_true"))
    key = ["seed", "case_id"]
    last = episodes.sort_values("episode_index").groupby(key).tail(1).set_index(key)
    first = episodes[episodes["episode_index"] == 0].set_index(key)
    multi = cases.set_index(key)
    multi = multi[multi["n_episodes"] > 1]

    rows = []
    for rule in rules:
        true_col, obs_col = f"{rule}_true", f"{rule}_obs"
        viol = multi[multi[obs_col] == "violated"].index
        sat = multi[multi[obs_col] == "satisfied"].index
        rows.append(
            {
                "rule": rule,
                "n_case_violated": len(viol),
                "final_violated_given_case_violated": (last.loc[viol, true_col] == "violated").mean(),
                "first_violated_given_case_violated": (first.loc[viol, true_col] == "violated").mean(),
                "n_case_satisfied": len(sat),
                "final_violated_given_case_satisfied": (last.loc[sat, true_col] == "violated").mean(),
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--cases", type=int, default=1000, help="cases per replication")
    parser.add_argument("--seed", type=int, default=42, help="first seed")
    args = parser.parse_args()

    episode_frames, case_frames = [], []
    for rep in range(args.reps):
        seed = args.seed + rep
        episodes, cases = run_replication(seed, args.cases)
        episodes["seed"], cases["seed"] = seed, seed
        episode_frames.append(episodes)
        case_frames.append(cases)

    table = alignment_table(pd.concat(episode_frames), pd.concat(case_frames))
    print(table.to_string(index=False, float_format=lambda v: f"{v:.2f}"))


if __name__ == "__main__":
    main()
