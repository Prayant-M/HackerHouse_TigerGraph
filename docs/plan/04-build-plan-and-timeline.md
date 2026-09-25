# 04 — Build Plan & Timeline

Two variants below: a **10-day plan** (~70–80 focused hours, the realistic shape if you have evenings plus two weekends) and a **72-hour compressed plan** if this is a sprint-format hackathon. Pick one, then hold the phase gates.

---

## Phase 0 — Setup and reconnaissance (6 hours)

Nothing is built in this phase and it is still the highest-leverage block of the project.

1. Provision TigerGraph (Savanna workspace or CE via Docker). Confirm version is **4.2+** — TigerVector is not available below it and half this design depends on it. On Savanna, turn on auto-stop and auto-start as the brief requires.
2. Download the HHGOA dataset. **Read the README end to end, twice.** Write down, in your own file, the exact answer format it specifies and the exact structure of the closed cases. Everything downstream keys off this.
3. Profile the data in a notebook: row counts, null rates per column, risk-score distribution, how closed cases link to transactions, what fields the 20 benchmark cases actually give you at trigger time.
4. Stand up `tigergraph-mcp`, connect it to a scratch graph, call `tigergraph__list_graphs` and `tigergraph__get_global_schema` successfully. Prove the plumbing before you build on it.
5. Join the TigerGraph Discord. Post your intended schema and ask one sharp question about the answer format. Mentor responses are free intelligence about grading intent.
6. Create the repo, the `.env.example`, and the Makefile skeleton.

**Gate:** you can run one GSQL query against TigerGraph through MCP from Python, and you can state the answer-file format from memory.

---

## Phase 1 — Graph modelling and ingestion (10 hours)

1. Write `01_normalise.py`: join transaction + identity, convert `TransactionDT` to absolute datetime, hash device fingerprints, compute per-card amount z-scores, encode missingness flags.
2. Write the DDL. Vertices, edges, then vector attributes as a separate script so you can iterate on vectors without dropping the graph.
3. Loading jobs. Load a **10,000-row sample first** and verify every count before you touch 590k. A full reload of a bad schema costs an hour you will not have later.
4. Build the derived `CO_OCCURS_WITH` projections in GSQL.
5. Load the closed cases from months 1–4 as `Case` vertices with dispositions, wired to their transactions via `INVESTIGATES`.
6. Compute and load `Transaction.behavior_emb` (the 64-d behavioural vector). Poll `GET /restpp/vector/status` until `Ready_for_query`.
7. `07_verify.py`: assert vertex/edge counts, run three spot-check traversals, confirm vector search returns non-empty.

**Gate:** `make load` runs clean from scratch on an empty database, and a vector search over `Transaction.behavior_emb` returns results.

---

## Phase 2 — GSQL investigation toolkit (10 hours)

Build the queries from `02` §4, in this order — the ordering is by value-per-hour, so if you run short you lose the least important ones:

1. `tx_neighborhood`, `card_history` — you cannot investigate anything without these.
2. `device_fanout`, `entity_fanout`, `velocity_burst` — the highest-signal cheap features.
3. `fraud_proximity` — converts closed cases into a live graph signal. Disproportionate value.
4. `hybrid_case_recall` — the signature query. Budget real time for it; fusing vector and graph legs correctly takes iteration.
5. `shared_entity_ring` + GDS (`tg_wcc`, `tg_louvain`, `tg_pagerank`, `tg_kcore`) materialised as vertex attributes offline.
6. `behavioural_neighbours`, `new_entity_first_use`, `geo_impossibility`, `email_mismatch_profile`.
7. The five documented typology matchers, one `pattern_match_*` query each.
8. `case_chain` — needed by the UI and by the answer writer.

Every query takes an `as_of` parameter and filters on it. No exceptions. Add a test that fails if any installed query lacks the parameter.

**Gate:** each query runs from Python through MCP, returns typed output, and respects `as_of`.

---

## Phase 3 — GraphRAG, policy compilation, calibration (10 hours)

1. Chunk the policy document, the five typologies, and the regulatory references. Embed and load as `PolicyClause` / `Pattern` / `RegulatoryRef` vertices with vectors.
2. Run the policy compiler: LLM extraction → `policy.compiled.yaml` → **you read every rule and fix it**. This is a one-hour review that prevents an entire class of demo failure.
3. Implement `core/policy_engine.py` and `core/permissions.py` against the compiled rules. Unit-test them. These files never call an LLM.
4. **Compute the empirical likelihood-ratio table** from the months 1–4 closed cases. For each binary graph signal, measure `P(signal | confirmed) / P(signal | cleared)`. Commit the table. This is the half-day that makes your posteriors real instead of decorative.
5. Compute base rates per hypothesis and per trigger type for the priors.

**Gate:** `policy_engine.evaluate(case_state)` returns permitted/required/forbidden actions with clause citations, and the LR table is committed with the code that generated it.

---

## Phase 4 — Agent orchestration and the uncertainty engine (14 hours)

The core of the project. Build the deterministic layer first — it is testable without LLM calls and without spending tokens.

