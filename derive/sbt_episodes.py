"""Episode construction anchored on SBT events."""

import pandas as pd
from typing import Optional


_MISSING_TEXT_TOKENS = {"", "none", "null", "nan", "nat", "[null]", "<na>"}


def _is_missing_text_value(value: object) -> bool:
    if pd.isna(value):
        return True
    text = str(value).strip().lower()
    return text in _MISSING_TEXT_TOKENS


def _non_missing_text_mask(series: pd.Series) -> pd.Series:
    return ~series.map(_is_missing_text_value)


# Explicit ventilator mode to category mapping based on clinical evidence.
# Maps from mode strings to one of: "Liberated/Non-Invasive", "Full Invasive Support", or "SBT"
_VENTILATOR_MODE_MAPPING = {
    # ventilator_mode column
    "Ambient": "Liberated/Non-Invasive",
    "Apnea Ventilation": "Full Invasive Support",
    "APRV": "Full Invasive Support",
    "APRV/Biphasic+ApnPress": "Full Invasive Support",
    "APRV/Biphasic+ApnVol": "Full Invasive Support",
    "APV (cmv)": "Full Invasive Support",
    "CMV": "Full Invasive Support",
    "CMV/ASSIST": "Full Invasive Support",
    "CMV/ASSIST/AutoFlow": "Full Invasive Support",
    "CMV/AutoFlow": "Full Invasive Support",
    "CPAP": "SBT",
    "CPAP/PPS": "SBT",
    "CPAP/PSV": "SBT",
    "CPAP/PSV+ApnPres": "SBT",
    "CPAP/PSV+Apn TCPL": "SBT",
    "CPAP/PSV+ApnVol": "SBT",
    "DuoPaP": "Full Invasive Support",
    "MMV": "Full Invasive Support",
    "MMV/AutoFlow": "Full Invasive Support",
    "MMV/PSV": "SBT",
    "MMV/PSV/AutoFlow": "SBT",
    "P-CMV": "Full Invasive Support",
    "PCV+": "Full Invasive Support",
    "PCV+Assist": "Full Invasive Support",
    "PCV+/PSV": "SBT",
    "PRES/AC": "Full Invasive Support",
    "PRVC/AC": "Full Invasive Support",
    "PRVC/SIMV": "Full Invasive Support",
    "P-SIMV": "Full Invasive Support",
    "PSV/SBT": "SBT",
    "(S) CMV": "Full Invasive Support",
    "SIMV": "Full Invasive Support",
    "SIMV/AutoFlow": "Full Invasive Support",
    "SIMV/PRES": "Full Invasive Support",
    "SIMV/PSV": "SBT",
    "SIMV/PSV/AutoFlow": "SBT",
    "SIMV/VOL": "Full Invasive Support",
    "SPONT": "SBT",
    "Standby": "Liberated/Non-Invasive",
    "SYNCHRON MASTER": "Full Invasive Support",
    "SYNCHRON SLAVE": "Full Invasive Support",
    "VOL/AC": "Full Invasive Support",
}

_VENTILATOR_MODE_HAMILTON_MAPPING = {
    # ventilator_mode_hamilton column
    "Ambient": "Liberated/Non-Invasive",
    "APRV": "Full Invasive Support",
    "APV (cmv)": "Full Invasive Support",
    "APV (simv)": "Full Invasive Support",
    "ASV": "Full Invasive Support",
    "DuoPaP": "Full Invasive Support",
    "nCPAP-PS": "Liberated/Non-Invasive",
    "NIV": "Liberated/Non-Invasive",
    "NIV-ST": "Liberated/Non-Invasive",
    "P-CMV": "Full Invasive Support",
    "P-SIMV": "Full Invasive Support",
    "(S) CMV": "Full Invasive Support",
    "SIMV": "Full Invasive Support",
    "SPONT": "SBT",
    "VS": "SBT",
}


# Direct mode→state lookups (skip intermediate category for vectorized path)
_HAMILTON_TO_STATE = {
    k: ("Full Support" if v == "Full Invasive Support" else "SBT Candidate")
    for k, v in _VENTILATOR_MODE_HAMILTON_MAPPING.items()
}
_MODE_TO_STATE = {
    k: ("Full Support" if v == "Full Invasive Support" else "SBT Candidate")
    for k, v in _VENTILATOR_MODE_MAPPING.items()
}


def vectorized_weaning_states(df: pd.DataFrame) -> pd.Series:
    """Vectorized equivalent of apply(map_weaning_state, axis=1) over a DataFrame."""
    def _clean(col: str) -> pd.Series:
        s = df[col].astype(str).str.strip()
        return s.where(~df[col].isna() & ~s.str.lower().isin(_MISSING_TEXT_TOKENS))

    hamilton_state = _clean("ventilator_mode_hamilton").map(_HAMILTON_TO_STATE)
    general_state = _clean("ventilator_mode").map(_MODE_TO_STATE)
    return hamilton_state.fillna(general_state).fillna("Other")


def _map_category_to_state(category: str | None) -> str:
    """Convert clinical category to weaning state for SBT detection."""
    if category == "SBT":
        return "SBT Candidate"
    elif category == "Liberated/Non-Invasive":
        return "SBT Candidate"
    elif category == "Full Invasive Support":
        return "Full Support"
    else:
        return "Other"


