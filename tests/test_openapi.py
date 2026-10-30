"""docs/openapi.yaml is the published contract for ui/server.py, so a route or a
response shape that changes without it fails here. Only answer-file routes are
called: nothing below needs a graph, a token or a ledger."""

import sys
from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))

import server  # noqa: E402

SPEC = yaml.safe_load((ROOT / "docs" / "openapi.yaml").read_text(encoding="utf-8"))
GENERATED_ROUTES = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
client = TestClient(server.app)


def validator(schema):
    return jsonschema.Draft202012Validator({**schema, "components": SPEC["components"]})


def response_schema(path, method="get"):
    return SPEC["paths"][path][method]["responses"]["200"]["content"]["application/json"]["schema"]


def test_every_route_is_documented_and_nothing_else():
    served = {(r.path, m.lower()) for r in server.app.routes
              if hasattr(r, "methods") and r.path not in GENERATED_ROUTES
              for m in r.methods if m != "HEAD"}
    documented = {(p, m) for p, ops in SPEC["paths"].items() for m in ops}
    assert served == documented


def test_console_serves_this_spec():
    assert client.get("/openapi.json").json()["info"]["title"] == SPEC["info"]["title"]
    assert client.get("/docs").status_code == 200


@pytest.mark.parametrize("url, path", [
    ("/api/cases", "/api/cases"),
    ("/api/cases/HHF-016", "/api/cases/{case_id}"),
    ("/api/cases/HHG-014", "/api/cases/{case_id}"),
    ("/api/graph/HHG-014", "/api/graph/{case_id}"),
    ("/api/proof/HHF-016", "/api/proof/{case_id}"),
    ("/api/replay/HHF-016", "/api/replay/{case_id}"),
    ("/api/policy", "/api/policy"),
    ("/api/autonomous", "/api/autonomous"),
    ("/api/autonomous/AUTO-001", "/api/autonomous/{case_id}"),
])
def test_response_matches_the_spec(url, path):
    res = client.get(url)
    assert res.status_code == 200
    errors = list(validator(response_schema(path)).iter_errors(res.json()))
    assert not errors, [e.message[:200] for e in errors[:3]]


def test_schema_rejects_a_verdict_the_spec_does_not_allow():
    answer = client.get("/api/cases/HHF-016").json()
    answer["case"]["verdict"] = "probably_fine"
    assert list(validator(response_schema("/api/cases/{case_id}")).iter_errors(answer))
