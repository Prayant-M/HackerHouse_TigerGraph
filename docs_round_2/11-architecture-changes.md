# Architecture changes

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

The six layers stay. Nine additions sit on top of them, and the first three are foundations that everything else depends on.

| # | Addition | Where | What it does |
| --- | --- | --- | --- |
| 1 | **Attestation layer** | `core/attest.py`, `eval/attest_verify.py` | Every evidence item, finding, SAR sentence, containment number and challenge claim becomes an `Attestation{what, evidence_ids, query, params, ran_at, data_snapshot}`. `data_snapshot` is a hash of the loaded file set plus the graph load version. `make attest-verify` re-runs every query and fails on any mismatch |
| 2 | **Fail-closed run mode** | `graphstore/gateway`, `benchmark/run_case.py` | Submission mode never uses the local mirror. If the graph, the tool layer or the model's structured output fails, the run stops with `status: FAILED_DEPENDENCY`, no verdict and exit code 2. Answers are written to a temp file and renamed only on success, so a crash never leaves a half-written "saved" file. The MCP → direct-pyTigerGraph path is kept only for the same graph and is flagged as `transport_degraded` |
| 3 | **Server-side approvals** | `ui/server.py`, `core/permissions.py`, `auth/` | Bearer token → role lookup on the server (hashed tokens in env). The role in the request body is ignored. The proposer can't approve their own action. Approvals are append-only and enter the hash chain; there is no edit endpoint. Every 403 is logged |
| 4 | **Least-privilege graph access** | TG RBAC, `TG_ALLOWED_TOOLS` | The agent's TG user can only run installed queries. Writes go only through one installed `case_write` query. Remove `add_node` / `add_edge` from the agent's tool list. The LLM never sees a query tool |
| 5 | **Hostile-text firewall** | `core/text_facts.py`, `agent/llm.py` | trigger_text is data only. A deterministic extractor pulls the few facts policy needs (denies, recognises, analyst asks about X) from a fixed phrase list, and flags instruction-like spans as `hostile_text_detected`. The LLM sees free text only inside a delimited data block, and grounded() still filters its output. **Never invert what the text asks** |
| 6 | **Data-quality taint** | `core/quality.py`, new GSQL `data_gaps` | Per case, find missing identity, empty billing region, placeholder values and a card history that's too thin. A tainted case gets its confidence capped and routes to uncertain + ESCALATE_TO_ANALYST under R8 |
| 7 | **Proof object and predictive containment** | `core/proof.py`, `core/containment.py`, GSQL `precedent_by_facts`, `compromise_origin`, `ring_at_asof` | Innovations 1 and 2 (see `05-…` and `06-…`) |
| 8 | **Schema-drift gate** | `ingest/00_drift.py` | Diff columns, types, null rates, value domains and key overlaps between old and new files. Propose a mapping with sample records and wait for an approval token before loading. The approval is stored as a graph vertex |
| 9 | **Run telemetry and redaction** | `agent/telemetry.py` | Per case: wall time, tokens, model cost, MCP calls, retries. Secrets and raw personal fields are redacted from logs and traces. Every call that leaves the bank boundary is listed in an egress log |

Two calibration changes go with these:

- Re-measure the likelihood ratios with the Nov–Dec closed cases included. Keep the HHG-001…020 outcomes as a separate holdout and report your Round 1 accuracy on them honestly.
- For transactions after 2016-12-31, set the risk_score signal's LR to 1 and stop treating a risk-score trigger as near-certain legit. That prior was learned on a model that had seen the data; for January it hasn't.
