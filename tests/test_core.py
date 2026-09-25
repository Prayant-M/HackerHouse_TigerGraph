"""Tests for the deterministic core.

These are the parts that have to be defensible to a regulator, so they are the
parts with tests: the approval routing, the policy rules, the stopping
arithmetic, the audit chain, and the boundary that keeps a language model out
of all of it.

    python -m pytest tests -q
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fraudagent.core import hypotheses as H  # noqa: E402
from fraudagent.core import policy_engine, stopping, voi  # noqa: E402
from fraudagent.core.evidence_ledger import (CONFIDENCE_CEILING, EvidenceLedger,  # noqa: E402
                                             apply_lr, trigger_prior)
from fraudagent.core.ledger import DecisionLedger  # noqa: E402
from fraudagent.core.permissions import (AUTO, L1, L2, PolicyViolation,  # noqa: E402
                                         may_execute, route_for)
from fraudagent.graphstore.matchers import (detect_card_testing,  # noqa: E402
                                            detect_threshold_structuring)


# ─────────────────────────────────────────────────────── the LLM boundary ──
def test_core_cannot_import_an_llm():
    """`core/` holds every decision that has to be defensible. If it could call
    a model, "the decision layer cannot hallucinate" would be a slogan rather
    than a property. This test is the enforcement."""
    banned = {"anthropic", "openai", "google", "langchain", "langgraph",
              "transformers", "litellm"}
    offenders = []
    for path in (ROOT / "src" / "fraudagent" / "core").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for n in names:
                root = n.split(".")[0]
                if root in banned or "llm" in n.lower():
                    offenders.append(f"{path.name}: {n}")
    assert not offenders, f"core/ must stay LLM-free: {offenders}"


# ───────────────────────────────────────────────────────────── permissions ──
@pytest.mark.parametrize("action,exposure,expected", [
    ("MONITOR_CARD", 0, AUTO),
    ("VERIFY_WITH_CUSTOMER", 0, AUTO),
    ("CREATE_CASE", 0, AUTO),
    ("DECLINE_TRANSACTION", 0, L1),
    ("BLOCK_CARD", 100.0, L1),
    ("BLOCK_CARD", 2500.0, L1),          # boundary: "≤ $2,500" is L1
    ("BLOCK_CARD", 2500.01, L2),
    ("BLOCK_ALL_CARDS", 0, L2),
    ("FILE_REPORT", 0, L2),
])
def test_approval_routes_match_the_policy(action, exposure, expected):
    assert route_for(action, exposure) == expected


def test_agent_may_not_execute_a_block():
    assert not may_execute("BLOCK_CARD")
    assert not may_execute("FILE_REPORT")
    assert may_execute("VERIFY_WITH_CUSTOMER")


def test_unknown_action_is_rejected():
    with pytest.raises(PolicyViolation):
        route_for("REFUND_EVERYTHING")


def test_simulated_service_refuses_to_execute_a_recommend_only_action():
    from fraudagent.mcp_servers.simulated_actions import execute

    with pytest.raises(PermissionError):
        execute("BLOCK_CARD", "T-1", "C00001-K1", "C00001")


# ────────────────────────────────────────────────────────────────── policy ──
def _state(**kw):
    base = dict(case_id="T-1", trigger_type="risk_score", fraud_probability=0.5,
                verdict="uncertain", pattern=H.CNP, exposure_usd=100.0,
                n_independent_evidence=2, single_signal_only=False)
    base.update(kw)
    return policy_engine.CaseState(**base)


def test_r1_blocks_the_block_on_a_single_weak_signal():
    d = policy_engine.evaluate(_state(fraud_probability=0.55, single_signal_only=True,
                                      verdict="uncertain"))
    assert "BLOCK_CARD" not in d.action_names()
    assert "VERIFY_WITH_CUSTOMER" in d.action_names()
    assert "R1" in d.cited_rules


def test_r2_blocks_when_the_customer_denies():
    d = policy_engine.evaluate(_state(customer_response="denied", fraud_probability=0.86,
                                      verdict="fraud"))
    assert "BLOCK_CARD" in d.action_names()
    assert "CREATE_CASE" in d.action_names()


def test_r3_closes_when_the_customer_confirms():
    d = policy_engine.evaluate(_state(customer_response="confirmed"))
    assert d.action_names() == ["CLOSE_NO_FRAUD"]


def test_r7_never_blocks_a_recurring_charge_dispute():
    d = policy_engine.evaluate(_state(trigger_type="customer_report",
                                      recurring_charge_match=True,
                                      fraud_probability=0.6))
    assert "BLOCK_CARD" not in d.action_names()
    assert "BLOCK_CARD" in d.forbidden
    assert {"CREATE_CASE", "VERIFY_WITH_CUSTOMER", "WARN_CUSTOMER"} <= set(d.action_names())


def test_r10_forbids_blocking_every_card_without_two_confirmations():
    d = policy_engine.evaluate(_state(verdict="fraud", fraud_probability=0.95))
    assert "BLOCK_ALL_CARDS" not in d.action_names()
    d2 = policy_engine.evaluate(_state(verdict="fraud", fraud_probability=0.95,
                                       cards_with_confirmed_fraud=2))
    assert "BLOCK_ALL_CARDS" in d2.action_names()


def test_sar_needs_both_suspicion_and_an_aggravating_condition():
    # strongly suspected but small, isolated and a documented pattern → no filing
    file_it, why = policy_engine.sar_required(
        _state(verdict="fraud", fraud_probability=0.9, exposure_usd=250.0))
    assert not file_it and "Case only" in why
    # over the $1,000 threshold → filing
    file_it, _ = policy_engine.sar_required(
        _state(verdict="fraud", fraud_probability=0.9, exposure_usd=1500.0))
    assert file_it
    # connected to another card's compromise → filing even when small
    file_it, _ = policy_engine.sar_required(
        _state(verdict="fraud", fraud_probability=0.9, exposure_usd=80.0,
               connected_card_ids=["C00001-K1"], shares_origin_with_other_fraud=True))
    assert file_it
    # not suspected → no filing whatever the amount
    file_it, _ = policy_engine.sar_required(
        _state(verdict="legitimate", fraud_probability=0.05, exposure_usd=90_000.0))
    assert not file_it


def test_the_llm_cannot_add_an_action():
    d = policy_engine.evaluate(_state(verdict="legitimate", fraud_probability=0.05))
    assert d.filter(["CLOSE_NO_FRAUD", "BLOCK_ALL_CARDS", "WIRE_MONEY"]) == ["CLOSE_NO_FRAUD"]


# ──────────────────────────────────────────────────────────────── stopping ──
def test_stops_when_decisive_on_two_pieces_of_evidence():
    post = {H.NONE: 0.05, H.CNP: 0.80, H.ATO: 0.05, H.CNP_NEW_DEVICE: 0.04,
            H.OUT_OF_REGION: 0.03, H.CARD_TESTING: 0.02, H.UNDOCUMENTED: 0.01}
    d = stopping.evaluate(post, n_independent_evidence=3, round_no=0,
                          best_voi_ratio=0.9, elapsed_s=1.0)
    assert d.stop and d.reason_code == stopping.DECISIVE


def test_stops_when_nothing_is_worth_asking():
    post = {H.NONE: 0.45, H.CNP: 0.25, H.ATO: 0.10, H.CNP_NEW_DEVICE: 0.10,
            H.OUT_OF_REGION: 0.05, H.CARD_TESTING: 0.03, H.UNDOCUMENTED: 0.02}
    d = stopping.evaluate(post, n_independent_evidence=2, round_no=0,
                          best_voi_ratio=0.0, elapsed_s=1.0)
    assert d.stop and d.reason_code == stopping.EXHAUSTED
    assert "friction" in d.reason


def test_keeps_going_while_the_case_is_open_and_evidence_is_available():
    post = {H.NONE: 0.40, H.CNP: 0.30, H.ATO: 0.12, H.CNP_NEW_DEVICE: 0.10,
            H.OUT_OF_REGION: 0.05, H.CARD_TESTING: 0.02, H.UNDOCUMENTED: 0.01}
    d = stopping.evaluate(post, n_independent_evidence=2, round_no=0,
                          best_voi_ratio=5.0, elapsed_s=1.0)
    assert not d.stop


def test_round_cap_is_enforced_in_code():
    post = {H.NONE: 0.40, H.CNP: 0.30, H.ATO: 0.12, H.CNP_NEW_DEVICE: 0.10,
            H.OUT_OF_REGION: 0.05, H.CARD_TESTING: 0.02, H.UNDOCUMENTED: 0.01}
    d = stopping.evaluate(post, 2, round_no=3, best_voi_ratio=5.0, elapsed_s=1.0)
    assert d.stop and d.reason_code == stopping.ROUND_CAP


# ───────────────────────────────────────────────────────────────────── VoI ──
def test_information_gain_is_never_negative():
    post = trigger_prior("risk_score")
    for a in voi.CATALOGUE:
        assert voi.expected_info_gain(post, a) >= -1e-9


def test_policy_can_forbid_asking_not_only_acting():
    post = trigger_prior("risk_score")

    def permits(action):
        return (False, "contact-fatigue limit") if action.key == "customer_validation" \
            else (True, "")

    best, ranking = voi.select(post, permits)
    assert best is None or best.action.key != "customer_validation"
    blocked = [r for r in ranking if not r.permitted]
    assert blocked and blocked[0].blocked_by


def test_a_settled_question_yields_less_information():
    undecided = {H.NONE: 0.5, H.CNP: 0.2, H.ATO: 0.1, H.CNP_NEW_DEVICE: 0.1,
                 H.OUT_OF_REGION: 0.05, H.CARD_TESTING: 0.03, H.UNDOCUMENTED: 0.02}
    decided = {H.NONE: 0.02, H.CNP: 0.90, H.ATO: 0.03, H.CNP_NEW_DEVICE: 0.02,
               H.OUT_OF_REGION: 0.01, H.CARD_TESTING: 0.01, H.UNDOCUMENTED: 0.01}
    a = next(x for x in voi.CATALOGUE if x.key == "customer_validation")
    assert voi.expected_info_gain(undecided, a) > voi.expected_info_gain(decided, a)


# ───────────────────────────────────────────────────────────────── ledger ──
def test_evidence_moves_belief_in_the_right_direction():
    led = EvidenceLedger(trigger_prior("risk_score"))
    before = led.fraud_probability
    led.add_solicited("customer_denied", "denied", "test")
    assert led.fraud_probability > before
    led2 = EvidenceLedger(trigger_prior("risk_score"))
    led2.add_solicited("customer_confirmed", "confirmed", "test")
    assert led2.fraud_probability < before


def test_reliability_damps_an_update():
    post = trigger_prior("risk_score")
    lrs = {H.NONE: 0.1, H.CNP: 5.0, H.ATO: 1.0, H.CNP_NEW_DEVICE: 1.0,
           H.OUT_OF_REGION: 1.0, H.CARD_TESTING: 1.0, H.UNDOCUMENTED: 1.0}
    full = H.fraud_probability(apply_lr(post, lrs, 1.0))
    half = H.fraud_probability(apply_lr(post, lrs, 0.5))
    assert H.fraud_probability(post) < half < full


def test_reported_probability_is_capped():
    led = EvidenceLedger(trigger_prior("customer_report"))
    for _ in range(12):
        led.add_solicited("customer_denied", "denied", "test")
    assert led.fraud_probability <= CONFIDENCE_CEILING + 1e-9
    assert abs(sum(led.reported().values()) - 1.0) < 1e-6


def test_posterior_always_sums_to_one():
    led = EvidenceLedger(trigger_prior("analyst_request"))
    led.add_solicited("step_up_failed", "failed", "test")
    led.add_solicited("analyst_confirms_ring", "ring", "test")
    assert abs(sum(led.posterior.values()) - 1.0) < 1e-9


def test_contradictions_are_recorded_not_averaged_away():
    led = EvidenceLedger(trigger_prior("risk_score"))
    led.add_solicited("customer_denied", "denied", "r1")
    led.add_solicited("step_up_passed", "passed", "r2")
    assert led.contradictions()


# ────────────────────────────────────────────────────────────── audit log ──
def test_decision_chain_verifies_and_detects_tampering():
    led = DecisionLedger("HHG-001")
    p = trigger_prior("risk_score")
    led.record("a", p, p, "first")
    led.record("b", p, p, "second")
    ok, msg = led.verify()
    assert ok, msg
    led.decisions[0].rationale = "quietly edited after the fact"
    ok, msg = led.verify()
    assert not ok and "tampered" in msg


# ──────────────────────────────────────────────────────────────── matchers ──
def _rows(spec):
    from datetime import datetime, timedelta
    t0 = datetime(2016, 11, 14, 9, 0, 0)
    return [{"txn_id": f"T{i}", "ts": t0 + timedelta(minutes=m), "amount": a}
            for i, (m, a) in enumerate(spec)]


def test_card_testing_matcher():
    hit = detect_card_testing(_rows([(0, 1.10), (12, 2.40), (28, 0.95), (91, 259.98)]))
    assert hit["matched"] and hit["n_small"] == 3
    assert hit["follow_amount"] == 259.98
    assert not detect_card_testing(_rows([(0, 1.10), (12, 2.40)]))["matched"]


def test_threshold_structuring_matcher_finds_the_undocumented_typology():
    hit = detect_threshold_structuring(
        _rows([(0, 478.95), (10, 456.96), (24, 488.04), (30, 482.12)]))
    assert hit["matched"]
    assert hit["threshold_usd"] == 500.0
    assert hit["n_txns"] == 4
    assert abs(hit["total_usd"] - 1906.07) < 0.01


def test_structuring_matcher_does_not_fire_on_ordinary_spending():
    assert not detect_threshold_structuring(
        _rows([(0, 12.00), (20, 480.00), (40, 33.50)]))["matched"]


# ──────────────────────────────────────── R7 cadence, R3 case, grounding ──
def _charges(days):
    from datetime import datetime, timedelta
    t0 = datetime(2016, 7, 1)
    return [{"ts": t0 + timedelta(days=d), "txn_id": str(3000000 + i)} for i, d in enumerate(days)]


def test_r7_recognises_a_regular_repeat_charge_not_only_a_monthly_one():
    from fraudagent.graphstore.matchers import recurrence_from_rows
    # HHG-018's shape: the same charge every one to three weeks for months
    r = recurrence_from_rows(_charges([0, 6, 25, 33, 50, 53, 63, 77, 95, 116, 136, 150]))
    assert r["recurring"] and r["cadence"] == "regular"
    assert recurrence_from_rows(_charges([0, 30, 61]))["cadence"] == "monthly"


def test_r7_does_not_call_two_coincidences_a_habit():
    from fraudagent.graphstore.matchers import recurrence_from_rows
    assert not recurrence_from_rows(_charges([0, 3]))["recurring"]
    assert not recurrence_from_rows(_charges([0, 5, 90, 95, 180]))["recurring"]   # 85-day gap
    # a fraud burst repeats an amount too: 21 charges, 2-3 days apart, 60 days
    assert not recurrence_from_rows(_charges(list(range(0, 63, 3))))["recurring"]


def test_r7_hands_over_to_r3_once_the_cardholder_recognises_the_charge():
    d = policy_engine.evaluate(_state(trigger_type="customer_report", recurring_charge_match=True,
                                      customer_response="confirmed", evidence_requested=True))
    names = d.action_names()
    assert "BLOCK_CARD" not in names and "VERIFY_WITH_CUSTOMER" not in names
    assert names[-1] == "CLOSE_NO_FRAUD" and {"CREATE_CASE", "WARN_CUSTOMER"} <= set(names)


def test_a_case_is_opened_whenever_evidence_was_requested():
    d = policy_engine.evaluate(_state(customer_response="confirmed", evidence_requested=True))
    assert d.action_names() == ["CREATE_CASE", "CLOSE_NO_FRAUD"]


def test_closing_without_asking_cites_the_stopping_rule_not_r3():
    d = policy_engine.evaluate(_state(verdict="legitimate", fraud_probability=0.05))
    close = next(a for a in d.actions if a.action == "CLOSE_NO_FRAUD")
    assert close.reason.startswith("§6") and "R3" not in close.reason


def test_llm_prose_citing_an_id_the_evidence_lacks_is_rejected():
    from fraudagent.report.narrative import grounded
    brief = "card C13487-K1 · device ring · CC-2649 · txn 3478561"
    assert grounded("Card C13487-K1 shares a device with CC-2649.", brief)
    assert grounded("Matches CC-9999 on card C13487-K1.", brief) == ""
    assert grounded("", brief) == ""
