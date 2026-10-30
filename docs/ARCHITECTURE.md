# Architecture

> **Final round:** the current, detailed diagram set (16 diagrams, each with a full explanation) is in [`docs/architecture/`](architecture/README.md), with PNG/SVG exports in [`docs/diagrams/`](diagrams/). The diagrams below document the Round 1 system and are kept for history; their images moved to `docs/diagrams/round1/`.

## Diagrams

Eighteen diagrams, drawn from the code as it runs. GitHub renders them; the same set is published as an interactive page. Together they cover every component, every graph path, every policy rule and every one of the twenty benchmark cases.

1. [System architecture](#01-system-architecture)
2. [Investigation loop](#02-investigation-loop)
3. [Graph access through MCP](#03-graph-access-through-mcp)
4. [Graph schema](#04-graph-schema)
5. [GraphRAG memory](#05-graphrag-memory)
6. [Decision authority](#06-decision-authority)
7. [Ring detection](#07-ring-detection)
8. [Case lifecycle](#08-case-lifecycle)
9. [Before / after evidence](#09-before--after-evidence)
10. [Data and install pipeline](#10-data-and-install-pipeline)
11. [The temporal wall](#11-the-temporal-wall)
12. [Trust boundaries](#12-trust-boundaries)
13. [Policy rules as code](#13-policy-rules-as-code)
14. [All twenty benchmark cases](#14-all-twenty-benchmark-cases)
15. [Analyst console and API](#15-analyst-console-and-api)
16. [Autonomous monitoring](#16-autonomous-monitoring)
17. [Evaluation and verification](#17-evaluation-and-verification)
18. [Failure modes and fallbacks](#18-failure-modes-and-fallbacks)

### 01 System architecture

Three triggers enter one LangGraph agent. The agent reaches TigerGraph only through a gateway that prefers the TigerGraph MCP server. Decisions come from a deterministic core, and the LLM only writes prose.

```mermaid
flowchart LR
  subgraph IN["Triggers"]
    T1["Risk-model alert"]
    T2["Customer report"]
    T3["Analyst request"]
    T4["Proactive sweeps<br/>monitor.py"]
  end
  subgraph AG["LangGraph agent · agent/"]
    N["15 nodes<br/>trigger → open → plan → retrieve<br/>→ recall → ground → assess<br/>⟲ ask for evidence<br/>→ act → gate → explain → write"]
  end
  subgraph CORE["Deterministic core · core/ (no LLM import)"]
    SIG["signals.py<br/>28 detectors"]
    LED["evidence_ledger<br/>measured LRs"]
    VOI["voi.py<br/>info per friction"]
    STOP["stopping.py<br/>policy §6"]
    POL["policy_engine<br/>R1–R10, §3a"]
    PERM["permissions<br/>auto · L1 · L2"]
    AUD["hash-chained<br/>decision ledger"]
  end
  LLM["LLM · Gemini / Claude<br/>plan + prose only<br/>grounded() ID check"]
  subgraph GA["Graph access · graphstore/"]
    GW{"Gateway<br/>per call"}
    MCPC["mcp_client.py"]
    MCPS["tigergraph-mcp<br/>stdio · 69 tools"]
    DIR["pyTigerGraph<br/>direct"]
    LOC["Local mirror<br/>pandas, same matchers"]
  end
  subgraph TG["TigerGraph Savanna 4.2.5 · FraudGraph"]
    Q["21 GSQL queries"]
    V["TigerVector HNSW<br/>narratives, policy, behaviour"]
    ALG["GDS WCC + PageRank<br/>anon-proxy projection"]
    CASE[("FraudCase subgraph<br/>written + read back")]
  end
  subgraph OUT["Outputs"]
    ANS["cases/HHG-*.json"]
    SIM["Simulated action<br/>service"]
    APP["Approval queue<br/>APPROVED_BY edge"]
    UI["Analyst console<br/>FastAPI + SPA"]
  end
  IN --> N
  N -- "facts" --> SIG --> LED --> STOP
  N -- "which question?" --> VOI
  LED --> POL --> PERM
  N -. "summary, SAR prose" .-> LLM
  N --> GW
  GW == "default" ==> MCPC --> MCPS --> Q
  GW -. "MCP fails" .-> DIR --> Q
  GW -. "graph down" .-> LOC
  Q --- V
  Q --- ALG
  PERM -- "auto" --> SIM
  PERM -- "L1 / L2" --> APP
  N -- "write + verify" --> CASE
  N --> ANS --> UI
  AUD --- N
  APP --> CASE
  
```

- **The graph decides.** Probabilities, actions and routes are computed in `core/`; a test fails the build if it ever imports an LLM client.
- **MCP is the default path.** 1,492 calls on the last run, 0 fallbacks. Direct and local paths exist so a sleeping workspace can't kill a demo.
- **Writes are checked.** A case counts as written only after `case_chain` reads it back.

### 02 Investigation loop

One conditional edge makes this an agent: after every assessment it either gathers more evidence or acts, and the provisional recommendation is recorded before any question is asked.

```mermaid
flowchart TD
  S((start)) --> A[trigger_intake<br/>fix as_of wall]
  A --> B[case_opener<br/>prior by trigger type]
  B --> C[evidence_planner<br/>LLM may reorder tools]
  C --> D[graph_retrieval<br/>GSQL via MCP]
  D --> E[memory_recall<br/>hybrid_case_recall]
  E --> F[policy_grounding<br/>policy_retrieve]
  F --> G[ledger_update<br/>fold signals into posterior]
  G --> H{uncertainty_assessor<br/>policy §6}
  H -- "not decisive, rounds left" --> P[record_provisional<br/>initial next best action]
  P --> R[evidence_gap_resolver<br/>best question by VoI · simulated reply]
  R --> H
  H -- "decisive or nothing worth asking" --> X[action_recommender<br/>R1–R10]
  X --> Y[permission_gate<br/>auto runs · L1/L2 wait]
  Y --> Z[explainer<br/>grounded prose]
  Z --> W[case_writer<br/>write + read back]
  W --> M[memory_consolidator<br/>verify audit chain]
  M --> E2((end))
  
```

- **Stop rule**: p ≥ 0.85 or ≤ 0.15 on two independent pieces of evidence, a reply that settles it, or nothing left worth its friction.
- **Round cap** is enforced in code (`MAX_EVIDENCE_ROUNDS`), not by the model.

### 03 Graph access through MCP

Each graph call tries the official TigerGraph MCP server first and falls back per call, so one failed tool call degrades a single read instead of the case.

```mermaid
sequenceDiagram
  participant AG as Agent node
  participant GW as Gateway (_Gateway)
  participant MC as TigerGraphMCPClient
  participant MS as tigergraph-mcp (stdio)
  participant TG as TigerGraph RESTPP
  participant PY as pyTigerGraph (direct)
  AG->>GW: runInstalledQuery("peer_purchases", params)
  GW->>MC: same call
  MC->>MS: call_tool tigergraph__run_installed_query
  MS->>TG: GET /restpp/query/FraudGraph/peer_purchases
  TG-->>MS: rows
  MS-->>MC: JSON block
  MC-->>GW: data.result
  GW-->>AG: rows (keys unprefixed)
  Note over GW,PY: if the MCP call raises, this call only goes direct
  GW->>PY: runInstalledQuery(...)
  PY->>TG: same RESTPP request
  TG-->>AG: rows
  
```

- **Tools used**: `run_installed_query`, `get_node`, `get_node_edges`, `add_node`, `add_edge`.
- **GRAPH_STRICT=1** fails closed: an unreachable graph raises instead of silently serving the mirror.

### 04 Graph schema

One graph holds three layers: the evidence the bank already has, the memory of 5,565 closed investigations, and every case the agent writes back.

```mermaid
flowchart LR
  subgraph E["Evidence subgraph"]
    CU[Customer] -- OWNS --> CA[Card]
    CA -- MADE --> TX[Transaction]
    TX -- NEXT_TXN --> TX
    TX -- FROM_DEVICE --> DP[DeviceProfile]
    TX -- BILLED_IN --> BR[BillingRegion]
    TX -- PURCHASER / RECIPIENT_EMAIL --> EM[EmailDomain]
    CA -. "CO_OCCURS_WITH (485k)" .- CA
    CA == "ANON_CO_OCCURS (1,725)" === CA
  end
  subgraph M["Memory subgraph"]
    CC[ClosedCase<br/>narrative_emb]
    PA[Pattern<br/>desc_emb]
    PD[PolicyDoc<br/>text_emb]
    CC -- CC_INVOLVES --> TX
    CC -- CC_ON_CARD / CONNECTED_TO --> CA
    CC -- CC_ON_DEVICE --> DP
  end
  subgraph K["Case subgraph (agent writes)"]
    FC[FraudCase<br/>narrative_emb]
    EV[Evidence]
    DE[Decision]
    RA[RecommendedAction]
    ER[EvidenceRequest]
    SA[SAR]
    AN[Analyst]
    FC -- HAS_EVIDENCE --> EV
    FC -- DECIDED --> DE
    FC -- RECOMMENDS --> RA
    FC -- REQUESTED --> ER
    FC -- FILED --> SA
    RA -- APPROVED_BY --> AN
    FC -- INVESTIGATES_TXN --> TX
    FC -- CONNECTED_CARD --> CA
    FC -- RECALLED_CASE --> CC
    FC -- CITES_POLICY --> PD
  end
  
```

- **Reserved words** on 4.2 forced `FraudCase` (not Case), `proxy_type`, `friction_cost`.
- **Card attributes** `community_id` and `hub_rank` are written by WCC and PageRank.

### 05 GraphRAG memory

Similar past cases are found two ways inside one query, by meaning and by shared entities, and fused. Policy clauses are retrieved the same way and handed to the model as citable text.

```mermaid
flowchart LR
  Q["Case text embedding<br/>+ entity ids"] --> EL["eligible = ClosedCase<br/>opened before as_of"]
  EL --> V1["vectorSearch narrative_emb<br/>top k×8 · distance_map A"]
  Q --> T1["Transaction ids → CC_INVOLVED_IN (w 2.0)"]
  Q --> T2["Card ids → CC_CARD_OF / CONNECTED (w 1.0)"]
  Q --> T3["Device ids → CC_DEVICE_OF (w 1.6)"]
  Q --> T4["Customer id → ClosedCase.customer_id (w 0.7)"]
  T1 & T2 & T3 & T4 --> L["linked set"]
  L --> V2["vectorSearch restricted to linked<br/>distance_map B (separate map)"]
  V1 --> F["fused = 0.55 · cosine + 0.45 · (1 − e^(−1.2 · weighted shares))"]
  V2 --> F
  L --> F
  F --> OUT["top 5 prior cases<br/>+ policy_retrieve clauses → LLM brief"]
  
```

- **Why two maps.** MapAccum sums repeated keys; one shared map doubled the distance of cases found by both searches.
- **Filter before top-k**, so future cases can never crowd out eligible ones.

### 06 Decision authority

Evidence becomes numbers through likelihood ratios measured on the bank's own closed cases; numbers become actions only through the written policy.

```mermaid
flowchart LR
  G["Graph facts<br/>(GSQL)"] --> D["28 detectors<br/>signals.py"]
  D --> LR["× measured LR<br/>peer_purchases 22.4<br/>shared_origin_ring 4.2"]
  P0["Prior by trigger<br/>risk alert · dispute · analyst"] --> POST
  LR --> POST["Posterior over 7 hypotheses"]
  POST --> V{"Verdict<br/>≥ 0.70 fraud · ≤ 0.15 legit"}
  V --> PE["Policy engine R1–R10 + §3a"]
  PE --> RT{"Route §2"}
  RT -- auto --> EX["Executed<br/>CREATE_CASE, MONITOR, VERIFY…"]
  RT -- "L1 ≤ $2,500" --> TL["Team lead<br/>BLOCK_CARD, DECLINE"]
  RT -- "L2" --> FM["Fraud manager<br/>FILE_REPORT, big blocks"]
  PE --> SAR{"§3a SAR?<br/>fraud AND (>$1,000 OR connected OR undocumented)"}
  
```

- **Probability capped** at 0.97 / 0.02: no investigation on this evidence is certain.
- **Claim types** on every evidence item: graph fact, derived inference, model score, policy text, simulated reply.

### 07 Ring detection

Raw device sharing is noise: 92% of online purchases sit on a profile shared by 3+ cards. Three gated signals separate real rings from popular browsers.

```mermaid
flowchart TD
  TX["Flagged transaction"] --> DP["its DeviceProfile"]
  DP --> FAN["device_fanout ≤ as_of<br/>cards all-time, anon ratio"]
  FAN --> R1{"anon-proxy ratio ≥ 0.5<br/>and ≥ 2 anon cards"}
  R1 -- yes --> HUB["device_proxy_hub / shared_origin_ring<br/>HHG-014: ratio 1.00, 19 cards"]
  DP --> PEER["peer_purchases (7 days)<br/>other cards, amount ±5%"]
  FAN --> RARE{"device rare?<br/>≤ 10 cards all-time"}
  PEER --> RARE
  RARE -- "yes and ≥ 2 peer cards" --> PP["peer_purchases fires · LR 22.4<br/>HHG-019: $100.00, $100.06 on 2 cards<br/>HHG-011: $125.59, $125.72"]
  RARE -- "no: generic string" --> NOISE["ignored<br/>'chrome 66.0' = 175 cards"]
  HUB --> CTX["card_community (GDS)<br/>WCC component 54 cards · PageRank #2"]
  PP -- "fired-only · evidence" --> POST["posterior"]
  HUB --> R6["R6 · proven shared origin<br/>§3a SAR + MONITOR_CONNECTED_CARDS"]
  
```

- **WCC on the full projection** gives one 6,125-card blob; on the anonymous-proxy slice it isolates the ring.
- **Algorithm output is context**, never probability: it is all-time structure behind the temporal wall.
- **Peers are evidence, not connected cards.** On the October holdout, counting them as connected filed 19 reports the bank never filed; counting their absence cost 19 pattern calls.

### 08 Case lifecycle

A case is opened as a graph object, may pause for evidence, closes with a verdict, and its consequential actions stay pending until a person approves them.

```mermaid
stateDiagram-v2
  [*] --> Open: trigger + as_of fixed
  Open --> Investigating
  Investigating --> Provisional: not decisive
  Provisional --> EvidenceRequested: best VoI question
  EvidenceRequested --> Reassessing: simulated reply lands
  Reassessing --> Investigating: still open, rounds left
  Investigating --> Decided: decisive / exhausted
  Reassessing --> Decided
  Decided --> Written: FraudCase upserted
  Written --> Verified: case_chain read-back
  Verified --> ClosedLegitimate
  Verified --> ClosedFraud
  Verified --> Escalated: R8 / R9
  ClosedFraud --> AwaitingApproval: L1 / L2 actions
  Escalated --> AwaitingApproval
  AwaitingApproval --> Approved: APPROVED_BY edge
  AwaitingApproval --> Rejected: recorded too
  ClosedLegitimate --> [*]
  Approved --> [*]
  Rejected --> [*]
  
```

### 09 Before / after evidence

The recommendation is recorded before the question and again after the answer. HHG-018 is a disputed charge the card has paid 21 times before.

```mermaid
sequenceDiagram
  participant C as Customer report
  participant A as Agent
  participant G as TigerGraph
  participant P as Policy engine
  participant S as Simulator
  C->>A: "I never made this $39.08 purchase"
  A->>G: recurring_charge_probe(card, amount, product)
  G-->>A: 21 identical charges over 140 days, regular cadence
  A->>P: dispute + recurring match
  P-->>A: initial: CREATE_CASE, VERIFY_WITH_CUSTOMER, WARN_CUSTOMER (R7, no block)
  A->>S: customer_validation (best info per friction)
  S-->>A: recognises the recurring charge (assumption stated)
  A->>P: customer confirmed
  P-->>A: final: CREATE_CASE (§3a), WARN_CUSTOMER (R7), CLOSE_NO_FRAUD (R3)
  Note over A: fraud likelihood 0.53 → 0.02 · verdict legitimate
  
```

### 10 Data and install pipeline

Raw CSVs are staged once, calibrated against the closed cases, and loaded into Savanna by an idempotent, resumable installer.

```mermaid
flowchart LR
  RAW["Datasets/<br/>transactions · identity<br/>closed cases · case pack"] --> N1["01 normalise<br/>card_id recovery 100%"]
  N1 --> N2["02 behaviour vectors<br/>64-d"]
  N2 --> N3["03 policy → 41 chunks"]
  N3 --> N4["04 memory<br/>384-d narratives"]
  N4 --> N5["05 calibrate<br/>matched controls, LRs"]
  N5 --> N7["07 verify"]
  N4 --> N6["06 stage graph CSVs"]
  N6 --> I1["install: schema"] --> I2["vectors"] --> I3["load<br/>48 MB chunks"] --> I4["21 queries"] --> I5["projections"] --> I6["GDS WCC + PageRank"] --> I7["verify"]
  N7 --> RUN["run_20.py → cases/"]
  I7 --> RUN
  RUN --> AU["audit_answers.py<br/>0 issues"]
  
```

### 11 The temporal wall

Every read stops at the moment the alert opened; nothing the agent cites can postdate it, and the baseline stops 72 hours earlier still.

```mermaid
flowchart LR
  subgraph PAST["Visible"]
    BL["Card baseline<br/>t ≤ as_of − 72h"]
    WIN["Suspect window<br/>as_of − 72h … as_of"]
    CCv["Closed cases<br/>opened < as_of"]
  end
  WALL["as_of<br/>fixed by trigger_intake"]
  subgraph FUT["Invisible"]
    LATER["Later transactions"]
    LATERC["Later cases"]
  end
  BL --> WIN --> WALL
  CCv --> WALL
  WALL -. "no query reads past here" .-> LATER
  WALL -.-> LATERC
  
```

- **Audited**: no affected transaction or prior case in any answer file postdates its alert.

### 12 Trust boundaries

The language model sits outside the decision boundary; people sit on the approval boundary.

```mermaid
flowchart LR
  subgraph L["LLM (optional)"]
    L1["order tool calls"]
    L2["write summary, pattern, SAR text"]
  end
  subgraph D["Deterministic core"]
    D1["probability"]
    D2["verdict, pattern label"]
    D3["actions and routes"]
    D4["stop decision"]
  end
  subgraph H["People"]
    H1["approve / reject L1, L2"]
  end
  L2 -- "grounded(): unknown IDs → template" --> OUT["answer file"]
  D --> OUT
  D3 -- "L1 / L2 wait" --> H1
  L -. "cannot reach" .-x D
  
```

- **Enforced** by `test_core_cannot_import_an_llm` and by the policy engine dropping any action it did not produce.
- **Runs without an LLM**: same verdicts, template prose.

### 13 Policy rules as code

Every recommended action traces to one clause of the written Fraud Policy. The engine tests each rule against the case; the route for each action comes from §2, and the SAR decision from §3a, separately from the verdict.

```mermaid
flowchart TD
  IN["verdict · p_fraud · exposure · pattern<br/>connected cards · customer reply · signals"]
  IN --> R7{"R7: disputed charge matches<br/>own recurring pattern?"}
  R7 -- yes --> A7["CREATE_CASE · VERIFY · WARN_CUSTOMER<br/>never block"]
  IN --> REP{"customer reply?"}
  REP -- "denies · R2" --> A2["BLOCK_CARD · CREATE_CASE<br/>+ FILE_REPORT if over $1,000 or shared origin"]
  REP -- "confirms · R3" --> A3["CLOSE_NO_FRAUD"]
  REP -- "silent 24h · R4" --> A4["MONITOR_CARD · DECLINE pending<br/>escalate if over $500"]
  IN --> R1{"R1: single signal<br/>and p below 0.70?"}
  R1 -- yes --> A1["VERIFY_WITH_CUSTOMER / STEP_UP_AUTH<br/>before any block"]
  IN --> R5{"R5: 3+ small online auths in 1h<br/>then a larger one?"}
  R5 -- yes --> A5["DECLINE · STEP_UP_AUTH<br/>BLOCK if over $100 cleared"]
  IN --> R6{"R6: several cards, same device /<br/>region / email, one window?"}
  R6 -- yes --> A6["CREATE_CASE · FILE_REPORT<br/>MONITOR_CONNECTED_CARDS"]
  IN --> R8{"R8: uncertain and over $500,<br/>or evidence conflicts?"}
  R8 -- yes --> A8["ESCALATE_TO_ANALYST"]
  IN --> R9{"R9: coordinated abuse<br/>fitting no known pattern?"}
  R9 -- yes --> A9["CREATE_CASE · FILE_REPORT · ESCALATE<br/>pattern described in own words"]
  IN --> R10{"R10: 2+ cards confirmed or<br/>credentials compromised?"}
  R10 -- no --> NOALL["BLOCK_ALL_CARDS forbidden"]
  A1 & A2 & A3 & A4 & A5 & A6 & A7 & A8 & A9 --> ORD["order + de-duplicate<br/>drop anything the engine did not produce"]
  NOALL --> ORD
  ORD --> SAR{"§3a: fraud AND (over $1,000<br/>OR connected OR undocumented)?"}
  ORD --> RT["§2 route per action<br/>auto · L1 team lead · L2 fraud manager"]
  
```

- **§3a is its own test.** HHG-019 is fraud at 0.95, but $99.92 on one card with a documented pattern meets none of the conditions, so no SAR.
- **Guard.** An action that breaches a rule (a block on one weak signal, a block under R7) is refused, not just discouraged.

### 14 All twenty benchmark cases

Every case in the benchmark, grouped by the path it took from trigger to final action: 11 legitimate, 9 fraud, 2 SARs, and 5 cases that asked a question and changed their decision.

```mermaid
flowchart LR
  RS["Risk-model alert<br/>10 cases"]
  CR["Customer report<br/>9 cases"]
  AR["Analyst request<br/>1 case"]
  RS --> CLR["Graph evidence clears it<br/>p 0.03–0.08 · CLOSE_NO_FRAUD<br/>HHG-001, 005, 010, 012, 013, 015"]
  RS --> ASK["Thin evidence → R1 verify first<br/>reply confirms → R3 close<br/>HHG-002, 007, 017, 020"]
  RS --> PEER["Rare device, peers on 2 other cards<br/>fraud 0.95 · BLOCK_CARD · no SAR<br/>HHG-019"]
  CR --> R2["Denied, graph agrees → R2<br/>BLOCK_CARD · CREATE_CASE<br/>003 out-of-region · 004, 016 new device<br/>008, 009 account takeover · 011 new device + peers"]
  CR --> STR["Sub-threshold structuring · U1<br/>4 buys, $1,906.07 in 30 min<br/>R2 + R9 · SAR · escalate<br/>HHG-006"]
  CR --> REC["Recurring charge → R7<br/>verify → recognised → R3 close, no block<br/>HHG-018"]
  AR --> RING["Anonymous-proxy device ring · U2<br/>19 connected cards · WCC 54 · PageRank #2<br/>R6 + R9 · SAR · monitor connected<br/>HHG-014"]
  
```

- **Changed after evidence**: HHG-002, 007, 017, 018, 020.
- **SAR filed**: HHG-006, HHG-014.
- **Undocumented patterns**: HHG-006 (structuring), HHG-014 (proxy ring).

### 15 Analyst console and API

The console is a static page over one FastAPI process. Every number on screen is read from the answer files, the graph or the calibration tables; the only writes are approvals and the live re-run's case write.

```mermaid
flowchart LR
  subgraph PAGES["Pages · hash routes"]
    HOME["Home<br/>story + featured cases"]
    CASES["Cases · 5 tabs<br/>Overview · Evidence · Graph<br/>Similar cases · Audit trail"]
    SB["Scoreboard<br/>20 cases + audit · CSV"]
    APR["Approvals<br/>L1 / L2 queue"]
    MON["Monitoring<br/>self-raised alerts"]
    INS["Insights<br/>calibration · policy"]
  end
  subgraph API["FastAPI endpoints"]
    H["/api/health"]
    C["/api/cases/{id}"]
    G["/api/graph/{id}"]
    L["/api/investigate/{id}<br/>SSE live trace"]
    AP["/api/approvals<br/>POST approve / reject"]
    AU["/api/audit"]
    AUT["/api/autonomous"]
    CAL["/api/calibration · /api/policy"]
  end
  subgraph SRC["Sources"]
    J["cases/*.json"]
    TG[("TigerGraph<br/>via MCP")]
    AG["LangGraph agent"]
    AUDPY["eval/audit_answers.py"]
    AJ["benchmark/autonomous/"]
    LRJ["likelihood_ratios.json<br/>policy chunks"]
  end
  HOME --> H
  HOME --> C
  CASES --> C
  CASES --> G
  CASES -- "Re-run live" --> L
  SB --> AU
  APR --> AP
  MON --> AUT
  INS --> CAL
  C --> J
  G -- "case_chain" --> TG
  L -- "runs" --> AG
  AG -- "reads + writes" --> TG
  AP -- "APPROVED_BY edge" --> TG
  AU --> AUDPY
  AUDPY --> J
  AUT --> AJ
  CAL --> LRJ
  
```

- **Deep links**: `#/cases/HHG-019/evidence` opens a case on a tab.
- **Evidence tab** draws the probability path: trigger prior → each ledger entry → calibration and caps → final.
- **No build step**: vanilla JS, one `python ui/server.py`.

### 16 Autonomous monitoring

Outside the benchmark, the agent raises its own alerts over November–December from three sources and investigates each exactly as it would a bank alert. The sweeps find what a per-transaction score cannot, because the pattern only exists across several transactions or cards.

```mermaid
flowchart LR
  TX[("Nov–Dec transactions<br/>benchmark cards excluded")] --> S1["risk_score sweep<br/>bank model's top scores"]
  TX --> S2["structuring_sweep<br/>online bursts parked under<br/>a round authorisation limit"]
  TX --> S3["device_hub_sweep<br/>profiles where nearly every card<br/>came through an anonymous proxy"]
  S1 --> TRG["synthetic trigger<br/>found_by + as_of"]
  S2 --> TRG
  S3 --> TRG
  TRG --> AGT["same LangGraph agent<br/>same policy, same temporal wall"]
  AGT --> OUT["benchmark/autonomous/AUTO-*.json<br/>summary.csv · README"]
  OUT --> UI["Monitoring page"]
  
```

- **Never mixed** into `cases/`: the submission stays exactly the twenty benchmark answers.

### 17 Evaluation and verification

Weights are measured on July–September closed cases and tested on an October holdout the calibration never saw. The twenty answers are audited against the raw data, and two backends must agree on every case.

```mermaid
flowchart LR
  CC[("5,565 closed cases")] -- "Jul–Sep" --> CAL["05_calibrate.py<br/>matched controls → LR per signal<br/>damping fitted on a held-out split"]
  CAL --> LRT["likelihood_ratios.json"]
  CC -- "Oct holdout · 400" --> BT["eval/backtest.py"]
  LRT --> BT
  BT --> A1["as-seen arm<br/>AUC 0.921 · Brier 0.083"]
  BT --> A2["graph-only arm, trigger stripped<br/>AUC 0.520 · pattern acc. 0.471"]
  RUN["run_20.py"] --> ANS["cases/HHG-*.json"]
  ANS --> AUD["audit_answers.py<br/>schema · temporal wall · amounts<br/>policy rules · SAR §3a<br/>0 issues / 20"]
  ANS --> PAR["backend parity<br/>TigerGraph vs local mirror<br/>20 / 20 identical"]
  T["pytest · 64 tests"] --> NOLLM["core cannot import an LLM"]
  T --> POLT["policy rules · R7 cadence<br/>grounding · answer schema"]
  
```

- **Why two arms.** In this history the trigger is perfectly correlated with the label, so a single precision figure would measure the label, not the agent.
- **Ablation switch.** `SIGNALS_OFF=peer_purchases` forces a detector off so its worth can be measured.

### 18 Failure modes and fallbacks

Each dependency has one defined fallback, and each fallback shows up in the output rather than happening silently.

```mermaid
flowchart TD
  START["graph read"] --> M{"MCP call ok?"}
  M -- yes --> OK["rows · transport mcp"]
  M -- raises --> D{"pyTigerGraph direct ok?"}
  D -- yes --> OK2["rows · counted as mcp_fallback"]
  D -- "workspace asleep or down" --> ST{"GRAPH_STRICT=1?"}
  ST -- yes --> FAIL["fail closed: raise"]
  ST -- no --> LOC["local mirror<br/>status pill: Local mirror"]
  LLMQ["prose needed"] --> LQ{"key set and quota ok?"}
  LQ -- yes --> GR{"grounded(): cites only<br/>IDs in the evidence?"}
  GR -- yes --> PROSE["LLM text"]
  GR -- no --> TPL["template text"]
  LQ -- "no, or AGENT_USE_LLM=0" --> TPL
  WR["case write"] --> RB{"case_chain read-back<br/>counts match?"}
  RB -- yes --> WOK["written_to_graph true"]
  RB -- no --> WNO["written_to_graph false<br/>shown in the audit trail"]
  
```

- **Verdicts never depend on the LLM.** With or without a key the twenty answers are identical except for prose.

---

## The one idea

Everything that has to be defensible is deterministic, and everything that has
to be readable is generated.

```
┌──────────────────────────────────────────────────────────────────────────┐
│  LAYER 6 — ANALYST CONSOLE  (FastAPI + vanilla JS, no build step)       │
│  Home · Cases (overview, evidence, graph, similar cases, audit trail) ·  │
│  Scoreboard with audit · Approvals · Monitoring · Insights ·             │
│  live re-run over SSE · replay stepper · zoomable case subgraph         │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 5 — ORCHESTRATION  (LangGraph, typed state, capped loop)         │
│  trigger → case opener → planner → retrieval → memory → policy grounding │
│  → ledger → uncertainty → [provisional → evidence request ⟲ ×3]          │
│  → action recommender → permission gate → explainer → case writer        │
│  → read-back verification → memory consolidator                          │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 4 — DETERMINISTIC CORE  (pure Python, no LLM imports, tested)     │
│  Bayesian evidence ledger (28 measured signals) · Value of Information · │
│  policy-as-code (R1–R10, §3a, §6) · approval routing ·                   │
│  two-sided stopping rule · episode reconstruction ·                      │
│  hash-chained decision log                                               │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 3 — TOOL LAYER                                                   │
│  GraphStore interface (one contract, two backends) ·                     │
│  gateway → TigerGraph MCP server (tigergraph-mcp, stdio, 69 tools) ·     │
│  direct pyTigerGraph fallback per call · simulated action service        │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 2 — GSQL INVESTIGATION TOOLKIT  (21 installed queries)           │
│  card_baseline · episode_window · device_fanout · peer_purchases ·       │
│  shared_entity_ring · fraud_proximity · typology probes ·                │
│  behavioural_neighbours · policy_retrieve · hybrid_case_recall ·         │
│  card_community · case_chain · case_write_links                          │
│  GDS (GDBMS_ALGO): WCC + PageRank over ANON_CO_OCCURS                    │
├──────────────────────────────────────────────────────────────────────────┤
│  LAYER 1 — TIGERGRAPH SAVANNA 4.2.5  (graph + TigerVector, one store)   │
│  transaction subgraph · memory subgraph · FraudCase subgraph ·           │
│  vectors: case narratives (384d) · policy text (384d) ·                  │
│           transaction behaviour (64d, engineered)                        │
└──────────────────────────────────────────────────────────────────────────┘
```

Layer 4 contains every decision a bank would have to justify: the risk
arithmetic, the policy enforcement, the approval routing, the stopping rule.
None of it can call a model, and `tests/test_core.py::test_core_cannot_import_an_llm`
walks the AST of every file in `core/` and fails the build if that ever changes.

The LLM plans which primitives to run, synthesises evidence into prose, writes
the case summary and the SAR narrative, and describes an undocumented pattern in
its own words. It never produces a probability, an action, an approval route, an
exposure figure or a transaction id. If it proposes an action anyway,
`PolicyDecision.filter` drops it before it can reach an answer file.

---

## 1. Graph schema

### Transaction subgraph — loaded from the dataset

| Vertex | Primary id | Notable attributes |
|---|---|---|
| `Transaction` | `txn_id` | `ts`, `amount`, `product_cd`, `channel`, `risk_score`, `region`, `device_status` (id_15), `proxy` (id_23), `m_mismatch_count`, `behaviour_emb` **(vector, 64d)** |
| `Card` | `card_id` | `brand`, `card_type`, amount distribution, `home_region`, `community_id`, `hub_rank` |
| `Customer` | `customer_id` | `n_cards`, tenure |
| `DeviceProfile` | `DeviceInfo \| OS \| browser \| screen` | `n_cards`, `n_customers`, first/last seen |
| `BillingRegion` | `addr1` | `country`, `n_cards` |
| `EmailDomain` | domain | `is_free` |
| `ClosedCase` | `case_id` | `outcome`, `pattern`, `exposure_usd`, `narrative`, `narrative_emb` **(vector, 384d)** |
| `Pattern` | `pattern_id` | `source` (DOCUMENTED / **DISCOVERED**), `historical_precision`, `desc_emb` **(vector)** |
| `PolicyDoc` | `doc_id` | `kind`, `section`, `text`, `text_emb` **(vector, 384d)** |

Edges: `MADE_WITH`, `OWNED_BY`, `FROM_DEVICE`, `BILLED_IN`, `PURCHASER_EMAIL`,
`RECIPIENT_EMAIL`, `NEXT_TXN`, plus the closed-case links `CC_INVOLVES`,
`CC_ON_CARD`, `CC_CONNECTED_TO`, `CC_ON_DEVICE`.

`CO_OCCURS_WITH` is a **derived projection**: Card ↔ Card through a shared
device profile, carrying `weight`, `shared_device`, the window it spanned and
`via_anon_proxy`. It collapses a four-hop path into one, which is what makes
ring detection and the GDS algorithms cheap enough to run inside a live demo.
Generic browser fingerprints (>150 cards over six months) are excluded at build
time, because projecting them produces a hairball in which every card is
connected to every other card.

### Case subgraph — written by the agent

`FraudCase` (renamed from `Case`, a reserved word on 4.2) · `Evidence` · `Finding` · `Decision` · `RecommendedAction` ·
`EvidenceRequest` · `SAR` · `Analyst`

This is the part a judge can inspect. `case_chain(graph_case_id)` walks
`Case → Evidence → Finding → Decision → RecommendedAction → SAR` and
reconstructs the whole investigation from the database, without opening the JSON.
Both are written from the same payload in `report/answer.py`, so they cannot
drift apart.

---

## 2. Two embedding spaces, one database

| Vector | Dim | Built from | Answers |
|---|---:|---|---|
| `ClosedCase.narrative_emb` | 384 | 5,565 analyst narratives + their structured facts | "have we investigated something that *reads* like this?" |
| `PolicyDoc.text_emb` | 384 | policy clauses, typologies, regulatory references | "which rule governs this?" |
| `Transaction.behaviour_emb` | **64** | **engineered, not textual** | "which confirmed-fraud transactions *behave* like this one?" |

The behaviour vector is the interesting one. `V1`–`V339` carry real Vesta signal
and are hopeless as LLM context — 339 unnamed columns is not evidence, it is
noise with a schema. Compressed by incremental PCA to 24 components and
concatenated with rank-normalised `C1`–`C14`, `D1`–`D15`, the `M` trinary flags
and amount/velocity features, they become a retrieval key: a nearest-neighbour
query over confirmed-fraud transactions, grounded in data rather than in a
model's impression of a table.

Having both spaces *in the same store as the graph* is the reason this project
belongs on TigerGraph rather than on a graph database plus a vector database.

---

## 3. The signature query

Pure vector search returns cases that *sound* similar. Pure traversal returns
cases that are *connected*. Neither is what an analyst means by "have we seen
this before".

```gsql
candidates = vectorSearch({ClosedCase.narrative_emb}, query_vec, k * 8);
candidates = SELECT c FROM candidates:c WHERE c.opened_at < as_of
             ACCUM @@vec_score += (c -> c.@distance);

linked_d = SELECT c FROM seed_dev:v -(CC_DEVICE_OF:e)- ClosedCase:c
           WHERE c.opened_at < as_of
           ACCUM @@shared += (c -> 1);

result = SELECT c FROM (candidates UNION linked_t UNION linked_c UNION linked_d):c
         ACCUM c.@score += 0.55 * @@vec_score.get(c)
                         + 0.45 * (1.0 - exp(-0.6 * @@shared.get(c)))
         ORDER BY c.@score DESC LIMIT k;
```

Two details carry their weight. The saturating term on the graph leg means the
first shared entity is worth a lot and the fourth is worth very little, so one
busy device profile cannot dominate the ranking. And the `as_of` guard is on
**both** legs — a memory system that can retrieve a case opened after the one it
is reasoning about is not a memory system, it is a leak, and every number
downstream of it is fiction.

---

## 4. The uncertainty engine

### Hypothesis space

Seven competing explanations, which are exactly the enum the answer file is
scored on, so nothing is lost in a mapping step:

`none` · `card_testing` · `card_not_present_fraud` ·
`card_not_present_new_device` · `out_of_region_use` · `account_takeover` ·
`undocumented`

The prior is conditioned on **how the alert arrived**, not on the model's score:
a proactive customer dispute and a risk-score alert have genuinely different base
rates, and the dataset states outright that above 0.70 most flagged transactions
turn out legitimate.

### Where the likelihood ratios come from

1. **Measured** — every closed investigation replayed through the same extractor
   the agent uses, under its own `as_of`. See `eval/reports/calibration.md`.
2. **Structural** — hard matchers for the two undocumented typologies, whose
   signature is near-deterministic and whose support in the history (5 and 4
   cases) is too thin for a smoothed estimate to carry.
3. **Solicited** — customer and step-up responses, entered with an explicit
   reliability below 1.0, because customers forget and channels fail.

An LLM is never permitted to emit a likelihood ratio. It would produce
confident-looking floats with no basis, and the reliability curve would expose it.

### Two calibration traps, and what they cost

Both were found by measuring, not by reasoning, and both inverted the agent
before they were fixed.

**Selection.** Calibrating straight off the closed-case file makes every signal
point the wrong way. Every *cleared* case in the history got there by scoring
high on the bank's model — it is a travel trip, a new phone, an unusual but real
purchase. Every *confirmed* case got there because a cardholder rang up, and
those are often small, ordinary-looking transactions. So inside that file "looks
anomalous" predicts **cleared**, and an agent trained on it learns to wave fraud
through. The fix is a third stratum: ordinary transactions from the same four
months that no investigation ever touched.

**Confounding.** An unmatched negative sample is confounded by card tenure.
Confirmed-fraud cases sit disproportionately on long-lived, busy cards, so "the
device and region are already established" comes out *correlated with fraud*.
The fix is a matched control design — each fraud case paired with another
transaction **on the same card** — which turns the question into the one an
analyst actually asks: what is different about *this* transaction compared with
the rest of this card's behaviour?

### The episode window

Anomaly is measured as **suspect window against established baseline**, never
against the card's whole history up to the alert. Measuring against everything
lets the first legs of a fraud episode teach the baseline that the new device
and the new region are normal, so by the time the alert fires nothing looks
unusual. The baseline cutoff is `as_of − 72h`; 75% of closed-case episodes open
within 29 hours of their alert.

### Stopping — two-sided

1. **Decisive** — belief clears the threshold the required action class demands,
   with enough separation from the runner-up, on at least two independent pieces
   of evidence (policy §6's own wording).
2. **Exhausted** — no permitted evidence action carries enough information per
   unit of friction to justify asking.

The second is the one that matters. Almost any agent can stop when confident.
Stopping because *further investigation would not repay its cost* is a different
and more defensible claim, and it is what a real fraud desk does.

### Value of Information

Each evidence action is scored by expected reduction in Shannon entropy over the
hypothesis space, divided by its **friction** cost — not its monetary cost.
Pinging a cardholder at two in the morning has a real price even though the API
call is free. The policy gate applies to *asking* as well as acting, so the agent
can say: the highest-value next step is customer validation, but the contact
limit forbids a third contact this week, so I am escalating instead.

---

## 5. Policy as code

The bank's policy ships as prose. Prose in a prompt is a suggestion. Rules
R1–R10, the case-versus-report test in §3a and the stopping conditions in §6 are
implemented as pure functions over case state, each carrying the clause id it
enforces and the verbatim source text it was compiled from — loaded at runtime
from `data/policy/chunks.jsonl`, so a citation cannot drift from the document it
claims to quote.

The agent chooses only from `permitted ∪ required`. Approval routing lives in
`core/permissions.py` and is pure data plus arithmetic. An agent that can be
*argued* into executing a block is not a control.

---

## 6. Repository layout

```
ingest/       01 normalise · 02 behaviour vectors · 03 policy corpus
              04 memory index · 05 calibrate · 06 stage graph CSVs · 07 verify
graph/        ddl/ · loading/ · queries/ · algorithms/ · install.py
src/fraudagent/
  config.py           every tunable dial, env-overridable
  graphstore/         base.py (contract) · local.py (mirror) · tigergraph.py
                      matchers.py (window logic shared by both backends)
  core/               hypotheses · signals · evidence_ledger · voi · stopping
                      policy_engine · permissions · episode · ledger
  agent/              graph.py (LangGraph) · nodes.py · state.py
                      llm.py · simulator.py
  memory/             embeddings.py
  report/             answer.py (schema + validation) · narrative.py
  mcp_servers/        simulated_actions.py
eval/         backtest.py → reports/
benchmark/    run_20.py → cases/ · monitor.py → autonomous/
ui/           server.py + static/
tests/        core purity, policy, stopping, VoI, ledger, matchers,
              answer schema, backend parity
```

---

## 7. What is deliberately not built

- **No custom fraud classifier.** There are no labels to train one on, and the
  bank's score is given. The value added here is investigation and action.
- **No real external identity or IP lookups.** The data is anonymised; `card1`
  is a surrogate integer and there are no real IPs. A live lookup returns noise
  dressed as evidence. The stubs are deterministic and say so in every receipt.
- **No production auth in the console.** Roles are a dropdown.
- **No multi-model routing.** Not a rubric item, and the model is not on the
  critical path.
