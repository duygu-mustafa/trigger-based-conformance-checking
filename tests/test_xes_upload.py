"""Sanity check for the independent XES upload + conformance flow (api.py).

Plain-assert, no pytest dependency. Run directly:
    python tests/test_xes_upload.py
"""

import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient

import api

SAMPLE_XES = """<?xml version="1.0" encoding="UTF-8"?>
<log xes.version="1.0" xmlns="http://www.xes-standard.org/">
  <trace>
    <string key="concept:name" value="c1"/>
    <event><string key="concept:name" value="A"/><date key="time:timestamp" value="2020-01-01T10:00:00.000+00:00"/></event>
    <event><string key="concept:name" value="B"/><date key="time:timestamp" value="2020-01-01T11:00:00.000+00:00"/></event>
  </trace>
  <trace>
    <string key="concept:name" value="c2"/>
    <event><string key="concept:name" value="A"/><date key="time:timestamp" value="2020-01-02T10:00:00.000+00:00"/></event>
    <event><string key="concept:name" value="C"/><date key="time:timestamp" value="2020-01-02T11:00:00.000+00:00"/></event>
  </trace>
</log>
"""


def test_upload_and_run():
    client = TestClient(api.app)

    with tempfile.NamedTemporaryFile(suffix=".xes", mode="w", delete=False) as f:
        f.write(SAMPLE_XES)
        path = f.name

    with open(path, "rb") as f:
        r = client.post("/api/upload_log", files={"file": ("sample.xes", f, "application/xml")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["num_cases"] == 2
    assert body["num_events"] == 4
    assert body["activities"] == ["A", "B", "C"]
    upload_id = body["upload_id"]

    rules = [{"label": "A then B", "template": "RESPONSE", "activation": "A", "target": "B"}]
    r2 = client.post("/api/run_uploaded", json={"upload_id": upload_id, "custom_rules": rules})
    assert r2.status_code == 200, r2.text
    result = r2.json()
    assert result["num_cases"] == 2
    assert len(result["constraints"]) == 1
    c = result["constraints"][0]
    assert c["satisfied"] == 1
    assert c["violated"] == 1
    assert c["violating_case_ids"] == ["c2"]

    r3 = client.post("/api/run_uploaded", json={"upload_id": "does-not-exist", "custom_rules": rules})
    assert r3.status_code == 404

    r4 = client.post("/api/run_uploaded", json={"upload_id": upload_id, "custom_rules": []})
    assert r4.status_code == 400


def test_wide_log_data_condition():
    """A data condition on an uploaded wide log resolves against the event's own attributes."""
    import pandas as pd
    from conformance.checker import check_log_conformance
    from conformance.types import (
        DataCondition,
        DeclareConstraint,
        DeclareModel,
        DeclareTemplate,
    )

    # Wide log: no itemid/value_num columns, data lives in an `amount` attribute column.
    df = pd.DataFrame(
        [
            {"case_id": "c1", "activity": "A", "timestamp": pd.Timestamp("2020-01-01T10:00Z"), "amount": 150.0},
            {"case_id": "c1", "activity": "B", "timestamp": pd.Timestamp("2020-01-01T11:00Z"), "amount": None},
            {"case_id": "c2", "activity": "A", "timestamp": pd.Timestamp("2020-01-02T10:00Z"), "amount": 50.0},
            {"case_id": "c2", "activity": "B", "timestamp": pd.Timestamp("2020-01-02T11:00Z"), "amount": None},
        ]
    )

    model = DeclareModel(name="wide")
    c = DeclareConstraint(
        template=DeclareTemplate.RESPONSE,
        activation="A",
        target="B",
        activation_cond=DataCondition("items['amount'] > 100"),
    )
    c.id = "R1"
    model.add(c)

    results = check_log_conformance(df, model)
    by_case = {r.case_id: r.constraint_results[0] for r in results}
    # c1: A has amount=150 > 100 → activates, B follows → satisfied.
    # c2: A has amount=50, condition fails → not activated (vacuous), not violated.
    from conformance.results import ConformanceOutcome

    assert by_case["c1"].outcome == ConformanceOutcome.SATISFIED, by_case["c1"].outcome
    assert by_case["c2"].outcome != ConformanceOutcome.VIOLATED, by_case["c2"].outcome


if __name__ == "__main__":
    test_upload_and_run()
    test_wide_log_data_condition()
    print("OK: test_xes_upload")
