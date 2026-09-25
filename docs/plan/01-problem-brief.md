# 01 — Problem Brief (Decoded)

**Challenge:** TigerGraph Agentic Fraud Investigation (HHGOA)
**Deliverable:** An AI agent that investigates fraud, opens and progresses cases, handles uncertainty, and recommends the next best action — grounded in a TigerGraph knowledge graph.

---

## 1. What is actually being asked

Strip the prose and there are **eight non-negotiable capabilities**. Every one of them maps to a judging line item, so treat this as the acceptance spec.

| # | Capability | Concrete meaning |
|---|---|---|
| 1 | **Trigger** | Investigation starts from a risk score, a customer report, or an analyst request. Three distinct entry points, not one. |
| 2 | **Investigate** | Open/attach a `Case`, expand the entity neighbourhood in the graph, pull transaction history, device/identity signals, behaviour, prior cases. |
| 3 | **Assess** | Name the fraud pattern, name the fraud type, produce a risk level **with a confidence number**. |
| 4 | **Case lifecycle** | Case is a first-class graph object that gets created, appended to, status-changed, and closed. Its full history must be reconstructible. |
| 5 | **Memory** | Prior closed cases (4 months of them ship with the dataset) must measurably change the agent's output on new cases. Retrieval + outcome priors + recurring-entity detection. |
| 6 | **Controlled evidence gathering** | When uncertain, the agent requests *specific* extra evidence via policy-approved channels (customer validation, step-up auth, analyst query) — then re-reasons. |
| 7 | **Next best action + permissions** | Recommend one or more actions. Some are auto-executable, some need approval, some are recommendation-only. The routing must be explicit. |
| 8 | **Explain + stop** | Say what evidence was used, what remained uncertain, why those actions, and why the investigation stopped where it did. |

### The two sentences that decide the winner

> *"Recommend or take one or more next actions ... and **update those recommendations as new evidence becomes available**."*

> *"The next best action and required approval route recorded: **before** any additional evidence is requested, **after** any additional evidence is received."*

This is the crux. The submission format literally demands a **before/after pair of recommendations per case**. That means your agent cannot be a single-shot pipeline — it must produce a *provisional* recommendation under uncertainty, then a *revised* one after the evidence lands, and the delta between them must be visible and justified. 50% of the score (Investigation accuracy + Next best action) rides on this loop.

Most teams will build a linear RAG pipeline that emits one verdict. **Build the loop.**

### The sentence that opens an Innovation lane

> *"Not every fraud pattern present in the data is documented."*

Five typologies ship in the dataset. The organisers are explicitly telling you there are more hiding in the graph. A team that **mines an undocumented typology out of the confirmed-fraud closed cases and registers it as a new `Pattern` the agent can then match against** has a story nobody else has. See `06-differentiators-and-addons.md`, item D5.

---

## 2. Dataset facts that constrain the design

Source: IEEE-CIS Fraud Detection (Vesta Corporation), re-cut for this hackathon as **HHGOA_IEEE**.

- ~590,000 card transactions, ~6 months, ~13,500 customers. Device and connection records for online transactions.
- **There is no `isFraud` label.** Every transaction carries a *bank model risk score* instead. This is the single most important design constraint — you cannot train a classifier and call it a day. The risk score is a **trigger signal**, not the truth.
- **Closed investigations from months 1–4** are provided, containing both *confirmed fraud* and *cleared* outcomes. This is your training signal, your memory seed, and your backtest set — all three.
- Ships with: the **bank's fraud policy**, **five documented fraud patterns**, **regulatory references**.
- **20 benchmark cases** from months 5–6. Every team is scored on the same 20. Your output on these is the submission.
- You may extend with additional data or sources.

**Read the dataset README before writing a line of code.** It defines every file, every column, the exact answer format, and how the cases work. Where this plan and the README disagree about the answer schema, **the README wins** — everything in `04` is a superset designed to be trimmed down to it.

### Original IEEE-CIS column families (for schema design)

| Family | Columns | Fraud meaning |
|---|---|---|
| Identity of payment instrument | `card1`–`card6` | `card1` = card/account id, `card4` = brand, `card6` = credit/debit. Backbone of the graph. |
| Geography | `addr1`, `addr2`, `dist1`, `dist2` | Billing region, distance between billing and transaction address |
| Email | `P_emaildomain`, `R_emaildomain` | Purchaser and recipient domain. Mismatch is a classic signal. |
| Counting | `C1`–`C14` | Counts of associated entities (how many addresses/phones/emails tied to this card). **Fan-out signals.** |
| Timedelta | `D1`–`D15` | Days since a previous event — days since card first seen, since last transaction. **Novelty and velocity signals.** |
| Match | `M1`–`M9` | Whether name/address fields matched across systems |
| Vesta engineered | `V1`–`V339` | Ranking/counting/entity-relation features. Too wide for the LLM — compress them (see `02`, §5). |
| Identity table | `id_01`–`id_38`, `DeviceType`, `DeviceInfo` | `id_30` OS, `id_31` browser, `id_33` screen resolution, `id_19`/`id_20` network/proxy-ish. Device fingerprinting. |

