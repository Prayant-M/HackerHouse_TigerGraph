"""Generate the architecture diagram set: one Markdown file per diagram (Mermaid
source + full explanation), the raw .mmd sources, and PNG/SVG exports when the
local mermaid-cli is installed (build/mmdc). Numbers quoted in the text come
from eval/reports and the answer files of the final run.

    python docs/architecture/build.py            # md + mmd (+ png/svg if mmdc present)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_IMG = ROOT / "docs" / "diagrams"
MMDC = ROOT / "build" / "mmdc" / "node_modules" / ".bin" / ("mmdc.cmd" if sys.platform == "win32" else "mmdc")

THEME = """%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%"""

CLASSES = """
classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
"""

D: list[dict] = []


def add(num: str, slug: str, title: str, kind: str, src: str, body: str) -> None:
    D.append({"num": num, "slug": slug, "title": title, "kind": kind, "src": src.strip("\n"),
              "body": body.strip("\n")})


# ------------------------------------------------------------------------ 01
add("01", "system", "System architecture — end to end", "flowchart", r"""
flowchart TB
  subgraph IN["Alert sources"]
    direction LR
    A1["risk_score alert<br/>(bank model)"]:::data
    A2["customer_report<br/>(dispute message)"]:::data
    A3["analyst_request<br/>(analyst note)"]:::data
    A4["alert inbox<br/>alert_pipeline.py (C9)"]:::data
  end

  subgraph RUN["One command: make case CASE=HHF-0xx (benchmark/run_case.py)"]
    direction TB
    V["Input guardrails<br/>schema · ids · trigger type · txn exists<br/>exit 3 on invalid input"]:::guard
    W["Workspace wake + health precondition<br/>graph loaded? else FAILED_DEPENDENCY (exit 2)"]:::guard
    REC["RecordingStore<br/>every tool call hashed + stored<br/>canary check · fail-closed wrapper"]:::guard
  end

  subgraph AG["Agent (LangGraph, 15 nodes) — src/fraudagent/agent"]
    direction TB
    FW["Hostile-text firewall<br/>UntrustedText · allow-listed facts only"]:::guard
    LOOP["Investigate → recall → ledger → VOI<br/>ask one question → re-assess (≤3 rounds)"]:::core
    LAY["Decision layers<br/>policy R1–R10 · §3a · conformal · proof gate · containment"]:::core
    EXP["Explainer (LLM prose only)<br/>grounded() · quality floor · template fallback"]:::llm
    CW["case_writer → case_write (1 installed query)<br/>read-back via case_chain"]:::tg
  end

  subgraph TGX["TigerGraph Savanna 4.2.5 — graph FraudGraph"]
    direction TB
    MCP["tigergraph-mcp (stdio)<br/>client allow-list: run_installed_query, get_node, get_node_edges"]:::tg
    Q["34 installed GSQL queries<br/>agent_role: EXECUTE on 25"]:::tg
    G[("650,938 txns · 14,849 cards · 13,553 customers<br/>9,729 devices · 5,585 closed cases<br/>TigerVector 384-d narratives + 64-d behaviour")]:::tg
    GDS["GDS WCC + PageRank<br/>time-sliced WCC ring_at_asof"]:::tg
  end

  subgraph OUT["Outputs"]
    direction LR
    ANS["cases/HHF-0xx.json<br/>case · SAR · actions before/after<br/>proof · attestations · telemetry"]:::ok
    UI["Analyst console (FastAPI)<br/>Proof · Containment · Replay · Case life"]:::ok
    GOV["Governance<br/>signed approvals · feedback · detectors"]:::human
  end

  IN --> V --> W --> REC --> FW --> LOOP --> LAY --> EXP --> CW
  LOOP <-->|"graph reads"| MCP
  CW -->|"single write path"| MCP
  MCP --> Q --> G
  G --- GDS
  CW --> ANS --> UI
  UI -->|"Bearer token → role (server-side)"| GOV
  GOV -->|"governance_write (console-only)"| Q
  LLMP["LLM provider (Google)<br/>sees evidence brief only"]:::llm
  EXP -.->|"egress logged"| LLMP
""" + CLASSES, """
**What it is.** A fraud-investigation agent a bank could run. Every alert enters through
one command, is checked before anything runs, is investigated against TigerGraph through
the TigerGraph MCP server, is decided by a deterministic policy core that cannot import an
LLM, and leaves a case written back to the graph plus an answer file in which every claim
is attested.

**Read it top to bottom**

1. **Alert sources.** The three trigger types in the brief (11 risk-score, 4 customer-report,
   3 analyst-request cases in the final pack), and an alert inbox for the autonomous pipeline
   (C9), which runs the same code path.
2. **One command** (`benchmark/run_case.py`). Input guardrails reject an unknown case id, a
   missing field, a bad trigger type or a transaction that is not in the graph (exit 3, no answer
   file). A health precondition refuses an empty or unreachable graph (exit 2, signed
   `FAILED_DEPENDENCY`), and waits a bounded time for an auto-stopped Savanna workspace.
   `RecordingStore` wraps every graph call: it records the response by content hash, turns any
   graph error into a named dependency failure, and aborts if a future-dated canary leaks
   through the temporal wall.
3. **Agent** (LangGraph, 15 nodes). Free text is `UntrustedText` from intake on; only
   allow-listed extractor facts (denies / recognises / analyst asks about a ring) can reach a
   decision. The loop investigates, recalls prior cases (vector + traversal fused in one GSQL
   query), folds measured likelihood ratios into a 7-hypothesis posterior, picks the one question
   with the highest information per unit of customer friction, and re-assesses (≤ 3 rounds,
   wall-clock and token budgets). The decision layers run in a fixed order. The LLM writes prose
   only, and only from a brief whose figures are already fixed.
4. **TigerGraph.** All reads go through installed queries reached via the MCP server; the
   agent's graph role may execute 25 of the 34 installed queries and nothing else; the one write
   is `case_write`. Graph algorithms: WCC/PageRank on the anonymous-proxy projection and a
   *time-sliced* WCC that feeds the containment plan.
