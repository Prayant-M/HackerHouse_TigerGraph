# Calibration — measured likelihood ratios

Replayed **7,123 alerts** through the same signal extractor the agent uses, each under its own `as_of`. Trained on 5,108 alerts before 2016-10-01; the damping exponent was fitted on the 2,015 held out after it.

## How the population was built, and why it is not the closed-case file

Calibrating directly on `closed_cases_history.csv` inverts every signal, and the cause is selection rather than modelling.

Every **cleared** case in that history got there by scoring high on the bank's model — a travel trip, a new phone, an unusual but genuine purchase. Every **confirmed** case got there because a cardholder rang up, and those are frequently small and unremarkable. So inside that file, *looks anomalous* predicts **cleared**, and an agent calibrated on it learns to treat ordinariness as incriminating. Measured that way, `known_device_and_region` came out at LR 3.3 toward fraud.

Two corrections, both visible in the strata below:

1. **Untouched negatives.** Ordinary transactions from the same four months that no investigation ever touched. Months 1-4 were fully worked by the bank's analysts, so an untouched transaction there is a usable negative.
2. **Matched controls.** Each confirmed-fraud case paired with another transaction **on the same card**, which removes the card-tenure confound — fraud cases sit disproportionately on long-lived busy cards, so "the device and region are already established" otherwise correlates with fraud through a variable that has nothing to do with fraud.

Two signals are excluded from the learned tables as **selection variables**: `customer_disputed` (perfectly confounded with outcome in the history) and `risk_score_high` (the variable that decided which transactions became alerts). Both enter through the trigger-conditioned prior instead.

Alerts opened before 2016-07-20 are skipped: the dataset opens on 2016-07-02, so the first fortnight has no established baseline to be anomalous against.

## Held-out performance

| metric | value |
|---|---|
| damping exponent (fitted) | 0.85 |
| accuracy | 0.5667 |
| Brier score | 0.2852 |
| expected calibration error | 0.2042 |

The damping exponent is the naive-Bayes independence correction. These signals are not independent — a structuring burst also registers as a velocity burst and as an online burst — so an undamped product compounds into posteriors of 1.00 that no evidence set in this dataset earns. It is fitted on the temporal holdout, not tuned by eye, and it applies to the structural likelihood ratios as well.

## What this history can and cannot teach

Worth stating plainly, because the numbers below are weaker than they would be if this were hidden: **the closed-case history cannot teach P(fraud | graph signals).** Every confirmed case in it was found by a cardholder ringing up, and every cleared case was found by the bank's model scoring a transaction highly. Fraud did not enter that file because it looked anomalous, so with the trigger removed the graph signals separate fraud from ordinary activity on the same card barely better than chance.

That is a finding about the data, not a failure of the extractor, and fabricating a confident likelihood-ratio table on top of it would be worse than useless. What the history *does* teach, and what the agent therefore uses:

1. **P(signal | pattern) among confirmed frauds** — which typology this is, given that it is fraud. That table discriminates strongly and is the second one below.
2. **The two undocumented typology signatures** — near-deterministic, carried by hard matchers rather than by a smoothed estimate.
3. **Base rates by trigger** — how the alert arrived is the single most informative variable available, and it enters as a prior rather than as evidence.

## Measured likelihood ratios

`LR fired` is P(signal | confirmed fraud) / P(signal | not fraud) across the whole alert population. Above 1 the signal argues for fraud; below 1 it argues against. Most sit near 1 for the reason above.

