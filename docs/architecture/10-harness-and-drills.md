# 10 · Harness — failure behaviour and the drills

![Harness — failure behaviour and the drills](../diagrams/10-harness-and-drills.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
