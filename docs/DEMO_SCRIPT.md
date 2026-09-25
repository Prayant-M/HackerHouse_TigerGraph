# Demo video — shot list

**Target 4:00. Hard ceiling 5:00.** Record three dry runs before the take.

Start the console first and leave it running:

```bash
python ui/server.py      # http://127.0.0.1:8080
```

Have a second terminal ready, and have `HHG-006` and `HHG-014` already loaded in
two browser tabs so you are never waiting on a page.

---

## 0:00–0:25 · The problem, in one breath

> "Six months of card transactions. No fraud label — every transaction carries a
> risk score from the bank's model instead, and above 0.70 most of those turn out
> legitimate. Four months of closed investigations, and twenty new alerts to
> decide. The hard part isn't scoring. It's knowing when you have enough to act."

On screen: the case inbox, twenty alerts, colour-coded by verdict.

---

## 0:25–1:15 · One case, end to end

Open **HHG-006** — a customer dispute.

Click **Re-run investigation live** and talk over the streaming trace:

> "It opens a case, fixes a temporal cutoff, and pulls the card's baseline from
> the graph. Then the typology probes run. This one hits."

Point at the evidence board:

> "Four online purchases in thirty minutes — $478.95, $456.96, $488.04, $482.12.
> Every one just under five hundred dollars. Nineteen hundred dollars total."

Then the important line:

> "That matches none of the five documented patterns. It matches five closed
> cases the bank's own analysts confirmed as fraud and couldn't categorise. The
> agent mined that signature out of the history and registered it as a new
> typology it can now match against."

Scroll to the posterior bars: `undocumented` leading.

---

## 1:15–2:05 · The money shot — the recommendation changes

Open **HHG-002** (or `HHG-007`, `HHG-017`, `HHG-020` — the inbox marks all four
`revised`).

Show the **before / after** panel side by side.

> "Belief sits at 0.29. That supports no defensible action in either direction.
> Here's the part a single-shot pipeline can't do honestly: the agent commits to
> a provisional recommendation *first* — verify with the customer, escalate, no
> block, because R1 forbids blocking on a single weak signal below 0.70 — and
> only then goes looking."

Point at the VoI numbers on the evidence request:

> "Then it picks *which* question to ask. Not the strongest one — the one with
> the most information per unit of customer friction. Pinging someone at 2am has
> a real cost even when the API call is free."

Point at the posterior movement, then the revised column:

> "The response lands. Belief falls from 0.29 to 0.02, and the recommendation
> becomes close-no-fraud — with the delta recorded and the policy rule cited.
> Before and after, both written to the case and both in the answer file."

---

## 2:05–2:45 · TigerGraph doing something a vector store can't

Open **HHG-014** — the analyst request.

Show the case subgraph canvas: the hub device at the centre, nineteen unrelated
cards hanging off it.

> "One Samsung handset, one browser, one anonymous proxy, nineteen unrelated
> cardholders in a month, marked new on every account it touches. No individual
> account looks like anything. It only exists as a hub in the card-device
> projection."

Then the discriminator:

> "The trick is that a device profile here is a model-OS-browser-screen string,
> not a serial number — ninety-two percent of online transactions sit on a
> profile shared by three or more cards. Counting cards finds nothing. What
> separates this one is that *every* card that ever touched it arrived through
> an anonymising proxy. Ratio of 1.00 against 0.03 for an ordinary shared
> fingerprint."

Cut to the terminal, show `graph/queries/hybrid_case_recall.gsql` on screen:

> "And this is the query the memory layer runs. Vector search over prior case
> narratives, fused with a graph traversal to the cases that touched the same
> entities — in one GSQL statement, in one database. Both legs time-bounded, so
> it can't retrieve the future."

---

## 2:45–3:20 · The controls

Switch to the **Approval queue** tab.

> "The agent executes only auto-routed actions. Blocks and regulatory filings are
> recommended with the route stated and wait for a person — team lead under
> $2,500, fraud manager above it, fraud manager always for a report. That routing
> is deterministic Python that cannot call a model. An agent you can *argue* into
> executing a block is not a control."

Approve one. Show it recorded against the case.

Then scroll a case's **decision ledger**:

> "Every decision is hash-chained to the one before it. Edit a recorded rationale
> after the fact and the chain breaks and says where."

---

## 3:20–3:50 · Calibrated, not confident

Switch to the **Calibration** tab.

> "These likelihood ratios aren't chosen. Every closed investigation was replayed
> through the same extractor the agent uses, under its own timestamp, and the
> ratios were measured from outcomes."

Then the honest bit — this lands well:

> "Doing that naively inverts the whole system. Every cleared case in the history
> got there by scoring high on the bank's model, so inside that file 'looks
> anomalous' predicts *cleared* — and an agent trained on it learns to wave fraud
> through. We caught it because we measured it. The fix was matched controls:
> compare each fraud case against another transaction on the same card."

Then the number I'd put on screen, from `eval/reports/backtest.md`:

> "Four hundred October alerts, replayed twice — once with the trigger each
> alert really had, once with it stripped. Strip the trigger and fraud-versus-not
> falls to chance, AUC 0.94 down to 0.53. Strip the trigger and pattern accuracy
> barely moves, 0.57 to 0.56, and the decision to file a regulatory report
> doesn't move at all, 0.925 to 0.922."
>
> "So the trigger tells you *whether*. The graph tells you *which typology*, *how
> far it goes*, and *whether to file*. That's measured, not claimed."

---

## 3:50–4:00 · Close

> "Twenty answer files, every one validated against the answer format. Every case
> written into TigerGraph as a graph object you can walk. Runs end to end with no
> API key at all — the model writes the prose, the graph makes the decisions."

If there is time, one last cut to the terminal:

> "And it doesn't only answer the twenty. Let it monitor November and December on
> its own and the bank's twenty highest-scoring transactions yield two frauds —
> while the sub-threshold structuring sweep yields twenty out of twenty, thirty-one
> thousand dollars the risk model never flagged, because every individual leg is
> an ordinary purchase and the pattern only exists across the burst."

---

## Recording notes

- **Use the cached LLM run.** `.cache/llm/` makes prose identical between takes,
  so a re-record doesn't change what's on screen.
- **Know your ids before you start.** Which case flips its recommendation, which
  files a SAR, which is undocumented. Do not hunt on camera.
- **Do not narrate the UI.** Narrate what the agent concluded and why.
- **Keep one terminal visible** at least twice. Judges want to see it run, not
  just see a dashboard.
- If Savanna has auto-stopped, the store falls back to the local mirror with a
  printed warning and the demo continues. Know that before it happens live.
