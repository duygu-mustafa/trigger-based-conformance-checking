"""Ground-truth experiments on synthetic logs.

Three experiments, each writing one tidy CSV to ``evaluation/data/synthetic/``:

* **SE1 — verdict correctness**: every constraint template, data condition,
  time window and target-selection mode is evaluated on a micro-trace whose
  verdict is fixed by the semantics, and the observed verdict is compared
  against it. Answers whether the checker is right, which neither real log can.
* **SE2 — episode-scoped vs. case-scoped checking**: the same multi-episode log
  is checked once per episode and once per whole case. Reports how often the
  case-scoped reading masks a real violation, and how often it manufactures one
  that no episode committed.
* **SE3 — association recovery**: the outcome is planted at known risk ratios,
  and the statistical stage is asked to recover them. Run over several seeds,
  so the coverage of the confidence intervals is measurable, and under both
  scopes and both vacuity treatments, so the cost of each choice is visible.

SE2 and SE3 read the same replications: one pass over a generated log yields
both the per-episode and the per-case verdict tables, and the two experiments
summarise them differently. Replications are keyed by seed and appended as they
finish, so ``--resume`` continues an interrupted run (same contract as
``benchmark_scalability.py``).

Usage::

    python evaluation/benchmark_synthetic.py --experiments SE1
    python evaluation/benchmark_synthetic.py --experiments SE2 SE3 --reps 20 --cases 2000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from conformance.checker import evaluate_constraint  # noqa: E402
from derive.statistical_analysis import calculate_stats  # noqa: E402
from evaluation.benchmark_scalability import ResultsWriter, write_machine_info  # noqa: E402
from evaluation.rtfm_utils import build_trigger_episodes  # noqa: E402
from evaluation.synthetic_log import (  # noqa: E402
    CORRECTNESS_CASES,
    RULES,
    TRIGGER,
    SyntheticLogConfig,
    aggregate_case_truth,
    generate_log,
    rule_model,
)

OUT_DIR = REPO_ROOT / "evaluation" / "data" / "synthetic"
ALPHA = 0.05


# ---------------------------------------------------------------------------
# SE1 — verdict correctness
# ---------------------------------------------------------------------------

def run_se1(resume: bool) -> None:
    print("[SE1] verdict correctness against planted ground truth", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "se1_correctness.csv"

    rows = []
    for case in CORRECTNESS_CASES:
        result = evaluate_constraint(
            case_id=case.case_id, trace_df=case.trace(), constraint=case.constraint
        )
        rows.append(
            {
                "case_id": case.case_id,
                "family": case.case_id.split("-")[0],
                "template": case.template,
                "expected": case.expected.value,
                "observed": result.outcome.value,
                "match": result.outcome == case.expected,
                "documented_deviation": (result.outcome != case.expected) and case.note is not None,
                "note": case.note or "",
                "n_activations": result.num_activations,
                "n_violated": result.num_violated,
            }
        )
    df = pd.DataFrame(rows)
    df.to_csv(path, index=False)

    n = len(df)
    matched = int(df["match"].sum())
    unexplained = df[(~df["match"]) & (~df["documented_deviation"])]
    deviations = df[(~df["match"]) & (df["documented_deviation"])]
    print(f"  {matched}/{n} verdicts match the planted ground truth", flush=True)
    print(f"  {len(deviations)} documented semantic deviation(s)", flush=True)
    if len(unexplained):
        print("  UNEXPLAINED MISMATCHES:", flush=True)
        for _, row in unexplained.iterrows():
            print(f"    {row['case_id']} ({row['template']}): "
                  f"expected {row['expected']}, got {row['observed']}", flush=True)
    print(f"  -> {path}", flush=True)


# ---------------------------------------------------------------------------
# SE2/SE3 — one replication yields both verdict tables
# ---------------------------------------------------------------------------

def run_replication(seed: int, n_cases: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate one log and check it under both scopes.

    Returns ``(episodes, cases)``. Each frame carries, per rule, the planted
    verdict (``<rule>_true``) and the observed one (``<rule>_obs``), plus the
    outcome the association stage will use.
    """
    log, truth = generate_log(SyntheticLogConfig(n_cases=n_cases), seed=seed)
    case_truth = aggregate_case_truth(truth)
    model = rule_model()

    truth_idx = truth.set_index(["case_id", "episode_index"])
    episode_rows = []
    case_rows = []

    case_truth_idx = case_truth.set_index("case_id")
    for case_id, trace in log.groupby("case_id", sort=False):
        trace = trace.sort_values("timestamp")

        # Episode-scoped: one evaluation unit per trigger occurrence.
        for ep_idx, (start_ts, end_ts) in enumerate(build_trigger_episodes(trace, TRIGGER)):
            episode = trace[(trace["timestamp"] >= start_ts) & (trace["timestamp"] < end_ts)]
            planted = truth_idx.loc[(case_id, ep_idx)]
            row = {
                "case_id": case_id,
                "episode_index": ep_idx,
                "n_episodes": int(planted["n_episodes"]),
                "outcome": int(planted["outcome"]),
            }
            for constraint in model.constraints:
                result = evaluate_constraint(
                    case_id=str(case_id), trace_df=episode, constraint=constraint
                )
                row[f"{constraint.label}_true"] = planted[constraint.label]
                row[f"{constraint.label}_obs"] = result.outcome.value
            episode_rows.append(row)

        # Case-scoped: the whole trace as one evaluation unit, the reading an
        # analyst without an episode notion would get.
        planted_case = case_truth_idx.loc[case_id]
        row = {
            "case_id": case_id,
            "n_episodes": int(planted_case["n_episodes"]),
            "outcome": int(planted_case["outcome"]),
        }
        for constraint in model.constraints:
            result = evaluate_constraint(
                case_id=str(case_id), trace_df=trace, constraint=constraint
            )
            row[f"{constraint.label}_true"] = planted_case[constraint.label]
            row[f"{constraint.label}_obs"] = result.outcome.value
        case_rows.append(row)

    return pd.DataFrame(episode_rows), pd.DataFrame(case_rows)


