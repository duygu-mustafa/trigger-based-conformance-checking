"""Scalability benchmark for the Declare conformance checker on the RTFM log.

Experiments (each writes one tidy CSV to ``evaluation/data/benchmarks/``):

* **E1 — log size**: wall time of the full pipeline (episode segmentation,
  outcome derivation, all 10 RTFM constraints) over increasing case samples.
* **E2 — trace length**: per-case runtime vs. events per trace; natural range
  from the log plus synthetically lengthened traces (event sequence replicated
  k times with shifted timestamps, checked without segmentation to keep the
  whole lengthened trace as one evaluation unit).
* **E3 — model size**: wall time on a fixed sample with the first k of the 10
  RTFM constraints, k = 1..10.
* **E4 — rule complexity**: per-constraint runtime (real model + synthetic
  variants from ``rtfm_synthetic_rules.yaml``) joined with the complexity
  breakdown from ``evaluation/complexity.py``.
* **E5 — memory**: tracemalloc peak and RSS over the E1 size ladder. Run
  separately from E1 because tracemalloc slows execution; its wall times must
  not be mixed with E1's.

Protocol: single-threaded, fixed sampling seed (same case sample across
repetitions, so repetition variance is timing noise only), one warm-up pass
before the first timed run, wall time via ``time.perf_counter``. Machine and
library versions are recorded in ``machine_info.json``.

Results are appended per measurement, so an interrupted run keeps everything
already measured and ``--resume`` continues from there (same contract as
``main_per_sbt.py --resume``). Long runs should go through
``run_benchmark_safe.sh``, which wraps this in tmux/nohup with a timestamped log.

Usage::

    python evaluation/benchmark_scalability.py --experiments E1 E3 --reps 5
    python evaluation/benchmark_scalability.py --experiments all --resume \
        --e1-sizes 1000 5000 10000 50000 full
"""

from __future__ import annotations

import argparse
import json
import platform
import subprocess
import sys
import time
import tracemalloc
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from conformance.checker import evaluate_constraint  # noqa: E402
from conformance.rules import load_model_from_yaml  # noqa: E402
from conformance.types import DeclareModel  # noqa: E402
from evaluation.complexity import complexity  # noqa: E402
from evaluation.rtfm_utils import build_trigger_episodes, derive_episode_outcome  # noqa: E402

EVAL_DIR = REPO_ROOT / "evaluation"
PARQUET_CACHE = EVAL_DIR / "data" / "rtfm_event_log.parquet"
MODEL_PATH = EVAL_DIR / "rtfm.yaml"
SYNTHETIC_MODEL_PATH = EVAL_DIR / "rtfm_synthetic_rules.yaml"
OUT_DIR = EVAL_DIR / "data" / "benchmarks"

TRIGGER_ACTIVITY = "Create Fine"


# ---------------------------------------------------------------------------
# Data and pipeline helpers
# ---------------------------------------------------------------------------

def load_log() -> pd.DataFrame:
    if not PARQUET_CACHE.exists():
        raise SystemExit(
            f"Missing {PARQUET_CACHE}. Run evaluation/rtfm_conformance.ipynb once to "
            "parse the XES log into the parquet cache."
        )
    return pd.read_parquet(PARQUET_CACHE)


def sample_cases(log: pd.DataFrame, n_cases: int | None, seed: int) -> pd.DataFrame:
    """Random case sample; deterministic for a given (n_cases, seed)."""
    all_ids = log["case_id"].drop_duplicates()
    if n_cases is None or n_cases >= len(all_ids):
        return log
    chosen = set(all_ids.sample(n=n_cases, random_state=seed))
    return log[log["case_id"].isin(chosen)]


