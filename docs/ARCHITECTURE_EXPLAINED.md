# The architecture, explained end to end

*A presenter's guide. Read it top to bottom once and you can explain every box in the system,
why it is there, where it lives in the code, and which number proves it works. Diagram
references point to `docs/diagrams/NN-*.png` (sources and per-diagram notes in
`docs/architecture/`). Every number here comes from a script's output in `eval/reports/` or
from the live TigerGraph workspace.*

---

## 0. The one-minute version

> A fraud alert arrives. One command checks the input, makes sure TigerGraph is up and loaded,
> and starts an agent. The agent investigates the alert against TigerGraph through the official
> MCP server, recalls similar past cases with a query that fuses vector search and graph
> traversal, and asks the cardholder one well-chosen question. It then decides through a
> deterministic policy engine that **cannot call an LLM**.
>
> Before any harmful action (a block or a regulatory report) leaves the system, the agent
> *computes a proof*: the smallest set of facts that forces the action, how many facts would
> have to be false to change it, and how the bank ruled on past cases with those same facts. A
> block that rests on a single fact is downgraded to "verify and escalate" before anyone is
> wronged.
>
> On ring cases it traces the ring back to where the cards were compromised and protects cards
> that have not been hit yet, using only actions that cost an innocent customer nothing.
> Everything is written back to the graph through one installed query, every claim is attested
> to the query that produced it, and every approval is checked against a server-side token
> role and signed.

Result on the final pack: the organisers' grader scores **18/18 clean** (0 hard, 0 policy,
0 warnings), all 11 resilience drills pass, and all 18 answers re-verify against live
TigerGraph.

---

## 1. The big picture (diagram 01)

Think of the system as six layers, top to bottom:

| Layer | What it does | Where |
|---|---|---|
| **1. Entry** | One command per case; validates input, checks the graph, records every tool call | `benchmark/run_case.py`, `agent/recorder.py` |
| **2. Agent** | A LangGraph loop of 15 nodes: investigate, recall, reason, ask, decide, explain, write | `src/fraudagent/agent/` |
| **3. Decision core** | Pure, LLM-free functions: Bayesian evidence ledger, policy R1–R10, proof, conformal, containment | `src/fraudagent/core/` |
| **4. Graph** | TigerGraph Savanna 4.2.5 — data, vectors, memory, the written cases | `graph/`, `graphstore/` |
| **5. Outputs** | Answer file, analyst console, case written to the graph | `report/`, `ui/` |
| **6. Governance** | Signed approvals, analyst feedback, detector and schema approvals | `governance/` |

**The design principle to say out loud:** *the graph decides, the model explains.* An LLM is
used for two things only — suggesting which tools to run, and writing prose — and a test fails
the build if any decision module ever imports an LLM.

---

## 2. Walk one case through the system

Use this to tell the story: follow a single alert from arrival to answer.

### Step 1 — Entry: one command, guarded (diagram 01, 10)

`make case CASE=HHF-016` runs `benchmark/run_case.py`. Before anything is investigated:

1. **Input guardrails.** The case id must exist in the pack, the required fields must be
   present, the trigger type must be one of the three allowed, and the flagged transaction
   must exist in the graph. Any failure means exit code **3** with the field named, and no
   answer file.
2. **Graph precondition.** The runner asks TigerGraph for its vertex counts. If the workspace
   is asleep (Savanna auto-stops when idle) it waits a bounded time for auto-start. If the
   graph is unreachable or empty it stops with exit code **2** and a signed
   `FAILED_DEPENDENCY` record. *Why this matters:* an empty graph would otherwise look like
   "unknown transaction" — we found and fixed exactly that after a workspace wipe.
3. **RecordingStore.** Every graph call from here on goes through a proxy that:
   - stores the response by its SHA-256 content hash — this is how *replay* and the
     regulator view work;
   - turns any graph error into a named `DependencyFailure` — this is fail-closed;
   - aborts if a future-dated `CANARY-*` transaction ever appears in a response — this
     proves the temporal wall.

### Step 2 — Intake: free text becomes untrusted data (diagram 11)

