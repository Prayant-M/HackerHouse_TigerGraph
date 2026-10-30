# Windows equivalent of the Makefile.  .\make.ps1 all
param([string]$Target = "all", [string]$Case = "HHF-001", [string]$Data = "", [string]$Name = "byo")

$ErrorActionPreference = "Stop"
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

switch ($Target) {
  "setup"     { python -m pip install -r requirements.txt }
  "ingest"    {
    Step "normalise";  python ingest/01_normalise.py
    Step "behaviour";  python ingest/02_behaviour_embeddings.py
    Step "policy";     python ingest/03_extract_policy.py
    Step "memory";     python ingest/04_build_memory.py
    Step "verify";     python ingest/07_verify.py
  }
  "calibrate" { python ingest/05_calibrate.py; python eval/calibration_report.py }
  "quick-calibrate" { python ingest/05_calibrate.py --limit 900 }
  "cases"     { python benchmark/run_case.py --all }
  "case"      { python benchmark/run_case.py --case $Case; exit $LASTEXITCODE }
  "twice"     { python benchmark/run_case.py --case $Case --twice }
  "replay"    { python benchmark/run_case.py --case $Case --replay }
  "diff"      { python benchmark/run_case.py --case $Case --diff }
  "drift"     { python ingest/00_drift.py --auto }
  "facts"     { python ingest/08_fact_vectors.py }
  "final-graph" { python graph/install.py --step final_round }
  "proof"     { python eval/proof_holdout.py }
  "conformal" { python eval/conformal_calibrate.py }
  "metamorphic" { python eval/metamorphic.py }
  "attacks"   { python eval/attacks.py }
  "detectors" { python eval/detectors.py }
  "containment" { python eval/containment_backtest.py --backend tigergraph }
  "quality"   { python eval/data_quality.py }
  "feedback"  { python eval/feedback_round.py }
  "drills"    { python drills/run_drills.py --case $Case }
  "attest-verify" { python eval/attest_verify.py }
  "canary"    { python eval/canaries.py --case $Case }
  "pipeline"  { python benchmark/alert_pipeline.py --enqueue-pack --drain }
  "tokens"    { python scripts/make_tokens.py }
  "byo"       { python ingest/byo.py --input $Data --name $Name --accept-mapping; exit $LASTEXITCODE }
  "byo-map"   { python ingest/byo.py --input $Data --name $Name --map-only }
  "grade"     { python eval/grade_official.py }
  "hhg-holdout" { python eval/hhg_holdout.py }
  "backtest"  { python eval/backtest.py }
  "monitor"   { python benchmark/monitor.py }
  "ui"        { python ui/server.py }
  "test"      { python -m pytest tests -q }
  "stage"     { python ingest/06_stage_graph_csv.py }
  "graph-install" { python ingest/06_stage_graph_csv.py; python graph/install.py --step all }
  "verify"    { python ingest/07_verify.py }
  "graph-algorithms" { python graph/install.py --step algorithms }
  "audit"     { python eval/audit_answers.py }
  "all"       { & $PSCommandPath ingest; & $PSCommandPath calibrate; & $PSCommandPath cases; & $PSCommandPath audit }
  default     { Write-Host "targets: setup ingest calibrate cases case twice replay diff drift facts final-graph proof conformal metamorphic attacks detectors containment quality feedback drills attest-verify canary pipeline tokens ui test audit all  (-Case HHF-007)" }
}
