# Answer audit

38 answer files in `cases/`, **0 issue(s)**. Checks: data integrity, §2 routing, §3a case/SAR, §4 exposure, R1, R2, R3, R7, §6 stopping, graph read-back. There is no answer key; this proves consistency, not correctness.

Alert details came from the case pack for 18 file(s) and from the trigger saved in the answer file for 20.

| case | trigger | verdict | p | pattern | exposure | SAR | final actions | audit |
|---|---|---|---:|---|---:|---|---|---|
| HHF-001 | analyst_request | fraud | 0.91 | card_not_present_new_device | $1,338.74 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT | ✅ |
| HHF-002 | analyst_request | fraud | 0.92 | card_not_present_new_device | $2,166.71 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT | ✅ |
| HHF-003 | customer_report | fraud | 0.82 | out_of_region_use | $1,800.00 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT | ✅ |
| HHF-004 | customer_report | fraud | 0.89 | account_takeover | $2.90 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHF-005 | customer_report | fraud | 0.94 | out_of_region_use | $143.39 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHF-006 | analyst_request | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-007 | customer_report | fraud | 0.97 | card_testing | $246.38 | no | DECLINE_TRANSACTION → BLOCK_CARD → CREATE_CASE | ✅ |
| HHF-008 | risk_score | legitimate | 0.02 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHF-009 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-010 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-011 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-012 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-013 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-014 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-015 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHF-016 | risk_score | uncertain | 0.75 | out_of_region_use | $3,008.76 | no | VERIFY_WITH_CUSTOMER → CREATE_CASE → ESCALATE_TO_ANALYST | ✅ |
| HHF-017 | risk_score | fraud | 0.96 | card_not_present_new_device | $43.92 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHF-018 | risk_score | legitimate | 0.07 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-001 | risk_score | legitimate | 0.08 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-002 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHG-003 | customer_report | fraud | 0.97 | out_of_region_use | $224.93 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-004 | customer_report | fraud | 0.93 | card_not_present_new_device | $128.33 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-005 | risk_score | legitimate | 0.03 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-006 | customer_report | fraud | 0.97 | undocumented | $1,906.07 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT → ESCALATE_TO_ANALYST | ✅ |
| HHG-007 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHG-008 | customer_report | fraud | 0.88 | account_takeover | $261.15 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-009 | customer_report | uncertain | 0.79 | account_takeover | $30.02 | no | VERIFY_WITH_CUSTOMER → CREATE_CASE → ESCALATE_TO_ANALYST | ✅ |
| HHG-010 | risk_score | legitimate | 0.06 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-011 | customer_report | fraud | 0.97 | card_not_present_new_device | $131.30 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-012 | risk_score | legitimate | 0.05 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-013 | risk_score | legitimate | 0.07 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-014 | analyst_request | fraud | 0.97 | undocumented | $74.96 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT → MONITOR_CONNECTED_CARDS → ESCALATE_TO_ANALYST | ✅ |
| HHG-015 | risk_score | legitimate | 0.05 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-016 | customer_report | fraud | 0.95 | card_not_present_new_device | $59.67 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-017 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHG-018 | customer_report | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → WARN_CUSTOMER → CLOSE_NO_FRAUD | ✅ |
| HHG-019 | risk_score | fraud | 0.95 | card_not_present_new_device | $99.92 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-020 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
