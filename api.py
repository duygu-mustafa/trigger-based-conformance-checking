"""Lightweight FastAPI backend for the Clinician Studio.

Exposes structured rule data and on-demand conformance analysis to the React
frontend via /api/* endpoints.

Run with:
    uvicorn api:app --reload --port 8000
"""

from __future__ import annotations

import re
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import numpy as _np
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))


def _sanitize(obj):
    """Recursively convert numpy scalars/arrays to native Python types."""
    if isinstance(obj, _np.bool_):
        return bool(obj)
    if isinstance(obj, _np.integer):
        return int(obj)
    if isinstance(obj, _np.floating):
        return None if _np.isnan(obj) else float(obj)
    if isinstance(obj, _np.ndarray):
        return obj.tolist()
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


app = FastAPI(title="Clinician Studio API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory job store ───────────────────────────────────────────────────────

_jobs: dict[str, dict[str, Any]] = {}
_job_cancel: dict[str, threading.Event] = {}


# ── Item label lookup ─────────────────────────────────────────────────────────

def _load_item_labels() -> dict[str, str]:
    """Build a flat itemid → human label map from item_dictionary.yaml."""
    path = PROJECT_ROOT / "configs" / "item_dictionary.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    labels: dict[str, str] = {}
    for source in data.get("sources", {}).values():
        for itemid, label in source.items():
            raw = str(label).strip()
            # Some entries are "short_alias  # description" – take before the #
            display = raw.split("#")[0].strip()
            # Some are multiline; take first line
            display = display.splitlines()[0].strip()
            labels[str(itemid)] = display
    return labels


_ITEM_LABELS: dict[str, str] = _load_item_labels()

# Pretty operator symbols
_OP_MAP = {
    ">=": "≥",
    "<=": "≤",
    "!=": "≠",
    ">": ">",
    "<": "<",
    "==": "=",
}

# Template → plain-English one-liner for clinicians
_TEMPLATE_DESCRIPTIONS: dict[str, str] = {
    "EXISTENCE": "Must occur at least once",
    "ABSENCE": "Must never occur",
    "AT_MOST_ONE": "Must occur at most once",
    "INIT": "Must be the first event",
    "END": "Must be the last event",
    "RESPONSE": "After [A] occurs, [B] must eventually follow",
    "ALTERNATE_RESPONSE": "Each occurrence of [A] must be followed by [B] before [A] can occur again",
    "CHAIN_RESPONSE": "After [A] occurs, [B] must occur immediately next",
    "PRECEDENCE": "[B] can only occur if [A] happened before it",
    "ALTERNATE_PRECEDENCE": "Each [B] must be preceded by a distinct occurrence of [A]",
    "CHAIN_PRECEDENCE": "[B] must be immediately preceded by [A]",
    "CO_EXISTENCE": "[A] and [B] must either both occur or both be absent",
    "RESPONDED_EXISTENCE": "If [A] occurs, [B] must also occur (in any order)",
    "SUCCESSION": "[A] and [B] must both occur, with [A] before [B]",
    "ALTERNATE_SUCCESSION": "Alternating succession between [A] and [B]",
    "CHAIN_SUCCESSION": "[A] and [B] must occur consecutively",
    "NOT_CO_EXISTENCE": "[A] and [B] cannot both occur in the same episode",
    "NOT_RESPONSE": "After [A] occurs, [B] must NOT follow",
    "NOT_CHAIN_RESPONSE": "[A] must not be immediately followed by [B]",
    "NOT_PRECEDENCE": "[B] must not have [A] before it",
    "NOT_CHAIN_PRECEDENCE": "[B] must not be immediately preceded by [A]",
    "NOT_RESPONDED_EXISTENCE": "If [A] occurs, [B] must not occur at all",
    "NOT_SUCCESSION": "[A] followed by [B] is forbidden",
    "NOT_CHAIN_SUCCESSION": "[A] immediately followed by [B] is forbidden",
}

# Category by rule-id prefix
_CATEGORY_MAP: dict[str, str] = {
    "RC-": "readiness",
    "SBT-": "sbt_execution",
    "INT-": "failure_correction",
}


def _rule_category(rule_id: str) -> str:
    for prefix, cat in _CATEGORY_MAP.items():
        if rule_id.startswith(prefix):
            return cat
    return "other"


# ── Condition parser ──────────────────────────────────────────────────────────

_ITEMS_PATTERN = re.compile(
    r"items\[(?:'([^']+)'|\"([^\"]+)\"|(\d+))\]\s*"
    r"(>=|<=|!=|>|<|==)\s*"
    r"(['\"]?[\w.\-]+['\"]?)"
)


def _label_for(key: str) -> str:
    label = _ITEM_LABELS.get(key) or _ITEM_LABELS.get(str(key))
    return label or key


def _parse_condition_expression(expr: str) -> list[dict[str, str]]:
    """Extract structured condition chips from a raw Python-style expression.

    Returns a list of {item_label, operator, value} dicts.  Falls back to a
    single plain-text chip when the expression cannot be parsed structurally.
    """
    if not expr:
        return []

    chips = []
    for m in _ITEMS_PATTERN.finditer(expr):
        key = m.group(1) or m.group(2) or m.group(3)
        op_raw = m.group(4)
        val_raw = m.group(5).strip("'\"")
        chips.append({
            "item_label": _label_for(key),
            "item_key": str(key),
            "operator": _OP_MAP.get(op_raw, op_raw),
            "value": val_raw,
        })

    if not chips:
        # Unparse-able – return a plain text chip so the UI still shows something
        cleaned = (
            expr.replace("NOT ", "NOT ")
            .replace(" AND ", " AND ")
            .replace(" OR ", " OR ")
        )
        return [{"text": cleaned}]

    return chips


def _detect_logic(expr: str) -> str:
    upper = expr.upper()
    and_count = len(re.findall(r"\bAND\b", upper))
    or_count = len(re.findall(r"\bOR\b", upper))
    if or_count > and_count:
        return "OR"
    if and_count > 0:
        return "AND"
    return "AND"


# ── Weights loader ────────────────────────────────────────────────────────────

def _load_weights() -> dict[str, dict[str, Any]]:
    path = PROJECT_ROOT / "configs" / "declare" / "weights.yaml"
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("weights", {})


_WEIGHTS: dict[str, dict[str, Any]] = _load_weights()


def _severity_for(rule_id: str) -> dict[str, float]:
    w = _WEIGHTS.get(rule_id, {})
    scores = w.get("metadata_scores", {})
    return {
        "clinical_consequence": scores.get("clinical_consequence", 0.5),
        "unnoticed_frequency": scores.get("unnoticed_frequency", 0.5),
        "must_not_vs_should": scores.get("must_not_vs_should", 0.5),
        "theta": w.get("theta"),
        "theta_crit": w.get("theta_crit"),
    }


# ── Rule serialiser ───────────────────────────────────────────────────────────

def _subst_activity_names(expr: str, activation: str | None, target: str | None) -> str:
    """Replace internal variable names (target_ts, activation_ts) with activity names."""
    if not expr:
        return expr
    result = expr
    if activation:
        result = result.replace("activation_ts", activation)
    if target:
        result = result.replace("target_ts", target)
    return result


def _constraint_to_dict(c: Any) -> dict[str, Any]:
    rule_id = getattr(c, "id", None) or c.label or ""
    template_name = c.template.name if hasattr(c.template, "name") else str(c.template)

    activation_name = getattr(c, "activation", None)
    target_name = getattr(c, "target", None)

    activation_expr = _subst_activity_names(
        getattr(c, "activation_condition_raw", None) or "",
        activation_name,
        target_name,
    )
    correlation_expr = _subst_activity_names(
        getattr(c, "target_condition_raw", None) or "",
        activation_name,
        target_name,
    )

    time_cond = getattr(c, "time_condition", None)
    min_hours = (time_cond.min_seconds / 3600.0) if time_cond and time_cond.min_seconds is not None else None
    max_hours = (time_cond.max_seconds / 3600.0) if time_cond and time_cond.max_seconds is not None else None
    obs_window = getattr(c, "observation_window_hours", None)
    if max_hours is None and obs_window is not None:
        max_hours = float(obs_window)

    activation_chips = _parse_condition_expression(str(activation_expr)) if activation_expr else []
    correlation_chips = _parse_condition_expression(str(correlation_expr)) if correlation_expr else []

    return {
        "id": str(rule_id),
        "label": c.label or str(rule_id),
        "description": getattr(c, "description", "") or "",
        "rationale": getattr(c, "rationale", "") or "",
        "category": _rule_category(str(rule_id)),
        "template": template_name,
        "template_label": _TEMPLATE_DESCRIPTIONS.get(template_name, template_name),
        "activation": c.activation,
        "target": c.target,
        "time_condition": {
            "min_hours": min_hours,
            "max_hours": max_hours,
        },
        "activation_conditions": activation_chips,
        "activation_logic": _detect_logic(str(activation_expr)) if activation_chips else "AND",
        "activation_condition_title": getattr(c, "activation_condition_title", None),
        "correlation_conditions": correlation_chips,
        "correlation_logic": _detect_logic(str(correlation_expr)) if correlation_chips else "AND",
        "target_condition_title": getattr(c, "target_condition_title", None),
        "semantics": getattr(c, "semantics", None),
        "severity": _severity_for(str(rule_id)),
    }


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/api/rules")
def get_rules() -> list[dict[str, Any]]:
    """Return all clinical rules as structured, code-free JSON."""
    from conformance.rules import (
        build_failure_correction_model,
        build_readiness_assessment_model,
        build_sbt_execution_model,
    )
    rules = []
    for builder in (
        build_readiness_assessment_model,
        build_sbt_execution_model,
        build_failure_correction_model,
    ):
        model = builder()
        for c in model.constraints:
            rules.append(_constraint_to_dict(c))
    return rules


@app.get("/api/activities")
def get_activities() -> dict[str, list[str]]:
    """Return known semantic activity names grouped by category."""
    path = PROJECT_ROOT / "configs" / "activity_mapping.yaml"
    if not path.exists():
        return {"all": []}
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    mappings = data.get("mappings", {})
    activities = list(mappings.keys())

    ventilation = [a for a in activities if "Ventilation" in a or "Intubation" in a]
    sbt = [a for a in activities if "SBT" in a]
    assessment_keywords = ("_Measured", "_Assessed", "_Performed", "ABG_", "Lab_", "CuffLeak", "Extubation")
    assessment = [a for a in activities if any(k in a for k in assessment_keywords)]
    interventions = [a for a in activities if a not in ventilation and a not in sbt and a not in assessment]

    return {
        "ventilation": ventilation,
        "sbt": sbt,
        "assessment": assessment,
        "interventions": interventions,
        "all": activities,
    }


@app.get("/api/item_labels")
def get_item_labels() -> dict[str, str]:
    """Return the item-id → human label lookup."""
    return _ITEM_LABELS


_BG_ITEMS = [
    {"itemid": "pao2fio2ratio", "label": "PaO2/FiO2 Ratio", "category": "Blood Gas"},
    {"itemid": "fio2_bg",       "label": "FiO2 (Blood Gas)", "category": "Blood Gas"},
    {"itemid": "ph_bg",         "label": "pH (Blood Gas)",   "category": "Blood Gas"},
    {"itemid": "hemoglobin_bg", "label": "Hemoglobin (Blood Gas)", "category": "Blood Gas"},
]


@app.get("/api/item_search")
def search_items(q: str = "", table: str = "chartevents", limit: int = 50) -> list[dict]:
    """Search MIMIC items by label substring. Falls back to static YAML if DB unavailable."""
    if table == "bg":
        q_lower = q.lower()
        return [i for i in _BG_ITEMS if not q_lower or q_lower in i["label"].lower()][:limit]

    try:
        from database.client import get_postgres_connection
        conn = get_postgres_connection()
        try:
            cur = conn.cursor()
            if table == "labevents":
                cur.execute(
                    "SELECT itemid, label, category FROM mimiciv_hosp.d_labitems"
                    " WHERE LOWER(label) LIKE %(q)s"
                    " ORDER BY label LIMIT %(limit)s",
                    {"q": f"%{q.lower()}%", "limit": limit},
                )
            else:
                cur.execute(
                    "SELECT itemid, label, category FROM mimiciv_icu.d_items"
                    " WHERE LOWER(label) LIKE %(q)s AND linksto = %(table)s"
                    " ORDER BY label LIMIT %(limit)s",
                    {"q": f"%{q.lower()}%", "table": table, "limit": limit},
                )
            rows = [{"itemid": r[0], "label": r[1], "category": r[2]} for r in cur.fetchall()]
            cur.close()
            return rows
        finally:
            conn.close()
    except Exception:
        results = []
        for key, label in _ITEM_LABELS.items():
            if q.lower() in label.lower():
                try:
                    results.append({"itemid": int(key), "label": label, "category": None})
                except ValueError:
                    pass
        return results[:limit]


# ── Analysis job models ───────────────────────────────────────────────────────

class DataConditionInput(BaseModel):
    item_key: str
    item_label: str
    operator: str
    value: str


class CustomRuleInput(BaseModel):
    id: Optional[str] = None
    label: str
    template: str
    activation: str
    target: Optional[str] = None
    min_gap_hours: Optional[float] = None
    max_gap_hours: Optional[float] = None
    activation_conditions: list[DataConditionInput] = []
    activation_logic: str = "AND"
    correlation_conditions: list[DataConditionInput] = []
    correlation_logic: str = "AND"
    activation_condition_expr: Optional[str] = None
    correlation_condition_expr: Optional[str] = None
    rationale: str = ""
    severity: dict[str, float] = {}


class ValueFilter(BaseModel):
    column: str      # "valuenum" | "value" | "amount"
    operator: str    # ">=" | "<=" | "==" | "!=" | ">" | "<"
    value: float | str


class ValueChangeSpec(BaseModel):
    value_type: str = "numeric"           # "numeric" | "categorical"
    prev_min: Optional[float] = None
    prev_max: Optional[float] = None
    next_min: Optional[float] = None
    next_max: Optional[float] = None
    prev_values: list[str] = []
    next_values: list[str] = []


class CustomEventType(BaseModel):
    name: str
    kind: str = "table"                        # "table" | "sql" | "value_change"
    source_table: Optional[str] = None
    itemids: Optional[list[int | str]] = None
    value_filter: Optional[ValueFilter] = None
    sql: Optional[str] = None                  # populated when kind="sql"
    value_change: Optional[ValueChangeSpec] = None  # populated when kind="value_change"


class QueryRequest(BaseModel):
    sql: str
    limit: int = 200


class CustomDataItem(BaseModel):
    source_table: str
    itemids: list[int]


class RunRequest(BaseModel):
    sample_size: int = 50
    seed: int = 42
    include_predefined: bool = True
    custom_rules: list[CustomRuleInput] = []
    custom_event_types: list[CustomEventType] = []
    custom_data_items: list[CustomDataItem] = []
    trigger_event: str = "InvasiveVentilationStarted"


# ── Custom rule → DeclareConstraint ──────────────────────────────────────────

_REVERSE_OP_MAP = {v: k for k, v in _OP_MAP.items()}


def _chips_to_expr(chips: list[DataConditionInput], logic: str) -> str:
    parts = []
    for chip in chips:
        op = _REVERSE_OP_MAP.get(chip.operator, chip.operator)
        try:
            float(chip.value)
            val = chip.value
        except ValueError:
            val = f"'{chip.value}'"
        parts.append(f"items['{chip.item_key}'] {op} {val}")
    if not parts:
        return ""
    joiner = f" {logic} "
    return joiner.join(f"({p})" for p in parts) if len(parts) > 1 else parts[0]


def _custom_rule_to_constraint(rule: CustomRuleInput):
    from conformance.types import (
        DataCondition,
        DeclareConstraint,
        DeclareTemplate,
        TimeCondition,
    )

    template_map = {
        "RESPONSE": DeclareTemplate.RESPONSE,
        "PRECEDENCE": DeclareTemplate.PRECEDENCE,
        "SUCCESSION": DeclareTemplate.SUCCESSION,
        "CO_EXISTENCE": DeclareTemplate.CO_EXISTENCE,
        "RESPONDED_EXISTENCE": DeclareTemplate.RESPONDED_EXISTENCE,
        "CHAIN_RESPONSE": DeclareTemplate.CHAIN_RESPONSE,
        "CHAIN_PRECEDENCE": DeclareTemplate.CHAIN_PRECEDENCE,
        "CHAIN_SUCCESSION": DeclareTemplate.CHAIN_SUCCESSION,
        "ALTERNATE_RESPONSE": DeclareTemplate.ALTERNATE_RESPONSE,
        "ALTERNATE_PRECEDENCE": DeclareTemplate.ALTERNATE_PRECEDENCE,
        "ALTERNATE_SUCCESSION": DeclareTemplate.ALTERNATE_SUCCESSION,
        "NOT_CO_EXISTENCE": DeclareTemplate.NOT_CO_EXISTENCE,
        "NOT_RESPONSE": DeclareTemplate.NOT_RESPONSE,
        "NOT_CHAIN_RESPONSE": DeclareTemplate.NOT_CHAIN_RESPONSE,
        "NOT_PRECEDENCE": DeclareTemplate.NOT_PRECEDENCE,
        "NOT_CHAIN_PRECEDENCE": DeclareTemplate.NOT_CHAIN_PRECEDENCE,
        "NOT_RESPONDED_EXISTENCE": DeclareTemplate.NOT_RESPONDED_EXISTENCE,
        "NOT_SUCCESSION": DeclareTemplate.NOT_SUCCESSION,
        "NOT_CHAIN_SUCCESSION": DeclareTemplate.NOT_CHAIN_SUCCESSION,
        "EXISTENCE": DeclareTemplate.EXISTENCE,
        "ABSENCE": DeclareTemplate.ABSENCE,
        "AT_MOST_ONE": DeclareTemplate.AT_MOST_ONE,
        "INIT": DeclareTemplate.INIT,
        "END": DeclareTemplate.END,
    }

    template = template_map.get(rule.template.upper())
    if template is None:
        raise ValueError(f"Unknown template: {rule.template}")

    activation_expr = rule.activation_condition_expr or _chips_to_expr(rule.activation_conditions, rule.activation_logic)
    correlation_expr = rule.correlation_condition_expr or _chips_to_expr(rule.correlation_conditions, rule.correlation_logic)

    time_cond = None
    if rule.min_gap_hours is not None or rule.max_gap_hours is not None:
        time_cond = TimeCondition(
            min_seconds=rule.min_gap_hours * 3600 if rule.min_gap_hours is not None else None,
            max_seconds=rule.max_gap_hours * 3600 if rule.max_gap_hours is not None else None,
        )

    unary_templates = {
        DeclareTemplate.EXISTENCE,
        DeclareTemplate.ABSENCE,
        DeclareTemplate.AT_MOST_ONE,
        DeclareTemplate.INIT,
        DeclareTemplate.END,
    }
    target = None if template in unary_templates else (rule.target or rule.activation)

    c = DeclareConstraint(
        template=template,
        activation=rule.activation,
        target=target,
        activation_cond=DataCondition(activation_expr) if activation_expr else None,
        correlation_cond=DataCondition(correlation_expr) if correlation_expr else None,
        time_condition=time_cond,
        label=rule.label,
    )
    c.id = rule.id or rule.label
    c.description = ""
    c.rationale = rule.rationale
    c.semantics = None
    c.activation_condition_raw = activation_expr or None
    c.target_condition_raw = correlation_expr or None
    return c


# ── Analysis runner ───────────────────────────────────────────────────────────

def _split_into_episodes(df: "pd.DataFrame", trigger_activity: str) -> list["pd.DataFrame"]:
    """Split a stay DataFrame into episode sub-frames using trigger_activity boundaries.

    Returns one DataFrame per episode. Falls back to [df] when no triggers are found.
    """
    import pandas as pd

    triggers = (
        df[df["activity"] == trigger_activity]
        .drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if triggers.empty:
        return [df]

    trace_end = df["timestamp"].max() + pd.Timedelta(seconds=1)
    episodes = []
    for idx, row in triggers.iterrows():
        start_ts = row["timestamp"]
        end_ts = triggers.iloc[idx + 1]["timestamp"] if idx + 1 < len(triggers) else trace_end
        episode_df = df[(df["timestamp"] >= start_ts) & (df["timestamp"] < end_ts)]
        if not episode_df.empty:
            episodes.append(episode_df)
    return episodes if episodes else [df]


def _fetch_custom_events(
    stay_ids: list[int],
    event_types: list[CustomEventType],
) -> dict[str, Any]:
    """Query MIMIC for custom event rows and return {stay_id_str: DataFrame}."""
    import pandas as pd
    from database.client import get_postgres_connection

    table_types = [et for et in event_types if et.kind == "table"]
    sql_types = [et for et in event_types if et.kind == "sql" and et.sql]
    vc_types = [et for et in event_types if et.kind == "value_change" and et.value_change]

    by_table: dict[str, list[CustomEventType]] = {}
    for et in table_types:
        by_table.setdefault(et.source_table, []).append(et)

    # {(source_table, itemid): name}
    label_lookup: dict[tuple[str, int], str] = {}
    for et in table_types:
        for iid in (et.itemids or []):
            label_lookup[(et.source_table, iid)] = et.name

    # value_filter lookup
    filter_lookup: dict[tuple[str, int], ValueFilter | None] = {}
    for et in table_types:
        for iid in (et.itemids or []):
            filter_lookup[(et.source_table, iid)] = et.value_filter

    TABLE_QUERIES = {
        "chartevents": (
            "SELECT stay_id, itemid, charttime AS event_time,"
            " value AS value_raw, valuenum AS value_num, valueuom AS unit"
            " FROM mimiciv_icu.chartevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
            " AND (error IS NULL OR error = 0)"
        ),
        "inputevents": (
            "SELECT stay_id, itemid, starttime AS event_time,"
            " NULL AS value_raw, amount AS value_num, amountuom AS unit"
            " FROM mimiciv_icu.inputevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
        ),
        "procedureevents": (
            "SELECT stay_id, itemid, starttime AS event_time,"
            " NULL AS value_raw, NULL AS value_num, NULL AS unit"
            " FROM mimiciv_icu.procedureevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
        ),
        "outputevents": (
            "SELECT stay_id, itemid, charttime AS event_time,"
            " NULL AS value_raw, value AS value_num, valueuom AS unit"
            " FROM mimiciv_icu.outputevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
        ),
        "labevents": (
            "SELECT s.stay_id, l.itemid, l.charttime AS event_time,"
            " l.value AS value_raw, l.valuenum AS value_num, l.valueuom AS unit"
            " FROM mimiciv_hosp.labevents l"
            " JOIN mimiciv_icu.icustays s ON l.hadm_id = s.hadm_id"
            " WHERE s.stay_id = ANY(%(stay_ids)s) AND l.itemid = ANY(%(itemids)s)"
        ),
        "bg": (
            "SELECT s.stay_id, cols.itemid, e.charttime AS event_time,"
            " cols.val::text AS value_raw, cols.val AS value_num, cols.uom AS unit"
            " FROM mimiciv_derived.bg e"
            " CROSS JOIN LATERAL (VALUES"
            "   ('pao2fio2ratio', e.pao2fio2ratio, 'ratio'),"
            "   ('fio2_bg', COALESCE(e.fio2, e.fio2_chartevents), '%%'),"
            "   ('ph_bg', e.ph, 'units'),"
            "   ('hemoglobin_bg', e.hemoglobin, 'g/dL')"
            " ) AS cols(itemid, val, uom)"
            " JOIN mimiciv_icu.icustays s ON e.hadm_id = s.hadm_id"
            " WHERE s.stay_id = ANY(%(stay_ids)s) AND cols.itemid = ANY(%(itemids)s)"
            " AND cols.val IS NOT NULL"
        ),
    }

    OP_FNS = {
        ">=": lambda a, b: a >= b,
        "<=": lambda a, b: a <= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
        ">": lambda a, b: a > b,
        "<": lambda a, b: a < b,
    }

    all_rows: list[dict] = []
    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        for table, ets in by_table.items():
            all_itemids = list({iid for et in ets for iid in (et.itemids or [])})
            sql = TABLE_QUERIES.get(table)
            if not sql:
                continue
            cur.execute(sql, {"stay_ids": stay_ids, "itemids": all_itemids})
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                key = (table, r["itemid"])
                name = label_lookup.get(key)
                if not name:
                    continue
                vf = filter_lookup.get(key)
                if vf:
                    col_val = r.get(vf.column)
                    try:
                        col_val = float(col_val)
                        threshold = float(vf.value)
                    except (TypeError, ValueError):
                        col_val = str(col_val) if col_val is not None else None
                        threshold = vf.value
                    fn = OP_FNS.get(vf.operator)
                    if fn and (col_val is None or not fn(col_val, threshold)):
                        continue
                all_rows.append({
                    "case_id": str(r["stay_id"]),
                    "activity": name,
                    "timestamp": pd.to_datetime(r["event_time"]),
                    "source_table": table,
                    "itemid": r["itemid"],
                    "value_raw": r.get("value_raw"),
                    "value_num": r.get("value_num"),
                    "unit": r.get("unit"),
                    "attrs": [{"kind": "custom_event"}],
                    "patient_id": None,
                    "stay_id": r["stay_id"],
                })
        # SQL-type custom events
        _TIMESTAMP_COLS = ["event_time", "charttime", "starttime", "endtime"]
        _VALUE_RAW_COLS = ["value_raw", "value", "value_text"]
        _VALUE_NUM_COLS = ["value_num", "valuenum", "amount"]
        _UNIT_COLS = ["unit", "valueuom", "amountuom"]

        def _pick(row: dict, candidates: list[str]):
            for c in candidates:
                if c in row and row[c] is not None:
                    return row[c]
            return None

        for et in sql_types:
            wrapped = (
                f"SELECT * FROM ({et.sql.rstrip(';')}) __q"
                f" WHERE __q.stay_id = ANY(%(stay_ids)s)"
            )
            try:
                cur.execute(wrapped, {"stay_ids": stay_ids})
                cols = [d[0] for d in cur.description]
                for row in cur.fetchall():
                    r = dict(zip(cols, row))
                    event_time = _pick(r, _TIMESTAMP_COLS)
                    if event_time is None:
                        continue
                    all_rows.append({
                        "case_id": str(r["stay_id"]),
                        "activity": et.name,
                        "timestamp": pd.to_datetime(event_time),
                        "source_table": "custom_sql",
                        "itemid": None,
                        "value_raw": _pick(r, _VALUE_RAW_COLS),
                        "value_num": _pick(r, _VALUE_NUM_COLS),
                        "unit": _pick(r, _UNIT_COLS),
                        "attrs": [{"kind": "custom_sql_event"}],
                        "patient_id": None,
                        "stay_id": r["stay_id"],
                    })
            except Exception:
                pass  # caller adds warning; skip this event type silently

        # Value-change event types: emit at transition timestamp
        def _in_range(v, lo, hi):
            if v is None:
                return False
            if lo is not None and v < lo:
                return False
            if hi is not None and v > hi:
                return False
            return True

        for et in vc_types:
            spec = et.value_change
            sql = TABLE_QUERIES.get(et.source_table)
            if not sql:
                continue
            all_itemids = list(et.itemids or [])
            if not all_itemids:
                continue
            try:
                ordered_sql = f"{sql} ORDER BY stay_id, event_time"
                cur.execute(ordered_sql, {"stay_ids": stay_ids, "itemids": all_itemids})
                cols = [d[0] for d in cur.description]
                rows_by_stay: dict[int, list[dict]] = {}
                for row in cur.fetchall():
                    r = dict(zip(cols, row))
                    rows_by_stay.setdefault(r["stay_id"], []).append(r)
                for stay_id, stay_rows in rows_by_stay.items():
                    for prev_r, next_r in zip(stay_rows, stay_rows[1:]):
                        if spec.value_type == "numeric":
                            prev_ok = _in_range(prev_r.get("value_num"), spec.prev_min, spec.prev_max)
                            next_ok = _in_range(next_r.get("value_num"), spec.next_min, spec.next_max)
                        else:
                            prev_ok = str(prev_r.get("value_raw") or "") in spec.prev_values
                            next_ok = str(next_r.get("value_raw") or "") in spec.next_values
                        if prev_ok and next_ok:
                            all_rows.append({
                                "case_id": str(stay_id),
                                "activity": et.name,
                                "timestamp": pd.to_datetime(next_r["event_time"]),
                                "source_table": et.source_table,
                                "itemid": next_r["itemid"],
                                "value_raw": next_r.get("value_raw"),
                                "value_num": next_r.get("value_num"),
                                "unit": next_r.get("unit"),
                                "attrs": [{"kind": "value_change_event"}],
                                "patient_id": None,
                                "stay_id": stay_id,
                            })
            except Exception:
                pass

        cur.close()
    finally:
        if conn:
            conn.close()

    if not all_rows:
        return {}

    df = pd.DataFrame(all_rows)
    result: dict[str, Any] = {}
    for sid, grp in df.groupby("case_id"):
        result[str(sid)] = grp.reset_index(drop=True)
    return result


def _fetch_condition_data(
    stay_ids: list[int],
    data_items: list[CustomDataItem],
) -> dict[str, Any]:
    """Fetch raw measurements for custom data condition items, keyed by stay_id string.

    Returns rows with itemid/value_num/value_raw but no activity, so they populate
    the items dict in _build_items_snapshot without creating spurious activities.
    """
    import pandas as pd
    from database.client import get_postgres_connection

    TABLE_QUERIES = {
        "chartevents": (
            "SELECT stay_id, itemid, charttime AS event_time,"
            " value AS value_raw, valuenum AS value_num"
            " FROM mimiciv_icu.chartevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
            " AND (error IS NULL OR error = 0)"
        ),
        "inputevents": (
            "SELECT stay_id, itemid, starttime AS event_time,"
            " NULL AS value_raw, amount AS value_num"
            " FROM mimiciv_icu.inputevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
        ),
        "outputevents": (
            "SELECT stay_id, itemid, charttime AS event_time,"
            " NULL AS value_raw, value AS value_num"
            " FROM mimiciv_icu.outputevents"
            " WHERE stay_id = ANY(%(stay_ids)s) AND itemid = ANY(%(itemids)s)"
        ),
        "labevents": (
            "SELECT s.stay_id, l.itemid, l.charttime AS event_time,"
            " l.value AS value_raw, l.valuenum AS value_num"
            " FROM mimiciv_hosp.labevents l"
            " JOIN mimiciv_icu.icustays s ON l.hadm_id = s.hadm_id"
            " WHERE s.stay_id = ANY(%(stay_ids)s) AND l.itemid = ANY(%(itemids)s)"
        ),
    }

    all_rows: list[dict] = []
    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        for item in data_items:
            sql = TABLE_QUERIES.get(item.source_table)
            if not sql or not item.itemids:
                continue
            cur.execute(sql, {"stay_ids": stay_ids, "itemids": item.itemids})
            cols = [d[0] for d in cur.description]
            for row in cur.fetchall():
                r = dict(zip(cols, row))
                all_rows.append({
                    "case_id": str(r["stay_id"]),
                    "activity": None,
                    "timestamp": pd.to_datetime(r["event_time"]),
                    "source_table": item.source_table,
                    "itemid": r["itemid"],
                    "value_raw": r.get("value_raw"),
                    "value_num": r.get("value_num"),
                    "unit": None,
                    "attrs": None,
                    "patient_id": None,
                    "stay_id": r["stay_id"],
                })
        cur.close()
    finally:
        if conn:
            conn.close()

    if not all_rows:
        return {}

    df = pd.DataFrame(all_rows)
    result: dict[str, Any] = {}
    for sid, grp in df.groupby("case_id"):
        result[str(sid)] = grp.reset_index(drop=True)
    return result


def _run_analysis(job_id: str, request: RunRequest) -> None:
    """Background thread: run conformance on a sample and store result."""
    cancel_event = _job_cancel[job_id]
    job = _jobs[job_id]

    try:
        import random
        import math
        import json
        import pandas as pd
        from conformance.batch_runner import BatchConformanceRunner
        from conformance.rules import (
            build_failure_correction_model,
            build_readiness_assessment_model,
            build_sbt_execution_model,
        )
        from conformance.types import DeclareModel

        event_log_path = PROJECT_ROOT / "data" / "icu_event_log_sample.parquet"
        if not event_log_path.exists():
            job["status"] = "error"
            job["error"] = "Event log not found. Run prepare_event_log.py first."
            return

        # Build model
        combined = DeclareModel(name="studio_run")
        if request.include_predefined:
            for builder in (
                build_readiness_assessment_model,
                build_sbt_execution_model,
                build_failure_correction_model,
            ):
                for c in builder().constraints:
                    combined.add(c)

        for cr in request.custom_rules:
            try:
                combined.add(_custom_rule_to_constraint(cr))
            except Exception as e:
                job["warnings"] = job.get("warnings", []) + [f"Skipped rule '{cr.label}': {e}"]

        if not combined.constraints:
            job["status"] = "error"
            job["error"] = "No rules selected. Enable predefined rules or add custom ones."
            return

        # Sample stay IDs
        runner = BatchConformanceRunner(
            input_file=str(event_log_path),
            model_builder=lambda: combined,
        )
        all_ids = runner.get_stay_ids()

        rng = random.Random(request.seed)
        sample_ids = rng.sample(all_ids, min(request.sample_size, len(all_ids)))

        job["total"] = len(sample_ids)
        job["done"] = 0

        from conformance.checker import check_log_conformance
        import pandas as pd

        custom_events_by_stay: dict[str, Any] = {}
        if request.custom_event_types:
            try:
                custom_events_by_stay = _fetch_custom_events(
                    [int(s) for s in sample_ids],
                    request.custom_event_types,
                )
            except Exception as e:
                job["warnings"] = job.get("warnings", []) + [
                    f"Custom event fetch failed: {e}. Custom events skipped."
                ]

        condition_data_by_stay: dict[str, Any] = {}
        if request.custom_data_items:
            try:
                condition_data_by_stay = _fetch_condition_data(
                    [int(s) for s in sample_ids],
                    request.custom_data_items,
                )
            except Exception as e:
                job["warnings"] = job.get("warnings", []) + [
                    f"Condition data fetch failed: {e}. Extra measurements skipped."
                ]

        # Each entry: (stay_id, trace_results, episode_outcome)
        all_episode_data = []

        for stay_id in sample_ids:
            if cancel_event.is_set():
                job["status"] = "cancelled"
                return

            df = runner.con.execute(
                f"SELECT * FROM events WHERE {runner._batch_key_column} = ?",
                [str(stay_id)],
            ).df()

            custom_df = custom_events_by_stay.get(str(stay_id))
            if custom_df is not None and not custom_df.empty:
                df = pd.concat([df, custom_df], ignore_index=True)

            cond_df = condition_data_by_stay.get(str(stay_id))
            if cond_df is not None and not cond_df.empty:
                df = pd.concat([df, cond_df], ignore_index=True)

            if custom_df is not None or cond_df is not None:
                df = df.sort_values("timestamp").reset_index(drop=True)

            if not df.empty:
                episodes = list(_split_into_episodes(df, request.trigger_event))
                for ep_idx, episode_df in enumerate(episodes):
                    activities = set(episode_df["activity"].dropna().tolist()) if "activity" in episode_df.columns else set()
                    if "SBTStarted" not in activities:
                        episode_outcome = "no_sbt_attempt"
                    else:
                        sbt_ts = episode_df[episode_df["activity"] == "SBTStarted"]["timestamp"].min()
                        window_end = sbt_ts + pd.Timedelta(hours=48)
                        revent_in_ep = (
                            (episode_df["activity"] == "InvasiveVentilationStarted") &
                            (episode_df["timestamp"] > sbt_ts) &
                            (episode_df["timestamp"] <= window_end)
                        ).any()
                        next_ep_start = episodes[ep_idx + 1]["timestamp"].min() if ep_idx + 1 < len(episodes) else None
                        next_in_window = next_ep_start is not None and sbt_ts < next_ep_start <= window_end
                        episode_outcome = "failure" if (revent_in_ep or next_in_window) else "success"

                    trace_results = check_log_conformance(episode_df, combined)
                    if trace_results:
                        all_episode_data.append((str(stay_id), trace_results, episode_outcome))

            job["done"] = job.get("done", 0) + 1
            job["progress"] = job["done"] / job["total"]

        summary = _sanitize(_build_rich_summary(all_episode_data, combined))

        job["result"] = summary
        job["status"] = "done"

    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["traceback"] = traceback.format_exc()


def _build_rich_summary(episode_data: list, model) -> dict[str, Any]:
    """Build a rich summary matching SummaryView data shape, with per-run statistical tests."""
    import math
    from scipy.stats import fisher_exact as _fisher_exact
    from conformance.results import ConformanceOutcome

    label_map = {c.id: getattr(c, "label", c.id) for c in model.constraints}
    rationale_map = {c.id: getattr(c, "rationale", "") for c in model.constraints}
    template_map = {c.id: getattr(c, "template", None) for c in model.constraints}
    min_gap_map = {c.id: getattr(c, "min_gap_hours", None) for c in model.constraints}
    max_gap_map = {c.id: getattr(c, "max_gap_hours", None) for c in model.constraints}
    activation_cond_map = {c.id: getattr(c, "activation_condition_raw", None) for c in model.constraints}
    target_cond_map = {c.id: getattr(c, "target_condition_raw", None) for c in model.constraints}

    # Per-constraint aggregates
    cid_counts: dict[str, dict] = {}
    forensics_data: dict[str, dict] = {}

    # Per-stay tracking
    stay_map: dict[str, dict] = {}

    # Episode outcome totals
    outcome_counts: dict[str, int] = {"success": 0, "failure": 0, "unknown": 0, "no_sbt_attempt": 0}
    outcome_violations: dict[str, int] = {"success": 0, "failure": 0, "unknown": 0, "no_sbt_attempt": 0}

    def _ensure_cid(cid: str) -> dict:
        if cid not in cid_counts:
            cid_counts[cid] = {"total": 0, "success": 0, "failure": 0, "satisfied": 0, "vacuous": 0}
            forensics_data[cid] = {
                "violation": {"delays": [], "delay_outcomes": [], "delta_distributions": {}},
                "satisfaction": {"delays": [], "delay_outcomes": [], "delta_distributions": {}},
            }
        return cid_counts[cid]

    for stay_id, trace_results, episode_outcome in episode_data:
        outcome_counts[episode_outcome] = outcome_counts.get(episode_outcome, 0) + 1

        if stay_id not in stay_map:
            stay_map[stay_id] = {
                "episodes": 0, "violations": 0,
                "success_eps": 0, "failure_eps": 0, "unknown_eps": 0, "no_sbt_attempt_eps": 0,
                "violated": set(), "satisfied": set(),
            }
        sm = stay_map[stay_id]
        sm["episodes"] += 1
        sm[f"{episode_outcome}_eps"] = sm.get(f"{episode_outcome}_eps", 0) + 1

        episode_violations = 0
        for trace in trace_results:
            for cr in (trace.constraint_results or []):
                cid = cr.constraint_id
                counts = _ensure_cid(cid)
                fo = forensics_data[cid]

                if cr.outcome == ConformanceOutcome.VIOLATED:
                    counts["total"] += 1
                    counts[episode_outcome] = counts.get(episode_outcome, 0) + 1
                    sm["violated"].add(cid)
                    episode_violations += 1
                    fv = fo["violation"]
                    if cr.delay_seconds is not None:
                        fv["delays"].append(cr.delay_seconds / 3600.0)
                        fv["delay_outcomes"].append(episode_outcome)
                    for k, v in (cr.violation_deltas or {}).items():
                        fv["delta_distributions"].setdefault(k, []).append(v)

                elif cr.outcome == ConformanceOutcome.SATISFIED:
                    counts["satisfied"] += 1
                    sm["satisfied"].add(cid)
                    fs = fo["satisfaction"]
                    if cr.delay_seconds is not None:
                        fs["delays"].append(cr.delay_seconds / 3600.0)
                        fs["delay_outcomes"].append(episode_outcome)
                    for k, v in (cr.satisfaction_deltas or {}).items():
                        fs["delta_distributions"].setdefault(k, []).append(v)

                elif cr.outcome == ConformanceOutcome.VACUOUS:
                    counts["vacuous"] += 1

        sm["violations"] += episode_violations
        outcome_violations[episode_outcome] = outcome_violations.get(episode_outcome, 0) + episode_violations

    total_episodes = len(episode_data)
    total_success = outcome_counts["success"]
    total_failure = outcome_counts["failure"]

    def _compute_stats(a: int, b: int, c: int, d: int):
        """2×2: a=viol&fail, b=viol&succ, c=noviol&fail, d=noviol&succ → p, OR, RR."""
        try:
            _, p_raw = _fisher_exact([[a, c], [b, d]], alternative="two-sided")
        except Exception:
            p_raw = None

        # Use 0.5 continuity correction for OR/RR CI when any cell is 0
        af, bf, cf, df_ = float(a), float(b), float(c), float(d)
        if min(af, bf, cf, df_) == 0.0:
            af += 0.5; bf += 0.5; cf += 0.5; df_ += 0.5

        or_val = or_low = or_high = None
        if bf > 0 and cf > 0:
            or_val = (af * df_) / (bf * cf)
            try:
                log_or = math.log(or_val)
                se_or = math.sqrt(1/af + 1/bf + 1/cf + 1/df_)
                or_low = math.exp(log_or - 1.96 * se_or)
                or_high = math.exp(log_or + 1.96 * se_or)
            except Exception:
                pass

        rr_val = rr_low = rr_high = None
        denom_viol = af + bf
        denom_noviol = cf + df_
        if denom_viol > 0 and denom_noviol > 0:
            p1 = af / denom_viol
            p2 = cf / denom_noviol
            if p1 > 0 and p2 > 0:
                rr_val = p1 / p2
                try:
                    log_rr = math.log(rr_val)
                    se_rr = math.sqrt((1 - p1) / af + (1 - p2) / cf)
                    rr_low = math.exp(log_rr - 1.96 * se_rr)
                    rr_high = math.exp(log_rr + 1.96 * se_rr)
                except Exception:
                    pass

        return p_raw, or_val, or_low, or_high, rr_val, rr_low, rr_high

    violation_frequency = []
    for c in model.constraints:
        cid = c.id
        counts = cid_counts.get(cid, {"total": 0, "success": 0, "failure": 0, "satisfied": 0, "vacuous": 0})

        a = counts.get("failure", 0)
        b = counts.get("success", 0)
        c_cell = max(0, total_failure - a)
        d = max(0, total_success - b)

        p_raw, or_val, or_low, or_high, rr_val, rr_low, rr_high = _compute_stats(a, b, c_cell, d)

        vr_success = b / max(total_success, 1)
        vr_failure = a / max(total_failure, 1)
        overall_vr = counts["total"] / max(total_episodes, 1)

        # Satisfaction rates approximate as (1 - violation_rate) per outcome group
        sr_success = 1.0 - vr_success
        sr_failure = 1.0 - vr_failure

        lift_failure = vr_failure / overall_vr if overall_vr > 0 else 1.0
        lift_success = sr_success / (1.0 - overall_vr) if overall_vr < 1.0 else 1.0

        is_sig = p_raw is not None and p_raw < 0.05
        if is_sig and or_val is not None:
            rule_class = "useful" if or_val > 1 else "harmful"
        else:
            rule_class = "neutral"

        template = template_map.get(cid)
        template_str = template.value if hasattr(template, "value") else (str(template) if template else None)

        violation_frequency.append({
            "constraint_id": cid,
            "constraint_label": label_map.get(cid, cid),
            "rationale": rationale_map.get(cid, ""),
            "template": template_str,
            "activation_condition": activation_cond_map.get(cid),
            "target_condition": target_cond_map.get(cid),
            "min_gap_hours": min_gap_map.get(cid),
            "max_gap_hours": max_gap_map.get(cid),
            "count": counts["total"],
            "count_success": b,
            "count_failure": a,
            "count_satisfied": counts.get("satisfied", 0),
            "count_vacuous": counts.get("vacuous", 0),
            "violation_rate_success": vr_success,
            "violation_rate_failure": vr_failure,
            "satisfaction_rate_success": sr_success,
            "satisfaction_rate_failure": sr_failure,
            "lift_failure": lift_failure,
            "lift_success": lift_success,
            "episode_share": overall_vr,
            "n_exposed": counts["total"],
            "n_unexposed": counts.get("satisfied", 0) + counts.get("vacuous", 0),
            "p_value_raw": p_raw,
            "is_significant": is_sig,
            "odds_ratio": or_val,
            "odds_ratio_low": or_low,
            "odds_ratio_high": or_high,
            "risk_ratio": rr_val,
            "rr_ci_low": rr_low,
            "rr_ci_high": rr_high,
            "rule_class": rule_class,
            "forensics": forensics_data.get(cid, {
                "violation": {"delays": [], "delay_outcomes": [], "delta_distributions": {}},
                "satisfaction": {"delays": [], "delay_outcomes": [], "delta_distributions": {}},
            }),
        })

    # Multiple testing corrections over all constraints with a valid p-value
    try:
        from statsmodels.stats.multitest import multipletests as _multipletests
        _idxs = [i for i, v in enumerate(violation_frequency) if v["p_value_raw"] is not None]
        if _idxs:
            _pvals = [violation_frequency[i]["p_value_raw"] for i in _idxs]
            _, _p_bonf, _, _ = _multipletests(_pvals, method="bonferroni")
            _, _p_fdr, _, _ = _multipletests(_pvals, method="fdr_bh")
            for j, i in enumerate(_idxs):
                violation_frequency[i]["p_value_bonferroni"] = float(_p_bonf[j])
                violation_frequency[i]["p_value_fdr"] = float(_p_fdr[j])
                violation_frequency[i]["is_significant_bonferroni"] = bool(_p_bonf[j] < 0.05)
                violation_frequency[i]["is_significant_fdr"] = bool(_p_fdr[j] < 0.05)
    except Exception:
        pass

    violation_frequency.sort(key=lambda x: -x["count"])

    # Stay summaries
    stay_summaries = []
    for stay_id, sm in stay_map.items():
        s_eps = sm.get("success_eps", 0)
        f_eps = sm.get("failure_eps", 0)
        n_eps = sm.get("no_sbt_attempt_eps", 0)
        if s_eps > 0 and f_eps == 0 and n_eps == 0:
            overall = "Success"
        elif f_eps > 0 and s_eps == 0 and n_eps == 0:
            overall = "Failure"
        elif s_eps > 0 and f_eps > 0:
            overall = "Mixed"
        elif n_eps > 0 and s_eps == 0 and f_eps == 0:
            overall = "No SBT Attempt"
        else:
            overall = "Mixed"
        eps = sm["episodes"]
        stay_summaries.append({
            "stay_id": stay_id,
            "episodes": eps,
            "overall_outcome": overall,
            "total_mandatory_violations": sm["violations"],
            "avg_mandatory_violations": sm["violations"] / max(eps, 1),
            "violated_constraints": list(sm["violated"]),
            "satisfied_constraints": list(sm["satisfied"]),
            "violated_constraints_count": len(sm["violated"]),
        })

    def _avg_viol(outcome: str) -> float:
        eps = outcome_counts.get(outcome, 0)
        return outcome_violations.get(outcome, 0) / max(eps, 1)

    return {
        "total_stays": len(stay_map),
        "total_episodes": total_episodes,
        "violation_frequency": violation_frequency,
        "stay_summaries": stay_summaries,
        "conformance_vs_outcome": {
            "success": {"episodes": total_success, "avg_mandatory_violations": _avg_viol("success")},
            "failure": {"episodes": total_failure, "avg_mandatory_violations": _avg_viol("failure")},
            "unknown": {"episodes": outcome_counts["unknown"], "avg_mandatory_violations": _avg_viol("unknown")},
            "no_sbt_attempt": {"episodes": outcome_counts["no_sbt_attempt"], "avg_mandatory_violations": _avg_viol("no_sbt_attempt")},
        },
        "item_labels": _ITEM_LABELS,
    }


@app.post("/api/query")
def run_query(req: QueryRequest) -> dict[str, Any]:
    """Execute a read-only SQL query against MIMIC and return preview rows."""
    from database.client import get_postgres_connection

    stripped = req.sql.strip()
    if not stripped.lower().startswith("select"):
        raise HTTPException(status_code=400, detail="Only SELECT queries are allowed.")

    limit = min(req.limit, 500)
    sql_lower = stripped.lower()
    if " limit " not in sql_lower:
        query = f"SELECT * FROM ({stripped.rstrip(';')}) __preview LIMIT {limit}"
    else:
        query = stripped

    conn = None
    try:
        conn = get_postgres_connection()
        cur = conn.cursor()
        cur.execute("SET LOCAL statement_timeout = '10s'")
        cur.execute(query)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        return {
            "columns": columns,
            "rows": [list(r) for r in rows],
            "count": len(rows),
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        if conn:
            conn.close()


@app.post("/api/run")
def submit_run(request: RunRequest) -> dict[str, str]:
    """Submit an analysis job; returns job_id immediately."""
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "status": "running",
        "progress": 0.0,
        "total": 0,
        "done": 0,
        "result": None,
        "error": None,
        "created_at": time.time(),
    }
    cancel_event = threading.Event()
    _job_cancel[job_id] = cancel_event

    thread = threading.Thread(target=_run_analysis, args=(job_id, request), daemon=True)
    thread.start()
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    """Poll job status and retrieve results when done."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    job = _jobs[job_id]
    return {
        "status": job["status"],
        "progress": job.get("progress", 0.0),
        "total": job.get("total", 0),
        "done": job.get("done", 0),
        "result": job.get("result"),
        "error": job.get("error"),
        "warnings": job.get("warnings", []),
    }


@app.delete("/api/jobs/{job_id}")
def cancel_job(job_id: str) -> dict[str, str]:
    """Cancel a running job."""
    if job_id not in _job_cancel:
        raise HTTPException(status_code=404, detail="Job not found")
    _job_cancel[job_id].set()
    return {"status": "cancellation_requested"}


@app.get("/api/case/{stay_id}")
def get_case_data(stay_id: str):
    """Serve case event data on demand from the event log parquet."""
    import duckdb as _duckdb
    import math as _math

    event_log_path = PROJECT_ROOT / "data" / "icu_event_log_sample.parquet"
    if not event_log_path.exists():
        raise HTTPException(status_code=404, detail="Event log not available")

    con = _duckdb.connect(database=":memory:")
    con.execute(f"CREATE TABLE events AS SELECT * FROM read_parquet('{event_log_path}')")
    columns = {row[1] for row in con.execute("PRAGMA table_info('events')").fetchall()}
    key_col = "case_id" if "case_id" in columns else "stay_id"

    df = con.execute(f"SELECT * FROM events WHERE {key_col} = ?", [stay_id]).df()
    if df.empty:
        raise HTTPException(status_code=404, detail=f"No data for case {stay_id}")

    df = df.sort_values("timestamp")
    events = []
    for row in df.to_dict(orient="records"):
        cleaned = {}
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                cleaned[k] = v.isoformat()
            elif isinstance(v, float) and _math.isnan(v):
                cleaned[k] = None
            else:
                cleaned[k] = v
        events.append(cleaned)

    return {"case_id": stay_id, "events": events, "conformance": []}
