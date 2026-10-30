# Innovation 2: predictive containment from the point of compromise

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

**Claim:** containment as the brief describes it looks backward, blocking cards that were already hit. The bigger saving is forward. Find where the ring's cards were compromised, then protect the cards that passed through the same point but haven't been hit yet. Forward actions are limited to MONITOR_CARD and STEP_UP_AUTH, which cost nothing on a legitimate customer, so the innocent-customer penalty can't touch them.

Banks do this by hand as "common point of purchase" analysis. The brief hints the data contains it ("purchases that share an origin weeks before the loss"). Other teams will likely build it as a detector. Using it to protect cards that haven't been hit yet, with a measured lift, is the step past that.

**Pipeline (all GSQL, all as_of-bounded)**

1. **Backward: find the origin.** For each ring card, collect the entities it touched between 6 weeks and 3 days before its first suspect txn: device profile, billing region, email domain, and product × amount band as a merchant proxy. For each entity, compute lift: the share of ring cards that touched it, divided by the share of matched control cards that touched it. Controls are drawn from the same month, with the same product mix and no fraud. Add a hypergeometric p-value. The origin is the highest-lift entity with p < 0.01 and at least 3 ring cards. This is one installed query, `compromise_origin(ring_cards, entity_type, as_of)`.
2. **Forward: find who's exposed.** Cards that touched the origin in the same window and have no suspect txns as of as_of are "at-risk". Rank them by how recently they touched the origin.
3. **Act on both sides.** At-risk cards get MONITOR_CARD (auto) plus STEP_UP_AUTH on their next card-not-present purchase. Already-hit cards get the harm-aware block set: the smallest set whose block cuts the most exposure, with legit customers named, R10 respected and L1/L2 routes. Every number is attested.
4. **Write back.** A `COMPROMISE_POINT` edge runs from the FraudCase to the origin entity, carrying the window and the lift. At-risk cards get child cases in a WATCH state (C14). The next investigation that touches the origin finds the edge through hybrid recall, so memory now carries *where* fraud came from, not just *what* it was.

**The time-sliced ring.** Build the ring from a projection cut at as_of, then run WCC on that slice. In Round 1, algorithm output was "context, never weighed" because it saw all six months. Cut at as_of, it becomes evidence. Ablate it against the all-time projection.

**The measurement** (future data is used only to score, never to decide)

| Metric | Definition |
| --- | --- |
| At-risk precision | Share of flagged cards with a confirmed-fraud closed case or a suspect episode within 30 days after as_of |
| Lift | That precision divided by the same rate for random cards active in the same window |
| Loss pre-empted | $ of later fraud on flagged cards that the monitor and step-up would have intercepted |
| Innocent cost | Zero blocks by construction; report the count of customers who got a step-up |

Compare three arms: no forward containment (Round 1), device fan-out neighbours (the obvious approach), and origin lift. Ablate matched controls by using raw counts instead. Raw counts should drown in popular entities, which is the same lesson as your Round 1 finding that 92% of online purchases sit on shared devices. That ablation is your proof that the controls matter.

**Data caveat.** There's no merchant id, so origins are limited to what the schema has. If nothing passes the lift test on the Nov–Dec rings, report that honestly. Keep the backward block set and the time-sliced ring, which stand on their own.
