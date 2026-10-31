# Deploying FraudGraph

There are two ways to put the console online. They serve different readers.

| | **Read-only snapshot** | **Live agent** |
|---|---|---|
| What it shows | The 38 answer files, evidence, audit trail, approval queue, ring replay | All of that, **plus "Re-run live"**: the agent investigates against TigerGraph and streams each step |
| Needs TigerGraph | No | Yes (Savanna, running) |
| Needs an LLM key | No | Optional (prose only; decisions are deterministic) |
| Secrets on the host | None | TigerGraph and model credentials, approval-token hashes |
| Build | `python deploy/build_space.py --static` | `python deploy/build_space.py --live` |
| Size | 0.8 MB | 8 MB of source; ~1.5 GB image (CPU torch, embedding model baked in) |
| Cost | Free (HF static Space, GitHub Pages, Netlify, Vercel) | Free tier on Google Cloud Run / Render; HF Docker Spaces need a paid plan |
| Current copy | https://prayant-fraudgraph-console.static.hf.space | not deployed yet |

The read-only copy is covered in `GETTING_STARTED.md` §6a. This page is about the
live agent.

---

## 1. What the live bundle contains, and what it does not

`python deploy/build_space.py --live` writes `build/live/`:

| Included | Why |
|---|---|
| `src/fraudagent/`, `ui/`, `benchmark/*.py` | The agent, the console, the case runner |
| `graph/queries/`, `graph/algorithms/` | The store reads the installed query names from these |
| `cases/HHF-*.json`, `HHG-*.json`, `benchmark/autonomous/` | The answer files the console shows before anyone re-runs |
| `data/policy`, `detectors`, `schema`, `lifecycle`, `approvals`, `manifest.json` | Policy text, the detector registry, case ownership/SLA, the approval ledger |
| `Datasets/round_2_dataset/cases/case_pack_final.csv` | The 18 cases the console can re-run |
| `data/staged/`: likelihood ratios, conformal calibration, proof gate, closed-case facts, embedder config | Calibration the agent reads on the TigerGraph path |
| `data/staged/behaviour_emb.parquet`, **cut to the 18 flagged transactions** | Conformal support check (160 MB → a few KB) |

**Not included:** `.env`, `.cache/` (including the approval signing key), and the
700 MB of staged transactions. The graph serves the transactions. The build refuses
to finish if a `.env`, a signing key or any other parquet file ends up in the bundle.

The Dockerfile pins:

```
GRAPH_BACKEND=tigergraph  GRAPH_STRICT=1   # never silently fall back to a mirror
TG_VIA_MCP=1                               # every graph call goes through the TigerGraph MCP server
CONSOLE_RUN_AUTH=1  CONSOLE_MAX_LIVE=1     # live runs need a token; one at a time
TG_LOAD_VERSION=staged:…                   # same data_snapshot the answer files were attested against
```

## 2. How a public URL is kept safe

A live run calls TigerGraph, spends model quota and writes a `FraudCase` through
`case_write`. A public URL must not let a stranger do that, so:

- **Live runs need a token.** `GET /api/investigate/{case}` and
  `POST /api/replay/{case}/rerun/{seq}` return **401** without a token that matches
  `APPROVAL_TOKENS` (any role). The console asks for the token the first time someone
  presses *Re-run live* and keeps it for that browser tab only. EventSource cannot
  send headers, so the stream passes it as `?token=`. The host's logs may record
  that URL, so treat demo tokens as short-lived.
- **One run at a time.** A second run while one is in progress gets
  *"Another live investigation is running"*, not a second bill.
- **Approvals stay role-checked and signed.** An analyst token cannot approve an L2
  action (403), the same as locally.
- **Browsing needs nothing.** Cases, evidence, audit, the approval queue and the
  ring replay are open.
- **A sleeping graph doesn't take the page down.** `/api/health` reports
  `backend: unavailable` with the reason, and the page still loads.
- **The breaker still applies.** If the model quota runs out, prose falls back to
  templates within seconds. Decisions are unchanged (see C9 in
  `CHALLENGES_DEEP_DIVE.md`).

Tested in `tests/test_deploy.py`: no token or a wrong token gets 401, a known
token passes, and the bundle holds no secrets or bulk data.

## 3. Secrets the host must provide

Set these in the host's secret store, never in the bundle:

