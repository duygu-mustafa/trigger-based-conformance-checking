"""Simplified derive pipeline entry points.

Prefer importing from this file in notebooks and scripts.
"""

from pathlib import Path
from typing import Any

from derive.activity_emitter import emit_activities
from derive.readiness_features import derive_readiness_features
from derive.sbt_episodes import build_sbt_episodes
from conformance.event_log_builder import build_event_log


__all__ = [
    "derive_readiness_features",
    "build_sbt_episodes",
    "emit_activities",
    "raw_to_event_log",
]


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
