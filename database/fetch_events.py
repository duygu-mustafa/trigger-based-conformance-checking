"""Fetch ICU event-level rows with timestamps for a given stay_id."""

from __future__ import annotations

from typing import Iterable

import pandas as pd
from psycopg2 import sql

from database.client import get_postgres_connection


ICU_EVENT_TABLES = [
    "chartevents",
    "datetimeevents",
    "inputevents",
    "outputevents",
    "procedureevents",
    "ingredientevents",
]


def _get_table_columns(cursor, schema: str, table: str) -> set[str]:
    cursor.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    return {row[0] for row in cursor.fetchall()}


def _optional_column_expr(column_name: str, available: set[str]) -> sql.SQL:
    if column_name in available:
        return sql.SQL("e.{col}").format(col=sql.Identifier(column_name))
    return sql.SQL("NULL")


def _value_num_expr(available: set[str]) -> sql.SQL:
    candidates: list[sql.SQL] = []
    if "valuenum" in available:
        candidates.append(sql.SQL("e.valuenum::double precision"))
    if "amount" in available:
        candidates.append(sql.SQL("e.amount::double precision"))
    if "rate" in available:
        candidates.append(sql.SQL("e.rate::double precision"))

    if not candidates:
        return sql.SQL("NULL::double precision")
    if len(candidates) == 1:
        return candidates[0]
    return sql.SQL("COALESCE({parts})").format(parts=sql.SQL(", ").join(candidates))


def _value_text_expr(available: set[str]) -> sql.SQL:
    candidates: list[sql.SQL] = []
    if "value" in available:
        candidates.append(sql.SQL("e.value::text"))
    if "valuenum" in available:
        candidates.append(sql.SQL("e.valuenum::text"))
    if "amount" in available:
        candidates.append(sql.SQL("e.amount::text"))
    if "rate" in available:
        candidates.append(sql.SQL("e.rate::text"))

    if not candidates:
        return sql.SQL("NULL::text")
    if len(candidates) == 1:
        return candidates[0]
    return sql.SQL("COALESCE({parts})").format(parts=sql.SQL(", ").join(candidates))


def _event_time_expr(available: set[str]) -> sql.SQL:
    candidates: list[sql.SQL] = []
    for c in ["charttime", "starttime", "endtime", "storetime"]:
        if c in available:
            candidates.append(sql.SQL("e.{col}").format(col=sql.Identifier(c)))

    if not candidates:
        return sql.SQL("NULL::timestamp")
    if len(candidates) == 1:
        return candidates[0]
    return sql.SQL("COALESCE({parts})").format(parts=sql.SQL(", ").join(candidates))


def _build_table_query(schema: str, table: str, available: set[str]) -> sql.SQL:
    """Build a per-table SELECT that returns a normalized event schema."""
    return sql.SQL(
        """
        SELECT
            {table_name}::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime AS icu_intime,
            s.outtime AS icu_outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            CASE WHEN a.deathtime IS NOT NULL THEN TRUE ELSE FALSE END AS died_in_hospital,
            {event_time} AS event_time,
            {charttime} AS charttime,
            {starttime} AS starttime,
            {endtime} AS endtime,
            {storetime} AS storetime,
            {itemid} AS itemid,
            d.label,
            d.category,
            {value_text} AS value_text,
            {value_num} AS value_num,
            {value_uom} AS value_uom
        FROM {schema}.{table} e
        LEFT JOIN {schema}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN mimiciv_hosp.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {schema}.d_items d ON e.itemid = d.itemid
        WHERE e.stay_id = %s
        """
    ).format(
        table_name=sql.Literal(table),
        event_time=_event_time_expr(available),
        charttime=_optional_column_expr("charttime", available),
        starttime=_optional_column_expr("starttime", available),
        endtime=_optional_column_expr("endtime", available),
        storetime=_optional_column_expr("storetime", available),
        itemid=_optional_column_expr("itemid", available),
        value_text=_value_text_expr(available),
        value_num=_value_num_expr(available),
        value_uom=_optional_column_expr("valueuom", available),
        schema=sql.Identifier(schema),
        table=sql.Identifier(table),
    )