| signal | P(s\|fraud) | P(s\|not fraud) | LR fired | LR absent | n fraud | n not fraud |
|---|---:|---:|---:|---:|---:|---:|
| `recurring_charge` | 0.001 | 0.000 | **3.15** | 1.00 | 3 | 0 |
| `behavioural_fraud_neighbourhood` | 0.666 | 0.311 | **2.14** | 0.48 | 1906 | 699 |
| `device_shared_across_cards` | 0.004 | 0.002 | **1.97** | 1.00 | 9 | 3 |
| `device_proxy_hub` | 0.004 | 0.002 | **1.57** | 1.00 | 9 | 4 |
| `shared_origin_ring` | 0.006 | 0.004 | **1.57** | 1.00 | 17 | 8 |
| `matches_cleared_alert_template` | 0.554 | 0.380 | **1.46** | 0.72 | 1586 | 855 |
| `known_device_and_region` | 0.464 | 0.348 | **1.33** | 0.82 | 1327 | 781 |
| `fraud_proximity` | 0.862 | 0.668 | **1.29** | 0.42 | 2465 | 1502 |
| `online_burst_2_to_4` | 0.249 | 0.214 | **1.17** | 0.95 | 713 | 481 |
| `amount_typical` | 0.434 | 0.383 | **1.13** | 0.92 | 1240 | 860 |
| `match_flag_anomaly` | 0.185 | 0.188 | **0.98** | 1.00 | 528 | 423 |
| `mixed_channel_shift` | 0.091 | 0.102 | **0.90** | 1.01 | 261 | 228 |
| `device_new_on_account` | 0.447 | 0.548 | **0.82** | 1.22 | 1277 | 1231 |
| `card_testing_sequence` | 0.002 | 0.003 | **0.79** | 1.00 | 6 | 6 |
| `thin_history` | 0.143 | 0.192 | **0.74** | 1.06 | 407 | 430 |
| `amount_anomalous` | 0.085 | 0.119 | **0.71** | 1.04 | 241 | 267 |
| `sustained_regional_stay` | 0.002 | 0.004 | **0.69** | 1.00 | 6 | 7 |
| `velocity_burst` | 0.058 | 0.087 | **0.67** | 1.03 | 166 | 194 |
| `anonymising_proxy` | 0.010 | 0.018 | **0.56** | 1.01 | 28 | 40 |
| `out_of_region_card_present` | 0.017 | 0.031 | **0.54** | 1.01 | 47 | 69 |
| `home_activity_continues` | 0.023 | 0.048 | **0.47** | 1.03 | 64 | 107 |
| `region_unseen` | 0.058 | 0.126 | **0.46** | 1.08 | 165 | 282 |
| `amount_extreme` | 0.030 | 0.082 | **0.36** | 1.06 | 85 | 184 |
| `threshold_structuring` | 0.007 | 0.021 | **0.34** | 1.01 | 20 | 47 |
| `email_mismatch` | 0.056 | 0.176 | **0.32** | 1.15 | 158 | 395 |

## Class-conditional probabilities — where the signal actually is

What the agent actually uses: P(signal | pattern) for each of the seven hypotheses, Laplace smoothed. This is what lets the posterior discriminate *between typologies* rather than only between fraud and not-fraud.

