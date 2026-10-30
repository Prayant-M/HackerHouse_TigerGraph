# One-command reproducibility. `make all` goes from a fresh clone with the
# dataset in Datasets/ to the twenty committed answer files.
#
# Windows without make: use `python -m` targets directly, or run `.\make.ps1`.

PY ?= python

.PHONY: all setup ingest calibrate quick-calibrate cases backtest monitor ui test stage verify clean graph-install graph-algorithms audit \
        case twice replay diff drift facts final-graph proof conformal metamorphic attacks detectors \
        containment quality feedback drills attest-verify canary pipeline tokens final

CASE ?= HHF-001

all: ingest calibrate cases

setup:
	$(PY) -m pip install -r requirements.txt

ingest:            ## normalise, embed, extract policy, build memory
	$(PY) ingest/01_normalise.py
	$(PY) ingest/02_behaviour_embeddings.py
	$(PY) ingest/03_extract_policy.py
	$(PY) ingest/04_build_memory.py
	$(PY) ingest/07_verify.py

calibrate:         ## measure likelihood ratios from the closed cases (~45 min)
	$(PY) ingest/05_calibrate.py
	$(PY) eval/calibration_report.py

quick-calibrate:   ## same, on a stratified sample (~3 min)
	$(PY) ingest/05_calibrate.py --limit 900

cases:             ## every case in the pack, chronologically, fail-closed -> cases/
	$(PY) benchmark/run_case.py --all

# ---------------------------------------------------------------- final round --
case:              ## ONE case from a clean clone: make case CASE=HHF-007  (exit 2 = FAILED_DEPENDENCY)
	$(PY) benchmark/run_case.py --case $(CASE)

twice:             ## same case twice; diffs the decision fields
	$(PY) benchmark/run_case.py --case $(CASE) --twice

replay:            ## reproduce a decision offline from recorded tool I/O
	$(PY) benchmark/run_case.py --case $(CASE) --replay

diff:              ## rerun live: did the data change or the code?
	$(PY) benchmark/run_case.py --case $(CASE) --diff

drift:             ## C12 drift gate on any new files (waits for a fraud-manager approval)
	$(PY) ingest/00_drift.py --auto

facts:             ## fact vector for every closed case (proof precedent, conformal) ~2 h
	$(PY) ingest/08_fact_vectors.py

final-graph:       ## final-round schema + queries + ClosedCase.fact_mask into TigerGraph
	$(PY) graph/install.py --step final_round

proof:             ## Innovation 1 holdout measurement + gate fit
	$(PY) eval/proof_holdout.py

conformal:         ## Innovation 4 calibration + coverage
	$(PY) eval/conformal_calibrate.py

metamorphic:       ## Innovation 3: M1-M7 + hostile-text fuzzing on recorded I/O
	$(PY) eval/metamorphic.py

attacks:           ## C10 evasion-frontier attacks
	$(PY) eval/attacks.py

detectors:         ## C1 typologies, C2 discovery, C3 policy-to-detector
	$(PY) eval/detectors.py

containment:       ## Innovation 2 backtest (three arms + controls ablation)
	$(PY) eval/containment_backtest.py --backend tigergraph

quality:           ## C11 data-quality report and tainted investigations
	$(PY) eval/data_quality.py

feedback:          ## C8 one feedback round, before/after
	$(PY) eval/feedback_round.py

drills:            ## every resilience drill
	$(PY) drills/run_drills.py --case $(CASE)

attest-verify:     ## re-run every attested query; fail on mismatch
	$(PY) eval/attest_verify.py

canary:            ## future-dated canary temporal-wall proof
	$(PY) eval/canaries.py --case $(CASE)

pipeline:          ## C9 alert -> ready case, p95 and cost
	$(PY) benchmark/alert_pipeline.py --enqueue-pack --drain

byo:               ## judges: your own dataset end to end: make byo DATA=path/to/folder NAME=judge1
	$(PY) ingest/byo.py --input $(DATA) --name $(or $(NAME),byo) --accept-mapping

byo-map:           ## mapping proposal only (with evidence), nothing applied
	$(PY) ingest/byo.py --input $(DATA) --name $(or $(NAME),byo) --map-only

grade:             ## organisers' grader on cases/HHF-*.json (January-only and full passes)
	$(PY) eval/grade_official.py

hhg-holdout:       ## Round 1 answers vs the real outcomes now in closed_cases_history.csv
	$(PY) eval/hhg_holdout.py

tokens:            ## generate approval tokens (prints plaintext once, hashes for .env)
	$(PY) scripts/make_tokens.py

final: facts proof conformal cases metamorphic attacks detectors containment quality feedback attest-verify

backtest:          ## replay the October holdout and write eval/reports/
	$(PY) eval/backtest.py

monitor:           ## autonomous sweep of the exam period (innovation extra)
	$(PY) benchmark/monitor.py

ui:                ## analyst console at http://127.0.0.1:8080
	$(PY) ui/server.py

test:
	$(PY) -m pytest tests -q

stage:             ## write the CSVs the TigerGraph loading jobs consume
	$(PY) ingest/06_stage_graph_csv.py

graph-install: stage   ## schema + vectors + load + queries + projections + GDS into TigerGraph
	$(PY) graph/install.py --step all

graph-algorithms:  ## re-run the GDS algorithms (WCC + PageRank) on the live graph
	$(PY) graph/install.py --step algorithms

audit:             ## check every answer file against the data and the policy
	$(PY) eval/audit_answers.py

verify:
	$(PY) ingest/07_verify.py

clean:
	rm -rf data/staged .cache __pycache__
