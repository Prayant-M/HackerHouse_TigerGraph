# Setup checklist

*TigerGraph × HH Goa 2026 — Final Round. Part of the execution plan; start at [`00-README.md`](00-README.md).*

Do this block first, in one sitting. Each item has an external dependency that can stall you later.

**Data and grader**

- [ ] Download the final-round Drive folder to `data/raw/final/` (gitignored). Record a sha256 per file in `data/manifest.json`; this becomes the `data_snapshot` for attestations
- [ ] Read `grader/grade.py` end to end. Copy the exact verdict values, the harmful-action set, the approval-route table and every policy check into `tests/fixtures/grader_rules.json`. Confirm which actions besides BLOCK_CARD, BLOCK_ALL_CARDS and FILE_REPORT are penalised on legit cases
- [ ] Check how the grader treats affected txns from before January. The published command passes only `transactions_2017q1.csv`, so a December leg may fail the "ID exists" check
- [ ] Confirm `policy/fraud_policy.md` and `cases/answer_format.md` are byte-identical to Round 1 (diff them)

**Graph (Savanna)**

- [ ] Wake the workspace and confirm 4.2.x, auto-stop and auto-start
- [ ] Re-verify card-id pinning on January. The K index came from labelled txns; check that every card id in the case pack and the new closed cases resolves, and fail loudly otherwise
- [ ] Behaviour vectors for January: **transform with the saved Round 1 PCA, don't refit**, or every old vector shifts
- [ ] Embed the 20 new closed-case narratives (local 384-d model, no egress). Upsert them and poll vector status until `Ready_for_query`
- [ ] Rebuild the CO_OCCURS / ANON_CO_OCCURS projections with January, rerun GDS, and add the time-sliced `ring_at_asof` query
- [ ] Dedupe: exclude agent-written HHG `FraudCase` vertices from recall, or link them to their new `CC-xxxx` twins
- [ ] Users: a superuser for loading only, plus an agent user that can run installed queries and the single `case_write` query, nothing else

**Keys, auth and egress**

- [ ] LLM key with a hard spend cap. Write down the provider and model name for the resilience statement
- [ ] Generate three approval tokens (L1 analyst, team lead, fraud manager). Keep them hashed in `.env`, never in the repo. Have a judge-facing token for each ready to hand over on paper or in DM
- [ ] Take the public HF console offline, or put it behind the same auth and declare it
- [ ] List every egress: Savanna (all graph data), the LLM provider (what goes in the brief), and nothing else. Embeddings stay local

**Repo and reproducibility**

- [ ] Branch `final` from the Round 1 commit, and tag `round1-final` for provenance
- [ ] Pin every dependency (`requirements.lock`) and pin the `tigergraph-mcp` version
- [ ] One command: `make case CASE=HHF-007`. It validates the env, checks the graph is reachable, runs the agent, writes `cases/HHF-007.json` and exits non-zero on failure. Also add `make all`, `make grade`, `make drills`, `make attest-verify`, `make twice CASE=…`
- [ ] CI: pytest on push, plus gitleaks (or `detect-secrets`) as a pre-commit hook and a CI step
- [ ] Clean-clone test: a fresh container, `git clone`, follow the README literally, run one case. Do this at least twice before the freeze

**Ask the organisers (Discord or in person)**

- [ ] Freeze time and Stage 1 timing
- [ ] How drill judges reach the graph and run the one command (your workspace with a token you give them, or their own load)
- [ ] When the C13 variant is released
- [ ] Whether simulated customer replies are still acceptable as "evidence received"
