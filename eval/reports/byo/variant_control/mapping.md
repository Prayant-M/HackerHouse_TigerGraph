# Schema mapping — variant_control

4 files from `build\variant_control`; mapped in 1137.1 s.

## case_pack ← `case_pack.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| trigger_type | trigger_type | 1.65 | identity | 3 shared values analyst_request, analyst_request |
| trigger_text | trigger_text | 1.65 | identity | 18 shared values Analyst request: several cards this month show losses with no shared device. Review transaction 3660108 on card C05061-K1 and look for what the affected cards have in common., Analyst request: several cards this month show losses with no shared device. Review transaction 3660127 on card C06220-K1 and look for what the affected cards have in common. |
| risk_score | risk_score | 1.65 | identity | quantiles match at scale x1 0.81, 0.8 |
| flagged_txn_id | flagged_txn_id | 1.65 | identity | quantiles match at scale x1 3660108, 3660127 |
| opened_at | opened_at | 1.585 | identity | same value shape (datetime) 2017-01-15 01:25:19, 2017-01-19 23:18:58 |
| customer_id | customer_id | 1.585 | identity | same value shape (customer_id) C05061, C06220 |
| case_id | case_id | 1.585 | identity | same value shape (case_id) HHF-001, HHF-002 |
| card_id | card_id | 1.585 | identity | same value shape (card_id) C05061-K1, C06220-K1 |

0 numbered-family columns mapped by index. Reshapes: none

## closed_cases ← `closed_cases_history.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| report_filed | report_filed | 1.65 | identity | 2 shared values No, No |
| pattern | pattern | 1.65 | identity | 6 shared values card_not_present_fraud, none |
| outcome | outcome | 1.65 | identity | 2 shared values confirmed_fraud, cleared |
| actions_taken | actions_taken | 1.65 | identity | 5 shared values CREATE_CASE|BLOCK_CARD, VERIFY_WITH_CUSTOMER|CLOSE_NO_FRAUD |
| first_fraud_txn_id | first_fraud_txn_id | 1.649 | identity | quantiles match at scale x1 3001611.0, 3000150.0 |
| txn_ids | txn_ids | 1.585 | identity | same value shape (ids_pipe) 3001611, 3004354 |
| opened_at | opened_at | 1.585 | identity | same value shape (datetime) 2016-07-03 22:54:31, 2016-07-03 23:36:27 |
| customer_id | customer_id | 1.585 | identity | same value shape (customer_id) C07847, C08842 |
| closed_at | closed_at | 1.585 | identity | same value shape (datetime) 2016-07-04 20:54:31, 2016-07-05 18:36:27 |
| case_id | case_id | 1.585 | identity | same value shape (case_id) CC-0022, CC-0026 |
| card_id | card_id | 1.585 | identity | same value shape (card_id) C07847-K2, C08842-K2 |
| n_txns | n_txns | 1.52 | identity | quantiles match at scale x1 1, 1 |
| exposure_usd | exposure_usd | 1.272 | identity | quantiles match at scale x1 100.04, 0.0 |
| connected_card_ids | connected_card_ids | 1.195 | identity | name and type agree; values sparse or free text  |
| analyst_notes | analyst_notes | 1.195 | identity | name and type agree; values sparse or free text Case CC-0022: cardholder C07847 reported unrecognized activity on card C07847-K2. 1 transaction(s) between 2016-07-02 and 2016-07-02 totaling $100.04 were confirmed fraudulent. Online purchases inconsistent with the cardholder's usual merchants and amounts. Online transactions came from a Windows on firefox 57.0. Card blocked and reissued. Customer reimbursed., Case CC-0026: model scored a $200.07 transaction at 0.99. Cardholder confirmed travel to the billing region in question. Alert cleared. |

0 numbered-family columns mapped by index. Reshapes: none

## identity ← `identity.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| id_15 | id_15 | 0.9 | identity | id* -> id_* (name hint + same size (38 members, 1..38)), member id_15  |
| id_23 | id_23 | 0.9 | identity | id* -> id_* (name hint + same size (38 members, 1..38)), member id_23  |
| id_31 | id_31 | 0.9 | identity | id* -> id_* (name hint + same size (38 members, 1..38)), member id_31  |
| DeviceType | DeviceType | 1.65 | identity | 2 shared values desktop, mobile |
| DeviceInfo | DeviceInfo | 1.65 | identity | 56 shared values Windows, Windows |
| TransactionID | TransactionID | 1.604 | identity | quantiles match at scale x1 3002118, 3002280 |