def run_pipeline(
    sample: pd.DataFrame,
    model: DeclareModel,
    per_case: bool = False,
    per_constraint: bool = False,
) -> dict:
    """One timed pass of the conformance pipeline over ``sample``.

    Mirrors ``check_case`` in rtfm_conformance.ipynb: per case, sort, segment
    into trigger episodes, derive the outcome, evaluate every constraint on
    every episode. Result flattening is left out — it feeds the statistical
    analysis, not the conformance method under evaluation.
    """
    per_case_rows: list[dict] = []
    rule_seconds: dict[str, float] = defaultdict(float)
    rule_evals: dict[str, int] = defaultdict(int)
    n_cases = 0
    n_events = 0

    t0 = time.perf_counter()
    for case_id, trace in sample.groupby("case_id", sort=False):
        c0 = time.perf_counter()
        trace = trace.sort_values("timestamp")
        windows = build_trigger_episodes(trace, trigger_activity=TRIGGER_ACTIVITY)
        for start_ts, end_ts in windows:
            episode = trace[(trace["timestamp"] >= start_ts) & (trace["timestamp"] < end_ts)]
            if episode.empty:
                continue
            derive_episode_outcome(episode)
            for constraint in model.constraints:
                if per_constraint:
                    r0 = time.perf_counter()
                    evaluate_constraint(case_id=str(case_id), trace_df=episode, constraint=constraint)
                    rule_seconds[constraint.id] += time.perf_counter() - r0
                    rule_evals[constraint.id] += 1
                else:
                    evaluate_constraint(case_id=str(case_id), trace_df=episode, constraint=constraint)
        n_cases += 1
        n_events += len(trace)
        if per_case:
            per_case_rows.append(
                {
                    "case_id": str(case_id),
                    "n_events": len(trace),
                    "wall_s": time.perf_counter() - c0,
                }
            )
    wall_s = time.perf_counter() - t0

    return {
        "wall_s": wall_s,
        "n_cases": n_cases,
        "n_events": n_events,
        "per_case": per_case_rows,
        "rule_seconds": dict(rule_seconds),
        "rule_evals": dict(rule_evals),
    }


def lengthen_trace(trace: pd.DataFrame, factor: int) -> pd.DataFrame:
    """Replicate a trace's event sequence ``factor`` times with shifted timestamps."""
    if factor <= 1:
        return trace
    span = trace["timestamp"].max() - trace["timestamp"].min() + pd.Timedelta(days=1)
    replicas = []
    for i in range(factor):
        replica = trace.copy()
        replica["timestamp"] = replica["timestamp"] + i * span
        replicas.append(replica)
    return pd.concat(replicas, ignore_index=True).sort_values("timestamp")


# ---------------------------------------------------------------------------
# Experiments
# ---------------------------------------------------------------------------

def reps_for_size(size: int | None, reps: int, large_threshold: int, large_reps: int) -> int:
    """Repetitions for one sample size.

    Timing noise is characterised at the small sizes (repetition spread there is
    well under a few percent), so the expensive large samples are measured fewer
    times rather than dropping them altogether.
    """
    if size is None or size >= large_threshold:
        return large_reps
    return reps


def run_e1(
    log: pd.DataFrame,
    model: DeclareModel,
    sizes: list[int | None],
    reps: int,
    seed: int,
    resume: bool,
    large_threshold: int,
    large_reps: int,
) -> None:
    writer = ResultsWriter("e1_log_size.csv", ["n_cases_requested", "rep"], resume)
    for size in sizes:
        label = size if size is not None else log["case_id"].nunique()
        n_reps = reps_for_size(size, reps, large_threshold, large_reps)
        sample = None
        for rep in range(n_reps):
            if writer.is_done(label, rep):
                continue
            if sample is None:
                sample = sample_cases(log, size, seed)
            result = run_pipeline(sample, model)
            row = {
                "n_cases_requested": label,
                "n_cases": result["n_cases"],
                "n_events": result["n_events"],
                "rep": rep,
                "wall_s": result["wall_s"],
                "cases_per_s": result["n_cases"] / result["wall_s"],
                "events_per_s": result["n_events"] / result["wall_s"],
            }
            writer.append([row])
            print(f"[E1] n={label} rep={rep}: {result['wall_s']:.1f}s "
                  f"({row['cases_per_s']:.1f} cases/s)", flush=True)
    writer.finish()