1. `core/evidence_ledger.py` — Bayesian update. Unit tests with hand-computed expected posteriors.
2. `core/voi.py` — expected information gain, action selection, cost ratios.
3. `core/stopping.py` — the two-sided stopping rule.
4. `core/ledger.py` — hash-chained decision log.
5. `agent/state.py` — the typed state.
6. LangGraph nodes, in dependency order: Trigger Intake → Case Opener → Evidence Planner → Retrievers (parallel) → Pattern Matcher → Ledger Update → Uncertainty Assessor → branch → VoI/Evidence Gap Resolver → Action Recommender → Permission Gate → Explainer → Case Writer → Memory Consolidator.
7. The simulated evidence responder, seeded and deterministic.
8. The LLM cache layer — cache on a hash of (prompt, model, temperature). You will re-run the 20 benchmark cases many times; without a cache you will burn your budget and your patience.

**Gate:** one case runs end to end, produces both a PROVISIONAL and a REVISED recommendation, and writes a `Case` subgraph you can read back with `case_chain`.

---

## Phase 5 — Memory loop and pattern discovery (8 hours)

1. Memory consolidation: narrative embedding, `SIMILAR_TO` edges, Beta-Binomial pattern-precision updates, entity recurrence counters.
2. LR recalibration on case close.
3. Pattern discovery pipeline (`06`, D5): motif mining over confirmed-fraud closed cases, cluster, LLM-name the clusters, register as `Pattern` vertices with `source: DISCOVERED`.
4. **Prove memory works.** Run the same case twice — once against an empty memory graph, once against the full months 1–4 memory — and record both outputs. The diff is your blog post's best figure and your demo's best 20 seconds.

**Gate:** you have a concrete, reproducible example of memory changing a recommendation.

---

## Phase 6 — Analyst console (10 hours)

Minimum viable, in priority order. Cut from the bottom if time runs out.

1. **Case view** — trigger, timeline, current posterior as a distribution over hypotheses, status.
2. **Live reasoning trace** — stream LangGraph node transitions over WebSocket. Watching the agent think is the single most demo-effective feature and it is mostly plumbing you already have via the checkpointer.
3. **Uncertainty meter** — posterior bar that visibly moves when evidence lands. This is the before/after loop made visual.
4. **Evidence board** — cards showing each item, its likelihood ratio, its source tool, and support/contradiction links to findings.
5. **Action panel** — recommended actions with tier, approval route, cited policy clause, and working Approve/Reject buttons.
6. **Graph canvas** — the case subgraph. Cytoscape.js or react-force-graph. Do not build a custom renderer.
7. **SAR viewer** — the drafted report with its regulatory citations.
8. **Case inbox** — list of all 20 benchmark cases with status.

Dark theme, monospace for identifiers and hashes, one accent colour for risk. Fraud consoles are dense and serious; make it look like a tool, not a landing page.

**Gate:** you can drive an entire investigation from the browser without a terminal.

---

## Phase 7 — Backtest and calibration (8 hours)

This phase is what converts "we built an agent" into "we built an agent that is 0.79 precise on 180 held-out cases."

