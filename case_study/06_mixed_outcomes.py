"""Mixed episode outcomes within a stay, and the stay-id lists for the ablation.

A per-stay (trace-global) verdict must assign one outcome label to a whole ICU stay.
This script counts the stays for which that label would necessarily be wrong for part
of the stay, namely those containing both a failed and a successful breathing trial.

It also writes the stay-id lists that the segmentation ablation runs on.

Usage:
    python case_study/06_mixed_outcomes.py [--sample-size 2000] [--seed 42]
"""

from __future__ import annotations

import argparse
import time

import matplotlib.pyplot as plt
import pandas as pd

from config import (
    EPISODE_RESULTS,
    FIG_WIDTH,
    OUT_DIR,
    OUTCOME_COLOR,
    save_fig,
    top_legend,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label

MULTI_EPISODE_IDS = OUT_DIR / "multi_episode_stay_ids.txt"


def sample_ids_path(n: int) -> "object":
    return OUT_DIR / f"ablation_sample_{n}_stay_ids.txt"


def episode_bucket(n: int) -> str:
    return str(n) if n <= 4 else "5+"


# Outcome classes of a stay, bottom to top. Success and failure keep the outcome
# colours of the other figures; mixed sits between them, missing is neutral.
CLASS_ORDER = ["all success", "mixed", "all failure", "no evaluable outcome"]
CLASS_COLOR = {
    "all success": OUTCOME_COLOR["success"],
    "mixed": "#E69F00",
    "all failure": OUTCOME_COLOR["failure"],
    "no evaluable outcome": "#c7c7c7",
}


def _plot_composition(table: pd.DataFrame) -> None:
    shares = table.div(table.sum(axis=1), axis=0).fillna(0)
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.8))
    bottom = None
    for cls in CLASS_ORDER:
        if cls not in shares.columns:
            continue
        vals = shares[cls].values
        # A thin surface-coloured edge separates the stacked segments.
        ax.bar(shares.index, vals, bottom=bottom, width=0.7, color=CLASS_COLOR[cls],
               edgecolor="white", linewidth=1, label=cls)
        bottom = vals if bottom is None else bottom + vals
    ax.set_ylim(0, 1.0)
    ax.set_xlabel("Episodes in stay")
    ax.set_ylabel("Share of stays")
    ax.grid(axis="x", visible=False)
    top_legend(ax)
    save_fig(fig, "fig_mixed_outcomes")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample-size", type=int, default=2000,
                        help="Size of the ablation sample drawn from multi-episode stays.")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--replot", action="store_true",
        help="Regenerate the figure from the cached CSV only, without recomputing.",
    )
    args = parser.parse_args()

    if args.replot:
        table = pd.read_csv(
            OUT_DIR / "mixed_outcomes_composition_by_episode_count.csv",
            dtype={"episodes_in_stay": str},
        ).set_index("episodes_in_stay")
        _plot_composition(table)
        return

    t0 = time.time()
    df = pd.read_csv(
        EPISODE_RESULTS,
        usecols=["stay_id", "episode_index", "sbt_outcome"],
        low_memory=False,
    )
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    print(f"Loaded {len(df):,} episodes over {df['stay_id'].nunique():,} stays")

    per_stay = df.groupby("stay_id").agg(
        n_episodes=("episode_index", "count"),
        n_evaluable=("outcome_binary", "count"),
        n_success=("outcome_binary", "sum"),
    )
    per_stay["n_failure"] = per_stay["n_evaluable"] - per_stay["n_success"]
    per_stay["mixed"] = (per_stay["n_success"] > 0) & (per_stay["n_failure"] > 0)
    per_stay["episode_bucket"] = per_stay["n_episodes"].map(episode_bucket)

    n_stays = len(per_stay)
    multi = per_stay[per_stay["n_episodes"] > 1]
    ge2_evaluable = per_stay[per_stay["n_evaluable"] > 1]
    mixed = per_stay[per_stay["mixed"]]

    # Best case for a collapsed per-stay label: assign the majority outcome. The
    # minority episodes are then mislabelled; count them.
    minority = pd.concat(
        [mixed["n_success"], mixed["n_failure"]], axis=1
    ).min(axis=1)
    n_episodes_mislabelled = int(minority.sum())
    n_episodes_in_mixed = int(mixed["n_evaluable"].sum())

    overview = {
        "source": str(EPISODE_RESULTS),
        "n_stays": int(n_stays),
        "n_multi_episode_stays": int(len(multi)),
        "n_stays_with_two_or_more_evaluable": int(len(ge2_evaluable)),
        "n_mixed_outcome_stays": int(len(mixed)),
        "mixed_share_of_multi_episode": float(len(mixed) / len(multi)) if len(multi) else None,
        "mixed_share_of_two_or_more_evaluable": (
            float(len(mixed) / len(ge2_evaluable)) if len(ge2_evaluable) else None
        ),
        "mixed_share_of_all_stays": float(len(mixed) / n_stays),
        "n_episodes_in_mixed_stays": n_episodes_in_mixed,
        "n_episodes_mislabelled_by_majority_collapse": n_episodes_mislabelled,
        "share_episodes_mislabelled_within_mixed_stays": (
            n_episodes_mislabelled / n_episodes_in_mixed if n_episodes_in_mixed else None
        ),
        "share_all_evaluable_episodes_mislabelled": (
            n_episodes_mislabelled / int(per_stay["n_evaluable"].sum())
        ),
        "failures_per_mixed_stay_mean": float(mixed["n_failure"].mean()),
        "failures_per_mixed_stay_median": float(mixed["n_failure"].median()),
    }

    by_count = (
        per_stay.groupby("episode_bucket")
        .agg(
            n_stays=("n_episodes", "size"),
            n_mixed=("mixed", "sum"),
            n_all_success=("n_failure", lambda s: int((s == 0).sum())),
        )
        .reset_index()
        .rename(columns={"episode_bucket": "episodes_in_stay"})
    )
    by_count["mixed_share"] = by_count["n_mixed"] / by_count["n_stays"]
    order = ["1", "2", "3", "4", "5+"]
    by_count["_o"] = by_count["episodes_in_stay"].map({k: i for i, k in enumerate(order)})
    by_count = by_count.sort_values("_o").drop(columns="_o")

    # composition per bucket for the figure and the table
    comp = per_stay.copy()
    comp["class"] = "no evaluable outcome"
    comp.loc[comp["n_evaluable"] > 0, "class"] = "all success"
    comp.loc[(comp["n_evaluable"] > 0) & (comp["n_success"] == 0), "class"] = "all failure"
    comp.loc[comp["mixed"], "class"] = "mixed"
    table = (
        comp.groupby(["episode_bucket", "class"]).size().unstack(fill_value=0)
    ).reindex(order)
    write_csv(table.reset_index().rename(columns={"episode_bucket": "episodes_in_stay"}),
              "mixed_outcomes_composition_by_episode_count.csv")
    write_csv(by_count, "mixed_outcomes_by_episode_count.csv")
    write_json(overview, "mixed_outcomes.json")

    # ---- stay-id lists for the ablation ---------------------------------
    multi_ids = sorted(multi.index.astype(str))
    MULTI_EPISODE_IDS.write_text("\n".join(multi_ids) + "\n", encoding="utf-8")
    print(f"  ids    -> {MULTI_EPISODE_IDS} ({len(multi_ids):,} stays)")

    n = min(args.sample_size, len(multi_ids))
    sample = (
        multi.sample(n=n, random_state=args.seed).index.astype(str).sort_values()
    )
    sample_path = sample_ids_path(args.sample_size)
    sample_path.write_text("\n".join(sample) + "\n", encoding="utf-8")
    print(f"  ids    -> {sample_path} ({n:,} stays, seed {args.seed})")

    # ---- figure ----------------------------------------------------------
    _plot_composition(table)

    print(
        f"Mixed-outcome stays: {len(mixed):,} of {len(ge2_evaluable):,} stays with two or "
        f"more evaluable episodes ({100 * len(mixed) / max(len(ge2_evaluable), 1):.1f}%)"
    )
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
