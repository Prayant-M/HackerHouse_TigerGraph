# 03 — Agent Design & The Uncertainty Engine

This is the 50%-of-the-score document. Investigation accuracy and next-best-action are both decided here.

---

## 1. LangGraph topology

```
         ┌─────────────────┐
         │ TRIGGER INTAKE  │  risk_score | customer_report | analyst_request
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
         │  CASE OPENER    │  create Case vertex, set as_of = trigger timestamp
         └────────┬────────┘
                  ▼
         ┌─────────────────┐
    ┌───▶│ EVIDENCE PLANNER│  LLM picks next tools given current gaps
    │    └────────┬────────┘
    │             ▼
    │    ┌─────────────────────────────────────────┐
    │    │ PARALLEL RETRIEVAL                      │
    │    │  graph_retriever · behavioural_retriever│
    │    │  memory_recall  · policy_retriever      │
    │    └────────┬────────────────────────────────┘
    │             ▼
    │    ┌─────────────────┐
    │    │ PATTERN MATCHER │  soft (vector) → hard (GSQL matchers) → score
    │    └────────┬────────┘
    │             ▼
    │    ┌─────────────────────────────┐
    │    │ EVIDENCE LEDGER UPDATE      │  DETERMINISTIC — Bayesian posterior
    │    └────────┬────────────────────┘
    │             ▼
    │    ┌─────────────────────────────┐
    │    │ UNCERTAINTY ASSESSOR        │  DETERMINISTIC — stopping rule
    │    └────────┬────────────────────┘
    │             │
    │      ┌──────┴──────┐
    │      │             │
    │  NOT ENOUGH     ENOUGH
    │      │             │
    │      ▼             ▼
    │ ┌──────────┐  ┌──────────────────┐
    │ │ VoI      │  │ ACTION           │
    │ │ ENGINE   │  │ RECOMMENDER      │
    │ └────┬─────┘  └────────┬─────────┘
    │      ▼                 ▼
    │ ┌──────────────┐  ┌──────────────────┐
    │ │ RECORD       │  │ PERMISSION GATE  │ DETERMINISTIC
    │ │ PROVISIONAL  │  └────────┬─────────┘
    │ │ RECOMMENDATION│          ▼
    │ └────┬─────────┘  ┌──────────────────┐
    │      ▼            │ EXPLAINER        │
    │ ┌──────────────┐  └────────┬─────────┘
    │ │ EVIDENCE GAP │           ▼
    │ │ RESOLVER     │  ┌──────────────────┐
    │ │ (controlled  │  │ CASE WRITER      │ → graph + JSON
    │ │  action)     │  └────────┬─────────┘
    │ └────┬─────────┘           ▼
    └──────┘            ┌──────────────────┐
     (loop, max 3)      │ MEMORY           │ narrative → embed → upsert,
                        │ CONSOLIDATOR     │ SIMILAR_TO edges, pattern priors
                        └──────────────────┘
```

Loop cap: **3 evidence-gathering rounds**. Cap it in code, not in the prompt. An uncapped agentic loop is the most common way these projects die on stage.

### Typed state

```python
class InvestigationState(TypedDict):
    case_id: str
    trigger: Trigger                     # type, payload, timestamp
    as_of: datetime                      # temporal cutoff — NEVER advances mid-case
    entities: dict[str, set[str]]         # entity_type -> ids discovered so far
    evidence: list[EvidenceItem]
    findings: list[Finding]
    pattern_matches: list[PatternMatch]
    prior_cases: list[RecalledCase]
    posterior: dict[str, float]           # hypothesis -> probability
    confidence: float
    open_questions: list[Question]
    recommendations: list[Recommendation] # tagged PROVISIONAL or REVISED
    evidence_requests: list[EvidenceRequest]
    decisions: list[Decision]
    round: int
    halt_reason: str | None
```

Checkpoint this state after every node using LangGraph's persistence. Two payoffs: the UI streams live from the checkpointer, and a crashed benchmark run resumes instead of restarting.

---

## 2. Hypothesis space

Don't model "fraud: yes/no". Model competing explanations, because the *type* determines the *action* — and the brief asks for the fraud type explicitly.

```
H0  Legitimate — unusual but genuine customer behaviour
H1  Account Takeover (ATO) — credentials compromised, new device/geo
H2  Card Testing — small probing authorisations before a large hit
H3  Stolen Card / CNP fraud — card data used without the instrument
H4  Synthetic Identity — fabricated identity, thin but clean history
H5  Bust-out — long good history, sudden coordinated drawdown
H6  Mule / Money Movement — account used as a pass-through node
H7  First-party / Friendly fraud — genuine customer disputing a real purchase
```