def run_e2_natural(
    log: pd.DataFrame, model: DeclareModel, n_cases: int, reps: int, seed: int, resume: bool
) -> None:
    writer = ResultsWriter("e2_trace_length_natural.csv", ["n_sample_cases", "rep"], resume)
    sample = sample_cases(log, n_cases, seed)
    n_sample_cases = sample["case_id"].nunique()
    for rep in range(reps):
        if writer.is_done(n_sample_cases, rep):
            continue
        result = run_pipeline(sample, model, per_case=True)
        for row in result["per_case"]:
            row["rep"] = rep
            row["n_sample_cases"] = n_sample_cases
        writer.append(result["per_case"])
        print(f"[E2-natural] rep={rep}: {result['wall_s']:.1f}s over {result['n_cases']} cases", flush=True)
    writer.finish()


def run_e2_synthetic(
    log: pd.DataFrame,
    model: DeclareModel,
    n_cases: int,
    factors: list[int],
    reps: int,
    seed: int,
    resume: bool,
) -> None:
    """Time the checker on synthetically lengthened traces, no segmentation.

    Segmentation would split the replicas back into episodes at each repeated
    trigger; evaluating the whole lengthened trace as one unit is what exposes
    the checker's scaling in events per trace.
    """
    writer = ResultsWriter(
        "e2_trace_length_synthetic.csv", ["n_sample_cases", "factor", "rep"], resume
    )
    sample = sample_cases(log, n_cases, seed)
    n_sample_cases = sample["case_id"].nunique()
    base_traces = [t.sort_values("timestamp") for _, t in sample.groupby("case_id", sort=False)]
    for factor in factors:
        if all(writer.is_done(n_sample_cases, factor, rep) for rep in range(reps)):
            continue
        long_traces = [lengthen_trace(t, factor) for t in base_traces]
        for rep in range(reps):
            if writer.is_done(n_sample_cases, factor, rep):
                continue
            rows = []
            for trace in long_traces:
                t0 = time.perf_counter()
                for constraint in model.constraints:
                    evaluate_constraint(
                        case_id=str(trace["case_id"].iloc[0]),
                        trace_df=trace,
                        constraint=constraint,
                    )
                rows.append(
                    {
                        "n_sample_cases": n_sample_cases,
                        "factor": factor,
                        "rep": rep,
                        "case_id": str(trace["case_id"].iloc[0]),
                        "n_events": len(trace),
                        "wall_s": time.perf_counter() - t0,
                    }
                )
            writer.append(rows)
        print(f"[E2-synthetic] factor={factor}: done ({reps} reps x {len(long_traces)} traces)", flush=True)
    writer.finish()


def run_e3(
    log: pd.DataFrame, model: DeclareModel, n_cases: int, reps: int, seed: int, resume: bool
) -> None:
    writer = ResultsWriter("e3_model_size.csv", ["n_cases", "k_constraints", "rep"], resume)
    sample = sample_cases(log, n_cases, seed)
    n_sample_cases = sample["case_id"].nunique()
    for k in range(1, len(model.constraints) + 1):
        partial = DeclareModel(name=f"{model.name}_first_{k}", constraints=model.constraints[:k])
        for rep in range(reps):
            if writer.is_done(n_sample_cases, k, rep):
                continue
            result = run_pipeline(sample, partial)
            writer.append([
                {
                    "k_constraints": k,
                    "rep": rep,
                    "n_cases": result["n_cases"],
                    "wall_s": result["wall_s"],
                }
            ])
            print(f"[E3] k={k} rep={rep}: {result['wall_s']:.1f}s", flush=True)
    writer.finish()


def run_e4(log: pd.DataFrame, n_cases: int, reps: int, seed: int, resume: bool) -> None:
    writer = ResultsWriter("e4_rule_complexity.csv", ["n_cases", "model", "rep"], resume)
    sample = sample_cases(log, n_cases, seed)
    n_sample_cases = sample["case_id"].nunique()
    for model_path in (MODEL_PATH, SYNTHETIC_MODEL_PATH):
        model = load_model_from_yaml(model_path)
        breakdown = {c.id: complexity(c).as_dict() for c in model.constraints}
        for rep in range(reps):
            if writer.is_done(n_sample_cases, model.name, rep):
                continue
            result = run_pipeline(sample, model, per_constraint=True)
            rows = []
            for rule_id, seconds in result["rule_seconds"].items():
                n_evals = result["rule_evals"][rule_id]
                rows.append(
                    {
                        "n_cases": n_sample_cases,
                        "model": model.name,
                        "rep": rep,
                        "total_s": seconds,
                        "n_evals": n_evals,
                        "mean_us_per_eval": seconds / n_evals * 1e6,
                        **breakdown[rule_id],
                    }
                )
            writer.append(rows)
            print(f"[E4] model={model.name} rep={rep}: {result['wall_s']:.1f}s", flush=True)
    writer.finish()


