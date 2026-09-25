# 02 — Architecture & Graph Data Model

---

## 1. System architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  LAYER 6 — ANALYST CONSOLE (Next.js)                                 │
│  Case inbox · Live reasoning trace · Graph canvas · Evidence board    │
│  Uncertainty meter · Action panel w/ approval routing · SAR viewer    │
└───────────────▲──────────────────────────────────────────────────────┘
                │ WebSocket (agent step stream) + REST
┌───────────────┴──────────────────────────────────────────────────────┐
│  LAYER 5 — ORCHESTRATION (LangGraph, typed state, checkpointed)      │
│  Trigger Intake → Case Opener → Evidence Planner → Retrievers →      │
│  Pattern Matcher → Memory Recall → Uncertainty Assessor →            │
│  [Evidence Gap Resolver ⟲] → Action Recommender → Permission Gate →  │
│  Explainer → Case Writer → Memory Consolidator                       │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│  LAYER 4 — DETERMINISTIC CORE (pure Python, no LLM, unit-tested)     │
│  Bayesian Evidence Ledger · Value-of-Information engine ·            │
│  Policy-as-Code rule engine · Permission & approval router ·         │
│  Stopping-rule evaluator · Hash-chained decision ledger              │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│  LAYER 3 — TOOL LAYER (MCP)                                          │
│  tigergraph-mcp (schema, query, vector, data)                        │
│  + custom fraud-tool MCP server (typed investigation primitives)     │
│  + simulated action MCP server (customer outreach, step-up, freeze)  │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│  LAYER 2 — GSQL INVESTIGATION TOOLKIT                                │
│  Neighbourhood expansion · Ring detection · Velocity · Fan-out ·     │
│  Fraud-proximity · Typology matchers · Hybrid vector+graph recall    │
│  GDS: WCC, Louvain, PageRank, k-core on entity projection            │
└───────────────▲──────────────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────────────┐
│  LAYER 1 — TIGERGRAPH (graph + TigerVector, one store)               │
│  Transaction graph · Case graph · Policy graph · Pattern library     │
│  Vector attrs: case narrative, policy clause, typology, tx behaviour │
└──────────────────────────────────────────────────────────────────────┘
```

**The load-bearing idea:** Layer 4 is deterministic and contains every decision that must be defensible — risk math, policy enforcement, approval routing, stopping. The LLM in Layer 5 plans, selects tools, synthesises, and writes prose. It never *computes* a risk number and never *grants* a permission. That split is what makes the system auditable, and it is directly quotable in your blog post.

---

## 2. Graph schema

### 2.1 Transaction subgraph (loaded from the dataset)

| Vertex | Primary ID | Key attributes |
|---|---|---|
| `Transaction` | `TransactionID` | `ts` (DATETIME, derived), `amount`, `product_cd`, `risk_score`, `hour_of_day`, `dow`, `dist1`, `dist2`, `amt_zscore_card`, `behavior_emb` (VECTOR) |
| `Card` | `card1` | `brand` (card4), `type` (card6), `bin_hash` (card3/card5), `first_seen`, `last_seen` |
| `Customer` | `customer_id` | `tenure_days`, `home_region`, `segment` |
| `Device` | `device_fp` (hash of DeviceInfo+id_30+id_31+id_33) | `device_type`, `os`, `browser`, `screen_res` |
| `EmailDomain` | `domain` | `is_free`, `is_disposable`, `tld` |
| `Address` | `addr1_addr2` | `region_code`, `country_code` |
| `NetworkNode` | `id19_id20_hash` | proxy/network cluster surrogate |
| `Merchant` | `product_cd` bucket | coarse merchant-category proxy |

| Edge | From → To | Attributes |
|---|---|---|
| `MADE_WITH` | Transaction → Card | |
| `FROM_DEVICE` | Transaction → Device | |
| `BILLED_TO` | Transaction → Address | |
| `PURCHASER_EMAIL` | Transaction → EmailDomain | |
| `RECIPIENT_EMAIL` | Transaction → EmailDomain | |
| `VIA_NETWORK` | Transaction → NetworkNode | |
| `OWNED_BY` | Card → Customer | |
| `CO_OCCURS_WITH` | Device ↔ Card (undirected, derived) | `weight` = shared tx count, `first_ts`, `last_ts` |

`CO_OCCURS_WITH` is a **derived projection edge**. Build it once in GSQL after load. It collapses the 2-hop `Card → Transaction → Device` path into 1 hop, which makes ring detection and community algorithms an order of magnitude faster. Do the same for `Card ↔ Address` and `Card ↔ EmailDomain`.

### 2.2 Case subgraph (written by the agent — this is the part judges inspect)

| Vertex | Key attributes |
|---|---|
| `Case` | `case_id`, `status` (OPEN/AWAITING_EVIDENCE/PENDING_APPROVAL/ACTIONED/CLOSED), `trigger_type`, `opened_at`, `as_of` (temporal cutoff), `risk_level`, `posterior_fraud_prob`, `confidence`, `fraud_type`, `disposition`, `narrative`, `narrative_emb` (VECTOR) |
| `Evidence` | `evidence_id`, `kind` (GRAPH/BEHAVIOURAL/DEVICE/POLICY/MEMORY/SOLICITED), `source_tool`, `payload_json`, `collected_at`, `likelihood_ratio`, `reliability` |
| `Finding` | `finding_id`, `statement`, `support_score`, `contradicted_by_count` |
| `Decision` | `decision_id`, `step_no`, `posterior_before`, `posterior_after`, `rationale`, `prev_hash`, `hash` |
| `RecommendedAction` | `action_id`, `action_type`, `phase` (PROVISIONAL/REVISED), `approval_route`, `executed`, `executed_at`, `policy_clause_ids` |
| `EvidenceRequest` | `request_id`, `channel`, `question`, `expected_info_gain`, `cost`, `sent_at`, `responded_at`, `response` |
| `Pattern` | `pattern_id`, `name`, `description`, `source` (DOCUMENTED/DISCOVERED), `base_rate`, `historical_precision`, `desc_emb` (VECTOR) |
| `PolicyClause` | `clause_id`, `section`, `text`, `obligation_type`, `text_emb` (VECTOR) |
| `RegulatoryRef` | `ref_id`, `citation`, `text`, `text_emb` (VECTOR) |
| `Analyst` | `analyst_id`, `role` (L1/L2/COMPLIANCE), `approval_ceiling` |
| `SAR` | `sar_id`, `narrative`, `filed_at`, `triggering_clause_id` |

| Edge | From → To |
|---|---|
| `INVESTIGATES` | Case → Transaction / Card / Customer / Device |
| `HAS_EVIDENCE` | Case → Evidence |
| `SUPPORTS` / `CONTRADICTS` | Evidence → Finding |
| `PRODUCED_FINDING` | Case → Finding |
| `MATCHED_PATTERN` | Case → Pattern (`match_score`, `matched_at`) |
| `CITES_POLICY` | Case / RecommendedAction → PolicyClause |
| `CITES_REGULATION` | SAR → RegulatoryRef |
| `RECOMMENDS` | Case → RecommendedAction |
| `REQUESTED` | Case → EvidenceRequest |
| `ANSWERED_BY` | EvidenceRequest → Evidence |
| `DECIDED` | Case → Decision (ordered by `step_no`) |
| `APPROVED_BY` | RecommendedAction → Analyst |
| `SIMILAR_TO` | Case ↔ Case (`cosine`, `shared_entities`, `computed_at`) |
| `FILED` | Case → SAR |

**Why this matters:** a judge who opens your graph and runs `SELECT * FROM Case WHERE case_id="..."` then follows `HAS_EVIDENCE → SUPPORTS → Finding → ... → RECOMMENDS` can reconstruct the entire investigation without reading your JSON. That is the *"maintain a record of decisions and actions taken"* requirement satisfied in the medium the judges care about.

### 2.3 Vector attributes (TigerVector, TigerGraph 4.2+)

| Vector | Dim | Populated from | Used for |
|---|---|---|---|
| `Case.narrative_emb` | 1536 (or 768 local) | LLM-written case summary | Memory recall — "what did we see that looked like this?" |
| `PolicyClause.text_emb` | 1536 | Policy doc chunks | Policy GraphRAG — which clause governs this action |
| `Pattern.desc_emb` | 1536 | Typology descriptions | Soft typology matching before hard GSQL matchers run |
| `RegulatoryRef.text_emb` | 1536 | Regulatory references | SAR citation grounding |
| `Transaction.behavior_emb` | 64 | **Engineered, not LLM** — see §5 | Behavioural nearest-neighbour: "transactions that *act* like this one" |

Community Edition caps vectors at 4096 dims and 300 GB combined graph+vector storage — you are nowhere near either limit. Note that TigerGraph builds the HNSW index asynchronously; vectors that have not finished indexing **will not appear in search results**. Poll `GET /restpp/vector/status` and wait for `Ready_for_query` before you run your benchmark, or you will silently get empty memory recall on a fresh load.

---

## 3. Ingestion pipeline

```
data/raw/            → parse, join transaction + identity on TransactionID
  ↓ 01_normalise.py     TransactionDT → absolute datetime; hash device fingerprints;
                        bucket amounts; compute per-card z-scores
