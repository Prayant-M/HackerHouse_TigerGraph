# Schema mapping — rehearsal

4 files from `build\variant`; mapped in 139.4 s.

## case_pack ← `alerts_to_review.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| trigger_type | trigger_type | 1.65 | identity | 1 shared values risk_score, risk_score |
| alertScore | risk_score | 0.931 | identity | quantiles match at scale x1 0.8, 0.53 |
| flaggedPayment | flagged_txn_id | 0.881 | identity | quantiles match at scale x1 3660355, 3655457 |
| message | trigger_text | 0.825 | identity | 3 shared values Real-time model scored transaction 3660355 ($228.01, online) at 0.8. Review and decide., Real-time model scored transaction 3655457 ($261.51) at 0.53. Review and decide. |
| openedTime | opened_at | 0.76 | identity | same value shape (datetime) 2017-01-27 18:08:36, 2017-01-09 04:34:19 |
| clientNo | customer_id | 0.76 | identity | same value shape (customer_id) C09177, C12223 |
| caseRef | case_id | 0.76 | identity | same value shape (case_id) HHF-009, HHF-012 |
| cardRef | card_id | 0.76 | identity | same value shape (card_id) C09177-K1, C12223-K1 |

0 numbered-family columns mapped by index. Reshapes: none

## identity ← `device_sessions.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| ident_15 | id_15 | 0.9 | identity | id_15  |
| ident_23 | id_23 | 0.9 | identity | id_23  |
| ident_31 | id_31 | 0.9 | identity | id_31  |
| deviceModel | DeviceInfo | 0.825 | identity | 51 shared values SM-G930V Build/NRD90M, MacOS |
| deviceClass | DeviceType | 0.825 | identity | 2 shared values mobile, desktop |
| paymentRef | TransactionID | 0.776 | identity | quantiles match at scale x1 3012642, 3002203 |

38 numbered-family columns mapped by index. Reshapes: none

## closed_cases ← `investigations.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| typology | pattern | 1.0 | identity | 5 shared values none, none |
| result | outcome | 1.0 | identity | 2 shared values cleared, cleared |
| lossAmount | exposure_usd | 0.847 | identity | quantiles match at scale x1 0.0, 0.0 |
| sarFiled | report_filed | 0.825 | identity | 2 shared values No, No |
| actions | actions_taken | 0.825 | identity | 3 shared values VERIFY_WITH_CUSTOMER|CLOSE_NO_FRAUD, VERIFY_WITH_CUSTOMER|CLOSE_NO_FRAUD |
| firstBadPayment | first_fraud_txn_id | 0.788 | identity | quantiles match at scale x1 3005146.0, 3008876.0 |
| openedTime | opened_at | 0.76 | identity | same value shape (datetime) 2016-07-03 23:36:27, 2016-07-04 04:29:21 |
| closedTime | closed_at | 0.76 | identity | same value shape (datetime) 2016-07-05 18:36:27, 2016-07-07 03:29:21 |
| clientNo | customer_id | 0.76 | identity | same value shape (customer_id) C08842, C05996 |
| caseRef | case_id | 0.76 | identity | same value shape (case_id) CC-0026, CC-0037 |
| cardRef | card_id | 0.76 | identity | same value shape (card_id) C08842-K2, C05996-K1 |
| paymentCount | n_txns | 0.607 | identity | quantiles match at scale x1 1, 1 |
| payments | txn_ids | 0.585 | identity | same value shape (ids_pipe) 3004354, 3006461 |
| notes | analyst_notes | 0.545 | identity | name and type agree; values sparse or free text Case CC-0026: model scored a $200.07 transaction at 0.99. Cardholder confirmed travel to the billing region in question. Alert cleared., Case CC-0037: model scored a $31.38 transaction at 0.84. Cardholder confirmed travel to the billing region in question. Alert cleared. |

0 numbered-family columns mapped by index. Reshapes: none