def run_e5(log: pd.DataFrame, model: DeclareModel, sizes: list[int | None], seed: int, resume: bool) -> None:
    try:
        import psutil
        process = psutil.Process()
    except ImportError:
        process = None
    writer = ResultsWriter("e5_memory.csv", ["n_cases_requested"], resume)
    for size in sizes:
        label = size if size is not None else log["case_id"].nunique()
        if writer.is_done(label):
            continue
        sample = sample_cases(log, size, seed)
        rss_before_mb = process.memory_info().rss / 2**20 if process else None
        tracemalloc.start()
        result = run_pipeline(sample, model)
        peak_mb = tracemalloc.get_traced_memory()[1] / 2**20
        tracemalloc.stop()
        writer.append([
            {
                "n_cases_requested": label,
                "n_cases": result["n_cases"],
                "n_events": result["n_events"],
                "tracemalloc_peak_mb": peak_mb,
                "rss_before_mb": rss_before_mb,
                "rss_after_mb": process.memory_info().rss / 2**20 if process else None,
                # Wall time under tracemalloc — not comparable with E1.
                "wall_s_instrumented": result["wall_s"],
            }
        ])
        print(f"[E5] n={label}: peak {peak_mb:.1f} MB", flush=True)
    writer.finish()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------

class ResultsWriter:
    """Append-per-unit CSV writer with ``--resume`` support.

    A *unit* is one timed measurement (e.g. one E1 size at one repetition). Its
    rows are appended and flushed as soon as the unit finishes, so a run that is
    interrupted keeps everything already measured; ``--resume`` reads the keys
    back and skips those units. Without ``--resume`` an existing file is
    truncated, so a fresh run never mixes measurements from different machines
    or code versions.
    """

    def __init__(self, filename: str, key_cols: list[str], resume: bool) -> None:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        self.path = OUT_DIR / filename
        self.key_cols = key_cols
        self.done: set[tuple[str, ...]] = set()
        if self.path.exists():
            if resume:
                existing = pd.read_csv(self.path)
                missing = [c for c in key_cols if c not in existing.columns]
                if missing:
                    raise SystemExit(
                        f"{self.path} predates the current result schema (missing {missing}). "
                        "Delete evaluation/data/benchmarks/ and start a fresh run, or drop "
                        "--resume."
                    )
                self.done = {
                    tuple(str(v) for v in key)
                    for key in existing[key_cols].drop_duplicates().itertuples(index=False)
                }
                print(f"[resume] {filename}: {len(self.done)} unit(s) already done", flush=True)
            else:
                self.path.unlink()

    def is_done(self, *key: object) -> bool:
        return tuple(str(k) for k in key) in self.done

    def append(self, rows: list[dict]) -> None:
        if not rows:
            return
        pd.DataFrame(rows).to_csv(
            self.path, mode="a", header=not self.path.exists(), index=False
        )

    def finish(self) -> None:
        print(f"  -> {self.path}", flush=True)


def write_sample_representativeness(log: pd.DataFrame, sizes: list[int | None], seed: int) -> None:
    """Compare each sample's trace-length distribution against the full log.

    Backs the claim that subsampled experiments generalise: random case sampling
    preserves the trace-length distribution in expectation, but the long-trace
    tail is thin, so small samples can miss it. Reports mean/median/p95/max
    events per case per sample size plus a two-sample Kolmogorov-Smirnov test
    against the full log.
    """
    full_lengths = log.groupby("case_id", sort=False).size()
    rows = []
    for size in sizes:
        sample = sample_cases(log, size, seed)
        lengths = sample.groupby("case_id", sort=False).size()
        row = {
            "n_cases_requested": size if size is not None else log["case_id"].nunique(),
            "n_cases": len(lengths),
            "mean_events": lengths.mean(),
            "median_events": lengths.median(),
            "p95_events": lengths.quantile(0.95),
            "max_events": lengths.max(),
        }
        try:
            from scipy import stats
            ks = stats.ks_2samp(lengths.to_numpy(), full_lengths.to_numpy())
            row["ks_statistic"] = ks.statistic
            row["ks_pvalue"] = ks.pvalue
        except ImportError:
            pass
        rows.append(row)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "sample_representativeness.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    print(f"  -> {path}", flush=True)