5. **Outputs.** The answer file (graded 18/18 clean by the organisers' grader), the analyst
   console, and governance: approvals are bearer-token → role on the server, Ed25519-signed and
   hash-chained, and mirrored into the graph through a console-only query.

**Egress.** Savanna (all graph data) and the LLM provider (evidence brief only). Nothing else.
Embeddings are computed locally. See `11-trust-boundaries.md`.
""")

# ------------------------------------------------------------------------ 02
add("02", "agent-loop", "The investigation loop (LangGraph)", "flowchart", r"""
flowchart TB
  T["1 trigger_intake<br/>as_of fixed · text → UntrustedText<br/>text facts + hostile spans"]:::guard
  O["2 case_opener<br/>trigger-conditioned prior<br/>(January: softened, risk prior neutral)"]:::core
  P["3 evidence_planner (LLM)<br/>suggests tools · full toolkit runs anyway<br/>text only inside a data block"]:::llm
  R["4 graph_retrieval<br/>28 measured signals via installed GSQL"]:::tg
  M["5 memory_recall<br/>hybrid_case_recall (vector ⨝ traversal)<br/>compromise_watch read-back"]:::tg
  G["6 policy_grounding<br/>policy_retrieve (GraphRAG over policy)"]:::tg
  L["7 ledger_update<br/>Bayes in log space · feedback scaling<br/>p_graph_only for conformal"]:::core
  U{"8 uncertainty_assessor<br/>two-sided stopping rule<br/>VOI per unit of friction"}:::core
  PV["9 record_provisional<br/>initial actions + routes<br/>(before any evidence returns)"]:::core
  E["10 evidence_gap_resolver<br/>ask ONE question (simulated reply)<br/>customer · step-up · analyst"]:::human
  AR["11 action_recommender<br/>verdict → conformal → policy → proof → gate<br/>→ containment → detectors"]:::core
  PG["12 permission_gate<br/>execute auto only · L1/L2 wait"]:::guard
  X["13 explainer (LLM)<br/>prose from fixed brief · template fallback"]:::llm
  CW["14 case_writer<br/>case_write → read-back check"]:::tg
  MC["15 memory_consolidator<br/>verify hash chain"]:::ok

  T --> O --> P --> R --> M --> G --> L --> U
  U -->|"not enough, round < 3"| PV --> E --> U
  U -->|"decisive / exhausted / cap / budget"| AR --> PG --> X --> CW --> MC
""" + CLASSES, """
**Why a loop and not a pipeline.** The answer format demands a recommendation *before* and
*after* evidence, with what changed. That can only be produced honestly by an agent that
commits under uncertainty (node 9), asks (node 10) and revises (node 11).

**Who may call a model.** Only node 3 (tool *suggestions*; the full toolkit runs regardless,
so a planner cannot silently skip the ring query) and node 13 (prose). Neither can produce a
probability, action, route or id: those come from `core/`, which a test proves cannot import
an LLM.

**Stopping.** Node 8 stops when the posterior is decisive on ≥ 2 independent pieces of
evidence (policy §6), when no permitted question would repay its friction cost, at the round
cap (3), or at the wall-clock / token budget, and the reason is written to `stop_reason`.

**Node 11 in order** (see `03-decision-layers.md`): threshold verdict → conformal widening →
policy R1–R10 and §3a → proof object → one-way gate → predictive containment → new-typology
detectors (evidence only).

**State.** Every node appends to `trace`, which is what the console streams live and what
the answer's audit record keeps; every decision is appended to a hash-chained ledger that is
verified before the case leaves the agent.
""")

# ------------------------------------------------------------------------ 03
add("03", "decision-layers", "Decision layers — from evidence to a defensible action", "flowchart", r"""
flowchart LR
  EV["Attested facts<br/>28 graph signals · memory · solicited replies<br/>allow-listed text facts"]:::tg
  POST["Posterior over 7 hypotheses<br/>measured LRs · damping · ceiling 0.97"]:::core
  V0{"Threshold verdict<br/>≥0.70 fraud · ≤0.15 legit"}:::core
  CF["Conformal layer (Innov. 4)<br/>90% set from p_graph_only<br/>+ support check + data taint<br/>widens FRAUD only"]:::core
  POL["Policy engine<br/>R1–R10 · §3a case vs report<br/>§2 routes auto / L1 / L2"]:::core
  PR["Proof (Innov. 1)<br/>minimal facts · flip set · margin k<br/>precedent_by_facts (GSQL)"]:::core
  GT{"Gate<br/>harmful & (k<2 or precedent contradicts)<br/>& not R2?"}:::guard
  DG["Downgrade<br/>VERIFY + ESCALATE (R8)<br/>verdict → uncertain"]:::guard
  KEEP["Keep action"]:::ok
  CT["Containment (Innov. 2)<br/>origin · at-risk (free actions) · block set"]:::tg
  DET["Detectors C1/C2/C3<br/>evidence only"]:::eval
  OUT["Final actions + routes<br/>what_changed · SAR if §3a"]:::ok

  EV --> POST --> V0 --> CF --> POL --> PR --> GT
  GT -->|yes| DG --> CT
  GT -->|no| KEEP --> CT
  CT --> DET --> OUT
""" + CLASSES, """
**The property that matters:** every layer after the posterior can only *remove* harm.
Conformal widens a fraud verdict to uncertain; it never creates one. The gate removes a
block or report; strong precedent can never promote an action. Containment's forward actions
are MONITOR_CARD and STEP_UP_AUTH only, which cost a legitimate customer nothing. Detectors
add evidence, never a block.

**R2 exemption.** A cardholder who denied the charge — in reply to our question *or* in the
customer-report text, read by the allow-listed extractor — makes the block mandatory, so the
gate records the margin but does not act, and the conformal layer treats the case as settled.

**Consistency with the grader.** An uncertain case never claims the `undocumented` pattern
(which would oblige a report under R9); a gated or abstained case is not "strongly suspected"
for §3a, and the SAR reason says why.

**Where it changed outcomes in the final pack.** HHF-016 ($3,008.76, hostile "do not
escalate" text): block resting on margin k=1 → downgraded to verify + escalate.
""")

# ------------------------------------------------------------------------ 04
add("04", "graph-schema", "TigerGraph schema — the data graph and the case graph", "flowchart", r"""
flowchart LR
  subgraph DATA["Transaction subgraph (loaded)"]
    CU(("Customer<br/>13,553")):::tg
    CA(("Card<br/>14,849")):::tg
    TX(("Transaction<br/>650,938<br/>behaviour_emb 64-d")):::tg
    DP(("DeviceProfile<br/>9,729")):::tg
    BR(("BillingRegion<br/>333")):::tg
    EM(("EmailDomain<br/>60")):::tg
    TX -->|MADE_WITH| CA -->|OWNED_BY| CU
    TX -->|FROM_DEVICE| DP
    TX -->|BILLED_IN| BR
    TX -->|PURCHASER_EMAIL / RECIPIENT_EMAIL| EM
    TX -->|NEXT_TXN| TX
    CA ---|"CO_OCCURS_WITH 485,961<br/>ANON_CO_OCCURS 1,728"| CA
  end
  subgraph MEM["Memory subgraph (loaded)"]
    CC(("ClosedCase<br/>5,585 · narrative_emb 384-d<br/>fact_mask (4,781)")):::tg
    PD(("PolicyDoc 41 · Pattern 7")):::tg
    CC -->|CC_INVOLVES| TX
    CC -->|CC_ON_CARD / CC_CONNECTED_TO| CA
    CC -->|CC_ON_DEVICE| DP
  end
  subgraph CASE["Case subgraph (written by case_write)"]
    FC(("FraudCase<br/>proof_margin · gate_applied<br/>conformal_set · lifecycle_state")):::ok
    EVD(("Evidence")):::ok
    DEC(("Decision<br/>hash chain")):::ok
    RA(("RecommendedAction")):::ok
    ER(("EvidenceRequest")):::ok
    SAR(("SAR")):::ok
    SC(("CaseStateChange")):::ok
    FC --> EVD & DEC & RA & ER & SAR & SC
    FC -->|INVESTIGATES_TXN / CARD / CUSTOMER / DEVICE| TX
    FC -->|CONNECTED_CARD| CA
    FC -->|RECALLED_CASE| CC
    FC -->|CITES_POLICY| PD
    FC -->|"COMPROMISE_POINT<br/>window · lift · p"| DP
    FC -->|"CHILD_CASE (WATCH)"| FC
  end
  subgraph GOVN["Governance (console-only write)"]
    AP(("ApprovalRecord<br/>signed · chained")):::human
    AF(("AnalystFeedback")):::human
    DT(("Detector")):::human
    SCH(("SchemaChange")):::human
    AP -->|APPROVAL_OF| FC
    AF -->|FEEDBACK_ON| FC
  end
""" + CLASSES, """
**Three subgraphs in one database.** The *transaction* subgraph is the evidence surface. The
*memory* subgraph holds the bank's 5,585 closed investigations (now including the 20 Round 1
cases with their real outcomes) with 384-d narrative vectors for TigerVector search and a
**fact_mask** bitmask — each closed case's replayed fact vector — so proof precedent is one
GSQL subset match. The *case* subgraph is what the agent writes: an investigation can be
reconstructed by traversal alone (`case_chain`), and the answer only claims
`written_to_graph: true` after that read-back succeeds.

**Final-round additions** (`graph/ddl/06_final_round.gsql`): `ClosedCase.fact_mask`,
`COMPROMISE_POINT` (FraudCase → device / region / email, carrying window, lift and p-value),
`CHILD_CASE` (WATCH children for at-risk cards), `CaseStateChange`, and the governance
vertices `ApprovalRecord`, `AnalystFeedback`, `Detector`, `SchemaChange`.

**Live state at demo time:** 650,938 transactions (Jul 2016 – 31 Jan 2017), 5,585 closed
cases, 20 written FraudCases with 148 evidence items, 50 state changes, a `COMPROMISE_POINT`
from the HHG-014 ring to its origin device, and 25 WATCH child cases.
""")

# ------------------------------------------------------------------------ 05
add("05", "queries-and-privilege", "Installed queries, MCP and least privilege", "flowchart", r"""
flowchart TB
  subgraph AGENT["Agent process"]
    GW["_Gateway<br/>reads + allow-listed installed queries<br/>NO upsert methods"]:::guard
    AQ["allowed_queries()<br/>parsed from graph/queries/*.gsql<br/>minus governance_write"]:::guard
  end
  subgraph MCPS["tigergraph-mcp server"]
    TL["client allow-list (TG_ALLOWED_TOOLS)<br/>run_installed_query · get_node · get_node_edges<br/>refuses add_node / add_edge / schema tools"]:::guard
  end
  subgraph TGQ["Installed GSQL (34)"]
    direction LR
    R1["Investigation reads (17)<br/>card_baseline · card_window · episode_window<br/>card_testing / threshold_structuring / mixed_channel<br/>out_of_region / recurring_charge probes<br/>device_fanout · peer_purchases · shared_entity_ring<br/>fraud_proximity · behavioural_neighbours<br/>hybrid_case_recall · policy_retrieve · card_community"]:::tg
    R2["Final-round reads (7)<br/>ring_at_asof (time-sliced WCC)<br/>origin_counts · origin_touchers · ring_exposure<br/>precedent_by_facts · compromise_watch · data_gaps"]:::tg
    WR["case_write<br/>the ONLY agent write"]:::ok
    GV["governance_write<br/>console only"]:::human
    LD["build_* projections · GDS installers<br/>loader (superuser) only"]:::data
  end
  ROLE["agent_role (RBAC, live)<br/>EXECUTE on 25 queries incl. case_write"]:::guard
  CROLE["console_role<br/>EXECUTE governance_write, case_chain, data_gaps"]:::human

  GW --> AQ --> TL --> R1 & R2 & WR
  ROLE -.-> R1 & R2 & WR
  CROLE -.-> GV
  GW -. "MCP down → direct same-graph<br/>transport_degraded=true<br/>(MCP_STRICT=1 → exit 2)" .-> TGQ
""" + CLASSES, """
**Least privilege, enforced three times.** (1) On the server: `agent_role`
(`graph/rbac.gsql`, created live on the workspace) may EXECUTE the investigation queries and
`case_write`, nothing else. (2) In the MCP client: only three MCP tools can be called; the
server's `add_node`, `add_edge` and schema tools are refused. (3) In the agent: the gateway has
no upsert method at all and refuses any query not defined in `graph/queries/`.

**One write path.** `case_write` takes one JSON document (the same payload as the answer file)
and can only create the case subgraph and link it to entities that already exist. Upsert
semantics make "same case twice" idempotent: same vertex ids, no duplicate evidence.

**The LLM never sees a query tool.** It is not an MCP client.

**Degradation.** If the MCP server dies mid-run, the gateway falls back per call to the direct
pyTigerGraph connection to the *same graph* and marks the answer `transport_degraded: true`;
with `MCP_STRICT=1` it stops instead (drill `mcp_down`: PASS on both paths).

**Parity.** The local mirror implements the same contract; 9 parity tests (incl.
`ring_at_asof`, `origin_counts`, `data_gaps`) agree with live TigerGraph, and the three final
cases re-run on TigerGraph reproduced the mirror's answers exactly.
""")

# ------------------------------------------------------------------------ 06
add("06", "proof-carrying-verdicts", "Innovation 1 — proof-carrying verdicts", "flowchart", r"""
flowchart TB
  F["Case facts<br/>(fired signals · memory · solicited replies)"]:::tg
  DEC["decide(facts) — the pure core<br/>rebuilds the ledger with the SAME add_signal<br/>+ conformal + feedback scaling"]:::core
  MIN["Minimal sufficient facts<br/>greedy deletion, weakest first<br/>(irredundant)"]:::core
  FLIP["Flip set & margin k<br/>singles → pairs → triples<br/>(≤ 2,500 core calls)"]:::core
  PREC["precedent_by_facts (GSQL)<br/>ClosedCase.fact_mask ⊇ mask<br/>opened_at < as_of"]:::tg
  REP["reproduces_live?<br/>fact replay == live decision"]:::eval
  GATE{"harmful AND (k < 2 OR ≥5 precedents ≥50% cleared)<br/>AND not R2"}:::guard
  DOWN["VERIFY_WITH_CUSTOMER + ESCALATE_TO_ANALYST<br/>reason stated in the answer"]:::guard
  KEEP["action kept<br/>margin recorded"]:::ok
  UI["Console Proof tab<br/>flip any fact live"]:::ok
  F --> DEC --> MIN & FLIP & REP
  MIN --> PREC
  FLIP --> GATE
  PREC --> GATE
  GATE -->|yes| DOWN
  GATE -->|no| KEEP
  MIN & FLIP & PREC --> UI
""" + CLASSES, """
**Claim.** Every answer ships a proof an examiner can check in five minutes: the smallest set
of attested facts that forces the action, the smallest set whose removal flips it (its
robustness margin *k*), and how the bank ruled on closed cases that had exactly those facts. A
harmful action resting on a thin or contradicted proof is downgraded before anyone is wronged.

**Why it can be computed rather than written.** The decision core is a pure function. The
proof replays it through the same `EvidenceLedger.add_signal` the agent used (with the
conformal layer and any analyst-feedback scaling), so it is a proof of the decision actually
taken; `reproduces_live` records that it matched.

**Measured on the October holdout** (fitted on July–September; `eval/reports/proof_holdout.md`):

| | harmful actions | on legitimate cases | error rate |
|---|--:|--:|--:|
| margin k = 1 | 181 | 65 | **0.36** |
| margin k ≥ 2 | 31 | 5 | **0.16** |

| arm | legit customers acted against | frauds acted on |
|---|--:|--:|
| no gate (Round 1) | 70 | 142 |
| margin + precedent (the gate) | **5** | 26 |

Fragility predicts error, so the gate is claimed — and its cost is stated next to it: the
frauds it does not block are escalated (verify + escalate), not dropped. Precedent alone rarely
fires (3 contradictions on the holdout); the margin carries the gate.

**Final pack.** Every one of the 18 answers carries a proof. HHF-016 is the case where the
gate changed the action: a $3,008.76 block resting on k=1 became verify + escalate. HHF-001 and
HHF-002 kept their blocks at k=2 with 1,227 precedents sharing the minimal fact.
""")

# ------------------------------------------------------------------------ 07
add("07", "predictive-containment", "Innovation 2 — predictive containment from the point of compromise (C7 + C1)", "flowchart", r"""
flowchart LR
  RING["Ring cards (hit)<br/>case card + connected cards"]:::tg
  TS["ring_at_asof<br/>seeded WCC on the card-device<br/>projection CUT AT as_of"]:::tg
  OC["origin_counts (GSQL)<br/>entities touched 45→3 days before<br/>device · region · email · product×$25 band"]:::tg
  LIFT["Lift vs matched controls<br/>+ hypergeometric p<br/>p<0.01 · ≥3 ring cards · ≤25 controls"]:::core
  ORG["Compromise origin"]:::ok
  FWD["origin_touchers + time-sliced component<br/>cards NOT yet hit"]:::tg
  FREE["MONITOR_CARD +<br/>STEP_UP_AUTH<br/>WATCH child case (C14)<br/>zero blocks on innocents"]:::ok
  EXPO["ring_exposure<br/>attested suspect txns per card"]:::tg
  BS["Block set<br/>block only where fraud established<br/>≥90% of established exposure<br/>others: step-up (R1) · R10 respected"]:::guard
  WB["case_write → COMPROMISE_POINT edge<br/>window · lift · p"]:::tg
  RB["compromise_watch<br/>later cases read it back"]:::tg
  RING --> TS --> FWD
  RING --> OC --> LIFT --> ORG --> FWD --> FREE
  RING --> EXPO --> BS
  ORG --> WB --> RB
""" + CLASSES, """
**Claim.** Containment usually looks backward (block the cards already hit). The bigger saving
is forward: find where the ring was compromised, then protect the cards that passed through the
same point but have not been hit yet, using only actions that cost a legitimate customer
nothing.

**Backtest** (80 rings from the closed history: 6 explicit, 74 implied by shared rare devices;
future data scores, never decides; `eval/reports/containment_backtest.md`):

| arm | flagged | precision | lift | loss pre-empted |
|---|--:|--:|--:|--:|
| device fan-out (obvious) | 100,189 | 0.20 | 2.67× | — (100k step-ups) |
| **origin lift with controls** | 246 | 0.26 | **3.57×** | $193,907 |
| origin by raw counts (ablation) | 39,838 | 0.04 | **0.53×** | — |
| **time-sliced WCC (as_of)** | 23,042 | **0.374** | **5.05×** | $14.41M |
| all-time component (ablation) | 24,826 | 0.354 | 4.78× | $14.91M |
| **agent: origin + time-sliced** | 23,211 | 0.372 | 5.03× | **$14.42M** |

Every arm has **zero blocks on innocent customers** by construction. Two ablations carry the
claim: matched controls are what make an origin usable (0.53× without them), and cutting the
graph at as_of beats the all-time component (higher precision with fewer cards flagged). Honest
note: fan-out over *rare* devices alone scores 0.49 — but these rings are themselves defined by
rare shared devices, so that baseline is favoured by construction.

**Live demo:** HHG-014 (19-card ring behind an anonymising proxy): origin = the SM-G935F device
(lift ≈ 4,946, p < 1e-20), 141 at-risk cards protected with step-up only, 1 block on the
established card, `COMPROMISE_POINT` + 25 WATCH child cases written to the graph.
""")

# ------------------------------------------------------------------------ 08
add("08", "conformal-abstention", "Innovation 4 — conformal abstention under the January shift (C11)", "flowchart", r"""
flowchart LR
  CAL["Calibration<br/>Aug–Sep replays: 2,437 fraud · 1,340 legit<br/>nonconformity = 1 − p(true class)<br/>label-conditional, α = 0.10"]:::eval
  Q["Class quantiles<br/>fraud in set if p ≥ 0.087<br/>legit in set if p ≤ 0.742"]:::core
  P["p_graph_only<br/>(before any solicited reply)"]:::core
  SUP["Support check<br/>10-NN behaviour distance<br/>> 95th pct ⇒ outside support"]:::tg
  TAINT["Data-quality taint (C11)<br/>missing identity · empty region<br/>placeholder · thin history"]:::guard
  SET{"Prediction set"}:::core
  U["uncertain<br/>R8: ESCALATE if > $500 or conflict<br/>else VERIFY"]:::guard
  F["fraud verdict stands"]:::ok
  CAL --> Q --> SET
  P --> SET
  SUP -->|widen| SET
  TAINT -->|widen| SET
  SET -->|"{fraud, legit} or {}"| U
  SET -->|"{fraud}"| F
""" + CLASSES, """
**Claim.** "Uncertain" is chosen by a coverage guarantee, not a hand-picked threshold, and it
widens automatically when a case looks like nothing calibration has seen — the brief's warning
that the bank's model has never seen January.

**Measured** (`eval/reports/conformal.md`): October empirical coverage 0.86 overall
(legit 0.94, fraud 0.81) against nominal 0.90. The fraud class under-covers under the
month-to-month shift, and we say so. Mean set size 1.75, so the set is often {fraud, legit},
but it only ever *widens a fraud verdict*; a legitimate verdict that cannot wrong anyone is
reported and left alone.

**January.** For transactions after 2016-12-31 the risk-alert signal that learned "isolated
anomaly = false alarm" carries LR 1, and the risk-score prior is softened from 0.62 to 0.50 — a
low score is not evidence of innocence.

**Taint (C11)** widened the set on 5 of the 18 final cases, all with missing identity records.
For the customer-denial cases among them, R2 still governs (a denial is outside what
calibration saw), so the block stands.

**Caveat stated up front.** The closed cases are a selected sample, so coverage holds for
"cases like the ones the bank investigated", not all traffic.
""")

# ------------------------------------------------------------------------ 09
add("09", "label-free-evaluation", "Innovation 3 — label-free evaluation and attacks (C10)", "flowchart", r"""
flowchart TB
  REC["Recorded tool I/O of each case<br/>(.cache/recordings — no live graph touched)"]:::data
  subgraph MR["Metamorphic relations (eval/metamorphic.py)"]
    M1["M1 id renaming<br/>0 / 18 violations"]:::ok
    M2["M2 hostile text<br/>40 templates × 18 = 720 runs<br/>0 decision changes · 468 flagged"]:::ok
    M4["M4 time shift (within regime)<br/>0 / 18"]:::ok
    M5["M5 monotone evidence<br/>0 / 90"]:::ok
    M6["M6 monotone exposure (SAR never switches off)<br/>0 / 18"]:::ok
    M7["M7 determinism<br/>0 / 18"]:::ok
  end
  subgraph ATK["Evasion-frontier attacks (eval/attacks.py)"]
    A1["ATK-* planted from OUR thresholds<br/>$430 legs · diluted burst · $6 probes<br/>3 evaded before"]:::guard
    A2["Frontier mining on closed cases<br/>24 frauds just past the old boundary"]:::eval
    A3["Defence: relative rules as<br/>evidence-only frontier detectors<br/>0 evade · cannot cause a block"]:::ok
  end
  NB["Naive baseline<br/>LLM reads trigger_text and decides"]:::llm
  REC --> MR
  A1 --> A2 --> A3
  M2 -. compare .- NB
""" + CLASSES, """
**Claim.** There is no answer key for the 18, so we test relations that must hold *whatever
the right answer is* — they find bugs without labels — and we derive attacks mechanically from
our own detector thresholds, because with an LLM that cannot decide, the rules are the real
attack surface.

**Bugs found and fixed by these relations** (each changed code, recorded in the session):
- M2 replace-mode removed a customer's denial: a legitimate allowed-fact change, so M2 now
  appends/prepends.
- M4 crossing 1 January flipped the date-keyed January regime: shifts now stay inside a regime.
- Graph set results came back unordered (re-runs differed): readers now sort, and attest-verify
  compares content.
- Recording isolation: a BYO run overwrote the main recordings; side effects are now scoped
  per dataset.

**Attacks.** 7 planted evasions + R7 seasoning; 3 evaded the original rules, 0 after the
defence. Deploying the hardened rules in the *core* would flag 67 legitimate cases on the
history for 68 extra frauds, so they run as **evidence-only frontier detectors**: the attack is
flagged to the analyst with its ids and cannot cause a block.

**The six hostile cases in the pack** (HHF-004/005/008/010/014/016) are all flagged with
spans, and each decision rests on graph evidence and the cardholder's reply, never on the text.
""")

# ------------------------------------------------------------------------ 10
add("10", "harness-and-drills", "Harness — failure behaviour and the drills", "flowchart", r"""
flowchart LR
  subgraph DR["drills/run_drills.py — 11 / 11 PASS"]
    direction TB
    D1["graph_down: kill after N calls"]:::guard
    D2["mcp_down: kill MCP only"]:::guard
    D3["llm_timeout / llm_garbage"]:::guard
    D4["invalid_input: id · field · txn · trigger"]:::guard
    D5["hostile_input"]:::guard
    D6["wrong_role · body role · self · replay · duplicate · tamper"]:::guard
    D7["twice · replay"]:::guard
    D8["bounded · canary"]:::guard
  end
  subgraph BEH["Behaviour"]
    direction TB
    B1["exit 2 · signed FAILED_DEPENDENCY<br/>step named · last good call · answer untouched"]:::ok
    B2["direct same-graph · transport_degraded=true<br/>MCP_STRICT=1 → exit 2"]:::ok
    B3["one retry · template prose · decision identical"]:::ok
    B4["exit 3 · field named · no answer file"]:::ok
    B5["flagged with spans · decision identical"]:::ok
    B6["401/403/409 · refusals in the signed chain<br/>edit detected by verify()"]:::ok
    B7["identical decision fields · offline bit-for-bit replay"]:::ok
    B8["round cap · wall clock · CANARY-* never seen"]:::ok
  end
  D1 --> B1
  D2 --> B2
  D3 --> B3
  D4 --> B4
  D5 --> B5
  D6 --> B6
  D7 --> B7
  D8 --> B8
""" + CLASSES, """
**What judges look for** in every drill: a clear error, no invented answer, no false "saved"
status, consistent results. Each row is a script in `drills/run_drills.py` (results in
`eval/reports/drills.md`), run against live TigerGraph on HHF-001.

**Proofs a judge can check in a minute**
- *Fail closed:* `DRILL_GRAPH_FAIL_AFTER=6 make case CASE=HHF-001` → exit 2, the answer file
  hash is unchanged, and a signed record names the step.
- *Not found ≠ invalid during an outage:* a missing transaction is only reported as invalid
  input after a healthy-graph precondition passes (this was a real bug, fixed).
- *Approvals:* the role comes from the bearer token's hash on the server; a body role is
  ignored and recorded as ignored; self-approval, wrong role, duplicate and replayed approvals
  are refused, and the refusals are themselves signed into the chain. Editing any record breaks
  `verify()`.
- *Same case twice:* identical decision-field hash; `make replay` reproduces it offline from the
  recording.
- *Temporal wall:* `make canary` plants `CANARY-*` transactions in 2099 on the case card; the
  negative control sees them, the investigation never does.
- *Model failures:* hard timeout, then one retry, then template prose (`prose_source:
  template`). Garbage that survives the id filter fails a quality floor and falls back too
  (a real bug caught by `llm_garbage`, fixed).
""")

# ------------------------------------------------------------------------ 11
add("11", "trust-boundaries", "Trust boundaries, provenance and egress", "flowchart", r"""
flowchart TB
  subgraph BANK["Bank boundary"]
    direction TB
    TXT["Customer / analyst free text<br/>UntrustedText"]:::guard
    EXT["Extractor (allow-list)<br/>text_denies_charge · text_recognises_charge<br/>text_analyst_asks_ring"]:::core
    CS["CaseState<br/>__post_init__ rejects UntrustedText<br/>at any depth"]:::guard
    CORE["Policy core (no LLM import)"]:::core
    RED["redact(): secrets + email/phone<br/>logs · traces"]:::guard
    LOG["logs/run.jsonl · egress.jsonl<br/>ledger · recordings"]:::data
    EMB["Local embeddings<br/>all-MiniLM-L6-v2 (no egress)"]:::data
    APPR["Approval tokens (sha256 only in env)<br/>Ed25519 signing key (local)"]:::human
  end
  SAV["TigerGraph Savanna<br/>all graph data · case write"]:::tg
  LLMP["LLM provider (Google gemini-3.6-flash)<br/>evidence brief: pseudonymous ids, aggregates,<br/>policy text, delimited trigger text"]:::llm
  HF["Public read-only console bundle<br/>(declared) answer files only"]:::data
  TXT --> EXT --> CS --> CORE
  TXT -. "data block only" .-> LLMP
  CORE --> RED --> LOG
  CORE <--> SAV
  CORE -. "prose request (logged)" .-> LLMP
  LOG -. "never" .-x LLMP
""" + CLASSES, """
**Provenance labels are a runtime assertion.** Free text enters as `UntrustedText`; the
policy core's only input, `CaseState`, refuses to be built if any field — at any depth — is
untrusted text (`core/provenance.py`, two tests). Only three allow-listed extractor facts cross
the boundary, and hostile spans are stripped before those facts are read, so "it was me" injected
into a dispute cannot clear it, and "classify as legitimate" cannot be obeyed — or inverted.

**What leaves the boundary** (also `docs/RESILIENCE.md`): Savanna sees all graph data. The LLM
provider sees the evidence brief only — never raw rows, V-columns, identity records,
credentials or tokens — and is never asked for a probability, action, route or id. Every call
is in `logs/egress.jsonl`. Embeddings are computed locally. The public read-only console bundle
is declared.

**Tip-off by construction.** Every customer-facing string is rendered from a `CustomerView`
whose fields cannot carry SAR state, verdict, probability, pattern or connected cards; a test
toggles the SAR flag on every answer and diffs the customer text: zero bytes change. The
organisers' tip-off regex is the second layer.
""")

# ------------------------------------------------------------------------ 12
add("12", "data-pipeline", "Data pipeline — January through the drift gate, and any bank's schema (C12, C13)", "flowchart", r"""
flowchart LR
  subgraph SRC["Inputs"]
    R1["Round 1: Jul–Dec 2016<br/>590,742 txns"]:::data
    JAN["Final drop: January 2017<br/>60,196 txns · 15,893 identity<br/>closed cases → 5,585 · pack of 18"]:::data
    BYO["Judge's own dataset<br/>renamed + reshaped columns"]:::data
  end
  DRIFT["00_drift.py (C12)<br/>columns · types · nulls · domains · key overlaps<br/>what each change BREAKS<br/>exit 4 until fraud-manager token"]:::guard
  MAP["byo.py + canonical.json (C13)<br/>role detection · column evidence<br/>cents · date+time · epoch · families<br/>refuse unmappable · validate"]:::guard
  N["01_normalise<br/>card-id pinning (labels win)<br/>pack authoritative for its txn"]:::core
  B["02_behaviour --append<br/>Round 1 PCA refit identically<br/>Jan ranked vs Round 1 · old vectors unchanged"]:::core
  M["04_build_memory<br/>384-d narratives (local)"]:::core
  ST["06_stage → graph/install.py load<br/>retry-safe chunked upload"]:::tg
  PJ["projections + GDS<br/>CO_OCCURS 485,961"]:::tg
  FV["08_fact_vectors --only-new<br/>fact masks → ClosedCase"]:::tg
  VER["07_verify: 16 checks<br/>every pack + closed-case card resolves"]:::ok
  R1 --> N
  JAN --> DRIFT --> N
  BYO --> MAP --> N
  N --> B --> M --> ST --> PJ --> FV --> VER
""" + CLASSES, """
**January (C12).** The drift gate compared every old/new pair: no columns added, removed or
renamed; 257 distribution shifts in transactions (D-deltas, null rates, new frequent
customers and timestamps), 7 in identity, the closed-case file replaced (5,565 ids overlap, 20
new). Each change names what it breaks downstream. The proposal waits for a fraud-manager
token (exit 4), and the approval is signed into the ledger and written to the graph as a
`SchemaChange` vertex.

**What the load surfaced.**
- January labels re-pinned 511 Round 1 transactions on two customers.
- The organisers' data contains a genuine **label conflict**: the pack puts HHF-011's
  transaction on C09241-K1, while 21 closed cases put that card tuple on K2. The pack wins for
  its own transaction, and the conflict is reported in the C11 report.
- Behaviour vectors were *appended*: the Round 1 PCA is refit on identical chunks, January is
  ranked against the Round 1 distribution, and all 590,742 old vectors stay byte-identical, so
  the 6-hour closed-case fact replay remains valid.

**Any bank's schema (C13, judges' run).** `make byo DATA=… NAME=…` maps against the bundled
spec (no reference data needed), validates, gates, transforms, ingests into isolated folders,
runs the pack and grades. Rehearsal on a renamed and reshaped variant: every required column
mapped (card tuple by value quantiles, cents ×0.01, date + time → ts, 377 family columns);
3/3 cases graded clean, with verdicts identical to the canonical run.
""")

# ------------------------------------------------------------------------ 13
add("13", "case-lifecycle", "Case lifecycle and governance (C14, C8, §2)", "state", r"""
stateDiagram-v2
  direction LR
  [*] --> OPENED: trigger, evidence = flagged txn
  OPENED --> AWAITING_EVIDENCE: VOI picks one question
  AWAITING_EVIDENCE --> OPENED: reply folded, simulated and seeded
  OPENED --> ESCALATED: R8 uncertain & exposed / R9 / gate
  OPENED --> PENDING_APPROVAL: BLOCK needs L1, REPORT needs L2
  OPENED --> CLOSED_LEGITIMATE: cleared on evidence
  PENDING_APPROVAL --> APPROVED: token role ok, signed and chained
  PENDING_APPROVAL --> REJECTED: approver rejects
  APPROVED --> CLOSED_FRAUD
  ESCALATED --> PENDING_APPROVAL: analyst decides
  OPENED --> WATCH: at-risk card, containment child
  WATCH --> OPENED: card hit later
  CLOSED_FRAUD --> [*]
  CLOSED_LEGITIMATE --> [*]
  note right of PENDING_APPROVAL
    401 no token, 403 wrong role or self-approval
    409 duplicate or replayed record
    every refusal enters the signed chain
  end note
