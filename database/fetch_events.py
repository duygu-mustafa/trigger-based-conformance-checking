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
    source_table, stay_id, event_time, charttime, starttime, endtime, storetime,
    itemid, label, category, value_text, value_num, value_uom
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

    if not frames:
        return pd.DataFrame(
            columns=[
                "source_table",
                "stay_id",
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
