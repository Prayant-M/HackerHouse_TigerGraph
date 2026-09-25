"""Differential tests between the two graph backends.

Two implementations of one contract only stay honest if something checks them
against each other. These tests run the same primitive against the local mirror
and against TigerGraph and assert the answers agree.

They **skip** when `TG_HOST` is not configured, so a fresh clone does not fail
on infrastructure it does not have. Running them is the first thing to do once
a workspace exists — that is where an accumulated divergence between the GSQL
and the mirror would show up, and nothing else in the suite can catch it.

    TG_HOST=... TG_PASSWORD=... python -m pytest tests/test_backend_parity.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fraudagent.config import PATHS, TG  # noqa: E402

pytestmark = pytest.mark.skipif(
    not TG.configured,
    reason="no TigerGraph workspace configured; set TG_HOST and TG_PASSWORD in .env")


@pytest.fixture(scope="module")
def stores():
    from fraudagent.graphstore.local import LocalGraphStore
    from fraudagent.graphstore.tigergraph import TigerGraphStore

    return LocalGraphStore(), TigerGraphStore()


@pytest.fixture(scope="module")
def sample_cases():
    pack = pd.read_csv(PATHS.case_pack_csv)
    pack["opened_at"] = pd.to_datetime(pack["opened_at"])
    return pack.to_dict("records")[:5]


def _close(a, b, tol=0.02):
    return abs(float(a or 0) - float(b or 0)) <= tol * max(1.0, abs(float(a or 0)))


def test_transaction_lookup_agrees(stores, sample_cases):
    local, tiger = stores
    for row in sample_cases:
        a = local.get_transaction(str(row["flagged_txn_id"]))
        b = tiger.get_transaction(str(row["flagged_txn_id"]))
        assert b is not None, row["case_id"]
        assert a.card_id == b.card_id
        assert a.channel == b.channel
        assert _close(a.amount, b.amount, 0.001)
        assert a.device_profile == b.device_profile


def test_card_baseline_agrees(stores, sample_cases):
    local, tiger = stores
    for row in sample_cases:
        as_of = row["opened_at"].to_pydatetime()
        a = local.card_baseline(row["card_id"], as_of)
        b = tiger.card_baseline(row["card_id"], as_of)
        assert a["n_txns"] == b["n_txns"], row["case_id"]
        assert _close(a["amt_median"], b["amt_median"])
        assert a["home_region"] == b["home_region"]


def test_device_fanout_agrees(stores, sample_cases):
    local, tiger = stores
    for row in sample_cases:
        as_of = row["opened_at"].to_pydatetime()
        txn = local.get_transaction(str(row["flagged_txn_id"]))
        if not txn.device_profile:
            continue
        a = local.device_fanout(txn.device_profile, as_of)
        b = tiger.device_fanout(txn.device_profile, as_of)
        assert a["n_cards"] == b["n_cards"], txn.device_profile
        assert a["n_cards_anon_proxy"] == b["n_cards_anon_proxy"]
        assert set(a["card_ids"]) == set(b["card_ids"])


def test_typology_probes_agree(stores, sample_cases):
    """Both backends run the *same* window matcher over rows the graph selected,
    so a disagreement here means the retrieval differs, not the logic."""
    local, tiger = stores
    for row in sample_cases:
        as_of = row["opened_at"].to_pydatetime()
        a = local.threshold_structuring_probe(row["card_id"], as_of)
        b = tiger.threshold_structuring_probe(row["card_id"], as_of)
        assert a.get("matched") == b.get("matched"), row["case_id"]
        if a.get("matched"):
            assert set(a["txn_ids"]) == set(b["txn_ids"])
            assert _close(a["total_usd"], b["total_usd"], 0.001)


def test_hybrid_case_recall_overlaps(stores, sample_cases):
    """Vector search is approximate (HNSW), so exact rank equality is the wrong
    assertion. The top-5 sets should still overlap substantially."""
    local, tiger = stores
    for row in sample_cases:
        as_of = row["opened_at"].to_pydatetime()
        query = "online purchase inconsistent with the cardholder's usual amounts"
        ents = [str(row["flagged_txn_id"]), row["card_id"], row["customer_id"]]
        a = {c.case_id for c in local.hybrid_case_recall(query, ents, as_of, k=5)}
        b = {c.case_id for c in tiger.hybrid_case_recall(query, ents, as_of, k=5)}
        if not a and not b:
            continue
        assert a & b, f"{row['case_id']}: local={a} tigergraph={b}"


def test_full_investigation_reaches_the_same_verdict(stores, sample_cases):
    """The end-to-end check. Probabilities may differ slightly because vector
    recall is approximate; the verdict and the pattern must not."""
    from fraudagent.agent.graph import Investigator, trigger_from_row
    from fraudagent.agent.llm import get_llm

    local, tiger = stores
    llm = get_llm()
    for row in sample_cases[:3]:
        a = Investigator(local, llm).run(trigger_from_row(row), row["case_id"])
        b = Investigator(tiger, llm).run(trigger_from_row(row), row["case_id"])
        assert a["case"]["verdict"] == b["case"]["verdict"], row["case_id"]
        assert a["case"]["pattern"] == b["case"]["pattern"], row["case_id"]
        assert abs(a["case"]["fraud_probability"]
                   - b["case"]["fraud_probability"]) < 0.10, row["case_id"]
