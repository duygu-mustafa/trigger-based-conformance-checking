"""Convert categorical string values to numerical codes for clinical measurements.

Maps MIMIC-IV chartevents with ordinal/categorical string values to numerical scales
for use in conformance checking conditions. Handles case-insensitive matching.
"""

from __future__ import annotations

import pandas as pd


# Mapping definitions: itemid -> ordinal scale
CATEGORICAL_MAPPINGS = {
    # Sedation / Consciousness
    223753: {  # Riker-SAS Scale
        "unarousable": 1,
        "very sedated": 2,
        "sedated": 3,
        "calm/cooperative": 4,
        "calm": 4,  # Alternative name
        "agitated": 5,
        "very agitated": 6,
        "danger agitation": 7,
    },
    # Respiratory Effort
    229322: {  # Breathing pattern/effort
        "regular": 0,
        "shallow": 1,
        "tachypneic (rr > 35 b/min)": 1,
        "tachypneic": 1,
        "prolonged exhalation": 1,
        "active exhalation": 1,
        "accessory muscle use/retractions": 2,
        "accessory muscle use": 2,
        "nasal flaring": 2,
        "splinting": 2,
        "inability to speak in full sentences": 2,
        "restlessness": 2,
        "fearful facial expression": 2,
        "gasping efforts": 3,
        "irregular": 3,
        "discoordinate": 3,
        "frequent desaturation episodes": 3,
        "cheyne-stokes": 3,
        "agonal": 3,
        "kussmaul": 3,
    },
    223990: {  # Respiratory Effort
        "normal": 0,
        "shallow": 1,
        "splinting": 1,
        "labored": 2,
        "dyspneic": 2,
        "apneic": 3,
        "agonal": 3,
    },
}


def convert_categorical_values(df: pd.DataFrame) -> pd.DataFrame:
    """Apply categorical-to-numerical conversions for supported itemids.

    For each row with an itemid in CATEGORICAL_MAPPINGS and a non-null value_text,
    attempts to map the text to a numerical code and stores it in value_num.
    Case-insensitive matching with fallback to original value_num.

    Args:
        df: DataFrame with columns 'itemid', 'value_text', 'value_num'.

    Returns:
        DataFrame with value_num updated for categorical items.
    """
    out = df.copy()

    for itemid, mapping in CATEGORICAL_MAPPINGS.items():
        mask = out["itemid"] == itemid
        if not mask.any():
            continue

        subset = out[mask]
        converted_values = []

        for _, row in subset.iterrows():
            value_text = row.get("value_text")
            if pd.isna(value_text) or value_text is None:
                # No text value, keep existing value_num
                converted_values.append(row.get("value_num"))
                continue

            # Normalize: strip and lowercase
            normalized = str(value_text).strip().lower()

            # Direct lookup
            if normalized in mapping:
                converted_values.append(float(mapping[normalized]))
                continue

            # Fallback: keep original numeric value if it exists
            orig_num = row.get("value_num")
            if pd.notna(orig_num):
                converted_values.append(orig_num)
            else:
                # No match, no fallback: store NaN
                converted_values.append(pd.NA)

        out.loc[mask, "value_num"] = converted_values

    return out
