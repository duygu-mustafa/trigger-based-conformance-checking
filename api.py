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

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

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


class CustomEventType(BaseModel):
    name: str
    kind: str = "table"                        # "table" | "sql"
    source_table: Optional[str] = None
    itemids: Optional[list[int | str]] = None
    value_filter: Optional[ValueFilter] = None
    sql: Optional[str] = None                  # populated when kind="sql"


class QueryRequest(BaseModel):
    sql: str
    limit: int = 200


class RunRequest(BaseModel):
    sample_size: int = 50
    seed: int = 42
    include_predefined: bool = True
    custom_rules: list[CustomRuleInput] = []
    custom_event_types: list[CustomEventType] = []
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

    table_types = [et for et in event_types if et.kind != "sql"]
    sql_types = [et for et in event_types if et.kind == "sql" and et.sql]

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

        event_log_path = PROJECT_ROOT / "data" / "icu_event_log.parquet"
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

        all_results = []
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
                df = df.sort_values("timestamp").reset_index(drop=True)

            if not df.empty:
                for episode_df in _split_into_episodes(df, request.trigger_event):
                    trace_results = check_log_conformance(episode_df, combined)
                    if trace_results:
                        all_results.extend(trace_results)

            job["done"] = job.get("done", 0) + 1
            job["progress"] = job["done"] / job["total"]

        # Build summary in same shape as summary.json
        summary = _build_minimal_summary(all_results, combined)

        job["result"] = summary
        job["status"] = "done"

    except Exception as exc:
        import traceback
        job["status"] = "error"
        job["error"] = str(exc)
        job["traceback"] = traceback.format_exc()


def _build_minimal_summary(results: list, model) -> dict[str, Any]:
    """Fallback summary builder when outcome_postprocessing is unavailable."""
    from conformance.results import ConformanceOutcome

    label_map = {c.id: getattr(c, "label", c.id) for c in model.constraints}

    violation_counts: dict[str, int] = {}
    episode_count = 0

    for r in results:
        episode_count += 1
        violated = [
            cr.constraint_id
            for cr in (r.constraint_results or [])
            if cr.outcome == ConformanceOutcome.VIOLATED
        ]
        for cid in violated:
            violation_counts[cid] = violation_counts.get(cid, 0) + 1

    violation_frequency = [
        {
            "constraint_id": cid,
            "constraint_label": label_map.get(cid, cid),
            "count": cnt,
            "episode_share": cnt / max(episode_count, 1),
        }
        for cid, cnt in sorted(violation_counts.items(), key=lambda x: -x[1])
    ]

    return {
        "total_episodes": episode_count,
        "violation_frequency": violation_frequency,
        "stay_summaries": [],
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