def write_machine_info() -> None:
    info = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": sys.version,
        "pandas": pd.__version__,
        "cpu_count": __import__("os").cpu_count(),
    }
    try:
        cpuinfo = Path("/proc/cpuinfo").read_text()
        for line in cpuinfo.splitlines():
            if line.startswith("model name"):
                info["cpu_model"] = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    try:
        info["git_commit"] = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True
        ).stdout.strip()
    except OSError:
        pass
    try:
        import psutil
        info["ram_total_gb"] = psutil.virtual_memory().total / 2**30
    except ImportError:
        pass
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "machine_info.json").write_text(json.dumps(info, indent=2))


def _parse_sizes(values: list[str]) -> list[int | None]:
    return [None if v.lower() == "full" else int(v) for v in values]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--experiments", nargs="+", default=["all"],
                        choices=["all", "E1", "E2", "E3", "E4", "E5"])
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--resume", action="store_true",
                        help="Keep measurements already in the output CSVs and only run "
                             "the missing units. Without it, existing CSVs are overwritten.")
    parser.add_argument("--e1-sizes", nargs="+",
                        default=["1000", "2000", "5000", "10000", "25000", "50000", "100000", "full"])
    parser.add_argument("--large-threshold", type=int, default=25000,
                        help="E1/E5 samples at or above this size use --large-reps repetitions.")
    parser.add_argument("--large-reps", type=int, default=1,
                        help="Repetitions for the large E1 samples (default: 1).")
    parser.add_argument("--e2-cases", type=int, default=10000,
                        help="Sample size for natural trace-length measurement")
    parser.add_argument("--e2-synthetic-cases", type=int, default=100)
    parser.add_argument("--e2-factors", nargs="+", type=int, default=[1, 2, 5, 10, 25, 50])
    parser.add_argument("--e3-cases", type=int, default=10000)
    parser.add_argument("--e4-cases", type=int, default=10000)
    parser.add_argument("--e5-sizes", nargs="+", default=None,
                        help="Sizes for the memory experiment (default: the E1 ladder up to "
                             "--large-threshold; peak memory is flat, so the expensive sizes "
                             "add little).")
    parser.add_argument("--skip-warmup", action="store_true")
    args = parser.parse_args()

    experiments = {"E1", "E2", "E3", "E4", "E5"} if "all" in args.experiments else set(args.experiments)

    log = load_log()
    model = load_model_from_yaml(MODEL_PATH)
    e1_sizes = _parse_sizes(args.e1_sizes)
    if args.e5_sizes is not None:
        e5_sizes = _parse_sizes(args.e5_sizes)
    else:
        e5_sizes = [s for s in e1_sizes if s is not None and s <= args.large_threshold]

    write_machine_info()
    write_sample_representativeness(log, e1_sizes, args.seed)

    if not args.skip_warmup:
        print("[warm-up] 200 cases", flush=True)
        run_pipeline(sample_cases(log, 200, args.seed), model)

    if "E1" in experiments:
        run_e1(log, model, e1_sizes, args.reps, args.seed, args.resume,
               args.large_threshold, args.large_reps)
    if "E2" in experiments:
        run_e2_natural(log, model, args.e2_cases, args.reps, args.seed, args.resume)
        run_e2_synthetic(log, model, args.e2_synthetic_cases, args.e2_factors,
                         args.reps, args.seed, args.resume)
    if "E3" in experiments:
        run_e3(log, model, args.e3_cases, args.reps, args.seed, args.resume)
    if "E4" in experiments:
        run_e4(log, args.e4_cases, args.reps, args.seed, args.resume)
    if "E5" in experiments:
        run_e5(log, model, e5_sizes, args.seed, args.resume)

    print("done", flush=True)


if __name__ == "__main__":
    main()