1. Run the agent over a held-out slice of the months 1–4 closed cases (hold out ~20% from memory seeding so you aren't testing on training data).
2. Report: precision and recall on confirmed vs cleared; fraud-type accuracy; **calibration curve, Brier score, expected calibration error**; average rounds to decision; evidence-request rate; action distribution.
3. Tune thresholds and LRs against the calibration curve, not against vibes.
4. Commit `eval/reports/` to the repo. Judges scoring *investigation accuracy* will look for exactly this and almost nobody will have it.

**Gate:** a committed backtest report with a calibration plot.

---

## Phase 8 — Run the 20 benchmark cases (6 hours)

1. Fresh graph load, full memory seeded from all of months 1–4.
2. Run all 20 with a fixed seed and the LLM cache warm. Write answer files **and** case subgraphs from the same code path.
3. Validate every answer file against the README's format with a schema check. A malformed answer file is a zero on that case regardless of how good the reasoning was.
4. Verify in the graph: 20 `Case` vertices, each with evidence, findings, decisions, both recommendation phases, and a SAR where policy required one.
5. Re-read each of the 20 explanations yourself. Anything that reads as generic, fix the prompt and re-run that case.

**Gate:** 20 validated answer files in `benchmark/outputs/`, 20 cases in the graph.

---

## Phase 9 — Demo, blog, social, polish (8 hours)

### Demo video (3–5 minutes, target 4:00)

| Time | Beat |
|---|---|
| 0:00–0:20 | The problem in one sentence, over a shot of the graph canvas. No slide deck. |
| 0:20–0:50 | Trigger a case from the risk-score inbox. Show the agent opening the case and streaming its first retrieval round. |
| 0:50–1:40 | Evidence board fills. Show `hybrid_case_recall` surfacing a prior case and the posterior moving because of it. Say the words "graph and vector, one query, one database." |
| 1:40–2:20 | **The hinge.** Posterior sits at 0.63, below the block threshold. Show the VoI panel ranking three possible evidence actions and choosing step-up auth. Show the PROVISIONAL recommendation recorded. |
| 2:20–2:50 | Evidence lands. Posterior jumps. **Recommendation flips** on screen. REVISED recommendation recorded with approval route. |
| 2:50–3:20 | Permission gate: BLOCK_ACCOUNT routed to L2, FILE_SAR routed to compliance, each with its cited policy clause. Click Approve. |
| 3:20–3:45 | Case subgraph in TigerGraph, and the counterfactual explanation. |
| 3:45–4:00 | Backtest numbers on screen, one line on the discovered undocumented pattern. |

Record in one take if you can; a live, unedited run is far more convincing than a cut montage, and it is also the thing most likely to reveal that you actually built it. Do three dry runs first.

### Blog post

Cover the six required points (what you built, architecture, how TigerGraph is used, agentic capabilities, what you learned, what you'd improve). Lead with the technical argument, not the story: *"We put two embedding spaces and a transaction graph in one database and queried them together, then made every decision that has to be defensible deterministic."* Include the `hybrid_case_recall` GSQL in full, the architecture diagram, the calibration curve, and one honest failure — something that didn't work and why. Write it in `docs/BLOG.md` as you build, not at the end.

### Social post

Tag **@TigerGraphDB**. One screenshot of the recommendation flipping, two sentences on the hybrid query, link to the blog. Post it before the deadline, not after.

---

## 10-day schedule

| Day | Phases | Hours |
|---|---|---|
| 1 | Phase 0 + start Phase 1 | 8 |
| 2 | Phase 1 complete | 8 |
| 3 | Phase 2 (queries 1–5) | 8 |
| 4 | Phase 2 complete + Phase 3 start | 8 |
| 5 | Phase 3 complete | 8 |
| 6 | Phase 4 (deterministic core + nodes) | 9 |
| 7 | Phase 4 complete + Phase 5 start | 9 |
| 8 | Phase 5 complete + Phase 6 start | 8 |
| 9 | Phase 6 complete + Phase 7 | 9 |
| 10 | Phase 8 + Phase 9 | 9 |

Leave day 10 evening empty. Something will break.

## 72-hour compressed variant

Cut, in this order: the discovered-pattern pipeline (D5), the graph canvas, the hash-chained ledger, the red-team layer, the multi-model fallback. Keep the Bayesian ledger, the VoI engine, the before/after loop, the policy engine, `hybrid_case_recall`, and the backtest — those carry the score.

| Block | Hours | Content |
|---|---|---|
| H0–H8 | 8 | Phase 0 + ingest a 100k-row subset only |
| H8–H18 | 10 | Six GSQL queries: neighborhood, history, fanout, fraud_proximity, hybrid_recall, two typology matchers |
| H18–H26 | 8 | Policy compile + LR table + deterministic core |
| H26–H42 | 16 | LangGraph agent, full loop, simulated responder |
| H42–H52 | 10 | UI: case view, reasoning trace, uncertainty meter, action panel |
| H52–H60 | 8 | Backtest on a 60-case sample, tune thresholds |
| H60–H66 | 6 | Run the 20, validate, write to graph |
| H66–H72 | 6 | Video, blog, social, README |

---

## Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vector index not ready → silent empty memory recall | High | High | Poll `/restpp/vector/status` in `07_verify.py`; fail loudly if not `Ready_for_query` |
| Savanna workspace auto-stops mid-demo | Medium | High | Auto-start is required by the brief and does work, but warm it 10 minutes before recording; keep a CE Docker fallback loaded |
| 590k rows make interactive queries slow | Medium | Medium | Materialise community/hub attributes offline; index on `ts`; demo on a pre-warmed case |
| LLM non-determinism breaks reproducibility | High | Medium | Temperature 0, seeded, response cache keyed on prompt hash, committed cache for the 20 |
| Agentic loop runs away on an ambiguous case | Medium | High | Hard round cap (3), token budget, wall-clock timeout, all recorded in `halt_reason` |
| Answer format mismatch with the README | Medium | **Critical** | Schema-validate every answer file in CI against a fixture derived from the README |
| Policy extraction produces wrong rules | Medium | High | Human review of `policy.compiled.yaml`; unit tests per clause |
| Temporal leakage inflates backtest numbers | High | High | `as_of` on every query; a test that greps installed queries for the parameter |
| Ambitious UI eats the last two days | High | Medium | Build UI features in the stated priority order; the top four are sufficient |
| Running out of LLM credit on the final benchmark run | Medium | High | Warm cache, run a 3-case smoke test before the full 20, keep a second provider key |

---

## What to cut, in order, if you are behind

1. Graph canvas visualisation (describe the subgraph in text instead)
2. Discovered-pattern mining (D5)
3. Hash-chained ledger (keep the `Decision` vertices, drop the hashing)
4. Red-team / prompt-injection layer (D11)
5. Multi-model routing (one model, one fallback)
6. Merchant verification and external stubs
7. Three of the eight hypotheses (keep H0, H1, H2, H3, H6)

**Never cut:** the before/after recommendation loop, the policy engine, `hybrid_case_recall`, the backtest report, writing cases to the graph, or the `as_of` discipline. Those are the score.