def fetch_icu_events_for_stay(stay_id: int, tables: Iterable[str] | None = None) -> pd.DataFrame:
    """Fetch timestamped ICU events for one stay from all selected ICU tables.

    Returned columns:
    source_table, stay_id, subject_id, hadm_id, icu_intime, icu_outtime,
    admittime, dischtime, deathtime, died_in_hospital, event_time, charttime,
    starttime, endtime, storetime, itemid, label, category, value_text,
    value_num, value_uom
    """
    schema = "mimiciv_icu"
    selected_tables = list(tables) if tables is not None else ICU_EVENT_TABLES

    with get_postgres_connection() as connection:
        with connection.cursor() as cursor:
            frames: list[pd.DataFrame] = []

            for table in selected_tables:
                available = _get_table_columns(cursor, schema=schema, table=table)
                if "stay_id" not in available or "itemid" not in available:
                    continue

                query = _build_table_query(schema=schema, table=table, available=available)
                cursor.execute(query, (int(stay_id),))
                rows = cursor.fetchall()
                cols = [d.name for d in cursor.description]

                if rows:
                    frames.append(pd.DataFrame(rows, columns=cols))

            # Fetch Norepinephrine Equivalent Dose from derived schema
            cursor.execute(
                """
                SELECT
                    'norepinephrine_equivalent_dose'::text AS source_table,
                    e.stay_id,
                    s.subject_id,
                    s.hadm_id,
                    s.intime AS icu_intime,
                    s.outtime AS icu_outtime,
                    a.admittime,
                    a.dischtime,
                    a.deathtime,
                    CASE WHEN a.deathtime IS NOT NULL THEN TRUE ELSE FALSE END AS died_in_hospital,
                    e.starttime AS event_time,
                    NULL::timestamp AS charttime,
                    e.starttime,
                    e.endtime,
                    NULL::timestamp AS storetime,
                    'norepinephrine_equiv' AS itemid,
                    'Norepinephrine-equivalent dose' AS label,
                    'Vasopressor' AS category,
                    e.norepinephrine_equivalent_dose::text AS value_text,
                    e.norepinephrine_equivalent_dose::double precision AS value_num,
                    'mcg/kg/min' AS value_uom
                FROM mimiciv_derived.norepinephrine_equivalent_dose e
                LEFT JOIN mimiciv_icu.icustays s ON e.stay_id = s.stay_id
                LEFT JOIN mimiciv_hosp.admissions a ON s.hadm_id = a.hadm_id
                WHERE e.stay_id = %s
                """,
                (int(stay_id),),
            )
            rows = cursor.fetchall()
            if rows:
                cols = [d.name for d in cursor.description]
                frames.append(pd.DataFrame(rows, columns=cols))

            # Fetch derived blood gas fields from mimiciv_derived.bg
            cursor.execute(
                """
                SELECT
                    'bg'::text AS source_table,
                    e.stay_id,
                    s.subject_id,
                    s.hadm_id,
                    s.intime AS icu_intime,
                    s.outtime AS icu_outtime,
                    a.admittime,
                    a.dischtime,
                    a.deathtime,
                    CASE WHEN a.deathtime IS NOT NULL THEN TRUE ELSE FALSE END AS died_in_hospital,
                    e.charttime AS event_time,
                    e.charttime AS charttime,
                    NULL::timestamp AS starttime,
                    NULL::timestamp AS endtime,
                    NULL::timestamp AS storetime,
                    cols.itemid,
                    cols.label,
                    'Blood Gas' AS category,
                    cols.val::text AS value_text,
                    cols.val::double precision AS value_num,
                    cols.uom AS value_uom
                FROM mimiciv_derived.bg e
                CROSS JOIN LATERAL (
                    VALUES 
                        ('pao2fio2ratio', 'PaO2/FiO2 Ratio', e.pao2fio2ratio, 'ratio'),
                        ('fio2_bg', 'FiO2 (Blood Gas)', COALESCE(e.fio2, e.fio2_chartevents), '%'),
                        ('ph_bg', 'pH (Blood Gas)', e.ph, 'units'),
                        ('hemoglobin_bg', 'Hemoglobin (Blood Gas)', e.hemoglobin, 'g/dL')
                ) AS cols(itemid, label, val, uom)
                LEFT JOIN mimiciv_icu.icustays s ON e.stay_id = s.stay_id
                LEFT JOIN mimiciv_hosp.admissions a ON s.hadm_id = a.hadm_id
                WHERE e.stay_id = %s AND cols.val IS NOT NULL
                """,
                (int(stay_id),),
            )
            rows = cursor.fetchall()
            if rows:
                cols = [d.name for d in cursor.description]
                frames.append(pd.DataFrame(rows, columns=cols))

            # Fetch PEEP from ventilator_setting
            cursor.execute(
                """
                SELECT
                    'ventilator_setting'::text AS source_table,
                    e.stay_id,
                    s.subject_id,
                    s.hadm_id,
                    s.intime AS icu_intime,
                    s.outtime AS icu_outtime,
                    a.admittime,
                    a.dischtime,
                    a.deathtime,
                    CASE WHEN a.deathtime IS NOT NULL THEN TRUE ELSE FALSE END AS died_in_hospital,
                    e.charttime AS event_time,
                    e.charttime AS charttime,
                    NULL::timestamp AS starttime,
                    NULL::timestamp AS endtime,
                    NULL::timestamp AS storetime,
                    'peep_vent' AS itemid,
                    'PEEP (Ventilator Setting)' AS label,
                    'Ventilation' AS category,
                    e.peep::text AS value_text,
                    e.peep::double precision AS value_num,
                    'cmH2O' AS value_uom
                FROM mimiciv_derived.ventilator_setting e
                LEFT JOIN mimiciv_icu.icustays s ON e.stay_id = s.stay_id
                LEFT JOIN mimiciv_hosp.admissions a ON s.hadm_id = a.hadm_id
                WHERE e.stay_id = %s AND e.peep IS NOT NULL
                """,
                (int(stay_id),),
            )
            rows = cursor.fetchall()
            if rows:
                cols = [d.name for d in cursor.description]
                frames.append(pd.DataFrame(rows, columns=cols))

    if not frames:
        return pd.DataFrame(
            columns=[
                "source_table",
                "stay_id",
                "subject_id",
                "hadm_id",
                "icu_intime",
                "icu_outtime",
                "admittime",
                "dischtime",
                "deathtime",
                "died_in_hospital",
                "event_time",
                "charttime",
                "starttime",
                "endtime",
                "storetime",
                "itemid",
                "label",
                "category",
                "value_text",
                "value_num",
                "value_uom",
            ]
        )

    out = pd.concat(frames, ignore_index=True)
    out["event_time"] = pd.to_datetime(out["event_time"], errors="coerce")
    out = out.dropna(subset=["event_time", "stay_id", "itemid"]).copy()
    out = out.sort_values(["event_time", "source_table", "itemid"]).reset_index(drop=True)

    return out