## transactions ← `payments_export.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| cnt_01 | C1 | 0.9 | identity | C1  |
| cnt_02 | C2 | 0.9 | identity | C2  |
| cnt_03 | C3 | 0.9 | identity | C3  |
| cnt_04 | C4 | 0.9 | identity | C4  |
| cnt_05 | C5 | 0.9 | identity | C5  |
| cnt_06 | C6 | 0.9 | identity | C6  |
| cnt_07 | C7 | 0.9 | identity | C7  |
| cnt_08 | C8 | 0.9 | identity | C8  |
| cnt_09 | C9 | 0.9 | identity | C9  |
| cnt_10 | C10 | 0.9 | identity | C10  |
| cnt_11 | C11 | 0.9 | identity | C11  |
| cnt_12 | C12 | 0.9 | identity | C12  |
| cnt_13 | C13 | 0.9 | identity | C13  |
| cnt_14 | C14 | 0.9 | identity | C14  |
| delta_01 | D1 | 0.9 | identity | D1  |
| delta_02 | D2 | 0.9 | identity | D2  |
| delta_03 | D3 | 0.9 | identity | D3  |
| delta_04 | D4 | 0.9 | identity | D4  |
| delta_05 | D5 | 0.9 | identity | D5  |
| delta_06 | D6 | 0.9 | identity | D6  |
| delta_07 | D7 | 0.9 | identity | D7  |
| delta_08 | D8 | 0.9 | identity | D8  |
| delta_09 | D9 | 0.9 | identity | D9  |
| delta_10 | D10 | 0.9 | identity | D10  |
| delta_11 | D11 | 0.9 | identity | D11  |
| delta_12 | D12 | 0.9 | identity | D12  |
| delta_13 | D13 | 0.9 | identity | D13  |
| delta_14 | D14 | 0.9 | identity | D14  |
| delta_15 | D15 | 0.9 | identity | D15  |
| match_1 | M1 | 0.9 | identity | M1  |
| match_2 | M2 | 0.9 | identity | M2  |
| match_3 | M3 | 0.9 | identity | M3  |
| match_4 | M4 | 0.9 | identity | M4  |
| match_5 | M5 | 0.9 | identity | M5  |
| match_6 | M6 | 0.9 | identity | M6  |
| match_7 | M7 | 0.9 | identity | M7  |
| match_8 | M8 | 0.9 | identity | M8  |
| match_9 | M9 | 0.9 | identity | M9  |
| prodCode | ProductCD | 1.0 | identity | 5 shared values W, C |
| chan | channel | 1.0 | identity | 2 shared values in_person, online |
| modelAlertScore | risk_score | 0.928 | identity | quantiles match at scale x1 0.08, 0.14 |
| valueCents | TransactionAmt | 0.787 | multiply by 0.01 | quantiles match at scale x0.01 11704.0, 2761.0 |
| paymentRef | TransactionID | 0.76 | identity | quantiles match at scale x1 3445829, 3451136 |
| clientNo | customer_id | 0.76 | identity | same value shape (customer_id) C04965, C13447 |
| payeeMailDomain | R_emaildomain | 0.65 | identity | 43 shared values gmail.com, comcast.net |
| network | card4 | 0.65 | identity | 4 shared values visa, visa |
| fundingType | card6 | 0.65 | identity | 2 shared values debit, credit |
| card_bin3 | card3 | 0.65 | identity | quantiles match at scale x1 150.0, 185.0 |
| buyerMailDomain | P_emaildomain | 0.65 | identity | 42 shared values gmail.com, icloud.com |
| billingCountry | addr2 | 0.65 | identity | quantiles match at scale x1 87.0, 87.0 |
| card_bin5 | card5 | 0.633 | identity | quantiles match at scale x1 226.0, 226.0 |
| card_issuer | card1 | 0.631 | identity | quantiles match at scale x1 21452, 10023 |
| billingZip | addr1 | 0.616 | identity | quantiles match at scale x1 512.0, 387.0 |
| distanceA | dist1 | 0.607 | identity | quantiles match at scale x1 5.0, 18.0 |
| card_bin2 | card2 | 0.599 | identity | quantiles match at scale x1 490.0, 141.0 |

377 numbered-family columns mapped by index. Reshapes: [{'reshape': 'timestamp split', 'columns': ['eventDate', 'eventTime'], 'to': 'ts'}]

