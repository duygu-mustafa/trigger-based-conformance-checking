"""Materialize derived weaning events once and export to a local CSV cache.

This script fetches data from mimiciv_derived.ventilation and 
mimiciv_derived.ventilator_setting for all relevant stays and saves it locally.
"""

import pandas as pd
from database.client import get_postgres_connection
from pathlib import Path

QUERY = """
WITH vent AS (
    SELECT 
        stay_id, 
        starttime, 
        endtime, 
        ventilation_status
    FROM mimiciv_derived.ventilation
),
settings AS (
    SELECT 
        stay_id, 
        charttime, 
        ventilator_mode, 
        ventilator_mode_hamilton,
        plateau_pressure,
        peep
    FROM mimiciv_derived.ventilator_setting
)
SELECT 
    COALESCE(v.stay_id, s.stay_id) as stay_id,
    COALESCE(s.charttime, v.starttime) as event_time,
    v.starttime,
    v.endtime,
    v.ventilation_status,
    s.ventilator_mode,
    s.ventilator_mode_hamilton,
    s.plateau_pressure,
    s.peep
FROM vent v
FULL OUTER JOIN settings s ON v.stay_id = s.stay_id 
    AND (
        (s.charttime >= v.starttime AND s.charttime <= v.endtime)
        OR (v.starttime IS NULL OR s.charttime IS NULL)
    )
ORDER BY stay_id, event_time
"""

def materialize_weaning_data(output_path: str = "weaning_derived_all.csv"):
    print("Fetching weaning data from database...")
    with get_postgres_connection() as conn:
        df = pd.read_sql_query(QUERY, conn)
    
    print(f"Fetched {len(df)} rows. Saving to {output_path}...")
    df.to_csv(output_path, index=False)
    print("Done.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="weaning_derived_all.csv", help="Output CSV file path")
    args = parser.parse_args()
    
    materialize_weaning_data(args.output)
