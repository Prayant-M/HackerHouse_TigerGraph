# Schema mapping — variant_b

4 files from `build\variant_b`; mapped in 1062.2 s.

## transactions ← `extract_01.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| t13 | D13 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D13  |
| t3 | D3 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D3  |
| t14 | D14 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D14  |
| t10 | D10 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D10  |
| t5 | D5 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D5  |
| t6 | D6 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D6  |
| t7 | D7 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D7  |
| t8 | D8 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D8  |
| t4 | D4 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D4  |
| t12 | D12 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D12  |
| t2 | D2 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D2  |
| t1 | D1 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D1  |
| t15 | D15 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D15  |
| t9 | D9 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D9  |
| t11 | D11 | 0.9 | identity | t* -> D* (same size (15 members, 1..15)), member D11  |
| k5 | C5 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C5  |
| k13 | C13 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C13  |
| k9 | C9 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C9  |
| k7 | C7 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C7  |
| k1 | C1 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C1  |
| k8 | C8 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C8  |
| k6 | C6 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C6  |
| k11 | C11 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C11  |
| k12 | C12 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C12  |
| k4 | C4 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C4  |
| k10 | C10 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C10  |
| k3 | C3 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C3  |
| k2 | C2 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C2  |
| k14 | C14 | 0.9 | identity | k* -> C* (same size (14 members, 1..14)), member C14  |
| flag2 | M2 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M2  |
| flag7 | M7 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M7  |
| flag9 | M9 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M9  |
| flag5 | M5 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M5  |
| flag6 | M6 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M6  |
| flag8 | M8 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M8  |
| flag1 | M1 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M1  |
| flag4 | M4 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M4  |
| flag3 | M3 | 0.9 | identity | flag* -> M* (same size (9 members, 1..9)), member M3  |
| pay_channel | channel | 1.0 | identity | 2 shared values in_person, in_person |
| score_rt | risk_score | 0.968 | identity | quantiles match at scale x1 0.22, 0.05 |
| amt_usd | TransactionAmt | 0.788 | identity | quantiles match at scale x1 170.92, 33.93 |
| txn_ref | TransactionID | 0.764 | identity | quantiles match at scale x1 3504341, 3063465 |
| party_no | customer_id | 0.76 | identity | same value shape (customer_id) C00777, C09241 |
| scheme | card4 | 0.65 | identity | 4 shared values visa, visa |
| prd | ProductCD | 0.65 | identity | 5 shared values W, W |
| pan_kind | card6 | 0.65 | identity | 2 shared values debit, debit |
| pan_e | card5 | 0.65 | identity | quantiles match at scale x1 195.0, 226.0 |
| mail_to | R_emaildomain | 0.65 | identity | 46 shared values hotmail.com, gmail.com |
| mail_from | P_emaildomain | 0.65 | identity | 47 shared values yahoo.com, yahoo.com |
| bill_ctry | addr2 | 0.65 | identity | quantiles match at scale x1 87.0, 87.0 |
| bill_area | addr1 | 0.62 | identity | quantiles match at scale x1 143.0, 476.0 |
| pan_a | card1 | 0.601 | identity | quantiles match at scale x1 18148, 11324 |
| pan_c | card3 | 0.599 | identity | quantiles match at scale x1 150.0, 150.0 |
| geo_d1 | dist1 | 0.573 | identity | quantiles match at scale x1 14.0, 10.0 |
| pan_b | card2 | 0.497 | identity | quantiles match at scale x1 215.0, 321.0 |
| dt_offset | TransactionDT | 0.428 | identity | name and type agree; values sparse or free text 13203911, 1446021 |

377 numbered-family columns mapped by index. Reshapes: [{'reshape': 'epoch seconds', 'columns': ['posted_epoch'], 'to': 'ts'}]

