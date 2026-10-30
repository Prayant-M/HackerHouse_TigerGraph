# Graph schema drift proposal GSCHEMA-c1424a71e388

Bank_CoreT24: +1 -0 ~1 vertex types, 2 changed; +1 -0 edge types, 0 changed; mapping impact: 3 breaking, 2 remap

`bank3_core_banking_t24.gsql` → `bank3_core_banking_t24_v2.gsql`; detected in 0.04 s.

## Structure

- vertices added: DEVICE
- vertices removed: none
- edges added: PROTOCOL_DEVICE
- edges removed: none
- vertices renamed (proposed by attribute overlap): CARD_ISSUE → CARD (100%)
- `FUNDS_TRANSFER`: retyped: DEBIT_AMOUNT: DOUBLE -> STRING
- `PROTOCOL`: removed: TERMINAL_ID

## What it breaks in our mapping

| severity | kind | canonical | old target | new target | why |
|---|---|---|---|---|---|
| breaking | concept | LoginEvent | PROTOCOL | unmapped | was mapped, now nothing in the new schema carries it |
| breaking | edge | LOGGED_IN | PROTOCOL_USER > EXT_USER_CUSTOMER > reverse_ACCOUNT_CUSTOMER | unmapped | was mapped, now nothing in the new schema carries it |
| breaking | attribute | Transaction.amount | FUNDS_TRANSFER.DEBIT_AMOUNT | TELLER.AMOUNT_LOCAL_1 | old target retyped (DEBIT_AMOUNT: DOUBLE -> STRING); the mapper falls back to TELLER.AMOUNT_LOCAL_1 |
| remap | concept | Card | CARD_ISSUE | CARD | the mapper chose a different target in the new schema (the old target vertex type is gone or renamed) |
| remap | concept | Device | PROTOCOL.TERMINAL_ID | DEVICE | the mapper chose a different target in the new schema |

## New schema validation

- ok: True; problems: 0; warnings: 26
- mapping against the new file's ground truth: 21/25