""", """
**A case is a record with a life.** Each run appends a version of its state changes to
`data/lifecycle/<case>.jsonl` and writes them to the graph as `CaseStateChange` vertices. Each
transition names the evidence that caused it, when it happened, and who acted. Each human
approval appends a transition with its ledger sequence and hash. Nothing is overwritten; a
rerun whose decision changed is flagged `changed_since_last_run`.

**Handover note** (console *Case life* tab): where the case stands, what it waits on and whose
approval, what the agent already did, the open questions, what changed after evidence, the
proof margin and the gate's reason. This is what lets an analyst take over cold.

**Approvals (§2, brief §9).** Bearer token → role on the server (SHA-256 hashes in the env);
L1 needs team lead or fraud manager, L2 needs fraud manager. The body role is ignored, and the
proposer cannot approve. Records are append-only, Ed25519-signed and hash-chained, and bind
case id, action index and answer hash, so a replay against another case or a changed decision
fails.

**Analyst in the loop (C8).** Accept/reject on findings through the same ledger discipline.
One feedback round on the October holdout cut legitimate customers acted against from 46 to 42,
with every adjustment naming the feedback ids that caused it.
""")

# ------------------------------------------------------------------------ 14
add("14", "challenges-map", "All 14 challenges — what was built and where the proof lives", "flowchart", r"""
flowchart LR
  subgraph G1["Find patterns nobody wrote down"]
    C1["C1 New typologies<br/>origin · dormant_wake · micro_charges<br/>recipient_fanin · frontier detectors"]:::eval
    C2["C2 Self-growing detective<br/>mine → spec → backtest → PROPOSED<br/>fraud-manager approval"]:::eval
    C3["C3 Policy text → detector<br/>R5/R6 compiled from prose<br/>agree/disagree with ids"]:::eval
  end
  subgraph G2["Explain and prove"]
    C4["C4 Evidence to SAR<br/>every sentence cited"]:::ok
    C5["C5 Ring replay<br/>time slider from attested txns"]:::ok
    C6["C6 Regulator's view<br/>proof-first · recorded I/O · re-run"]:::ok
  end
  subgraph G3["Act on it"]
    C7["C7 Containment planner<br/>block set + forward protection"]:::tg
  end
  subgraph G4["Work with analysts"]
    C8["C8 Analyst in the loop"]:::human
    C9["C9 Speed & autonomy<br/>p95 · cost/case"]:::human
    C14["C14 Case management<br/>lifecycle · WATCH · handover"]:::human
  end
  subgraph G5["Defend the agent"]
    C10["C10 Break the agent<br/>720 fuzz · ATK-* · provenance"]:::guard
  end
  subgraph G6["Messy and changing data"]
    C11["C11 Data quality detective<br/>taint → conformal widening"]:::core
    C12["C12 Schema drift survival<br/>diff → explain → approve → re-map"]:::core
    C13["C13 Someone else's schema<br/>byo.py end to end"]:::core
  end
  I1(("Innov. 1<br/>Proof")):::core
  I2(("Innov. 2<br/>Containment")):::tg
  I3(("Innov. 3<br/>Label-free eval")):::eval
  I4(("Innov. 4<br/>Conformal")):::core
  I1 --- C6 & C4
  I2 --- C7 & C1 & C5 & C14
  I3 --- C10
  I4 --- C11
