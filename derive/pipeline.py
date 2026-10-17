"""Raw MIMIC-IV rows -> canonical event log.

raw_to_event_log() is the entry point used by prepare_event_log.py and the
conformance runners. Per stay it
  1. drops explicit procedureevents 225792 (invasive ventilation) rows and infers
     InvasiveVentilationStarted/Ended from ventilator settings instead
     (Full Support onset/offset),
  2. reconstructs SBT episodes from ventilator-mode transitions
     (derive/sbt_episodes.py) and emits one SBTStarted anchor per episode,
  3. maps rows to activities and derives outcome and criterion activities
     (derive/activity_emitter.py, configs/activity_mapping.yaml),
  4. normalizes the result to the canonical schema
     (conformance/event_log_builder.py).
"""

from pathlib import Path

import pandas as pd

from derive.activity_emitter import emit_activities
from derive.sbt_episodes import build_sbt_episodes as _build_sbt_episodes, vectorized_weaning_states
from conformance.event_log_builder import build_event_log


__all__ = [
    "build_sbt_episodes",
    "emit_activities",
    "raw_to_event_log",
]


def build_sbt_episodes(weaning_df: pd.DataFrame) -> pd.DataFrame:
    """Build SBT episodes from a weaning frame (sbt_episodes.build_sbt_episodes, default parameters)."""
    return _build_sbt_episodes(weaning_df)


def sbt_episodes_to_events(episodes_df: pd.DataFrame) -> pd.DataFrame:
    """Transform SBT episodes into normalized event rows for the activity emitter.

    Emits only SBTStarted anchors. Outcomes (SBTFailed/SBTSucceeded) are
    derived downstream in activity_emitter._derive_activities() via the
    48-hour re-ventilation rule.
    """
    events = []
    for _, row in episodes_df.iterrows():
        events.append({
            'source_table': 'sbt_derived',
            'stay_id': row['stay_id'],
            'event_time': row['sbt_start_time'],
            'itemid': 'sbt_status',
            'label': 'SBT status',
            'value_text': 'Started',
            'value_num': 1.0
        })
    return pd.DataFrame(events)


_MISSING_TEXT_TOKENS = {"", "none", "null", "nan", "nat", "[null]", "<na>"}


def _is_missing_text_value(value: object) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip().lower()
    return text in _MISSING_TEXT_TOKENS


def _non_missing_text_mask(series: pd.Series) -> pd.Series:
    return ~series.map(_is_missing_text_value)