Map the five documented typologies from the dataset onto this space at load time. Keep H0 and H7 in the space — teams forget that *"cleared"* is a real outcome and the dataset explicitly contains cleared cases. An agent that can never conclude "legitimate" will fail half the benchmark.

Initialise priors from the closed-case base rates in months 1–4, **not** uniformly. Condition the prior on the trigger type: a customer report has a very different prior over H7 than a risk-model alert does.

---

## 3. The Bayesian evidence ledger

Every piece of evidence arrives with a **likelihood ratio** per hypothesis. Update in log-odds.

```python
# core/evidence_ledger.py  — no LLM imports in this file
def update(posterior: dict[str, float],
           item: EvidenceItem) -> dict[str, float]:
    log_odds = {h: math.log(p / (1 - p)) for h, p in posterior.items()}
    for h, lr in item.likelihood_ratios.items():
        # reliability shrinks the evidence toward neutral
        damped = 1.0 + (lr - 1.0) * item.reliability
        log_odds[h] += math.log(max(damped, 1e-6))
    raw = {h: 1 / (1 + math.exp(-lo)) for h, lo in log_odds.items()}
    total = sum(raw.values())
    return {h: v / total for h, v in raw.items()}
```

### Where the likelihood ratios come from

Three sources, in descending order of trustworthiness — and the ordering is the point:

1. **Empirically calibrated (preferred).** For any binary signal you can compute from the graph — `device_fanout > 3`, `first_use_of_card_device_pair`, `fraud_proximity > 0.5` — measure `P(signal | confirmed fraud) / P(signal | cleared)` **directly over the months 1–4 closed cases**. These are real numbers from real data. Precompute them into a lookup table at build time. This is the single highest-value half-day of work in the project.
2. **Pattern-match priors.** Each `Pattern` vertex carries `historical_precision`, computed from how often cases that matched it were confirmed. A hard GSQL matcher firing contributes that pattern's measured precision as an LR.
3. **LLM-assessed (last resort, damped).** For unstructured evidence — a customer's free-text report, an analyst note — ask the LLM for a discrete strength on a five-point scale (`STRONG_AGAINST … STRONG_FOR`), map to fixed LRs {0.2, 0.5, 1.0, 2.0, 5.0}, and set `reliability = 0.6`. Never let the LLM emit a raw float. It will produce confident-looking numbers with no basis, and a calibration plot will expose it.

`reliability` is the honest hedge. Graph-derived evidence gets 1.0, solicited customer confirmation gets ~0.85 (customers lie and customers forget), LLM-assessed text gets 0.6.

### Contradiction handling

When two evidence items push the same hypothesis in opposite directions, don't silently average. Record a `CONTRADICTS` edge, flag the case as `conflicted`, and let the conflict itself raise the value of a disambiguating evidence request. A demo where the agent says *"the device is new, which suggests ATO, but the behavioural fingerprint matches this customer's own history from three months ago — I need step-up auth to resolve this"* is worth more than any amount of dashboard polish.

---

## 4. The stopping rule (two-sided)

The brief asks: *"Determine when to stop the investigation once enough evidence is available to take a defensible action."* Answer it with arithmetic, not vibes.

**Stop and act when either holds:**

1. **Decisiveness** — the top hypothesis' posterior exceeds the action threshold for its required action class, *and* the margin over the runner-up exceeds a separation floor. Thresholds come from the policy, not from you:
   - `BLOCK_ACCOUNT` / `FILE_SAR` → posterior ≥ 0.85, margin ≥ 0.25
   - `BLOCK_TRANSACTION` → posterior ≥ 0.70, margin ≥ 0.15
   - `MONITOR` / `WARN_CUSTOMER` → posterior ≥ 0.45
   - `ALLOW` / close as cleared → P(H0) ≥ 0.80
2. **Exhaustion** — `max(expected_info_gain over all available evidence actions) < acquisition_cost_threshold`. Nothing you could ask would move the needle enough to justify the friction. **Escalate to a human analyst and say exactly that.**

**Also stop on:** round cap reached (3), or wall-clock/token budget exceeded — both recorded honestly in `halt_reason`.

Condition 2 is the one that wins points. Almost every team will implement "stop when confident." Stopping because *further investigation is not worth its cost* is a genuinely different and more defensible claim, and it is exactly what a real fraud operation does.

---

## 5. Value of Information — choosing the next evidence action

When uncertain, the agent must decide *what to ask*, not just *that it needs more*. Score each available evidence action by expected reduction in decision loss.

