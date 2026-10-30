# Innovation claim — proof-carrying verdicts

*One idea to judge, and the measurements where it changes the outcome. Every number in the block below is regenerated from the last run by `scripts/readme_numbers.py`; the full tables are in `eval/reports/`.*

## The idea

Our decision core is a pure, LLM-free function of attested facts. So the reason for an action does not have to be written as prose: it can be **computed**. Every answer file carries a `proof` block:

| Part | Definition | How it is computed |
|---|---|---|
| Minimal sufficient facts | the smallest subset of the case's attested facts that, with every other fact neutral (likelihood ratio 1), still yields the same action class | greedy deletion, one call of the pure core per step (`core/proof.minimal_sufficient`) |
| Flip set and margin *k* | the smallest set of facts whose removal changes the action class | singles, then pairs, then triples (`core/proof.flip_set`) |
| Precedent support | closed cases opened before `as_of` whose replayed fact vector contains the minimal set, with how the bank ruled | one installed GSQL subset match over `ClosedCase.fact_mask` (`graph/queries/precedent_by_facts.gsql`); fact vectors replayed for every closed case by `ingest/08_fact_vectors.py` |
| Single-fact flips | for each fact, what the decision becomes without it | the examiner's "flip one fact live" (console Proof tab, `POST /api/proof/{case}/flip`) |
| Reproduction check | whether the fact-replay decision equals the live decision | `reproduces_live` |

The replay goes through the *same* `EvidenceLedger.add_signal` / `add_solicited` the agent used, includes the conformal layer and any analyst-feedback scaling, so the proof is a proof of the decision that was actually taken.

**The gate (one-way).** A harmful action (BLOCK_CARD, BLOCK_ALL_CARDS, FILE_REPORT) is kept only if margin *k* ≥ the fitted floor **and** precedent does not contradict it (≥ *n* precedents with ≥ *s* cleared). Otherwise it is downgraded to VERIFY_WITH_CUSTOMER + ESCALATE_TO_ANALYST, the verdict becomes uncertain, and the answer says why. R2 (the cardholder denied the charge) is exempt because policy requires the block; its margin is still recorded. Strong precedent can never promote an action: the gate can only remove harm. Cut-offs are fitted on July–September replays and reported on the October holdout (`eval/proof_holdout.py`).

## Why it is hard to copy

It needs a side-effect-free decision function and a fact vector for every closed case under its own `as_of`. An agent with an LLM in the decision path cannot compute a flip set; it can only write a counterfactual sentence.

## Measurements

<!-- numbers:start -->
<!-- numbers:end -->

* Holdout table by margin and by precedent agreement, and the ablation (no gate / margin only / precedent only / both): `eval/reports/proof_holdout.md`.
* Every case where the gate changed the action is listed in `eval/reports/run_summary.md` (`gate` column) with its reason in the answer file's `agent_record.gate`.
* If the holdout shows fragility does *not* predict errors, the report says so and the gate is not claimed; the proof stays as the examiner tool (C6).

## Second measurement — predictive containment

Containment from the point of compromise: the time-sliced ring (`ring_at_asof`, a seeded WCC cut at `as_of`), the compromise origin by lift against matched controls (`origin_counts`), forward protection of cards that passed through the origin with free actions only, and a harm-aware block set. Table: `eval/reports/containment_backtest.md` (arms: none, device fan-out, rare-device fan-out, origin lift with and without the specificity cap, raw counts, time-sliced vs all-time component). The honest reading is in that file: matched controls are what make an origin usable; rare-device fan-out is a strong baseline on rings that are themselves defined by rare devices.

## Honest limits

* The final-round January files were not present in this repository's data folder when this run was made; every number here is on the July–December data and the twenty Round 1 cases. The loaders, the drift gate and the case-pack selection pick the January files up automatically when they are dropped into `Datasets/`.
* Closed cases are a selected sample (the bank's investigations), so precedent counts and conformal coverage hold for "cases like the ones the bank investigated".
* Replays carry no customer replies, so R2 never fires in the holdout; live cases with a denial are exempt from the gate anyway.
