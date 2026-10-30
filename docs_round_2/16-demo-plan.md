# Demo plan

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

The analyst picks the case, so the demo is built around the one thing that exists on every case: the proof. Rehearse one script, with a second beat chosen by case shape.

| Time | Beat | On screen |
| --- | --- | --- |
| 0:00–0:30 | Open the named case live from its trigger; say the trigger type and as_of | Console → Re-run live (SSE trace) |
| 0:30–1:30 | The trace: tools called, the provisional action and route, the question asked and why, the revised action and what changed | Evidence and Audit tabs |
| 1:30–3:00 | **The proof.** "This action rests on these 2 facts; margin 2; this many closed cases share them, and here is how the bank ruled." Then *flip one fact live* and the action changes in front of the judges. Say which cases the gate downgraded and the holdout numbers behind it | Proof panel |
| 3:00–4:00 | Second beat by case shape (below) | Containment, conformal or fuzz panel |
| 4:00–5:00 | One drill live: cut the graph mid-run and show the signed failure record, or replay an old approval and show the refusal | Terminal next to the console |

**Second beat by case shape**

- **Ring or connected fraud:** the compromise origin, its lift against controls, the at-risk cards protected with step-up only, and the block set with the customers it touches.
- **Legitimate or ambiguous:** the conformal set, and why it was {fraud, legit}: support check, taint or conflict. Then the harm avoided: who a block would have touched, and that no exposure would have been stopped.
- **Hostile text in the trigger:** the fuzz result for this case (N mutations, 0 decision changes), and the tip-off diff showing zero bytes.

**Prepared answers**

- **"Your weakest point?"** "Graph signals alone separate fraud from legit poorly. Our graph-only arm was AUC 0.52 in Round 1. That is why harmful actions need a proof with margin 2, and why we escalate rather than guess. The cost is more escalations; here is the count."
- **"Isn't the gate just making you timid?"** It can only remove a block that rests on one fact or contradicts precedent. Report the frauds it cost on the holdout next to the innocents it spared.
- **"Why did the risk score not decide?"** The bank model hasn't seen January, so its LR is 1 for January txns, and the support check widens the uncertainty set.
- **"How do you know the text didn't steer it?"** Provenance labels mean the core can't read it, and the fuzz runs show invariance.

Before every slot: wake Savanna 10 minutes early, warm the LLM cache by running all 18 once, and have the three role tokens ready to paste.
