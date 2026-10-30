"""The audit must cover both rounds, including a Round 1 answer with no case
pack on the machine, which used to crash the console's /api/audit."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "eval"))

from audit_answers import ANSWER_GLOBS, alert_for  # noqa: E402

RECORD = {"trigger": {"type": "risk_score", "opened_at": "2016-11-02 10:00:00",
                      "card_id": "C00001-K1", "flagged_txn_id": "1234567"}}


def test_audit_covers_every_answer_file():
    found = {p.name for g in ANSWER_GLOBS for p in (ROOT / "cases").glob(g)}
    assert found == {p.name for p in (ROOT / "cases").glob("HH*.json")}


def test_alert_comes_from_the_case_pack_when_it_has_the_case():
    row = {"opened_at": "2017-01-01 00:00:00"}
    assert alert_for("HHF-001", {"HHF-001": row}, RECORD) == (row, "case pack")


def test_alert_falls_back_to_the_saved_trigger():
    alert, source = alert_for("HHG-001", {}, RECORD)
    assert source == "answer file"
    assert alert["trigger_type"] == "risk_score"
    assert alert["card_id"] == "C00001-K1"
