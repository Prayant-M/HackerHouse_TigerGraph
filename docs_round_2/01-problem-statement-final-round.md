# TigerGraph × Hacker House Goa 2026 — Final Round Problem Statement

*The complete final-round brief, start to end, organised for reference. Sections 1–14 follow the official brief. The appendices add context from Round 1 (the original challenge, the dataset, and a policy quick reference) so this file stands on its own. Where an appendix and the official files disagree, `policy/fraud_policy.md` and `cases/answer_format.md` win.*

**At a glance:** 6 teams · 18 cases · 100 points · Fraud Operations Policy v1.0, unchanged.

> Round 1 asked whether your agent can investigate fraud. This round asks whether a bank can run it.

---

## 1. The problem

A bank does not deploy an agent because it scored well on a benchmark. It deploys one when it can answer harder questions:

- What happens when the graph goes down mid-investigation?
- What happens when the customer's message is written to manipulate the agent rather than inform it?
- What happens when two signals disagree?
- What happens when someone claims an approval role they do not have?
- What happens when the loss is $23 but connects to eleven other cards?

Your agent will run in front of a fraud team, on cases it has never seen, with faults injected while it runs. Build something that investigates correctly and stays safe when conditions are bad. When it cannot be sure, it should say so and hand the case to a person rather than guess.

**The most valuable work here makes an analyst faster without making the bank's risk bigger.**

---

## 2. What changed in the data

It is the same bank, two months further on. Your November–December data still applies. January 2017 is new, in the same schema. Load it alongside what you already have: baselines, history and precedent all depend on the full July 2016 to January 2017 picture.

| File | Rows | What it is |
| --- | ---: | --- |
| `transactions_2017q1.csv` | 60,196 | January 2017 transactions. The same 397 columns as Round 1, including `customer_id`, `ts`, `channel` and `risk_score` |
| `identity_2017q1.csv` | 15,893 | Identity records for the January transactions that have them |
| `closed_cases_history.csv` | 5,585 | Replaces your Round 1 copy. Holds 20 extra closed cases: the HHG-001…020 investigations, with their real outcomes |
| `cases/case_pack_final.csv` | 18 | The cases to answer, HHF-001 … HHF-018 |
| `policy/fraud_policy.md` | — | Unchanged. v1.0 |
| `cases/answer_format.md` | — | Unchanged |
| `grader/grade.py` | — | The same grader the organisers use. Python 3, no dependencies |

### Your Round 1 cases are now closed cases

The 20 cases investigated in Round 1 appear in `closed_cases_history.csv` as ordinary `CC-xxxx` records. Each has its outcome, pattern, affected transactions, exposure, connected cards and actions taken. They are precedent now, exactly like the other 5,565.

Every team gets the same file, so nobody is penalised for not having written cases back to the graph in Round 1. But an agent that retrieves prior cases by shared entity has real precedent available to it this round.

### The bank's model has not been retrained

It has never seen what is in January, so for the newest activity `risk_score` is close to useless. **A low score is not evidence of innocence.**

### Download

One folder holds the January 2017 data, the updated closed cases, the case pack, the policy, the answer format and the grader. It is linked from the brief as "Open the dataset on Google Drive".

---

## 3. What you are answering

There are 18 cases, HHF-001 … HHF-018. The answer format is the same as Round 1, with three parts per case:

1. the internal case;
2. the SAR, when policy calls for one;
3. the next best action, recorded **before** and **after** you gather evidence.

**Triggers in the pack:** 11 `risk_score`, 4 `customer_report`, 3 `analyst_request`.

**What the pack contains,** in an order the organisers do not disclose:

