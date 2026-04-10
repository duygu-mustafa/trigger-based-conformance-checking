"""Persistent storage for local data ingestion of derived stay events."""

import pandas as pd
from pathlib import Path
from database.fetch_events import fetch_icu_events_for_stay
from database.fetch_weaning import fetch_weaning_data_for_stay
import os

CACHE_DIR = Path("data/raw")

def ensure_cache_dir():
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)

def fetch_and_save_stay_data(stay_id: int) -> str:
    """
    Fetches all necessary ICU events and derived weaning data for a stay
    and saves them to local CSVs for computations.
    """
    ensure_cache_dir()
    
    # 1. Fetch ICU events (native and norepinephrine_equiv)
    events_df = fetch_icu_events_for_stay(stay_id)
    events_path = CACHE_DIR / f"icu_stay_{stay_id}_event_level.csv"
    events_df.to_csv(events_path, index=False)
    
    # 2. Fetch Weaning derived data
    weaning_df = fetch_weaning_data_for_stay(stay_id)
    weaning_path = CACHE_DIR / f"icu_stay_{stay_id}_weaning_events.csv"
    weaning_df.to_csv(weaning_path, index=False)
    
    return str(events_path)

def load_cached_stay_events(stay_id: int) -> pd.DataFrame:
    path = CACHE_DIR / f"icu_stay_{stay_id}_event_level.csv"
    if path.exists():
        return pd.read_csv(path)
    return fetch_icu_events_for_stay(stay_id)

def load_cached_weaning_events(stay_id: int) -> pd.DataFrame:
    path = CACHE_DIR / f"icu_stay_{stay_id}_weaning_events.csv"
    if path.exists():
         df = pd.read_csv(path)
         df['charttime'] = pd.to_datetime(df['charttime'])
         return df
    return fetch_weaning_data_for_stay(stay_id)
