from __future__ import annotations

import pandas as pd


CANONICAL_EVENT_LOG_COLUMNS = [
    "case_id",
    "activity",
    "timestamp",
    "source_table",
    "itemid",
    "value_raw",
    "value_num",
    "unit",
    "attrs",
    "patient_id",
    "stay_id",
]


def build_event_log(activity_df: pd.DataFrame) -> pd.DataFrame:
    """Normalize activity dataframe to canonical conformance event-log schema."""
    missing = [c for c in ["case_id", "activity", "timestamp"] if c not in activity_df.columns]
    if missing:
        raise ValueError(f"Missing required event-log columns: {missing}")

    out = activity_df.copy()
    for c in CANONICAL_EVENT_LOG_COLUMNS:
        if c not in out.columns:
            out[c] = None

    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
    out = out.dropna(subset=["case_id", "activity", "timestamp"])

    # MIMIC-IV charttime is minute-precision, so many events in a case share an
    # exact timestamp. Break ties on activity/itemid so ordering is deterministic
    # and reproducible across runs, independent of upstream row order — this does
    # not resolve the underlying temporal ambiguity, only makes it consistent.
    return (
        out[CANONICAL_EVENT_LOG_COLUMNS]
        .sort_values(["case_id", "timestamp", "activity", "itemid"], kind="stable")
        .reset_index(drop=True)
    )