## identity ← `extract_02.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| sig15 | id_15 | 0.9 | identity | sig* -> id_* (same size (38 members, 1..38)), member id_15  |
| sig23 | id_23 | 0.9 | identity | sig* -> id_* (same size (38 members, 1..38)), member id_23  |
| sig31 | id_31 | 0.9 | identity | sig* -> id_* (same size (38 members, 1..38)), member id_31  |
| txn_ref | TransactionID | 0.779 | identity | quantiles match at scale x1 3002118, 3002280 |
| hw_string | DeviceInfo | 0.65 | identity | 56 shared values Windows, Windows |
| hw_kind | DeviceType | 0.65 | identity | 2 shared values desktop, mobile |

38 numbered-family columns mapped by index. Reshapes: none

## closed_cases ← `extract_03.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| steps_taken | actions_taken | 0.825 | identity | 5 shared values CREATE_CASE|BLOCK_CARD, VERIFY_WITH_CUSTOMER|CLOSE_NO_FRAUD |
| first_txn | first_fraud_txn_id | 0.789 | identity | quantiles match at scale x1 3001611.0, 3000150.0 |
| txn_list | txn_ids | 0.76 | identity | same value shape (ids_pipe) 3001611, 3004354 |
| party_no | customer_id | 0.76 | identity | same value shape (customer_id) C07847, C08842 |
| opened | opened_at | 0.76 | identity | same value shape (datetime) 2016-07-03 22:54:31, 2016-07-03 23:36:27 |
| closed | closed_at | 0.76 | identity | same value shape (datetime) 2016-07-04 20:54:31, 2016-07-05 18:36:27 |
| card_ref | card_id | 0.76 | identity | same value shape (card_id) C07847-K2, C08842-K2 |
| txn_n | n_txns | 0.695 | identity | quantiles match at scale x1 1, 1 |
| scheme_type | pattern | 0.65 | identity | 6 shared values card_not_present_fraud, none |
| sar | report_filed | 0.65 | identity | 2 shared values No, No |
| disposition | outcome | 0.65 | identity | 2 shared values confirmed_fraud, cleared |
| loss_usd | exposure_usd | 0.622 | identity | quantiles match at scale x1 100.04, 0.0 |
| remarks | analyst_notes | 0.585 | identity | free text, shared vocabulary 62% Case CC-0022: cardholder C07847 reported unrecognized activity on card C07847-K2. 1 transaction(s) between 2016-07-02 and 2016-07-02 totaling $100.04 were confirmed fraudulent. Online purchases inconsistent with the cardholder's usual merchants and amounts. Online transactions came from a Windows on firefox 57.0. Card blocked and reissued. Customer reimbursed., Case CC-0026: model scored a $200.07 transaction at 0.99. Cardholder confirmed travel to the billing region in question. Alert cleared. |
| inv_no | case_id | 0.585 | identity | same value shape (case_id) CC-0022, CC-0026 |

0 numbered-family columns mapped by index. Reshapes: none

## case_pack ← `extract_04.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| score_rt | risk_score | 1.0 | identity | quantiles match at scale x1 0.81, 0.8 |
| txn_ref | flagged_txn_id | 0.767 | identity | quantiles match at scale x1 3660108, 3660127 |
| party_no | customer_id | 0.76 | identity | same value shape (customer_id) C05061, C06220 |
| card_ref | card_id | 0.76 | identity | same value shape (card_id) C05061-K1, C06220-K1 |
| source | trigger_type | 0.65 | identity | 3 shared values analyst_request, analyst_request |
| raised | opened_at | 0.585 | identity | same value shape (datetime) 2017-01-15 01:25:19, 2017-01-19 23:18:58 |
| body | trigger_text | 0.585 | identity | free text, shared vocabulary 100% Analyst request: several cards this month show losses with no shared device. Review transaction 3660108 on card C05061-K1 and look for what the affected cards have in common., Analyst request: several cards this month show losses with no shared device. Review transaction 3660127 on card C06220-K1 and look for what the affected cards have in common. |
| alert_no | case_id | 0.585 | identity | same value shape (case_id) HHF-001, HHF-002 |

0 numbered-family columns mapped by index. Reshapes: none

