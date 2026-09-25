# Demo Video Script (3–5 min)

**Target 4:30. Hard ceiling 5:00.** One dry run with a timer before recording.

The story in one line: **the graph makes the decisions, the agent knows when it
doesn't know enough, and every case goes back into TigerGraph — through MCP —
as an object you can walk.**

---

## 1. Pre-flight (10 minutes before)

**Terminal 1 — wake TigerGraph** (it auto-stops when idle). Wait for `pong`:
```powershell
curl.exe -s https://tg-cf861626-a62b-4fc7-8f48-98f44e66d4ad.tg-3452941248.i.tgcloud.io/api/ping
```
Keep it awake during the takes (Ctrl+C when done):
```powershell
while ($true) { curl.exe -s https://tg-cf861626-a62b-4fc7-8f48-98f44e66d4ad.tg-3452941248.i.tgcloud.io/api/ping | Out-Null; Start-Sleep 120 }
```

**Terminal 2 — fresh answers and audit:**
```powershell
$env:AGENT_USE_LLM = "0"; python benchmark/run_20.py
python eval/audit_answers.py
```
Expect 11 legitimate / 9 fraud, 2 SARs, 5 changed after evidence, `0 issue(s)`.
(Drop the `AGENT_USE_LLM` line if the LLM quota is working; verdicts are identical.)

**Terminal 3 — the console** (leave running):
```powershell
python ui/server.py      # http://127.0.0.1:8080
```
The status pill must read **TigerGraph · via MCP**. If it says "Local mirror",
ping the workspace and restart the server.

**Browser tabs, in order:** the console home · Savanna GraphStudio on
`FraudGraph` (Explore Graph open) · the GitHub repo.

**Editor tabs:** `graph/queries/hybrid_case_recall.gsql` ·
`graph/queries/peer_purchases.gsql` · `graph/algorithms/05_graph_algorithms.gsql` ·
`src/fraudagent/graphstore/mcp_client.py` · `tests/test_core.py`
(`test_core_cannot_import_an_llm`).

**Cases to know by heart:**

| Case | Shows |
|---|---|
| **HHG-006** | Undocumented structuring: 4 purchases, $1,906.07 in 30 min, SAR |
| **HHG-018** | R7: a disputed $39.08 charge paid 21 times → verify → recognised → closed, no block |
| **HHG-014** | Device ring: 19 cards, anonymous-proxy ratio 1.00; WCC 54-card component, PageRank #2 |
| **HHG-019** | A low-priority risk alert: same rare device, ~$100 on two other cards that week → fraud 0.95, blocked, no SAR (§3a) |

Screen: 1080p, browser zoom ~110%, notifications off. Narrate what the agent
concluded and why, not which button you press.

---

## 2. Script

### 0:00–0:25 · The problem — Home page
> "Card-fraud alerts arrive three ways: the bank's risk model, a customer saying
> 'that wasn't me', or an analyst's question. The hard part isn't scoring. It's
> knowing when you have enough to act, and what to do when you don't. This agent
> investigates each alert on TigerGraph and explains every decision."

Scroll once through "How it works" and stop on the three "Start here" cards.

### 0:25–1:05 · A pattern nobody documented — HHG-006
Click the HHG-006 card. On **Overview**, point at the gauge (97%) and the SAR chip.
Switch to **Evidence**: the top item.
> "Four online purchases in thirty minutes, each just under $500. Every leg looks
> ordinary, so a per-transaction score never sees it. It matches none of the five
> documented patterns, but it matches five closed cases the bank's own analysts
> confirmed as fraud and couldn't categorise. The agent mined that signature from
> the history and files a report."

### 1:05–2:00 · The decision changes — HHG-018
Open **HHG-018**. Stay on **Overview**, scroll to **How the decision unfolded**.
> "A customer says 'I never made this $39.08 purchase'. The graph shows the card
> has paid exactly that amount, same product, 21 times since July. That is policy
> rule R7: disputed but legitimate. So the first recommendation is not a block —
> open a case, ask the cardholder, remind them of the charge."

Point at the middle column, then the final column.
> "It asks the one question worth its friction. The reply is simulated this
> round, and the file says exactly what was assumed and why. The cardholder
> recognises the charge, the likelihood falls from 52% to 2%, and the case closes
> with no block. Before and after are both in the answer file."

Point at **What the agent still doesn't know** for two seconds.

### 2:00–3:05 · Only a graph sees this — HHG-014 and HHG-019
Open **HHG-014 → Graph**. Scroll-zoom into the right-hand cluster, click the red
device node.
> "An analyst asked about one device. It sits behind an anonymising proxy on
> nineteen unrelated cards in a month. No single account looks wrong; it only
> exists as a hub. TigerGraph's graph algorithms confirm it: weakly connected
> components over the anonymous-proxy links put this card in a 54-card component,
> and PageRank ranks it second."

