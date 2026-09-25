# Backtest — October 2016 holdout

Replayed **400 alerts** through the full agent, twice, under each case's own `as_of`. Calibration tables were fitted on July-September only; every graph read, vector recall and proximity walk is bounded by the case's own timestamp.

## Two arms, because one number would mislead

In this history the trigger type is perfectly correlated with the outcome: every confirmed case arrived as a customer report, every cleared one as a risk-score alert. Reporting precision on the realistic trigger therefore measures the label, not the agent. So the holdout is replayed twice.

| | **as seen** — real trigger | **graph only** — trigger stripped |
|---|---:|---:|
| precision | 0.891 | 0.637 |
| recall | 0.967 | 0.209 |
| F1 | 0.927 | 0.315 |
| true pos / false pos | 236 / 29 | 51 / 29 |
| true neg / false neg | 127 / 8 | 127 / 193 |
| **AUC** (prior-invariant ranking) | **0.921** | **0.52** |
| Brier score | 0.0825 | 0.4951 |
| expected calibration error | 0.036 | 0.4966 |
| uncertain verdicts | 0 | 0 |
| evidence requested | 28.7% | 50.5% |
| recommendation changed after evidence | 28.7% | 50.5% |

**Read the gap, not the left column.** The `as seen` arm is the fair measure of the deployed system — it is how the bank's alerts actually arrive, and the trigger is real information. The `graph only` arm is the honest measure of the graph evidence, and the distance between them is exactly how much of this agent's fraud/not-fraud discrimination comes from *how the alert arrived* rather than from anything in the graph. In this dataset that is most of it, and the reason is in `eval/reports/calibration.md`: fraud entered the closed-case file because cardholders rang up, not because it looked anomalous.

## What the graph evidence *does* decide

Pattern identification is independent of the trigger — knowing a case is fraud says nothing about which typology it is — so this is a clean measure of the graph work.

| metric | as seen | graph only |
|---|---:|---:|
| **pattern accuracy, both sides agree it is fraud** | **0.508** (n=236) | **0.471** (n=51) |
| pattern accuracy over all confirmed fraud | 0.492 | 0.098 |
| affected-transaction overlap (Jaccard) | 0.587 | 0.141 |
| SAR decision agreement with the bank's own filing | 0.9 | 0.907 |
| median exposure error on fraud cases | 0.309 | — |

Six pattern classes; always guessing the majority class would score about 0.26. The first row is the one to read — the second is confounded, because an agent that calls a case legitimate reports pattern `none`, so it measures the verdict as much as the typology.

Note the AUC line above as well. Brier and accuracy both punish the `graph_only` arm for a prior that does not match this population — the holdout is 61% fraud because it is built from a case file, while the agent's prior is calibrated to an alert population that is roughly half legitimate. AUC is invariant to that shift.

## Calibration — `as seen` arm

**Brier 0.0825** · **ECE 0.036**

| predicted band | n | mean predicted | observed fraud rate |
|---|---:|---:|---:|
| 0.0–0.1 | 124 | 0.037 | 0.065 |
| 0.1–0.2 | 11 | 0.136 | 0.000 |
| 0.7–0.8 | 23 | 0.759 | 0.739 |
| 0.8–0.9 | 45 | 0.869 | 0.889 |
| 0.9–1.0 | 197 | 0.950 | 0.909 |

## Why investigations stopped (`as seen`)

