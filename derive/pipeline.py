"""Simplified derive pipeline entry points.

Prefer importing from this file in notebooks and scripts.
"""

from pathlib import Path
from typing import Any

import pandas as pd

from derive.activity_emitter import emit_activities
from derive.readiness_features import derive_readiness_features
from derive.sbt_episodes import build_sbt_episodes as _build_sbt_episodes
from conformance.event_log_builder import build_event_log


__all__ = [
    "derive_readiness_features",
    "build_sbt_episodes",
    "emit_activities",
    "raw_to_event_log",
]


def build_sbt_episodes(weaning_df: pd.DataFrame) -> pd.DataFrame:
    """Wrapper for sbt_episodes.build_sbt_episodes with thesis-specific defaults."""
    return _build_sbt_episodes(weaning_df)


def sbt_episodes_to_events(episodes_df: pd.DataFrame) -> pd.DataFrame:
    """Transform SBT episodes into normalized event rows for the activity emitter."""
    events = []
    for _, row in episodes_df.iterrows():
        # Start event
        events.append({
            'source_table': 'sbt_derived',
            'stay_id': row['stay_id'],
            'event_time': row['sbt_start_time'],
            'itemid': 'sbt_status',
            'label': 'SBT status',
            'value_text': 'Started',
            'value_num': 1.0
        })
        
        # End event
        outcome_time = row.get('extubation_time') or row.get('failure_time') or row.get('last_time')
        if outcome_time:
            events.append({
                'source_table': 'sbt_derived',
                'stay_id': row['stay_id'],
                'event_time': outcome_time,
                'itemid': 'sbt_outcome',
                'label': 'SBT outcome',
                'value_text': 'Success' if row['is_success'] else 'Failure',
                'value_num': 1.0 if row['is_success'] else 0.0
            })
            
    return pd.DataFrame(events)


def _last_valid(series: pd.Series) -> object:
    non_null = series.dropna()
    if non_null.empty:
        return None
    return non_null.iloc[-1]


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

    working["ventilation_status"] = working.apply(
        lambda row: row.get("value_text")
        if str(row.get("source_table")) == "ventilation" and str(row.get("itemid")) == "ventilation_status"
        else None,
        axis=1,
    )
    working["ventilator_mode"] = working.apply(
        lambda row: row.get("value_text")
        if str(row.get("source_table")) == "ventilator_setting" and str(row.get("itemid")) == "ventilator_mode"
        else None,
        axis=1,
    )
    working["ventilator_mode_hamilton"] = working.apply(
        lambda row: row.get("value_text")
        if str(row.get("source_table")) == "ventilator_setting" and str(row.get("itemid")) == "ventilator_mode_hamilton"
        else None,
        axis=1,
    )
    working["plateau_pressure"] = working.apply(
        lambda row: row.get("value_num")
        if str(row.get("source_table")) == "ventilator_setting" and str(row.get("itemid")) == "plateau_pressure"
        else None,
        axis=1,
    )
    working["peep"] = working.apply(
        lambda row: row.get("value_num")
        if str(row.get("source_table")) == "ventilator_setting" and str(row.get("itemid")) == "peep_vent"
        else None,
        axis=1,
    )

    if not working[["ventilation_status", "ventilator_mode", "ventilator_mode_hamilton", "plateau_pressure", "peep"]].notna().any().any():
        return pd.DataFrame()

    grouped = (
        working.sort_values(["stay_id", "event_time"])
        .groupby(["stay_id", "event_time"], as_index=False)
        .agg(
            {
                "ventilation_status": _last_valid,
                "ventilator_mode": _last_valid,
                "ventilator_mode_hamilton": _last_valid,
                "plateau_pressure": _last_valid,
                "peep": _last_valid,
            }
        )
    )

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
        "ventilation_status",
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


