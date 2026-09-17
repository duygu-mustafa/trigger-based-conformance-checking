"""Episode-level characterisation: segmentation, SBT coverage, outcomes, censoring.

Reads the per-episode conformance results (one row per trigger episode) and reports
how many episodes each stay produced, how long they are, how many contain an SBT
attempt, how outcomes are distributed, and how much censoring the inter-episode
outcome introduces.

Usage:
    python case_study/02_episode_stats.py
"""

from __future__ import annotations

import time

import matplotlib.pyplot as plt
import pandas as pd

from config import EPISODE_RESULTS, quantile_summary, save_fig, write_csv, write_json
from derive.statistical_analysis import _binarize_label

USECOLS = [
    "stay_id",
    "episode_index",
    "episode_start",
    "episode_end",
    "ventilation_start",
    "ventilation_end",
    "sbt_attempt",
    "sbt_start",
    "sbt_end",
    "sbt_outcome",
    "next_sbt_outcome",
    "num_mandatory_violations",
    "num_mandatory_satisfactions",
]


def classify_outcome(value) -> str:
    """Human-readable outcome class, consistent with `_binarize_label`."""
    if pd.isnull(value) or str(value).strip() == "":
        return "no evaluable outcome"
    label = str(value)
    low = label.lower()
    if "success" in low:
        return "success (right-censored)" if "censor" in low else "success"
    if "failure" in low:
        return "failure"
    return "no evaluable outcome"


def hours(end: pd.Series, start: pd.Series) -> pd.Series:
    return (
        pd.to_datetime(end, errors="coerce") - pd.to_datetime(start, errors="coerce")
    ).dt.total_seconds() / 3600.0