38 numbered-family columns mapped by index. Reshapes: none

## transactions ← `transactions.csv`

| from | to | score | transform | evidence |
|---|---|--:|---|---|
| D1 | D1 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D1  |
| D2 | D2 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D2  |
| D3 | D3 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D3  |
| D4 | D4 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D4  |
| D5 | D5 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D5  |
| D6 | D6 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D6  |
| D7 | D7 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D7  |
| D8 | D8 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D8  |
| D9 | D9 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D9  |
| D10 | D10 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D10  |
| D11 | D11 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D11  |
| D12 | D12 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D12  |
| D13 | D13 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D13  |
| D14 | D14 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D14  |
| D15 | D15 | 0.9 | identity | d* -> D* (name hint + same size (15 members, 1..15)), member D15  |
| C1 | C1 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C1  |
| C2 | C2 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C2  |
| C3 | C3 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C3  |
| C4 | C4 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C4  |
| C5 | C5 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C5  |
| C6 | C6 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C6  |
| C7 | C7 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C7  |
| C8 | C8 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C8  |
| C9 | C9 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C9  |
| C10 | C10 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C10  |
| C11 | C11 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C11  |
| C12 | C12 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C12  |
| C13 | C13 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C13  |
| C14 | C14 | 0.9 | identity | c* -> C* (name hint + same size (14 members, 1..14)), member C14  |
| M1 | M1 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M1  |
| M2 | M2 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M2  |
| M3 | M3 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M3  |
| M4 | M4 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M4  |
| M5 | M5 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M5  |
| M6 | M6 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M6  |
| M7 | M7 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M7  |
| M8 | M8 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M8  |
| M9 | M9 | 0.9 | identity | m* -> M* (name hint + same size (9 members, 1..9)), member M9  |
| channel | channel | 1.65 | identity | 2 shared values in_person, in_person |
| card6 | card6 | 1.65 | identity | 2 shared values debit, debit |
| card4 | card4 | 1.65 | identity | 4 shared values visa, visa |
| addr2 | addr2 | 1.65 | identity | quantiles match at scale x1 87.0, 87.0 |
| R_emaildomain | R_emaildomain | 1.65 | identity | 46 shared values yahoo.com, yahoo.com.mx |
| ProductCD | ProductCD | 1.65 | identity | 5 shared values W, W |
| P_emaildomain | P_emaildomain | 1.65 | identity | 45 shared values gmail.com, gmail.com |
| TransactionID | TransactionID | 1.628 | identity | quantiles match at scale x1 3000011, 3000030 |
| risk_score | risk_score | 1.627 | identity | quantiles match at scale x1 0.09, 0.08 |
| dist1 | dist1 | 1.623 | identity | quantiles match at scale x1 1.0, 5.0 |
| card5 | card5 | 1.622 | identity | quantiles match at scale x1 226.0, 226.0 |
| addr1 | addr1 | 1.62 | identity | quantiles match at scale x1 299.0, 299.0 |
| card1 | card1 | 1.601 | identity | quantiles match at scale x1 16435, 16435 |
| TransactionAmt | TransactionAmt | 1.6 | identity | quantiles match at scale x1 114.93, 319.01 |
| card3 | card3 | 1.599 | identity | quantiles match at scale x1 150.0, 150.0 |
| ts | ts | 1.585 | identity | same value shape (datetime) 2016-07-02 00:07:50, 2016-07-02 00:25:22 |
| customer_id | customer_id | 1.585 | identity | same value shape (customer_id) C03218, C03218 |
| dist2 | dist2 | 1.558 | identity | quantiles match at scale x1 7.0, 7.0 |
| card2 | card2 | 1.455 | identity | quantiles match at scale x1 321.0, 321.0 |
| TransactionDT | TransactionDT | 1.195 | identity | name and type agree; values sparse or free text 470, 1522 |

377 numbered-family columns mapped by index. Reshapes: none

