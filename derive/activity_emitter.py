"""Convert raw ICU event rows into checker-ready activity rows.

This module reads:
- configs/item_dictionary.yaml (itemid -> canonical signal labels)
- configs/activity_mapping.yaml (itemid/value -> modeled activities)
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import pandas as pd

from derive.value_converter import convert_categorical_values


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ITEM_DICTIONARY_PATH = PROJECT_ROOT / "configs" / "item_dictionary.yaml"
DEFAULT_ACTIVITY_MAPPING_PATH = PROJECT_ROOT / "configs" / "activity_mapping.yaml"


@functools.lru_cache(maxsize=None)
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
        default_source = cfg.get("source")

        itemid_raw = cfg.get("itemid")
        itemids_raw = cfg.get("itemids")
        if itemid_raw is None and itemids_raw is None:
            raise ValueError(
                f"Activity mapping '{activity}' has neither 'itemid' nor 'itemids' "
                "and is not marked 'derived'."
            )
        # itemid_raw may be int or str (sbt_status)
        itemid_list = [itemid_raw] if itemid_raw is not None else list(itemids_raw)

        value_equals = None
        conditions = cfg.get("conditions")
        if isinstance(conditions, dict) and conditions.get("value_equals") is not None:
            value_equals = str(conditions["value_equals"])

        timestamp_field = cfg.get("timestamp_field")
        if timestamp_field is not None:
            timestamp_field = str(timestamp_field)

        for entry in itemid_list:
            # entry may be a plain itemid, or {itemid: X, source: Y} to override
            # the default source for items that live in a different table.
            if isinstance(entry, dict):
                itemid = entry.get("itemid")
                source = entry.get("source", default_source)
            else:
                itemid = entry
                source = default_source
            if not isinstance(source, str):
                continue

            out.append(
                {
                    "activity": activity,
                    "source": source,
                    "itemid": str(itemid),
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
    - SBTFailed: Fired when InvasiveVentilationStarted occurs within 48h after SBTStarted.
    - SBTSucceeded: Fired when no re-ventilation occurs within 48h after SBTStarted.
    """
    derived_frames: list[pd.DataFrame] = []

    # ── AnyFailureIntervention (Phase 1) ──────────────────────────────────────
    # One event per occurrence of any of the seven post-SBT-failure intervention
    # activities, so INT-COMPOSITE-01 has a real target instead of a phantom one.
    FAILURE_INTERVENTION_ACTIVITIES = {
        "Bronchodilator_Admin",
        "Diuretic_Admin",
        "AfterloadReduction_Admin",
        "ElectrolyteBG_Test",
        "ElectrolyteCorrection_Admin",
        "HormonalLab_Test",
        "HormonalReplacement_Admin",
    }
    intervention_rows = activity_df[activity_df["activity"].isin(FAILURE_INTERVENTION_ACTIVITIES)].copy()
    if not intervention_rows.empty:
        intervention_rows["activity"] = "AnyFailureIntervention"
        derived_frames.append(intervention_rows)

    # ── SBT Outcomes (48h window / re-ventilation rule) ──────────────────────
    # For each SBTStarted: if InvasiveVentilationStarted occurs within the
    # episode window (bounded by next SBTStarted and 48h), emit SBTFailed at
    # that timestamp. Otherwise emit SBTSucceeded at min(start+48h, stay_end).
    # One outcome per start, mutual exclusivity guaranteed by the if/else.
    failure_window = pd.Timedelta(hours=48)
    sbt_started = activity_df[activity_df["activity"] == "SBTStarted"].copy()
    vent_starts = activity_df[activity_df["activity"] == "InvasiveVentilationStarted"].copy()

    outcome_rows: list[dict[str, object]] = []
    for case_id, case_starts in sbt_started.groupby("case_id", sort=False):
        case_starts = case_starts.sort_values("timestamp").reset_index(drop=True)
        stay_end_ts = activity_df[activity_df["case_id"] == case_id]["timestamp"].max()
        case_vents = vent_starts[vent_starts["case_id"] == case_id]

        for _, srow in case_starts.iterrows():
            start_ts = srow["timestamp"]

            later_starts = case_starts[case_starts["timestamp"] > start_ts]["timestamp"]
            next_start_ts = later_starts.min() if not later_starts.empty else pd.NaT

            window_end = start_ts + failure_window
            if pd.notna(next_start_ts):
                window_end = min(window_end, next_start_ts)

            near_vents = case_vents[
                (case_vents["timestamp"] > start_ts) & (case_vents["timestamp"] <= window_end)
            ]

            if not near_vents.empty:
                revent_ts = near_vents["timestamp"].min()
                outcome_rows.append({
                    "case_id": case_id,
                    "activity": "SBTFailed",
                    # Attribute failure to the SBT's own episode: the re-vent
                    # timestamp equals the next episode's start, and episode
                    # slicing is [start, end) — landing on it would push
                    # SBTFailed into the wrong episode. True time kept in attrs.
                    "timestamp": revent_ts - pd.Timedelta(seconds=1),
                    "source_table": "derived_revent",
                    "itemid": None,
                    "value_raw": "Failure (Reventilated <48h)",
                    "value_num": 0.0,
                    "unit": None,
                    "attrs": [{
                        "kind": "derived_activity",
                        "trigger": "reventilation",
                        "revent_ts": revent_ts.isoformat(),
                    }],
                    "patient_id": srow.get("patient_id"),
                    "stay_id": srow.get("stay_id"),
                })
            else:
                # Bound success by the next SBT's start too, so outcomes of
                # consecutive attempts can never interleave.
                success_ts = min(start_ts + failure_window, stay_end_ts)
                if pd.notna(next_start_ts):
                    success_ts = min(success_ts, next_start_ts - pd.Timedelta(seconds=1))
                right_censored = stay_end_ts < start_ts + failure_window
                outcome_rows.append({
                    "case_id": case_id,
                    "activity": "SBTSucceeded",
                    "timestamp": success_ts,
                    "source_table": "derived_implicit",
                    "itemid": None,
                    "value_raw": "Success",
                    "value_num": 1.0,
                    "unit": None,
                    "attrs": [{
                        "kind": "derived_activity",
                        "trigger": "no_revent_48h",
                        "right_censored": bool(right_censored),
                    }],
                    "patient_id": srow.get("patient_id"),
                    "stay_id": srow.get("stay_id"),
                })

    if outcome_rows:
        derived_frames.append(pd.DataFrame(outcome_rows))

    # ── Readiness Criterion Activities ────────────────────────────────────────
    # Emit a named event only when the criterion IS satisfied so PRECEDENCE rules
    # can check "SBTStarted must be preceded by [CriterionMeasured] within 24h"
    # without needing a correlation_condition.

    def _criterion_row(src: pd.Series, activity_name: str, trigger: str) -> dict:
        return {
            "case_id": src.get("case_id"),
            "activity": activity_name,
            "timestamp": src["timestamp"],
            "source_table": "derived_criterion",
            "itemid": None,
            "value_raw": trigger,
            "value_num": src.get("value_num"),
            "unit": None,
            "attrs": [{"kind": "derived_activity", "trigger": trigger}],
            "patient_id": src.get("patient_id"),
            "stay_id": src.get("stay_id"),
        }

    # ponytail: one pass instead of 8+ full-column filter scans
    _itemid_groups = {str(k): v for k, v in activity_df.groupby(activity_df["itemid"].astype(str), sort=False)}
    _empty_frame = activity_df.iloc[0:0]

    def _by_itemid(itemid_str: str) -> pd.DataFrame:
        return _itemid_groups.get(itemid_str, _empty_frame)

    # ── OxygenationMeasured ───────────────────────────────────────────────────
    # ponytail: unconditional emission, oxygenation_ok correlation_condition is
    # sole authority (matches pH/Hgb/Temp/Vasopressor pattern below); no
    # cross-item time-proximity check between SpO2/FiO2/PEEP, accepted tradeoff.
    oxy_rows = [
        _criterion_row(r, "OxygenationMeasured", "pao2fio2ratio")
        for _, r in _by_itemid("pao2fio2ratio").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    oxy_rows += [
        _criterion_row(r, "OxygenationMeasured", "220277")
        for _, r in _by_itemid("220277").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if oxy_rows:
        derived_frames.append(pd.DataFrame(oxy_rows))

    # ── pHMeasured ────────────────────────────────────────────────────────────
    ph_rows = [
        _criterion_row(r, "pHMeasured", "ph_bg")
        for _, r in _by_itemid("ph_bg").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if ph_rows:
        derived_frames.append(pd.DataFrame(ph_rows))

    # ── HemoglobinMeasured ────────────────────────────────────────────────────
    hgb_rows = [
        _criterion_row(r, "HemoglobinMeasured", "hemoglobin_bg")
        for _, r in _by_itemid("hemoglobin_bg").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if hgb_rows:
        derived_frames.append(pd.DataFrame(hgb_rows))

    # ── TemperatureMeasured ───────────────────────────────────────────────────
    temp_rows = [
        _criterion_row(r, "TemperatureMeasured", "223762")
        for _, r in _by_itemid("223762").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if temp_rows:
        derived_frames.append(pd.DataFrame(temp_rows))

    # ── VasopressorMeasured ───────────────────────────────────────────────────
    vp_rows = [
        _criterion_row(r, "VasopressorMeasured", "norepinephrine_equiv")
        for _, r in _by_itemid("norepinephrine_equiv").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if vp_rows:
        derived_frames.append(pd.DataFrame(vp_rows))

    # ── MentalStatusMeasured ──────────────────────────────────────────────────
    mental_rows: list[dict] = []
    for _, row in _by_itemid("228302").iterrows():  # RASS LOC
        if str(row.get("value_raw") or "").strip().lower() == "yes":
            mental_rows.append(_criterion_row(row, "MentalStatusMeasured", "RASS_LOC=Yes"))
    for _, row in _by_itemid("223753").iterrows():  # SAS
        val = row.get("value_num")
        if pd.notna(val) and float(val) in {3.0, 4.0}:
            mental_rows.append(_criterion_row(row, "MentalStatusMeasured", "SAS_in_3_4"))
    if mental_rows:
        derived_frames.append(pd.DataFrame(mental_rows))

    # ── InspiratoryEffortMeasured ─────────────────────────────────────────────
    ie_rows = [
        _criterion_row(r, "InspiratoryEffortMeasured", "224686")
        for _, r in _by_itemid("224686").iterrows()
        if pd.notna(r.get("value_num"))
    ]
    if ie_rows:
        derived_frames.append(pd.DataFrame(ie_rows))

    return derived_frames


def _vectorized_activity_labels(raw: pd.DataFrame, labels: dict[tuple[str, Any], str]) -> pd.Series:
    """Vectorized replacement for apply(_measurement_activity_label, axis=1)."""
    sources = raw["source_table"].astype(str)
    itemids = raw["itemid"]
    primary = pd.Series(
        [labels.get((s, i)) for s, i in zip(sources, itemids)],
        index=raw.index,
        dtype=object,
    )
    fallback_label = (
        raw.get("label", pd.Series(dtype=object))
        .where(lambda s: s.notna())
        .astype("string")
        .str.strip()
        .replace("", pd.NA)
    )
    return primary.fillna(fallback_label).fillna("item_" + itemids.astype(str))


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
            "activity": _vectorized_activity_labels(raw, labels),
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
        mask = (raw["source_table"] == rule["source"]) & (raw["itemid"].astype(str) == rule["itemid"])
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
