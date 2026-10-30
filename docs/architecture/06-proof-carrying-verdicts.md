# 06 · Innovation 1 — proof-carrying verdicts

![Innovation 1 — proof-carrying verdicts](../diagrams/06-proof-carrying-verdicts.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
flowchart TB
  F["Case facts<br/>(fired signals · memory · solicited replies)"]:::tg
  DEC["decide(facts) — the pure core<br/>rebuilds the ledger with the SAME add_signal<br/>+ conformal + feedback scaling"]:::core
  MIN["Minimal sufficient facts<br/>greedy deletion, weakest first<br/>(irredundant)"]:::core
  FLIP["Flip set ＆ margin k<br/>singles → pairs → triples<br/>(≤ 2,500 core calls)"]:::core
  PREC["precedent_by_facts (GSQL)<br/>ClosedCase.fact_mask ⊇ mask<br/>opened_at ＜ as_of"]:::tg
  REP["reproduces_live?<br/>fact replay == live decision"]:::eval
  GATE{"harmful AND (k ＜ 2 OR ≥5 precedents ≥50% cleared)<br/>AND not R2"}:::guard
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
