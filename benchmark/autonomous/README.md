# Autonomous monitoring — outside the benchmark

These cases are **not** part of the graded twenty. The agent raised them itself over the November–December exam period and investigated them end to end under the same policy, the same evidence ledger and the same stopping rule.

Three triggers ran. The first is the ordinary one — transactions the bank's model scored highly. The other two look for structure that per-transaction scoring cannot see at all, because the signal is a property of a burst or of a hub rather than of any single row:

| trigger | what it looks for |
|---|---|
| `risk_score` | the bank's model at or above 0.88 |
| `structuring_sweep` | online bursts parked just under a round authorisation ceiling — undocumented typology U1 |
| `device_hub_sweep` | device profiles where nearly every card that ever touched them arrived through an anonymising proxy — undocumented typology U2 |

## Results by trigger

| found_by          |   alerts |   fraud |   mean_p |   exposure |
|:------------------|---------:|--------:|---------:|-----------:|
| device_hub_sweep  |       18 |      14 |    0.705 |    2583.34 |
| risk_score        |       20 |       2 |    0.135 |    4082.92 |
| structuring_sweep |       20 |      20 |    0.949 |   31611    |

## All alerts

| case     | found_by          |     txn | verdict    | pattern                     |   p_fraud |   exposure | sar   |
|:---------|:------------------|--------:|:-----------|:----------------------------|----------:|-----------:|:------|
| AUTO-001 | structuring_sweep | 3581257 | fraud      | undocumented                |     0.949 |    1999.84 | True  |
| AUTO-002 | structuring_sweep | 3487348 | fraud      | undocumented                |     0.949 |    1935.29 | True  |
| AUTO-003 | structuring_sweep | 3476008 | fraud      | undocumented                |     0.97  |    1926.93 | True  |
| AUTO-004 | structuring_sweep | 3498092 | fraud      | undocumented                |     0.97  |    1922.43 | True  |
| AUTO-005 | structuring_sweep | 3481444 | fraud      | undocumented                |     0.947 |    1921.59 | True  |
| AUTO-006 | structuring_sweep | 3475414 | fraud      | undocumented                |     0.97  |    1911.84 | True  |
| AUTO-007 | structuring_sweep | 3509706 | fraud      | undocumented                |     0.962 |    1908.26 | True  |
| AUTO-008 | structuring_sweep | 3483895 | fraud      | undocumented                |     0.828 |    1906.11 | True  |
| AUTO-009 | structuring_sweep | 3507670 | fraud      | undocumented                |     0.97  |    1904.86 | True  |
| AUTO-010 | structuring_sweep | 3509576 | fraud      | undocumented                |     0.961 |    1884.76 | True  |
| AUTO-011 | structuring_sweep | 3511062 | fraud      | undocumented                |     0.885 |    1880.16 | True  |
| AUTO-012 | structuring_sweep | 3476664 | fraud      | undocumented                |     0.97  |    1860.43 | True  |
| AUTO-013 | structuring_sweep | 3531493 | fraud      | undocumented                |     0.97  |    1499.85 | True  |
| AUTO-014 | structuring_sweep | 3493541 | fraud      | undocumented                |     0.97  |    1499.85 | True  |
| AUTO-015 | structuring_sweep | 3518549 | fraud      | undocumented                |     0.948 |    1499.84 | True  |
| AUTO-016 | structuring_sweep | 3564258 | fraud      | undocumented                |     0.97  |     999.86 | True  |
| AUTO-017 | structuring_sweep | 3490106 | fraud      | undocumented                |     0.97  |     799.81 | True  |
| AUTO-018 | structuring_sweep | 3455821 | fraud      | undocumented                |     0.94  |     799.73 | True  |
| AUTO-019 | structuring_sweep | 3538288 | fraud      | undocumented                |     0.95  |     799.7  | True  |
| AUTO-020 | structuring_sweep | 3563264 | fraud      | undocumented                |     0.922 |     749.88 | True  |
| AUTO-021 | device_hub_sweep  | 3512487 | fraud      | undocumented                |     0.97  |      40.41 | True  |
| AUTO-022 | device_hub_sweep  | 3512532 | fraud      | undocumented                |     0.97  |     204.89 | True  |
| AUTO-023 | device_hub_sweep  | 3512563 | fraud      | undocumented                |     0.97  |     209.66 | True  |
| AUTO-024 | device_hub_sweep  | 3467210 | fraud      | card_not_present_new_device |     0.928 |     400.08 | False |
| AUTO-025 | device_hub_sweep  | 3472599 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-026 | device_hub_sweep  | 3472608 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-027 | device_hub_sweep  | 3493920 | fraud      | card_not_present_new_device |     0.786 |      99.97 | False |
| AUTO-028 | device_hub_sweep  | 3493926 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-029 | device_hub_sweep  | 3496768 | fraud      | card_not_present_new_device |     0.803 |     100.08 | True  |
| AUTO-030 | device_hub_sweep  | 3510432 | fraud      | card_not_present_new_device |     0.951 |      31.74 | True  |
| AUTO-031 | device_hub_sweep  | 3512377 | fraud      | undocumented                |     0.967 |     100.91 | True  |
| AUTO-032 | device_hub_sweep  | 3512388 | fraud      | undocumented                |     0.967 |     100.91 | True  |
| AUTO-033 | device_hub_sweep  | 3462618 | fraud      | card_not_present_new_device |     0.957 |      99.93 | False |
| AUTO-034 | device_hub_sweep  | 3467993 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-035 | device_hub_sweep  | 3527383 | fraud      | account_takeover            |     0.746 |     144.62 | False |
| AUTO-036 | device_hub_sweep  | 3514989 | fraud      | card_not_present_new_device |     0.933 |     350.02 | False |
| AUTO-037 | device_hub_sweep  | 3523870 | fraud      | card_not_present_new_device |     0.719 |     350.07 | False |
| AUTO-038 | device_hub_sweep  | 3526664 | fraud      | card_not_present_new_device |     0.94  |     350.05 | False |
| AUTO-039 | risk_score        | 3549837 | legitimate | none                        |     0.08  |       0    | False |
| AUTO-040 | risk_score        | 3469573 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-041 | risk_score        | 3436706 | fraud      | out_of_region_use           |     0.863 |    1772.03 | True  |
| AUTO-042 | risk_score        | 3471965 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-043 | risk_score        | 3542004 | legitimate | none                        |     0.06  |       0    | False |
| AUTO-044 | risk_score        | 3467310 | legitimate | none                        |     0.094 |       0    | False |
| AUTO-045 | risk_score        | 3435614 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-046 | risk_score        | 3500526 | legitimate | none                        |     0.094 |       0    | False |
| AUTO-047 | risk_score        | 3524594 | legitimate | none                        |     0.133 |       0    | False |
| AUTO-048 | risk_score        | 3446975 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-049 | risk_score        | 3497655 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-050 | risk_score        | 3516131 | legitimate | none                        |     0.039 |       0    | False |
| AUTO-051 | risk_score        | 3511767 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-052 | risk_score        | 3515392 | legitimate | none                        |     0.103 |       0    | False |
| AUTO-053 | risk_score        | 3581276 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-054 | risk_score        | 3424985 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-055 | risk_score        | 3418313 | fraud      | account_takeover            |     0.854 |    2310.89 | True  |
| AUTO-056 | risk_score        | 3526069 | legitimate | none                        |     0.078 |       0    | False |
| AUTO-057 | risk_score        | 3589881 | legitimate | none                        |     0.122 |       0    | False |
| AUTO-058 | risk_score        | 3528137 | legitimate | none                        |     0.02  |       0    | False |