|                                 |   none |   card_testing |   card_not_present_fraud |   card_not_present_new_device |   out_of_region_use |   account_takeover |   undocumented |
|:--------------------------------|-------:|---------------:|-------------------------:|------------------------------:|--------------------:|-------------------:|---------------:|
| amount_anomalous                |  0.133 |          0.067 |                    0.068 |                         0.074 |               0.128 |              0.115 |          0.636 |
| amount_extreme                  |  0.093 |          0.067 |                    0.019 |                         0.016 |               0.07  |              0.052 |          0.545 |
| thin_history                    |  0.172 |          0.067 |                    0.183 |                         0.146 |               0.033 |              0.122 |          0.091 |
| device_new_on_account           |  0.503 |          0.333 |                    0.667 |                         0.853 |               0.001 |              0.068 |          0.727 |
| device_shared_across_cards      |  0.001 |          0.067 |                    0.004 |                         0.001 |               0.001 |              0.002 |          0.455 |
| anonymising_proxy               |  0.018 |          0.067 |                    0.015 |                         0.015 |               0.001 |              0.004 |          0.455 |
| region_unseen                   |  0.117 |          0.067 |                    0.072 |                         0.073 |               0.098 |              0.009 |          0.091 |
| out_of_region_card_present      |  0.032 |          0.067 |                    0.001 |                         0.001 |               0.098 |              0.005 |          0.091 |
| home_activity_continues         |  0.04  |          0.067 |                    0.025 |                         0.032 |               0.038 |              0.004 |          0.091 |
| sustained_regional_stay         |  0.003 |          0.067 |                    0.002 |                         0.005 |               0.004 |              0.001 |          0.091 |
| velocity_burst                  |  0.086 |          0.067 |                    0.057 |                         0.075 |               0.046 |              0.076 |          0.364 |
| online_burst_2_to_4             |  0.196 |          0.2   |                    0.431 |                         0.431 |               0.001 |              0.043 |          0.636 |
| card_testing_sequence           |  0.005 |          0.133 |                    0.006 |                         0.004 |               0.001 |              0.001 |          0.091 |
| threshold_structuring           |  0.018 |          0.067 |                    0.006 |                         0.01  |               0.002 |              0.006 |          0.545 |
| mixed_channel_shift             |  0.086 |          0.067 |                    0.066 |                         0.097 |               0.085 |              0.075 |          0.273 |
| device_proxy_hub                |  0.002 |          0.067 |                    0.003 |                         0.001 |               0.001 |              0.003 |          0.455 |
| match_flag_anomaly              |  0.242 |          0.067 |                    0.001 |                         0.001 |               0.556 |              0.469 |          0.091 |
| email_mismatch                  |  0.154 |          0.067 |                    0.083 |                         0.107 |               0.001 |              0.015 |          0.182 |
| recurring_charge                |  0.001 |          0.067 |                    0.001 |                         0.001 |               0.007 |              0.004 |          0.091 |
| amount_typical                  |  0.388 |          0.667 |                    0.401 |                         0.441 |               0.512 |              0.439 |          0.273 |
| known_device_and_region         |  0.383 |          0.667 |                    0.292 |                         0.139 |               0.861 |              0.749 |          0.273 |
| shared_origin_ring              |  0.003 |          0.067 |                    0.002 |                         0.005 |               0.005 |              0.004 |          0.545 |
| fraud_proximity                 |  0.711 |          0.933 |                    0.932 |                         0.925 |               0.829 |              0.774 |          0.636 |
| behavioural_fraud_neighbourhood |  0.23  |          0.6   |                    0.539 |                         0.377 |               0.43  |              0.49  |          0.455 |
| matches_cleared_alert_template  |  0.396 |          0.867 |                    0.518 |                         0.539 |               0.702 |              0.591 |          0.091 |

Read the rows that matter: `device_new_on_account` is 0.85 under card-not-present-from-a-new-device and 0.001 under out-of-region use; `match_flag_anomaly` is 0.56 under out-of-region and 0.001 under card-not-present; `online_burst_2_to_4` is 0.43 under both card-not-present typologies and 0.001 under out-of-region. That is the discrimination the posterior runs on.

## Operating priors

The closed-case file is 84% confirmed fraud because it *is* a case file, not a sample of alerts, so its base rate cannot be used directly. The prior is conditioned on how the alert arrived, with P(legitimate) taken from the dataset's own guidance ("above 0.7, most flagged transactions turn out to be legitimate") and the fraud mass split by the measured pattern mix.

| trigger | none | card_testing | card_not_present_fraud | card_not_present_new_device | out_of_region_use | account_takeover | undocumented |
|---|---|---|---|---|---|---|---|
| `risk_score` | 0.620 | 0.001 | 0.119 | 0.096 | 0.067 | 0.095 | 0.001 |
| `customer_report` | 0.200 | 0.003 | 0.250 | 0.203 | 0.142 | 0.200 | 0.003 |
| `analyst_request` | 0.350 | 0.002 | 0.203 | 0.165 | 0.115 | 0.162 | 0.002 |

## Structural overrides

Nine of the 5,565 closed cases are marked `undocumented` — confirmed fraud the bank's own analysts could not categorise. Five share one signature and four share another. That support is far too thin for a smoothed table to express how *specific* those signatures are, so both are carried by hard matchers with hand-set likelihood ratios in `core/evidence_ledger.py::STRUCTURAL_LR`, damped by the same fitted exponent as everything else. The seed cases are named in the code and in every answer file that matches them.

| typology | seed cases | signature |
|---|---|---|
| sub-threshold authorisation structuring | CC-3748, CC-3841, CC-3907, CC-4086, CC-4124 | 4 online purchases in ~40 minutes, each just under a $500 ceiling, ~$1,900 total |
| shared-device ring behind an anonymising proxy | CC-2649, CC-2971, CC-2985, CC-3035 | one device profile across unrelated cardholders in a month, anonymous-proxy ratio 1.00 |