```python
# core/voi.py
def expected_info_gain(posterior, action: EvidenceAction) -> float:
    """Expected reduction in Shannon entropy from running this action."""
    h_now = entropy(posterior)
    h_after = 0.0
    for outcome, p_outcome in action.outcome_distribution(posterior).items():
        h_after += p_outcome * entropy(update(posterior, outcome.as_evidence()))
    return h_now - h_after


def select(posterior, available: list[EvidenceAction], policy) -> EvidenceAction | None:
    scored = [
        (a, expected_info_gain(posterior, a) / a.cost)
        for a in available
        if policy.permits(a, posterior)          # policy gate applies to ASKING too
    ]
    best, ratio = max(scored, key=lambda t: t[1], default=(None, 0))
    return best if ratio >= MIN_VOI_PER_UNIT_COST else None
```

### The evidence action catalogue

| Action | Channel | Cost | Reliability | Typically resolves |
|---|---|---|---|---|
| Customer transaction validation | Push / SMS (simulated) | 3 | 0.85 | H0 vs H3, H7 |
| Step-up authentication challenge | App / OTP (simulated) | 5 | 0.92 | H1 (ATO) — a passed challenge is strong evidence *against* takeover |
| Device attestation check | Internal (simulated) | 1 | 0.90 | H1, H4 |
| Analyst query — prior relationship context | Internal queue | 8 | 0.95 | H5, H6 |
| Extended graph sweep (3-hop ring expansion) | Free, internal GSQL | 1 | 1.00 | H5, H6 |
| Historical behavioural comparison | Free, internal | 1 | 1.00 | H0 vs everything |
| Merchant verification | External (stubbed) | 6 | 0.75 | H2, H3 |

**Cost is friction, not money.** Pinging a customer at 2am has a real cost even when the API call is free. Make that explicit in the blog — it's the sort of domain thinking judges from a graph-database company will notice, because it is the thing that separates a demo from a system.

Note that the two zero-friction internal actions are always available. The agent should exhaust free evidence before it ever touches a customer. Enforce that by cost ratio and it falls out of the maths automatically.

---

## 6. The before/after recommendation loop

The submission format demands both. Implement it as an explicit state transition, not as a byproduct.

```
round 0:  evidence gathered → posterior P0 → PROVISIONAL recommendation R0
          + approval route  → written to graph and to the answer file
          ↓
          VoI selects evidence action A → EvidenceRequest vertex → simulated dispatch
          ↓
round 1:  response arrives → Evidence vertex → ANSWERED_BY edge
          → posterior P1 → REVISED recommendation R1 + approval route
          → written to graph and to the answer file
          ↓
          Decision vertex records: P0 → P1, what changed, why R0 → R1
```

Every `Decision` vertex stores `posterior_before` and `posterior_after`, so the delta is queryable. In the demo, show that delta on screen as a moving bar. **Make sure at least one of your 20 benchmark cases genuinely flips its recommendation** — that is your money shot, and you should know which case it is before you record the video.

### Simulating evidence responses

You need responses to the requests without real customers. Build a **deterministic responder** seeded per case:

- It reads the case's ground-truth-adjacent context (for months 1–4 backtest cases, the actual closed-case disposition) and generates a plausible response consistent with it.
- For the 20 benchmark cases there is no disposition, so the responder samples from a documented distribution and **the run records that it was simulated**, with the seed.
- Never let the responder leak the answer into the agent's context. It returns only what a real channel would return: "customer confirms", "customer denies", "no response within SLA", "step-up passed", "step-up failed".

Include **"no response"** as an outcome with meaningful probability. An agent that can act on silence — treating a non-response to a high-value validation request as weakly incriminating and proceeding to a monitored hold — is demonstrating exactly the uncertainty handling the rubric rewards.

---

## 7. Policy-as-code

The dataset ships the bank's fraud policy as a document. Do not stuff it into a prompt and hope.

**Two-stage compilation:**

*Stage 1 (offline, LLM-assisted, human-reviewed):* parse the policy document into structured rules.

```yaml
# policy/policy.compiled.yaml
- clause_id: FP-4.2.1
  section: "Account restriction"
  source_text: "..."          # verbatim, for citation
  when:
    all:
      - posterior_fraud: ">= 0.85"
      - fraud_type: ["ATO", "STOLEN_CARD"]
  permits: [BLOCK_ACCOUNT, BLOCK_TRANSACTION, WARN_CUSTOMER]
  approval: L2_FRAUD_MANAGER
  obligation: MUST_NOTIFY_CUSTOMER_WITHIN_24H

- clause_id: FP-6.1
  section: "Suspicious activity reporting"
  when:
    all:
      - posterior_fraud: ">= 0.75"
      - amount_aggregate: ">= threshold"
  requires: [FILE_SAR]
  approval: COMPLIANCE_OFFICER
  regulatory_ref: REG-BSA-1020.320

- clause_id: FP-3.4
  section: "Customer contact limits"
  when:
    all:
      - contacts_in_window: ">= 2"
  forbids: [CUSTOMER_VALIDATION_REQUEST]
  rationale: "Contact fatigue controls"
```

