# 13 · Case lifecycle and governance (C14, C8, §2)

![Case lifecycle and governance (C14, C8, §2)](../diagrams/13-case-lifecycle.png)

```mermaid
%%{init: {"theme": "base", "themeVariables": {
  "fontFamily": "Arial", "fontSize": "15px",
  "primaryColor": "#FFF4EC", "primaryBorderColor": "#F58220", "primaryTextColor": "#1F2430",
  "lineColor": "#5B6475", "secondaryColor": "#EEF4FF", "tertiaryColor": "#F6F7F9",
  "clusterBkg": "#FBFBFC", "clusterBorder": "#C9CED6"},
  "flowchart": {"htmlLabels": false, "padding": 18, "nodeSpacing": 45, "rankSpacing": 55}}}%%
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
```

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

---
[← index](README.md)
