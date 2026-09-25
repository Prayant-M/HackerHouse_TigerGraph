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
| device_hub_sweep  |       27 |      24 |    0.825 |    3396.39 |
| risk_score        |       30 |       6 |    0.224 |   16520.3  |
| structuring_sweep |       30 |      30 |    0.945 |   38145.7  |

## All alerts

| case     | found_by          |     txn | verdict    | pattern                     |   p_fraud |   exposure | sar   |
|:---------|:------------------|--------:|:-----------|:----------------------------|----------:|-----------:|:------|
| AUTO-001 | structuring_sweep | 3581257 | fraud      | undocumented                |     0.97  |    1999.84 | True  |
| AUTO-002 | structuring_sweep | 3487348 | fraud      | undocumented                |     0.907 |    1935.29 | True  |
| AUTO-003 | structuring_sweep | 3476008 | fraud      | undocumented                |     0.97  |    1926.93 | True  |
| AUTO-004 | structuring_sweep | 3498092 | fraud      | undocumented                |     0.97  |    1922.43 | True  |
| AUTO-005 | structuring_sweep | 3481444 | fraud      | undocumented                |     0.866 |    1921.59 | True  |
| AUTO-006 | structuring_sweep | 3475414 | fraud      | undocumented                |     0.924 |    1911.84 | True  |
| AUTO-007 | structuring_sweep | 3509706 | fraud      | undocumented                |     0.836 |    1908.26 | True  |
| AUTO-008 | structuring_sweep | 3483895 | fraud      | undocumented                |     0.755 |    1906.11 | True  |
| AUTO-009 | structuring_sweep | 3507670 | fraud      | undocumented                |     0.965 |    1904.86 | True  |
| AUTO-010 | structuring_sweep | 3509576 | fraud      | undocumented                |     0.966 |    1884.76 | True  |
| AUTO-011 | structuring_sweep | 3511062 | fraud      | undocumented                |     0.97  |    1880.16 | True  |
| AUTO-012 | structuring_sweep | 3476664 | fraud      | undocumented                |     0.97  |    1860.43 | True  |
| AUTO-013 | structuring_sweep | 3531493 | fraud      | undocumented                |     0.959 |    1499.85 | True  |
| AUTO-014 | structuring_sweep | 3493541 | fraud      | undocumented                |     0.97  |    1499.85 | True  |
| AUTO-015 | structuring_sweep | 3518549 | fraud      | undocumented                |     0.944 |    1499.84 | True  |
| AUTO-016 | structuring_sweep | 3564258 | fraud      | undocumented                |     0.97  |     999.86 | True  |
| AUTO-017 | structuring_sweep | 3490106 | fraud      | undocumented                |     0.97  |     799.81 | True  |
| AUTO-018 | structuring_sweep | 3455821 | fraud      | undocumented                |     0.97  |     799.73 | True  |
| AUTO-019 | structuring_sweep | 3538288 | fraud      | undocumented                |     0.97  |     799.7  | True  |
| AUTO-020 | structuring_sweep | 3563264 | fraud      | undocumented                |     0.958 |     749.88 | True  |
| AUTO-021 | structuring_sweep | 3495090 | fraud      | undocumented                |     0.97  |     749.83 | True  |
| AUTO-022 | structuring_sweep | 3554912 | fraud      | undocumented                |     0.97  |     749.82 | True  |
| AUTO-023 | structuring_sweep | 3443338 | fraud      | undocumented                |     0.97  |     736.62 | True  |
| AUTO-024 | structuring_sweep | 3556907 | fraud      | undocumented                |     0.912 |     699.63 | True  |
| AUTO-025 | structuring_sweep | 3507362 | fraud      | undocumented                |     0.97  |     599.84 | True  |
| AUTO-026 | structuring_sweep | 3574660 | fraud      | undocumented                |     0.97  |     599.84 | True  |
| AUTO-027 | structuring_sweep | 3468799 | fraud      | undocumented                |     0.97  |     599.83 | True  |
| AUTO-028 | structuring_sweep | 3538893 | fraud      | undocumented                |     0.97  |     599.8  | True  |
| AUTO-029 | structuring_sweep | 3473726 | fraud      | undocumented                |     0.907 |     599.79 | True  |
| AUTO-030 | structuring_sweep | 3464923 | fraud      | undocumented                |     0.964 |     599.63 | True  |
| AUTO-031 | device_hub_sweep  | 3509581 | fraud      | undocumented                |     0.97  |      83.19 | True  |
| AUTO-032 | device_hub_sweep  | 3510657 | fraud      | undocumented                |     0.97  |     144.85 | True  |
| AUTO-033 | device_hub_sweep  | 3512487 | fraud      | undocumented                |     0.97  |      40.41 | True  |
| AUTO-034 | device_hub_sweep  | 3512532 | fraud      | undocumented                |     0.97  |     204.89 | True  |
| AUTO-035 | device_hub_sweep  | 3512563 | fraud      | undocumented                |     0.97  |     209.66 | True  |
| AUTO-036 | device_hub_sweep  | 3435957 | fraud      | card_not_present_new_device |     0.927 |      25.04 | False |
| AUTO-037 | device_hub_sweep  | 3441930 | fraud      | card_not_present_new_device |     0.812 |      19.91 | False |
| AUTO-038 | device_hub_sweep  | 3467210 | fraud      | card_not_present_new_device |     0.94  |     400.08 | False |
| AUTO-039 | device_hub_sweep  | 3472599 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-040 | device_hub_sweep  | 3472608 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-041 | device_hub_sweep  | 3491098 | fraud      | card_not_present_new_device |     0.943 |      99.94 | False |
| AUTO-042 | device_hub_sweep  | 3493920 | fraud      | card_not_present_new_device |     0.97  |      99.97 | False |
| AUTO-043 | device_hub_sweep  | 3493926 | fraud      | card_not_present_new_device |     0.97  |      99.93 | False |
| AUTO-044 | device_hub_sweep  | 3496768 | fraud      | card_not_present_new_device |     0.97  |     100.08 | True  |
| AUTO-045 | device_hub_sweep  | 3503953 | fraud      | card_not_present_new_device |     0.97  |      31.75 | True  |
| AUTO-046 | device_hub_sweep  | 3503990 | fraud      | card_not_present_new_device |     0.97  |     158.6  | True  |
| AUTO-047 | device_hub_sweep  | 3510432 | fraud      | card_not_present_new_device |     0.97  |      31.74 | True  |
| AUTO-048 | device_hub_sweep  | 3512377 | fraud      | undocumented                |     0.97  |     100.91 | True  |
| AUTO-049 | device_hub_sweep  | 3512388 | fraud      | undocumented                |     0.97  |     100.91 | True  |
| AUTO-050 | device_hub_sweep  | 3459903 | legitimate | none                        |     0.048 |       0    | False |
| AUTO-051 | device_hub_sweep  | 3462542 | fraud      | card_not_present_new_device |     0.812 |      99.93 | False |
| AUTO-052 | device_hub_sweep  | 3462618 | fraud      | card_not_present_new_device |     0.817 |      99.93 | False |
| AUTO-053 | device_hub_sweep  | 3467993 | fraud      | card_not_present_new_device |     0.97  |      49.91 | False |
| AUTO-054 | device_hub_sweep  | 3527383 | fraud      | account_takeover            |     0.758 |     144.62 | False |
| AUTO-055 | device_hub_sweep  | 3514989 | fraud      | card_not_present_new_device |     0.75  |     350.02 | False |
| AUTO-056 | device_hub_sweep  | 3523870 | fraud      | card_not_present_new_device |     0.878 |     350.07 | False |
| AUTO-057 | device_hub_sweep  | 3526664 | fraud      | card_not_present_new_device |     0.97  |     350.05 | False |
| AUTO-058 | risk_score        | 3549837 | legitimate | none                        |     0.053 |       0    | False |
| AUTO-059 | risk_score        | 3469573 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-060 | risk_score        | 3436706 | fraud      | out_of_region_use           |     0.876 |    1772.03 | True  |
| AUTO-061 | risk_score        | 3471965 | fraud      | out_of_region_use           |     0.921 |     773.96 | False |
| AUTO-062 | risk_score        | 3542004 | legitimate | none                        |     0.057 |       0    | False |
| AUTO-063 | risk_score        | 3467310 | legitimate | none                        |     0.084 |       0    | False |
| AUTO-064 | risk_score        | 3435614 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-065 | risk_score        | 3500526 | legitimate | none                        |     0.084 |       0    | False |
| AUTO-066 | risk_score        | 3524594 | legitimate | none                        |     0.127 |       0    | False |
| AUTO-067 | risk_score        | 3446975 | fraud      | out_of_region_use           |     0.921 |    1331.06 | True  |
| AUTO-068 | risk_score        | 3497655 | fraud      | card_not_present_new_device |     0.939 |     149.97 | False |
| AUTO-069 | risk_score        | 3516131 | legitimate | none                        |     0.037 |       0    | False |
| AUTO-070 | risk_score        | 3511767 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-071 | risk_score        | 3515392 | legitimate | none                        |     0.067 |       0    | False |
| AUTO-072 | risk_score        | 3581276 | fraud      | out_of_region_use           |     0.921 |   10182.4  | True  |
| AUTO-073 | risk_score        | 3424985 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-074 | risk_score        | 3418313 | fraud      | account_takeover            |     0.9   |    2310.89 | True  |
| AUTO-075 | risk_score        | 3526069 | legitimate | none                        |     0.084 |       0    | False |
| AUTO-076 | risk_score        | 3589881 | legitimate | none                        |     0.077 |       0    | False |
| AUTO-077 | risk_score        | 3528137 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-078 | risk_score        | 3460220 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-079 | risk_score        | 3434696 | legitimate | none                        |     0.084 |       0    | False |
| AUTO-080 | risk_score        | 3475913 | legitimate | none                        |     0.064 |       0    | False |
| AUTO-081 | risk_score        | 3581530 | legitimate | none                        |     0.084 |       0    | False |
| AUTO-082 | risk_score        | 3500355 | legitimate | none                        |     0.044 |       0    | False |
| AUTO-083 | risk_score        | 3454257 | legitimate | none                        |     0.098 |       0    | False |
| AUTO-084 | risk_score        | 3457197 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-085 | risk_score        | 3561840 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-086 | risk_score        | 3565983 | legitimate | none                        |     0.02  |       0    | False |
| AUTO-087 | risk_score        | 3428279 | legitimate | none                        |     0.02  |       0    | False |
