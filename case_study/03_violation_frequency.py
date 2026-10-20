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
import numpy as np
import pandas as pd

from config import (
    EPISODE_RESULTS,
    FIG_WIDTH,
    OUT_DIR,
    CONSTRAINT_NAME,
    OUTCOME_COLOR,
    STATE_COLUMNS,
    constraint_label,
    explode_states,
    load_constraint_meta,
    save_fig,
    top_legend,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label


# Constraint families in the order of the thesis table, keyed by ID prefix.
FAMILIES = [("RC-", "Readiness"), ("SBT-", "Trial timing"), ("INT-", "Failure management")]
TABLE_ORDER = {cid: i for i, cid in enumerate(CONSTRAINT_NAME)}


def _plot_violation_rates(out: pd.DataFrame) -> None:
    """Two dots per constraint, one per outcome arm, joined by a line.

    The gap between the dots is the quantity the text discusses, so it is drawn
    rather than left to be read off two bars. Rows alternate in shading, as in the
    cause association figure; families are separated by a thin rule and named,
    rotated, to the left of the constraint labels.
    """
    plot_df = out.dropna(subset=["violation_rate_success", "violation_rate_failure"])
    rows: list[tuple[str, float, float]] = []
    bands: list[tuple[float, float, str]] = []
    y = 0.0
    for prefix, family in FAMILIES:
        members = plot_df[plot_df["constraint_id"].str.startswith(prefix)]
        # The order of the thesis constraint table.
        members = members.sort_values(
            "constraint_id", key=lambda ids: ids.map(TABLE_ORDER.get)
        )
        if members.empty:
            continue
        top = y
        for row in members.itertuples(index=False):
            rows.append((row.constraint_id, y, row.violation_rate_success,
                         row.violation_rate_failure))
            y += 1.0
        bands.append((top, y - 1.0, family))

    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 0.6 + 0.2 * y))
    # Shading restarts in every family, so each family opens with a shaded row.
    for top, bottom, _ in bands:
        for yy in np.arange(top, bottom + 1.0, 2.0):
            ax.axhspan(yy - 0.5, yy + 0.5, color="#f0f0f0", zorder=0, linewidth=0)
    for cid, yy, success, failure in rows:
        ax.plot([success, failure], [yy, yy], color="#bdbdbd", linewidth=1.5, zorder=1)
    ys = [r[1] for r in rows]
    ax.scatter([r[2] for r in rows], ys, color=OUTCOME_COLOR["success"], s=22, zorder=2,
               label="reference episode succeeded")
    ax.scatter([r[3] for r in rows], ys, color=OUTCOME_COLOR["failure"], s=22, zorder=2,
               label="reference episode failed")
    ax.set_yticks(ys)
    ax.set_yticklabels([constraint_label(r[0]) for r in rows])
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="y", visible=False)
    ax.set_ylim(y - 0.5, -0.5)
    ax.set_xlim(0, 1.02)
    ax.set_xlabel("Violation rate among activations")

    # Family names sit left of the constraint labels, so measure those first.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_width = max(t.get_window_extent(renderer).width for t in ax.get_yticklabels())
    label_width *= 72 / fig.dpi  # pixels to points
    family_x = -(label_width + 10)
    for k, (top, bottom, family) in enumerate(bands):
        ax.annotate(family, xy=(0, (top + bottom) / 2), xycoords=("axes fraction", "data"),
                    xytext=(family_x, 0), textcoords="offset points", rotation=90,
                    ha="center", va="center", fontsize=7.5, style="italic")
        if k > 0:
            # Thin rule between families, across the plot and the label column.
            ax.axhline(top - 0.5, color="black", linewidth=0.6, zorder=3)
            ax.annotate("", xy=(0, top - 0.5), xycoords=("axes fraction", "data"),
                        xytext=(family_x - 6, 0), textcoords="offset points",
                        arrowprops={"arrowstyle": "-", "color": "black", "linewidth": 0.6,
                                    "shrinkA": 0, "shrinkB": 0})
    top_legend(ax)
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