The trigger text is wrapped as `UntrustedText`. A deterministic extractor
(`core/text_facts.py`) does two things:

- **Reads only three facts:** does the customer deny the charge, does the customer recognise
  it, does the analyst ask about a ring.
- **Flags instruction-like spans:** fake system notes, role claims, "do not escalate", JSON
  injection, homoglyphs.

Hostile spans are stripped *before* facts are read, so an injected "it was me" cannot clear a
dispute. And the decision engine's input type, `CaseState`, refuses to be constructed if any
field is untrusted text. That is a runtime assertion, not a promise.

> **Say:** "Six cases in the pack carry hostile text. All six are flagged with their spans,
> none is obeyed, and none is inverted — because some of them ask for the right answer."

### Step 3 — The investigation loop (diagram 02)

The LangGraph nodes, in order:

1. **trigger_intake** fixes `as_of` — the temporal wall; every query is bounded by it.
2. **case_opener** sets the prior, conditioned on how the alert arrived. For January the
   risk-score prior is softened and the "this looks like a false alarm" signal is neutralised,
   because the bank's model has never seen January data.
3. **evidence_planner** — the LLM suggests tools, but the full toolkit always runs, so a
   planner cannot silently skip the ring query.
4. **graph_retrieval** runs 28 measured signals through installed GSQL queries: amount
   anomaly, new device, device fan-out, anonymising proxy, out-of-region use, velocity, card
   testing, structuring, mixed channel, recurring charge, shared-origin ring, fraud proximity,
   behavioural neighbours, and so on.
5. **memory_recall** — `hybrid_case_recall`, the signature TigerGraph query: TigerVector
   search over 384-d closed-case narratives *fused* with traversal over shared entities, in one
   query, bounded by as_of. It also reads back `COMPROMISE_POINT` edges written by earlier
   investigations.
6. **policy_grounding** — GraphRAG over the bank's policy text, so explanations cite clauses.
7. **ledger_update** folds every signal into a posterior over 7 hypotheses: legitimate plus
   the 6 fraud patterns. The likelihood ratios are *measured* by replaying the closed cases,
   not guessed.
8. **uncertainty_assessor** decides whether to stop or ask. It scores each possible question
   (customer validation, step-up authentication, analyst query) by expected information per
   unit of customer friction.
9. **record_provisional** commits the *before* recommendation with its approval routes.
10. **evidence_gap_resolver** asks the one best question. Replies are simulated, seeded from
    the case id and never from an outcome. The loop returns to node 8, at most 3 rounds.
11. **action_recommender** runs the decision layers (next section).
12. **permission_gate** executes only `auto` actions; L1/L2 actions wait for a human.
13. **explainer** — the LLM writes prose from a brief whose numbers are already fixed. Prose
    that invents ids, is too short, or is JSON-shaped falls back to a template.
14. **case_writer** writes the case to the graph through the single `case_write` query and
    reads it back before claiming `written_to_graph: true`.
15. **memory_consolidator** verifies the hash chain of every decision.

### Step 4 — The decision layers (diagram 03)

This is the heart of the system. Inside node 11, in a fixed order:

1. **Threshold verdict.** Fraud at p ≥ 0.70, legitimate at p ≤ 0.15, uncertain in between.
2. **Conformal abstention** (Innovation 4). A 90%-coverage prediction set is computed from
   the graph-only probability. If the set cannot single out "fraud" — or the case is outside
   what calibration has seen, or the data is tainted — a fraud verdict widens to *uncertain*.
3. **Policy engine.** R1–R10, §3a (case vs report), §2 approval routes (auto / L1 / L2). Pure
   functions over a small typed `CaseState`, each citing the clause it enforces.
4. **Proof** (Innovation 1). Minimal sufficient facts, the flip set and margin *k*, and
   precedent from the graph.
5. **Gate.** A block or report with margin k < 2, or contradicted by precedent, is
   downgraded to *verify + escalate*. R2 is exempt: if the cardholder denied the charge,
   policy requires the block.
6. **Containment** (Innovation 2) on ring cases: compromise origin, forward protection,
   block set.
