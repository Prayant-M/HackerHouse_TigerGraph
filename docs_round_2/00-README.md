# TigerGraph × HH Goa 2026 — Final Round Plan

*Execution plan for the final round (Oct 2026), building on the Round 1 FraudGraph agent. Read `01` once for the brief, then this page, then `05`.*

## Files

| File | What's in it |
| --- | --- |
| [`01-problem-statement-final-round.md`](01-problem-statement-final-round.md) | The final-round brief, start to end, plus Round 1 context, the dataset and a policy quick reference |
| [`02-what-changed-and-scoring.md`](02-what-changed-and-scoring.md) | Round 1 choices that now cost points, data changes, where the 100 points sit |
| [`03-challenge-selection.md`](03-challenge-selection.md) | Which of the 14 challenges to take, and why |
| [`04-competitive-landscape.md`](04-competitive-landscape.md) | What the other teams will likely build, and the step past each |
| [`05-innovation-1-proof-carrying-verdicts.md`](05-innovation-1-proof-carrying-verdicts.md) | **Headline idea:** minimal facts, flip set, precedent support, the gate |
| [`06-innovation-2-predictive-containment.md`](06-innovation-2-predictive-containment.md) | Compromise origin, forward protection with free actions, the block set |
| [`07-innovation-3-label-free-evaluation-and-attacks.md`](07-innovation-3-label-free-evaluation-and-attacks.md) | Metamorphic tests, hostile-text fuzzing, evasion-frontier attacks |
| [`08-innovation-4-conformal-abstention.md`](08-innovation-4-conformal-abstention.md) | Coverage-guaranteed "uncertain" under the January shift |
| [`09-harness-moves-with-proofs.md`](09-harness-moves-with-proofs.md) | Drill-facing guarantees a judge can verify in a minute |
| [`10-innovation-map-and-build-budget.md`](10-innovation-map-and-build-budget.md) | Scoring axis → idea → measurement; hours and tiers |
| [`11-architecture-changes.md`](11-architecture-changes.md) | What gets added to the Round 1 system, by module |
| [`12-setup-checklist.md`](12-setup-checklist.md) | Data, graph, keys, auth, repo, organiser questions |
| [`13-execution-timeline.md`](13-execution-timeline.md) | Nine phases to the freeze, each with a gate |
| [`14-drills-and-resilience.md`](14-drills-and-resilience.md) | Each drill category, the planned behaviour, the resilience statement |
| [`15-submission-checklist.md`](15-submission-checklist.md) | Everything that must exist at the frozen commit |
| [`16-demo-plan.md`](16-demo-plan.md) | The 5-minute script for any case, plus prepared answers |
| [`17-risks-and-cut-order.md`](17-risks-and-cut-order.md) | Risks, mitigations, and what to cut first |

## TL;DR

Keep the Round 1 engine, harden it into something a bank could run, and compete on ideas the brief doesn't spell out. The brief's own examples (fan-out detectors, injection filters, per-sentence citations, a ring slider) are what the other five teams will build. Every idea below goes one step past them, and each comes with the measurement the brief requires.

**Headline, the one idea judged: proof-carrying verdicts.** Every answer ships with three things:

- the minimal set of attested facts that forces its action;
- the smallest set whose falsity would flip it (its robustness margin);
- how many closed cases with exactly those facts the bank confirmed or cleared.

A block or report with margin 1, or with contrary precedent, is downgraded to verify plus escalate before anyone is wronged. This works on any of the 18 cases, which matters because the analyst picks the demo case. Only your LLM-free core makes it computable.

**Supporting stack**

1. **Predictive containment from the point of compromise (C7 + C1).** Trace a ring back to the entity its cards shared weeks before the loss. Then protect the cards that touched it but haven't been hit yet, using only monitor and step-up, which cost nothing on legit customers.
2. **Label-free evaluation (C10).** Metamorphic relations find bugs without an answer key. Hostile-text fuzzing proves decisions are invariant to the text. Attacks are derived from your own detector thresholds.
3. **Conformal abstention under the January shift (C11, R8).** "Uncertain" comes from a coverage guarantee, and widens when a case falls outside what calibration has seen.
4. **Harness moves with proofs.** No tip-off by construction, recorded-I/O replay, future-dated canaries, signed approvals.

**Order of work.** Load January → a gradeable baseline on all 18 → answer quality with proofs and conformal → harness for drills → predictive containment → metamorphic tests and attacks → freeze. A gradeable baseline exists from about hour 10, and every checkpoint after that is tagged and submittable.

**Open questions for organisers on day 1**

- When is the freeze?
- How will drill judges reach your graph: your Savanna with credentials they hold, or their own Community Edition load?
- When is the C13 schema variant handed out?
- Does the public HF console count as data egress?

## Reading order

1. **First time:** `01` (the brief) → this page → `02` → `05` → `13`.
2. **Before building each phase:** the phase in `13`, then the innovation file it points to.
3. **Before the demo:** `16`, `14`, then `17`'s cut order.
