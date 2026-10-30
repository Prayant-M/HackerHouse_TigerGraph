# Risks and cut order

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Freeze is earlier than planned | Unfinished work is ignored | Tag at every gate; from hour 10 you are always one push from a valid submission |
| Card-id pinning fails for new January cards | Card-scoped queries break silently | Assert that every pack and closed-case card id resolves in 07_verify; fail the load otherwise |
| Overfitting the rules to the 20 HHG outcomes | Hidden-case accuracy drops | Fit on Jul–Oct; use HHG and Nov–Dec as holdout only; backtest every rule on closed cases before keeping it |
| The old risk-alert prior clears January fraud | Missed frauds on 11 risk-score cases | Neutral LR for Jan risk_score, a softened prior, and R1 verify before any block |
| Over-correcting into blocking | Zero on legit cases | Harm-aware selection; a block needs R2 or two independent signals; otherwise verify or escalate |
| Savanna sleeps or drops during drills | A failed drill, or a fallback that looks silent | Keep it warm before your slot; fail closed and say so. That is a pass, not a failure |
| Drill judges can't reach your graph | An unreproducible run is a gate failure | Settle access with the organisers on day 1; have a scoped read-only token ready |
| C13 variant arrives and eats the afternoon | Core work slips | Hard 3-hour box; drop it if C12's mapper doesn't generalise |
| LLM quota or outage | Slow runs | The LLM is off the decision path; cache prose; template fallback |
| Fatigue on the last night | Mistakes at the freeze | The sleep block is in the plan; the freeze checklist is a script, not memory |

**Cut order if behind.** Cut from the top; never cut the last group.

1. Evasion-frontier attacks (keep the hostile-text fuzz)
2. Signed approvals, canaries and runtime provenance labels (keep token auth and the extractor-only rule)
3. C14 WATCH child cases and handover notes
4. Containment UI panel (keep the JSON plan and the CLI table)
5. Forward at-risk set (keep the time-sliced ring and the backward block set)
6. Metamorphic relations M3–M6 (keep M1, M2 and M7)
7. Precedent support in the proof (keep the minimal facts, the margin and the gate)

**Never cut:** 18 grader-clean answers, fail-closed mode, server-side approval auth, least-privilege writes, attestation on every claim, the resilience statement, the one command from a clean clone, the proof object with its holdout table, and conformal uncertain + escalate.
