"""Deviation patterns: which constraints are violated together, and when.

Step 03 reports each constraint on its own. Two things are invisible in that view
and are only available once verdicts are localized to a trial.

Co-violation: episodes are not violated at random across the model. A stay whose
charting is thin fails several readiness criteria at once, whereas an episode that
fails a single criterion with the rest documented and met is a deliberate,
isolated departure. The conditional violation matrix separates the two.

Attempt position: a deviation at the first weaning attempt and one at the fifth
have different readings, since later attempts select for patients who are harder
to liberate. Violation rate by attempt index shows where in a stay each
obligation actually goes unmet.

Usage:
    python case_study/09_deviation_patterns.py
"""

from __future__ import annotations

import argparse
import time

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    EPISODE_RESULTS,
    FIG_WIDTH,
    OUT_DIR,
    STATE_COLUMNS,
    constraint_label,
    explode_states,
    load_constraint_meta,
    save_fig,
    top_legend,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label, calculate_stats

READINESS_PREFIX = "RC-DP-"
# RC-DP-06 is violated in 99.9% of its activations and is already excluded from
# interpretation elsewhere in the results. Left in, it would appear in nearly every
# profile and swamp the co-violation structure of the criteria that discriminate.
SATURATED = {"RC-DP-06"}
# Beyond this the per-attempt strata get too thin to read, so they are pooled.
MAX_ATTEMPT_BUCKET = 5
TOP_PROFILES = 15


def _readiness(long: pd.DataFrame) -> pd.DataFrame:
    """Readiness rows, minus the constraint that is saturated by construction."""
    is_readiness = long["constraint_id"].str.startswith(READINESS_PREFIX)
    return long[is_readiness & ~long["constraint_id"].isin(SATURATED)]