""" + CLASSES, """
See `docs/CHALLENGES_DEMO.md` for each challenge's problem, what was built, the exact files,
the attested numbers, and the live demo steps.

| # | Challenge | Depth | Headline evidence |
|---|---|---|---|
| 1 | New typologies | deep | origin test + 3 detectors + 2 frontier detectors, backtested on 7,133 replays; evidence-only, so no rise in legitimate customers acted against |
| 2 | Self-growing detective | medium | 3 conjunctions mined, backtested and filed as *proposed*. Honest: the October backtest shows them spurious (0 caught, 330 legit touched), which is exactly why approval exists |
| 3 | Policy text to detector | medium | R5: 7,065 agree / 58 disagree; R6: 7,117 / 6, every disagreement with ids |
| 4 | Evidence to SAR | byproduct | 3 SARs in the pack (HHF-001/002/003), each sentence cited |
| 5 | Ring replay | light | time slider on HHG-014 |
| 6 | Regulator's view | deep | proof + flip live + every tool response by hash + re-run; 18/18 attest-verify |
| 7 | Containment planner | deep | 5.0× lift, $14.4M pre-empted, 0 innocent blocks |
| 8 | Analyst in the loop | medium | 46 → 42 legit acted against after one round |
| 9 | Speed and autonomy | byproduct | p95 ≈ 284 s with LLM prose, ≈ $0.001/case (cached) |
| 10 | Break the agent | deep | 0/720 fuzz flips; 3 → 0 evasions; provenance assertion |
| 11 | Data quality detective | medium | 490,613 txns without identity; 5/18 cases tainted; label conflict found |
| 12 | Schema drift survival | medium | January run through the gate with approval |
| 13 | Someone else's schema | medium | variant mapped and investigated, verdicts identical |
| 14 | Case management | medium | state changes in graph, WATCH children, signed approvals, handover |
""")

# ------------------------------------------------------------------------ 15
add("15", "demo-flow", "The 5-minute demo — one script for any case", "flowchart", r"""
flowchart LR
  S0["0:00 Open the named case live<br/>trigger type · as_of<br/>Console → Re-run live (SSE)"]:::data
  S1["0:30 The trace<br/>tools · provisional action + route<br/>question asked · revised action · what changed"]:::core
  S2["1:30 THE PROOF<br/>minimal facts · margin k · precedent<br/>flip one fact live"]:::core
  S3{"3:00 Case shape?"}:::core
  R["Ring: origin · lift · at-risk step-ups<br/>block set + customers touched<br/>ring replay slider"]:::tg
  L["Legit / ambiguous: conformal set + why<br/>harm avoided"]:::ok
  H["Hostile text: spans flagged<br/>720 fuzz → 0 changes · tip-off diff 0 bytes"]:::guard
  S4["4:00 One drill live<br/>kill graph → signed FAILED_DEPENDENCY<br/>or replayed approval → 409"]:::guard
  S0 --> S1 --> S2 --> S3
  S3 --> R & L & H
  R & L & H --> S4
