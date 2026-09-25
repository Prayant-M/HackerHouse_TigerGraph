# One-command reproducibility. `make all` goes from a fresh clone with the
# dataset in Datasets/ to the twenty committed answer files.
#
# Windows without make: use `python -m` targets directly, or run `.\make.ps1`.

PY ?= python

.PHONY: all setup ingest calibrate cases backtest ui test verify clean graph-install

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

cases:             ## run the agent over the 20 benchmark cases -> cases/
	$(PY) benchmark/run_20.py

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

graph-install: stage   ## schema + vectors + load + queries + GDS into TigerGraph
	$(PY) graph/install.py --step all

verify:
	$(PY) ingest/07_verify.py

clean:
	rm -rf data/staged .cache __pycache__