def main() -> None:
    t0 = time.time()
    df = pd.read_csv(EPISODE_RESULTS, usecols=USECOLS, low_memory=False)
    print(f"Loaded {len(df):,} episodes from {EPISODE_RESULTS.name}")

    df["episode_duration_h"] = hours(df["episode_end"], df["episode_start"])
    df["ventilation_duration_h"] = hours(df["ventilation_end"], df["ventilation_start"])
    df["sbt_duration_h"] = hours(df["sbt_end"], df["sbt_start"])
    df["has_sbt"] = df["sbt_attempt"].notna() & (df["sbt_attempt"].astype(str) != "")
    df["outcome_class"] = df["sbt_outcome"].apply(classify_outcome)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)

    # ---- episodes per stay ----------------------------------------------
    per_stay = df.groupby("stay_id").agg(
        n_episodes=("episode_index", "count"),
        n_sbt_episodes=("has_sbt", "sum"),
    )
    ep_dist = (
        per_stay["n_episodes"].value_counts().sort_index().rename("n_stays").reset_index()
    )
    ep_dist.columns = ["episodes_in_stay", "n_stays"]
    ep_dist["share_of_stays"] = ep_dist["n_stays"] / len(per_stay)
    write_csv(ep_dist, "episodes_per_stay.csv")

    # ---- durations -------------------------------------------------------
    durations = pd.DataFrame(
        [
            quantile_summary(df["episode_duration_h"], "episode_duration_hours"),
            quantile_summary(df["ventilation_duration_h"], "ventilation_duration_hours"),
            # sbt_start -> sbt_end spans the post-SBT outcome-observation window
            # (capped at 48 h and equal to episode_end whenever the episode failed),
            # not the duration of the breathing trial itself.
            quantile_summary(
                df.loc[df["has_sbt"], "sbt_duration_h"], "sbt_observation_window_hours"
            ),
            quantile_summary(per_stay["n_episodes"], "episodes_per_stay"),
            quantile_summary(per_stay["n_sbt_episodes"], "sbt_episodes_per_stay"),
        ]
    )
    write_csv(durations, "episode_durations.csv")

    # ---- outcomes --------------------------------------------------------
    outcome = (
        df["outcome_class"].value_counts().rename("n_episodes").reset_index()
    )
    outcome.columns = ["outcome_class", "n_episodes"]
    outcome["share_of_episodes"] = outcome["n_episodes"] / len(df)
    sbt_only = df[df["has_sbt"]]
    outcome["share_of_sbt_episodes"] = outcome["outcome_class"].map(
        sbt_only["outcome_class"].value_counts() / max(len(sbt_only), 1)
    )
    write_csv(outcome, "outcome_distribution.csv")

    # outcome by episode position (1, 2, 3+)
    df["episode_position"] = df["episode_index"].clip(upper=3).map({1: "1", 2: "2", 3: "3+"})
    by_pos = (
        df.groupby(["episode_position", "outcome_class"]).size().unstack(fill_value=0)
    )
    by_pos_share = by_pos.div(by_pos.sum(axis=1), axis=0)
    write_csv(by_pos.reset_index(), "outcome_by_episode_position.csv")

    # ---- violations per episode -----------------------------------------
    viol = pd.DataFrame(
        [
            quantile_summary(df["num_mandatory_violations"], "mandatory_violations_per_episode"),
            quantile_summary(
                df["num_mandatory_satisfactions"], "mandatory_satisfactions_per_episode"
            ),
            quantile_summary(
                df.loc[df["has_sbt"], "num_mandatory_violations"],
                "mandatory_violations_per_sbt_episode",
            ),
        ]
    )
    write_csv(viol, "violations_per_episode.csv")

    viol_hist = (
        df["num_mandatory_violations"].value_counts().sort_index().rename("n_episodes").reset_index()
    )
    viol_hist.columns = ["n_mandatory_violations", "n_episodes"]
    viol_hist["share"] = viol_hist["n_episodes"] / len(df)
    write_csv(viol_hist, "violations_per_episode_histogram.csv")

    # ---- overview --------------------------------------------------------
    n_sbt = int(df["has_sbt"].sum())
    overview = {
        "source": str(EPISODE_RESULTS),
        "n_episodes": int(len(df)),
        "n_stays": int(per_stay.shape[0]),
        "episodes_per_stay_mean": float(per_stay["n_episodes"].mean()),
        "episodes_per_stay_median": float(per_stay["n_episodes"].median()),
        "episodes_per_stay_max": int(per_stay["n_episodes"].max()),
        "n_stays_single_episode": int((per_stay["n_episodes"] == 1).sum()),
        "share_stays_single_episode": float((per_stay["n_episodes"] == 1).mean()),
        "n_episodes_with_sbt": n_sbt,
        "share_episodes_with_sbt": n_sbt / len(df),
        "n_stays_with_sbt": int((per_stay["n_sbt_episodes"] > 0).sum()),
        "n_episodes_evaluable_outcome": int(df["outcome_binary"].notna().sum()),
        "n_episodes_success": int((df["outcome_binary"] == 1).sum()),
        "n_episodes_failure": int((df["outcome_binary"] == 0).sum()),
        "failure_rate_evaluable": float(
            (df["outcome_binary"] == 0).sum() / max(df["outcome_binary"].notna().sum(), 1)
        ),
        "n_right_censored_success": int(
            (df["outcome_class"] == "success (right-censored)").sum()
        ),
        "n_episodes_with_next_outcome": int(df["next_outcome_binary"].notna().sum()),
        "share_censored_for_inter_episode": float(
            1 - df["next_outcome_binary"].notna().sum() / len(df)
        ),
    }
    write_json(overview, "episode_overview.json")

    # ---- figures ---------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10, 3.8))
    head = ep_dist[ep_dist["episodes_in_stay"] <= 10]
    ax1.bar(head["episodes_in_stay"], head["n_stays"], color="#1f77b4")
    ax1.set_yscale("log")
    ax1.set_xlabel("Episodes per stay")
    ax1.set_ylabel("Stays (log scale)")
    ax1.set_title("Segmentation granularity")
    ax2.hist(
        df["episode_duration_h"].clip(upper=df["episode_duration_h"].quantile(0.99)),
        bins=60,
        color="#ff7f0e",
    )
    ax2.set_xlabel("Episode duration (h, 99th-percentile clipped)")
    ax2.set_ylabel("Episodes")
    ax2.set_title("Episode duration")
    save_fig(fig, "fig_episodes_per_stay")

    order = [
        c
        for c in ["success", "success (right-censored)", "failure", "no evaluable outcome"]
        if c in by_pos_share.columns
    ]
    fig, ax = plt.subplots(figsize=(6, 3.8))
    bottom = None
    palette = {
        "success": "#2ca02c",
        "success (right-censored)": "#98df8a",
        "failure": "#d62728",
        "no evaluable outcome": "#c7c7c7",
    }
    for col in order:
        vals = by_pos_share[col].values
        ax.bar(
            by_pos_share.index, vals, bottom=bottom, label=col, color=palette.get(col)
        )
        bottom = vals if bottom is None else bottom + vals
    ax.set_xlabel("Episode index within stay")
    ax.set_ylabel("Share of episodes")
    ax.set_title("Outcome composition by episode position")
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    save_fig(fig, "fig_outcome_distribution")

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
