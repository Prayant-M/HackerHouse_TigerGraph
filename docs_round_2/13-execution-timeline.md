# Execution timeline

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

The plan assumes about 42 hours from now to the freeze, including one sleep block. If the freeze is announced earlier, follow the cut order in `17-risks-and-cut-order.md` and keep the tags; never skip a gate.

```text
                          H0    H6    H12   H18   H24   H30   H36   H42
                          |-----|-----|-----|-----|-----|-----|-----|
Setup and questions       ##                                           H0–2
January load, C12 gate      ####                                       H2–6
Baseline on 18, triage          ####                                   H6–10
Decision layer, proofs              #######                            H10–17
Sleep                                      ......                      H17–23
Harness with proofs                              ######                H23–29
Predictive containment                                 ######          H29–35
Metamorphic, attacks                                         ####      H35–39
Freeze prep, rehearse                                            ###   H39–42
                                    ^ H10: first tagged, submittable answer set
```

Each phase ends with a gate. Tag the commit when the gate passes (`final-g1`, `final-g2` …), so there's always a freezable state.

1. **H0–2 · Setup and questions.** Run the setup checklist (`12-setup-checklist.md`). Send the organiser questions. Read the grader.
   - Gate: the grader runs on one dummy answer file, all data files are hashed, and the grader rules are captured as a fixture.
2. **H2–6 · January load through the drift gate.** Build the minimal `00_drift.py` (schema and profile diff, a mapping proposal, an approval token). Run the normalise → vectors → memory → stage → load → projections → GDS → verify pipeline on January plus the new closed cases. While you're in `05_calibrate`, **store each closed case's fact vector as a bitmask**; Innovation 1 needs it.
   - Gate: `07_verify` passes, every case-pack card id resolves, vector status is Ready_for_query, and the drift report and approval are committed.
3. **H6–10 · Baseline and triage.** Run the unchanged agent on all 18 cases and grade them. Score your Round 1 answers against the real HHG outcomes. Hand-read the 18 triggers into `eval/triage.md`: suspected hostile text, ring or connected, undocumented, thin data, R1 vs R2.
   - Gate: 18 files pass the grader's hard checks. Tag `final-baseline`. This is your floor.
4. **H10–17 · Decision layer.** In this order:
   - attestation;
   - January risk-score neutralisation and a softened prior;
   - the R1/R2 split and the §3a connected rule;
   - **conformal abstention with the support check and C11 taint**, which replaces hand thresholds for uncertain;
   - **the proof object and the gate**, with λ, margin and precedent cut-offs fitted on Jul–Oct only.
   - Backtest every change on the closed cases.
   - Gate: zero hard or policy findings, zero blocks or reports on legit HHG holdout cases, and `attest-verify` green. Commit the gate's holdout table.
5. **H17–23 · Sleep.** Start the full holdout backtest and the conformal coverage run before you sleep.
6. **H23–29 · Harness with proofs.** Fail-closed mode with a signed failure record. Token auth on approvals. A least-privilege TG user and `case_write`-only writes. Recorded tool I/O with replay and diff. Tip-off by construction. Redaction and LLM timeout/garbage handling. `drills/` scripts and the resilience statement. Canaries and signed approvals only if ahead.
   - Gate: `make drills`, `make replay` and the tip-off diff are green.
7. **H29–35 · Predictive containment.** `ring_at_asof` (time-sliced WCC), `compromise_origin` with matched controls, the at-risk forward set, the harm-aware block set, `COMPROMISE_POINT` write-back, the three-arm backtest and the controls ablation, and a containment panel naming who is touched.
   - Gate: the backtest is committed, and the lift is reported honestly even if it is weak.
8. **H35–39 · Label-free evaluation and attacks.** Metamorphic relations M1–M7 on the mirror, hostile-text fuzzing on all 18, and the naive-LLM baseline flip rate. Evasion-frontier attacks if ahead. Fix what the tests find and record which HHF answers changed. Then add the byproducts: SAR citations (C4), the proof-first examiner view (C6), p95 and cost (C9).
   - Gate: `make metamorphic` and `make attacks` reproduce every reported number.
9. **H39–42 · Freeze prep.** Do the clean-clone run twice. Regenerate the README numbers from that run. Write the innovation claim page around Innovation 1, with Innovation 2 as the second measurement. Rehearse the demo three times on randomly drawn cases. Push and tag `final-freeze`, and submit the commit hash.

C13 (someone else's schema) arrives on the day: time-box it to 3 hours, inside phase 8, and only if C12's mapper handles the variant.
