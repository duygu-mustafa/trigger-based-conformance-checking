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

    # Create a minimal activity frame with an SBT start and a re-vent start
    activity_rows = [
        {"case_id": "c1", "activity": "SBTStarted", "timestamp": pd.Timestamp(base)},
        {"case_id": "c1", "activity": "InvasiveVentilationStarted", "timestamp": pd.Timestamp(base + timedelta(hours=6))},
    ]
    df = pd.DataFrame(activity_rows)

    derived = _derive_activities(df)

    # Expect one derived frame containing a SBTFailed at revent timestamp
    assert isinstance(derived, list)
    combined = pd.concat(derived, ignore_index=True) if derived else pd.DataFrame()
    assert not combined.empty
    assert "SBTFailed" in combined["activity"].values
    # Verify the timestamp equals the re-vent time
    ts = combined.loc[combined["activity"] == "SBTFailed", "timestamp"].iloc[0]
    assert pd.Timestamp(base + timedelta(hours=6)) == pd.Timestamp(ts)
