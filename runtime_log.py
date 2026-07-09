"""Runtime tracking for pipeline scripts: named phase timers + cProfile.

Two composed views:
  1. track_step(...)  -> appends one JSONL line per phase to data/runtime_log.jsonl
                         (readable step durations, accumulates across resumes).
  2. profile_run(...) -> dumps one cProfile .prof per invocation to data/profiles/
                         (function-level hot-spots; merge across runs with pstats).

Report: `python runtime_log.py` prints both.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import cProfile, json, pstats, time

DEFAULT_LOG_PATH = Path("data/runtime/runtime_log.jsonl")
PROFILE_DIR = Path("data/runtime/profiles")
RUN_ID = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")  # stamps every step of one process invocation


def log_step(script: str, step: str, start: float, status: str = "completed",
             log_path: Path = DEFAULT_LOG_PATH, **extra) -> None:
    """Append one JSONL row for a phase given its start time (from time.time())."""
    record = {
        "run_id": RUN_ID,
        "script": script,
        "step": step,
        "start": datetime.fromtimestamp(start, tz=timezone.utc).isoformat(),
        "end": datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(time.time() - start, 3),
        "status": status,
        **extra,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")


@contextmanager
def track_step(script: str, step: str, log_path: Path = DEFAULT_LOG_PATH, **extra):
    start = time.time()
    status = "completed"
    try:
        yield
    except BaseException:
        status = "failed"
        raise
    finally:
        log_step(script, step, start, status, log_path, **extra)


@contextmanager
def profile_run(script: str, profile_dir: Path = PROFILE_DIR):
    """Wrap a whole main() to dump one cProfile .prof per invocation."""
    profile_dir.mkdir(parents=True, exist_ok=True)
    pr = cProfile.Profile()
    pr.enable()
    try:
        yield
    finally:
        pr.disable()
        pr.dump_stats(str(profile_dir / f"{script}_{RUN_ID}.prof"))


def report(log_path: Path = DEFAULT_LOG_PATH):
    """Per-step totals + share of the run's total time. Run: python runtime_log.py"""
    import pandas as pd
    df = pd.read_json(log_path, lines=True)
    agg = df.groupby(["script", "step"], sort=False)["duration_seconds"].sum().reset_index()
    total = agg["duration_seconds"].sum()
    agg["pct_of_run"] = (100 * agg["duration_seconds"] / total).round(1)
    return agg


def profile_report(profile_dir: Path = PROFILE_DIR, top: int = 30, sort: str = "cumulative") -> None:
    """Merge every .prof across runs and print top-N functions by cumtime."""
    profs = sorted(profile_dir.glob("*.prof"))
    if not profs:
        print("No .prof files found.")
        return
    stats = pstats.Stats(*[str(p) for p in profs])
    stats.strip_dirs().sort_stats(sort).print_stats(top)


if __name__ == "__main__":
    if DEFAULT_LOG_PATH.exists():
        print(report().to_string(index=False))
    else:
        print(f"No runtime log yet at {DEFAULT_LOG_PATH} — run a pipeline script first.")
    print("\n=== cProfile hot-spots (merged across runs) ===")
    profile_report()
