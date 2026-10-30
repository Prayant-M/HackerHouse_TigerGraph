# What changed, and what scoring rewards

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

Round 1 asked "can it investigate?" The final asks "can a bank run it?" Several Round 1 choices that were fine before are now breaches, so they are the first things to fix.

**Round 1 choices that now cost points or gates**

| Round 1 behaviour | Final round rule | Change |
| --- | --- | --- |
| Graph down → local pandas mirror (`GRAPH_STRICT=0` default) | Fail closed; never present fallback data as complete | `GRAPH_STRICT=1` is the default. The mirror is dev-only and never used in submission mode |
| Roles are a UI dropdown | Approvals enforced server-side; a role from the request body is not enforcement | Token → role on the server, append-only approvals |
| Agent writes through MCP `add_node` / `add_edge` | Least privilege: one write path only | Writes go only through one installed `case_write` query. Allow-list the MCP tools |
| Evidence items carry tool + raw output | Every claim attested (what, evidence ids, query + params, timestamp + data) or it counts as wrong | Add an attestation object and a `make attest-verify` that re-runs every query |
| Risk-alert prior learned from 900 of 900 cleared | Jan risk_score is near useless; a low score is not innocence | Neutralise the risk_score signal for Jan and soften the risk-alert prior. **The old prior would wave Jan fraud through** |
| Peers on a rare device are not "connected cards" | §3a: a connection to a shared device, a region cluster or another customer's fraud triggers a SAR | Re-derive the SAR rule and backtest it against the bank's real filings |
| Public HF console with case data | Undeclared egress rules a team out | Take it down, or declare it in the resilience statement |

**Data changes and what they mean**

- **January 2017** (60,196 txns, 15,893 identity rows) uses the same schema. New cards will appear, so card-id pinning has to be re-verified.
- **closed_cases_history.csv** now has 5,585 rows and includes HHG-001…020 with their real outcomes. That gives you a free scored holdout for your Round 1 answers. It also means a likely duplicate: your agent-written HHG `FraudCase` vertices and the new `CC-xxxx` records for the same investigations. Dedupe them in recall.
- **Case pack:** 18 cases, with 11 risk_score, 4 customer_report and 3 analyst_request triggers. About half are legitimate, some are ambiguous, some fit no documented pattern, and 6 carry hostile text.

**Where the 100 points sit**

| Criterion | Pts | What wins it for you |
| --- | --: | --- |
| Innovation | 25 | One idea plus a measurement where it changes an outcome; an ablation |
| Harness and critical situations | 20 | Live drills: fail closed, auth, redaction, audit, bounded, escalate |
| Answer quality | 15 | Never block or report a legitimate customer; uncertain + escalate is full credit |
| Evidence and policy behaviour | 10 | R1 vs R2, §3a, approval routes, a stated reason for the after-evidence change |
| Use of TigerGraph | 10 | Vector + traversal fusion, an algorithm that changes output, write-back and read-back, restricted MCP |
| Engineering and reproducibility | 10 | Tests pass, clean clone works, no secrets, auth on approvals |
| Demo clarity and honesty | 10 | Explain any case from the trace; README numbers match the live run |

Gates outrank points: disallowed data, undeclared egress, or a run that can't be reproduced rules a team out. Harness (20) and the gates together are worth more than answer quality (15), so harness work comes before polishing answers.
