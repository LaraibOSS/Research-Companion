"""Tests for rebuttal data models and segment JSON round-trip."""
from __future__ import annotations

import json

from papergraph.rebuttal.models import (
    Concern, Passage, RebuttalReport, ResponseDraft,
    concerns_from_json, concerns_to_json,
)


def test_concern_json_roundtrip():
    cs = [Concern(concern_id="R1.1", reviewer="R1", text="Missing baseline."),
          Concern(concern_id="R2.1", reviewer="R2", text="Unclear notation.", kind="clarification")]
    blob = concerns_to_json(cs)
    back = concerns_from_json(blob)
    assert back == cs
    assert json.loads(blob)[0]["concern_id"] == "R1.1"


def test_report_to_dict_json_safe():
    draft = ResponseDraft(
        concern_id="R1.1", reply="We thank R1...",
        cited_passages=[Passage(location="para 3", text="we compare against X", score=0.8)],
        verified=True, unverified_spans=[], planned_revision="add baseline Y",
    )
    report = RebuttalReport(drafts=[draft], changelog=["add baseline Y"], groups=[["R1.1"]])
    d = report.to_dict()
    json.dumps(d)
    assert d["drafts"][0]["cited_passages"][0]["location"] == "para 3"
