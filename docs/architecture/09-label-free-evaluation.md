# 09 · Innovation 3 — label-free evaluation and attacks (C10)

![Innovation 3 — label-free evaluation and attacks (C10)](../diagrams/09-label-free-evaluation.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