- **Fraud,** including activity that connects several cards through something they share.
- **Legitimate activity that looks suspicious.** This is roughly half the pack. In Round 1 the most common failure across the whole field was not missing fraud; it was blocking people who had done nothing wrong. A block on a legitimate customer is a policy breach under R1, and it is scored as one.
- **Ambiguous or conflicting evidence,** where uncertain plus escalation is the correct answer under R1 and R8.
- **Activity matching none of the five documented patterns.** R9 applies: describe it in your own words; do not force it into a known category.
- **Free text written to instruct your agent.** Some `trigger_text` contains strings aimed at your model rather than at an analyst. Treat all free text as data, never as instruction. Some of those strings ask for an outcome that happens to be correct, so inverting whatever the text demands is not a strategy.

Answering the 18 cases is not optional and is not a challenge. The challenges are what you build around that, and what you demo.

---

## 4. The challenges

**Innovation (25 points)** covers novel detection, novel use of the graph, novel agent design, novel evaluation and real-world value, each scored 0 to 5. An idea scores zero unless you show a case or a measurement where it changes the outcome. An ablation helps. The challenges below are how these 25 points are won.

There are fourteen challenges in six groups. Pick any, as many as you like. Each is scored on its own, and **depth beats spread**: a challenge taken seriously is worth more than three touched lightly. Unsure which to take? Ask before you commit. Picking well is half the work.

### Summary table

| # | Group | Challenge | The problem | What you build | You hand in | How it is scored | Difficulty |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Find patterns nobody has written down | New typologies | The agent knows five documented patterns. The people attacking the bank keep inventing others | Detectors for patterns the policy does not name: purchases that share an origin weeks before the loss, cards that wake after weeks of silence, charges too small to trip any threshold, many cards paying one recipient | A detector per pattern, each with a backtest over the closed cases | Hidden cases caught, with no rise in legitimate customers acted against | Medium |
| 2 | Find patterns nobody has written down | Self-growing detective | Every new detector needs a human to notice the pattern and write it | An agent that finds an unlabelled pattern itself, writes a detector, backtests it on the 5,585 closed cases and asks a human to approve it before it joins the toolkit | The approval flow, at least one discovered detector, its backtest | Quality of what it discovers, and whether it finds a pattern you did not hand it | Hard |
| 3 | Find patterns nobody has written down | Policy text to detector | Rules and advisories arrive as prose, not code | Turn a written rule (one of R1 to R10, or a regulator advisory the organisers hand you) into a working detector, then show where it agrees and disagrees with your agent's own judgement | The detector, its backtest, and a rule-versus-agent comparison | Correctness on the hidden pack; how fast prose becomes a working detector | Medium |
| 4 | Explain and prove | Evidence to SAR | Analysts spend hours writing filings an agent could draft | A filing an analyst could send with minor edits: narrative, timeline, the evidence graph, and a citation on every sentence. Policy §3a decides whether a report is owed at all | Filings for every case where §3a requires one | Blind review (team names removed), plus attested accuracy | Medium |
| 5 | Explain and prove | Ring replay | A ring is hard to see in a table of rows | A time slider that plays a ring forming: which cards joined when, what they shared, how the loss accumulated | The replay for any ring your agent finds | How fast someone who has never seen the case understands it, with the replay versus without | Medium |
| 6 | Explain and prove | Regulator's view | Months later an examiner asks why the agent concluded what it did | An audit replay: what the agent saw at each step, which tool it called, what came back, and why it moved. Every step challengeable | The replay for any past investigation | Can an outsider reconstruct and challenge a decision in five minutes | Medium |
| 7 | Act on it | Containment planner | Knowing which cards are compromised does not stop the loss, and blocking everything harms people who did nothing | Given a ring, the smallest set of cards to block that cuts the most exposure, with the legitimate customers that action would touch named explicitly | A containment plan per ring, with who it affects | Exposure stopped, minus a penalty per legitimate customer acted against | Hard |
| 8 | Work with analysts | Analyst in the loop | The agent repeats mistakes an analyst already corrected | Accept and reject on findings, and behaviour that changes from those decisions without retraining a model | The feedback flow and a before-and-after run on the same cases | Fall in wrongly-acted-against customers after one feedback round | Medium |
| 9 | Work with analysts | Speed and autonomy | Analysts wait while an investigation runs | An alert that triggers the investigation so the case is ready before anyone opens it. Report p95 latency and cost per case | The pipeline from alert to ready case, with measured cost | p95 latency and cost per case, with accuracy held | Medium |
| 14 | Work with analysts | Case management | A case is not one decision. It opens, changes as evidence arrives, and closes, and someone has to be able to pick it up halfway | Write the case, escalate it when policy calls for it, and keep track of what is still open: what changed, what it is waiting on, what was decided and by whom | The full life of a case, from opening to close, across more than one sitting | Could an analyst take over an open case cold and know exactly where it stands | Medium |
| 10 | Defend the agent | Break the agent | The data an agent reads is written by people, and some of them are hostile | Instructions hidden in a customer message or an analyst note, signals built to mislead, activity shaped to look innocent. Then the defences. Six cases in this pack already carry hostile text; find your own too | Reproducible attacks, the defences, and new test cases | Attacks that produce a wrong verdict, before and after your defences | Hard |
| 11 | Messy and changing data | Data quality detective | Bad data looks like fraud, or hides it. A quarter of transactions have no identity record at all | Find the gaps that matter: missing device records, empty billing regions, placeholder values, cards whose history is too thin to judge. Then say which of your own investigations cannot be trusted because of them | A data-quality report, and the investigations it taints | Real problems found, and tainted investigations correctly flagged | Medium |
| 12 | Messy and changing data | Schema drift survival | Banks change their data under you and things break quietly | January arrives as new files and a replaced closed-case history. Detect what changed, explain what it breaks, re-map, and get human approval before acting on it | A run through the change, with the approval step | Detected, explained and recovered correctly, and how fast | Hard |
| 13 | Messy and changing data | Someone else's schema | Every bank stores the same ideas under different names | Work out the mapping yourself on a variant of this data with renamed and reshaped columns, handed out on the day, then investigate on it | Your mapping, and investigations run on the variant | Investigation accuracy on a schema you have never seen | Hard |

