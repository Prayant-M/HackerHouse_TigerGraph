# Agentic Fraud Investigation on TigerGraph

**TigerGraph × Hacker House Goa 2026 — Agentic Fraud Investigation (HHGOA)**

An agent that investigates a fraud alert, opens a case as a first-class graph
object, decides what it does not yet know, asks one well-chosen question, and
revises its recommendation when the answer arrives — under a bank policy it
cannot talk its way past.

```
Trigger ──▶ Open case ──▶ Investigate the graph ──▶ Recall prior cases
                                │
                    ┌───────────▼───────────┐
                    │  Is this defensible?  │
                    └───────┬───────────┬───┘
                        no  │           │  yes
       ┌────────────────────▼──┐     ┌──▼────────────────────┐
       │ PROVISIONAL action    │     │  Recommend + route    │
       │ + approval route      │     │  + explain + stop     │
       │ ↓                     │     └──┬────────────────────┘
       │ Pick the question with│        │
       │ most information per  │        │
       │ unit of friction      │        ▼
       │ ↓ response ──────────────▶ REVISED action + what changed
       └───────────────────────┘
```

Everything that has to be defensible — the risk arithmetic, the policy, the
approval routing, the stopping rule — is deterministic Python that **cannot
import an LLM**, and a test fails the build if that ever changes. The model
plans, synthesises and explains. The graph decides.

**At a glance:** TigerGraph Savanna 4.2.5 · 590,742 transactions · 21 installed
GSQL queries reached **through the TigerGraph MCP server** · TigerVector GraphRAG ·
GDS WCC + PageRank · 11 legitimate / 9 fraud / 2 SARs / 5 decisions changed after
evidence · 20 / 20 answers audit-clean · 64 tests.

