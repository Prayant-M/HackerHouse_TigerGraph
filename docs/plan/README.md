# Planning documents (pre-build)

These six documents were written before implementation, from the challenge brief
and the dataset README. They are kept for provenance — they are the plan, not the
record.

Where the plan and the built system disagree, **the built system is right and the
reason is in `INTEGRATION.md`**. The substantive divergences:

| Plan said | What was built | Why |
|---|---|---|
| Eight abstract hypotheses (ATO, synthetic identity, bust-out, mule…) mapped onto the dataset's typologies | Seven hypotheses that *are* the dataset's `pattern` enum | The mapping step loses exactly the information the answer file is scored on. Synthetic identity, bust-out and mule have no support in this data |
| Likelihood ratios measured from confirmed-vs-cleared closed cases | Matched-control design with untouched negatives | Measuring confirmed-vs-cleared inverts every signal — see `INTEGRATION.md` §7 |
| Anomaly measured against the card's history up to `as_of` | Measured against a baseline cut 72h before the alert | The earlier legs of a fraud episode otherwise teach the baseline that the fraud is normal |
| Ring detection on device fan-out | Anonymous-proxy ratio | 92% of online transactions sit on a profile shared by ≥3 cards; raw fan-out fires on almost everything |
| A backtest reporting one precision/recall figure | Two arms — `as seen` and `graph only` — plus AUC | In this history the trigger type is perfectly correlated with the outcome, so a single precision figure measures the label rather than the agent |
| Next.js analyst console | FastAPI + one HTML file, no build step | A judge should be looking at it forty seconds after cloning |
| LangGraph checkpointer for UI streaming | Explicit trace in state, streamed over SSE | The state holds live objects a msgpack serialiser cannot round-trip |
| Policy compiled to YAML and interpreted | Policy compiled to typed Python functions carrying verbatim clause text | The ten rules are specific enough that an interpreter adds indirection without adding safety |

`docs/brief/` holds the original challenge statement and the submission form
requirements.