### What each challenge means, and what "attested" means for it

1. **New typologies.** Detectors for patterns the policy does not name. *Attested:* every detection lists the transaction and card ids that match the pattern.
2. **Self-growing detective.** The agent finds an unlabelled pattern, writes a detector, backtests it on the 5,585 closed cases and asks a human to approve it before it joins the toolkit. *Attested:* every proposed detector ships with its backtest: what it caught, what it missed, and which legitimate customers it would have acted against.
3. **Policy text to detector.** Turn a written rule (R1 to R10, or a regulator advisory handed out) into a working detector, then show where it agrees and disagrees with your agent's own judgement. *Attested:* the detector's backtest, and every agreement or disagreement with your agent, with ids.
4. **Evidence to SAR.** A filing an analyst could send with minor edits: narrative, timeline, the evidence graph, and a citation on every sentence. Policy §3a decides whether a report is owed at all. *Attested:* every sentence in the filing links to attested transactions.
5. **Ring replay.** A time slider that plays a ring forming: which cards joined when, what they shared, how the loss accumulated. *Attested:* every frame is built from attested transactions, not a stored picture.
6. **Regulator's view.** An audit replay: what the agent saw at each step, which tool it called, what came back, and why it moved. Every step challengeable. *Attested:* each step shows the evidence the agent actually had at that moment.
7. **Containment planner.** Given a ring, the smallest set of cards to block that cuts the most exposure, with the legitimate customers that action would touch named explicitly. *Attested:* each plan shows the exposure it cuts, with amounts, and names the customers it touches.
8. **Analyst in the loop.** Accept and reject on findings, and behaviour that changes from those decisions without retraining a model. *Attested:* when behaviour changes, record which analyst decisions caused it.
9. **Speed and autonomy.** An alert that triggers the investigation so the case is ready before anyone opens it. Report p95 latency and cost per case. *Attested:* the pre-investigation carries the same attested evidence as one run by hand.
10. **Break the agent.** Instructions hidden in a customer message or an analyst note, signals built to mislead, activity shaped to look innocent. Then the defences. Six cases in this pack already carry hostile text; find your own too. *Attested:* every attack is a reproducible test case, with the ids of the data you planted.
11. **Data quality detective.** A quarter of transactions have no identity record at all. Find the gaps that matter (missing device records, empty billing regions, placeholder values, cards whose history is too thin to judge), then say which of your own investigations cannot be trusted because of them. *Attested:* each problem lists the affected record ids and the investigations it taints.
12. **Schema drift survival.** January arrives as new files and a replaced closed-case history. Detect what changed, explain what it breaks, re-map, and get human approval before acting on it. *Attested:* the before and after shape of what changed, what broke, and the approved re-mapping.
13. **Someone else's schema.** Work out the mapping yourself on a variant of this data with renamed and reshaped columns, handed out on the day, then investigate on it. *Attested:* each mapping choice comes with the sample records that justify it.
14. **Case management.** Policy §3a says a case is the bank's internal record of an investigation. It can be opened before anything is proven, updated when new evidence arrives, and closed as fraud or as legitimate. Most of this round treats a case as a single answer; this challenge treats it as a record with a life: opened, escalated, added to, handed over, closed. Decide for yourself what should own each step. *Attested:* every state change records the evidence that caused it, when it happened, and who approved it where policy required approval.