**Live console (read-only):** [prayant-fraudgraph-console.static.hf.space](https://prayant-fraudgraph-console.static.hf.space), all twenty
investigations, no install. Live re-runs need the repository and a workspace.

**Diagrams:** final round — sixteen detailed diagrams in [`docs/architecture/`](docs/architecture/README.md); Round 1 — eighteen architecture diagrams (system, agent loop, MCP path, schema,
GraphRAG, decision authority, ring detection, case lifecycle, R7 walkthrough,
pipeline, temporal wall, trust boundaries, policy rules R1–R10, all twenty
benchmark cases, console and API, autonomous monitoring, evaluation, failure
modes) live in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) as Mermaid,
rendered by GitHub, and as an interactive page:
[FraudGraph Blueprints](https://claude.ai/artifact/VioVT79phoeLTjBKkMWRvb). PNG exports of all eighteen are in
[`docs/diagrams/`](docs/diagrams/); a dev.to-ready post is in
[`docs/DEVTO_POST.md`](docs/DEVTO_POST.md).

---

## Final round — can a bank run it?

Round 1 asked whether the agent can investigate. The final round asks whether a
bank can run it: faults injected live, hostile text, wrong-role approvals, a
January the bank's model has never seen, and nine legitimate customers in
eighteen cases who must not be blocked. Everything below is reproducible from
this repository and every number in this block is regenerated from the last run
by `scripts/readme_numbers.py`.

<!-- numbers:start -->
- **18 cases** answered by `benchmark/run_case.py --all` on backend `tigergraph`: verdicts {'legitimate': 10, 'fraud': 7, 'uncertain': 1}; 7 carry a block or report; the proof gate changed the action on **1** (HHF-016).
- p95 latency **283.6 s**, mean 248.7 s; 380 LLM tokens and $0.0018 per case; 199 attestations in total.
- hostile text flagged on 6 cases; data-quality taint on 5.
- **Proof gate (October holdout, 2015 replays, fitted on Jul–Sep):** harmful-action error rate 0.3591 at margin k=1 vs 0.1613 at k≥2; legitimate customers acted against 70 → 5, frauds acted on 142 → 26. Gate claimed: **yes**.
- **Conformal (α=0.1):** October coverage 0.8605 overall (fraud 0.8111, legit 0.9377), mean set size 1.754.
- **Metamorphic relations** (violations/runs): M1 0/18, M2 0/720, M4 0/18, M5 0/90, M6 0/18, M7 0/18.
- **Predictive containment** (80 rings, origin found on 38): origin-lift precision 0.2642 (lift 3.57×) on 246 free step-ups vs raw counts 0.0392 (lift 0.53×); zero blocks on innocents.
- **Evasion attacks:** 3 evaded before hardening, 0 after; hardening's legitimate cost on the history: 67.
- **Drills:** 11/11 pass (`eval/reports/drills.md`).
- **Attestation re-run:** 18 of 18 answer files pass.
<!-- numbers:end -->

**The one idea to judge: proof-carrying verdicts** ([`docs/INNOVATION.md`](docs/INNOVATION.md)).
The decision core is a pure function, so every answer ships a *computed* proof:
the minimal set of attested facts that forces the action, the smallest set whose
removal flips it (margin *k*), and how the bank ruled on closed cases with those
facts (an installed GSQL bitmask query, `precedent_by_facts`). A block or report
resting on *k* = 1 or contradicted by precedent is downgraded to verify +
escalate before anyone is wronged. The console's **Proof** tab flips any fact
live.

| Layer | What it adds | Where |
|---|---|---|
| Proof + gate (Innovation 1) | minimal facts, flip set, precedent, one-way gate | `core/proof.py`, `eval/proof_holdout.py` |
| Predictive containment (Innovation 2, C7, C1) | time-sliced ring, compromise origin by lift vs controls, at-risk cards protected with free actions only, harm-aware block set, `COMPROMISE_POINT` write-back read by later cases | `core/containment.py`, GSQL `ring_at_asof`, `origin_counts`, `origin_touchers`, `ring_exposure`, `compromise_watch` |
| Label-free evaluation (Innovation 3, C10) | metamorphic relations M1–M7, 40-template hostile-text fuzz, naive-LLM baseline, evasion-frontier attacks | `eval/metamorphic.py`, `eval/attacks.py`, `eval/naive_llm_baseline.py` |
| Conformal abstention (Innovation 4, C11) | coverage-guaranteed "uncertain", support check, data-quality taint | `core/conformal.py`, `core/quality.py` |
| Harness | fail-closed with signed FAILED_DEPENDENCY, recorded tool I/O + replay/diff, tip-off by construction, future-dated canaries, signed hash-chained server-side approvals, hostile-text firewall, redaction + egress log, least-privilege single write path | `benchmark/run_case.py`, `agent/recorder.py`, `report/customer_text.py`, `governance/`, `core/text_facts.py`, `graph/queries/case_write.gsql`, `graph/rbac.gsql` |

**TigerGraph is the source of truth.** 34 installed GSQL queries on Savanna 4.2.5
reached through the TigerGraph MCP server (client-side tool allow-list; no
`add_node`/`add_edge`), TigerVector hybrid recall fused with traversal in one
query, GDS WCC/PageRank plus a time-sliced WCC that *does* change output, the
case written back through one installed query (`case_write`) and read back
(`case_chain`) before the answer says `written_to_graph: true`, compromise
points written as edges and read by later investigations, approvals and
detector/schema approvals written through a separate console-only query, and a
least-privilege `agent_role` (EXECUTE on the investigation queries and
`case_write` only). Backend parity: 9 tests agree between the mirror and live
TigerGraph.

**One command:** `make case CASE=HHF-007` (Windows: `.\make.ps1 case -Case HHF-007`)
— exit 0 answer written · 1 failed validation (nothing written) · 2
FAILED_DEPENDENCY (signed record, previous answer untouched) · 3 invalid input.
Also `make twice`, `make replay`, `make diff`, `make drills`, `make attest-verify`,
`make canary`. The January files drop into `Datasets/` (or `Datasets/final/`):
`make drift` gates them behind a fraud-manager approval, the loaders read every
month present, and `case_pack_final.csv` is picked up automatically.

### Judges: run it on your own dataset (any schema)

```bash
make byo-map DATA=path/to/your_folder NAME=judge1   # mapping proposal with evidence, nothing applied
make byo     DATA=path/to/your_folder NAME=judge1   # map -> validate -> transform -> ingest -> run every case -> grade
# Windows: .\make.ps1 byo -Data path\to\your_folder -Name judge1
# Approve with a token instead of the operator flag:
python ingest/byo.py --input path/to/your_folder --name judge1 --token <fraud-manager token> [--graph]
```

`ingest/byo.py` needs none of our data: it maps against the bundled spec
`data/schema/canonical.json`. It identifies each file's role (transactions,
identity, closed cases, case pack) and maps every column with evidence: name
tokens and synonyms, type shape, and value overlap or quantile match with a scale
search. It detects amounts in cents, timestamps split into date + time, epoch
seconds, and numbered families under any prefix (`vesta_007`→`V7`, `cnt_03`→`C3`,
`ident_31`→`id_31`).

Guardrails:
- A file that maps onto nothing is **refused**, not guessed.
- The run stops with the field named if any of these fail: ids unique, amounts
  numeric and non-negative, timestamps parse, every case-pack transaction present,
  trigger types valid, and the row limit.
- The mapping is applied only with a fraud-manager token, or with
  `--accept-mapping`, which is recorded in the report as an operator decision.
- Everything runs in isolated folders (`Datasets/byo/<name>`,
  `data/staged_byo/<name>`, `cases_byo/<name>`, with recordings, lifecycle and
  logs scoped there too), so a judge's dataset can never overwrite the submission.

Rehearsed on a renamed and reshaped variant of our own data (`eval/make_variant.py`):
- Every required column was mapped correctly, including the card tuple matched
  by value quantiles, cents ×0.01, date + time → ts and 377 family columns.
- Three optional columns were left unmapped and reported: `distanceB` (filled
  empty), `secondsSinceStart` (re-derived from ts) and `linkedCards` (sparse).
