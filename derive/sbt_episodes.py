"""Episode construction anchored on SBT events."""

import pandas as pd
from typing import Optional

def map_weaning_state(row: pd.Series) -> str:
    """
    Classifies a timepoint into a weaning state with preference for ventilator settings.
    - Full Support: Any mode suggesting mandatory/controlled ventilation.
    - SBT Candidate: CPAP, SPONT, Ambient, ASV with low support, or Supplemental oxygen.
    - Liberated: None (from ventilation status) or explicitly 'None' in settings.
    """
    # 1. Start with ventilator modes as they are more granular/reliable
    hamilton_mode = row.get('ventilator_mode_hamilton')
    general_mode = row.get('ventilator_mode')
    
    # Hamilton specific logic (ASV, Ambient, etc.)
    if hamilton_mode and pd.notna(hamilton_mode):
        hamilton_mode = str(hamilton_mode)
        if hamilton_mode == 'Ambient':
            return 'SBT Candidate'
        if hamilton_mode == 'ASV':
            peep = row.get('peep', 0) or 0
            plateau = row.get('plateau_pressure', 0) or 0
            # ASV with pressure support <= 8 is a candidate
            if plateau - peep > 0 and (plateau - peep) <= 8:
                return 'SBT Candidate'
            return 'Full Support'
        if hamilton_mode in ['SPONT', 'CPAP']:
            return 'SBT Candidate'
        # Mandatory modes
        if 'cmv' in hamilton_mode.lower() or 'SIMV' in hamilton_mode:
            return 'Full Support'

    # General mode logic
    if general_mode and pd.notna(general_mode):
        general_mode = str(general_mode)
        if general_mode in ['CPAP', 'CPAP/PSV', 'Pressure Support', 'Standby', 'Spontaneous']:
            return 'SBT Candidate'
        if 'Control' in general_mode or 'Assist' in general_mode:
            return 'Full Support'

    # 2. Fallback to ventilation_status if settings are missing or ambiguous
    status = row.get('ventilation_status')
    if status == 'InvasiveVent':
        return 'Full Support'
    if status in ['SupplementalOxygen', 'HFNC', 'NonInvasiveVent']:
        return 'SBT Candidate'
    if status == 'None':
        return 'Liberated'
        
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
    df['weaning_state'] = df.apply(map_weaning_state, axis=1)

    # Sort by time and reset index
    df = df.sort_values('charttime').reset_index(drop=True)

    episodes = []
    current_episode = None

    for i, row in df.iterrows():
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
                while look_ahead_idx < len(df):
                    next_row = df.iloc[look_ahead_idx]
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
            
            # Handle End of Data
            elif i == len(df) - 1:
                current_episode['extubation_time'] = time
                current_episode['is_success'] = True
                current_episode['sbt_duration_minutes'] = (time - current_episode['sbt_start_time']).total_seconds() / 60
                episodes.append(current_episode)
                current_episode = None
            
            else:
                current_episode['last_time'] = time

    return pd.DataFrame(episodes)

