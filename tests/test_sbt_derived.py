import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Allow running this test file directly without setting PYTHONPATH.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from derive.activity_emitter import _derive_activities


def test_reventilation_emits_sbt_failed():
    base = datetime(2024, 1, 1, 8, 0, 0)

    # Minimal activity frame (canonical columns) with an SBT start and a re-vent start
    activity_rows = [
        {"case_id": "c1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base)},
        {"case_id": "c1", "activity": "InvasiveVentilationStarted", "timestamp": pd.Timestamp(base + timedelta(hours=6))},
    ]
    df = pd.DataFrame(activity_rows)
    for col in ["source_table", "itemid", "value_raw", "value_num", "unit", "attrs", "patient_id", "stay_id"]:
        df[col] = None

    derived = _derive_activities(df)

    # Expect a derived SBTFailed 1 s before the re-ventilation (so it stays in the SBT's episode)
    assert isinstance(derived, list)
    combined = pd.concat(derived, ignore_index=True) if derived else pd.DataFrame()
    assert not combined.empty
    assert "SBTFailed" in combined["activity"].values
    ts = combined.loc[combined["activity"] == "SBTFailed", "timestamp"].iloc[0]
    assert pd.Timestamp(base + timedelta(hours=6) - timedelta(seconds=1)) == pd.Timestamp(ts)
