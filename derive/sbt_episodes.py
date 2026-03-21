"""Episode construction anchored on SBT events."""

import pandas as pd


def build_sbt_episodes(signal_df: pd.DataFrame) -> pd.DataFrame:
    return signal_df.copy()