def _explicit_invasive_vent_start_times_from_raw(raw_df: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Return the first explicit invasive ventilation start timestamp per stay."""

    required = {"stay_id", "source_table", "itemid"}
    if not required.issubset(raw_df.columns):
        return {}

    working = raw_df.copy()
    if "starttime" in working.columns:
        working["starttime"] = pd.to_datetime(working["starttime"], errors="coerce")
    if "event_time" in working.columns:
        working["event_time"] = pd.to_datetime(working["event_time"], errors="coerce")

    mask = (
        working["source_table"].astype(str).eq("procedureevents")
        & working["itemid"].astype(str).eq("225792")
    )
    if not mask.any():
        return {}

    candidates = working.loc[mask, ["stay_id"] + (["starttime"] if "starttime" in working.columns else []) + (["event_time"] if "event_time" in working.columns else [])].copy()
    if candidates.empty:
        return {}

    if "starttime" in candidates.columns:
        start_ts = candidates["starttime"].where(candidates["starttime"].notna(), candidates.get("event_time"))
    else:
        start_ts = candidates["event_time"]

    candidates = candidates.assign(start_ts=pd.to_datetime(start_ts, errors="coerce"))
    candidates = candidates.dropna(subset=["stay_id", "start_ts"])
    if candidates.empty:
        return {}

    start_times: dict[str, pd.Timestamp] = {}
    for stay_id, group in candidates.groupby("stay_id", sort=False):
        start_times[str(stay_id)] = group["start_ts"].min()

    return start_times


def _invasive_vent_start_times_from_raw(raw_df: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Return invasive ventilation start timestamp per stay from inferred Full Support only."""

    return _full_support_start_times_from_settings(raw_df)


def _is_sbt_candidate_state(mode: object, mode_hamilton: object, plateau_pressure: object, peep: object) -> bool:
    mode_text = str(mode).strip() if mode is not None else ""
    mode_h_text = str(mode_hamilton).strip() if mode_hamilton is not None else ""

    if mode_h_text in {"Ambient", "SPONT", "CPAP"}:
        return True

    if mode_h_text == "ASV":
        try:
            if pd.notna(plateau_pressure) and pd.notna(peep):
                if float(plateau_pressure) - float(peep) <= 8.0:
                    return True
        except (TypeError, ValueError):
            pass

    if mode_text in {"CPAP", "CPAP/PSV", "Pressure Support", "Standby", "Spontaneous"}:
        return True

    return False


def _full_support_start_times_from_settings(raw_df: pd.DataFrame) -> dict[str, pd.Timestamp]:
    """Fallback invasive-vent onset from ventilator settings classified as Full Support."""

    weaning_df = _derive_weaning_frame_from_raw(raw_df)
    if weaning_df.empty:
        return {}

    working = weaning_df.copy()
    working["charttime"] = pd.to_datetime(working["charttime"], errors="coerce")
    working = working.dropna(subset=["stay_id", "charttime"])
    if working.empty:
        return {}

    full_support_mask = ~working.apply(
        lambda row: _is_sbt_candidate_state(
            row.get("ventilator_mode"),
            row.get("ventilator_mode_hamilton"),
            row.get("plateau_pressure"),
            row.get("peep"),
        ),
        axis=1,
    )
    full_support_rows = working.loc[full_support_mask, ["stay_id", "charttime"]]
    if full_support_rows.empty:
        return {}

    start_times: dict[str, pd.Timestamp] = {}
    for stay_id, group in full_support_rows.groupby("stay_id", sort=False):
        start_times[str(stay_id)] = group["charttime"].min()
    return start_times


def _synthesize_invasive_vent_events_from_settings(raw_df: pd.DataFrame) -> pd.DataFrame:
    """Create synthetic procedureevents(225792) starts from inferred Full Support onset."""

    fallback_starts = _full_support_start_times_from_settings(raw_df)
    if not fallback_starts:
        return pd.DataFrame()

    synthetic_rows: list[dict[str, object]] = []
    for stay_id_text in fallback_starts.keys():
        stay_mask = raw_df.get("stay_id", pd.Series(index=raw_df.index, dtype=object)).astype(str).eq(stay_id_text)
        stay_rows = raw_df.loc[stay_mask]

        row: dict[str, object] = {
            "source_table": "procedureevents",
            "stay_id": int(stay_id_text) if stay_id_text.isdigit() else stay_id_text,
            "event_time": fallback_starts[stay_id_text],
            "starttime": fallback_starts[stay_id_text],
            "endtime": pd.NaT,
            "itemid": 225792,
            "label": "Invasive Ventilation (Derived from Full Support)",
            "value_text": "derived_full_support_onset",
            "value_num": None,
            "value_uom": None,
        }

        for optional_col in ["case_id", "subject_id", "hadm_id", "charttime", "storetime"]:
            if optional_col in raw_df.columns:
                non_null = stay_rows[optional_col].dropna()
                row[optional_col] = non_null.iloc[0] if not non_null.empty else None

        synthetic_rows.append(row)

    return pd.DataFrame(synthetic_rows)


def _load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to load pipeline config. Install with `pip install pyyaml`."
        ) from exc

    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Invalid pipeline config at {path}: expected top-level mapping")
    return data


def raw_to_event_log(
    raw_df,
    *,
    pipeline_config_path: str | Path | None = None,
    item_dictionary_path: str | Path | None = None,
    activity_mapping_path: str | Path | None = None,
):
    """Run configured map/derive steps to produce canonical checker event log.

    The current implementation always builds mapped activities and forwards the
    resulting dataframe to the canonical event-log normalizer.
    """
    if pipeline_config_path is not None:
        # Validates config file existence/shape now and keeps compatibility with
        # the run_* switches for future staged execution.
        _load_yaml(pipeline_config_path)

    raw_df = _remove_explicit_invasive_vent_rows(raw_df)

    synthetic_invasive_events = _synthesize_invasive_vent_events_from_settings(raw_df)
    if not synthetic_invasive_events.empty:
        raw_df = pd.concat([raw_df, synthetic_invasive_events], ignore_index=True)

    weaning_df = _derive_weaning_frame_from_raw(raw_df)
    if not weaning_df.empty:
        invasive_start_times = _invasive_vent_start_times_from_raw(raw_df)
        episodes = build_sbt_episodes(weaning_df)
        if not episodes.empty and invasive_start_times:
            episodes = episodes[
                episodes.apply(
                    lambda row: (
                        str(row["stay_id"]) in invasive_start_times
                        and pd.to_datetime(row["sbt_start_time"], errors="coerce") >= invasive_start_times[str(row["stay_id"])]
                    ),
                    axis=1,
                )
            ].copy()
        else:
            episodes = episodes.iloc[0:0] if not invasive_start_times else episodes

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