---

## 5. Attest every claim

One rule applies across every challenge: **a claim nobody can check does not count.** A claim with no attestation is treated as wrong, not as unproven.

An attested claim carries four things:

| Part | What it is |
| --- | --- |
| what | The claim, in one sentence |
| evidence | The exact transaction, card and customer ids behind it |
| how | The query that produced it, with its parameters |
| when | A timestamp, and which data you ran it against |

The organisers re-run the query. If the result differs from the claim, the claim scores zero, so a narrative sentence with no ids behind it is worse than silence. This is the same discipline the grader already applies to `exposure_usd` and `first_suspicious_txn_id`, extended to everything your agent asserts.

---

## 6. Two policy points that separated teams last round

**R1 and R2 govern different situations.** R1 is for a case resting on one weak signal, such as a risk score alone: verify before you block. R2 is for a customer who has already denied the charge: block and open a case, with no verification step needed. Conflating them costs points either way.

**§3a is not a single threshold.** A report is required when fraud is confirmed or strongly suspected **and** any one of these holds:

- exposure over $1,000;
- a connection to a shared device profile, a region cluster or another customer's fraud;
- a coordinated or undocumented pattern.

A $23 loss that connects to other cards still needs a report. Several cases in this pack turn on exactly that.

---

## 7. What you submit

1. **Frozen code** at a commit hash you give the organisers at the freeze. Anything pushed after the freeze is ignored.
2. **Answer files for all 18 cases,** `<case_id>.json`, produced by your frozen code.
3. **One command** that runs your agent on a single case from a clean clone, with setup written down. It is used in the drills.
4. **A one-page resilience statement:** what you depend on, what leaves the bank's boundary (including every model provider and what data it sees), what your agent does when each dependency fails, and what is logged.
5. **An innovation claim:** the one idea you want judged, and the case or measurement where it changes the outcome.

---

## 8. How the round runs

| Stage | What happens |
| --- | --- |
| **Stage 1: Case pack** | Your frozen code answers the 18 hidden cases. The organisers grade the output with the published checks and their answer key |
| **Stage 2: Drills** | A judge runs live resilience drills against your agent. You do not know the faults in advance |
| **Stage 3: Demo** | 5 minutes. Show your innovation on a live case, then take questions, including one about your weakest point |

