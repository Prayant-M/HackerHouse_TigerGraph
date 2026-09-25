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

---

## Table of contents

- [What it does](#what-it-does)
- [Quickstart](#quickstart)
- [Running against TigerGraph](#running-against-tigergraph)
- [The analyst console](#the-analyst-console)
- [Repository map](#repository-map)
- [Everything a command does](#everything-a-command-does)
- [Design notes worth knowing before you read the code](#design-notes-worth-knowing-before-you-read-the-code)
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
| Case lifecycle as a graph object, reconstructible | `Case` subgraph + `case_chain.gsql` |
| Memory that measurably changes the output | `hybrid_case_recall`, `fraud_proximity`, measured likelihood ratios |
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
python -m pytest tests -q      # 52 tests on the core, the policy and the answer schema
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
python graph/install.py --step all      # schema, vectors, load, queries, GDS, verify
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

Both backends implement the same `GraphStore` contract and share the same window
matchers (`graphstore/matchers.py`), so they answer the same question rather
than merely similar ones.

---

## The analyst console

```bash
python ui/server.py
```

No build step, no bundler, no `node_modules` — FastAPI serving one HTML file.

- **Case inbox** — twenty alerts, filterable by verdict, marked when the
  recommendation was revised
- **Uncertainty meter** — the posterior across all seven hypotheses, with the
  policy thresholds marked on it
- **Evidence board** — every item with the *measured movement in belief* it
  caused, so you can see which evidence actually mattered
- **Before / after** — the provisional recommendation, the evidence request with
  its information-per-unit-of-friction, the revision, and what changed
- **Case subgraph canvas** — the same object `case_chain()` walks in TigerGraph
- **Live re-run** — streams the agent's reasoning trace over SSE while the
  posterior moves on screen
- **Approval queue** — approving or rejecting writes an `APPROVED_BY` edge
- **Calibration** — the measured likelihood-ratio table
- **Policy** — the compiled rules with their verbatim clause text

---

## Repository map

```
ingest/                  01 normalise → 07 verify, run in order
graph/
  ddl/                   01_schema.gsql · 02_vectors.gsql
  loading/               03_loading_jobs.gsql
  queries/               the investigation toolkit, one file per primitive
  algorithms/            04_projections.gsql — CO_OCCURS_WITH + GDS
  install.py             idempotent installer, --dry-run supported
src/fraudagent/
  config.py              every tunable dial, env-overridable
  graphstore/            base.py · local.py · tigergraph.py · matchers.py
  core/                  DETERMINISTIC — no LLM import may appear here
  agent/                 graph.py (LangGraph) · nodes.py · llm.py · simulator.py
  report/                answer.py (schema + validation) · narrative.py
  memory/                embeddings.py
  mcp_servers/           simulated_actions.py
eval/                    backtest.py → reports/
benchmark/               run_20.py → cases/ · monitor.py → autonomous/
ui/                      server.py + static/
cases/                   ← THE SUBMISSION: HHG-001.json … HHG-020.json
docs/                    ARCHITECTURE.md · BLOG.md · DEMO_SCRIPT.md
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
| `graph/install.py` | Schema → vectors → load → queries → GDS → verify | ~20min |
| `benchmark/run_20.py` | **The submission.** Twenty answer files, validated | ~1min |
| `eval/backtest.py` | October holdout: precision, recall, Brier, ECE, confusion | ~10min |
| `benchmark/monitor.py` | Autonomous sweep of Nov–Dec, three trigger sources | ~5min |
| `ui/server.py` | Analyst console | — |
| `pytest tests -q` | 52 tests on the core, the policy and the answer schema | <1s |

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

## Results

### The twenty benchmark cases

11 legitimate, 9 fraud. Two SARs. Four cases requested evidence and four
revised their recommendation. All 20 validate against the Answer Format.
Mean 1.4 s and 24 graph calls per case.

Both undocumented typologies are present and both are caught: **HHG-006**
(sub-threshold structuring, $1,906.07 across four purchases in thirty minutes)
and **HHG-014** (shared-device ring, 19 connected cards, anonymous-proxy ratio
1.00).

### October holdout — and the result worth reading twice

400 alerts replayed under their own `as_of`, twice: once with the trigger each
alert really had, once with it stripped. Two arms, because in this history the
trigger is perfectly correlated with the outcome, so a single precision figure
would be measuring the label.

| | as seen | graph only |
|---|---:|---:|
| **AUC** | **0.936** | **0.531** |
| precision / recall | 0.93 / 0.98 | 0.695 / 0.168 |
| Brier / ECE | 0.0559 / 0.028 | 0.5015 / 0.4984 |
| **pattern accuracy (both sides say fraud)** | **0.573** | **0.561** |
| affected-transaction overlap | 0.613 | 0.117 |
| **SAR agreement with the bank's own filing** | **0.925** | **0.922** |

Strip the trigger and fraud-versus-not collapses to chance — AUC 0.936 to
0.531. Strip the trigger and **pattern accuracy barely moves, and SAR
agreement does not move at all.**

So the division of labour is measured, not claimed: the trigger decides
*whether*; the graph decides *which typology*, *how far it goes*, and *whether
to file*. Six pattern classes — always guessing the majority scores 0.26.

### Autonomous monitoring, outside the benchmark

`python benchmark/monitor.py` raises its own alerts across November–December
from three triggers and investigates all of them:

| trigger | alerts | assessed fraud |
|---|---:|---:|
| `structuring_sweep` (undocumented U1) | 20 | **20** |
| `device_hub_sweep` (undocumented U2) | 18 | **14** |
| `risk_score` (the bank's own model, top scores) | 20 | 2 |

The bank's twenty highest-scoring transactions in the exam period yield
2 fraud. The structuring sweep yields
20 of
20 — none of which the model scores
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
| Demo video | shot list in `docs/DEMO_SCRIPT.md` |
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
