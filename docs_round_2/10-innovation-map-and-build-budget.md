# Innovation map and build budget

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

Innovation is scored 0–5 on each of five axes, and an idea scores zero without a measurement. Each axis below is covered by at least one idea with its own measurement.

| Axis | Idea | Measurement that shows it changes an outcome |
| --- | --- | --- |
| Novel detection | Compromise origin by lift; evasion-frontier mining | At-risk precision and lift; frontier fraud caught with no new legit hits |
| Novel use of the graph | Precedent-by-fact-set query; time-sliced ring; `COMPROMISE_POINT` write-back read by later cases | Precedent counts in every answer; time-sliced vs all-time ablation |
| Novel agent design | Proof-carrying verdicts and the gate; provenance-typed data flow | Harmful actions downgraded on the holdout; legit customers spared |
| Novel evaluation | Metamorphic relations; conformal coverage | Violations found and fixed; coverage vs nominal 90% |
| Real-world value | Forward containment with free actions only; a proof an examiner checks in minutes | $ of loss pre-empted at zero blocks on innocents |

**Build budget.** These ideas replace generic work in the timeline; they don't sit on top of it.

| Item | Hours | Tier | Phase |
| --- | --: | --- | --- |
| Proof-carrying verdicts and the gate | 5 | Must | 4 |
| Conformal abstention and the support check | 3 | Must | 4 |
| Tip-off by construction | 1 | Must | 6 |
| Recorded tool I/O replay | 2 | Must | 6 |
| Compromise origin, forward containment, block set | 7 | Must | 7 |
| Metamorphic suite and hostile-text fuzzing | 4 | Must | 8 |
| Evasion-frontier attacks | 3 | Stretch | 8 |
| Future-dated canaries | 1 | Stretch | 6 |
| Signed approvals | 1.5 | Stretch | 6 |
| Provenance labels at runtime | 2 | Stretch | 6 |

The must-build items total 22 hours. Phases 4, 6, 7 and 8 have about 23 hours, and they still hold the required work: attestation, the R1/R2 split, fail-closed mode and auth. **This is tight.** It fits only if the generic versions of the same work are dropped, and stretch items are started only when a gate passes early. If you have a teammate, give them Innovation 3 and the harness moves; that is the cleanest split.