| stop reason | n |
|---|---:|
| A verification response settled the question outright (polic | 115 |
| Fraud probability 0.97 is at or above the 0.85 ceiling in po | 75 |
| Fraud probability 0.94 is at or above the 0.85 ceiling in po | 28 |
| Fraud probability 0.08 is at or below the 0.15 floor in poli | 18 |
| Fraud probability 0.95 is at or above the 0.85 ceiling in po | 15 |
| Fraud probability 0.88 is at or above the 0.85 ceiling in po | 14 |
| Fraud probability 0.90 is at or above the 0.85 ceiling in po | 13 |
| Fraud probability 0.91 is at or above the 0.85 ceiling in po | 12 |
| Fraud probability 0.89 is at or above the 0.85 ceiling in po | 11 |
| Fraud probability 0.05 is at or below the 0.15 floor in poli | 8 |
| Fraud probability 0.77 clears the 0.70 threshold for the act | 8 |
| Fraud probability 0.96 is at or above the 0.85 ceiling in po | 7 |
| Fraud probability 0.07 is at or below the 0.15 floor in poli | 7 |
| Fraud probability 0.06 is at or below the 0.15 floor in poli | 6 |
| Fraud probability 0.93 is at or above the 0.85 ceiling in po | 6 |
| Fraud probability 0.15 is at or below the 0.15 floor in poli | 5 |
| Fraud probability 0.04 is at or below the 0.15 floor in poli | 5 |
| Fraud probability 0.86 is at or above the 0.85 ceiling in po | 4 |
| Fraud probability 0.84 clears the 0.70 threshold for the act | 3 |
| Fraud probability 0.83 clears the 0.70 threshold for the act | 3 |
| Fraud probability 0.79 clears the 0.70 threshold for the act | 3 |
| Fraud probability 0.92 is at or above the 0.85 ceiling in po | 3 |
| Fraud probability 0.85 is at or above the 0.85 ceiling in po | 2 |
| Fraud probability 0.02 is at or below the 0.15 floor in poli | 2 |
| Fraud probability 0.76 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.03 is at or below the 0.15 floor in poli | 2 |
| Fraud probability 0.73 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.81 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.71 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.74 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.78 clears the 0.70 threshold for the act | 2 |
| Fraud probability 0.14 is at or below the 0.15 floor in poli | 2 |
| Fraud probability 0.11 is at or below the 0.15 floor in poli | 2 |
| Fraud probability 0.87 is at or above the 0.85 ceiling in po | 2 |
| Fraud probability 0.09 is at or below the 0.15 floor in poli | 1 |
| Fraud probability 0.72 clears the 0.70 threshold for the act | 1 |
| Fraud probability 0.13 is at or below the 0.15 floor in poli | 1 |
| Fraud probability 0.82 clears the 0.70 threshold for the act | 1 |
| Fraud probability 0.85 clears the 0.70 threshold for the act | 1 |
| Fraud probability 0.12 is at or below the 0.15 floor in poli | 1 |
| Fraud probability 0.80 clears the 0.70 threshold for the act | 1 |

## Action mix (`as seen`)

| action | times recommended |
|---|---:|
| `CREATE_CASE` | 340 |
| `BLOCK_CARD` | 265 |
| `CLOSE_NO_FRAUD` | 135 |
| `FILE_REPORT` | 39 |
| `MONITOR_CARD` | 11 |
| `ESCALATE_TO_ANALYST` | 4 |
| `DECLINE_TRANSACTION` | 2 |
| `STEP_UP_AUTH` | 2 |
| `WARN_CUSTOMER` | 1 |

## Pattern confusion (rows = truth, columns = agent)

| truth_pattern               |   account_takeover |   card_not_present_fraud |   card_not_present_new_device |   card_testing |   none |   out_of_region_use |
|:----------------------------|-------------------:|-------------------------:|------------------------------:|---------------:|-------:|--------------------:|
| account_takeover            |                 33 |                        3 |                             2 |              0 |      3 |                  22 |
| card_not_present_fraud      |                 16 |                        7 |                            37 |              1 |      1 |                   0 |
| card_not_present_new_device |                  6 |                        2 |                            46 |              1 |      0 |                   0 |
| card_testing                |                  1 |                        0 |                             1 |              0 |      0 |                   0 |
| out_of_region_use           |                 24 |                        0 |                             0 |              0 |      4 |                  34 |
