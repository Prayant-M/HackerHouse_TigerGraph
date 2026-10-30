# 08 · Innovation 4 — conformal abstention under the January shift (C11)

![Innovation 4 — conformal abstention under the January shift (C11)](../diagrams/08-conformal-abstention.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
flowchart LR
  CAL["Calibration<br/>Aug–Sep replays: 2,437 fraud · 1,340 legit<br/>nonconformity = 1 − p(true class)<br/>label-conditional, α = 0.10"]:::eval
  Q["Class quantiles<br/>fraud in set if p ≥ 0.087<br/>legit in set if p ≤ 0.742"]:::core
  P["p_graph_only<br/>(before any solicited reply)"]:::core
  SUP["Support check<br/>10-NN behaviour distance<br/>＞ 95th pct ⇒ outside support"]:::tg
  TAINT["Data-quality taint (C11)<br/>missing identity · empty region<br/>placeholder · thin history"]:::guard
  SET{"Prediction set"}:::core
  U["uncertain<br/>R8: ESCALATE if ＞ $500 or conflict<br/>else VERIFY"]:::guard
  F["fraud verdict stands"]:::ok
  CAL --> Q --> SET
  P --> SET
  SUP -->|widen| SET
  TAINT -->|widen| SET
  SET -->|"{fraud, legit} or {}"| U
  SET -->|"{fraud}"| F

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