""" + CLASSES, """
**The analyst picks the case**, so the demo is built on what exists on *every* case: the
proof. Full script with commands and prepared answers: `docs/DEMO_PLAYBOOK.md`.

Before the slot: wake Savanna 10 minutes early (`python benchmark/run_case.py --case HHF-001
--replay` needs no graph; a live run needs it awake), run `make grade` once, keep the three role
tokens ready, and have a terminal next to the console.
""")

# ------------------------------------------------------------------------ 16
add("16", "results", "Results at a glance (final run)", "flowchart", r"""
flowchart TB
  subgraph Q["Answer quality"]
    Q1["Official grader: 18 / 18 clean<br/>0 hard · 0 policy · 0 warnings"]:::ok
    Q2["Round 1 holdout: 17 / 20 correct<br/>1 innocent harmed (now in precedent)"]:::eval
  end
  subgraph H["Harness"]
    H1["Drills 11 / 11 PASS"]:::ok
    H2["attest-verify 18 / 18"]:::ok
    H3["Tests 122 pass · parity 9 / 9"]:::ok
  end
  subgraph I["Innovation"]
    I1["Gate: legit acted against 70 → 5<br/>err k=1 0.36 vs k≥2 0.16"]:::core
    I2["Containment: 5.0× lift · $14.4M<br/>0 innocent blocks"]:::tg
    I3["Fuzz: 0 / 720 · metamorphic 0 / 882"]:::eval
    I4["Conformal: coverage 0.86 (0.90 nominal)"]:::core
  end
  subgraph D["Data"]
    D1["650,938 txns · January loaded through the gate<br/>BYO variant: 3 / 3 clean, identical verdicts"]:::data
  end
