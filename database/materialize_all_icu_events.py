"""Materialize all ICU events once and export to a local CSV cache.

This script builds a denormalized event-level table from core MIMIC-IV ICU
event tables and writes it to a local file so downstream experiments can run
without querying the database each time.
"""

from __future__ import annotations

import argparse
import gzip
import sys
from pathlib import Path

from psycopg2 import sql

# Allow running this file directly via an absolute path.
if __package__ in {None, ""}:
    sys.path.append(str(Path(__file__).resolve().parents[1]))

from database.client import get_postgres_connection


CREATE_TABLE_SQL_TEMPLATE = """
    CREATE TABLE {{derived_schema}}.{{table_name}} AS
    WITH sbt_stay_ids AS (
        SELECT DISTINCT stay_id
        FROM {{icu_schema}}.chartevents
        WHERE itemid = 224715
          AND LOWER(TRIM(COALESCE(value::text, ''))) = 'yes'
    ),
    all_events AS (
        SELECT
            'chartevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime AS icu_intime,
            s.outtime AS icu_outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.charttime, e.storetime) AS event_time,
            e.charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            COALESCE(e.value::text, e.valuenum::text) AS value_text,
            e.valuenum::double precision AS value_num,
            e.valueuom AS value_uom
        FROM {{icu_schema}}.chartevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

        SELECT
            'datetimeevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime,
            s.outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.charttime, e.storetime) AS event_time,
            e.charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            e.value::text AS value_text,
            NULL::double precision AS value_num,
            NULL::text AS value_uom
        FROM {{icu_schema}}.datetimeevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

        SELECT
            'inputevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime,
            s.outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.starttime, e.endtime, e.storetime) AS event_time,
            NULL::timestamp AS charttime,
            e.starttime,
            e.endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            COALESCE(e.amount::text, e.rate::text) AS value_text,
            COALESCE(e.amount::double precision, e.rate::double precision) AS value_num,
            e.amountuom AS value_uom
        FROM {{icu_schema}}.inputevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

        SELECT
            'outputevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime,
            s.outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.charttime, e.storetime) AS event_time,
            e.charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            e.value::text AS value_text,
            e.value::double precision AS value_num,
            e.valueuom AS value_uom
        FROM {{icu_schema}}.outputevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

        SELECT
            'procedureevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime,
            s.outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.starttime, e.endtime, e.storetime) AS event_time,
            NULL::timestamp AS charttime,
            e.starttime,
            e.endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            e.value::text AS value_text,
            NULL::double precision AS value_num,
            e.valueuom AS value_uom
        FROM {{icu_schema}}.procedureevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

        SELECT
            'ingredientevents'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime,
            s.outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            COALESCE(e.starttime, e.endtime, e.storetime) AS event_time,
            NULL::timestamp AS charttime,
            e.starttime,
            e.endtime,
            e.storetime,
            e.itemid::text AS itemid,
            d.label,
            d.category,
            COALESCE(e.amount::text, e.rate::text) AS value_text,
            COALESCE(e.amount::double precision, e.rate::double precision) AS value_num,
            e.amountuom AS value_uom
        FROM {{icu_schema}}.ingredientevents e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        LEFT JOIN {{icu_schema}}.d_items d ON e.itemid = d.itemid

        UNION ALL

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
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            e.starttime AS event_time,
            NULL::timestamp AS charttime,
            e.starttime,
            e.endtime,
            NULL::timestamp AS storetime,
            'norepinephrine_equiv'::text AS itemid,
            'Norepinephrine-equivalent dose'::text AS label,
            'Vasopressor'::text AS category,
            e.norepinephrine_equivalent_dose::text AS value_text,
            e.norepinephrine_equivalent_dose::double precision AS value_num,
            'mcg/kg/min'::text AS value_uom
        FROM mimiciv_derived.norepinephrine_equivalent_dose e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id

        UNION ALL

        SELECT
            'bg'::text AS source_table,
            s.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime AS icu_intime,
            s.outtime AS icu_outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            e.charttime AS event_time,
            e.charttime AS charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            NULL::timestamp AS storetime,
            cols.itemid::text AS itemid,
            cols.label::text AS label,
            'Blood Gas'::text AS category,
            cols.val::text AS value_text,
            cols.val::double precision AS value_num,
            cols.uom::text AS value_uom
        FROM mimiciv_derived.bg e
        CROSS JOIN LATERAL (
            VALUES 
                ('pao2fio2ratio', 'PaO2/FiO2 Ratio', e.pao2fio2ratio, 'ratio'),
                ('fio2_bg', 'FiO2 (Blood Gas)', COALESCE(e.fio2, e.fio2_chartevents), '%'),
                ('ph_bg', 'pH (Blood Gas)', e.ph, 'units'),
                ('hemoglobin_bg', 'Hemoglobin (Blood Gas)', e.hemoglobin, 'g/dL')
        ) AS cols(itemid, label, val, uom)
        INNER JOIN {{icu_schema}}.icustays s ON e.hadm_id = s.hadm_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        WHERE cols.val IS NOT NULL

        UNION ALL

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
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            e.charttime AS event_time,
            e.charttime AS charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            NULL::timestamp AS storetime,
            cols.itemid::text AS itemid,
            cols.label::text AS label,
            'Ventilation'::text AS category,
            cols.val::text AS value_text,
            cols.val_num::double precision AS value_num,
            cols.uom::text AS value_uom
        FROM mimiciv_derived.ventilator_setting e
        CROSS JOIN LATERAL (
            VALUES 
                ('peep_vent', 'PEEP (Ventilator Setting)', e.peep::text, e.peep, 'cmH2O'),
                ('ventilator_mode', 'Ventilator Mode', e.ventilator_mode, NULL, NULL),
                ('ventilator_mode_hamilton', 'Ventilator Mode (Hamilton)', e.ventilator_mode_hamilton, NULL, NULL),
                ('plateau_pressure', 'Plateau Pressure', e.plateau_pressure::text, e.plateau_pressure, 'cmH2O')
        ) AS cols(itemid, label, val, val_num, uom)
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        WHERE cols.val IS NOT NULL
          AND (
              CASE
                  WHEN e.ventilator_mode IS NULL THEN NULL
                  WHEN LOWER(BTRIM(e.ventilator_mode)) IN ('', 'null', 'none', 'nan', 'nat', '[null]', '<na>') THEN NULL
                  ELSE BTRIM(e.ventilator_mode)
              END IS NOT NULL
              OR
              CASE
                  WHEN e.ventilator_mode_hamilton IS NULL THEN NULL
                  WHEN LOWER(BTRIM(e.ventilator_mode_hamilton)) IN ('', 'null', 'none', 'nan', 'nat', '[null]', '<na>') THEN NULL
                  ELSE BTRIM(e.ventilator_mode_hamilton)
              END IS NOT NULL
          )

        UNION ALL

        -- Derived SBT Detection Logic (using ventilator_setting)
        SELECT
            'sbt_derived'::text AS source_table,
            v.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime AS icu_intime,
            s.outtime AS icu_outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            v.charttime AS event_time,
            v.charttime AS charttime,
            NULL::timestamp AS starttime,
            NULL::timestamp AS endtime,
            NULL::timestamp AS storetime,
            'sbt_status'::text AS itemid,
            'Derived SBT Trigger'::text AS label,
            'Ventilation'::text AS category,
            'Started'::text AS value_text,
            1.0::double precision AS value_num,
            NULL::text AS value_uom
        FROM (
            SELECT 
                vs.stay_id,
                vs.charttime,
                CASE 
                    -- Hamilton logic
                    WHEN vs.ventilator_mode_hamilton_clean IN ('Ambient', 'SPONT', 'CPAP') THEN 'SBT Candidate'
                    WHEN (vs.ventilator_mode_hamilton_clean = 'ASV' AND vs.plateau_pressure - vs.peep <= 8) THEN 'SBT Candidate'
                    -- General mode logic
                    WHEN vs.ventilator_mode_clean IN ('CPAP', 'CPAP/PSV', 'Pressure Support', 'Standby', 'Spontaneous') THEN 'SBT Candidate'
                    ELSE 'Full Support'
                END as weaning_state,
                LAG(
                    CASE 
                        WHEN vs.ventilator_mode_hamilton_clean IN ('Ambient', 'SPONT', 'CPAP') THEN 'SBT Candidate'
                        WHEN (vs.ventilator_mode_hamilton_clean = 'ASV' AND vs.plateau_pressure - vs.peep <= 8) THEN 'SBT Candidate'
                        WHEN vs.ventilator_mode_clean IN ('CPAP', 'CPAP/PSV', 'Pressure Support', 'Standby', 'Spontaneous') THEN 'SBT Candidate'
                        ELSE 'Full Support'
                    END
                ) OVER (PARTITION BY vs.stay_id ORDER BY vs.charttime) as prev_state
            FROM (
                SELECT
                    stay_id,
                    charttime,
                    CASE
                        WHEN ventilator_mode IS NULL THEN NULL
                        WHEN LOWER(BTRIM(ventilator_mode)) IN ('', 'null', 'none', 'nan', 'nat', '[null]', '<na>') THEN NULL
                        ELSE BTRIM(ventilator_mode)
                    END AS ventilator_mode_clean,
                    CASE
                        WHEN ventilator_mode_hamilton IS NULL THEN NULL
                        WHEN LOWER(BTRIM(ventilator_mode_hamilton)) IN ('', 'null', 'none', 'nan', 'nat', '[null]', '<na>') THEN NULL
                        ELSE BTRIM(ventilator_mode_hamilton)
                    END AS ventilator_mode_hamilton_clean,
                    plateau_pressure,
                    peep
                FROM mimiciv_derived.ventilator_setting
            ) vs
            WHERE
                vs.ventilator_mode_clean IS NOT NULL
                OR vs.ventilator_mode_hamilton_clean IS NOT NULL
        ) v
        LEFT JOIN {{icu_schema}}.icustays s ON v.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        WHERE v.weaning_state = 'SBT Candidate' 
          AND (v.prev_state IS NULL OR v.prev_state = 'Full Support')

        UNION ALL

        -- Ventilation Status - Narrowed to 'None' (Liberation) and Fallback for missing settings
        SELECT
            'ventilation'::text AS source_table,
            e.stay_id,
            s.subject_id,
            s.hadm_id,
            s.intime AS icu_intime,
            s.outtime AS icu_outtime,
            a.admittime,
            a.dischtime,
            a.deathtime,
            (a.deathtime IS NOT NULL) AS died_in_hospital,
            e.starttime AS event_time,
            NULL::timestamp AS charttime,
            e.starttime,
            e.endtime,
            NULL::timestamp AS storetime,
            'ventilation_status'::text AS itemid,
            'Ventilation Status'::text AS label,
            'Ventilation'::text AS category,
            e.ventilation_status::text AS value_text,
            NULL::double precision AS value_num,
            NULL::text AS value_uom
        FROM mimiciv_derived.ventilation e
        LEFT JOIN {{icu_schema}}.icustays s ON e.stay_id = s.stay_id
        LEFT JOIN {{hosp_schema}}.admissions a ON s.hadm_id = a.hadm_id
        WHERE e.ventilation_status = 'None' -- Phase 3: Liberation Signal
           OR NOT EXISTS (
               SELECT 1 FROM mimiciv_derived.ventilator_setting vs 
               WHERE vs.stay_id = e.stay_id 
                 AND vs.charttime BETWEEN e.starttime AND e.endtime
           ) -- Phase 2: Strict Fallback
    )
    SELECT *
    FROM all_events
    WHERE event_time IS NOT NULL
      AND stay_id IS NOT NULL
      AND itemid IS NOT NULL
      {sbt_filter}
    """


