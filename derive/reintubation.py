"""Helpers to detect intubation after SBT in canonical event logs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def detect_intubation_after_sbt(
    event_log: pd.DataFrame,
    window_hours: float = 48.0,
    return_positive_sbt_events: bool = False,
) -> pd.DataFrame | tuple[pd.DataFrame, pd.DataFrame]:
    """Return one row per case with intubation-after-SBT detection.

    Expected input columns are the canonical event-log columns, especially:
    - case_id
    - activity
    - timestamp

    The check uses mapped activities:
    - SBTStarted
    - Intubation

    A case is counted as positive only if Intubation occurs within
    ``window_hours`` after the first SBTStarted timestamp.

    Args:
        event_log: Canonical event log dataframe.
        window_hours: Maximum allowed delay from SBT to Intubation.
        return_positive_sbt_events: If True, also return a dataframe of
            SBTStarted events that have a qualifying intubation afterward.

    Returns:
        By default, a case-level summary dataframe.
        If return_positive_sbt_events is True, returns a tuple:
            (summary_df, positive_sbt_events_df)
    """
    required = {"case_id", "activity", "timestamp"}
    missing = required - set(event_log.columns)
    if missing:
        raise ValueError(f"Event log missing required columns for reintubation check: {sorted(missing)}")

    df = event_log.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["case_id", "activity", "timestamp"]).copy()

    rows: list[dict[str, object]] = []
    positive_sbt_rows: list[dict[str, object]] = []
    for case_id, g in df.sort_values("timestamp").groupby("case_id", sort=False):
        sbt = g[g["activity"] == "SBTStarted"]
        intub = g[g["activity"] == "Intubation"]

        first_sbt_ts = sbt["timestamp"].min() if not sbt.empty else pd.NaT
        first_intub_after_sbt_ts = pd.NaT
        if pd.notna(first_sbt_ts) and not intub.empty:
            later = intub[intub["timestamp"] > first_sbt_ts]
            if not later.empty:
                max_ts = first_sbt_ts + pd.Timedelta(hours=float(window_hours))
                in_window = later[later["timestamp"] <= max_ts]
                if not in_window.empty:
                    first_intub_after_sbt_ts = in_window["timestamp"].min()

        # Keep per-SBT matches for downstream inspection when requested.
        if return_positive_sbt_events and not sbt.empty and not intub.empty:
            for sbt_ts in sbt["timestamp"].tolist():
                later = intub[intub["timestamp"] > sbt_ts]
                if later.empty:
                    continue
                max_ts = sbt_ts + pd.Timedelta(hours=float(window_hours))
                in_window = later[later["timestamp"] <= max_ts]
                if in_window.empty:
                    continue

                matched_intub_ts = in_window["timestamp"].min()
                positive_sbt_rows.append(
                    {
                        "case_id": str(case_id),
                        "sbt_timestamp": sbt_ts,
                        "matched_intubation_timestamp": matched_intub_ts,
                        "hours_from_sbt_to_intubation": (matched_intub_ts - sbt_ts).total_seconds()
                        / 3600.0,
                        "window_hours": float(window_hours),
                    }
                )

        hours_to_intub = np.nan
        if pd.notna(first_sbt_ts) and pd.notna(first_intub_after_sbt_ts):
            hours_to_intub = (first_intub_after_sbt_ts - first_sbt_ts).total_seconds() / 3600.0

        rows.append(
            {
                "case_id": str(case_id),
                "n_sbt_started": int(len(sbt)),
                "n_intubation": int(len(intub)),
                "window_hours": float(window_hours),
                "first_sbt_started_ts": first_sbt_ts,
                "first_intubation_after_sbt_ts": first_intub_after_sbt_ts,
                "intubation_after_sbt": bool(pd.notna(first_intub_after_sbt_ts)),
                "hours_from_sbt_to_intubation": hours_to_intub,
            }
        )

    summary_df = pd.DataFrame(rows)
    if not return_positive_sbt_events:
        return summary_df

    positive_sbt_events_df = pd.DataFrame(
        positive_sbt_rows,
        columns=[
            "case_id",
            "sbt_timestamp",
            "matched_intubation_timestamp",
            "hours_from_sbt_to_intubation",
            "window_hours",
        ],
    )
    return summary_df, positive_sbt_events_df