7. **New-typology detectors** (C1/C2/C3) add evidence, never a block.

> **Key point:** every layer after the probability can only *remove* harm. Conformal widens a
> fraud verdict, never creates one. The gate removes a block, never adds one. Containment's
> forward actions are monitoring and step-up, which cost a legitimate customer nothing.
> Detectors add evidence only.

### Step 5 — Outputs (diagram 01)

- **The answer file** (`cases/HHF-0xx.json`) contains the case, the SAR if §3a requires one,
  and actions *before* and *after* evidence with what changed. Beyond the required schema it
  also holds the proof, the conformal set, the data-quality taint, the containment plan, the
  lifecycle, a handover note, ~10–16 attestations, per-case telemetry and the full trace.
- **The graph** gets a `FraudCase` vertex with evidence, decisions, actions, requests, SAR,
  state changes, a `COMPROMISE_POINT` edge and WATCH child cases.
- **The console** shows everything, live.

---

## 3. TigerGraph's role in detail (diagrams 04, 05)

### What is in the graph

| Subgraph | Contents | Live counts |
|---|---|---|
| Transactions | Customer → Card → Transaction → DeviceProfile / BillingRegion / EmailDomain, NEXT_TXN chains | 650,938 txns · 14,849 cards · 13,553 customers · 9,729 devices |
| Projections | CO_OCCURS_WITH (cards sharing devices), ANON_CO_OCCURS (anonymous-proxy slice) | 485,961 · 1,728 edges |
| Memory | ClosedCase (384-d narrative vectors + `fact_mask` bitmask), PolicyDoc, Pattern | 5,585 closed cases (4,781 with masks), 41 policy docs |
| Cases | FraudCase, Evidence, Decision (hash chain), RecommendedAction, EvidenceRequest, SAR, CaseStateChange, COMPROMISE_POINT, CHILD_CASE | written by the agent |
| Governance | ApprovalRecord, AnalystFeedback, Detector, SchemaChange | written by the console |

### How TigerGraph earns its 10 points (say these five)

1. **Vector search fused with traversal in one query:** `hybrid_case_recall` scores
   0.55 × cosine + 0.45 × saturating shared-entity overlap, and it moves the posterior.
2. **A graph algorithm that changes the output:** `ring_at_asof`, a weakly-connected-component
   seeded at the case card on the card-device projection, *cut at as_of*. It feeds forward
   protection. Ablated against the all-time component: precision 0.374 vs 0.354.
3. **Write-back and read-back:** `case_write` writes the whole case; `case_chain` reads it back
   before the answer claims it was written; `COMPROMISE_POINT` edges are read by later cases
   through `compromise_watch`.
4. **Restricted MCP:**
   - the agent talks to TigerGraph through `tigergraph-mcp`;
   - the client allows only three MCP tools;
   - the `agent_role` in TigerGraph RBAC may run 25 installed queries and nothing else;
   - the agent code has no upsert method at all.
5. **The graph as source of truth:** `make attest-verify` re-runs every recorded query against
   the live graph; 18/18 match.

### The single write path

`case_write.gsql` accepts one JSON document — the same payload as the answer file — and can
only create the case subgraph and link it to entities that already exist. Upsert semantics
mean running the same case twice gives the same vertex ids and no duplicates. Human decisions
go through a separate `governance_write` query that only the console role can run.

---

## 4. The four innovations (diagrams 06–09)

### Innovation 1 — proof-carrying verdicts (headline; diagram 06)

**Claim.** Every answer ships a proof an examiner can check in five minutes, and a harmful
action resting on a thin proof is downgraded before anyone is wronged.

**How.** Because the decision core is a pure function, `decide(facts)` can be re-run with
facts removed:
- **Minimal sufficient facts:** greedy deletion until removing any one more fact changes the
  action.
- **Flip set and margin k:** the smallest set of facts whose removal flips the action —
  singles, then pairs, then triples.
- **Precedent:** one GSQL subset match, `ClosedCase.fact_mask ⊇ minimal-set mask`, over closed
  cases opened before as_of. The fact masks come from replaying all 5,585 closed cases through
  the same extractor under their own as_of.