def _create_table_sql(derived_schema: str, table_name: str, icu_schema: str, hosp_schema: str, sbt_only: bool = False) -> sql.SQL:
    """Generate CREATE TABLE SQL with optional SBT filtering."""
    sbt_filter = "AND stay_id IN (SELECT stay_id FROM sbt_stay_ids)" if sbt_only else ""
    
    sql_str = CREATE_TABLE_SQL_TEMPLATE.format(sbt_filter=sbt_filter)
    return sql.SQL(sql_str).format(
        derived_schema=sql.Identifier(derived_schema),
        table_name=sql.Identifier(table_name),
        icu_schema=sql.Identifier(icu_schema),
        hosp_schema=sql.Identifier(hosp_schema),
    )


def _export_data(cursor, derived_schema: str, table_name: str, output_path: Path) -> None:
    """Export table to CSV or Parquet format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    if output_path.suffix.lower() in {".parquet", ".pq"}:
        _export_parquet(cursor, derived_schema, table_name, output_path)
    else:
        _export_csv(cursor, derived_schema, table_name, output_path)


def _export_csv(cursor, derived_schema: str, table_name: str, output_path: Path) -> None:
    copy_sql = sql.SQL(
        """
        COPY (
            SELECT *
            FROM {derived_schema}.{table_name}
            ORDER BY stay_id, event_time, source_table, itemid
        ) TO STDOUT WITH CSV HEADER
        """
    ).format(
        derived_schema=sql.Identifier(derived_schema),
        table_name=sql.Identifier(table_name),
    )

    if output_path.suffix == ".gz":
        with gzip.open(output_path, "wt", encoding="utf-8", newline="") as f:
            cursor.copy_expert(copy_sql, f)
    else:
        with output_path.open("w", encoding="utf-8", newline="") as f:
            cursor.copy_expert(copy_sql, f)


def _export_parquet(cursor, derived_schema: str, table_name: str, output_path: Path, chunk_size: int = 10000) -> None:
    """Export table to Parquet format without loading the full dataset in memory."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    # Keep a fixed schema across chunks; otherwise all-null chunks can be
    # inferred as `null` and fail against prior timestamp/string columns.
    parquet_schema = pa.schema(
        [
            pa.field("source_table", pa.string()),
            pa.field("stay_id", pa.int64()),
            pa.field("subject_id", pa.int64()),
            pa.field("hadm_id", pa.int64()),
            pa.field("icu_intime", pa.timestamp("us")),
            pa.field("icu_outtime", pa.timestamp("us")),
            pa.field("admittime", pa.timestamp("us")),
            pa.field("dischtime", pa.timestamp("us")),
            pa.field("deathtime", pa.timestamp("us")),
            pa.field("died_in_hospital", pa.bool_()),
            pa.field("event_time", pa.timestamp("us")),
            pa.field("charttime", pa.timestamp("us")),
            pa.field("starttime", pa.timestamp("us")),
            pa.field("endtime", pa.timestamp("us")),
            pa.field("storetime", pa.timestamp("us")),
            pa.field("itemid", pa.string()),
            pa.field("label", pa.string()),
            pa.field("category", pa.string()),
            pa.field("value_text", pa.string()),
            pa.field("value_num", pa.float64()),
            pa.field("value_uom", pa.string()),
        ]
    )

    select_sql = sql.SQL(
        """
        SELECT *
        FROM {derived_schema}.{table_name}
        ORDER BY stay_id, event_time, source_table, itemid
        """
    ).format(
        derived_schema=sql.Identifier(derived_schema),
        table_name=sql.Identifier(table_name),
    )

    writer = None
    try:
        # Fetch column metadata up front; named cursors may not always expose
        # `description` immediately in all driver/code paths.
        with cursor.connection.cursor() as meta_cursor:
            meta_cursor.execute(
                sql.SQL(
                    """
                    SELECT *
                    FROM {derived_schema}.{table_name}
                    LIMIT 0
                    """
                ).format(
                    derived_schema=sql.Identifier(derived_schema),
                    table_name=sql.Identifier(table_name),
                )
            )
            columns = [desc[0] for desc in meta_cursor.description]

        with cursor.connection.cursor(name="materialize_export_cursor") as stream_cursor:
            stream_cursor.itersize = chunk_size
            stream_cursor.execute(select_sql)

            while True:
                rows = stream_cursor.fetchmany(chunk_size)
                if not rows:
                    break

                chunk_data = {
                    col: [row[idx] for row in rows]
                    for idx, col in enumerate(columns)
                }
                table = pa.Table.from_pydict(chunk_data, schema=parquet_schema)

                if writer is None:
                    writer = pq.ParquetWriter(output_path, parquet_schema, compression="snappy")
                writer.write_table(table)

            if writer is None:
                # Preserve behavior for empty tables by writing an empty parquet file.
                empty_table = pa.Table.from_pydict({col: [] for col in columns}, schema=parquet_schema)
                writer = pq.ParquetWriter(output_path, parquet_schema, compression="snappy")
                writer.write_table(empty_table)
    finally:
        if writer is not None:
            writer.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build one local ICU events cache file from MIMIC-IV ICU tables.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/icu_event_level_sbt.parquet"),
        help="Local output file (.csv, .csv.gz, .parquet, or .pq).",
    )
    parser.add_argument(
        "--icu-schema",
        type=str,
        default="mimiciv_icu",
        help="Schema containing ICU event tables.",
    )
    parser.add_argument(
        "--hosp-schema",
        type=str,
        default="mimiciv_hosp",
        help="Schema containing admissions table.",
    )
    parser.add_argument(
        "--derived-schema",
        type=str,
        default="mimiciv_derived",
        help="Schema where denormalized table is created.",
    )
    parser.add_argument(
        "--table-name",
        type=str,
        default="icu_event_level_all",
        help="Name of denormalized table to create.",
    )
    parser.add_argument(
        "--keep-existing-table",
        action="store_true",
        help="Do not drop/recreate the denormalized table.",
    )
    parser.add_argument(
        "--skip-indexes",
        action="store_true",
        help="Skip index creation on the denormalized table.",
    )
    parser.add_argument(
        "--sbt-only",
        action="store_true",
        help="Filter to only stays with SBT Started events (itemid=224715, value=Yes).",
    )
    args = parser.parse_args()

    with get_postgres_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {schema}").format(
                    schema=sql.Identifier(args.derived_schema)
                )
            )

            if not args.keep_existing_table:
                cursor.execute(
                    sql.SQL("DROP TABLE IF EXISTS {schema}.{table}").format(
                        schema=sql.Identifier(args.derived_schema),
                        table=sql.Identifier(args.table_name),
                    )
                )
                cursor.execute(
                    _create_table_sql(
                        derived_schema=args.derived_schema,
                        table_name=args.table_name,
                        icu_schema=args.icu_schema,
                        hosp_schema=args.hosp_schema,
                        sbt_only=args.sbt_only,
                    )
                )

            if not args.skip_indexes:
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {idx_name}
                        ON {schema}.{table} (stay_id)
                        """
                    ).format(
                        idx_name=sql.Identifier(f"idx_{args.table_name}_stay_id"),
                        schema=sql.Identifier(args.derived_schema),
                        table=sql.Identifier(args.table_name),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {idx_name}
                        ON {schema}.{table} (event_time)
                        """
                    ).format(
                        idx_name=sql.Identifier(f"idx_{args.table_name}_event_time"),
                        schema=sql.Identifier(args.derived_schema),
                        table=sql.Identifier(args.table_name),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        """
                        CREATE INDEX IF NOT EXISTS {idx_name}
                        ON {schema}.{table} (itemid)
                        """
                    ).format(
                        idx_name=sql.Identifier(f"idx_{args.table_name}_itemid"),
                        schema=sql.Identifier(args.derived_schema),
                        table=sql.Identifier(args.table_name),
                    )
                )

            cursor.execute(
                sql.SQL("SELECT COUNT(*) FROM {schema}.{table}").format(
                    schema=sql.Identifier(args.derived_schema),
                    table=sql.Identifier(args.table_name),
                )
            )
            row_count = int(cursor.fetchone()[0])

            _export_data(
                cursor=cursor,
                derived_schema=args.derived_schema,
                table_name=args.table_name,
                output_path=args.output,
            )

        conn.commit()

    print(f"Materialized rows: {row_count}")
    print(f"Saved local cache: {args.output}")


if __name__ == "__main__":
    main()