""" + CLASSES, """
Every number is generated by a script and stored in `eval/reports/`. The figures below are
regenerated into the README by `scripts/readme_numbers.py`.

| Area | Number | Source |
|---|---|---|
| Official grader on the 18 | 18/18 clean, 0 hard, 0 policy, 0 warnings | `eval/reports/grade_official.md` |
| Final verdicts | 10 legitimate · 7 fraud · 1 uncertain; 3 SARs; gate changed 1 (HHF-016) | `run_summary.md` |
| Hostile text | 6/6 flagged; 0/720 fuzzed runs changed a decision | `metamorphic.md` |
| Data quality | 5/18 tainted; 1 organiser label conflict | `data_quality.md` |
| Proof gate (Oct holdout) | legit acted against 70 → 5; harmful error 0.36 (k=1) vs 0.16 (k≥2) | `proof_holdout.md` |
| Containment backtest | agent arm 0.37 precision, 5.0× lift, $14.4M pre-empted, 0 innocent blocks | `containment_backtest.md` |
| Conformal | Oct coverage 0.86 (fraud 0.81, legit 0.94) | `conformal.md` |
| Drills | 11/11 pass | `drills.md` |
| Attestations | 18/18 re-run and match on live TigerGraph | `attest_verify.md` |
| Round 1 honesty | 17/20 correct; HHG-004 (legit) was blocked | `hhg_holdout.md` |
| Latency / cost | p95 ≈ 284 s with LLM prose; ≈ $0.001 per case (prose cached) | `run_summary.md` |
""")


# -------------------------------------------------------------------- write --
def clean_labels(src: str) -> str:
    """SVG text labels print entities literally: inside quoted labels swap
    & < > for look-alike glyphs, keeping <br/> line breaks."""
    import re

    def fix(m: "re.Match") -> str:
        t = m.group(0).replace("<br/>", "\x00")
        t = t.replace("&", "＆").replace("<", "＜").replace(">", "＞")
        return t.replace("\x00", "<br/>")
    return re.sub(r'"[^"\n]*"', fix, src)


def write() -> None:
    mmd_dir = HERE / "src"
    mmd_dir.mkdir(exist_ok=True)
    idx = ["# Architecture — diagram set", "",
           "Generated by `python docs/architecture/build.py`. Each page holds a detailed "
           "Mermaid diagram (rendered by GitHub and VS Code) and the explanation to give when "
           "presenting it. PNG/SVG exports are in `docs/diagrams/` when mermaid-cli is "
           "installed (`build/mmdc`).", "",
           "| # | Diagram | Use it for |", "|---|---|---|"]
    for d in D:
        name = f"{d['num']}-{d['slug']}"
        src = THEME + "\n" + clean_labels(d["src"])
        (mmd_dir / f"{name}.mmd").write_text(src + "\n", encoding="utf-8")
        img = f"../diagrams/{name}.png"
        md = [f"# {d['num']} · {d['title']}", "",
              f"![{d['title']}]({img})", "",
              "```mermaid", src, "```", "", d["body"], "",
              "---", f"[← index](README.md)"]
        (HERE / f"{name}.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        idx.append(f"| [{d['num']}]({name}.md) | {d['title']} | "
                   f"{d['body'].splitlines()[0][:110].replace('|', '/')}… |")
    (HERE / "README.md").write_text("\n".join(idx) + "\n", encoding="utf-8")


def render() -> None:
    if not MMDC.exists():
        print(f"mermaid-cli not found at {MMDC}; skipping PNG/SVG export")
        return
    OUT_IMG.mkdir(parents=True, exist_ok=True)
    cfg = HERE / "src" / "puppeteer.json"
    cfg.write_text('{"args": ["--no-sandbox"]}', encoding="utf-8")
    css = HERE / "src" / "style.css"
    css.write_text("svg, svg * { font-family: Arial, Helvetica, sans-serif !important; }\n",
                   encoding="utf-8")
    for d in D:
        name = f"{d['num']}-{d['slug']}"
        src = HERE / "src" / f"{name}.mmd"
        for ext, extra in (("png", ["-s", "2"]), ("svg", [])):
            out = OUT_IMG / f"{name}.{ext}"
            r = subprocess.run([str(MMDC), "-i", str(src), "-o", str(out), "-b", "white",
                                "-w", "2000", "-p", str(cfg), "-C", str(css), *extra],
                               capture_output=True, text=True, shell=(sys.platform == "win32"))
            print(f"{name}.{ext}: {'ok' if r.returncode == 0 else r.stderr[-300:]}")


if __name__ == "__main__":
    write()
    render()
    print(f"wrote {len(D)} diagram pages to {HERE.relative_to(ROOT)}")