def _derive_weaning_frame_from_raw(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Reconstruct a weaning frame from long-form raw event rows.

    This lets the default raw-to-event-log pipeline call the SBT episode builder
    without requiring a separate weaning file.
    """

    required = {"stay_id", "event_time", "source_table", "itemid"}
    if not required.issubset(raw_df.columns):
        return pd.DataFrame()

    working = raw_df.copy()
    working["event_time"] = pd.to_datetime(working["event_time"], errors="coerce")
    working = working.dropna(subset=["stay_id", "event_time"]).copy()
    if working.empty:
        return pd.DataFrame()

    # If raw rows already carry wide ventilator setting columns, keep only rows
    # where at least one mode column has a non-empty value.
    if {"ventilator_mode", "ventilator_mode_hamilton"}.issubset(working.columns):
        mode_a = working["ventilator_mode"]
        mode_b = working["ventilator_mode_hamilton"]
        mode_a_missing = ~_non_missing_text_mask(mode_a)
        mode_b_missing = ~_non_missing_text_mask(mode_b)
        working = working.loc[~(mode_a_missing & mode_b_missing)].copy()
        if working.empty:
            return pd.DataFrame()

    # Ignore empty ventilator mode observations; they can create artificial
    # Full Support/SBT transitions when alternated with real mode values.
    mode_setting_mask = (
        working["source_table"].astype(str).eq("ventilator_setting")
        & working["itemid"].astype(str).isin({"ventilator_mode", "ventilator_mode_hamilton"})
    )
    mode_value = working.get("value_text", pd.Series(index=working.index, dtype=object))
    mode_missing_mask = ~_non_missing_text_mask(mode_value)
    working = working.loc[~(mode_setting_mask & mode_missing_mask)].copy()
    if working.empty:
        return pd.DataFrame()

    vent_mask = working["source_table"].astype(str).eq("ventilator_setting")
    itemid_s = working["itemid"].astype(str)
    _vtext = working.get("value_text", pd.Series(index=working.index, dtype=object))
    _vnum = working.get("value_num", pd.Series(index=working.index, dtype=object))

    working["ventilator_mode"] = _vtext.where(vent_mask & itemid_s.eq("ventilator_mode"))
    working["ventilator_mode_hamilton"] = _vtext.where(vent_mask & itemid_s.eq("ventilator_mode_hamilton"))
    working["plateau_pressure"] = _vnum.where(vent_mask & itemid_s.eq("plateau_pressure"))
    working["peep"] = _vnum.where(vent_mask & itemid_s.eq("peep_vent"))

    setting_cols = ["ventilator_mode", "ventilator_mode_hamilton", "plateau_pressure", "peep"]
    if not working[setting_cols].notna().any().any():
        return pd.DataFrame()

    grouped = (
        working.sort_values(["stay_id", "event_time"])
        .groupby(["stay_id", "event_time"], as_index=False)[setting_cols]
        .last()
    )

    if grouped.empty:
        return grouped

    # Keep only rows with at least one non-null setting value.
    mode_non_empty = grouped[["ventilator_mode", "ventilator_mode_hamilton"]].apply(
        _non_missing_text_mask,
    )
    numeric_non_null = grouped[["plateau_pressure", "peep"]].notna()
    keep_mask = pd.concat([mode_non_empty, numeric_non_null], axis=1).any(axis=1)
    grouped = grouped.loc[keep_mask].copy()
    if grouped.empty:
        return grouped

    grouped = grouped.rename(columns={"event_time": "charttime"})
    grouped["starttime"] = grouped["charttime"]
    grouped["endtime"] = grouped["charttime"]
    return grouped[[
        "stay_id",
        "charttime",
        "starttime",
        "endtime",
        "ventilator_mode",
        "ventilator_mode_hamilton",
        "plateau_pressure",
        "peep",
    ]]


def _remove_explicit_invasive_vent_rows(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Drop explicit procedureevents 225792 rows to enforce inferred-only semantics."""

    required = {"source_table", "itemid"}
    if not required.issubset(raw_df.columns):
        return raw_df

    mask = (
        raw_df["source_table"].astype(str).eq("procedureevents")
        & raw_df["itemid"].astype(str).eq("225792")
    )
    if not mask.any():
        return raw_df

    return raw_df.loc[~mask].copy()


def _full_support_start_times_from_settings(raw_df: pd.DataFrame) -> dict[str, list[pd.Timestamp]]:
    """Infer invasive ventilation (start, end) pairs per stay from ventilator settings.

    A start is emitted at the first observed Full Support mode and at each
    transition from non-Full-Support to Full Support; the end is the first
    transition back to non-Full-Support after it (None if there is none).
    """

    weaning_df = _derive_weaning_frame_from_raw(raw_df)
    if weaning_df.empty:
        return {}

    working = weaning_df.copy()
    working["charttime"] = pd.to_datetime(working["charttime"], errors="coerce")
    working = working.dropna(subset=["stay_id", "charttime"])
    if working.empty:
        return {}

    working = working.sort_values(["stay_id", "charttime"]).copy()
    states = vectorized_weaning_states(working)
    # "Other" rows (e.g. peep-only, no mode) are neutral: drop them so they
    # can't open or close a full-support episode.
    working = working.loc[states != "Other"].copy()
    if working.empty:
        return {}
    working["is_full_support"] = states.loc[working.index].eq("Full Support")

    start_end_times: dict[str, list[tuple[pd.Timestamp, pd.Timestamp | None]]] = {}
    for stay_id, group in working.groupby("stay_id", sort=False):
        g = group.sort_values("charttime").copy()
        prev_full = g["is_full_support"].shift(1)
        
        # Starts: transition from non-full (or start of data) to full support
        start_mask = g["is_full_support"] & ((prev_full != True) | prev_full.isna())
        
        # Ends: transition from full support to non-full support
        end_mask = (prev_full == True) & (g["is_full_support"] != True)
        
        starts = g.loc[start_mask, "charttime"].tolist()
        ends = g.loc[end_mask, "charttime"].tolist()
        
        # Pair them up
        pairs = []
        for s_ts in starts:
            # Find the first end after this start
            e_ts = next((e for e in ends if e > s_ts), None)
            pairs.append((s_ts, e_ts))
            
        if pairs:
            start_end_times[str(stay_id)] = pairs

    return start_end_times


def _synthesize_invasive_vent_events_from_settings(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Create synthetic invasive-ventilation start and end triggers per inferred episode."""

    episode_times = _full_support_start_times_from_settings(raw_df)
    if not episode_times:
        return pd.DataFrame()

    synthetic_rows: list[dict[str, object]] = []
    for stay_id_text, episodes in episode_times.items():
        stay_mask = raw_df.get("stay_id", pd.Series(index=raw_df.index, dtype=object)).astype(str).eq(stay_id_text)
        stay_rows = raw_df.loc[stay_mask]

        for start_ts, end_ts in episodes:
            # Common attributes
            base_row: dict[str, object] = {
                "source_table": "ventilator_derived",
                "stay_id": int(stay_id_text) if stay_id_text.isdigit() else stay_id_text,
            }
            for optional_col in ["case_id", "subject_id", "hadm_id", "charttime", "storetime"]:
                if optional_col in raw_df.columns:
                    non_null = stay_rows[optional_col].dropna()
                    base_row[optional_col] = non_null.iloc[0] if not non_null.empty else None

            # Start event
            start_row = base_row.copy()
            start_row.update({
                "event_time": start_ts,
                "starttime": start_ts,
                "endtime": pd.NaT,
                "itemid": "derived_invasive_ventilation_start",
                "label": "Invasive Ventilation Started (Derived)",
                "value_text": "derived_full_support_onset",
            })
            synthetic_rows.append(start_row)

            # End event (if exists)
            if end_ts and not pd.isna(end_ts):
                end_row = base_row.copy()
                end_row.update({
                    "event_time": end_ts,
                    "starttime": pd.NaT,
                    "endtime": end_ts,
                    "itemid": "derived_invasive_ventilation_end",
                    "label": "Invasive Ventilation Ended (Derived)",
                    "value_text": "derived_full_support_offset",
                })
                synthetic_rows.append(end_row)

    return pd.DataFrame(synthetic_rows)


def raw_to_event_log(
    raw_df,
    *,
    item_dictionary_path: str | Path | None = None,
    activity_mapping_path: str | Path | None = None,
):
    """Convert raw event rows (one or more stays) into the canonical event log.

    See the module docstring for the steps. Previously derived SBT rows
    (source_table 'sbt_derived') in the input are discarded and rebuilt.
    """
    if "source_table" in raw_df.columns:
        raw_df = raw_df[raw_df["source_table"].ne("sbt_derived")].copy()
    raw_df = _remove_explicit_invasive_vent_rows(raw_df)

    synthetic_invasive_events = _synthesize_invasive_vent_events_from_settings(raw_df)
    if not synthetic_invasive_events.empty:
        raw_df = pd.concat([raw_df, synthetic_invasive_events], ignore_index=True)

    weaning_df = _derive_weaning_frame_from_raw(raw_df)
    if not weaning_df.empty:
        # Keep all detected SBT episodes; trigger-based episode segmentation is
        # done later, in main.py.
        episodes = build_sbt_episodes(weaning_df)
        sbt_events = sbt_episodes_to_events(episodes)
        if not sbt_events.empty:
            raw_df = pd.concat([raw_df, sbt_events], ignore_index=True)

    activity_df = emit_activities(
        raw_df,
        item_dictionary_path=item_dictionary_path
        or Path(__file__).resolve().parents[1] / "configs" / "item_dictionary.yaml",
        activity_mapping_path=activity_mapping_path
        or Path(__file__).resolve().parents[1] / "configs" / "activity_mapping.yaml",
    )
    return build_event_log(activity_df)
