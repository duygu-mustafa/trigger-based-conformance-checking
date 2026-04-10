"""Functions to fetch derived status and settings for a stay."""

import pandas as pd
from database.client import get_postgres_connection

def fetch_weaning_data_for_stay(stay_id: int) -> pd.DataFrame:
    """
    Fetches and joins ventilation status and ventilator settings for a stay.
    Useful for defining SBT start/end and success/failure.
    """
    query = f"""
    WITH vent AS (
        SELECT 
            stay_id, 
            starttime, 
            endtime, 
            ventilation_status
        FROM mimiciv_derived.ventilation
        WHERE stay_id = {stay_id}
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
        WHERE stay_id = {stay_id}
    )
    SELECT 
        COALESCE(v.stay_id, s.stay_id) as stay_id,
        COALESCE(v.starttime, s.charttime) as charttime,
        v.starttime,
        v.endtime,
        v.ventilation_status,
        s.ventilator_mode,
        s.ventilator_mode_hamilton,
        s.plateau_pressure,
        s.peep
    FROM vent v
    FULL OUTER JOIN settings s ON v.stay_id = s.stay_id 
        AND s.charttime >= v.starttime AND s.charttime <= v.endtime
    ORDER BY charttime
    """
    with get_postgres_connection() as conn:
        df = pd.read_sql_query(query, conn)
    return df

def fetch_extubation_times_for_stay(stay_id: int) -> pd.DataFrame:
    """
    Fetches extubation events for a stay from thoracic or general procedures if available,
    or inferred from ventilation status changes to 'None'.
    For now, we use the ventilation table's transition to 'None'.
    """
    query = f"""
    SELECT 
        stay_id, 
        starttime as extubation_time
    FROM mimiciv_derived.ventilation
    WHERE stay_id = {stay_id} AND ventilation_status = 'None'
    ORDER BY starttime
    """
    with get_postgres_connection() as conn:
        df = pd.read_sql_query(query, conn)
    return df