**The organisers pick the demo case, not you.** A fraud analyst chooses which of the 18 you run live, and you are told which one when your slot starts. Prepare your system, not a case.

**There is no per-case time limit.** Take the time your investigation needs. Report per-case time and tokens honestly; the organisers read them but do not cap them.

**Schedule.** The freeze, Stage 1 and the demo running order are confirmed on the day. Everything else in the brief is fixed now.

**Prizes.** ₹45,000 across the top three: ₹20,000 first, ₹15,000 second, ₹10,000 third.

### What the drills cover

The drills test categories, not scripts:

- a dependency failing mid-run;
- a model call that times out or returns garbage;
- hostile or invalid input;
- an approval attempted by the wrong role;
- the same case run twice.

Judges look for a clear error, no invented answer, no false "saved" status, and consistent results.

---

## 9. Banking guidelines

- **Do not tip off.** Nothing a customer sees, including your `evidence_requests` text, may reveal that a suspicious activity report is being considered or filed.
- **Approvals are enforced server-side.** L1 and L2 actions wait for a human whose role your backend checks. A role read from the request body is not enforcement.
- **Fail closed.** If the graph, the tool layer or the model fails, stop and report it. Do not fall back silently to other data and present the result as complete.
- **Least privilege.** The model gets no raw query access and no write access beyond the one path you define.
- **Protect data.** Redact secrets and personal data in logs and traces. Commit no credentials. Say what you send to external services.
- **Keep an audit trail.** Every tool call and decision is recorded and replayable; approvals are not editable afterwards.
- **Be honest with probabilities.** They are scored for calibration. Escalate when uncertain and exposed (R8). Use `BLOCK_ALL_CARDS` only when R10 allows it.

---

## 10. Scoring

| Criterion | Points | How it is measured |
| --- | ---: | --- |
| Innovation | 25 | Novel detection, novel use of the graph, novel agent design, novel evaluation, real-world value, 0 to 5 each. An idea scores zero unless you show a case or measurement where it changes the outcome. An ablation helps |
| Harness and critical situations | 20 | Drill results: fail-closed behaviour, authorization, data protection, audit trail, bounded behaviour, and escalation instead of guessing |
| Answer quality | 15 | Hard and policy checks, plus accuracy against the answer key. Correct uncertain answers earn full credit on ambiguous cases. Harming an innocent customer costs more than missing a fraud (see below) |
| Evidence and policy behaviour | 10 | Rule compliance, correct approval routes, and whether the final recommendation changes for a stated reason after an evidence request |
| Use of TigerGraph | 10 | Vector search in decisions, vector search fused with traversal, a graph algorithm that affects output, case write-back and read-back, restricted MCP tools, the graph as source of truth, and a live run |
| Engineering and reproducibility | 10 | Tests run and pass, no committed secrets, setup works from a clean clone, auth on approvals |
| Demo clarity and honesty | 10 | Can you explain one case end to end from the trace? Do your README numbers match what is seen live? |

### The innocent-customer penalty

A bank measures a fraud team on money stopped minus the customers it wronged getting there, and this round is scored the same way. **Nine of the 18 cases are legitimate,** so this is not a footnote: it decides results.

| On a legitimate case | Actions | Effect |
| --- | --- | --- |
| Costs you nothing | `VERIFY_WITH_CUSTOMER`, `STEP_UP_AUTH`, `MONITOR_CARD`, `CLOSE_NO_FRAUD`, `ALLOW_TRANSACTION`, `ESCALATE_TO_ANALYST` | Being unsure is free. Uncertain plus escalation is a correct answer wherever R1 and R8 call for it, not a hedge |
| Scores zero | `BLOCK_CARD`, `BLOCK_ALL_CARDS`, `FILE_REPORT` | Zero for that case, not partial credit |

A missed fraud costs you one case. A wrongly blocked customer costs you the case and tells the judges the system is not deployable.

