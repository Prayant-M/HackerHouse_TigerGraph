# Submission checklist

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

Five artifacts are required. Anything pushed after the freeze is ignored, so every item below has to exist at the frozen commit.

- [ ] **Frozen commit hash** for `final-freeze`, sent to the organisers
- [ ] **18 answer files** `cases/HHF-001.json` … `HHF-018.json`, produced by the frozen code (not hand-edited), with 0 hard and 0 policy findings from `grade.py --transactions`
- [ ] **One command from a clean clone**, plus written setup: `make case CASE=HHF-0xx`. The README states the Python version, env vars, data download path, how a judge gets graph access, and the expected runtime
- [ ] **Resilience statement** (`docs/RESILIENCE.md`, one page): dependencies, egress per provider with what data it sees, behaviour per failure, what is logged
- [ ] **Innovation claim** (`docs/INNOVATION.md`, one page): proof-carrying verdicts, the holdout table by margin and precedent, the ablations, and every HHF case where the gate changed the action. Add predictive containment's lift as the second measurement. Every number is attested
- [ ] Per-case time and tokens reported honestly in each answer file and in `eval/reports/run_summary.csv`
- [ ] `make attest-verify` is green at the frozen commit, and `eval/reports/` has the attestation re-run log
- [ ] Tests pass in CI on the frozen commit; gitleaks is clean; `.env` and data are ignored
- [ ] Challenge write-ups, one short file each, listing only what's attested: `docs/challenges/C07.md`, `C10.md`, `C12.md`, `C11.md` (plus C04, C06, C09 if built)
- [ ] README numbers regenerated from the final run, not typed by hand. The demo is scored on whether they match