`TransactionDT` is a **timedelta in seconds from a reference point**, not a real timestamp. Convert it to a synthetic absolute datetime once, at ingest, and use that everywhere — otherwise every temporal query will be subtly wrong.

---

## 3. Required stack (no substitutions on these)

| Component | Requirement | Note |
|---|---|---|
| **TigerGraph** | Savanna (`savanna.tgcloud.io`) or Community Edition (`dl.tigergraph.com`) | Used for **both graph and vector** storage/retrieval. Enable auto-stop/auto-start on Savanna. Use **4.2+** so TigerVector and hybrid retrieval are available. |
| **GSQL + graph algorithms** | Traversal, pattern detection, relationship analysis | Don't do graph work in Python that GSQL should do. Judges will look for this. |
| **TigerGraph MCP** | `github.com/tigergraph/tigergraph-mcp` | Expose graph capability to the agent as MCP tools. 50+ tools covering schema, data, queries, vectors. |
| **GraphRAG** | Ground the LLM with retrieved graph evidence **and** policy/typology/regulatory documents | Explicit instruction: *pass relevant context to the LLM rather than raw data*. Budget your context; don't dump 339 V-columns. |
| **UI** | Analyst dashboard / conversational / case management view | Must demonstrate investigation, case progression, evidence, **uncertainty**, recommendations, next actions. |

Optional and free to choose: agent framework (LangGraph recommended — it is also what the TigerGraph MCP repo recommends), LLM(s), and any external tools or simulated data sources.

**The LLM reasons; the graph decides.** The brief says it outright: *"The LLM should be used for reasoning, tool selection, evidence synthesis, and generating explanations rather than replacing graph analysis."* Any score, count, ring, or traversal result that an LLM produced by eyeballing rows is a point lost. Compute it in GSQL, hand the LLM the result.

---

## 4. Submission checklist (flat list, no boxes)

1. **Working agent.**
2. **Public GitHub repository.**
3. **Agent output on the 20 provided cases.** One answer file per case containing:
   - the case, including internal investigation record, evidence, findings, decisions, actions taken;
   - the case **also written to the graph**;
   - a **suspicious activity report** where policy requires one;
   - the next best action **and required approval route**, recorded **before** any additional evidence is requested **and again after** it is received.
4. **3–5 minute demo video**, end to end.
5. **Technical blog post**: what you built, the architecture, how TigerGraph is used, the agentic capabilities implemented, what you learned, what you'd improve with more time.
6. **Social post on X or LinkedIn** tagging **@TigerGraphDB**, linking the blog or demo.

Item 3's second bullet — *"The case should also be written to the graph"* — is quietly load-bearing. The JSON answer file is not enough; a judge may open your graph and look for `Case` vertices. Write both, from the same code path, so they can never diverge.

---

## 5. Judging criteria → where each is earned

| Criterion | Weight | Where it is won |
|---|---|---|
| **Investigation accuracy** | 25% | Pattern identification correctness; evidence completeness; no-leakage temporal discipline; backtest on the 4 months of closed cases proving calibration. |
| **Next best action** | 25% | The before/after recommendation loop; explicit uncertainty handling; Value-of-Information-driven evidence selection; recommendation actually changing when evidence lands. |
| **Case summary & explainability** | 10% | Case lifecycle as graph objects; evidence-to-finding provenance links; counterfactual explanations ("what would change my mind"). |
| **Agentic design & engineering** | 15% | LangGraph orchestration; MCP tool layer; typed state; permission gate as deterministic code, not prompt text; memory subsystem; audit ledger. |
| **Innovation** | 15% | Hybrid graph+vector case recall; undocumented pattern discovery; policy-as-code compiler; behavioural embeddings on transactions. |
| **Demo quality & completeness** | 10% | A 4-minute video that shows one ambiguous case flip its recommendation live, on camera. |

**Read the weights backwards.** 50% is investigation accuracy + next best action, and only 10% is the case summary. Teams instinctively over-invest in pretty case write-ups. Invest in *being right* and in *the uncertainty loop*.

---

## 6. Scope discipline — what to deliberately not build

- **No custom fraud ML model.** The bank's risk score is given. Your value-add is investigation and action, not a better classifier. A model also can't be trained without labels.
- **No real external API integrations for identity/IP reputation.** The data is anonymised; `card1` is a surrogate key, not a PAN. Real lookups return nothing. Stub them with a deterministic mock service (see `05`, §6) and say so honestly in the blog — judges respect that more than a fake integration.
- **No production auth/multi-tenancy in the UI.** Roles can be a dropdown.
- **No real customer messaging.** The brief explicitly permits simulated, stubbed, or mock APIs for sending messages, freezing accounts, blocking cards, refunds, CRM updates, and case closure.

---

## 7. Support channels

- TigerGraph Discord (mentors and judges answer here): `https://discord.gg/7JMkCAy9D3`
- TigerGraph WhatsApp group for quick doubts and announcements
- Devanshu, DevRel at TigerGraph: +91 7404313376

Join the Discord on day one and ask your schema question early. Mentor contact is free signal about what the judges care about, and the answer often reveals grading intent.