An agent that blocks freely cannot pass this pack, however much real fraud it also finds. That is deliberate: in Round 1 the most common failure across all 215 teams was not missing fraud; it was acting against people who had done nothing wrong.

---

## 11. Run the grader yourself

It is the same grader the organisers use: Python 3, no dependencies. Each team folder holds a `cases/` directory of `<case_id>.json` files.

```bash
python grade.py --teams-dir teams --case-pack case_pack_final.csv \
                --transactions transactions_2017q1.csv --out report.json
```

Findings come in three classes:

- **hard:** required fields, valid values, internal consistency, and, with `--transactions`, that every id exists, that `exposure_usd` equals the sum of the affected amounts, and that `first_suspicious_txn_id` really is the earliest affected transaction.
- **policy:** approval routes, R1, R8, R9, R10, the case-versus-report rules in §3a and §3b, and tip-off in anything the customer would see.
- **warning:** heuristics a judge reads by hand. Not scored.

Passing these checks is necessary, not sufficient. On Round 1's 20 public cases, five of the six finalist teams passed every hard and policy check. The hidden pack, the drills and the demo decide this round.

---

## 12. How the winner is declared

- Weights and checks are fixed before scoring and do not change.
- **Any failed gate rules a team out:** disallowed data, undeclared data egress, or an unreproducible run.
- Judges score each demo before seeing the next team. The top SAR narratives are scored blind, with team names removed.
- Each team gets its own report before the announcement and may point out grader mistakes.
- The score table is published with every criterion shown.
- **Tie-breaks:** fewer failed gates, then fewer failed drills, then higher accuracy against the key.

---

## 13. Required stack (carried over from Round 1)

| Component | Requirement |
| --- | --- |
| TigerGraph | Savanna (`savanna.tgcloud.io`) or Community Edition (`dl.tigergraph.com`), used for both graph and vector storage and retrieval. On Savanna, auto-stop and auto-start must be enabled. Version 4.2+ for TigerVector |
| GSQL and graph algorithms | Traversal, pattern detection, relationship analysis and fraud investigation |
| TigerGraph MCP | `github.com/tigergraph/tigergraph-mcp`, to expose graph capabilities and data to the agent |
| GraphRAG | Ground the agent with connected evidence from the graph and with documents such as fraud policies, procedures and typologies. Pass relevant context to the LLM rather than raw data |
| User interface | Must show investigation, case progression, evidence, uncertainty, recommendations and next actions |

Actions such as messaging customers, freezing accounts, blocking cards, refunding customers, updating CRM systems or closing cases may be simulated, stubbed or represented through mock APIs.

---

## 14. Support

- TigerGraph Discord: `https://discord.com/invite/4cc7SNqRf`
- The TigerGraph WhatsApp group, for quick doubts and announcements

---

## Appendix A: The Round 1 challenge, in brief

**Goal:** build an AI agent, powered by TigerGraph, that investigates fraud, creates and progresses cases, and recommends the next best action when signals are uncertain.

The agent must:

1. **Investigate when triggered** by a fraud signal or risk score, a customer report, or a fraud analyst.
2. **Gather evidence** from the knowledge graph, transaction history, device and identity signals, account behaviour, prior fraud cases and external sources.
3. **Assess** the fraud pattern, the likely type of fraud, and the level of risk.
4. **Create and progress a case:** add evidence and findings, update status, risk and recommended actions, and keep a record of decisions and actions.
5. **Use case memory:** retrieve similar past cases, use prior outcomes and analyst decisions, find recurring patterns, entities and relationships, and update memory as cases resolve.
6. **Gather more evidence when needed** through controlled, policy-approved actions: ask the account owner to validate, request step-up authentication, or ask an analyst or approved party.
7. **Recommend or take next actions:** allow or block a transaction, block or monitor an account, warn a customer, create a case, file a report, request more evidence, escalate.
8. **Operate within policy and permissions:** the agent may recommend; only authorised actions may be executed; some need human approval.
9. **Stop** once enough evidence exists to take a defensible action.
10. **Explain** what evidence was used, why more was requested, and why the actions were chosen.

