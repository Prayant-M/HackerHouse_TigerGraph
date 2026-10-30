# Where the other teams will land

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

All six finalists read the same brief, and the brief already lists example builds for every challenge. Those examples are the floor: expect each of them from at least two teams. Every innovation in files 05–09 starts one step past the floor. It also leans on something only your Round 1 build has: a decision core that is a pure, LLM-free function, and fact vectors replayed for all 5,585 closed cases under their own as_of.

| Challenge area | What the brief's example invites | The step past it |
| --- | --- | --- |
| Hostile text | Regex or LLM filter on trigger_text, plus a demo of one blocked injection | Prove decisions *can't* depend on free text (provenance labels), then fuzz hundreds of mutations and report invariance (Innovation 3) |
| New typologies | Four detectors from the brief's list, each with a backtest | Turn "shared origin weeks before" into **forward** protection of cards not yet hit (Innovation 2), and mine fraud that sits just past your own thresholds |
| Containment | Block the ring minus a penalty | Contain backward *and* forward, with forward actions limited to ones that cost nothing on a legit customer |
| Explainability | Per-sentence citations, an audit replay | Each verdict carries a machine-checkable proof: the minimal facts that force it and the facts that would flip it (Innovation 1) |
| Uncertainty | A probability threshold for "uncertain" | A coverage guarantee (conformal) that widens when January data falls outside what calibration has seen (Innovation 4) |
| Evaluation | Accuracy on the HHG precedents | Label-free metamorphic tests on the 18 cases, which find bugs without an answer key (Innovation 3) |
| Drills | Fail closed, check the token role | Byte-level proofs: no tip-off by construction, recorded-I/O replay, future-dated canaries (Harness moves) |

The headline claim changes from containment to **proof-carrying verdicts**, for one practical reason: the analyst picks the demo case. A proof exists on every one of the 18 cases. A containment plan only exists on ring cases, which may be 2 or 3 of them.