def se2_metrics(episodes: pd.DataFrame, cases: pd.DataFrame, seed: int) -> list[dict]:
    """Per-rule accuracy under each scope, split by what the error does."""
    rows = []
    multi = cases["n_episodes"] > 1
    for rule in RULES:
        rid = rule.rule_id
        true_ep, obs_ep = episodes[f"{rid}_true"], episodes[f"{rid}_obs"]
        true_case, obs_case = cases[f"{rid}_true"], cases[f"{rid}_obs"]

        # Masking: a violation the case-scoped reading fails to report.
        masked = (true_case == "violated") & (obs_case != "violated")
        # False alarm: a violation it reports where no episode committed one.
        false_alarm = (true_case != "violated") & (obs_case == "violated")

        rows.append(
            {
                "seed": seed,
                "rule_id": rid,
                "template": rule.constraint.template.value,
                "expected_effect": rule.masking,
                "n_episodes": len(episodes),
                "n_cases": len(cases),
                "n_multi_episode_cases": int(multi.sum()),
                "episode_scope_accuracy": float((true_ep == obs_ep).mean()),
                "case_scope_accuracy": float((true_case == obs_case).mean()),
                "case_scope_accuracy_multi": float((true_case == obs_case)[multi].mean()),
                "masked_rate": float(masked.mean()),
                "masked_rate_multi": float(masked[multi].mean()),
                "false_alarm_rate": float(false_alarm.mean()),
                "false_alarm_rate_multi": float(false_alarm[multi].mean()),
                "true_violation_rate": float((true_case == "violated").mean()),
            }
        )
    return rows


def _exposure(verdicts: pd.Series, pool_vacuous: bool) -> pd.Series:
    """Map verdicts to the exposure variable: 1 violated, 0 satisfied, NaN excluded.

    Under ``pool_vacuous`` the vacuous episodes join the satisfied ones, which
    is the alternative treatment the conformance tables report alongside the
    activated-only default.
    """
    mapped = verdicts.map({"violated": 1.0, "satisfied": 0.0})
    if pool_vacuous:
        mapped = mapped.fillna(verdicts.map({"vacuous": 0.0}))
    return mapped


