# The twenty answer files

`HHG-001.json` … `HHG-020.json`, one per case in `case_pack.csv`, in the dataset's
Answer Format. Regenerate with:

```bash
python benchmark/run_20.py
```

Every file is validated before it is written — enum values, required fields,
the SAR flag agreeing with the final actions, a legitimate verdict carrying no
exposure, and **every identifier checked against the real key sets**, because
the dataset says made-up IDs score zero. A non-zero exit means a file would
have lost points and names which and why.

Each case is also written into the graph from the same payload, so the JSON and
`case_chain(graph_case_id)` cannot disagree.

---

## Reading one

The three required parts are `case`, `sar` and `next_best_actions`, exactly as
the dataset specifies. Beyond them each file carries an **`agent_record`**
block, which is where the investigation actually lives:

| field | what it holds |
|---|---|
| `posterior` | belief across all seven hypotheses, not just P(fraud) |
| `prior` | the trigger-conditioned starting point, so the movement is visible |
| `evidence_with_impact` | every evidence item with the **measured change in P(fraud)** it caused |
| `voi_ranking` | every evidence action scored by information per unit of friction, **including the ones policy forbade and why** |
| `decisions` | the hash-chained decision ledger, with the posterior on both sides of each step |
| `audit_chain.head` | the chain head; `verify()` detects any later edit |
| `explanation.counterfactual` | what response would have changed the decision, and to what |
| `cited_policy_rules` | the rules that produced the actions |
| `forbidden_actions` | what the policy ruled out — often more informative than what it allowed |
| `trace` | the full reasoning trace, node by node, with timings |

---

## What the run produced

| | |
|---|---|
| verdicts | 11 legitimate, 9 fraud |
| patterns | 11 `none`, 3 `card_not_present_new_device`, 2 `out_of_region_use`, 2 `undocumented`, 2 `account_takeover` |
| SARs filed | 2 of 20 |
| evidence requested | 4 cases |
| recommendation changed after evidence | 4 cases |

The dataset warns that about half the cases are legitimate and that an agent
which blocks everything scores badly; `tests/test_answer_schema.py` asserts the
fraud count stays inside a sane band so that guard rail is enforced rather than
hoped for.

Only two cases file a report, which is deliberate — policy §3a requires
confirmed-or-strongly-suspected fraud **and** an aggravating condition
(exposure over $1,000, a shared origin, or a coordinated/undocumented pattern).
Most cases never need one, and the boundary is explicitly part of the score.

---

## The two worth opening first

**`HHG-006.json` — undocumented typology U1.** A customer dispute that turns out
to be four online purchases inside thirty minutes at $478.95, $456.96, $488.04
and $482.12 — every one parked just under a $500 authorisation ceiling,
$1,906.07 in total. It matches no documented pattern and matches five closed
cases (`CC-3748`, `CC-3841`, `CC-3907`, `CC-4086`, `CC-4124`) that the bank's own
analysts confirmed as fraud and could not categorise. Invisible to
per-transaction scoring, because every individual leg looks ordinary.

**`HHG-014.json` — undocumented typology U2.** An analyst asks about "the same
unusual device profile" across several cards. It is a Samsung handset behind an
anonymising proxy, new to every account it touches, shared with 19 other
cardholders in thirty days. The discriminator is not how many cards share the
profile — 92% of online transactions in this dataset sit on a profile shared by
three or more cards — but that **every** card that ever reached it came through
an anonymous proxy: a ratio of 1.00 against 0.03 for an ordinary shared browser
fingerprint. Its `similar_prior_cases` are the four closed ring cases, found by
the hybrid graph+vector recall through the shared device.

**`HHG-002.json`** is the one to open for the before/after loop, and
`HHG-007`, `HHG-017` and `HHG-020` do the same thing. Belief starts at 0.29,
which supports no defensible action either way, so the agent commits to a
provisional `VERIFY_WITH_CUSTOMER` + `ESCALATE_TO_ANALYST` under policy R1 and
R8 — *before* asking anything. It then picks the question with the most
information per unit of customer friction, the validation comes back confirming
the purchase, belief falls to 0.02, and the revised recommendation becomes
`CLOSE_NO_FRAUD`. Both recommendations are recorded, with the delta and the
rule that produced each.

All four revisions in this run move toward *clearing* a case rather than
blocking one, and that is not a quirk of tuning. The cases that would revise the
other way are customer disputes, and on those the agent already has the
cardholder's statement at the outset — so under policy §5 there is nothing worth
asking, and the loop correctly does not run.

---

## Simulated responses

Customer and analyst replies are not provided by the dataset, so they are
simulated and the assumption is recorded in `evidence_requests[].assumed_response`
on every case that has one.

The responder takes the **most likely** reply under the agent's own belief at
that moment, and never sees any outcome label. Sampling would have been the more
obviously realistic choice and is the wrong one here: on a balanced case the
sampled reply is close to a coin flip, and since a denial carries a likelihood
ratio of 3 and a confirmation 0.08, that coin flip would decide the verdict. Set
`SIMULATION_MODE=sample` to switch, seeded per case so it stays reproducible.