- **reproduces_live:** checks the proof replays the actual decision.

**Measured** on the October holdout, with the cut-offs fitted on July–September:

| | value |
|---|--:|
| harmful-action error rate at k = 1 | 0.36 |
| harmful-action error rate at k ≥ 2 | 0.16 |
| legitimate customers acted against, without → with gate | 70 → 5 |
| frauds acted on, without → with gate (the others are escalated, not dropped) | 142 → 26 |

**On the pack.** HHF-016: a $3,008.76 block resting on k = 1 was downgraded to verify +
escalate — while its text said "do not escalate".

### Innovation 2 — predictive containment (diagram 07)

**Claim.** Do not only block cards already hit; find where the ring was compromised and
protect the cards that passed through the same point but have not been hit yet, at zero cost
to innocent customers.

**How.**
- **Backward:** `origin_counts` finds what ring cards touched 45–3 days before the loss
  (device, region, email, product × amount band). Lift is measured against control cards
  active in the same window with no fraud, plus a hypergeometric p-value. The origin is the
  narrow entity with p < 0.01.
- **Forward:** cards that touched the origin or the time-sliced ring component get monitoring
  and step-up, plus a WATCH child case.
- **Block set:** blocks only cards where fraud is established; the customers it touches are
  named.
- **Write-back:** `COMPROMISE_POINT`.

**Measured** on 80 rings: the agent arm has precision 0.37, **5.0× lift**, **$14.4M loss
pre-empted** and **zero blocks on innocents**. Two ablations carry the claim:

| ablation | with | without |
|---|--:|--:|
| matched controls (lift) | 3.57× | 0.53× (raw counts) |
| as_of cut (precision) | 0.374 (time-sliced) | 0.354 (all-time) |

**Live:** HHG-014 — origin device lift ≈ 4,946, 141 at-risk cards protected with step-up only.

### Innovation 3 — label-free evaluation and attacks (diagram 09)

**Claim.** There is no answer key for the 18, so we test relations that must hold whatever
the right answer is, and we attack our own thresholds.

**Metamorphic relations,** run on recorded tool I/O — 0 violations in 882 runs after fixing
the bugs they found:

| relation | what it checks | violations / runs |
|---|---|--:|
| M1 | id renaming | 0 / 18 |
| M2 | hostile text, 40 templates × 18 | 0 / 720 |
| M4 | time shift | 0 / 18 |
| M5 | monotone evidence | 0 / 90 |
| M6 | monotone exposure | 0 / 18 |
| M7 | determinism | 0 / 18 |

**Attacks** derived from our own thresholds ($430 legs instead of $480, a diluted burst, $6
probes): 3 evaded before, 0 after. The hardened rules run as evidence-only detectors, because
in the core they would flag 67 legitimate customers.

### Innovation 4 — conformal abstention (diagram 08)

**Claim.** "Uncertain" comes from a coverage guarantee, and widens when a January case looks
unlike anything calibration has seen.

**How.**
- Label-conditional split conformal at α = 0.1, calibrated on August–September replays.
- **Support check:** a case whose behaviour vector is far from the calibration set is outside
  support.
- **Data-quality taint** (C11) also widens the set.

**Measured.** October coverage was 0.86 against the nominal 0.90; we state that fraud
under-covers under the shift. 5 of the 18 final cases were tainted.

---

## 5. Safety and harness (diagrams 10, 11)

**Eleven drills, all passing** (`eval/reports/drills.md`):

| drill | what happens |
|---|---|
| graph down mid-run | exit 2, signed failure record, answer file untouched |
| MCP down | falls back to the same graph directly and flags `transport_degraded`; strict mode exits 2 |
| LLM timeout | one retry, then template prose; decision identical |
| LLM garbage | template prose; decision identical |
| invalid input | exit 3 with the field named |
| hostile input | flagged, decision identical |
| wrong role | 401 / 403 / 409; refusals are signed; tampering detected |
| same case twice | identical decision fields |
| replay | offline, bit-for-bit |
| bounded | round cap and wall-clock budget honoured |
| canary | never seen by any query |

