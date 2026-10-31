"""Public live deployment: live runs are token-gated, and the live bundle
ships no credentials and none of the bulk staged data."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "deploy"))


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient

    import server

    monkeypatch.setattr(server, "RUN_AUTH", True)
    monkeypatch.setenv("APPROVAL_TOKENS",
                       "tester:analyst:" + hashlib.sha256(b"testtok").hexdigest())
    return TestClient(server.app)


def test_live_run_needs_a_token(client):
    assert client.get("/api/investigate/HHF-001").status_code == 401
    assert client.get("/api/investigate/HHF-001?token=wrong").status_code == 401
    assert client.post("/api/replay/HHF-001/rerun/0").status_code == 401


def test_a_known_token_passes_the_gate(client):
    import server

    server._require_runner(None, "testtok")
    server._require_runner("Bearer testtok", None)


def test_live_bundle_ships_no_secrets_or_bulk_data(tmp_path):
    import build_space

    if not (ROOT / "data" / "staged" / "behaviour_emb.parquet").exists():
        pytest.skip("staged data not built")
    out = tmp_path / "live"
    build_space.build_live(out)
    names = {p.name for p in out.rglob("*")}
    assert ".env" not in names and "approval_signing_key" not in names
    assert "transactions.parquet" not in names
    assert sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) < 50e6
    assert "CONSOLE_RUN_AUTH=1" in (out / "Dockerfile").read_text(encoding="utf-8")