def _profiles(long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Frequency of readiness violation profiles, and their size distribution."""
    readiness = _readiness(long)
    activated = readiness[readiness["state"].isin(["violated", "satisfied"])]

    per_episode = (
        activated.assign(violated=activated["state"] == "violated")
        .groupby(["stay_id", "episode_index"])
        .agg(
            n_activated=("violated", "size"),
            n_violated=("violated", "sum"),
            profile=("constraint_id", lambda s: ""),
        )
    )
    violated_only = activated[activated["state"] == "violated"]
    profile = (
        violated_only.groupby(["stay_id", "episode_index"])["constraint_id"]
        .agg(lambda s: "+".join(sorted(set(s))))
        .rename("profile")
    )
    per_episode = per_episode.drop(columns=["profile"]).join(profile)
    per_episode["profile"] = per_episode["profile"].fillna("(none)")

    counts = (
        per_episode.groupby("profile")
        .agg(n_episodes=("n_violated", "size"), n_violated=("n_violated", "first"))
        .sort_values("n_episodes", ascending=False)
        .reset_index()
    )
    counts["n_criteria"] = counts["profile"].apply(
        lambda p: 0 if p == "(none)" else len(p.split("+"))
    )
    counts["share"] = counts["n_episodes"] / counts["n_episodes"].sum()
    counts = counts.drop(columns=["n_violated"])

    size = (
        per_episode.groupby("n_violated")
        .size()
        .rename("n_episodes")
        .reset_index()
        .sort_values("n_violated")
    )
    size["share"] = size["n_episodes"] / size["n_episodes"].sum()
    return counts, size


def _profile_outcomes(long: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Outcome by how broadly an episode deviates, and by which criterion it was.

    An episode that misses one readiness criterion with the rest documented and met
    is the shape a deliberate, reasoned departure would take. An episode that misses
    four at once is not. Both are compared against episodes that met every criterion,
    so the two readings of a deviation can be told apart.
    """
    readiness = _readiness(long)
    activated = readiness[readiness["state"].isin(["violated", "satisfied"])]
    per_episode = (
        activated.assign(violated=(activated["state"] == "violated").astype(int))
        .groupby(["stay_id", "episode_index"])["violated"]
        .agg(n_violated="sum", n_activated="size")
    )
    only = (
        activated[activated["state"] == "violated"]
        .groupby(["stay_id", "episode_index"])["constraint_id"]
        .agg(lambda s: sorted(set(s))[0] if len(set(s)) == 1 else "")
        .rename("sole_violation")
    )
    per_episode = per_episode.join(only).join(
        outcomes.set_index(["stay_id", "episode_index"])["outcome_binary"]
    )
    per_episode = per_episode[per_episode["outcome_binary"].notna()]

    conformant = per_episode[per_episode["n_violated"] == 0]
    reference_success = int((conformant["outcome_binary"] == 1).sum())
    reference_failure = int((conformant["outcome_binary"] == 0).sum())

    rows: list[dict] = []

    def _arm(label: str, arm: pd.DataFrame, kind: str) -> None:
        a = int((arm["outcome_binary"] == 1).sum())
        b = int((arm["outcome_binary"] == 0).sum())
        if a + b == 0:
            return
        stats = calculate_stats(a, b, reference_success, reference_failure)
        rows.append(
            {
                "kind": kind,
                "arm": label,
                "n_episodes": a + b,
                "success_rate": a / (a + b),
                "reference_success_rate": reference_success
                / max(reference_success + reference_failure, 1),
                "rr_point": stats["rr_point"],
                "rr_ci_low": stats["rr_ci_low"],
                "rr_ci_high": stats["rr_ci_high"],
                "p_raw": stats["p_raw"],
            }
        )

    for n_violated, arm in per_episode.groupby("n_violated"):
        if n_violated == 0:
            continue
        _arm(str(int(n_violated)), arm, "breadth")

    isolated = per_episode[per_episode["sole_violation"].fillna("") != ""]
    for cid, arm in isolated.groupby("sole_violation"):
        _arm(cid, arm, "sole criterion")

    return pd.DataFrame(rows)


def _conditional_matrix(long: pd.DataFrame) -> pd.DataFrame:
    """P(constraint B violated | constraint A violated), over episodes activating both."""
    readiness = _readiness(long)
    activated = readiness[readiness["state"].isin(["violated", "satisfied"])]
    wide = (
        activated.assign(violated=(activated["state"] == "violated").astype(int))
        .pivot_table(
            index=["stay_id", "episode_index"],
            columns="constraint_id",
            values="violated",
            aggfunc="max",
        )
    )
    ids = sorted(wide.columns)
    matrix = pd.DataFrame(index=ids, columns=ids, dtype=float)
    for a in ids:
        given = wide[wide[a] == 1]
        for b in ids:
            both = given[b].dropna()
            matrix.loc[a, b] = float(both.mean()) if len(both) else np.nan
    matrix.index.name = "given_violated"
    return matrix


def _by_attempt(long: pd.DataFrame) -> pd.DataFrame:
    activated = long[long["state"].isin(["violated", "satisfied"])]
    activated = activated[activated["attempt_bucket"].notna()]
    out = (
        activated.assign(violated=(activated["state"] == "violated").astype(int))
        .groupby(["constraint_id", "attempt_bucket"])["violated"]
        .agg(n_activated="size", n_violated="sum")
        .reset_index()
    )
    out["violation_rate"] = out["n_violated"] / out["n_activated"]
    return out


def _plot_profile_sizes(size: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(6.0, 3.2))
    ax.bar(size["n_violated"], size["share"], color="#3182bd")
    ax.set_xlabel("Readiness criteria violated in the episode")
    ax.set_ylabel("Share of episodes")
    save_fig(fig, "fig_readiness_profile_sizes")


def _plot_profile_outcomes(profile_outcomes: pd.DataFrame) -> None:
    breadth = profile_outcomes[profile_outcomes["kind"] == "breadth"].copy()
    if breadth.empty:
        return
    breadth["arm"] = breadth["arm"].astype(int)
    breadth = breadth.sort_values("arm")
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.6))
    err = np.vstack(
        [
            (breadth["rr_point"] - breadth["rr_ci_low"]).to_numpy(dtype=float),
            (breadth["rr_ci_high"] - breadth["rr_point"]).to_numpy(dtype=float),
        ]
    )
    ax.errorbar(breadth["arm"], breadth["rr_point"], yerr=np.abs(err), fmt="o-",
                capsize=3, color="#d62728", markersize=5)
    ax.axhline(1.0, color="black", linewidth=1)
    # The arms shrink with breadth, so each tick carries the size of its arm.
    ax.set_xticks(breadth["arm"])
    ax.set_xticklabels(
        [f"{int(r.arm)}\nn = {int(r.n_episodes):,}".replace(",", "\u2009")
         for r in breadth.itertuples(index=False)]
    )
    ax.grid(axis="x", visible=False)
    ax.set_xlabel("Readiness criteria violated in the episode")
    ax.set_ylabel("Risk ratio of success")
    save_fig(fig, "fig_deviation_breadth_outcome")


