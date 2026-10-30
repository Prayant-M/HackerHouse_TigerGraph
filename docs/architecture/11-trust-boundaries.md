# 11 · Trust boundaries, provenance and egress

![Trust boundaries, provenance and egress](../diagrams/11-trust-boundaries.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
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

classDef tg fill:#FFE8D6,stroke:#F58220,stroke-width:2px,color:#1F2430;
classDef core fill:#E8F1FF,stroke:#2F6FEB,stroke-width:2px,color:#10233F;
classDef llm fill:#F3E8FF,stroke:#8B5CF6,stroke-width:1.5px,color:#2A1450,stroke-dasharray:4 3;
classDef guard fill:#FFECEC,stroke:#D64545,stroke-width:2px,color:#4A1010;
classDef ok fill:#E9F8EF,stroke:#1E9E5A,stroke-width:2px,color:#0D3B22;
classDef human fill:#FFF8DB,stroke:#C79A00,stroke-width:2px,color:#3A2E00;
classDef data fill:#F1F3F6,stroke:#7A8394,stroke-width:1.5px,color:#1F2430;
classDef eval fill:#E6FAF8,stroke:#0F9D8F,stroke-width:1.5px,color:#08332F;
```

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

---
[← index](README.md)
