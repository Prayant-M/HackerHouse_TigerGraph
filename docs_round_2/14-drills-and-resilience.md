# Drill readiness

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

Judges look for four things in every drill: a clear error, no invented answer, no false "saved" status, and consistent results. Each behaviour below needs a script in `drills/` that triggers it, so you have run every drill yourself before a judge does.

| Drill category | What a judge will likely do | Planned behaviour | Your proof |
| --- | --- | --- | --- |
| Dependency fails mid-run | Stop the Savanna workspace, kill the MCP process, or block the network partway through a case | Retry once, then stop with `FAILED_DEPENDENCY`: no verdict, exit code 2, the failing step named, an audit entry. No local-mirror fallback in submission mode. The previous answer file is left untouched | `drills/graph_down.sh` kills the connection after N calls |
| MCP down, graph up | Kill only the MCP server | Use the direct same-graph path, and mark `transport_degraded: true` in the output and the trace. With `GRAPH_STRICT=1`, stop instead | `drills/mcp_down.sh` |
| Model times out | Point the LLM at a black hole, or set a 1 ms timeout | One retry with backoff, then template prose with `prose_source: template`. The verdict, actions and routes are unchanged, and the output says so | `drills/llm_timeout.sh`, plus a diff against the LLM run |
| Model returns garbage | Return malformed JSON, invented ids or an injected action | Schema validation rejects it, grounded() drops sentences with unknown ids, PolicyDecision.filter drops actions, and the run falls back to the template. All of it is logged | A fake-LLM fixture in pytest |
| Hostile or invalid input | Injection in trigger_text; an unknown case id; a missing field; a txn id not in the graph | Injection: flagged with spans, treated as data, and the verdict is unchanged. Invalid input: a clear validation error naming the field, and no answer file | `tests/test_hostile.py`, plus the text-invariance check on all 18 |
| Approval by the wrong role | POST an approval with an L1 token for an L2 action, or put `role: fraud_manager` in the body | 403 from the server-side token role. The body role is ignored, self-approval is refused, and the attempt enters the hash chain. Existing approvals can't be edited | `drills/wrong_role.sh` with curl |
| Same case run twice | Run `make case CASE=HHF-0xx` twice | Identical verdict, probability, actions, routes, exposure and first txn. The case write is an idempotent upsert (version +1, no duplicate evidence or approvals). Prose comes from the LLM cache | `make twice` diffs the decision fields |
| Bounded behaviour | An ambiguous case that could loop | Round cap, wall-clock timeout and token budget, enforced in code and recorded in `halt_reason` | Already exists; add a test |

**Resilience statement (one page; draft it in phase 6)**

- **Dependencies:** TigerGraph Savanna, tigergraph-mcp (pinned), the LLM provider, the local embedding model, Python packages (locked).
- **What leaves the bank boundary:** all graph data to Savanna. To the LLM provider: the evidence brief only (pseudonymous ids, aggregates, policy text, delimited trigger text), never raw rows or V-columns. Nothing else, and no external lookups.
- **On each failure:** the table above.
- **What is logged:** every tool call with params and latency, every decision with its hash, every approval or refusal with the actor's role, and the egress log. Secrets and raw personal fields are redacted.
