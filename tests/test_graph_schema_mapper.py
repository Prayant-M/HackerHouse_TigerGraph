"""Foreign graph schemas (schemas/*.gsql): parse, validate and map onto the
canonical fraud model, scored against each file's own ground truth."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ingest"))
import graph_schema_mapper as gsm  # noqa: E402

FILES = sorted((ROOT / "schemas").glob("*.gsql"))


@pytest.mark.parametrize("path", FILES, ids=[p.stem for p in FILES])
def test_schema_valid_and_mapped(path):
    r = gsm.run(path)
    assert r["validation"]["ok"], r["validation"]["problems"]
    sc = r["score"]
    assert sc["n"] >= 20 and not sc["not_attempted"]
    assert sc["correct"] == sc["n"], [x for x in sc["rows"] if not x["ok"]]


def test_reserved_word_is_a_problem(tmp_path):
    src = (ROOT / "schemas" / "bank3_core_banking_t24.gsql").read_text(encoding="utf-8")
    bad = tmp_path / "t24_reserved.gsql"
    bad.write_text(src.replace(" TARGET_MARKET INT,", " TARGET INT,"), encoding="utf-8")
    v = gsm.validate(gsm.parse(bad))
    assert not v["ok"] and any("TARGET" in p for p in v["problems"])


def test_traps_avoided():
    iso = gsm.run(ROOT / "schemas" / "bank1_iso20022_payments.gsql")
    assert iso["concepts"]["Transaction"]["targets"] == ["CdtTrfTxInf"]  # not PmtInf / TxInf
    assert "Ultmt" not in " ".join(iso["edges"]["PAYS"]["path"])
    bian = gsm.run(ROOT / "schemas" / "bank2_bian_service_domains.gsql")
    assert bian["concepts"]["Device"]["targets"] == ["AccessDevice"]  # not the issued card
    assert "FraudDiagnosisAssessment" not in bian["concepts"]["InvestigationCase"]["targets"]
    t24 = gsm.run(ROOT / "schemas" / "bank3_core_banking_t24.gsql")
    assert "STMT_ENTRY" not in t24["concepts"]["Transaction"]["targets"]
    assert t24["concepts"]["Device"]["kind"].startswith("attribute")