- 3/3 cases answered, and the organisers' grader is clean (0 hard, 0 policy, 0 warnings).
- The verdicts are **identical** to the canonical run (`eval/reports/byo/rehearsal/`).

Agent guardrails, each enforced in code:
- **Free text** enters as `UntrustedText`, and the policy core's `CaseState`
  refuses to be built from it (`core/provenance.py`). Only allow-listed extractor
  facts cross; 0 of 720 hostile-text mutations changed a decision.
- **The model** has no tools, no query access and no write access. Its output is
  schema-checked, `grounded()` drops ids it invented, and `PolicyDecision.filter`
  drops actions it added. A hard timeout falls back to template prose.
- **Actions** come from a fixed catalogue with policy routes (`tests/fixtures/grader_rules.json`
  mirrors the organisers' grader). Only `auto` actions execute; L1/L2 wait for a
  server-side token role.
- **Harmful actions** need a proof margin ≥ 2 (R2 exempt), and an uncertain case
  escalates (R8).
- **Bounds**: a round cap, a wall-clock budget and a token budget.
- **Graph access** is fail-closed with signed `FAILED_DEPENDENCY` records. "Not
  found" during an outage is never reported as invalid input, and the runner
  waits a bounded time for a sleeping Savanna workspace.

Challenge write-ups, each listing only what is attested: [`docs/challenges/`](docs/challenges/).
Resilience statement: [`docs/RESILIENCE.md`](docs/RESILIENCE.md). Architecture (16 diagrams with explanations): [`docs/architecture/`](docs/architecture/README.md). Challenge-by-challenge demo guide: [`docs/CHALLENGES_DEMO.md`](docs/CHALLENGES_DEMO.md). Demo script: [`docs/DEMO_PLAYBOOK.md`](docs/DEMO_PLAYBOOK.md).

---

## Table of contents

- [What it does](#what-it-does)
- [Quickstart](#quickstart)
- [Running against TigerGraph](#running-against-tigergraph)
- [The analyst console](#the-analyst-console)
- [Repository map](#repository-map)
- [Everything a command does](#everything-a-command-does)
- [Design notes worth knowing before you read the code](#design-notes-worth-knowing-before-you-read-the-code)
- [Checking the answers](#checking-the-answers)
- [Results](#results)
- [Submission artefacts](#submission-artefacts)
- [Troubleshooting](#troubleshooting)

---

## What it does

| Capability the challenge asks for | Where it lives |
|---|---|
| Trigger from a risk score, a customer report, or an analyst request | `agent/graph.py::trigger_from_row`, prior conditioned per trigger |
| Investigate: neighbourhood, history, device, behaviour, prior cases | `graph/queries/*.gsql`, mirrored in `graphstore/local.py` |
| Assess: name the pattern, name the type, give a confidence number | `core/hypotheses.py`, `core/evidence_ledger.py` |
| Case lifecycle as a graph object, reconstructible | `FraudCase` subgraph + `case_chain.gsql`, read back after every write |
| Memory that measurably changes the output | `hybrid_case_recall`, `fraud_proximity`, measured likelihood ratios |
| TigerGraph MCP exposes the graph to the agent | `graphstore/mcp_client.py` → official `tigergraph-mcp` (stdio, 69 tools) |
| GraphRAG grounds the agent in evidence and documents | TigerVector over narratives, policy clauses, typologies; `policy_retrieve.gsql` |
| GSQL and graph algorithms | 21 installed queries; GDS WCC + PageRank in `05_graph_algorithms.gsql` |
| Controlled evidence gathering, then re-reason | `core/voi.py` + `agent/nodes.py::evidence_gap_resolver` |
| Next best action **before and after** evidence, with approval route | `record_provisional` → `action_recommender`, `core/permissions.py` |
| Explain, and say why it stopped | `core/stopping.py`, `report/narrative.py` |

Two things it does that the brief does not ask for, and that turned out to
matter:

- **It found two fraud typologies that are not in the documentation.** The
  dataset says "not every fraud pattern present in the data is documented". Both
  were mined out of the nine closed cases the bank's own analysts confirmed as
  fraud but could not categorise, and both are now hard matchers the agent runs
  on every case. See [Design notes](#two-undocumented-typologies).
- **It is calibrated against the closed cases, and the calibration caught two
  bugs that had silently inverted the whole system.** See
  [Design notes](#the-calibration-trap-that-inverts-everything).
- **It asks what happened on *other* cards.** A rare device making near-identical
  purchases on several unrelated cards within a week is a ring no single card
  shows. That signal (`peer_purchases`) fired on 31 confirmed-fraud closed cases
  and no cleared ones — the strongest likelihood ratio in the model (22.4). See
  [Design notes](#rings-you-cannot-see-from-one-card).

---

## Quickstart

### 0. Requirements

Python ≥ 3.11, ~8 GB RAM, ~4 GB disk. Nothing else — no Docker, no Node, no
database, no API key.

### 1. Install

```bash
git clone <your-repo-url>
cd <repo>
python -m pip install -r requirements.txt
```

### 2. Put the dataset in place

The HHGOA dataset is not committed (`transactions.csv` alone is 676 MB).
Download it and drop the files in:

```
Datasets/
├── transactions.csv
├── identity.csv
├── closed_cases_history.csv
├── case_pack.csv
└── README.md
```

### 3. Build

```bash
python ingest/01_normalise.py            # ~20s   card_id recovery, device profiles, baselines
python ingest/02_behaviour_embeddings.py # ~40s   64-d behaviour vector per transaction
python ingest/03_extract_policy.py       # ~1s    policy → 41 citable chunks
python ingest/04_build_memory.py         # ~2min  narrative + policy vector indexes
python ingest/07_verify.py               # ~10s   checks every artefact
```

or, in one line:

```bash
make ingest          # Windows:  .\make.ps1 ingest
```

`07_verify.py` is worth reading its output. It checks the recovered `card_id`
against the dataset's own labels, that behaviour vectors are aligned and
normalised, that the vector indexes are non-empty, and that the shared-device
ring is still intact.

### 4. Calibrate

```bash
python ingest/05_calibrate.py              # ~45min, the real thing
python ingest/05_calibrate.py --limit 900  # ~4min, good enough to see it work
```

This replays closed investigations through the **same extractor the agent uses**
and measures `P(signal | pattern)` from outcomes. Skipping it is allowed — the
agent falls back to structural priors — but the calibration is the difference
between a posterior and a guess with a decimal point.

### 5. Run the twenty benchmark cases

```bash
python benchmark/run_20.py
```

Writes `cases/HHG-001.json` … `cases/HHG-020.json`, writes each case into the
graph, and validates every file against the dataset's Answer Format before it
finishes. A non-zero exit means a file would have lost points, and it tells you
which and why.

```bash
python benchmark/run_20.py --case HHG-014     # one case
python benchmark/run_20.py --no-llm           # deterministic prose
```

### 6. Look at it

```bash
python ui/server.py        # http://127.0.0.1:8080
```

### 7. Optional but worth it

```bash
python eval/backtest.py        # replay the October holdout, write eval/reports/
python benchmark/monitor.py    # the agent raises its own alerts across Nov–Dec
python -m pytest tests -q      # 64 tests: core, policy, answer schema, backend parity
python eval/audit_answers.py   # policy + data audit of cases/ → eval/reports/answer_audit.md
```

---

## Running against TigerGraph

Everything above runs on a local mirror of the GSQL toolkit over the staged
parquet, so the pipeline is reproducible without an instance. The submission
requires TigerGraph, and the same code path runs against it.

```bash
cp .env.example .env
# set TG_HOST, TG_USERNAME, TG_PASSWORD  (see SETUP_REQUIRED_FROM_YOU.md §2)

python ingest/06_stage_graph_csv.py     # CSVs the loading jobs consume
python graph/install.py --step all      # schema, vectors, load, queries, projections, GDS algorithms, verify
python graph/install.py --from queries   # resume from any step
python benchmark/run_20.py              # now reads and writes TigerGraph
```

`GRAPH_BACKEND=auto` (the default) selects TigerGraph whenever credentials are
present and falls back to the local mirror with a printed warning if the
workspace is unreachable — an auto-stopped Savanna workspace cannot kill a demo
mid-recording.

Watch `--step verify`. TigerGraph builds the HNSW index asynchronously, so
vectors that have not finished indexing silently return nothing, and RESTPP
accepts a misspelled vector attribute name without error and hands you an empty
index. Both look exactly like "no similar prior cases found", which is the worst
possible way to discover them.

**The agent reaches TigerGraph through MCP.** `graphstore/mcp_client.py` starts
the official [TigerGraph MCP server](https://github.com/tigergraph/tigergraph-mcp)
(`tigergraph-mcp`) over stdio, and every investigation query, vertex lookup and
case write goes through its tools (`tigergraph__run_installed_query`,
`tigergraph__get_node`, `tigergraph__add_node`, …). If the server can't start,
or a call fails, the store falls back to a direct connection for that call.
`TG_VIA_MCP=0` turns MCP off. The console's status pill shows which route is live.

**Graph algorithms.** WCC and PageRank from TigerGraph's GDS library
(`GDBMS_ALGO`) run over the anonymous-proxy slice of the card co-occurrence
network. The full network is one 6,125-card component held together by ordinary
shared browser strings; the anonymous slice isolates the HHG-014 ring as its own
54-card component, with the case's card ranked #2 by PageRank. Both are all-time
structure, so the agent cites them as context in the ring evidence and never
feeds them into the probability.

Both backends implement the same `GraphStore` contract and share the same window
matchers (`graphstore/matchers.py`), so they answer the same question rather
than merely similar ones.

---

## The analyst console

```bash
python ui/server.py        # http://127.0.0.1:8080
```

No build step, no bundler, no `node_modules` — FastAPI serving one page. Light
theme, responsive down to phone width, keyboard-navigable.

| Page | What it shows |
|---|---|
| **Home** | What the agent does in five steps, live counts from the answer files, three "start here" cases |
| **Cases** | Search + dropdown filters (verdict, trigger, sort, revised, SAR). Each case has five tabs, each deep-linkable (`#/cases/HHG-019/evidence`): **Overview** (fraud gauge, uncertainty in bits, open questions, first recommendation → question → final decision, SAR with copy), **Evidence** (the probability path from the trigger's prior through every ledger entry to the final figure, belief by hypothesis, every item's measured movement, claim-type badges and filter), **Graph** (the written case subgraph; zoom, pan, click to inspect), **Similar cases** (hybrid recall scores), **Audit trail** (step-by-step replay, hash-chained ledger, graph read-back checks, full trace). **Re-run live** streams the reasoning; **⬇ JSON** downloads the answer file. |
| **Scoreboard** | All 20 decisions in one sortable matrix with each case's audit status and a CSV export |
| **Approvals** | L1 / L2 actions waiting for a person; approving writes an `APPROVED_BY` edge |
| **Monitoring** | Alerts the agent raised itself, compared by sweep (structuring, device hub, bank model) |
| **Insights** | Measured likelihood ratios; the bank policy as a searchable accordion |

The status pill reads **TigerGraph · via MCP** when the graph is reached through
the MCP server, and **Local mirror** when the workspace is unreachable.

---

## Repository map

```
ingest/                  01 normalise → 07 verify, run in order
graph/
  ddl/                   01_schema.gsql · 02_vectors.gsql
  loading/               03_loading_jobs.gsql
  queries/               the investigation toolkit, one file per primitive
  algorithms/            04_projections.gsql — CO_OCCURS_WITH + ANON_CO_OCCURS projections
                         05_graph_algorithms.gsql — GDS WCC + PageRank (GDBMS_ALGO)
  install.py             idempotent installer: --dry-run, --step, --from
src/fraudagent/
  config.py              every tunable dial, env-overridable
  graphstore/            base.py · local.py · tigergraph.py · matchers.py
  core/                  DETERMINISTIC — no LLM import may appear here
  agent/                 graph.py (LangGraph) · nodes.py · llm.py · simulator.py
  report/                answer.py (schema + validation) · narrative.py
  memory/                embeddings.py
  graphstore/mcp_client.py  agent ↔ graph through the TigerGraph MCP server
  mcp_servers/           simulated_actions.py
eval/                    backtest.py → reports/ · audit_answers.py → reports/answer_audit.md
benchmark/               run_20.py → cases/ · monitor.py → autonomous/
ui/                      server.py + static/
cases/                   ← THE SUBMISSION: HHG-001.json … HHG-020.json
docs/                    ARCHITECTURE.md (12 Mermaid diagrams) · BLOG.md
GETTING_STARTED.md       clone → dataset → run → what to check
DEMO_VIDEO_SCRIPT.md     the 3–5 minute video, shot by shot
INTEGRATION.md           the full engineering record — what was built and why
SETUP_REQUIRED_FROM_YOU.md   accounts, keys, budget, decisions
```

---

## Everything a command does

| Command | What it does | Time |
|---|---|---|
| `ingest/01_normalise.py` | Recovers `card_id` (not a column in the raw data), joins identity, builds device profiles, derives per-card baselines | ~20s |
| `ingest/02_behaviour_embeddings.py` | Incremental PCA over `V1`–`V339` + rank-normalised C/D/M → 64-d behaviour vector | ~40s |
| `ingest/03_extract_policy.py` | Splits the dataset README into 41 citable chunks: 10 rules, 8 sections, 5 typologies, 17 regulatory refs | ~1s |
| `ingest/04_build_memory.py` | Embeds 5,565 narratives + the policy corpus | ~2min |
| `ingest/05_calibrate.py` | Replays closed investigations, measures `P(signal \| pattern)`, fits damping on a temporal holdout | ~45min |
| `ingest/06_stage_graph_csv.py` | Writes the CSVs the TigerGraph loading jobs consume | ~2min |
| `ingest/07_verify.py` | Checks every artefact against the dataset's own labels | ~10s |
| `graph/install.py` | Schema → vectors → load → queries → projections → GDS algorithms → verify | ~20min |
| `graph/install.py --from <step>` | Resume from any step after a failure or a workspace nap | — |
| `benchmark/run_20.py` | **The submission.** Twenty answer files, validated | ~1min |
| `eval/backtest.py` | October holdout: precision, recall, Brier, ECE, confusion | ~10min |
| `benchmark/monitor.py` | Autonomous sweep of Nov–Dec, three trigger sources | ~5min |
| `ui/server.py` | Analyst console | — |
| `eval/audit_answers.py` | Checks every answer file against the raw data and each policy rule | ~20s |
| `pytest tests -q` | 64 tests: core, policy, R7 cadence, grounding, answer schema, backend parity | ~40s |

---

## Design notes worth knowing before you read the code

### `card_id` is not in the dataset

`transactions.csv` has no `card_id`, but the case pack and the closed cases are
expressed entirely in terms of `C01234-K1`. A card turns out to be the
`(customer_id, card2..card6)` tuple — but the `K` index is not derivable from
the tuple alone, and the obvious orderings (first-seen, lexicographic, by count)
top out around 50% agreement with the labels.

The fix is to stop guessing and *pin* it: the closed cases and the case pack
between them name the card for 14,975 transactions, so those pin their tuples
directly, and the rest are ordered by a heuristic that agrees with the labels on
94% of unpinned rows. Result: **100% agreement on every labelled transaction**,
including all twenty benchmark cases. `ingest/07_verify.py` asserts it.

Getting this wrong silently breaks every card-scoped query on half the cases,
and nothing else in the pipeline would have told you.

### Two undocumented typologies

Nine closed cases are marked `undocumented` — confirmed fraud the bank's
analysts could not fit to a pattern. Reading their narratives gives two distinct
signatures, and both appear in the benchmark:

**U1 — sub-threshold authorisation structuring.** Four online purchases inside
about forty minutes, each parked just beneath a round authorisation ceiling,
roughly $1,900 in aggregate. Invisible to per-transaction scoring because every
single leg looks ordinary. Seeded from `CC-3748`, `CC-3841`, `CC-3907`,
`CC-4086`, `CC-4124`. **HHG-006 is one of these**: $478.95, $456.96, $488.04,
$482.12 in thirty minutes, $1,906.07 total.

**U2 — shared-device ring behind an anonymising proxy.** One device profile
across a run of unrelated cardholders in a single month, marked new on every
account. Seeded from `CC-2649`, `CC-2971`, `CC-2985`, `CC-3035`. **HHG-014 is
one of these** — the analyst request even says so.

The detection subtlety is worth the paragraph. A "device profile" here is a
`DeviceInfo | OS | browser | screen` string, not a serial number, and **92% of
online transactions sit on a profile shared by three or more cards**. Counting
cards finds nothing but noise. What separates a hub is the *anonymous-proxy
ratio*: on the confirmed ring, every card that ever touched the profile arrived
anonymously — ratio **1.00**, against **0.03–0.06** for an ordinary shared
browser fingerprint.

### The calibration trap that inverts everything

Calibrating directly on the closed-case file makes every signal point the wrong
way, and it is not a modelling error — it is selection.

Every *cleared* case in the history got there by scoring high on the bank's
model: a travel trip, a new phone, an unusual but genuine purchase. Every
*confirmed* case got there because a cardholder rang up, and those are often
small, ordinary-looking transactions. So inside that file, "looks anomalous"
predicts **cleared**. Measured naively, `known_device_and_region` came out at
LR 3.3 *toward fraud* — an agent calibrated on that learns to treat ordinariness
as incriminating and confidently clears real fraud.

Two fixes, both in `ingest/05_calibrate.py`:

1. **A third stratum.** Ordinary transactions from the same four months that no
   investigation ever touched. Because months 1–4 were fully worked by the
   bank's analysts, an untouched transaction there is a usable negative.
2. **Matched controls.** Each fraud case paired with another transaction **on
   the same card**, which removes the card-tenure confound — fraud cases sit
   disproportionately on long-lived busy cards. The question becomes the one an
   analyst actually asks: what is different about *this* transaction compared
   with the rest of this card's behaviour?

And then the result, which is worth stating plainly rather than burying:
corrected, held-out fraud-vs-not accuracy falls from 0.93 to **0.57**. That is
not a regression, it is the measurement finally answering the right question.
Every confirmed case in this history was found by a cardholder ringing up, so
fraud never entered the file because it *looked* anomalous — and with the
trigger excluded as the confound it is, the graph signals genuinely cannot
separate fraud from ordinary activity on the same card.

What the history *can* teach is which typology a fraud is, and it teaches that
strongly: `device_new_on_account` runs 0.85 under card-not-present-from-a-new-device
against 0.001 under out-of-region use; `match_flag_anomaly` 0.56 against 0.001
the other way. That is what the posterior discriminates on. Fraud-versus-not is
carried by the trigger prior and by the structural typology matchers, and
`eval/reports/calibration.md` says so.

### Anomaly is measured against a clean baseline

Never against the card's whole history up to the alert. Measuring against
everything lets the first legs of a fraud episode teach the baseline that the
new device and the new region are normal, so by the last leg nothing looks
unusual. The baseline cutoff is `as_of − 72h`; 75% of closed-case episodes open
within 29 hours of their alert.

### The temporal wall is real

In all 5,565 closed investigations, the last transaction of the episode
*precedes* `opened_at`. So `as_of` is a hard wall: every query, every vector
recall, every proximity walk is bounded by it, on both legs of the hybrid recall.
It costs some accuracy and it is the only way the backtest numbers mean anything.

### Reported probability is capped

At 0.97 and 0.02. No investigation on this evidence is certain, and
`fraud_probability` is explicitly scored for calibration — reporting 1.00 is not
confidence, it is a missing error bar. The ceiling sits above the 0.85 action
threshold in policy §6, so it never changes an action.

---

### Rings you cannot see from one card

Several fraud cases look ordinary card by card. On the graph, the flagged
purchase's device made near-identical purchases on other cards in the same week:
HHG-019's $99.92 sits next to $100.00 and $100.06 on two other cards from a
device profile only 3 cards had used by the time of the alert; HHG-011's $131.30 next to $125.59 and
$125.72, also from a 3-card device. `peer_purchases.gsql` asks that two-hop question.

The gate matters more than the query. On a generic browser string
("chrome 66.0", 175 cards) ordinary shoppers with similar baskets would make a
false ring, so the signal only fires on a device seen on at most 10 cards up to
the alert. Its weight is measured, not chosen: it fired on 31 confirmed-fraud
closed cases and no cleared ones (likelihood ratio 22.4).

Two things it deliberately does not do, both learned on the October holdout. It
is **fired-only**: folding in "did not fire" on every other case nudged each one
away from card-not-present fraud and cost nineteen correct pattern calls, and
the absence of a rare hub is not a finding. And its peer cards are **evidence,
not connected cards**: treating them as connected made §3a file 19 reports the
bank itself never filed. The peers move the probability; R6 and the report still
need a proven shared origin.

### A habit is not only monthly (R7)

R7 protects a customer who disputes their own recurring charge, and says
"monthly". HHG-018's $39.08 product-W charge appears 21 times on the card over
140 days, every one to three weeks. The matcher accepts a monthly cadence or a
regular one (≥ 4 earlier identical charges over ≥ 45 days, no gap over 45 days,
median gap ≤ 35 days). The closed history cannot teach the verification reply —
all 4,665 of its customer reports were fraud — so for an R7 match the simulator
assumes the reply R7 exists for: the cardholder recognises the charge. The case
closes as legitimate with a reminder, and the assumption is written into the
answer file.

### Guardrails on what the model writes

The LLM writes summaries, pattern descriptions and SAR narratives. Any of them
that cites an identifier (case, card, customer, transaction) not present in the
material it was given is rejected and the deterministic template is used instead
(`report/narrative.py::grounded`). Every evidence item is tagged as a graph fact,
a derived inference, a model score, policy text, the customer's statement or a
simulated reply, and each case lists its open questions — what the agent still
does not know when it stops.

### A write is not a write until it reads back

After writing the case subgraph the agent reads it back with `case_chain` and
checks the case vertex, the affected transactions, the connected cards and the
SAR link. `written_to_graph` is only `true` if the case read back.
`GRAPH_STRICT=1` fails closed instead of falling back to the local mirror.

---

## Checking the answers

There is no answer key, so correctness cannot be proven. What can be checked is
everything mechanical: `python eval/audit_answers.py` verifies every ID against
the dataset, that nothing postdates the alert, exposure (§4), approval routes
(§2), case and SAR rules (§3a), R1, R2, R3, R7, the stop rule (§6) and graph
read-back. Current result: **0 issues across 20 files**
(`eval/reports/answer_audit.md`). The console's Scoreboard shows the same audit
per case.

---

## Results

### The twenty benchmark cases

11 legitimate, 9 fraud. Two SARs. Five cases requested evidence and all five
revised their recommendation. All 20 validate against the Answer Format and pass
the audit. Run against TigerGraph through MCP: 1,492 MCP calls, 0 fallbacks, about
4 s and 38 graph calls per case.

| Case | What the graph showed |
|---|---|
| **HHG-006** | Sub-threshold structuring (undocumented U1): four purchases, $1,906.07 in thirty minutes. SAR. |
| **HHG-014** | Shared-device ring (undocumented U2): 19 connected cards, anonymous-proxy ratio 1.00; WCC puts the card in a 54-card component, PageRank #2. SAR. |
| **HHG-019** | A risk-model alert the bank's model scored low: the same rare device bought ~$100 on two other cards that week (`peer_purchases`, LR 22.4). Fraud at 0.95, card blocked. No SAR: $99.92, one card, documented pattern — the peers are evidence, not a proven shared origin. |
| **HHG-011** | A disputed purchase with the same peer signature on two other cards. Fraud at 0.97, blocked, no SAR for the same reason. |
| **HHG-018** | A disputed $39.08 charge the card has paid 21 times: R7 → verify → recognised → closed, no block. |
| **HHG-002, 007, 017, 020** | Thin evidence: verify first, then close on the reply. |

### October holdout — and the result worth reading twice

400 alerts replayed under their own `as_of`, twice: once with the trigger each
alert really had, once with it stripped. Two arms, because in this history the
trigger is perfectly correlated with the outcome, so a single precision figure
would be measuring the label.

| | as seen | graph only |
|---|---:|---:|
| **AUC** | **0.921** | **0.520** |
| precision / recall | 0.891 / 0.967 | 0.637 / 0.209 |
| Brier / ECE | 0.0825 / 0.036 | 0.4951 / 0.4966 |
| **pattern accuracy (both sides say fraud)** | **0.508** (n=236) | **0.471** (n=51) |
| affected-transaction overlap | 0.587 | 0.141 |
| **SAR agreement with the bank's own filing** | **0.900** | **0.907** |

Strip the trigger and fraud-versus-not collapses to chance — AUC 0.921 to
0.520. Strip the trigger and **pattern accuracy barely moves (0.508 → 0.471),
and SAR agreement does not move at all (0.900 → 0.907).**

Ablation: rerunning calibration and backtest with `peer_purchases` forced off
drops graph-only recall from 0.209 to 0.184 and precision from 0.637 to 0.608,
with the as-seen arm unchanged — the signal adds evidence the trigger doesn't
already carry. Details in `INTEGRATION.md` §12a.

So the division of labour is measured, not claimed: the trigger decides
*whether*; the graph decides *which typology*, *how far it goes*, and *whether
to file*. Six pattern classes — always guessing the majority scores 0.26.

### Autonomous monitoring, outside the benchmark

`python benchmark/monitor.py` raises its own alerts across November–December
from three triggers and investigates all of them:

| trigger | alerts | assessed fraud |
|---|---:|---:|
| `structuring_sweep` (undocumented U1) | 30 | **30** ($38,145.65) |
| `device_hub_sweep` (undocumented U2) | 27 | **24** |
| `risk_score` (the bank's own model, top scores) | 30 | 6 |

The bank's thirty highest-scoring transactions in the exam period yield
6 fraud. The structuring sweep yields 30 of 30 — none of which the model scores
highly, because every individual leg is an ordinary purchase and the pattern
only exists across the burst. Results land in `benchmark/autonomous/`, never in
`cases/`.

---

## Submission artefacts

| Required | Where |
|---|---|
| Working agent | this repo |
| Public GitHub repository | your fork |
| Agent output on the 20 cases | `cases/HHG-001.json` … `cases/HHG-020.json` |
| — the case, written to the graph too | `case.written_to_graph` / `case.graph_case_id`, walkable via `case_chain()` |
| — SAR where policy requires one | `sar` block; `file` always agrees with the final actions |
| — next best action **before** evidence | `next_best_actions.initial` |
| — and **after** | `next_best_actions.final` + `what_changed` |
| Demo video | shot list in `DEMO_VIDEO_SCRIPT.md` |
| Answer audit | `eval/reports/answer_audit.md` (0 issues) |
| Technical blog post | draft in `docs/BLOG.md` |
| Social post tagging @TigerGraphDB | yours to write |

Each answer file also carries an `agent_record` block beyond the required
schema: the full posterior, the measured belief movement per evidence item, the
VoI ranking including the actions the policy *forbade*, the hash-chained
decision ledger, the counterfactual, and the complete reasoning trace.

---

## Troubleshooting

**`data/staged/transactions.parquet missing`** — run `python ingest/01_normalise.py`.

**Memory recall returns nothing on TigerGraph** — the HNSW index is still
building. `python graph/install.py --step verify` says so explicitly. Wait and
re-run.

**`ModuleNotFoundError: fraudagent`** — run scripts from the repo root; each
entry point puts `src/` on the path itself.

**The console shows "no cases"** — `cases/` is empty. Run
`python benchmark/run_20.py`.

**Savanna workspace asleep** — it auto-starts, but the first call may time out.
The store falls back to the local mirror with a printed warning; re-run once the
workspace is up to exercise the real backend.

**Status pill says "Local mirror"** — the workspace was asleep when the console
started. Ping it, then restart `ui/server.py`. Set `GRAPH_STRICT=1` to fail instead
of falling back.

**MCP server won't start** — `pip install tigergraph-mcp`. The store falls back to
the direct connection per call and prints why; `TG_VIA_MCP=0` skips MCP.

**GSQL "reserved keyword" or "Encountered" errors** — TigerGraph 4.2 reserves
`Case`, `proxy`, `cost` and others; the schema already avoids them. The installer
stops at the first refusal and names the file.

**Slow first run** — `sentence-transformers` downloads model weights once. Set
`EMBEDDING_PROVIDER=tfidf` to avoid the download entirely; it is fully offline
and byte-reproducible.

---

## Credits

Built on the **IEEE-CIS Fraud Detection** dataset (Vesta Corporation, via the
IEEE Computational Intelligence Society), re-cut for Hacker House Goa 2026 by
TigerGraph. Customer, calendar, channel, risk scores, closed cases and case pack
were added by TigerGraph.

Customer outreach, step-up authentication, card blocks and regulatory filings
are **simulated**, as the brief permits. Every receipt says so.