*Stage 2 (runtime, deterministic):* `core/policy_engine.py` evaluates the compiled rules against case state and returns `(permitted_actions, required_actions, forbidden_actions, approval_routes, obligations, cited_clause_ids)`. The LLM chooses only from `permitted ∪ required`. It cannot invent an action, and every action it recommends carries a clause citation because the citation came from the rule that permitted it.

`FP-3.4` above is deliberately included as an example of a rule that **constrains evidence gathering itself** — a contact-fatigue limit. Wire the policy engine into the VoI selector (note the `policy.permits(a, posterior)` filter in §5) so the agent can genuinely say: *"the highest-value next evidence is customer validation, but policy FP-3.4 forbids a third contact this week, so I am escalating to an analyst instead."* That single sentence demonstrates four rubric items at once — uncertainty handling, policy compliance, next best action, and explainability.

Commit `policy.compiled.yaml` to the repo with a note that a human reviewed it. Honesty about the LLM-assisted extraction step is better than pretending it was hand-written.

---

## 8. Permissions and approval routing

Three action tiers, enforced in `core/permissions.py`:

| Tier | Behaviour | Example actions |
|---|---|---|
| **AUTO** | Agent executes immediately, logs it | Request step-up auth, extended graph sweep, add case note, monitor account |
| **APPROVAL_REQUIRED** | Agent recommends, routes to a role, waits | Block transaction, block account, warn customer, refund |
| **RECOMMEND_ONLY** | Agent never executes, always human | File SAR, close case as confirmed fraud, law-enforcement referral |

Route by role and ceiling: `L1_ANALYST` (up to monitoring and warnings), `L2_FRAUD_MANAGER` (blocks, freezes, refunds), `COMPLIANCE_OFFICER` (SAR, regulatory filings). The `approval_route` field is explicitly required in the answer file — for both the provisional and the revised recommendation.

In the UI, the approval queue is real: a human clicks Approve or Reject, the `APPROVED_BY` edge is written, the action's `executed` flag flips. Rejection is also informative — record it, and feed analyst rejections back into the pattern precision priors in memory consolidation. An agent whose recommendations improve because analysts overruled it is the strongest possible reading of *"use prior case outcomes and analyst decisions to inform recommendations."*

---

## 9. Memory consolidation

Runs after every closed case:

1. **Narrative** — LLM writes a structured 150-word case summary; embed it; upsert `Case.narrative_emb`.
2. **Similarity edges** — run `hybrid_case_recall` against the new narrative, write the top-5 as `SIMILAR_TO` edges with cosine and shared-entity counts.
3. **Pattern priors** — update each matched `Pattern`'s `historical_precision` with the case outcome (Beta-Binomial update, so early patterns don't swing wildly on one case).
4. **Entity recurrence** — increment a `recurrence_count` on every entity the case touched; entities crossing a threshold get flagged as watchlist nodes, which raises the prior on any future case touching them.
5. **Likelihood-ratio recalibration** — every N closed cases, recompute the empirical LR table from §3. Memory that updates the agent's *evidence weighting*, not just its retrieval, is a materially stronger claim than what most submissions will make.
6. **New pattern candidates** — if the case matched no documented typology but scored high, queue its motif for the discovery pipeline (see `06`, D5).

---

## 10. Answer file schema

**Conform to the dataset README's format first.** This is a superset — trim fields the README doesn't want, keep the structure for your internal record and the UI.

