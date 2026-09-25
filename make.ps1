# Windows equivalent of the Makefile.  .\make.ps1 all
param([string]$Target = "all")

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
  "cases"     { python benchmark/run_20.py }
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
  default     { Write-Host "targets: setup ingest calibrate quick-calibrate cases backtest monitor ui test stage graph-install graph-algorithms verify audit all" }
}
