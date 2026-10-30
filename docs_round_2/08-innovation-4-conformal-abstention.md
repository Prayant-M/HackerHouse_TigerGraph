# Innovation 4: conformal abstention under the January shift

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

**Claim:** "uncertain" should be chosen by a coverage guarantee, not by a hand-picked threshold. It should also widen automatically when a January case looks like nothing the calibration data has seen. That is exactly the brief's warning: the bank model has never seen January.

**How it works**

1. **Calibrate.** Use the matched-control sets from Nov–Dec, the months closest to January. Nonconformity = 1 − calibrated p of the true class. Calibrate separately per trigger type (Mondrian conformal), with α = 0.1.
2. **Decide.** If the prediction set is {fraud, legit}, the verdict is uncertain. With exposure over $500 or conflicting evidence, that becomes ESCALATE_TO_ANALYST under R8; otherwise VERIFY_WITH_CUSTOMER.
3. **Support check.** Measure the case's behaviour-vector distance to its k nearest calibration transactions. Beyond the 95th percentile, the case is "outside support" and the set widens to both classes. This is how January novelty becomes uncertain instead of a confident guess.
4. **Data-quality taint (C11) widens the set too.** That covers a missing identity record, a placeholder value, or a card history too thin to judge. The taint report lists which of your own investigations it touched, which is what C11 asks for.

**The measurement**

- Empirical coverage on the HHG holdout and the October holdout, against the nominal 90%.
- Average set size, overall and for January cases versus Nov–Dec cases.
- Legit customers acted against, compared with Round 1's fixed thresholds.
- How many of the 18 the support check moved to uncertain.

**Honest caveat to state up front.** The closed cases are a selected sample; that was Round 1's calibration lesson. So coverage holds for "cases like the ones the bank investigated", not for all transactions. Say this before a judge does.
