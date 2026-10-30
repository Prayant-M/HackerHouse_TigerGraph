# 07 · Innovation 2 — predictive containment from the point of compromise (C7 + C1)

![Innovation 2 — predictive containment from the point of compromise (C7 + C1)](../diagrams/07-predictive-containment.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
flowchart LR
  RING["Ring cards (hit)<br/>case card + connected cards"]:::tg
  TS["ring_at_asof<br/>seeded WCC on the card-device<br/>projection CUT AT as_of"]:::tg
  OC["origin_counts (GSQL)<br/>entities touched 45→3 days before<br/>device · region · email · product×$25 band"]:::tg
  LIFT["Lift vs matched controls<br/>+ hypergeometric p<br/>p＜0.01 · ≥3 ring cards · ≤25 controls"]:::core
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
