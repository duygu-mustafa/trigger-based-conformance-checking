"""Thesis versions of the scalability and trigger-sensitivity figures.

Redraws the figures of scalability_analysis.ipynb and trigger_sensitivity.ipynb
in the shared thesis style (text width, serif, legend on top, no titles) from
the cached results, without rerunning any benchmark:

* scalability_{log_size,trace_length,model_size,rule_complexity}.{pdf,png}
  from data/benchmarks/*.csv, with the statistics of the notebook;
* trigger_{coverage,data_loss,granularity,label_validity}.{pdf,png}
  from data/trigger_sensitivity.csv and data/trigger_distributions.npz
  (written by trigger_distributions.py).

Figures land in evaluation/figures; copy the PDFs into the thesis tree.

Usage:
    python evaluation/thesis_figures.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# The thesis figure style lives with the case study; importing it applies the
# shared rcParams.
sys.path.insert(0, str(REPO_ROOT / "case_study"))
sys.path.insert(0, str(REPO_ROOT / "evaluation"))
from config import FIG_WIDTH, OUTCOME_COLOR  # noqa: E402

DATA_DIR = REPO_ROOT / "evaluation" / "data"
BENCH_DIR = DATA_DIR / "benchmarks"
FIG_DIR = REPO_ROOT / "evaluation" / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

MAIN_COLOR = "#0072B2"
SECOND_COLOR = "#E69F00"
FIT_COLOR = "#7a7a7a"
NEUTRAL = "#c7c7c7"
INK = "#4a4a4a"

# As in trigger_sensitivity.ipynb: process start to escalation.
TRIGGER_CANDIDATES = [
    "Create Fine",
    "Send Fine",
    "Insert Fine Notification",
    "Add penalty",
    "Payment",
    "Appeal to Judge",
]


def save_fig(fig, name: str) -> None:
    # Constrained layout keeps a figure drawn at FIG_WIDTH exactly that wide.
    fig.set_layout_engine("constrained")
    for ext in ("pdf", "png"):
        fig.savefig(FIG_DIR / f"{name}.{ext}", dpi=200 if ext == "png" else None)
    plt.close(fig)
    print(f"  figure -> {FIG_DIR / name}.{{pdf,png}}")


def legend_above(ax, **kwargs) -> None:
    """Frameless legend centred above one panel, data before fitted lines."""
    handles, labels = ax.get_legend_handles_labels()
    pairs = sorted(zip(handles, labels), key=lambda hl: hl[1].startswith(("fit", "linear")))
    ax.legend([h for h, _ in pairs], [lab for _, lab in pairs], loc="lower center",
              bbox_to_anchor=(0.5, 1.0), frameon=False, **kwargs)


def quartile_agg(df: pd.DataFrame, by: str, col: str = "wall_s") -> pd.DataFrame:
    return df.groupby(by)[col].agg(
        median="median", q1=lambda s: s.quantile(0.25), q3=lambda s: s.quantile(0.75),
        n="size",
    )


def load_bench(name: str, sample_col: str | None = None) -> pd.DataFrame:
    """Read a benchmark CSV, keeping a single sample size (as in the notebook)."""
    df = pd.read_csv(BENCH_DIR / name)
    if sample_col and sample_col in df.columns and df[sample_col].nunique() > 1:
        df = df[df[sample_col] == df[sample_col].max()]
    return df


# ---------------------------------------------------------------------------
# Scalability (scalability_analysis.ipynb)
# ---------------------------------------------------------------------------

def scalability_figures() -> None:
    e1 = load_bench("e1_log_size.csv")
    e2n = load_bench("e2_trace_length_natural.csv", "n_sample_cases")
    e2s = load_bench("e2_trace_length_synthetic.csv", "n_sample_cases")
    e3 = load_bench("e3_model_size.csv", "n_cases")
    e4 = load_bench("e4_rule_complexity.csv", "n_cases")
    e5 = load_bench("e5_memory.csv")

    # E1 and E5: runtime and memory against log size.
    agg = quartile_agg(e1, "n_cases")
    slope, intercept, r, *_ = stats.linregress(np.log(agg.index), np.log(agg["median"]))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(FIG_WIDTH, 2.6))
    ax1.errorbar(agg.index, agg["median"],
                 yerr=[agg["median"] - agg["q1"], agg["q3"] - agg["median"]],
                 fmt="o-", color=MAIN_COLOR, capsize=3, markersize=4, label="median")
    xs = np.array([agg.index.min(), agg.index.max()])
    ax1.plot(xs, np.exp(intercept) * xs**slope, "--", color=FIT_COLOR,
             label=f"fit $t \\propto n^{{{slope:.2f}}}$ ($R^2$ = {r**2:.3f})")
    ax1.set(xscale="log", yscale="log", xlabel="Cases", ylabel="Wall time [s]")
    legend_above(ax1, ncol=1)
    ax2.plot(e5["n_cases"], e5["tracemalloc_peak_mb"], "s-", color=MAIN_COLOR,
             markersize=4)
    ax2.set(xscale="log", xlabel="Cases", ylabel="Peak memory (tracemalloc) [MB]")
    save_fig(fig, "scalability_log_size")

    # E2: natural and synthetically lengthened traces.
    nat = quartile_agg(e2n, "n_events")
    nat = nat[nat["n"] >= 10]  # drop sparsely populated lengths
    syn = quartile_agg(e2s, "n_events")
    s_slope, s_int, s_r, *_ = stats.linregress(np.log(syn.index), np.log(syn["median"]))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(FIG_WIDTH, 2.6))
    ax1.plot(nat.index, nat["median"] * 1e3, "o-", color=MAIN_COLOR, markersize=4,
             label="median")
    ax1.fill_between(nat.index, nat["q1"] * 1e3, nat["q3"] * 1e3, color=MAIN_COLOR,
                     alpha=0.2, linewidth=0, label="interquartile range")
    ax1.set(xlabel="Events per trace", ylabel="Per-case wall time [ms]")
    legend_above(ax1, ncol=2)
    ax2.errorbar(syn.index, syn["median"],
                 yerr=[syn["median"] - syn["q1"], syn["q3"] - syn["median"]],
                 fmt="o", color=MAIN_COLOR, capsize=3, markersize=4, label="median")
    xs = np.array([syn.index.min(), syn.index.max()])
    ax2.plot(xs, np.exp(s_int) * xs**s_slope, "--", color=FIT_COLOR,
             label=f"fit $t \\propto m^{{{s_slope:.2f}}}$ ($R^2$ = {s_r**2:.3f})")
    ax2.set(xscale="log", yscale="log", xlabel="Events per trace",
            ylabel="Per-trace wall time [s]")
    legend_above(ax2, ncol=1)
    save_fig(fig, "scalability_trace_length")

    # E3: runtime against model size.
    agg3 = quartile_agg(e3, "k_constraints")
    l_slope, l_int, l_r, *_ = stats.linregress(agg3.index, agg3["median"])
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.6))
    ax.errorbar(agg3.index, agg3["median"],
                yerr=[agg3["median"] - agg3["q1"], agg3["q3"] - agg3["median"]],
                fmt="o", color=MAIN_COLOR, capsize=3, markersize=4, label="median")
    ax.plot(agg3.index, l_int + l_slope * agg3.index, "--", color=FIT_COLOR,
            label=f"linear fit, {l_slope:.2f} s per constraint ($R^2$ = {l_r**2:.3f})")
    ax.set(xlabel="Constraints in model", ylabel="Wall time [s]", xticks=agg3.index)
    legend_above(ax, ncol=2)
    save_fig(fig, "scalability_model_size")

    # E4: per-evaluation runtime against the complexity score.
    per_rule = (
        e4.groupby(["model", "rule_id", "template", "w_template", "n_clauses",
                    "n_attributes", "t_time", "complexity"])
        ["mean_us_per_eval"].median().reset_index()
    )
    rho, rho_p = stats.spearmanr(per_rule["complexity"], per_rule["mean_us_per_eval"])
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.8))
    for model_name, marker, color, label in (
        ("rtfm", "o", MAIN_COLOR, "fine log constraints"),
        ("rtfm_synthetic", "^", SECOND_COLOR, "controlled rule variants"),
    ):
        sub = per_rule[per_rule["model"] == model_name]
        ax.scatter(sub["complexity"], sub["mean_us_per_eval"], marker=marker, s=22,
                   color=color, label=label, zorder=2)
    ax.set(xlabel="Complexity score $C(r)$", ylabel="Per-evaluation runtime [µs]")
    ax.text(0.98, 0.05, f"Spearman $\\rho$ = {rho:.2f} ($p$ = {rho_p:.1e})",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=INK)
    legend_above(ax, ncol=2)
    save_fig(fig, "scalability_rule_complexity")


# ---------------------------------------------------------------------------
# Trigger sensitivity (trigger_sensitivity.ipynb)
# ---------------------------------------------------------------------------

def _trigger_axis(ax, order, rotation: int = 30) -> None:
    ax.set_xticks(np.arange(len(order)))
    ax.set_xticklabels(order, rotation=rotation, ha="right", rotation_mode="anchor")
    ax.grid(axis="x", visible=False)


def trigger_figures() -> None:
    metrics = pd.read_csv(DATA_DIR / "trigger_sensitivity.csv", index_col="trigger")
    dist_path = DATA_DIR / "trigger_distributions.npz"
    order = TRIGGER_CANDIDATES
    x = np.arange(len(order))

    # Case coverage.
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.3))
    vals = metrics.loc[order, "case_coverage"] * 100
    ax.barh(order[::-1], vals[::-1], height=0.65, color=MAIN_COLOR)
    for y, v in enumerate(vals[::-1]):
        ax.text(v + 1, y, f"{v:.1f}\u2009%", va="center", fontsize=7.5, color=INK)
    ax.set_xlim(0, 112)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("Cases with at least one trigger occurrence [%]")
    ax.grid(axis="y", visible=False)
    ax.tick_params(axis="y", length=0)
    save_fig(fig, "trigger_coverage")

    # Events never checked: dropped cases plus prefix loss, as shares of all
    # events of the working set (prefix_loss is relative to covered-case events).
    sample_events = _working_set_events()
    covered_events = sample_events - metrics.loc[order, "events_lost_to_dropped_cases"]
    prefix = metrics.loc[order, "prefix_loss"] * covered_events / sample_events * 100
    dropped = metrics.loc[order, "events_lost_to_dropped_cases"] / sample_events * 100
    fig, ax = plt.subplots(figsize=(FIG_WIDTH, 2.8))
    ax.bar(x, dropped, width=0.65, color=NEUTRAL, edgecolor="white", linewidth=1,
           label="events in dropped cases")
    ax.bar(x, prefix, bottom=dropped, width=0.65, color=MAIN_COLOR, edgecolor="white",
           linewidth=1, label="prefix loss in covered cases")
    for xi, (d, p) in enumerate(zip(dropped, prefix)):
        ax.text(xi, d + p + 1.5, f"{d + p:.0f}\u2009%", ha="center", fontsize=7.5, color=INK)
    ax.set_ylim(0, 108)
    ax.set_ylabel("Events never checked [%]")
    _trigger_axis(ax, order)
    legend_above(ax, ncol=2)
    save_fig(fig, "trigger_data_loss")

    # Granularity: episodes per case and episode size.
    dist = np.load(dist_path)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(FIG_WIDTH, 2.8))
    means = metrics.loc[order, "eps_per_case_mean"]
    multi = metrics.loc[order, "multi_episode_case_share"] * 100
    ax1.bar(x, means, width=0.65, color=MAIN_COLOR)
    for xi, (m, s) in enumerate(zip(means, multi)):
        ax1.text(xi, m + 0.03, f"{m:.2f}\n({s:.0f}\u2009%)", ha="center", va="bottom",
                 fontsize=6.5, color=INK)
    ax1.set_ylim(0, max(means) * 1.35)
    ax1.set_ylabel("Episodes per covered case (mean)")
    _trigger_axis(ax1, order, rotation=45)
    ax2.boxplot(
        [dist[f"{t}|ep_events"] for t in order],
        positions=x, widths=0.55, showfliers=False, patch_artist=True,
        boxprops={"facecolor": "#cfe3f1", "edgecolor": MAIN_COLOR},
        medianprops={"color": MAIN_COLOR, "linewidth": 1.5},
        whiskerprops={"color": MAIN_COLOR}, capprops={"color": MAIN_COLOR},
    )
    ax2.set_ylabel("Events per episode")
    _trigger_axis(ax2, order, rotation=45)
    save_fig(fig, "trigger_granularity")

    # Outcome balance and label validity.
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(FIG_WIDTH, 2.9))
    succ = metrics.loc[order, "success_share"] * 100
    ax1.bar(x, succ, width=0.65, color=OUTCOME_COLOR["success"], edgecolor="white",
            linewidth=1, label="Success")
    ax1.bar(x, 100 - succ, bottom=succ, width=0.65, color=OUTCOME_COLOR["failure"],
            edgecolor="white", linewidth=1, label="Failure")
    ax1.set_ylim(0, 100)
    ax1.set_ylabel("Episodes [%]")
    _trigger_axis(ax1, order, rotation=45)
    legend_above(ax1, ncol=2)
    validity = metrics.loc[order, "eps_without_create_fine_share"] * 100
    ax2.bar(x, validity, width=0.65, color=MAIN_COLOR)
    for xi, v in enumerate(validity):
        ax2.text(xi, v + 2, f"{v:.0f}\u2009%", ha="center", fontsize=7.5, color=INK)
    ax2.set_ylim(0, 112)
    ax2.set_ylabel("Episodes without Create Fine [%]")
    _trigger_axis(ax2, order, rotation=45)
    save_fig(fig, "trigger_label_validity")


def _working_set_events() -> int:
    """Events in the notebook's working set (len(sample) there): same sample
    size and seed as trigger_sensitivity.ipynb."""
    from trigger_distributions import RANDOM_STATE, SAMPLE_N

    log = pd.read_parquet(DATA_DIR / "rtfm_event_log.parquet", columns=["case_id"])
    case_ids = set(log["case_id"].drop_duplicates().sample(n=SAMPLE_N,
                                                           random_state=RANDOM_STATE))
    return int(log["case_id"].isin(case_ids).sum())


def main() -> None:
    scalability_figures()
    trigger_figures()


if __name__ == "__main__":
    main()
