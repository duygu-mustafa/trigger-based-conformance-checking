#!/usr/bin/env python3
"""
Check that every SBTStarted event in the event log has a subsequent
SBTCompleted / SBTFailed / SBTSucceeded event within the same case.
"""
import argparse
from pathlib import Path
import pandas as pd

SBT_START = "SBTStarted"
SBT_END = {"SBTFailed", "SBTSucceeded"}
SBT_SUCCESS = "SBTSucceeded"
SBT_FAILURE = "SBTFailed"
VENT_START = "InvasiveVentilationStarted"


def check(path: Path) -> None:
    df = pd.read_parquet(path, columns=["case_id", "activity", "timestamp"])
    df = df.sort_values(["case_id", "timestamp"])

    unpaired = []
    total_starts = 0
    total_success = 0
    total_failure = 0
    total_episodes = 0
    no_sbt_attempt_eps = 0

    for case_id, grp in df.groupby("case_id"):
        starts = grp[grp["activity"] == SBT_START]["timestamp"].tolist()
        ends = grp[grp["activity"].isin(SBT_END)]["timestamp"].tolist()

        total_success += (grp["activity"] == SBT_SUCCESS).sum()
        total_failure += (grp["activity"] == SBT_FAILURE).sum()

        for start_ts in starts:
            total_starts += 1
            matched = any(e >= start_ts for e in ends)
            if not matched:
                unpaired.append({"case_id": case_id, "sbt_start": start_ts})

        # Count vent-bounded episodes without any SBTStarted
        vents = grp[grp["activity"] == VENT_START]["timestamp"].sort_values().tolist()
        if vents:
            trace_end = grp["timestamp"].max() + pd.Timedelta(seconds=1)
            boundaries = vents + [trace_end]
            for i, ep_start in enumerate(vents):
                ep_end = boundaries[i + 1]
                ep_acts = set(grp[(grp["timestamp"] >= ep_start) & (grp["timestamp"] < ep_end)]["activity"])
                total_episodes += 1
                if SBT_START not in ep_acts:
                    no_sbt_attempt_eps += 1

    paired = total_starts - len(unpaired)
    pct = 100 * paired / total_starts if total_starts else 0

    print(f"Total SBTStarted events : {total_starts}")
    print(f"Unpaired (no end event) : {len(unpaired)}")
    print(f"Pairing rate            : {pct:.1f}%")
    print()
    print(f"SBTSucceeded            : {total_success}")
    print(f"SBTFailed               : {total_failure}")
    outcome_total = total_success + total_failure
    print(f"Success + Failure       : {outcome_total}")
    if total_starts > 0:
        missing = total_starts - outcome_total
        print(f"SBTStarted w/o outcome  : {missing}  ({'OK' if missing == 0 else 'MISMATCH'})")
    print()
    print(f"Total vent episodes     : {total_episodes}")
    print(f"No SBT attempt          : {no_sbt_attempt_eps}")
    if total_episodes > 0:
        print(f"No-SBT rate             : {100 * no_sbt_attempt_eps / total_episodes:.1f}%")

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
