---
title: FraudGraph Analyst Console
emoji: 🕵️
colorFrom: indigo
colorTo: purple
sdk: static
app_file: index.html
pinned: false
short_description: Agentic fraud investigation on TigerGraph, read-only demo
---

# FraudGraph Agent: analyst console (read-only)

A public, read-only copy of the analyst console from the TigerGraph × Hacker
House Goa 2026 agentic fraud investigation project. It shows the benchmark
investigations exactly as the agent wrote them: evidence and how
each piece moved the probability, the case subgraph, similar past cases, the
hash-chained audit trail, the approval queue, and the cases the agent raised
on its own.

The agent itself ran against TigerGraph Savanna through the TigerGraph MCP
server. This copy serves a snapshot of those results, so it needs no graph
connection or API key. Live re-runs are disabled here; clone the repository
and run `python ui/server.py` to watch the agent investigate.
