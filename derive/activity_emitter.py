"""Convert raw ICU event rows into checker-ready activity rows.

This module reads:
- configs/item_dictionary.yaml (itemid -> canonical signal labels)
- configs/activity_mapping.yaml (itemid/value -> modeled activities)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from derive.value_converter import convert_categorical_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEM_DICTIONARY_PATH = PROJECT_ROOT / "configs" / "item_dictionary.yaml"
DEFAULT_ACTIVITY_MAPPING_PATH = PROJECT_ROOT / "configs" / "activity_mapping.yaml"


def _load_yaml(path: str | Path) -> dict[str, Any]:
    try:
        import yaml
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "PyYAML is required to load mapping configs. Install with `pip install pyyaml`."
        ) from exc

    with Path(path).open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML structure in {path}: expected top-level mapping")
    return data


def _item_label_lookup(item_dictionary: dict[str, Any]) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    sources = item_dictionary.get("sources", {})
    if not isinstance(sources, dict):
        return out

    for source, mapping in sources.items():
        if not isinstance(source, str) or not isinstance(mapping, dict):
            continue
        for itemid_raw, name in mapping.items():
            try:
                itemid = int(itemid_raw)
            except (TypeError, ValueError):
                continue
            if isinstance(name, str) and name.strip():
                out[(source, itemid)] = name.strip()
    return out


def _activity_rules(activity_mapping: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    mappings = activity_mapping.get("mappings", {})
    if not isinstance(mappings, dict):
        return out

    for activity, cfg in mappings.items():
        if not isinstance(activity, str) or not isinstance(cfg, dict):
            continue
        if cfg.get("derived"):
            continue
        source = cfg.get("source")
        itemid_raw = cfg.get("itemid")
        if not isinstance(source, str):
            continue
        try:
            itemid = int(itemid_raw)
        except (TypeError, ValueError):
            continue

        value_equals = None
        conditions = cfg.get("conditions")
        if isinstance(conditions, dict) and conditions.get("value_equals") is not None:
            value_equals = str(conditions["value_equals"])

        timestamp_field = cfg.get("timestamp_field")
        if timestamp_field is not None:
            timestamp_field = str(timestamp_field)

        out.append(
            {
                "activity": activity,
                "source": source,
                "itemid": itemid,
                "value_equals": value_equals,
                "timestamp_field": timestamp_field,
            }
        )
    return out


def _normalize_raw_input(raw_df: pd.DataFrame) -> pd.DataFrame:
    out = raw_df.copy()

    if "event_time" not in out.columns:
        for candidate in ["charttime", "starttime", "endtime", "storetime"]:
            if candidate in out.columns:
                out["event_time"] = out[candidate]
                break

    required = ["source_table", "itemid", "event_time"]
    missing = [c for c in required if c not in out.columns]
    if missing:
        raise ValueError(f"Raw input is missing required columns: {missing}")

    if "value_text" not in out.columns:
        out["value_text"] = out.get("value")
    if "value_num" not in out.columns:
        out["value_num"] = out.get("valuenum")
    if "value_uom" not in out.columns:
        out["value_uom"] = out.get("valueuom")

    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    out["itemid"] = pd.to_numeric(out["itemid"], errors="coerce")
    out["value_num"] = pd.to_numeric(out["value_num"], errors="coerce")

    for ts_col in ["charttime", "starttime", "endtime", "storetime"]:
        if ts_col in out.columns:
            out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")

    out = out.dropna(subset=["event_time", "itemid"]).copy()
    out["itemid"] = out["itemid"].astype(int)
    return out


def _measurement_activity_label(row: pd.Series, labels: dict[tuple[str, int], str]) -> str:
    source = str(row.get("source_table") or "")
    itemid = int(row["itemid"])
    mapped = labels.get((source, itemid))
    if mapped:
        return mapped

    label = row.get("label")
    if label is not None and str(label).strip():
        return str(label).strip()

    return f"item_{itemid}"


def emit_activities(
    raw_df: pd.DataFrame,
    *,
    item_dictionary_path: str | Path = DEFAULT_ITEM_DICTIONARY_PATH,
    activity_mapping_path: str | Path = DEFAULT_ACTIVITY_MAPPING_PATH,
) -> pd.DataFrame:
    """Emit activity rows from raw ICU events using YAML configuration.

    Returns a dataframe already aligned with the canonical event-log schema fields.
    """
    raw = _normalize_raw_input(raw_df)
    raw = convert_categorical_values(raw)
    item_dictionary = _load_yaml(item_dictionary_path)
    activity_mapping = _load_yaml(activity_mapping_path)
    labels = _item_label_lookup(item_dictionary)
    rules = _activity_rules(activity_mapping)

    case_series = (
        raw.get("case_id")
        if "case_id" in raw.columns
        else raw.get("stay_id", pd.Series("unknown", index=raw.index, dtype=object))
    )

    measurement_df = pd.DataFrame(
        {
            "case_id": case_series.astype(str),
            "activity": raw.apply(lambda r: _measurement_activity_label(r, labels), axis=1),
            "timestamp": raw["event_time"],
            "source_table": raw["source_table"],
            "itemid": raw["itemid"],
            "value_raw": raw.get("value_text"),
            "value_num": raw.get("value_num"),
            "unit": raw.get("value_uom"),
            "attrs": [{"kind": "measurement"}] * len(raw),
            "patient_id": raw.get("subject_id"),
            "stay_id": raw.get("stay_id"),
        }
    )

    mapped_frames: list[pd.DataFrame] = []
    for rule in rules:
        mask = (raw["source_table"] == rule["source"]) & (raw["itemid"] == rule["itemid"])
        value_equals = rule.get("value_equals")
        if value_equals is not None:
            raw_values = raw.get("value_text", pd.Series(index=raw.index, dtype=object)).astype(str)
            mask = mask & raw_values.str.strip().str.lower().eq(str(value_equals).strip().lower())

        subset = raw[mask].copy()
        if subset.empty:
            continue

        ts_col = rule.get("timestamp_field") or "event_time"
        if ts_col not in subset.columns:
            ts_col = "event_time"

        mapped = pd.DataFrame(
            {
                "case_id": (
                    subset.get("case_id")
                    if "case_id" in subset.columns
                    else subset.get("stay_id", pd.Series("unknown", index=subset.index, dtype=object))
                ).astype(str),
                "activity": rule["activity"],
                "timestamp": pd.to_datetime(subset[ts_col], errors="coerce"),
                "source_table": subset["source_table"],
                "itemid": subset["itemid"],
                "value_raw": subset.get("value_text"),
                "value_num": subset.get("value_num"),
                "unit": subset.get("value_uom"),
                "attrs": [
                    {
                        "kind": "mapped_activity",
                        "timestamp_field": ts_col,
                    }
                ]
                * len(subset),
                "patient_id": subset.get("subject_id"),
                "stay_id": subset.get("stay_id"),
            }
        )
        mapped = mapped.dropna(subset=["timestamp"])
        if not mapped.empty:
            mapped_frames.append(mapped)

    all_frames = [measurement_df, *mapped_frames]
    out = pd.concat(all_frames, ignore_index=True)
    out = out.dropna(subset=["case_id", "activity", "timestamp"]).copy()
    return out.sort_values(["case_id", "timestamp", "activity"]).reset_index(drop=True)