Flash `05_graph_algorithms.gsql`, then `hybrid_case_recall.gsql` (scroll past
`vectorSearch` and the traversal legs).
> "Memory is one GSQL query: vector search over 5,565 past narratives, fused with
> a traversal to cases that touched the same cards and devices."

Open **HHG-019 → Evidence**; point at **How the probability got here**: 38% at the start, then the peer-purchase row adds about 51 points.
> "This one came from the risk model, which is usually a false alarm. But the same
> rare device bought about a hundred dollars on two other cards that week. That
> signal was measured on the bank's closed cases: it fired on 31 frauds and no
> cleared cases. Fraud, card blocked. And no report: under a hundred dollars, one
> card, a known pattern — the policy's filing test says case only, and the agent
> follows the policy, not the drama."

Point at the status pill.
> "Every one of these reads went through the TigerGraph MCP server — nearly fifteen
> hundred tool calls on the last run, zero fallbacks."

### 3:05–3:45 · The controls
Open **HHG-019 → Audit trail**, press **▶ Play** and let two steps run.
> "Every decision is hash-chained. The case is written back to the graph and read
> back before the file says it was written."

Click **Approvals**, approve one block.
> "The agent only runs low-risk actions itself. Blocks and filings wait for a
> person, and approving writes an APPROVED_BY edge into the graph."

Flash `test_core_cannot_import_an_llm`.
> "Probabilities, actions and routes come from code that cannot import a language
> model. The model plans and writes, and any sentence citing an ID the evidence
> doesn't contain is thrown away."

### 3:45–4:15 · Checked, not claimed — Scoreboard and Insights
Click **Scoreboard**.
> "All twenty side by side, each audited against the raw data and every policy
> rule: zero issues."

Click **Insights → Calibration** for two seconds.
> "The weights aren't hand-picked; they're measured on the closed cases. On 400
> held-out October alerts: with the alert's trigger, AUC 0.92. Strip the
> trigger and it falls to 0.52 — but which fraud pattern, and whether to
> file a report, barely move. The trigger tells you *whether*; the graph tells
> you *what* and *whether to file*."

### 4:15–4:40 · Close — Monitoring
Click **Monitoring**.
> "Left alone on November and December, the bank's top-scored alerts gave 6 frauds
> in 30. The agent's own structuring sweep found 30 in 30 — $38,000 the risk model
> never flagged."

Switch to the GitHub tab (`cases/` folder).
> "Twenty validated answer files, every case written into TigerGraph through MCP,
> and it runs end to end with or without an API key."

**Stop recording.**

---

## 3. What to emphasise in the UI

1. **"How the decision unfolded"** (HHG-018) — before → question → after. The brief's core ask.
2. **Graph tab** (HHG-014) — zoom, click; the ring is visibly a hub.
3. **Evidence tab** — the probability path (prior → each item → final), each item's measured movement and its claim-type badge.
4. **Status pill "via MCP"** and the **✓ In graph** chip.
5. **Audit trail replay** and the read-back checks.
6. **Approvals**, **Scoreboard** (20/20 clean), **Monitoring**.

---

## 4. Numbers to have ready

| Claim | Number | Source |
|---|---|---|
| Verdicts | 11 legitimate / 9 fraud | `run_20.py` footer |
| SARs | 2 (HHG-006, 014) | Scoreboard |
| Changed after evidence | 5 | Scoreboard |
| Answer audit | 0 issues / 20 | `eval/reports/answer_audit.md` |
| HHG-006 | 4 purchases, $1,906.07, 30 min | Evidence tab |
| HHG-018 | 21 identical charges, 140 days; 52% → 2% | Overview |
| HHG-014 | 19 cards, ratio 1.00; WCC 54 cards, PageRank #2 | Evidence / Graph |
| peer_purchases | fired on 31 fraud, 0 cleared closed cases (LR 22.4) | Insights → Calibration |
| Graph | 590,742 transactions · 21 GSQL queries · 69 MCP tools | README |
| MCP | 1,492 calls, 0 fallbacks | last `run_20` |
| Backtest AUC | 0.921 with trigger → 0.520 graph-only; pattern accuracy 0.508 → 0.471 | `eval/reports/backtest.md` |
| Monitoring | risk model 6/30 · structuring 30/30 ($38,145.65) · device hub 24/27 | Monitoring page |
| Tests | 64 passing | `pytest tests -q` |

---

## 5. If something goes wrong on camera

| Problem | Do this |
|---|---|
| Pill says "Local mirror" | Stop. Ping the workspace, restart `ui/server.py`. |
| Re-run live is slow | Cut after five seconds; the stored case has everything. |
| A number on screen differs from the script | Say the number on screen. |

---

## 6. After recording — submission checklist

- [ ] Video uploaded, viewable by link (test in a private window).
- [ ] Repo public; `cases/HHG-001.json` … `HHG-020.json` at `cases/`.
- [ ] `.env` not committed.
- [ ] Form: LLM = `gemini-3.6-flash` (prose only) · framework = `LangGraph`.
- [ ] Blog + social posts tagging **@TigerGraphDB** and **@247pmstudio**.