def _plot_matrix(matrix: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    data = matrix.to_numpy(dtype=float)
    image = ax.imshow(data, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(matrix.columns)))
    ax.set_xticklabels(matrix.columns, rotation=90, fontsize=7)
    ax.set_yticks(range(len(matrix.index)))
    ax.set_yticklabels(matrix.index, fontsize=7)
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            if not np.isnan(data[i, j]):
                ax.text(j, i, f"{data[i, j]:.2f}", ha="center", va="center", fontsize=6,
                        color="white" if data[i, j] > 0.55 else "black")
    ax.set_xlabel("also violated")
    ax.set_ylabel("given violated")
    ax.set_title("Conditional violation among readiness criteria", fontsize=10)
    ax.grid(False)
    fig.colorbar(image, ax=ax, shrink=0.8)
    save_fig(fig, "fig_readiness_coviolation")


def _plot_by_attempt(by_attempt: pd.DataFrame) -> None:
    readiness = by_attempt[
        by_attempt["constraint_id"].str.startswith(READINESS_PREFIX)
        & ~by_attempt["constraint_id"].isin(SATURATED)
    ]
    if readiness.empty:
        return
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 3.0))
    for cid, arm in readiness.groupby("constraint_id"):
        arm = arm.sort_values("attempt_bucket")
        ax.plot(arm["attempt_bucket"], arm["violation_rate"], marker="o", markersize=4,
                label=constraint_label(cid))
    ax.set_xticks(sorted(readiness["attempt_bucket"].unique()))
    ax.set_xticklabels(
        [
            f"{int(b)}+" if b == MAX_ATTEMPT_BUCKET else str(int(b))
            for b in sorted(readiness["attempt_bucket"].unique())
        ]
    )
    ax.set_ylim(0, 1.02)
    ax.set_xlabel("Weaning attempt within the stay")
    ax.set_ylabel("Violation rate among activations")
    top_legend(ax, ncol=3)
    save_fig(fig, "fig_violation_by_attempt")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--replot", action="store_true",
        help="Regenerate the thesis figures from the cached CSVs only, without recomputing.",
    )
    args = parser.parse_args()

    if args.replot:
        _plot_profile_outcomes(pd.read_csv(OUT_DIR / "deviation_profile_outcomes.csv"))
        _plot_by_attempt(pd.read_csv(OUT_DIR / "violation_by_attempt.csv"))
        return

    t0 = time.time()
    usecols = [
        "stay_id", "episode_index", "sbt_attempt", "sbt_outcome", "next_sbt_outcome",
        *STATE_COLUMNS.values(),
    ]
    df = pd.read_csv(EPISODE_RESULTS, usecols=usecols, low_memory=False)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)
    attempt = pd.to_numeric(df["sbt_attempt"], errors="coerce")
    df["attempt_bucket"] = attempt.clip(upper=MAX_ATTEMPT_BUCKET)
    print(f"Loaded {len(df):,} episodes")

    long = explode_states(df)
    long = long.merge(
        df[["stay_id", "episode_index", "attempt_bucket"]],
        on=["stay_id", "episode_index"],
        how="left",
    )

    profiles, sizes = _profiles(long)
    write_csv(profiles.head(TOP_PROFILES), "deviation_profiles_top.csv")
    write_csv(profiles, "deviation_profiles.csv")
    write_csv(sizes, "deviation_profile_sizes.csv")

    profile_outcomes = _profile_outcomes(
        long, df[["stay_id", "episode_index", "outcome_binary"]]
    )
    write_csv(profile_outcomes, "deviation_profile_outcomes.csv")

    matrix = _conditional_matrix(long)
    write_csv(matrix.reset_index(), "readiness_coviolation_matrix.csv")

    by_attempt = _by_attempt(long)
    write_csv(by_attempt, "violation_by_attempt.csv")

    meta = load_constraint_meta()
    isolated = profiles[profiles["n_criteria"] == 1]
    overview = {
        "n_episodes": int(len(df)),
        "n_constraints_in_config": int(len(meta)),
        "n_distinct_profiles": int(profiles["profile"].nunique()),
        "share_no_readiness_violation": float(
            profiles.loc[profiles["profile"] == "(none)", "share"].sum()
        ),
        "share_single_criterion_profiles": float(isolated["share"].sum()),
        "top_profile": profiles.iloc[0]["profile"] if len(profiles) else None,
        "top_profile_share": float(profiles.iloc[0]["share"]) if len(profiles) else None,
        "mean_criteria_violated": float(
            (sizes["n_violated"] * sizes["n_episodes"]).sum() / sizes["n_episodes"].sum()
        ),
    }
    write_json(overview, "deviation_patterns_overview.json")

    _plot_profile_sizes(sizes)
    _plot_profile_outcomes(profile_outcomes)
    _plot_matrix(matrix)
    _plot_by_attempt(by_attempt)

    print(
        f"{overview['n_distinct_profiles']} distinct readiness violation profiles; "
        f"single-criterion profiles cover {overview['share_single_criterion_profiles']:.1%} "
        "of episodes"
    )
    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
