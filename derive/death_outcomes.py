"""Death-within-48h outcome correction for SBT episodes.

The base outcome rule (derive/activity_emitter.py) calls an SBT a success when no
re-ventilation follows within 48h. A patient extubated and then dying (e.g.
comfort-care extubation) also shows no re-ventilation, so that rule labels them a
success. This module adds one extra condition on top of it: an episode labelled
"Success" (right-censored or not) whose patient dies within 48h after SBTStarted is
relabelled as a failure. Re-ventilation failures are left as they are.

Death time comes from MIMIC-IV ``admissions.deathtime``, which the raw extraction
already carries per row. It covers in-hospital deaths only; deaths after discharge
are not captured.

Usage:
    # 1. one-time: stay_id -> deathtime lookup (reads only 3 columns of the raw file)
    python -m derive.death_outcomes extract
    # 2. patch existing conformance CSVs in place (keeps a .bak copy)
    python -m derive.death_outcomes relabel data/results/full_results/trigger_results_full.csv
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pandas as pd

RAW_EVENTS = Path("data/icu_event_level_sbt.parquet")
STAY_DEATHS = Path("data/stay_deaths.parquet")
DEATH_WINDOW = pd.Timedelta(hours=48)
DEATH_FAILURE_LABEL = "Failure (Died <=48h)"


def extract_stay_deaths(raw_path: Path = RAW_EVENTS, out_path: Path = STAY_DEATHS) -> pd.DataFrame:
    """Write a stay_id -> deathtime table, reading only the columns it needs."""
    import duckdb

    con = duckdb.connect()
    con.execute("SET memory_limit = '2GB'")
    con.execute("SET threads = 2")
    deaths = con.execute(
        f"""
        SELECT stay_id,
               max(deathtime) AS deathtime,
               count(DISTINCT deathtime) AS n_deathtimes,
               bool_or(died_in_hospital) AS died_in_hospital
        FROM read_parquet('{raw_path.as_posix()}')
        GROUP BY stay_id
        """
    ).df()
    con.close()

    inconsistent = int((deaths["n_deathtimes"] > 1).sum())
    if inconsistent:
        print(f"  warning: {inconsistent} stays have more than one deathtime; using the latest")
    deaths = deaths.drop(columns="n_deathtimes")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    deaths.to_parquet(out_path, index=False)
    print(
        f"  {len(deaths)} stays, {int(deaths['deathtime'].notna().sum())} with in-hospital "
        f"deathtime -> {out_path}"
    )
    return deaths


def load_stay_deaths(path: Path = STAY_DEATHS) -> dict[str, pd.Timestamp]:
    """stay_id (as str) -> deathtime, for stays with a recorded death only."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path} missing; build it once with `python -m derive.death_outcomes extract`"
        )
    df = pd.read_parquet(path, columns=["stay_id", "deathtime"]).dropna(subset=["deathtime"])
    return dict(zip(df["stay_id"].astype(str), pd.to_datetime(df["deathtime"])))


def apply_death_rule(outcome: str, sbt_start, deathtime) -> str:
    """Relabel a success as a failure when death falls in (sbt_start, sbt_start + 48h]."""
    if "success" not in str(outcome).lower():
        return outcome
    if deathtime is None or pd.isnull(deathtime) or sbt_start is None or sbt_start == "":
        return outcome
    start = pd.Timestamp(sbt_start)
    if pd.isnull(start):
        return outcome
    if start < pd.Timestamp(deathtime) <= start + DEATH_WINDOW:
        return DEATH_FAILURE_LABEL
    return outcome


def relabel_results_csv(csv_path: Path, deaths_path: Path = STAY_DEATHS) -> None:
    """Apply the death rule to an existing conformance CSV and rebuild next_sbt_outcome."""
    deaths = load_stay_deaths(deaths_path)
    # All-str read so untouched columns are written back verbatim.
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)

    # next_sbt_outcome is the following row of the same stay (rows are written per
    # stay in episode order). Confirm that holds before rebuilding it that way.
    has_next = "next_sbt_outcome" in df.columns
    if has_next:
        rebuilt = df.groupby("stay_id", sort=False)["sbt_outcome"].shift(-1).fillna("")
        mismatches = int((rebuilt != df["next_sbt_outcome"]).sum())
        if mismatches:
            raise RuntimeError(
                f"{csv_path}: {mismatches} rows where next_sbt_outcome is not the next "
                "row's sbt_outcome; refusing to rebuild it"
            )

    before = df["sbt_outcome"].copy()
    df["sbt_outcome"] = [
        apply_death_rule(o, s, deaths.get(str(sid)))
        for o, s, sid in zip(df["sbt_outcome"], df["sbt_start"], df["stay_id"])
    ]
    if has_next:
        df["next_sbt_outcome"] = df.groupby("stay_id", sort=False)["sbt_outcome"].shift(-1).fillna("")

    changed = before != df["sbt_outcome"]
    print(f"{csv_path}: {int(changed.sum())} episodes relabelled as '{DEATH_FAILURE_LABEL}'")
    print(before[changed].value_counts().rename("previous label").to_string())
    print(f"  affected stays: {df.loc[changed, 'stay_id'].nunique()}")

    backup = csv_path.with_suffix(csv_path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(csv_path, backup)
        print(f"  backup -> {backup}")
    df.to_csv(csv_path, index=False, lineterminator="\r\n")  # csv.DictWriter default


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    ex = sub.add_parser("extract", help="Build the stay_id -> deathtime lookup.")
    ex.add_argument("--raw", type=Path, default=RAW_EVENTS)
    ex.add_argument("--out", type=Path, default=STAY_DEATHS)
    rl = sub.add_parser("relabel", help="Apply the death rule to conformance CSVs in place.")
    rl.add_argument("csv", type=Path, nargs="+")
    rl.add_argument("--deaths", type=Path, default=STAY_DEATHS)
    args = parser.parse_args()

    if args.cmd == "extract":
        extract_stay_deaths(args.raw, args.out)
    else:
        for path in args.csv:
            relabel_results_csv(path, args.deaths)


if __name__ == "__main__":
    main()
