# Integration and development record

What was built, in what order, what broke, and what the fix was. This is the
engineering account — `README.md` is the operating manual and
`SETUP_REQUIRED_FROM_YOU.md` is the list of things only you can provide.

---

## Contents

1. [What was delivered](#1-what-was-delivered)
2. [Order of construction](#2-order-of-construction)
3. [The data layer, and the problem that had to be solved first](#3-the-data-layer)
4. [Graph model and the GSQL toolkit](#4-graph-model-and-the-gsql-toolkit)
5. [Two backends, one contract](#5-two-backends-one-contract)
6. [The deterministic core](#6-the-deterministic-core)
7. [Calibration: what measuring actually found](#7-calibration-what-measuring-actually-found)
8. [The agent](#8-the-agent)
9. [Answer files and schema discipline](#9-answer-files-and-schema-discipline)
10. [The console](#10-the-console)
11. [Enhancements beyond the brief](#11-enhancements-beyond-the-brief)
12. [Requirement-by-requirement traceability](#12-requirement-by-requirement-traceability)
12a. [Results](#12a-results)
13. [Known limits and what I would do next](#13-known-limits-and-what-i-would-do-next)
14. [What other teams' designs taught us](#14-what-other-teams-designs-taught-us)

---

## 1. What was delivered

| Artefact | Path | State |
|---|---|---|
| Ingestion pipeline (7 stages) | `ingest/` | complete, verified |
| TigerGraph schema, vectors, loading jobs | `graph/ddl/`, `graph/loading/` | complete |
| GSQL investigation toolkit (14 files) | `graph/queries/` | complete |
| Derived projection + GDS | `graph/algorithms/` | complete |
| Idempotent installer | `graph/install.py` | complete, `--dry-run` supported |
| Graph access layer, two backends | `src/fraudagent/graphstore/` | complete |
| Deterministic decision core | `src/fraudagent/core/` | complete, 64 tests across the suite |
| LangGraph agent | `src/fraudagent/agent/` | complete |
| Answer builder + schema validator | `src/fraudagent/report/` | complete |
| Simulated action service | `src/fraudagent/mcp_servers/` | complete |
| Calibration replay | `ingest/05_calibrate.py` | complete |
| Backtest harness | `eval/backtest.py` | complete |
| Benchmark runner | `benchmark/run_20.py` | complete — **writes the submission** |
| Autonomous monitor | `benchmark/monitor.py` | complete (optional extra) |
| Analyst console | `ui/` | complete |
| Documentation | `README.md`, `docs/`, this file | complete |

---

## 2. Order of construction

The sequence mattered, because each stage exposed something that changed the
one before it.

1. **Read the dataset README twice before writing code.** It contains the answer
   format, the policy, the typologies and — crucially — the sentence *"not every
   fraud pattern present in the data is documented"*.
2. **Profile the raw files.** This is where `card_id` turned out to be missing,
   which blocked everything else.
3. **Mine the closed cases before designing detectors.** The nine `undocumented`
   cases and the analyst-note templates determined the whole detector set. Doing
   this after building detectors would have meant building the wrong ones.
4. Ingestion → graph model → local mirror → deterministic core → calibration →
   agent → answer files → console → docs.
5. **Calibrate, then look at the numbers.** Twice the numbers said something
   absurd, and twice the absurdity was real. See §7.

---

## 3. The data layer

### The problem that had to be solved first: `card_id` does not exist

`transactions.csv` has 394 columns and none of them is `card_id`. Both
`case_pack.csv` and `closed_cases_history.csv` are expressed entirely in terms
of `C01234-K1`. Without recovering it, no card-scoped query can be written at
all.

Findings, in order:

- `card1` is **1:1 with `customer_id`** — 13,553 customers, 13,553 distinct
  `card1` values. So `card1` is not the card.
- The card is the `(customer_id, card2..card6)` tuple: 12,308 customers with one,
  1,157 with two, 81 with three, 7 with four. The maximum `K` index in the labels
  is 3, consistent.
- But the `K` **ordering** is not recoverable from the tuple. Measured against
  the labels:

  | ordering | agreement |
  |---|---:|
  | first-seen ascending | 0.506 |
  | lexicographic | 0.508 |
  | transaction count ascending | 0.927 |
  | most-missing-card-fields first, then first-seen | 0.952 |

  A 95% heuristic silently breaks every card-scoped query on one case in twenty.

**The fix was to stop guessing.** The closed cases and the case pack between
them name the card for **14,975 transactions**. Those pin their `(customer, tuple)`
keys directly by majority vote; unpinned keys take the remaining indices by the
95% heuristic. Result: **1.0000 agreement on every labelled transaction, 20/20
on the case pack.** `ingest/07_verify.py` asserts it on every build.

### What else the ingestion does

| Stage | Output |
|---|---|
| `01_normalise.py` | 590,742 transactions → parquet; identity joined; device profile assembled as `DeviceInfo \| OS \| browser \| screen`; `M1`–`M9` made trinary (match / mismatch / **missing**, because missingness is signal in IEEE-CIS); per-card rolling baselines; 14,850 card profiles; 9,705 device profiles |
| `02_behaviour_embeddings.py` | Incremental PCA over `V1`–`V339` → 24 components, concatenated with rank-normalised `C1`–`C14`, `D1`–`D15`, the M trinaries and amount/velocity features → **64-d L2-normalised behaviour vector per transaction** |
| `03_extract_policy.py` | The dataset README split into **41 citable chunks**: 10 policy rules, 8 policy sections, 5 typologies, 17 regulatory references, 1 guidance block |
| `04_build_memory.py` | 5,565 narrative vectors + 41 policy vectors, 384-d |
| `05_calibrate.py` | The measured likelihood-ratio table — see §7 |
| `06_stage_graph_csv.py` | The CSVs the TigerGraph loading jobs consume |
| `07_verify.py` | 14 checks; non-zero exit on failure |

Rank normalisation rather than z-scores throughout: IEEE-CIS outliers are brutal
enough that a z-score is meaningless on several of these columns.

### What the closed cases told us

Measured, not assumed:

- **Every affected transaction precedes `opened_at`.** In all 5,565 cases the
  last transaction of the episode is at least one hour before the alert. So
  `as_of` can be a hard wall with no loss.
- Episode sizes: median 1 transaction for card-not-present, 2 for account
  takeover, 4 for the structuring typology, 17 for card testing. This is the
  sanity check the episode builder is written against.
- Cleared cases carry `exposure_usd = 0`, and the confirmed ones have
  `exposure == sum(amounts)` exactly.
- Analyst notes are templated, which makes them clean training signal — and
  makes the nine `undocumented` ones readable as two distinct typologies.

---

## 4. Graph model and the GSQL toolkit

Two subgraphs in one store. The **transaction subgraph** is the evidence
surface; the **case subgraph** is what the agent writes and what a judge can
walk.

`CO_OCCURS_WITH` is a derived Card ↔ Card projection through shared device
profiles, carrying `weight`, `shared_device`, the window and `via_anon_proxy`.
It collapses a four-hop path into one. Profiles used by more than 150 cards over
six months are excluded at build time — those are "Windows | Windows 10 | chrome
63.0 | 1920x1080", not devices, and projecting them produces a hairball where
every card connects to every other card.

Eleven query files. The two that carry the project:

**`hybrid_case_recall.gsql`** — vector search over case narratives fused with a
graph traversal to the cases that touched the same entities, in one statement,
with `as_of` enforced on *both* legs. The graph leg saturates
(`1 - exp(-0.6 × shared)`) so one busy device profile cannot dominate.

**`fraud_proximity.gsql`** — a distance-decayed count of confirmed-fraud closed
cases around the entities under investigation. This is what turns four months of
static history into a live graph signal that feeds the ledger as a likelihood
ratio, rather than as documents to paste into a prompt.

GDS runs **offline** through the 4.x `GDBMS_ALGO` package (the 3.x `tg_*`
queries do not install on 4.2): WCC and PageRank over `ANON_CO_OCCURS`, the
anonymous-proxy slice of the card projection, write `community_id` and
`hub_rank` onto `Card`. Over the full projection WCC finds one 6,125-card
component held together by ordinary browser strings; over the slice it isolates
the HHG-014 ring as a 54-card component with the case's card ranked #2. The agent
reads the result through `card_community` and cites it as all-time context next
to the time-bounded ring evidence; it never enters the probability.

---

## 5. Two backends, one contract

`graphstore/base.py` defines the tool surface. Two implementations:

- **`tigergraph.py`** — the production path. Every read calls an installed GSQL
  query; every write goes through RESTPP upserts plus `case_write_links`.
- **`local.py`** — a mirror over the staged parquet, computing the identical
  answers.

The mirror is not a toy. It exists so the benchmark is reproducible without an
instance, so the GSQL can be differentially tested against a reference, and so a
judge can clone and run. `GRAPH_BACKEND=auto` picks TigerGraph when credentials
exist and falls back with a printed warning when the workspace is unreachable —
an auto-stopped Savanna workspace cannot kill a demo.

**The sliding-window matchers live in one shared module** (`matchers.py`), used
by both backends. Card testing and threshold structuring need an ordered scan
with carry, which GSQL expresses badly and Python expresses in a dozen lines. So
the graph does the selective retrieval — what a graph is good at — and the
window logic is written once, which is what keeps the two backends answering the
same question rather than merely similar ones.

### Performance work

The first calibration replay projected **70 minutes**. Three fixes took it to
~25:

| fix | effect |
|---|---|
| pandas 3 stores strings in Arrow; positional `take` on an Arrow column costs ~5 ms per slice. Converting to NumPy-backed object columns at load. | 746 → 347 ms/case |
| Capping `shared_entity_ring` at the 8 most-used device profiles per card — a busy card touches dozens, and each fan-out is a real traversal. | included above |
| Memoising card slices and device fan-outs per `(card, as_of)`; one investigation asks for the same window a dozen times. | 347 → 177 ms/case |
| Replacing the per-call 5,565-iteration Python loop in `behavioural_neighbours` with a precomputed flattened table and a masked matrix product. | included above |

---

## 6. The deterministic core

Everything a bank would have to justify lives in `core/`, which **cannot import
an LLM**. `tests/test_core.py::test_core_cannot_import_an_llm` walks the AST of
every file in that package and fails the build if `anthropic`, `openai`,
`langchain`, `langgraph`, `transformers` or anything with `llm` in the name ever
appears.

| Module | Responsibility |
|---|---|
| `hypotheses.py` | Seven competing explanations — exactly the enum the answer file is scored on, so nothing is lost in a mapping step |
| `signals.py` | 26 computed observations, each with the claim an analyst would write, the query that produced it, and the entity ids it rests on |
| `evidence_ledger.py` | Bayesian update in log space; measured / structural / solicited sources; reliability damping; contradiction detection; the 0.97 confidence ceiling |
| `policy_engine.py` | R1–R10, §3a, §6 as pure functions, each carrying its verbatim clause text loaded at runtime from the extracted corpus |
| `permissions.py` | The action catalogue and approval routing, transcribed from policy §1–§2 |
| `voi.py` | Expected entropy reduction per unit of **friction**, with the policy gate applied to *asking* |
| `stopping.py` | Two-sided rule: decisive, or exhausted |
| `episode.py` | Which transactions belong to the episode, selected by mechanism |
| `ledger.py` | Hash-chained decision log with tamper detection |

Design decisions worth stating:

- **`pattern` is the hypothesis space.** Modelling "fraud yes/no" and mapping to
  a typology afterwards loses exactly the information the answer file is scored
  on.
- **The prior is conditioned on the trigger, not on the risk score.** The README
  is explicit that above 0.70 most flagged transactions are legitimate, and the
  score is the variable that *selected* the alert — using it as evidence double
  counts it.
- **Reported probability is capped at 0.97 / 0.02.** No investigation on this
  evidence is certain, and `fraud_probability` is explicitly scored for
  calibration. The ceiling sits above the 0.85 action threshold, so it never
  changes an action.
- **The exhaustion branch of the stopping rule is the interesting one.** Almost
  any agent stops when confident. Stopping because *further investigation would
  not repay its friction* is a different and more defensible claim.

---

## 7. Calibration: what measuring actually found

This section is the honest part of the build, and the one I would point a judge
at first.

### Bug 1 — the episode teaches its own baseline

First replay: `known_device_and_region` measured **LR 3.51 toward fraud**.
Meaning: a transaction on an established device in an established region is
three and a half times more likely to be fraud.

Partly this was a real defect. The "flagged" transaction of a multi-leg fraud
episode was being compared against a baseline that *included the earlier legs of
the same episode*. The first fraudulent transaction teaches the baseline that
the new device is normal, and by the fourth one nothing looks unusual.

**Fix:** anomaly is measured as suspect window against established baseline,
with the baseline cut at `as_of − 72h`. Seventy-five percent of closed-case
episodes open within 29 hours of their alert.

It helped. It did not fix the inversion, which meant the inversion had another
cause.

### Bug 2 — the closed-case file is not a sample of alerts

Second replay, clean baselines: `known_device_and_region` **LR 3.30**,
`amount_typical` **2.63**, `device_new_on_account` **0.28**. Held-out accuracy
**93%**.

The accuracy was real and the model was inverted, which is the combination worth
remembering.

Every *cleared* case in the history got there by scoring high on the bank's
model — a travel trip, a new phone, an unusual but genuine purchase. Every
*confirmed* case got there because a cardholder rang up, and those are often
small and unremarkable. So inside that file "looks anomalous" genuinely predicts
**cleared**. The measurement was right; the population was wrong.

**Fix:** a third stratum the file does not contain — ordinary transactions from
the same four months that no investigation ever touched. Months 1–4 were fully
worked by the bank's analysts, so an untouched transaction there is a usable
negative.

### Bug 3 — unmatched negatives are confounded by card tenure

Adding untouched negatives brought `known_device_and_region` to **LR 1.56**.
Still pointing the wrong way.

The residual confound is the card, not the transaction. Confirmed-fraud cases
sit disproportionately on long-lived, busy cards, which have more history and
therefore more established devices and regions.

**Fix:** a matched control design. Each confirmed-fraud case is paired with
another transaction **on the same card**. The card-level confound cancels
exactly, and the calibration now answers the question an analyst actually asks:
what is different about *this* transaction compared with the rest of this card's
behaviour?

### What else the calibration is careful about

- **Two features are excluded from the learned tables as selection variables.**
  `customer_disputed` is perfectly confounded with outcome in the history (every
  cleared case is risk-score triggered, every confirmed one is
  customer-reported), so its learned LR would be infinite and the agent would
  stop investigating and read the trigger. `risk_score_high` is the variable
  that decided which transactions became alerts. Both enter as a
  trigger-conditioned prior instead.
- **Alerts before 2016-07-20 are skipped.** The dataset opens on 2016-07-02, so
  the first fortnight has no established baseline to be anomalous against.
  Calibrating on them teaches the model that fraud has no signature.
- **The class prior is an operating prior, not the historical one.** The closed
  file is 84% fraud because it *is* a case file.
- **The damping exponent is fitted on a temporal holdout** (train July–September,
  test October), not tuned by eye. It applies to the structural likelihood ratios
  too, because they are not independent of the measured ones — a structuring
  burst also registers as a velocity burst and as an online burst, and undamped
  they compound into a posterior of 1.00 that no evidence set here earns.

### What the corrected calibration actually showed — and why that is the result

With both corrections in, the measured likelihood ratios mostly sit near 1, and
held-out fraud-vs-not accuracy is 0.57 against 0.93 for the biased version.

That is the honest number, and it is worth being direct about what it means:
**this history cannot teach P(fraud | graph signals).** Every confirmed case in
it was found by a cardholder ringing up; every cleared case was found by the
bank's model scoring a transaction highly. Fraud did not enter that file because
it looked anomalous. So once the trigger is removed as a feature — which it must
be, since it is perfectly confounded with the outcome — the graph signals
separate confirmed fraud from ordinary activity on the same card barely better
than chance.

The 0.93 was the artefact. The 0.57 is the data.

What the history *does* teach is still substantial, and it is what the agent
runs on:

| what it teaches | strength | where it is used |
|---|---|---|
| `P(signal \| pattern)` among confirmed frauds — *which* typology, given fraud | strong | the naive-Bayes tables |
| the two undocumented typology signatures | near-deterministic | hard matchers in `STRUCTURAL_LR` |
| base rates by trigger type | strong | the operating prior |

The class-conditional table discriminates cleanly where it matters:
`device_new_on_account` is 0.85 under card-not-present-from-a-new-device and
0.001 under out-of-region use; `match_flag_anomaly` is 0.56 under out-of-region
and 0.001 under card-not-present; `online_burst_2_to_4` is 0.43 under both
card-not-present typologies and 0.001 under out-of-region.

The alternative was to keep the 0.93 and not look too closely. The reliability
curve would have looked excellent right up until the agent cleared a real fraud
because it was small and unremarkable, which is what most fraud in this dataset
is.

One override is applied on top of the measurement and should be named as such.
`matches_cleared_alert_template` — a risk-score alert resting on one isolated
anomaly with no structural corroboration — carries a hand-set likelihood ratio
of 5.0 toward *legitimate*, while the matched-control measurement puts it at
1.46 toward fraud. The override is justified against the population that
actually matters: all 900 cleared investigations in the history are risk-score
alerts of exactly that shape, and only 55% of confirmed frauds share it, so
among *alerts* the ratio runs the other way. The measurement cannot see this
because matched controls are ordinary transactions, not alerts. It is a
judgement call, it is documented in `eval/reports/calibration.md`, and it is the
single largest hand-set number in the system.

### And a fourth: ring detection on a fingerprint, not a device

The first ring detector fired on half the benchmark. A "device profile" here is
a `DeviceInfo | OS | browser | screen` string — **92% of online transactions sit
on a profile shared by three or more cards**. Counting cards finds nothing.

The discriminator is the **anonymous-proxy ratio**:

| profile | cards | via anonymous proxy | ratio |
|---|---:|---:|---:|
| `SM-G935F \| Android 7.0 \| chrome 62.0 \| 1920x1080` | 52 | 52 | **1.00** |
| `Windows \| Windows 10 \| chrome 65.0 \| 1920x1080` | 300 | 9 | 0.03 |
| `Trident/7.0 \| Windows 10 \| ie 11.0 \| 1920x1080` | 253 | 14 | 0.06 |

A hub fires on ratio ≥ 0.5 with ≥ 3 anonymous cards, or on a rare profile
(≤ 60 cards all-time) appearing brand new on ≥ 8 accounts in one window.

---

## 8. The agent

LangGraph, typed state, one conditional edge, loop capped **in code**:

```
trigger_intake → case_opener → evidence_planner → graph_retrieval
  → memory_recall → policy_grounding → ledger_update → uncertainty_assessor
       ├─ enough ──→ action_recommender → permission_gate → explainer
       │                → case_writer → memory_consolidator
       └─ not enough → record_provisional → evidence_gap_resolver ─┐
                              ↑  (max 3 rounds)                    │
                              └────────────────────────────────────┘
```

`record_provisional` is the node the submission format forces to exist: the
recommendation committed **before** any evidence is requested. Without it there
is no honest "before".

Notes on decisions inside the agent:

- **The planner's plan is recorded, and the full toolkit runs anyway.** The
  primitives are cheap, and a planner that can silently skip the ring query is a
  planner that can silently miss a ring.
- **No checkpointer.** The state carries live objects — the ledger, the hash
  chain, the investigation context — that a msgpack serialiser cannot round-trip.
  Flattening them purely to satisfy a checkpointer would cost more than it buys,
  so the reasoning trace the console streams is built explicitly and is the same
  record that lands in the answer file.
- **The simulator never sees a label.** Responses are sampled deterministically
  from the agent's own predictive distribution, seeded from the case identity —
  which introduces no information the agent did not already have, so the loop
  cannot manufacture accuracy. What it does test is whether the recommendation
  *moves* correctly when evidence lands. Silence is a modelled outcome with its
  own likelihood ratio.
- **The permission gate checks twice.** Once in the gate, once inside the
  simulated action service. A control enforced at one call site is not a control.

---

## 9. Answer files and schema discipline

`report/answer.py` builds the submission JSON and the graph payload from the
same state object, so the file and the graph cannot disagree.

`validate()` runs on every case before anything is written, and checks the
things the dataset says score zero:

- every required field at every level
- enum values for `status`, `verdict`, `pattern`, `route`, evidence `source`
- `fraud_probability` in range
- `pattern_description` present iff `pattern == "undocumented"`
- legitimate verdict ⇒ no affected transactions, zero exposure, no SAR
- `sar.file` agrees with whether `FILE_REPORT` is in the final actions
- SAR narrative long enough to stand on its own; empty SAR fields when not filing
- `sar.total_amount_usd` equals `case.exposure_usd`
- **every id exists in the dataset** — transactions, cards and prior case ids all
  checked against the real key sets, because "made-up IDs score zero"

Each file also carries an `agent_record` block beyond the required schema: the
full posterior, per-evidence belief movement, the VoI ranking *including the
actions the policy forbade*, the hash-chained ledger, the counterfactual, and
the complete trace.

---

## 10. The console

FastAPI serving one HTML file, one stylesheet, one script. No build step, no
bundler, no `node_modules`, so `python ui/server.py` is the whole deployment
story.

Six pages: Home (the five-step story, live counts, three "start here" cases),
Cases (search and dropdown filters; per case an Overview with gauge, entropy in
bits, open questions and the before → question → after journey; Evidence with
claim-type badges; a zoomable Graph tab; Similar cases; an Audit trail with a
replay stepper, the hash-chained ledger and the graph read-back checks),
Scoreboard (all 20 with audit status, sortable, CSV), Approvals (writes
`APPROVED_BY`), Monitoring (the autonomous sweeps compared) and Insights
(calibration, searchable policy). The status pill says whether the graph is
reached through MCP, directly, or not at all.

---

## 11. Enhancements beyond the brief

| # | Enhancement | Why it is worth the code |
|---|---|---|
| 1 | **Two undocumented typologies mined from the closed cases** | The dataset says they exist. Both appear in the benchmark (HHG-006, HHG-014) |
| 2 | **Matched-control calibration** | Without it the agent is confidently inverted — see §7 |
| 3 | **Anonymous-proxy ratio as the ring discriminator** | Raw device fan-out fires on 92% of online transactions |
| 4 | **Behaviour embeddings over `V1`–`V339`** | Turns 339 unusable columns into a retrieval key |
| 5 | **Clean-baseline episode windowing** | Stops a fraud episode normalising itself |
| 6 | **Hash-chained decision ledger** | Audit trail that is checkable, not merely present |
| 7 | **Confidence ceiling** | `fraud_probability` is scored for calibration; 1.00 is a missing error bar |
| 8 | **Policy gate on evidence requests** | Contact fatigue is a real control; it belongs in code, not in a prompt |
| 9 | **Counterfactual on every case** | Answers "what would change your mind" in ten lines |
| 10 | **Autonomous monitor with three triggers** | Two of them find cases the bank's model does not score highly at all |
| 11 | **Dual backend with shared matchers** | Reproducible without an instance; differentially testable |
| 12 | **Schema validator in the runner** | Catches what would silently score zero |
| 13 | **Runs with no API key** | A judge can reproduce the twenty files with zero credentials |
| 14 | **Peer-purchase ring signal** (`peer_purchases.gsql`) | Rings that are invisible from one card; LR 22.4 measured on the closed cases |
| 15 | **R7 regular-cadence recurrence** | A charge paid 21 times every one to three weeks is a habit, not only a monthly one |
| 16 | **Verified write-back** | `written_to_graph` means the case read back, with counts checked |
| 17 | **ID-grounded LLM prose** | Text citing an identifier the evidence lacks falls back to the template |
| 18 | **Claim types and open questions** | Facts, inferences, scores and simulated replies are never confused |
| 19 | **Fail-closed strict mode** (`GRAPH_STRICT=1`) | A demo can never present mirror results as graph results |
| 20 | **Committed answer audit** (`eval/audit_answers.py`) | Every policy rule and data invariant, re-checkable in one command |
| 21 | **Scoreboard and monitoring views** | The whole benchmark and the proactive sweeps on one screen each |

---

## 12. Requirement-by-requirement traceability

| Brief requirement | Implementation |
|---|---|
| Trigger: risk score / customer report / analyst request | `trigger_from_row`; prior conditioned per trigger in `trigger_prior` |
| Investigate: graph, history, device, behaviour, prior cases | 21 installed GSQL queries; 28 signals in `core/signals.py` |
| Assess: pattern, type, risk level **with a confidence number** | `fraud_probability` + full 7-way posterior |
| Create and progress a case; maintain decisions | `FraudCase` subgraph; `DecisionLedger`; `case_chain()` read-back |
| Case memory that informs new investigations | `hybrid_case_recall` + `fraud_proximity` + measured LRs |
| Controlled evidence gathering, policy-approved | `core/voi.py`, policy gate on asking, `simulator.py` |
| Next best action, one or more, with approval route | `policy_engine.evaluate` → `permissions.route` |
| **Before and after** evidence | `record_provisional` / `action_recommender` → `initial` / `final` / `what_changed` |
| Only authorised actions executed | `may_execute`, enforced in the gate and in the service |
| Determine when to stop | `core/stopping.py`, two-sided, recorded in `stop_reason` |
| Explain evidence, uncertainty, why these actions | `report/narrative.py::explanation` + policy notes |
| TigerGraph for graph **and** vector | one store, three vector attributes, `hybrid_case_recall` |
| GSQL and graph algorithms | `graph/queries/`; GDS WCC + PageRank via `GDBMS_ALGO` in `graph/algorithms/05_graph_algorithms.gsql` |
| TigerGraph MCP | `graphstore/mcp_client.py` runs the official `tigergraph-mcp` server over stdio; every agent read (`run_installed_query`, `get_node`, `get_node_edges`) and case write (`add_node`, `add_edge`) goes through it, with a per-call fallback to a direct connection |
| GraphRAG | `policy_retrieve` over 41 clause chunks; the LLM gets clauses, not raw rows |
| User interface | `ui/` |
| Case written to the graph | `write_case` + `case_write_links`, same payload as the JSON, verified by `case_chain` read-back |
| SAR where policy requires | `sar_required` implements §3a exactly; validated for agreement |

---

## 12a. Results

### The twenty benchmark cases

| | |
|---|---|
| verdicts | 11 legitimate, 9 fraud |
| patterns | 11 `none`, 4 `card_not_present_new_device`, 2 `undocumented`, 2 `account_takeover`, 1 `out_of_region_use` |
| SARs filed | 2 (HHG-006, HHG-014) |
| evidence requested | 5 cases |
| recommendation changed after evidence | 5 cases |
| schema validation | 20/20 pass |
| answer audit | 0 issues (`eval/reports/answer_audit.md`) |
| graph path | TigerGraph via MCP: 1,492 calls, 0 fallbacks; ~4 s and ~38 graph calls per case |

Both undocumented typologies appear and are caught: **HHG-006** is sub-threshold
structuring ($1,906.07 across four purchases in thirty minutes) and **HHG-014**
is the shared-device ring (19 connected cards, anonymous-proxy ratio 1.00).
**HHG-019** and **HHG-011** are rings visible only on other cards (peer
purchases): fraud at 0.95 and 0.97 and blocked, but no SAR — $99.92 and $131.30
on one card with a documented pattern meet none of §3a's conditions, and the
peers are evidence, not a proven shared origin. **HHG-018** is a disputed
recurring charge closed under R7.

### October holdout backtest

400 alerts, replayed twice — once with the trigger each alert actually had, once
with the trigger stripped. See §7 for why one number would have been misleading.

| | as seen | graph only |
|---|---:|---:|
| **AUC** | **0.921** | **0.520** |
| precision / recall | 0.891 / 0.967 | 0.637 / 0.209 |
| Brier / ECE | 0.0825 / 0.036 | 0.4951 / 0.4966 |
| **pattern accuracy, both sides agree it is fraud** | **0.508** (n=236) | **0.471** (n=51) |
| affected-transaction overlap (Jaccard) | 0.587 | 0.141 |
| SAR agreement with the bank's own filing | 0.900 | 0.907 |

The two rows at the bottom are the ones that matter, and they are the result I
would put first. Fraud-versus-not collapses when the trigger is removed — AUC
0.921 to 0.520, essentially chance — but **pattern accuracy barely
moves (0.508 to 0.471) and SAR agreement does not move at all (0.900 to
0.907)**.

These figures come after the R7 cadence rule was tightened and `peer_purchases`
made fired-only (§14). An earlier build scored higher on paper (AUC 0.936,
pattern 0.573) with a looser R7 rule that the holdout showed was clearing
confirmed fraud whose amounts happened to repeat in a burst; the lower number is
the honest one.

That is a clean division of labour, and it is measured rather than asserted:

* **the trigger decides *whether*** — a cardholder ringing up is the single most
  informative fact available, and it is why fraud is in the file at all;
* **the graph decides *which typology*, *how far it goes*, and *whether to
  file*** — and it does that just as well without knowing how the alert arrived.

Six pattern classes; always guessing the majority would score 0.26.

**What `peer_purchases` is worth, measured.** The same calibration and backtest
rerun with the detector forced off (`SIGNALS_OFF=peer_purchases`):

| | with | without |
|---|---:|---:|
| graph-only precision / recall | 0.637 / 0.209 | 0.608 / 0.184 |
| graph-only Brier | 0.4951 | 0.5083 |
| as-seen pattern accuracy (all fraud) | 0.492 | 0.488 |
| as-seen precision / recall | 0.891 / 0.967 | 0.891 / 0.967 |

It adds six graph-only true positives (51 against 45) with no extra false positives (29 either way),
and leaves the as-seen arm untouched. Small, but measured, and in the direction
that matters: evidence the trigger doesn't already carry.

### Autonomous monitoring (outside the benchmark)

The agent raised its own alerts across November and December from three
triggers, then investigated all of them under the same policy:

| found_by          |   alerts |   fraud |   mean_p |   exposure |
|:------------------|---------:|--------:|---------:|-----------:|
| device_hub_sweep  |       27 |      24 |    0.825 |    3396.39 |
| risk_score        |       30 |       6 |    0.224 |   16520.3  |
| structuring_sweep |       30 |      30 |    0.945 |   38145.7  |

The bank's own model, at its thirty highest scores in the exam period, yields
**6 fraud**. The sub-threshold structuring sweep yields **30 of 30**, worth
$38,145.65, none of which the risk model
scores highly — because every individual leg is an ordinary purchase and the
pattern only exists across the burst. That is the case for doing this in a
graph.

---

## 13. Known limits and what I would do next

Stated plainly, because a limits section that lists nothing real is not a limits
section.

1. **The R7 reply and the peer-signal gate are assumptions.** The simulated
   recognition of a recurring charge follows R7's own premise, because the
   history holds no recurring disputes to learn from; the "rare device" cut-off
   (≤ 10 cards) is chosen, while the signal's weight is measured. Both are
   written into the answer files.
2. **Memory does not yet close the loop on weighting.** Cases the agent writes
   are retrievable by the next investigation, but the likelihood-ratio table is
   not recomputed from them. Memory that updates the agent's *evidence
   weighting*, not just its retrieval, is a materially stronger claim than the
   one currently made.
3. **The 72-hour episode window is a fitted constant, not a model.** A
   changepoint model over the card's own activity would be better and is not
   hard.
4. **Ring propagation stops at monitoring.** When the hub typology fires, every
   connected card is a case waiting to be opened. Right now they are placed under
   monitoring, which is what the policy requires, but not investigated.
5. **The simulated responder cannot validate response realism.** It is honest —
   it uses only information the agent already has — but that means the
   before/after loop demonstrates correct *movement*, not correct *outcomes*.
   Real responses would change the measured numbers.
6. **GDS output is context only.** WCC and PageRank see the whole six months,
   so they are cited beside the evidence and never weighed; a time-sliced
   projection per alert would let them count.

---

## 14. What other teams' designs taught us

After the first submission-ready build, ten other teams' technical write-ups for
the same brief were read end to end. Most ideas were already here (a
deterministic policy engine, VoI-driven evidence requests, a temporal wall,
case memory in the graph). What was worth taking, and what was checked against
the data before anything changed:

| Idea (from) | Checked how | What changed |
|---|---|---|
| HHG-018 is a forgotten recurring charge, R7 (three teams) | 21 identical $39.07–39.08 product-W charges since July, never more than 21 days apart | R7 matcher accepts a regular cadence; the simulated reply follows R7; verdict legitimate, no block |
| "What happened on other cards?" (SentinelGraph) | HHG-019 and HHG-011: rare devices with near-identical purchases on two other cards within days; generic strings excluded | `peer_purchases` query + signal, LR 22.4 measured on 31 fraud / 0 cleared closed cases. **Fired-only** (its absence is not evidence) and its peers are **evidence, not connected cards** — the holdout showed both mistakes |
| Read the case back before claiming it was written (FraudLens, BROTHERHOOD) | `case_chain` returns every linked vertex | `written_to_graph` = read-back; counts checked and shown in the audit trail |
| Reject LLM text citing IDs not in the evidence (SentinelGraph) | Regex over case, card, customer and transaction IDs | `grounded()` on every LLM-written field |
| Observed fact vs derived inference vs model score (BALLERINA) | Mapped from each ledger entry's source | `claim_type` on every evidence item; filter and badges in the console |
| Explicit open questions (SentinelGraph, BROTHERHOOD) | Derived deterministically from the case state | `open_questions` in every answer file |
| Uncertainty as a quantity (RAVEL's entropy) | Binary entropy of the final posterior | Shown in bits beside the gauge |
| Fail closed when the graph is down (BALLERINA) | — | `GRAPH_STRICT=1` |
| Scoreboard / executive matrix (RAVEL, SentinelGraph) | Built on the audit | Scoreboard page + CSV |

Considered and not adopted: a gradient-boosted prior (the closed cases' trigger
is perfectly confounded with the label, see §7); leaving `fraud_probability`
null (it is a scored field, and ours is calibrated and capped); a second, custom
MCP server (the official one already exposes installed queries, and one path is
easier to audit than two).

---

## Appendix — reproducing this build from nothing

```bash
python -m pip install -r requirements.txt
# put the HHGOA dataset in Datasets/

python ingest/01_normalise.py
python ingest/02_behaviour_embeddings.py
python ingest/03_extract_policy.py
python ingest/04_build_memory.py
python ingest/05_calibrate.py
python ingest/07_verify.py

python -m pytest tests -q
python benchmark/run_20.py
python eval/backtest.py
python ui/server.py
```

With TigerGraph credentials in `.env`, add:

```bash
python ingest/06_stage_graph_csv.py
python graph/install.py --step all
```

and every command above runs against the database instead of the mirror.