def se3_metrics(episodes: pd.DataFrame, cases: pd.DataFrame, seed: int) -> list[dict]:
    """Estimate each rule's association and compare it with the planted value."""
    threshold = ALPHA / len(RULES)
    rows = []
    for scope, frame in (("episode", episodes), ("case", cases)):
        for pool_vacuous in (False, True):
            for rule in RULES:
                rid = rule.rule_id
                exposure = _exposure(frame[f"{rid}_obs"], pool_vacuous)
                valid = pd.DataFrame({"x": exposure, "y": frame["outcome"]}).dropna()
                a = int(((valid.x == 1) & (valid.y == 1)).sum())
                b = int(((valid.x == 1) & (valid.y == 0)).sum())
                c = int(((valid.x == 0) & (valid.y == 1)).sum())
                d = int(((valid.x == 0) & (valid.y == 0)).sum())
                stats = calculate_stats(a, b, c, d)
                planted = rule.planted_rr
                rows.append(
                    {
                        "seed": seed,
                        "scope": scope,
                        "vacuity_mode": "pooled" if pool_vacuous else "activated_only",
                        "rule_id": rid,
                        "planted_rr": planted,
                        "a": a, "b": b, "c": c, "d": d,
                        "n_analysed": a + b + c + d,
                        "rr_point": stats["rr_point"],
                        "rr_ci_low": stats["rr_ci_low"],
                        "rr_ci_high": stats["rr_ci_high"],
                        "or_point": stats["or_point"],
                        "p_raw": stats["p_raw"],
                        "significant": bool(stats["p_raw"] < threshold),
                        "ci_covers_planted": bool(
                            stats["rr_ci_low"] <= planted <= stats["rr_ci_high"]
                        ),
                        "log_ratio_to_planted": float(
                            np.log(stats["rr_point"] / planted)
                        ) if stats["rr_point"] > 0 and np.isfinite(stats["rr_point"]) else np.nan,
                        "continuity_correction": bool(stats["continuity_correction"]),
                    }
                )
    return rows


def run_se2_se3(reps: int, n_cases: int, seed0: int, resume: bool, experiments: set[str]) -> None:
    print(f"[SE2/SE3] {reps} replication(s) of {n_cases} cases", flush=True)
    se2_writer = ResultsWriter("se2_scoping.csv", ["seed", "rule_id"], resume, out_dir=OUT_DIR)
    se3_writer = ResultsWriter(
        "se3_association.csv", ["seed", "scope", "vacuity_mode", "rule_id"], resume, out_dir=OUT_DIR
    )
    verdict_path = OUT_DIR / "se2_verdicts_seed{seed}.csv"

    for rep in range(reps):
        seed = seed0 + rep
        if se2_writer.is_done(seed, RULES[0].rule_id) and se3_writer.is_done(
            seed, "episode", "activated_only", RULES[0].rule_id
        ):
            continue
        episodes, cases = run_replication(seed, n_cases)
        if "SE2" in experiments:
            se2_writer.append(se2_metrics(episodes, cases, seed))
        if "SE3" in experiments:
            se3_writer.append(se3_metrics(episodes, cases, seed))
        if rep == 0:
            # Keep one replication's raw verdicts for the per-case breakdown plot.
            episodes.to_csv(str(verdict_path).format(seed=seed), index=False)
        print(f"  seed {seed}: {len(episodes)} episodes, {len(cases)} cases", flush=True)

    se2_writer.finish()
    se3_writer.finish()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--experiments", nargs="+", default=["all"],
                        choices=["all", "SE1", "SE2", "SE3"])
    parser.add_argument("--reps", type=int, default=20,
                        help="replications for SE2/SE3, one seed each")
    parser.add_argument("--cases", type=int, default=2000, help="cases per replication")
    parser.add_argument("--seed", type=int, default=42, help="first seed")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    experiments = {"SE1", "SE2", "SE3"} if "all" in args.experiments else set(args.experiments)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_machine_info()

    if "SE1" in experiments:
        run_se1(args.resume)
    if experiments & {"SE2", "SE3"}:
        run_se2_se3(args.reps, args.cases, args.seed, args.resume, experiments)


if __name__ == "__main__":
    main()