```json
{
  "case_id": "HHGOA-C-013",
  "trigger": {
    "type": "RISK_SCORE",
    "source_id": "3577291",
    "timestamp": "2019-05-14T03:22:41Z",
    "initial_signal": {"risk_score": 0.78}
  },
  "as_of": "2019-05-14T03:22:41Z",
  "investigation_record": {
    "rounds": [
      {
        "round": 0,
        "tools_called": [
          {"tool": "tx_neighborhood", "args": {"hops": 2}, "latency_ms": 142},
          {"tool": "device_fanout", "args": {}, "latency_ms": 88},
          {"tool": "hybrid_case_recall", "args": {"k": 5}, "latency_ms": 310}
        ],
        "evidence": [
          {
            "evidence_id": "E-01",
            "kind": "GRAPH",
            "statement": "Device fingerprint shared across 7 distinct cards in 11 days",
            "source_tool": "device_fanout",
            "raw": {"distinct_cards": 7, "window_days": 11},
            "likelihood_ratios": {"H1": 3.1, "H6": 4.4, "H0": 0.3},
            "reliability": 1.0
          }
        ],
        "posterior": {"H0": 0.11, "H1": 0.34, "H6": 0.41, "H3": 0.09, "H2": 0.05},
        "confidence": 0.52,
        "open_questions": [
          "Is the device shared legitimately (family/shared household) or is it a mule hub?"
        ]
      }
    ]
  },
  "prior_cases_used": [
    {"case_id": "HHGOA-H-0412", "similarity": 0.81, "shared_entities": 2,
     "disposition": "CONFIRMED_FRAUD", "fraud_type": "MULE",
     "influence": "Raised H6 prior; same device-fanout signature"}
  ],
  "findings": [
    {"finding_id": "F-01", "statement": "Device operates as a hub across unrelated customers",
     "supported_by": ["E-01", "E-04"], "contradicted_by": [], "support_score": 0.79}
  ],
  "pattern_matches": [
    {"pattern_id": "P-03", "name": "Mule network pass-through", "source": "DOCUMENTED",
     "match_score": 0.76, "historical_precision": 0.68}
  ],
  "risk_assessment": {
    "level": "HIGH", "fraud_type": "MULE",
    "posterior_fraud_probability": 0.82, "confidence": 0.71
  },
  "recommendations": [
    {
      "phase": "PROVISIONAL",
      "recorded_at": "before_additional_evidence",
      "actions": [
        {"action": "MONITOR_ACCOUNT", "tier": "AUTO", "approval_route": "NONE",
         "policy_clause": "FP-2.3"},
        {"action": "BLOCK_TRANSACTION", "tier": "APPROVAL_REQUIRED",
         "approval_route": "L2_FRAUD_MANAGER", "policy_clause": "FP-4.2.1"}
      ],
      "posterior_at_time": 0.63
    },
    {
      "phase": "REVISED",
      "recorded_at": "after_additional_evidence",
      "actions": [
        {"action": "BLOCK_ACCOUNT", "tier": "APPROVAL_REQUIRED",
         "approval_route": "L2_FRAUD_MANAGER", "policy_clause": "FP-4.2.1"},
        {"action": "FILE_SAR", "tier": "RECOMMEND_ONLY",
         "approval_route": "COMPLIANCE_OFFICER", "policy_clause": "FP-6.1"}
      ],
      "posterior_at_time": 0.82,
      "changed_because": "Step-up authentication failed; behavioural divergence confirmed"
    }
  ],
  "evidence_requests": [
    {"request_id": "R-01", "channel": "STEP_UP_AUTH",
     "question": "Challenge account holder with OTP on registered channel",
     "expected_info_gain": 0.34, "cost": 5,
     "policy_clause": "FP-5.1", "permitted": true,
     "sent_at": "2019-05-14T03:26:10Z", "response": "FAILED",
     "simulated": true, "simulation_seed": 4471}
  ],
  "decisions": [
    {"decision_id": "D-01", "step": 1, "posterior_before": 0.63, "posterior_after": 0.82,
     "rationale": "Failed step-up is strong evidence against legitimate use",
     "prev_hash": "0000...", "hash": "9a3f..."}
  ],
  "actions_taken": [
    {"action": "MONITOR_ACCOUNT", "executed": true, "executed_at": "...", "simulated": true}
  ],
  "sar": {
    "required": true,
    "triggering_clause": "FP-6.1",
    "regulatory_refs": ["REG-BSA-1020.320"],
    "narrative": "..."
  },
  "explanation": {
    "evidence_used": "...",
    "why_more_evidence_was_requested": "Posterior 0.63 sat below the 0.85 block threshold with H1/H6 separation under 0.15; step-up auth carried the highest information gain per unit of customer friction.",
    "why_these_actions": "...",
    "remaining_uncertainty": "H6 vs H1 not fully separated; mule involvement may be unwitting.",
    "counterfactual": "Had step-up authentication passed, posterior would fall to 0.29 and the recommendation would be MONITOR_ACCOUNT only."
  },
  "halt_reason": "DECISIVE_POSTERIOR",
  "graph_write": {"case_vertex": "HHGOA-C-013", "vertices_written": 24, "edges_written": 41}
}
```

The `counterfactual` field is small and disproportionately impressive. Compute it by re-running the ledger with the opposite outcome of the highest-VoI evidence item — it's about ten lines and it directly answers "what would change your mind."
