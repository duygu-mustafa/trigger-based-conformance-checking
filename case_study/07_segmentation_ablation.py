"""What episode-local evaluation buys, measured against a trace-global ablation.

Compares the episode-level verdicts (baseline, `trigger_results_full.csv`) against a
no-segmentation run of the same stays (one evaluation trace per stay, produced by
`main_per_sbt.py --no-segmentation`) on three axes per constraint:

  * masking     — flagged at episode level, not flagged at trace level (a violation
                   in one trial discharged/hidden by pooling all trials into one trace)
  * trace-only   — flagged at trace level, not at episode level (a violation invented
                   by pooling, which no individual trial committed)
  * activation   — activations lost to merged vacuity when episodes are pooled
  * localization — how many episodes/trials a clinician would have to inspect to find
                   the deviation a trace-level verdict reports

Usage:
    python case_study/07_segmentation_ablation.py --ablation out/ablation_no_segmentation_sample2000.csv
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from config import (
    EPISODE_RESULTS,
    ROOT,
    STATE_COLUMNS,
    explode_states,
    load_constraint_meta,
    save_fig,
    write_csv,
    write_json,
)
from derive.statistical_analysis import _binarize_label

NOT_COMPARABLE = {
    "INT-COMPOSITE-01": "activates only for attempt_index > 1, which never occurs "
                         "under a single whole-stay trace",
}


def load_level(path, usecols) -> pd.DataFrame:
    df = pd.read_csv(path, usecols=usecols, low_memory=False)
    df["outcome_binary"] = df["sbt_outcome"].apply(_binarize_label)
    if "next_sbt_outcome" in df.columns:
        df["next_outcome_binary"] = df["next_sbt_outcome"].apply(_binarize_label)
    else:
        df["next_outcome_binary"] = pd.NA
    return df


def stay_level_flags(df: pd.DataFrame) -> pd.DataFrame:
    """Per (stay, constraint): violated/vacuous at least once, satisfied-only otherwise."""
    long = explode_states(df)
    flags = (
        long.groupby(["stay_id", "constraint_id"])["state"]
        .agg(lambda s: "violated" if "violated" in set(s) else (
            "vacuous" if set(s) == {"vacuous"} else "satisfied"
        ))
        .rename("flag")
        .reset_index()
    )
    n_activations = (
        long[long["state"].isin(["violated", "satisfied"])]
        .groupby(["stay_id", "constraint_id"])
        .size()
        .rename("n_activations")
        .reset_index()
    )
    return flags.merge(n_activations, on=["stay_id", "constraint_id"], how="left").fillna(
        {"n_activations": 0}
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ablation", type=str, required=True,
                        help="Path to the no-segmentation conformance CSV.")
    args = parser.parse_args()
    ablation_path = Path(args.ablation)
    if not ablation_path.is_absolute():
        # Resolve relative to the repository root, since run_ablation.sh invokes this
        # script with a path like "case_study/out/....csv" from the repo root, and a
        # direct manual invocation from within case_study/ would otherwise double the
        # "case_study" segment.
        candidate = ROOT / ablation_path
        if not candidate.exists() and (Path.cwd() / ablation_path).exists():
            candidate = Path.cwd() / ablation_path
        ablation_path = candidate

    t0 = time.time()
    usecols = [
        "stay_id", "episode_index", "sbt_outcome", "next_sbt_outcome",
        *STATE_COLUMNS.values(),
    ]
    trace = load_level(ablation_path, usecols)
    stay_ids = sorted(trace["stay_id"].astype(str).unique())
    print(f"Ablation covers {len(stay_ids):,} stays, loaded from {ablation_path}")

    episode = load_level(EPISODE_RESULTS, usecols)
    episode = episode[episode["stay_id"].astype(str).isin(stay_ids)]
    print(f"Baseline restricted to the same stays: {episode['stay_id'].nunique():,} stays, "
          f"{len(episode):,} episodes")

    ep_flags = stay_level_flags(episode).rename(
        columns={"flag": "flag_episode", "n_activations": "n_activations_episode"}
    )
    tr_flags = stay_level_flags(trace).rename(
        columns={"flag": "flag_trace", "n_activations": "n_activations_trace"}
    )
    joined = ep_flags.merge(tr_flags, on=["stay_id", "constraint_id"], how="outer")
    for col in ("flag_episode", "flag_trace"):
        joined[col] = joined[col].fillna("not_observed")
    joined[["n_activations_episode", "n_activations_trace"]] = joined[
        ["n_activations_episode", "n_activations_trace"]
    ].fillna(0)

    # episodes-per-stay, for the localization metric, restricted to stays with a trial
    ep_counts = (
        episode.groupby("stay_id")
        .agg(n_episodes=("episode_index", "count"),
             n_trial_episodes=("sbt_outcome", lambda s: s.notna().sum()))
    )
    joined = joined.merge(ep_counts, on="stay_id", how="left")

    rows = []
    for cid, g in joined.groupby("constraint_id"):
        n_stays = g["stay_id"].nunique()
        ep_violated = set(g.loc[g["flag_episode"] == "violated", "stay_id"])
        tr_violated = set(g.loc[g["flag_trace"] == "violated", "stay_id"])
        ep_vacuous = set(g.loc[g["flag_episode"] == "vacuous", "stay_id"])
        tr_vacuous = set(g.loc[g["flag_trace"] == "vacuous", "stay_id"])

        masked = ep_violated - tr_violated
        trace_only = tr_violated - ep_violated
        both = ep_violated & tr_violated

        n_act_episode = g["n_activations_episode"].sum()
        n_act_trace = g["n_activations_trace"].sum()

        loc = g[g["stay_id"].isin(tr_violated)]
        rows.append(
            {
                "constraint_id": cid,
                "n_stays": n_stays,
                "not_comparable": cid in NOT_COMPARABLE,
                "not_comparable_reason": NOT_COMPARABLE.get(cid, ""),
                "stays_flagged_episode_level": len(ep_violated),
                "stays_flagged_trace_level": len(tr_violated),
                "stays_flagged_both": len(both),
                "masked_stays": len(masked),
                "masking_rate": len(masked) / len(ep_violated) if ep_violated else None,
                "trace_only_stays": len(trace_only),
                "trace_only_rate": len(trace_only) / len(tr_violated) if tr_violated else None,
                "activations_episode_level": int(n_act_episode),
                "activations_trace_level": int(n_act_trace),
                "activation_loss": int(n_act_episode - n_act_trace),
                "activation_loss_rate": (
                    (n_act_episode - n_act_trace) / n_act_episode if n_act_episode else None
                ),
                "vacuity_rate_episode_level": len(ep_vacuous) / n_stays if n_stays else None,
                "vacuity_rate_trace_level": len(tr_vacuous) / n_stays if n_stays else None,
                "mean_episodes_per_flagged_stay": (
                    loc["n_episodes"].mean() if len(loc) else None
                ),
                "mean_trial_episodes_per_flagged_stay": (
                    loc["n_trial_episodes"].mean() if len(loc) else None
                ),
            }
        )

    out = pd.DataFrame(rows)
    meta = load_constraint_meta()[["constraint_id", "label", "model_group"]]
    out = meta.merge(out, on="constraint_id", how="right")
    out = out.sort_values("masking_rate", ascending=False)
    write_csv(out, "ablation_by_constraint.csv")

    comparable = out[~out["not_comparable"]]

    # Stay-level disagreement, restricted to the comparable constraints and to the
    # violated verdict itself. `n_stays_any_constraint_disagrees` below is the looser
    # quantity: it spans every constraint and counts a satisfied -> vacuous transition
    # as a disagreement, which is not what the case study reports.
    cmp_join = joined[~joined["constraint_id"].isin(NOT_COMPARABLE)].copy()
    for level in ("episode", "trace"):
        cmp_join[f"violated_{level}"] = cmp_join[f"flag_{level}"] == "violated"
    verdict_disagrees = cmp_join.loc[
        cmp_join["violated_episode"] != cmp_join["violated_trace"], "stay_id"
    ].nunique()

    activation_loss = comparable["activation_loss_rate"].dropna()
    overview = {
        "ablation_source": str(ablation_path),
        "n_stays_compared": int(len(stay_ids)),
        "n_constraints": int(len(out)),
        "n_constraints_not_comparable": int(out["not_comparable"].sum()),
        "not_comparable_constraints": {
            k: v for k, v in NOT_COMPARABLE.items() if k in set(out["constraint_id"])
        },
        "total_violations_episode_level": int(
            comparable["stays_flagged_episode_level"].sum()
        ),
        "total_violations_trace_level": int(comparable["stays_flagged_trace_level"].sum()),
        "total_masked_stays": int(comparable["masked_stays"].sum()),
        "overall_masking_rate": (
            comparable["masked_stays"].sum() / comparable["stays_flagged_episode_level"].sum()
            if comparable["stays_flagged_episode_level"].sum() else None
        ),
        "total_trace_only_stays": int(comparable["trace_only_stays"].sum()),
        "overall_trace_only_rate": (
            comparable["trace_only_stays"].sum() / comparable["stays_flagged_trace_level"].sum()
            if comparable["stays_flagged_trace_level"].sum() else None
        ),
        "n_stays_any_constraint_disagrees": int(
            joined.loc[
                joined["flag_episode"] != joined["flag_trace"], "stay_id"
            ].nunique()
        ),
        "n_stays_violation_verdict_disagrees": int(verdict_disagrees),
        "mean_activation_loss_rate": float(activation_loss.mean()),
        "median_activation_loss_rate": float(activation_loss.median()),
        "min_activation_loss_rate": float(activation_loss.min()),
        "max_activation_loss_rate": float(activation_loss.max()),
    }
    write_json(overview, "ablation_overview.json")

    # ---- cross-check: episode-level stay counts vs a direct groupby of baseline ---
    long_ep = explode_states(episode)
    direct_counts = (
        long_ep[long_ep["state"] == "violated"]
        .groupby("constraint_id")["stay_id"]
        .nunique()
    )
    mismatch = []
    for _, r in out.iterrows():
        expected = int(direct_counts.get(r["constraint_id"], 0))
        if expected != r["stays_flagged_episode_level"]:
            mismatch.append((r["constraint_id"], expected, r["stays_flagged_episode_level"]))
    consistency_status = "PASS" if not mismatch else "FAIL"
    print(f"CONSISTENCY CHECK (episode-level stay counts vs direct groupby): "
          f"{consistency_status}" + (f" mismatches={mismatch}" if mismatch else ""))

    over_total = out[out["masked_stays"] + out["trace_only_stays"] > out["n_stays"]]
    bound_status = "PASS" if over_total.empty else "FAIL"
    print(f"BOUND CHECK (masked + trace_only <= n_stays): {bound_status}"
          + (f" violations={list(over_total['constraint_id'])}" if not over_total.empty else ""))

    # ---- figures ---------------------------------------------------------
    plot_df = comparable.dropna(subset=["masking_rate"]).copy()
    plot_df["total_disagreement"] = plot_df["masked_stays"] + plot_df["trace_only_stays"]
    plot_df = plot_df.sort_values("total_disagreement")
    if not plot_df.empty:
        fig, ax = plt.subplots(figsize=(7.5, max(3.5, 0.35 * len(plot_df))))
        y = range(len(plot_df))
        ax.barh(y, plot_df["stays_flagged_episode_level"], color="#d62728", alpha=0.5,
                label="flagged at episode level")
        ax.barh(y, plot_df["stays_flagged_trace_level"], color="#1f77b4", alpha=0.7,
                label="flagged at trace level")
        ax.set_yticks(list(y))
        ax.set_yticklabels(plot_df["constraint_id"])
        ax.set_xlabel("Stays flagged violated")
        ax.set_title("Verdict relocation under trace-global evaluation")
        ax.legend(fontsize=8, loc="lower right")
        save_fig(fig, "fig_ablation_masking")

        fig, ax = plt.subplots(figsize=(5.5, 5))
        ax.scatter(plot_df["activations_episode_level"] + 1,
                   plot_df["activations_trace_level"] + 1, s=30, color="#1f77b4")
        for _, r in plot_df.iterrows():
            ax.annotate(r["constraint_id"],
                        (r["activations_episode_level"] + 1, r["activations_trace_level"] + 1),
                        fontsize=6, xytext=(3, 3), textcoords="offset points")
        lims = [1, max(plot_df["activations_episode_level"].max(),
                       plot_df["activations_trace_level"].max()) * 2]
        ax.plot(lims, lims, color="black", lw=0.8, ls="--")
        ax.set_xscale("log")
        ax.set_yscale("log")
        ax.set_xlabel("Activations, episode level (+1)")
        ax.set_ylabel("Activations, trace level (+1)")
        ax.set_title("Activation loss under pooling")
        save_fig(fig, "fig_ablation_activations")

    print(f"Done in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