def map_weaning_state(row: pd.Series) -> str:
    """
    Classifies a timepoint into a weaning state with preference for ventilator settings.
    Uses explicit clinical mapping tables from evidence-based ventilator mode definitions.
    
    Returns one of:
    - 'SBT Candidate': Patient ready for spontaneous breathing trial (includes liberated modes).
    - 'Full Support': Patient on mandatory/controlled ventilation.
    - 'Liberated': Confirmed extubation/liberation signal.
    - 'Other': Unmapped or ambiguous mode.
    """
    # 1. Prefer hamilton-specific mode if available (more granular)
    hamilton_mode_raw = row.get('ventilator_mode_hamilton')
    general_mode_raw = row.get('ventilator_mode')
    
    hamilton_mode = None if _is_missing_text_value(hamilton_mode_raw) else str(hamilton_mode_raw).strip()
    general_mode = None if _is_missing_text_value(general_mode_raw) else str(general_mode_raw).strip()
    
    # Check Hamilton mode mapping first
    if hamilton_mode and hamilton_mode in _VENTILATOR_MODE_HAMILTON_MAPPING:
        category = _VENTILATOR_MODE_HAMILTON_MAPPING[hamilton_mode]
        state = _map_category_to_state(category)
        if state != "Other":
            return state
    
    # Fall back to general ventilator mode mapping
    if general_mode and general_mode in _VENTILATOR_MODE_MAPPING:
        category = _VENTILATOR_MODE_MAPPING[general_mode]
        state = _map_category_to_state(category)
        if state != "Other":
            return state

    return 'Other'

def build_sbt_episodes(weaning_df: pd.DataFrame, debounce_minutes: int = 120) -> pd.DataFrame:
    """
    Processes a time-series of weaning states to find SBT episodes.
    - SBT Start: Transition to 'SBT Candidate'.
    - SBT End: Successful liberation or return to 'Full Support' (failure).
    - Debounce: Brief returns to 'Full Support' or state changes within `debounce_minutes` 
      are merged into the current episode to avoid fragmented trials.
    """
    if weaning_df.empty:
        return pd.DataFrame()

    df = weaning_df.copy()
    # Require at least one non-null ventilator setting to classify a row.
    setting_cols = ["ventilator_mode", "ventilator_mode_hamilton", "plateau_pressure", "peep"]
    missing_setting_cols = [c for c in setting_cols if c not in df.columns]
    for col in missing_setting_cols:
        df[col] = pd.NA

    mode_non_empty = df[["ventilator_mode", "ventilator_mode_hamilton"]].apply(
        _non_missing_text_mask,
    )
    numeric_non_null = df[["plateau_pressure", "peep"]].notna()
    keep_mask = pd.concat([mode_non_empty, numeric_non_null], axis=1).any(axis=1)
    df = df.loc[keep_mask].copy()
    if df.empty:
        return pd.DataFrame()

    df['weaning_state'] = df.apply(map_weaning_state, axis=1)

    all_episodes = []
    for _, group in df.groupby('stay_id', sort=False):
        group = group.sort_values('charttime').reset_index(drop=True)

        episodes = []
        current_episode = None

        for i, row in group.iterrows():
            state = row['weaning_state']
            time = row['charttime']

            # Transition to SBT Candidate: Start an episode if not already in one
            if state == 'SBT Candidate' and current_episode is None:
                current_episode = {
                    'stay_id': row['stay_id'],
                    'sbt_start_time': time,
                    'last_time': time,
                    'is_success': False
                }

            elif current_episode is not None:
                # Transition to Liberated: Mark success and close episode
                if state == 'Liberated':
                    current_episode['extubation_time'] = time
                    current_episode['is_success'] = True
                    current_episode['sbt_duration_minutes'] = (time - current_episode['sbt_start_time']).total_seconds() / 60
                    episodes.append(current_episode)
                    current_episode = None

                # Transition back to Full Support: Check for failure vs brief fluctuation
                elif state == 'Full Support':
                    # Look ahead to see if they return to SBT Candidate soon (debounce)
                    is_permanent_failure = True
                    look_ahead_idx = i + 1
                    while look_ahead_idx < len(group):
                        next_row = group.iloc[look_ahead_idx]
                        gap = (next_row['charttime'] - time).total_seconds() / 60
                        if gap > debounce_minutes:
                            break
                        if next_row['weaning_state'] == 'SBT Candidate':
                            is_permanent_failure = False # Brief dip, don't fail yet
                            break
                        look_ahead_idx += 1

                    if is_permanent_failure:
                        current_episode['failure_time'] = time
                        current_episode['is_success'] = False
                        current_episode['sbt_duration_minutes'] = (time - current_episode['sbt_start_time']).total_seconds() / 60
                        episodes.append(current_episode)
                        current_episode = None
                    else:
                        # Brief fluctuation, keep current episode alive
                        current_episode['last_time'] = time

                else:
                    current_episode['last_time'] = time

        # Episode still open at end of stay — emit start anchor, outcome decided by _derive_activities
        if current_episode is not None:
            episodes.append(current_episode)

        all_episodes.extend(episodes)

    return pd.DataFrame(all_episodes)

