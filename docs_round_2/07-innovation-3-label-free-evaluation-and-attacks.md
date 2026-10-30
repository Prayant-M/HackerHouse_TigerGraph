# Innovation 3: label-free evaluation and attacks your own thresholds generate

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

**Claim:** there's no answer key for the 18, so most teams will tune by eye or against the 20 HHG precedents. Metamorphic testing checks relations that must hold *whatever the right answer is*, so it finds real bugs with no labels at all. The attack suite is then derived mechanically from your own detector thresholds, not written by imagination.

**Metamorphic relations**

Run these on the local-mirror backend, so mutations never touch the real graph. Round 1's parity test already shows the mirror agrees with TigerGraph on 20 of 20 cases.

| ID | Relation | Mutation | Must hold |
| --- | --- | --- | --- |
| M1 | Id renaming | Consistently relabel every customer, card and txn id | Identical decision fields. This also rehearses C13 |
| M2 | Hostile text | About 40 injection templates × each case: fake system text, role claims, demands for both the correct and the wrong outcome, homoglyphs, instructions inside analyst notes | Decision fields identical, except for the facts the extractor is allowed to read, which are listed |
| M3 | Irrelevant activity | Add txns from unrelated customers outside the case's 2-hop neighbourhood | Identical |
| M4 | Time shift | Shift every ts and the as_of by the same +Δ | Identical |
| M5 | Monotone evidence | Add one more attested fraud signal | p_fraud doesn't fall, and action severity doesn't fall |
| M6 | Monotone exposure | Double the affected amounts | A SAR requirement never switches off |
| M7 | Determinism | Run the same case twice | Byte-identical decision fields |

Report three numbers: violations found, violations fixed, and which HHF answers changed because of a fix. M2 alone gives a headline like "0 of 720 mutated runs changed a decision". Back it with a naive baseline where the LLM reads trigger_text directly, and show that baseline's flip rate next to yours.

**Evasion-frontier attacks (C10, "activity shaped to look innocent")**

Your LLM can't decide anything, so the honest attack surface is your rules. Saying that out loud, and attacking them, is the step past prompt-injection demos.

1. **Derive the cheapest evasion of each detector from its own thresholds.**
   - U1 structuring: 3 legs instead of 4, legs at $430 instead of $480, or 90 minutes instead of 40.
   - R7 recurring: "season" a card with 8 small charges over 90 days before the fraud, so the disputed charge looks like a habit.
   - U2 proxy hub: mix in non-proxy sessions until the anonymous ratio drops below 0.5.
   - peer_purchases: use a device seen on 11 cards, just over the "rare" cut-off.
2. **Make each one reproducible.** Plant txns with ids `ATK-*` in the mirror, and record the expected and actual verdicts.
3. **Mine real data at the frontier.** Look for confirmed-fraud closed cases that fall just outside each threshold. If fraud clusters just past a boundary, attackers have adapted to it. Harden with relative rules (legs within 15% below any round ceiling such as $250, $500 or $1,000; seasoning detected as baseline built only in recent weeks), then re-backtest the legit hits.
4. **Score it.** Report attacks that flipped a verdict before and after the defences, and legit customers newly flagged by the hardening.