| Name | Value |
|---|---|
| `TG_HOST` | Savanna workspace URL (`https://….tgcloud.io`) |
| `TG_GRAPH_NAME` | `FraudGraph` |
| `TG_USERNAME`, `TG_PASSWORD` | A database user. Prefer one with only `agent_role` (`graph/rbac.gsql`), not the superuser |
| `TG_SECRET` *(or `TG_TOKEN`)* | If you authenticate with a secret instead |
| `TG_RESTPP_PORT`, `TG_GSQL_PORT`, `TG_VERSION` | Copy from your local `.env` if you set them there |
| `LLM_PROVIDER`, `LLM_MODEL`, `GOOGLE_API_KEY` | `google`, `gemini-3.6-flash`, the key. Omit all three and set `AGENT_USE_LLM=0` for template prose |
| `AGENT_USE_LLM` | `1` with a key, `0` without |
| `APPROVAL_TOKENS` | The hashes-only line from `python scripts/make_tokens.py` |
| `APPROVAL_SIGNING_KEY` | 64 hex characters: `python -c "import os;print(os.urandom(32).hex())"`. Without it the container makes a new key on every restart, and earlier signatures no longer verify against it |

`make_tokens.py` prints each plaintext token **once**. Give those to the people
(or judges) who may run the agent. Only the hashes go to the host.

## 4. Build

```powershell
python deploy/build_space.py --live        # → build/live/  (~8 MB)
```

Rebuild after re-running cases, so the answer files the console shows are current.

## 5. Deploy: pick one host

### A. Google Cloud Run (recommended: free tier, scales to zero, handles streaming)

```powershell
gcloud auth login
gcloud config set project <your-project>
gcloud run deploy fraudgraph-agent --source build/live --region asia-south1 `
  --port 7860 --memory 2Gi --cpu 1 --timeout 900 --max-instances 1 `
  --allow-unauthenticated `
  --set-env-vars "TG_GRAPH_NAME=FraudGraph,LLM_PROVIDER=google,LLM_MODEL=gemini-3.6-flash,AGENT_USE_LLM=1" `
  --set-secrets "TG_HOST=tg-host:latest,TG_USERNAME=tg-user:latest,TG_PASSWORD=tg-password:latest,GOOGLE_API_KEY=gemini-key:latest,APPROVAL_TOKENS=approval-tokens:latest,APPROVAL_SIGNING_KEY=approval-signing-key:latest"
```

Create each secret first, typing the value at the prompt so it never sits in your
shell history:

```powershell
gcloud secrets create tg-password --data-file=-
```

`--timeout 900` lets a slow investigation finish streaming. `--max-instances 1`
keeps `CONSOLE_MAX_LIVE=1` true across the service. `--allow-unauthenticated`
opens the page; live runs are still token-gated (§2).

### B. Hugging Face Docker Space

HF's documentation says Spaces that run compute, Docker included, need a paid
plan. Static Spaces stay free. With a paid plan:

```powershell
huggingface-cli login                                   # write token
huggingface-cli repo create fraudgraph-agent --type space --space_sdk docker
huggingface-cli upload <you>/fraudgraph-agent build/live . --repo-type space
```

Then set each §3 value as a **Secret** under the Space's *Settings → Variables and
secrets*, and restart the Space. The bundle's `README.md` carries the Space front
matter (`sdk: docker`, `app_port: 7860`). HF runs the container as uid 1000, which
the Dockerfile already uses.

### C. Render / Railway / Fly

All three build `build/live/Dockerfile` directly: push `build/live` to a Git repo,
or use the host's CLI (`fly launch --no-deploy`, then `fly secrets set …`,
`fly deploy`). The app listens on `$PORT` (default 7860). Give it at least 2 GB of
memory, because the embedding model and pandas need it.

## 6. Verify the deployment

```powershell
$U = "https://<your-url>"
curl.exe -s "$U/api/health"                          # graph.backend = tigergraph, run_auth = true
curl.exe -s -o NUL -w "%{http_code}`n" "$U/api/investigate/HHF-001"   # 401: the gate holds
curl.exe -s -N "$U/api/investigate/HHF-001?token=<analyst token>"     # streams step events, then done
```

In the browser, open a case, press **▶ Re-run live**, paste the analyst token, and
watch the posterior move. The status pill should read **TigerGraph · via MCP**.

## 7. Operating notes

- **Savanna auto-stops when idle.** Wake it before a demo (open the workspace, or
  `curl $TG_HOST/api/ping` until `pong`). The first call after a wake can take
  minutes. While it is asleep the page still works; live runs fail closed with the
  reason.
- **Savanna billing must be valid.** A workspace with a failed payment returns
  `403 "Payment validation failed"` and cannot start, whatever the host does.
- **Cold start.** The first live run in a fresh container takes about 150 s to load
  the embedding model and open the MCP session; later runs take about 30–80 s.
- **The disk is temporary.** Answer files a live run writes inside the container
  are lost on restart. The graph keeps the record: every run writes its
  `FraudCase` through `case_write`. Rebuild and redeploy to refresh the files the
  page opens with.
- **Allowlists.** If the Savanna workspace restricts source IPs, add the host's
  egress range, or every graph call will time out.
- **Rotating tokens.** Run `make_tokens.py` again, replace `APPROVAL_TOKENS`, and
  restart. Old tokens stop working at once.
