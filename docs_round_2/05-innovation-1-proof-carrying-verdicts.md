# Innovation 1 (headline): proof-carrying verdicts

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

**Claim:** every answer ships with a proof an examiner can check in five minutes. The proof gives the smallest set of attested facts that forces the action, the smallest set whose falsity would flip it, and how the bank ruled on past cases with exactly those facts. A harmful action resting on a thin proof is downgraded before anyone is wronged.

Your decision core is a pure function with no LLM. That means the proof can be *computed exactly* rather than written as prose. The idea comes from abductive ("prime implicant") explanations in the explainability literature; here it is applied to a policy engine.

**What each answer carries (a `proof` block)**

| Part | Definition | How it is computed |
| --- | --- | --- |
| Minimal sufficient facts | The smallest subset of attested facts that, with every other fact set to neutral, still yields the same action class | Greedy deletion over the case's 10–30 facts. Each step is one call of the pure core, so the whole search takes milliseconds |
| Flip set and margin *k* | The smallest set of facts whose negation changes the action class; *k* is its size | Try every single fact, then every pair. With 30 facts that is at most 465 core calls |
| Precedent support | Closed cases whose replayed fact vector contains the same minimal set, with their outcome and action counts | `05_calibrate` already replays every closed case through the same extractor. Store each case's fact vector as a bitmask attribute on `ClosedCase` and query it with one installed GSQL subset match, as_of-bounded |
| Harm ledger | Exposure the action stops (txn ids, $) and the customers it touches | From attested exposure and `OWNS` edges |
| Uncertainty set | {fraud}, {legit} or both | Innovation 4 |

Illustrative output (the numbers are made up): *"Blocked on 2 facts (new device on account; peer purchases on a rare device). Margin 2: both would have to be false to change the action. 31 closed cases share these facts: 29 confirmed, 2 cleared."*

**The gate that changes outcomes**

- Keep a harmful action (BLOCK_CARD, BLOCK_ALL_CARDS, FILE_REPORT) only if *k* ≥ 2 **and** precedent doesn't contradict it. For example, if 10 or more precedents exist and at least 70% were cleared, that is a contradiction. Fit both numbers on Jul–Oct, not by hand.
- Otherwise, downgrade to the strongest free action (VERIFY_WITH_CUSTOMER or STEP_UP_AUTH) plus ESCALATE_TO_ANALYST, and state why in the answer.
- R2 (the customer has denied the charge) is exempt, because policy requires the block. Record the margin anyway.
- The gate is one-way: strong precedent can never *promote* an action to a block. A proof can only remove harm.

**The measurement**

- On the Nov–Dec holdout (including HHG-001…020 with their real outcomes), report the error rate of harmful actions by margin bucket (*k* = 1 vs *k* ≥ 2) and by precedent agreement.
- Report legit customers acted against and frauds missed, with and without the gate. Ablate margin only, precedent only, and both.
- On the 18, list every case where the gate changed the action. That is the "case where it changes the outcome" the brief requires.
- If the holdout shows that fragility does *not* predict errors, say so. Keep the proof as the examiner tool (C6) and don't claim the gate. That honesty is worth points under "Demo clarity and honesty".

**Why it's hard to copy in two days.** It needs a side-effect-free decision function and per-case fact vectors for the whole history. Teams whose LLM sits in the decision path can't compute a flip set at all; they can only write a counterfactual sentence.

**What the examiner sees (C6).** The regulator replay opens on the minimal facts, each with a "re-run query" button. It shows "if fact 2 is false, the action becomes …" before the examiner asks. Challenging a decision means checking 2–3 facts, not reading a trace.
