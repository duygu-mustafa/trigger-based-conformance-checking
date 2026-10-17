"""Self-check for runtime_log: track_step appends a timed JSONL row."""
import json
import time
from pathlib import Path

from runtime_log import track_step


def test_track_step_appends_timed_row(tmp_path: Path):
    tmp_log = tmp_path / "rt.jsonl"
    with track_step("unit_test", "sleep_step", log_path=tmp_log, n=1):
        time.sleep(0.01)
    lines = tmp_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["script"] == "unit_test"
    assert rec["step"] == "sleep_step"
    assert rec["status"] == "completed"
    assert rec["n"] == 1
    assert rec["duration_seconds"] >= 0.01


if __name__ == "__main__":
    import tempfile
    test_track_step_appends_timed_row(Path(tempfile.mkdtemp()))
    print("OK")
