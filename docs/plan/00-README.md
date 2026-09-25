# TigerGraph Agentic Fraud Investigation (HHGOA) — Complete Plan

Six documents. Read them in order the first time; after that use this page as the index.

| File | What's in it |
|---|---|
| `01-problem-brief.md` | The problem statement decoded into eight acceptance capabilities, dataset constraints, IEEE-CIS column families, required stack, submission list, judging-criteria map, and what to deliberately *not* build |
| `02-architecture-and-graph-model.md` | Six-layer architecture, full graph schema (transaction subgraph + case subgraph + vector attributes), ingestion pipeline, the GSQL investigation toolkit with the signature hybrid query, behavioural embeddings, repo structure |
| `03-agent-design-and-uncertainty-engine.md` | LangGraph topology, hypothesis space, Bayesian evidence ledger, two-sided stopping rule, Value-of-Information engine, the before/after recommendation loop, policy-as-code, permissions, memory consolidation, answer-file schema |
| `04-build-plan-and-timeline.md` | Ten phases with hour estimates and gates, 10-day schedule, 72-hour compressed variant, demo video shot list, blog outline, risk register, cut-order |
| `05-setup-keys-and-accounts.md` | **Everything you personally have to provide** — accounts, API keys, budget, full `.env.example`, local requirements, the decisions only you can make, day-one 30-minute checklist |
| `06-differentiators-and-addons.md` | Thirteen add-ons ranked by score impact per hour, selection guide by time available, and three things that lose points |

---

## The one-paragraph version

Build a LangGraph agent over TigerGraph that opens a fraud `Case` as a first-class graph object, gathers evidence through GSQL investigation primitives exposed as MCP tools, and maintains a **Bayesian posterior over eight competing fraud hypotheses** rather than a single risk score. When the posterior is too uncertain to act, a **Value-of-Information engine** picks the single highest-information-per-unit-of-friction evidence action that policy permits, records a **provisional** recommendation with its approval route, dispatches a simulated request, then re-reasons and records a **revised** recommendation — which is exactly the before/after pair the submission format demands. Memory is a **hybrid graph + vector query in one GSQL statement**: semantic similarity over prior case narratives fused with structural overlap on shared entities. Every decision that must be defensible — risk arithmetic, policy enforcement, approval routing, stopping — lives in a deterministic Python core that cannot call an LLM. The LLM plans, selects tools, synthesises, and explains.

## The three things that decide the outcome

1. **The revision loop is the product.** Fifty percent of the score is investigation accuracy plus next best action, and the submission format explicitly requires a recommendation recorded before evidence is requested and again after it arrives. A single-shot pipeline cannot produce that honestly.
2. **Calibrate against the closed cases, don't just retrieve them.** Four months of confirmed and cleared outcomes ship with the dataset. Measure real likelihood ratios from them, then prove calibration with a committed backtest. It turns an impression into a number.
3. **Use TigerGraph for something a vector store can't do.** Fusing `vectorSearch` with a graph traversal in one query is the reason this project belongs on TigerGraph, and it is the headline for the blog post.

## Start here

Open `05-setup-keys-and-accounts.md` §8 and do the day-one 30-minute checklist before anything else. Then read the dataset README twice, then read `01`.
