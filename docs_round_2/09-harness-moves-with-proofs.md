# Harness moves that come with proofs

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

The harness is worth 20 points and is judged live. Every team will say "we fail closed" and "we check the role". These moves each turn a claim into something a judge can verify in under a minute.

| Guideline | What most teams will do | Your version | The proof a judge can run |
| --- | --- | --- | --- |
| Do not tip off | Scan customer-facing text for banned words | Build customer-visible text with a function whose *input type* excludes SAR state and case-internal fields, so it can't leak them. Keep the word scan as a second layer | A test toggles the SAR flag on all 18 cases and diffs the customer text: zero bytes change |
| Same case run twice | "Temperature 0, deterministic" | Recorded tool I/O: every tool response is stored by content hash. `replay` reproduces the decision bit-for-bit offline. `diff` reports whether a rerun changed because the *data* changed or the *code* changed | `make replay CASE=…` and `make diff CASE=…` |
| Temporal wall | An as_of parameter on every query | Future-dated canary txns (ids `CANARY-*`, ts in 2099) on every case card. They are inserted at verify time and removed after. Any canary appearing in a query result fails the run | The canary step in `07_verify` and in CI |
| Treat text as data | A regex or LLM filter | Provenance labels on every state value: graph, customer text, analyst text, or LLM. The core rejects any decision input whose label isn't graph or an allow-listed extractor output | A runtime assertion, plus the M2 fuzz results |
| Approvals enforced server-side | Check the token's role | Check the token's role, then sign the approval record on the server (Ed25519) and chain it. `verify` detects an edited approval or one replayed from another case | A drill that replays an old approval: refused |
| Fail closed | Stop on error | Stop on error, and write a signed `FAILED_DEPENDENCY` record naming the step, the dependency and the last good attestation. The previous answer file stays untouched | Kill the graph mid-run, then show the record |

Recorded tool I/O does double duty. It is the regulator replay (C6: "what the agent saw at that moment" is the stored response), and it answers the "same case twice" drill.
