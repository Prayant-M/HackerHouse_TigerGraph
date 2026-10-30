# Round 1 answers vs the real outcomes

`eval/hhg_holdout.py`. The final-round closed-case file adds the 20 HHG investigations with their real outcomes (20 matched by card and date: 10 fraud, 10 cleared). Uncertain + escalate counts as correct, as the brief scores it.

| answers | scored | correct | innocent customers harmed | frauds cleared | Brier |
|---|--:|--:|--:|--:|--:|
| round1 | 20 | 17 | 1 | 2 | 0.1437 |
| current | 20 | 17 | 1 | 2 | 0.1437 |

| case | truth | Round 1 verdict | current verdict | current harmful | true pattern |
|---|---|---|---|---|---|
| HHG-001 | legit | legitimate | legitimate | False | none |
| HHG-002 | legit | legitimate | legitimate | False | none |
| HHG-003 | fraud | fraud | fraud | True | out_of_region_use |
| HHG-004 | legit | fraud | fraud | True | none |
| HHG-005 | legit | legitimate | legitimate | False | none |
| HHG-006 | fraud | fraud | fraud | True | undocumented |
| HHG-007 | fraud | legitimate | legitimate | False | out_of_region_use |
| HHG-008 | fraud | fraud | fraud | True | card_testing |
| HHG-009 | fraud | fraud | uncertain | False | card_not_present_fraud |
| HHG-010 | legit | legitimate | legitimate | False | none |
| HHG-011 | fraud | fraud | fraud | True | card_testing |
| HHG-012 | legit | legitimate | legitimate | False | none |
| HHG-013 | legit | legitimate | legitimate | False | none |
| HHG-014 | fraud | fraud | fraud | True | undocumented |
| HHG-015 | legit | legitimate | legitimate | False | none |
| HHG-016 | fraud | fraud | fraud | True | card_not_present_new_device |
| HHG-017 | legit | legitimate | legitimate | False | none |
| HHG-018 | fraud | legitimate | legitimate | False | account_takeover |
| HHG-019 | fraud | fraud | fraud | True | card_not_present_new_device |
| HHG-020 | legit | legitimate | legitimate | False | none |
