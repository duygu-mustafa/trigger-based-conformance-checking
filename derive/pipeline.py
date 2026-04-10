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

    activity_df = emit_activities(
        raw_df,
        item_dictionary_path=item_dictionary_path
        or Path(__file__).resolve().parents[1] / "configs" / "item_dictionary.yaml",
        activity_mapping_path=activity_mapping_path
        or Path(__file__).resolve().parents[1] / "configs" / "activity_mapping.yaml",
    )
    return build_event_log(activity_df)


def run_full_pipeline(
    raw_events_df: pd.DataFrame,
    weaning_df: pd.DataFrame,
    *,
    item_dictionary_path: str | Path | None = None,
    activity_mapping_path: str | Path | None = None,
) -> pd.DataFrame:
    """Run the complete pipeline including derived weaning episodes.
    
    Combines raw observation events with derived SBT start/end events
    before passing them through the activity emitter.
    """
    # 1. Derive SBT episodes from weaning states
    episodes = build_sbt_episodes(weaning_df)
    
    # 2. Convert episodes to event-like rows
    sbt_events = sbt_episodes_to_events(episodes)
    
    # 3. Combine with raw observations
    # Ensure raw_events_df has required columns
    combined_df = pd.concat([raw_events_df, sbt_events], ignore_index=True)
    
    # 4. Map activities and finalize event log
    return raw_to_event_log(
        combined_df,
        item_dictionary_path=item_dictionary_path,
        activity_mapping_path=activity_mapping_path
    )