The core flow is: trigger → investigate → gather evidence → assess uncertainty → gather more evidence if needed → act → explain → update case memory.

Round 1 output: 20 cases (HHG-001…020), each with the case written to the graph, a SAR where policy required one, and the next best action with its approval route recorded before and after additional evidence.

## Appendix B: The dataset

- Derived from IEEE-CIS Fraud Detection (Vesta), re-cut as HHGOA. About 590,000 card transactions from July to December 2016, about 13,500 customers, with device and connection records for online transactions. January 2017 adds 60,196 transactions.
- **There is no fraud label.** Every transaction carries the bank model's `risk_score`. Above 0.7, most flagged transactions turn out to be legitimate, and some fraud scores near zero.
- **Closed investigations** (now 5,585) contain confirmed-fraud and cleared outcomes with the analyst's notes, pattern, affected transactions, exposure, connected cards and actions taken.
- **Five documented fraud patterns** ship with the policy. The answer enum (as used in Round 1) is `none`, `card_testing`, `card_not_present_fraud`, `card_not_present_new_device`, `out_of_region_use`, `account_takeover` and `undocumented`. Not every fraud pattern present in the data is documented.
- Column families: `card1`–`card6` (instrument), `addr1`/`addr2`, `dist1`/`dist2` (geography), `P_emaildomain`/`R_emaildomain` (email), `C1`–`C14` (counts), `D1`–`D15` (time deltas), `M1`–`M9` (match flags), `V1`–`V339` (Vesta-engineered), and identity `id_01`–`id_38`, `DeviceType` and `DeviceInfo`.
- Card ids in cases look like `C01234-K1`. There is no card column in the transactions file; Round 1 recovered card ids from the `(customer_id, card2..card6)` tuple, pinned against labelled transactions.

## Appendix C: Policy quick reference

*Summarised from the Round 1 implementation of Fraud Operations Policy v1.0. The policy file itself is authoritative; check every line against it.*

| Rule | When it applies | What it requires |
| --- | --- | --- |
| R1 | A single weak signal (for example, a risk score alone) and fraud probability below about 0.70 | Verify with the customer or step up authentication before any block |
| R2 | The customer has denied the charge | `BLOCK_CARD` and `CREATE_CASE`, with no verification step. Add a report if §3a conditions hold |
| R3 | The customer confirms the charge | `CLOSE_NO_FRAUD` |
| R4 | No customer response within 24 hours | `MONITOR_CARD`, decline pending; escalate if exposure is over $500 |
| R5 | 3+ small online authorisations within 1 hour, then a larger one | Decline and step up; block if over $100 has cleared |
| R6 | Several cards share a device, region or email within one window | Create a case, file a report, monitor connected cards |
| R7 | A disputed charge matches the card's own recurring pattern | Verify and warn; never block |
| R8 | Uncertain and exposure over $500, or evidence conflicts | `ESCALATE_TO_ANALYST` |
| R9 | Coordinated abuse that fits no known pattern | Create a case, file a report, escalate; describe the pattern in your own words |
| R10 | 2+ cards confirmed, or credentials compromised | Only then is `BLOCK_ALL_CARDS` allowed |
| §2 | Approval routes | Auto for low-risk actions; L1 (team lead) for blocks and declines up to $2,500; L2 (fraud manager) for reports and larger blocks |
| §3a | Case versus report | A case can be opened before anything is proven. A report is required when fraud is confirmed or strongly suspected and exposure > $1,000, or there is a connection to a shared device profile, region cluster or another customer's fraud, or the pattern is coordinated or undocumented |
| §6 | Stopping | Act when the decision rests on at least two independent pieces of evidence, or when no further evidence would change it |