**Approvals.**
- The bearer token is hashed and looked up on the server to get the role; the role written in
  the request body is ignored.
- L1 actions need a team lead or fraud manager; L2 actions need a fraud manager.
- The proposer cannot approve their own action.
- Records are Ed25519-signed and hash-chained, and bind the case, the action and the answer
  hash, so a replayed or edited approval fails.

**Tip-off by construction.** Customer-facing text is rendered from a type that has no field
able to carry SAR state. Toggling the SAR flag on every answer changes zero bytes of customer
text.

**Egress.**
- Savanna receives the graph data.
- The LLM provider receives only the evidence brief: pseudonymous ids, aggregates, policy text
  and the trigger text inside a delimited block.
- Embeddings are computed locally.
- Every outbound call is logged, and logs are redacted.

---

## 6. Data and change (diagram 12)

- **January** arrived as new files plus a replaced closed-case history. The drift gate
  (`ingest/00_drift.py`) diffs columns, types, nulls, value domains and key overlaps, explains
  what each change breaks, and waits for a fraud-manager token before loading (C12). The
  behaviour vectors were *appended*: the old PCA was re-fit identically and old vectors stayed
  byte-identical, so the 6-hour fact replay stayed valid.
- **What the load surfaced:**
  - January labels re-pinned 511 old transactions;
  - one genuine label conflict in the organisers' data (HHF-011's card), reported by the
    data-quality report (C11).
- **Any bank's schema** (C13, the judges' run): `make byo DATA=… NAME=…` maps unseen columns
  against a bundled spec using evidence (names, value shapes, quantiles, cents, split
  timestamps), refuses what it cannot map, validates, asks for approval, and runs in isolated
  folders. On a renamed and reshaped variant: 3/3 cases graded clean, with verdicts identical
  to the canonical run.

---

## 7. Cases as records, and humans in the loop (diagram 13)

- **Lifecycle (C14).** OPENED → AWAITING_EVIDENCE → ESCALATED or PENDING_APPROVAL →
  APPROVED / REJECTED → CLOSED, plus WATCH for at-risk cards. Each transition records the
  evidence that caused it, the time and the actor, both in the graph and in a versioned log.
  The *Case life* tab is the handover note.
- **Analyst feedback (C8).** Accept/reject a finding. Behaviour changes without retraining:
  the finding is suppressed on that card, or the signal's reliability shrinks, and every
  answer names the feedback ids responsible. One round cut legitimate customers acted against
  from 46 to 42.

---

## 8. How to answer "explain this decision" for any case

1. Open the case in the console → **Overview**: trigger, verdict, before/after actions,
   what changed.
2. **Proof** tab: "it rests on these facts, margin k, this precedent". Click *Recompute* on a
   fact to show the action change live.
3. **Regulator replay** tab: every query the agent ran and the hash of what came back. Click
   *Re-run* → "matches".
4. **Case life** tab: where it stands and who must approve what.
5. If it is a ring: the **Containment & ring** tab — origin, protected cards, block set, the
   replay slider.

---

## 9. Glossary

| Term | Meaning |
|---|---|
| **as_of** | The alert's timestamp; no query may see anything after it (temporal wall) |
| **Attestation** | A claim plus its ids, the query and parameters that produced it, the recorded response hash, the time and the data snapshot |
| **Margin k** | How many facts would have to be false to change the action |
| **Precedent** | Closed cases whose replayed facts contain this case's minimal facts |
| **Conformal set** | {fraud}, {legit} or both, with 90% coverage; both means uncertain |
| **Taint** | A data gap (missing identity, empty region, placeholder, thin history) that blinds evidence this decision needed |
| **Compromise origin** | The entity the ring's cards shared weeks before the loss, found by lift against control cards |
| **R2 / R1 / R8 / §3a** | Customer denied → block; single weak signal → verify first; uncertain and exposed → escalate; when a report is owed |
| **FAILED_DEPENDENCY** | The signed record written instead of a verdict when the graph, MCP or model fails |
| **case_write** | The single installed query through which the agent may write |