data/staged/*.csv    → one CSV per vertex type, one per edge type
  ↓ 02_ddl.gsql         CREATE VERTEX / CREATE DIRECTED EDGE / CREATE GRAPH
  ↓ 03_loading.gsql     CREATE LOADING JOB, LOAD ... TO VERTEX / TO VECTOR ATTRIBUTE
  ↓ 04_projections.gsql build CO_OCCURS_WITH derived edges
  ↓ 05_seed_memory.py   load 4 months of closed cases as Case vertices with outcomes
  ↓ 06_embed.py         policy chunks, typologies, case narratives → vectors → upsert
  ↓ 07_verify.py        vertex/edge counts, vector index status, spot-check traversals
```

Three things that will bite you if you skip them:

1. **Missingness is signal, not noise.** IEEE-CIS is full of nulls and the null *pattern* correlates with fraud. Do not blanket-impute. Encode "was this field present" as a separate boolean attribute where it matters (`M1`–`M9`, `dist2`, `R_emaildomain`).
2. **Load vectors with the right separator.** `LOAD ... TO VECTOR ATTRIBUTE emb ON VERTEX Case VALUES ($0, SPLIT($1, ","))` — and note the documented restriction that nested built-in token functions inside `SPLIT` will fail to compile. Clean the bracket characters in Python before writing the CSV, not in GSQL.
3. **RESTPP will not error on a misspelled vector attribute name.** It silently accepts the load and you get an empty index. Verify counts after every vector load.

---

## 4. The GSQL investigation toolkit

These are the primitives the agent calls as tools. Write them as installed GSQL queries, expose each through MCP, and give each a one-line description the LLM can select on.

| Query | Signature | What it answers |
|---|---|---|
| `tx_neighborhood` | `(tx_id, hops, as_of)` | The 2-hop entity blast radius of a transaction, time-bounded |
| `card_history` | `(card_id, as_of, window_days)` | Transaction timeline, amount distribution, merchant mix |
| `velocity_burst` | `(card_id, as_of, window_hours)` | Count and value of transactions in a rolling window vs. that card's baseline |
| `card_testing_probe` | `(card_id, as_of)` | Sequence of small-value authorisations followed by a large one |
| `device_fanout` | `(device_fp, as_of)` | How many distinct cards/customers share this device fingerprint |
| `entity_fanout` | `(entity_id, entity_type, as_of)` | Generic fan-out — the `C1`–`C14` intuition done as a real traversal |
| `shared_entity_ring` | `(seed_card, as_of, min_weight)` | Connected component over `CO_OCCURS_WITH` — the mule/bust-out ring |
| `fraud_proximity` | `(entity_id, as_of)` | How many *confirmed-fraud* closed cases sit within N hops of this entity, decayed by distance |
| `new_entity_first_use` | `(tx_id, as_of)` | Is this the first time this card/device/address pair has ever been seen? (the `D`-column intuition) |
| `geo_impossibility` | `(card_id, as_of)` | Billing/transaction distance vs. elapsed time between consecutive transactions |
| `email_mismatch_profile` | `(tx_id)` | Purchaser vs. recipient domain divergence, free/disposable flags |
| `hybrid_case_recall` | `(query_vec, entity_ids, k, as_of)` | **Vector search over `Case.narrative_emb`, then graph-filter to cases sharing ≥1 entity.** The signature query of this project. |
| `behavioural_neighbours` | `(tx_behavior_vec, k, as_of)` | Nearest transactions in behaviour space among *closed confirmed-fraud* cases |
| `pattern_match_<n>` | `(entity_id, as_of)` | One hard matcher per documented typology |
| `case_chain` | `(case_id)` | Full ordered reconstruction of a case: evidence → findings → decisions → actions |

### 4.1 The signature query — hybrid graph + vector case recall

This is the one to put in the blog post and on screen in the demo. Pure vector search over case narratives returns cases that *sound* similar. Pure graph traversal returns cases that are *connected*. Neither alone is right. Intersect them, and rank by the product.

```gsql
CREATE QUERY hybrid_case_recall(
    LIST<FLOAT> query_vec,
    SET<STRING> entity_ids,
    INT k,
    DATETIME as_of
) FOR GRAPH FraudGraph {

  MapAccum<VERTEX<Case>, FLOAT>  @@vec_score;
  MapAccum<VERTEX<Case>, INT>    @@shared_entities;
  SumAccum<FLOAT>                @score;

  // 1. Vector leg — semantically similar prior narratives
  candidates = vectorSearch({Case.narrative_emb}, query_vec, k * 5);
  candidates = SELECT c FROM candidates:c
               WHERE c.status == "CLOSED" AND c.opened_at < as_of
               ACCUM @@vec_score += (c -> c.similarity_score);

  // 2. Graph leg — cases touching any entity in the current investigation
  seeds = {entity_ids};
  linked = SELECT c FROM seeds:s -(reverse_INVESTIGATES:e)- Case:c
           WHERE c.status == "CLOSED" AND c.opened_at < as_of
           ACCUM @@shared_entities += (c -> 1);

  // 3. Fuse — semantic similarity weighted by structural overlap
  all_c = candidates UNION linked;
  result = SELECT c FROM all_c:c
           ACCUM c.@score = 0.55 * @@vec_score.get(c)
                          + 0.45 * (1.0 - exp(-0.6 * @@shared_entities.get(c)))
           ORDER BY c.@score DESC
           LIMIT k;

  PRINT result[result.case_id, result.fraud_type, result.disposition,
               result.posterior_fraud_prob, result.@score];
}
```

Note the `as_of` guard on **both** legs. That is the temporal-leakage discipline described in `06`, item D8 — and it is the reason your backtest numbers will be honest when other teams' are not.

### 4.2 Ring detection with the GDS library

Do not hand-roll community detection. Install from the TigerGraph Graph Data Science library and run it over the `CO_OCCURS_WITH` projection:

- `tg_wcc` — connected components. A component containing >3 cards and >1 confirmed-fraud case is a ring.
- `tg_louvain` — finer community structure inside large components.
- `tg_pagerank` — which entity is the hub of the ring (usually a device or an address).
- `tg_kcore` — dense cores; k≥3 on a card-device projection is strongly abnormal for legitimate behaviour.

Materialise the results as vertex attributes (`community_id`, `hub_rank`) once, offline, so the agent reads them instead of recomputing them per case. Recomputing Louvain inside an investigation will blow your latency budget and the judges will notice a slow demo.

### 4.3 Fraud proximity — the feature nobody else will build

```gsql
CREATE QUERY fraud_proximity(VERTEX seed, DATETIME as_of, INT max_hops) FOR GRAPH FraudGraph {
  SumAccum<FLOAT> @@proximity;
  OrAccum         @visited;
  SetAccum<STRING> @@contributing_cases;

  start = {seed};
  start = SELECT s FROM start:s ACCUM s.@visited = TRUE;

  FOREACH hop IN RANGE[1, max_hops] DO
    frontier = SELECT t FROM start:s -(:e)- :t
               WHERE t.@visited == FALSE
               ACCUM t.@visited = TRUE;

    touched = SELECT c FROM frontier:f -(reverse_INVESTIGATES)- Case:c
              WHERE c.disposition == "CONFIRMED_FRAUD" AND c.opened_at < as_of
              ACCUM @@proximity += pow(0.5, hop),
                    @@contributing_cases += c.case_id;

    start = frontier;
  END;

  PRINT @@proximity AS proximity_score, @@contributing_cases AS evidence_cases;
}
```

A distance-decayed count of confirmed-fraud cases around an entity. It converts your 4 months of closed cases from static "memory documents" into a **live graph signal** that feeds the Bayesian ledger as a likelihood ratio. This is the cleanest answer to *"use prior case outcomes to inform recommendations"* and it costs about 40 lines of GSQL.

---

## 5. Behavioural embeddings on transactions

The `V1`–`V339` columns are unusable as LLM context and mostly redundant. Compress them into a 64-dimensional behaviour vector at ingest:

1. Take `C1`–`C14` (fan-out counts), `D1`–`D15` (timedeltas), `M1`–`M9` (match flags as trinary: yes/no/missing), plus `amount_log`, `amt_zscore_card`, `hour_sin`, `hour_cos`, `dist1`, `dist2`.
2. Rank-normalise each (IEEE-CIS has brutal outliers; z-scores won't survive them).
3. PCA the `V1`–`V339` block down to 24 components — they carry real Vesta-engineered signal, just too much of it.
4. Concatenate → ~64 dims → L2-normalise → store as `Transaction.behavior_emb` with **cosine** similarity.

Now `behavioural_neighbours()` answers: *"among transactions that belong to closed confirmed-fraud cases, which ones behave most like this one?"* — a retrieval that is grounded in data, not in an LLM's impression of the data. Feed the top-k and their dispositions to the agent as evidence with a computed likelihood ratio.

This also gives you a clean line for the blog: **two embedding spaces in one database — a semantic space over case narratives and a behavioural space over transactions — queried side by side with graph structure, in a single GSQL query.** That is a genuine TigerVector showcase and it is exactly the kind of thing the Innovation criterion is for.

---

## 6. Repository structure

```
tigergraph-fraud-agent/
├── README.md                     ← architecture diagram, 5-minute quickstart, demo GIF
├── .env.example                  ← every variable, no secrets (see 05)
├── docker-compose.yml            ← TigerGraph CE + app + UI, one command
├── Makefile                      ← make setup / load / backtest / run-benchmark / demo
│
├── data/
│   ├── raw/                      ← .gitignored, the HHGOA download
│   ├── staged/                   ← .gitignored, generated CSVs
│   └── policy/                   ← policy doc, 5 typologies, regulatory refs (committed)
│
├── graph/
│   ├── ddl/                      ← 01_schema.gsql, 02_vectors.gsql
│   ├── loading/                  ← 03_loading_jobs.gsql
│   ├── queries/                  ← one .gsql per investigation primitive
│   ├── algorithms/               ← GDS installs + projection builders
│   └── install.py                ← idempotent installer, safe to re-run
│
├── ingest/                       ← 01_normalise.py … 07_verify.py
│
├── agent/
│   ├── graph.py                  ← LangGraph assembly
│   ├── state.py                  ← typed InvestigationState
│   ├── nodes/                    ← one module per node
│   ├── prompts/                  ← versioned, each with a golden-output test
│   └── llm.py                    ← provider abstraction + cache + fallback
│
├── core/                         ← DETERMINISTIC. No LLM imports allowed here.
│   ├── evidence_ledger.py        ← Bayesian posterior over fraud hypotheses
│   ├── voi.py                    ← Value-of-Information engine
│   ├── policy_engine.py          ← compiled policy rules → obligations
│   ├── permissions.py            ← action → approval route
│   ├── stopping.py               ← two-sided stopping rule
│   └── ledger.py                 ← hash-chained decision log
│
├── mcp_servers/
│   ├── fraud_tools/              ← typed wrappers over the GSQL toolkit
│   └── simulated_actions/        ← outreach, step-up auth, freeze, SAR filing
│
├── policy/
│   ├── policy.compiled.yaml      ← generated from the bank policy doc
│   └── compile_policy.py         ← LLM extract → human review → deterministic rules
│
├── eval/
│   ├── backtest.py               ← replay months 1–4 closed cases
│   ├── calibration.py            ← reliability curve, Brier score, ECE
│   └── reports/                  ← committed backtest output (this is evidence for judges)
│
├── benchmark/
│   ├── run_20.py                 ← produce the 20 answer files + write cases to graph
│   └── outputs/                  ← the actual submission artefacts
│
├── ui/                           ← Next.js analyst console
└── docs/
    ├── ARCHITECTURE.md
    ├── BLOG.md                   ← draft the blog inside the repo
    └── DEMO_SCRIPT.md
```

The `core/` boundary is worth enforcing with a lint rule that fails CI if anything under `core/` imports an LLM client. It is a two-line check and it is a genuinely strong thing to be able to point at in the blog post: *the decision layer cannot hallucinate because it cannot call a model.*
