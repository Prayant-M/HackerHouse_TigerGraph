# 04 · TigerGraph schema — the data graph and the case graph

![TigerGraph schema — the data graph and the case graph](../diagrams/04-graph-schema.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
