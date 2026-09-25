# Getting Started

From a fresh clone to a running demo, with what to check at each step. For the
design, read `README.md`; for the diagrams, `docs/ARCHITECTURE.md`; for accounts
and keys, `SETUP_REQUIRED_FROM_YOU.md`.

Commands are shown for PowerShell on Windows. `make <target>` and
`.\make.ps1 <target>` are interchangeable.

---

## 1. Prerequisites

- Python 3.11 or newer, about 8 GB RAM, 4 GB free disk
- The HHGOA dataset in `Datasets/`: `transactions.csv`, `identity.csv`,
  `closed_cases_history.csv`, `case_pack.csv`
- Optional: a TigerGraph Savanna workspace (4.2 or newer) and one LLM API key

```powershell
python -m pip install -r requirements.txt     # includes tigergraph-mcp and mcp
Copy-Item .env.example .env
```

> `.env` is gitignored. Passwords, secrets and API keys go there, never in
> `.env.example`, which is committed.

---

## 2. Build the data (no TigerGraph needed)

| Step | Command | Time | Check |
|---|---|---|---|
| Stage and verify | `.\make.ps1 ingest` | ~3–20 min | `07_verify` prints every check `ok`; `card_id` agreement **1.0000** |
| Calibrate (quick) | `.\make.ps1 quick-calibrate` | ~20 min | `peer_purchases` near the top of "strongest measured likelihood ratios" |
| Calibrate (full) | `.\make.ps1 calibrate` | ~45 min+ | same, on all 5,565 closed cases |

The embedding step downloads model weights once. `EMBEDDING_PROVIDER=tfidf`
avoids the download and stays byte-reproducible.

---

## 3. Load TigerGraph

1. Fill in `.env`:

   ```bash
   TG_HOST=https://tg-xxxx.i.tgcloud.io
   TG_GRAPH_NAME=FraudGraph
   TG_USERNAME=<database user with the superuser role>
   TG_PASSWORD=<its password>
   GRAPH_BACKEND=auto      # TigerGraph when reachable, otherwise the local mirror
   TG_VIA_MCP=1            # reach the graph through the TigerGraph MCP server
   GRAPH_STRICT=0          # 1 = fail instead of falling back to the mirror
   ```

   In the Savanna console, confirm the version is **4.2 or newer** and that
   **auto-stop and auto-start** are both on.

2. Wake the workspace (it auto-stops when idle). Wait for `"message":"pong"`:

   ```powershell
   curl.exe -s https://<your-host>/api/ping
   ```

3. Stage and install:

   ```powershell
   python ingest/06_stage_graph_csv.py        # ~2 min
   python graph/install.py --dry-run          # preview
   python graph/install.py --step all         # ~20–40 min
   ```

   Steps run in order: `schema → vectors → load → queries → projections → algorithms → verify`.
   If one fails, fix the cause and resume with `--from <step>`.

**Check the install output:**
- [ ] Every load upload shows no rejected lines.
- [ ] `Query installation summary … failed: 0` (float-comparison warnings are harmless).
- [ ] `building ANON_CO_OCCURS… anon_edges: 1725`, then WCC and PageRank run without error.
- [ ] Verify: Transaction 590,742 · Card 14,850 · ClosedCase 5,565 · PolicyDoc 41, each `ok`.
- [ ] `hybrid_case_recall returned … rows ok`. If it says EMPTY, the vector index is still building; wait and run `--step verify` again.

---

## 4. Run the twenty cases

```powershell
python benchmark/run_20.py                 # add --no-llm for template prose
python eval/audit_answers.py               # policy + data audit of cases/
```

**Expected:**

| | |
|---|---|
| header | `backend : tigergraph` and no "falling back" line |
| verdicts | 11 legitimate, 9 fraud |
| SARs | 2 (HHG-006, 014) |
| changed after evidence | 5 (HHG-002, 007, 017, 018, 020) |
| audit | `0 issue(s) across 20 files` |
| LLM footer | `llm tokens: … across N calls`; an `llm errors:` line means those calls fell back to templates (usually quota) |

Useful variants:

```powershell
python benchmark/run_20.py --case HHG-018  # one case
python -m pytest tests -q                  # 64 tests
$env:GRAPH_BACKEND = "local"; python benchmark/run_20.py   # no TigerGraph at all
```

---

## 5. Open the console

```powershell
python ui/server.py                        # http://127.0.0.1:8080
```

- [ ] The status pill reads **TigerGraph · via MCP**. "Local mirror" means the workspace was asleep at start-up: ping it and restart the server.
- [ ] **Scoreboard**: 9 · 11, 2 SARs, 5 changed, audit clean 20 / 20.
- [ ] **Cases → HHG-018**: Overview shows first recommendation → question → final decision (R7, no block).
- [ ] **Cases → HHG-014 → Graph**: zoom, pan, click a node; the device ring sits on the right.
- [ ] **Cases → HHG-019 → Evidence** (or open `#/cases/HHG-019/evidence`): the probability path starts at 38% and the `peer_purchases` row adds about 51 points; the item carries a "Derived inference" badge. Fraud, blocked, no SAR.
- [ ] **Audit trail**: press ▶ Play; the ledger checks "Graph write verified by read-back".
- [ ] **Approvals**: approve one; the toast confirms the `APPROVED_BY` edge.
- [ ] **Monitoring**: the structuring sweep finds fraud the bank's model misses.

---

## 6. Optional extras

```powershell
python eval/backtest.py        # ~10 min, October holdout → eval/reports/backtest.md
python benchmark/monitor.py    # ~5 min, proactive sweep → benchmark/autonomous/
```

---

## 7. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `FileNotFoundError` in `Datasets/` | Dataset missing or in the wrong folder |
| HTML "Starting workspace" instead of results | Savanna was asleep. Ping until `pong`, rerun |
| 401 / 403, "does not have the permission" | Database user lacks the superuser role |
| "reserved keyword" / "Encountered" from GSQL | Schema already avoids 4.2's reserved words; the installer names the failing file |
| `falling back to local mirror` | Workspace unreachable at start; ping, restart. `GRAPH_STRICT=1` makes this an error |
| `MCP … failed; using the direct connection` | `pip install tigergraph-mcp`; the call still completes directly |
| `llm errors: … 429 quota` | LLM quota exhausted. Use `--no-llm`; verdicts do not change |
| "No similar prior cases" everywhere | Vector index still building; `graph/install.py --step verify` |

---

## 8. Read next

- `README.md`: capabilities, design notes, results
- `docs/ARCHITECTURE.md`: twelve Mermaid diagrams covering every component and path
- `INTEGRATION.md`: the full engineering record, including what other teams' designs taught us
- `DEMO_VIDEO_SCRIPT.md`: the 3–5 minute video, shot by shot
- `SETUP_REQUIRED_FROM_YOU.md`: accounts, keys and the submission checklist
