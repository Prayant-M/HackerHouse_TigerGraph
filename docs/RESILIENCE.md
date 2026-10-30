# Resilience statement

*One page. What the agent depends on, what leaves the bank's boundary, what happens when each dependency fails, and what is logged. Every behaviour below has a drill in `drills/run_drills.py` (results: `eval/reports/drills.md`).*

## Dependencies

| Dependency | Version | Role | On the decision path? |
|---|---|---|---|
| TigerGraph Savanna (`tgcloud.io`), graph `FraudGraph` | 4.2.5 | graph + vector store, every investigation query, the case write-back | **yes** — source of truth |
| `tigergraph-mcp` (stdio subprocess) | 1.0.3 | transport for the agent's graph calls | no (transport only) |
| LLM provider: Google, model `gemini-3.6-flash` | — | tool-plan suggestion and prose (summary, SAR narrative, explanation) | **no** — `core/` cannot import it |
| Local embedding model `all-MiniLM-L6-v2` (384-d) | sentence-transformers 5.6 | narrative + policy vectors | no egress; computed locally |
| Python 3.10+ packages | `requirements.txt` | — | — |

## What leaves the bank boundary

| Destination | What it sees | What it never sees |
|---|---|---|
| **TigerGraph Savanna** (the bank's own workspace) | all graph data; every query with its parameters; the case write | — |
| **Google (LLM)** | the *evidence brief*: pseudonymous ids (C01234-K1, txn ids), aggregates, policy clause text, the decision already taken, and `trigger_text` inside a delimited untrusted-data block | raw transaction rows, V-columns, identity records, credentials, approval tokens; it is never asked for a probability, action, route or id |
| nothing else | — | no external lookups, no telemetry vendors |

Every LLM call and every case's graph usage is appended to `logs/egress.jsonl` with destination, purpose and bytes sent. The public read-only console bundle (`deploy/build_space.py`, Hugging Face Space) serves committed answer files only — pseudonymous ids, no raw rows, no credentials, no live graph — and is **declared here as egress**. It refuses live re-runs and approvals.

## What the agent does when a dependency fails

| Failure | Behaviour | Drill |
|---|---|---|
| Graph down / network drops mid-run | the failing tool call becomes `DependencyFailure(step, dependency)`; the run stops with **no verdict**, a **signed `FAILED_DEPENDENCY` record** naming the step and the last good call, **exit code 2**. The previous answer file is untouched (answers are written to a temp file and renamed only after validation). `GRAPH_STRICT=1` is the default: the local mirror is never served as graph data | `graph_down` |
| MCP server dies, graph up | per-call fallback to the direct pyTigerGraph connection to the *same graph*, marked `transport_degraded: true` in the answer and trace; `MCP_STRICT=1` stops instead (exit 2) | `mcp_down` |
| Model times out | hard wall-clock timeout, one retry with backoff, then template prose with `prose_source: template`; verdict, probability, actions and routes are byte-identical | `llm_timeout` |
| Model returns garbage / injected actions / invented ids | the planner's tool list is filtered to the toolkit, `PolicyDecision.filter` drops any action the policy did not authorise, `grounded()` drops sentences citing unknown ids, template fallback; logged | `llm_garbage` |
| Hostile text in `trigger_text` | deterministic extractor reads only allow-listed facts; instruction-like spans are flagged with offsets (`hostile_text_detected`), never obeyed and never inverted; the decision core cannot read free text | `hostile_input`, `eval/metamorphic.py` M2 |
| Invalid input (unknown case id, missing field, unknown txn, bad trigger type) | clear error naming the field, **exit code 3**, no answer file | `invalid_input` |
| Approval by the wrong role / body role claim / self-approval / replayed or duplicate approval | 401/403/409 from the server-side token → role lookup; the body role is ignored and recorded as ignored; every refusal enters the signed hash chain; there is no edit endpoint | `wrong_role` |
| Same case run twice | identical decision fields (verdict, p, actions, routes, exposure, first txn); the case write is an idempotent upsert of the same vertex ids; prose from the LLM cache | `twice` |
| A query leaks post-`as_of` data | future-dated `CANARY-*` transactions planted on the case card abort the run (`TemporalWallBreach`) | `canary` |
| Ambiguous case that could loop | round cap, wall-clock budget and token budget enforced in code, recorded in `stop_reason` | `bounded` |

## What is logged

* **Every tool call**: method, parameters, latency, SHA-256 of the response, the response itself by content hash (`.cache/recordings/<case>/`). `make replay` reproduces a decision offline; `make diff` says whether a rerun changed because the data or the code changed.
* **Every decision**: the hash-chained decision ledger in each answer (`agent_record.decisions`, verified on write), written to the graph as `Decision` vertices.
* **Every approval or refusal**: `data/approvals/ledger.jsonl`, Ed25519-signed and hash-chained, mirrored to the graph as `ApprovalRecord` via the console-only `governance_write` query. `GET /api/approvals/verify` checks chain and signatures.
* **Every claim**: an attestation (what, ids, query + params, recorded calls with digests, time, data snapshot); `make attest-verify` re-runs them.
* **Egress**: `logs/egress.jsonl`. **Runs**: `logs/run.jsonl`.
* **Redaction**: all log lines pass `agent/telemetry.redact()` — values of any secret in the environment (keys, passwords, tokens, signing key) and email/phone patterns are removed. No credential is committed (`.env` is git-ignored; approval tokens are stored only as SHA-256 hashes).

## Least privilege

The agent's graph role (`agent_role`, `graph/rbac.gsql`, live on the workspace) may EXECUTE 24 installed read queries and the single write query `case_write`; nothing else. The same allow-lists are enforced client-side (`TG_ALLOWED_QUERIES`, `TG_ALLOWED_TOOLS`): the MCP client refuses `add_node`/`add_edge`/schema tools, and the gateway has no upsert method. The LLM never sees a query tool.
