"""Per-constraint conformance profile: activation, violation and vacuity frequencies.

Explodes the semicolon-separated constraint lists of the per-episode results into
long form and reports, for every constraint, how often it was activated, violated,
satisfied or vacuous, split by the episode's SBT outcome.

Usage:
    python case_study/03_violation_frequency.py
"""

from __future__ import annotations

import argparse
import time

import matplotlib.pyplot as plt
import pandas as pd

from config import (
    EPISODE_RESULTS,
    OUT_DIR,
    STATE_COLUMNS,
    explode_states,
    load_constraint_meta,
    save_fig,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label


def _plot_violation_rates(out: pd.DataFrame) -> None:
    plot_df = out.dropna(subset=["rate_diff"]).sort_values("rate_diff")
    fig, ax = plt.subplots(figsize=(7.5, max(3.5, 0.32 * len(plot_df))))
    y = range(len(plot_df))
    ax.barh([i - 0.2 for i in y], plot_df["violation_rate_success"], height=0.4,
            color="#0072B2", label="episodes ending in success")
    ax.barh([i + 0.2 for i in y], plot_df["violation_rate_failure"], height=0.4,
            color="#E69F00", label="episodes ending in failure")
    ax.set_yticks(list(y))
    ax.set_yticklabels(
        [
            f"{cid} *" if ent else cid
            for cid, ent in zip(plot_df["constraint_id"], plot_df["outcome_entangled"])
        ]
    )
    ax.set_xlim(0, 1.05)
    ax.set_xlabel("Violation rate among activations  (* = activations confined to one arm)")
    ax.set_title("Violation rate by episode outcome")
    ax.legend(fontsize=8, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    save_fig(fig, "fig_violation_rates")


def _plot_activation_coverage(out: pd.DataFrame) -> None:
    cov = out[out["n_observed"] > 0].sort_values("activation_rate")
    fig, ax = plt.subplots(figsize=(7.5, max(3.5, 0.3 * len(cov))))
    shares = cov[["n_violated", "n_satisfied", "n_vacuous"]].div(cov["n_observed"], axis=0)
    left = None
    for col, color, lab in [
        ("n_violated", "#d62728", "violated"),
        ("n_satisfied", "#2ca02c", "satisfied"),
        ("n_vacuous", "#c7c7c7", "vacuous"),
    ]:
        ax.barh(cov["constraint_id"], shares[col], left=left, color=color, label=lab)
        left = shares[col] if left is None else left + shares[col]
    ax.set_xlabel("Share of episodes where the constraint was evaluated")
    ax.set_title("Activation coverage and vacuity per constraint")
    ax.legend(fontsize=8, loc="lower right")
    save_fig(fig, "fig_activation_coverage")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replot", action="store_true",
        help="Regenerate figures from the cached CSV only, without recomputing.",
    )
    args = parser.parse_args()

    if args.replot:
        out = pd.read_csv(OUT_DIR / "violation_frequency.csv")
        _plot_violation_rates(out)
        _plot_activation_coverage(out)
        return

    t0 = time.time()
    usecols = [
        "stay_id", "episode_index", "sbt_attempt", "sbt_outcome", "next_sbt_outcome",
        *STATE_COLUMNS.values(),
    ]
    df = pd.read_csv(EPISODE_RESULTS, usecols=usecols, low_memory=False)
    df["has_sbt"] = df["sbt_attempt"].notna() & (df["sbt_attempt"].astype(str) != "")
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)
    n_episodes = len(df)
    n_sbt_episodes = int(df["has_sbt"].sum())
    print(f"Loaded {n_episodes:,} episodes ({n_sbt_episodes:,} with an SBT attempt)")

    long = explode_states(df)
    print(f"Exploded to {len(long):,} (episode, constraint) observations")

    # one severity per constraint (constraints appear in exactly one severity list)
    severity = (
        long.groupby("constraint_id")["severity"]
        .agg(lambda s: s.mode().iat[0])
        .rename("severity")
    )

    counts = (
        long.pivot_table(
            index="constraint_id", columns="state", values="episode_index", aggfunc="count"
        )
        .fillna(0)
        .astype(int)
    )
    for col in ("violated", "satisfied", "vacuous"):
        if col not in counts.columns:
            counts[col] = 0
    counts = counts.rename(
        columns={"violated": "n_violated", "satisfied": "n_satisfied", "vacuous": "n_vacuous"}
    )[["n_violated", "n_satisfied", "n_vacuous"]]

    # Outcome split. Rules flagged `outcome_scope: next_episode` activate on
    # SBTFailed, so the same-episode outcome is definitionally failure for every
    # activation (circular). Those are split by the *next* episode's outcome instead,
    # mirroring the contingency tables in derive/statistical_analysis.py.
    meta = load_constraint_meta()
    scope = dict(zip(meta["constraint_id"], meta["outcome_scope"]))

    def outcome_split(outcome_col: str) -> pd.DataFrame:
        evaluable = long[long[outcome_col].notna()]
        split = (
            evaluable[evaluable["state"].isin(["violated", "satisfied"])]
            .assign(is_violation=lambda d: (d["state"] == "violated").astype(int))
            .groupby(["constraint_id", outcome_col])["is_violation"]
            .agg(["sum", "count"])
            .unstack(fill_value=0)
        )
        split.columns = [f"{a}_{int(b)}" for a, b in split.columns]
        return split.rename(
            columns={
                "sum_1": "n_violated_success",
                "count_1": "n_activated_success",
                "sum_0": "n_violated_failure",
                "count_0": "n_activated_failure",
            }
        )

    same_split = outcome_split("outcome_binary")
    next_split = outcome_split("next_outcome_binary")
    same_ids = [c for c in counts.index if scope.get(c, "same_episode") != "next_episode"]
    next_ids = [c for c in counts.index if scope.get(c, "same_episode") == "next_episode"]
    split = pd.concat(
        [
            same_split.reindex(same_ids).assign(outcome_used="same episode"),
            next_split.reindex(next_ids).assign(outcome_used="next episode"),
        ]
    )

    out = counts.join(severity).join(split, how="left")
    out["outcome_used"] = out["outcome_used"].fillna("same episode")
    count_cols = [c for c in out.columns if c.startswith("n_")]
    out[count_cols] = out[count_cols].fillna(0).astype(int)
    out = out.reset_index()
    out = meta.merge(out, on="constraint_id", how="outer")
    out["label"] = out["label"].fillna(out["constraint_id"])
    out["model_group"] = out["model_group"].fillna("Composite / derived")
    out["outcome_scope"] = out["outcome_scope"].fillna("same_episode")

    out["n_episodes"] = n_episodes
    out["n_observed"] = out["n_violated"] + out["n_satisfied"] + out["n_vacuous"]
    out["n_activated"] = out["n_violated"] + out["n_satisfied"]
    out["activation_rate"] = out["n_activated"] / out["n_observed"].replace(0, pd.NA)
    out["violation_rate_activated"] = out["n_violated"] / out["n_activated"].replace(0, pd.NA)
    out["violation_rate_all"] = out["n_violated"] / out["n_observed"].replace(0, pd.NA)
    out["vacuity_rate"] = out["n_vacuous"] / out["n_observed"].replace(0, pd.NA)
    out["violation_rate_success"] = out["n_violated_success"] / out[
        "n_activated_success"
    ].replace(0, pd.NA)
    out["violation_rate_failure"] = out["n_violated_failure"] / out[
        "n_activated_failure"
    ].replace(0, pd.NA)
    out["rate_diff"] = out["violation_rate_failure"] - out["violation_rate_success"]
    # Activation confined to one outcome arm: the constraint's trigger and the
    # outcome label are entangled, so any association estimate is degenerate.
    out["outcome_entangled"] = (out["n_activated_success"] == 0) | (
        out["n_activated_failure"] == 0
    )

    cols = [
        "constraint_id", "label", "model_group", "template", "severity",
        "outcome_scope", "outcome_used",
        "n_episodes", "n_observed", "n_violated", "n_satisfied", "n_vacuous", "n_activated",
        "activation_rate", "violation_rate_activated", "violation_rate_all", "vacuity_rate",
        "n_activated_success", "n_violated_success", "violation_rate_success",
        "n_activated_failure", "n_violated_failure", "violation_rate_failure", "rate_diff",
        "outcome_entangled",
    ]
    out = out[cols].sort_values(
        ["model_group", "violation_rate_activated"], ascending=[True, False]
    )
    write_csv(out, "violation_frequency.csv")

    by_group = (
        out.groupby("model_group")
        .agg(
            n_constraints=("constraint_id", "count"),
            n_violated=("n_violated", "sum"),
            n_satisfied=("n_satisfied", "sum"),
            n_vacuous=("n_vacuous", "sum"),
        )
        .reset_index()
    )
    by_group["violation_rate_activated"] = by_group["n_violated"] / (
        by_group["n_violated"] + by_group["n_satisfied"]
    )
    by_group["vacuity_rate"] = by_group["n_vacuous"] / (
        by_group["n_violated"] + by_group["n_satisfied"] + by_group["n_vacuous"]
    )
    write_csv(by_group, "violation_frequency_by_group.csv")

    # sanity: no constraint may be observed more often than there are episodes
    over = out[out["n_observed"] > n_episodes]
    check = {
        "n_constraints": int(len(out)),
        "n_constraints_in_config": int(len(meta)),
        "n_constraints_not_in_config": sorted(
            set(out["constraint_id"]) - set(meta["constraint_id"])
        ),
        "n_constraints_never_observed": sorted(
            out.loc[out["n_observed"] == 0, "constraint_id"]
        ),
        "consistency_n_observed_le_n_episodes": bool(over.empty),
        "n_episodes": n_episodes,
        "n_sbt_episodes": n_sbt_episodes,
        "mean_violation_rate_activated": float(out["violation_rate_activated"].mean()),
    }
    write_json(check, "violation_frequency_check.json")
    print(
        "CHECK n_observed <= n_episodes: "
        + ("PASS" if over.empty else f"FAIL ({list(over['constraint_id'])})")
    )

    # ---- figures ---------------------------------------------------------
    _plot_violation_rates(out)
    _plot_activation_coverage(out)

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
