#!/usr/bin/env python3
"""
Check that every SBTStarted event in the event log has a subsequent
SBTCompleted / SBTFailed / SBTSucceeded event within the same case.
"""
import argparse
from pathlib import Path
import pandas as pd

SBT_START = "SBTStarted"
SBT_END = {"SBTCompleted", "SBTFailed", "SBTSucceeded"}


def check(path: Path) -> None:
    df = pd.read_parquet(path, columns=["case_id", "activity", "timestamp"])
    df = df.sort_values(["case_id", "timestamp"])

    unpaired = []
    total_starts = 0

    for case_id, grp in df.groupby("case_id"):
        starts = grp[grp["activity"] == SBT_START]["timestamp"].tolist()
        ends = grp[grp["activity"].isin(SBT_END)]["timestamp"].tolist()

        for start_ts in starts:
            total_starts += 1
            matched = any(e >= start_ts for e in ends)
            if not matched:
                unpaired.append({"case_id": case_id, "sbt_start": start_ts})

    print(f"Total SBTStarted events : {total_starts}")
    print(f"Unpaired (no end event) : {len(unpaired)}")
    paired = total_starts - len(unpaired)
    pct = 100 * paired / total_starts if total_starts else 0
    print(f"Pairing rate            : {pct:.1f}%")

    if unpaired:
        print("\nCases with unpaired SBTStarted:")
        for row in unpaired:
            print(f"  case_id={row['case_id']}  sbt_start={row['sbt_start']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--input",
        type=Path,
        default=Path("data/icu_event_log_sample.parquet"),
    )
    args = ap.parse_args()
    check(args.input)
