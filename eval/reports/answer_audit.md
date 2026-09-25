# Answer audit

20 answer files in `cases/`, **0 issue(s)**. Checks: data integrity, §2 routing, §3a case/SAR, §4 exposure, R1, R2, R3, R7, §6 stopping, graph read-back. There is no answer key; this proves consistency, not correctness.

| case | trigger | verdict | p | pattern | exposure | SAR | final actions | audit |
|---|---|---|---:|---|---:|---|---|---|
| HHG-001 | risk_score | legitimate | 0.08 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-002 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHG-003 | customer_report | fraud | 0.97 | out_of_region_use | $224.93 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-004 | customer_report | fraud | 0.93 | card_not_present_new_device | $128.33 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-005 | risk_score | legitimate | 0.03 | none | $0.00 | no | CLOSE_NO_FRAUD | ✅ |
| HHG-006 | customer_report | fraud | 0.97 | undocumented | $1,906.07 | yes | BLOCK_CARD → CREATE_CASE → FILE_REPORT → ESCALATE_TO_ANALYST | ✅ |
| HHG-007 | risk_score | legitimate | 0.02 | none | $0.00 | no | CREATE_CASE → CLOSE_NO_FRAUD | ✅ |
| HHG-008 | customer_report | fraud | 0.88 | account_takeover | $261.15 | no | BLOCK_CARD → CREATE_CASE | ✅ |
| HHG-009 | customer_report | fraud | 0.79 | account_takeover | $30.02 | no | BLOCK_CARD → CREATE_CASE | ✅ |
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
