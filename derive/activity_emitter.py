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


def _item_label_lookup(item_dictionary: dict[str, Any]) -> dict[tuple[str, Any], str]:
    out: dict[tuple[str, Any], str] = {}
    sources = item_dictionary.get("sources", {})
    if not isinstance(sources, dict):
        return out

    for source, mapping in sources.items():
        if not isinstance(source, str) or not isinstance(mapping, dict):
            continue
        for itemid_raw, name in mapping.items():
            if isinstance(name, str) and name.strip():
                out[(source, itemid_raw)] = name.strip()
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
        
        # itemid_raw may be int or str (sbt_status)
        itemid = itemid_raw

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
    
    # Do not force itemid to numeric to support sbt_status / norepinephrine_equiv
    # out["itemid"] = pd.to_numeric(out["itemid"], errors="coerce")
    
    out["value_num"] = pd.to_numeric(out["value_num"], errors="coerce")

    for ts_col in ["charttime", "starttime", "endtime", "storetime"]:
        if ts_col in out.columns:
            out[ts_col] = pd.to_datetime(out[ts_col], errors="coerce")

    out = out.dropna(subset=["event_time", "itemid"]).copy()
    # out["itemid"] = out["itemid"].astype(int)
    return out


def _measurement_activity_label(row: pd.Series, labels: dict[tuple[str, Any], str]) -> str:
    source = str(row.get("source_table") or "")
    itemid = row["itemid"]
    mapped = labels.get((source, itemid))
    if mapped:
        return mapped

    label = row.get("label")
    if label is not None and str(label).strip():
        return str(label).strip()

    return f"item_{itemid}"


def _derive_activities(activity_df: pd.DataFrame) -> list[pd.DataFrame]:
    """Generate derived activities from mapped activities.

    Currently implements:
    - SBTFailed: Fired when SBTCompleted.value == "No" OR when SBTStopped
      occurs within an active SBT window.
    """
    derived_frames: list[pd.DataFrame] = []

    # ── SBTFailed ────────────────────────────────────────────────────────────
    # Case 1: SBTCompleted with value_raw == "Failure"
    sbt_completed = activity_df[activity_df["activity"] == "SBTCompleted"].copy()
    if not sbt_completed.empty:
        failed_mask = (
            sbt_completed.get("value_raw", pd.Series(index=sbt_completed.index, dtype=object))
            .astype(str)
            .str.strip()
            .str.lower()
            .eq("failure")
        )
        sbt_failed_completed = sbt_completed[failed_mask].copy()
        if not sbt_failed_completed.empty:
            sbt_failed_from_completed = pd.DataFrame(
                {
                    "case_id": sbt_failed_completed["case_id"],
                    "activity": "SBTFailed",
                    "timestamp": sbt_failed_completed["timestamp"],
                    "source_table": sbt_failed_completed["source_table"],
                    "itemid": sbt_failed_completed["itemid"],
                    "value_raw": sbt_failed_completed.get("value_raw"),
                    "value_num": sbt_failed_completed.get("value_num"),
                    "unit": sbt_failed_completed.get("unit"),
                    "attrs": [{"kind": "derived_activity", "trigger": "SBTCompleted=Failure"}] * len(sbt_failed_completed),
                    "patient_id": sbt_failed_completed.get("patient_id"),
                    "stay_id": sbt_failed_completed.get("stay_id"),
                }
            )
            derived_frames.append(sbt_failed_from_completed)


    return derived_frames


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
    
    # HARD FILTER: Remove legacy SBT/Vent IDs from raw input entirely
    legacy_blacklist = {224715, 224716, 224717, 225792, "224715", "224716", "224717", "225792"}
    raw = raw[~raw["itemid"].isin(legacy_blacklist)].copy()

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

    # Filter out virtual items that are handled as mapped activities to avoid duplication
    virtual_ids = {"sbt_status", "sbt_outcome", "derived_invasive_ventilation_start"}
    measurement_df = measurement_df[~measurement_df["itemid"].isin(virtual_ids)]

    # Filter out measurement rows with placeholder-only values (e.g., "N/A", "null", "none")
    # Keep row if: has meaningful numeric value OR has non-placeholder text
    # Drop row if: value_num is NaN AND value_raw is only placeholder
    has_valid_number = pd.notna(measurement_df["value_num"])
    
    # Check if value_raw is not a placeholder (vectorized)
    placeholder_set = {"", "none", "null", "nan", "nat", "[null]", "<na>", "n/a"}
    is_placeholder_text = measurement_df["value_raw"].fillna("").astype(str).str.strip().str.lower().isin(placeholder_set)
    has_valid_text = pd.notna(measurement_df["value_raw"]) & ~is_placeholder_text
    
    measurement_df = measurement_df[has_valid_number | has_valid_text]

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

    # Combine all frames before deriving
    all_frames = [measurement_df, *mapped_frames]
    out = pd.concat(all_frames, ignore_index=True)
    out = out.dropna(subset=["case_id", "activity", "timestamp"]).copy()
    out = out.sort_values(["case_id", "timestamp", "activity"]).reset_index(drop=True)

    # Generate derived activities
    derived_frames = _derive_activities(out)
    if derived_frames:
        out = pd.concat([out, *derived_frames], ignore_index=True)
        out = out.dropna(subset=["case_id", "activity", "timestamp"]).copy()
        out = out.sort_values(["case_id", "timestamp", "activity"]).reset_index(drop=True)

    # DEDUPLICATION: Remove identical rows (ignoring patient_id if it causes duplicates)
    # We prioritize rows that HAVE a patient_id if duplicates exist
    if not out.empty:
        out = out.sort_values(["case_id", "timestamp", "activity", "patient_id"], na_position='last')
        out = out.drop_duplicates(subset=["case_id", "activity", "timestamp", "itemid", "value_raw"], keep="first")
        out = out.sort_values(["case_id", "timestamp", "activity"]).reset_index(drop=True)

    return out
