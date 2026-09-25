"""Tests for the answer-file schema validator, and for the committed answers.

The dataset is explicit that "missing fields score zero for that part" and
"made-up IDs score zero". So the validator is the thing standing between a
working agent and a silently zeroed submission, and it gets tested like it.

The last two tests run against `cases/` if it has been populated, and skip
otherwise — so a fresh clone does not fail on work it has not done yet.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fraudagent.report.answer import validate  # noqa: E402

GOOD = {
    "case_id": "HHG-001",
    "case": {
        "status": "closed_fraud", "verdict": "fraud", "fraud_probability": 0.86,
        "pattern": "card_testing", "pattern_description": "",
        "affected_txn_ids": ["3514030"], "first_suspicious_txn_id": "3514030",
        "connected_card_ids": [], "connected_device_profiles": [],
        "exposure_usd": 268.43,
        "evidence": [{"claim": "three small authorisations then a larger purchase",
                      "source": "graph", "ref": "query:card_testing_probe",
                      "entity_ids": ["3514030"]}],
        "similar_prior_cases": [], "summary": "A summary an analyst could read.",
        "written_to_graph": True, "graph_case_id": "CASE-HHG-001",
    },
    "evidence_requests": [],
    "next_best_actions": {
        "initial": [{"action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1"}],
        "final": [{"action": "BLOCK_CARD", "route": "L1", "reason": "R2"}],
        "what_changed": "nothing",
    },
    "sar": {"file": False, "reason": "§3a: exposure under $1,000", "narrative": "",
            "subjects": [], "total_amount_usd": 0, "activity_dates": []},
    "stop_reason": "Decisive posterior.",
    "tool_calls": 9, "tokens": 0, "latency_s": 1.2,
}


def test_a_well_formed_answer_passes():
    assert validate(copy.deepcopy(GOOD)) == []


def test_missing_required_field_is_caught():
    bad = copy.deepcopy(GOOD)
    del bad["case"]["exposure_usd"]
    assert any("missing case fields" in p for p in validate(bad))


def test_bad_enum_values_are_caught():
    for path, value, needle in [
        (("case", "status"), "in_progress", "bad status"),
        (("case", "verdict"), "probably", "bad verdict"),
        (("case", "pattern"), "money_laundering", "bad pattern"),
    ]:
        bad = copy.deepcopy(GOOD)
        bad[path[0]][path[1]] = value
        assert any(needle in p for p in validate(bad)), f"{path} {value}"


def test_probability_out_of_range_is_caught():
    bad = copy.deepcopy(GOOD)
    bad["case"]["fraud_probability"] = 1.4
    assert any("fraud_probability out of range" in p for p in validate(bad))


def test_undocumented_pattern_requires_a_description():
    bad = copy.deepcopy(GOOD)
    bad["case"]["pattern"] = "undocumented"
    assert any("pattern_description is empty" in p for p in validate(bad))
    bad["case"]["pattern_description"] = "Four purchases just under $500 in forty minutes."
    assert not any("pattern_description" in p for p in validate(bad))


def test_documented_pattern_must_not_carry_a_description():
    bad = copy.deepcopy(GOOD)
    bad["case"]["pattern_description"] = "some prose"
    assert any("must be empty" in p for p in validate(bad))


def test_legitimate_verdict_must_be_empty_and_free():
    bad = copy.deepcopy(GOOD)
    bad["case"]["verdict"] = "legitimate"
    problems = validate(bad)
    assert any("no affected_txn_ids" in p for p in problems)
    assert any("zero exposure" in p for p in problems)


def test_sar_flag_must_agree_with_the_final_actions():
    bad = copy.deepcopy(GOOD)
    bad["sar"]["file"] = True
    bad["sar"]["narrative"] = "word " * 80
    bad["sar"]["total_amount_usd"] = 268.43
    bad["sar"]["activity_dates"] = ["2016-11-14", "2016-11-14"]
    assert any("disagrees" in p for p in validate(bad))

    bad["next_best_actions"]["final"].append(
        {"action": "FILE_REPORT", "route": "L2", "reason": "§3a"})
    assert not any("disagrees" in p for p in validate(bad))


def test_a_filed_sar_needs_a_narrative_that_stands_alone():
    bad = copy.deepcopy(GOOD)
    bad["sar"].update({"file": True, "narrative": "Fraud happened.",
                       "total_amount_usd": 268.43,
                       "activity_dates": ["2016-11-14", "2016-11-14"]})
    bad["next_best_actions"]["final"].append(
        {"action": "FILE_REPORT", "route": "L2", "reason": "§3a"})
    assert any("too short" in p for p in validate(bad))


def test_invented_identifiers_are_caught():
    bad = copy.deepcopy(GOOD)
    bad["case"]["affected_txn_ids"] = ["9999999"]
    bad["case"]["connected_card_ids"] = ["C99999-K9"]
    bad["case"]["similar_prior_cases"] = ["CC-9999"]
    problems = validate(bad, known_txn_ids={"3514030"}, known_card_ids={"C12382-K1"},
                       known_case_ids={"CC-0001"})
    assert any("affected_txn_id 9999999" in p for p in problems)
    assert any("connected_card_id C99999-K9" in p for p in problems)
    assert any("similar_prior_case CC-9999" in p for p in problems)


def test_exposure_and_sar_total_must_match():
    bad = copy.deepcopy(GOOD)
    bad["sar"].update({"file": True, "narrative": "word " * 80,
                       "total_amount_usd": 999.99,
                       "activity_dates": ["2016-11-14", "2016-11-14"]})
    bad["next_best_actions"]["final"].append(
        {"action": "FILE_REPORT", "route": "L2", "reason": "§3a"})
    assert any("does not match case.exposure_usd" in p for p in validate(bad))


def test_an_action_without_a_reason_is_caught():
    bad = copy.deepcopy(GOOD)
    bad["next_best_actions"]["final"] = [{"action": "BLOCK_CARD", "route": "L1"}]
    assert any("has no reason" in p for p in validate(bad))


# ────────────────────────────────── the committed submission, if it exists ──
CASES = ROOT / "cases"
FILES = sorted(CASES.glob("HHG-*.json"))


@pytest.mark.skipif(not FILES, reason="run benchmark/run_20.py first")
def test_all_twenty_answer_files_exist_and_are_named_correctly():
    expected = {f"HHG-{i:03d}.json" for i in range(1, 21)}
    assert {p.name for p in FILES} == expected


@pytest.mark.skipif(not FILES, reason="run benchmark/run_20.py first")
def test_every_committed_answer_validates():
    problems = {}
    for path in FILES:
        answer = json.loads(path.read_text(encoding="utf-8"))
        found = validate(answer)
        if found:
            problems[path.name] = found
    assert not problems, json.dumps(problems, indent=2)


@pytest.mark.skipif(not FILES, reason="run benchmark/run_20.py first")
def test_every_case_was_written_to_the_graph():
    for path in FILES:
        answer = json.loads(path.read_text(encoding="utf-8"))
        assert answer["case"]["written_to_graph"] is True, path.name
        assert answer["case"]["graph_case_id"], path.name


@pytest.mark.skipif(not FILES, reason="run benchmark/run_20.py first")
def test_the_agent_does_not_block_everything():
    """The dataset warns that about half the cases are legitimate and that an
    agent which blocks everything scores badly. This is that guard rail."""
    verdicts = [json.loads(p.read_text(encoding="utf-8"))["case"]["verdict"] for p in FILES]
    assert verdicts.count("fraud") <= 15, f"too many fraud verdicts: {verdicts}"
    assert verdicts.count("fraud") >= 4, f"too few fraud verdicts: {verdicts}"
