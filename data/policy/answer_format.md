# Answer Format

Submit one JSON file per case, named `<case_id>.json`, for every case in `case_pack.csv`. Twenty cases, twenty files, in a folder called `cases/` in your repository.

Each answer has **three parts**, because that is what a fraud investigation produces:

1. **The case.** The bank's internal record of the investigation: its status, what you concluded, what evidence you found, how far the fraud goes, and which past cases you drew on. Cases are internal. They progress as evidence arrives. Your agent should also write the case into the graph so later investigations can find it; that is the case memory the next investigation retrieves.
2. **The suspicious activity report (SAR).** The regulatory filing. Not every case needs one. When your agent recommends `FILE_REPORT`, include the report: who, what, when, where, how, and why it is suspicious. This goes to the regulator, so it must stand on its own.
3. **The next best action.** What the bank should do, with the approval route. Actions evolve: what you recommend before asking the customer may differ from what you recommend after. Record both.

Same structure for every case. Missing fields score zero for that part.

### Fields

#### Top level

| Field | Type | Meaning |
|---|---|---|
| `case_id` | string | From `case_pack.csv` |
| `case` | object | Part 1, below |
| `evidence_requests` | list | Each: `type` (`customer_validation` \| `step_up_auth` \| `analyst_info`), `asked_after_step` (int), `assumed_response` (string). Empty if you asked for nothing |
| `next_best_actions` | object | Part 3, below |
| `sar` | object | Part 2, below |
| `stop_reason` | string | Why the investigation ended here |
| `tool_calls` | int | Graph and retrieval calls made for this case |
| `tokens` | int | LLM tokens consumed for this case |
| `latency_s` | number | Wall-clock seconds for this case |

#### Part 1: `case`

| Field | Type | Meaning |
|---|---|---|
| `status` | `open` \| `closed_fraud` \| `closed_legitimate` \| `escalated` | Where the case stands when your agent stops. `open` means more evidence is still pending |
| `verdict` | `fraud` \| `legitimate` \| `uncertain` | Your conclusion |
| `fraud_probability` | number 0–1 | How likely the flagged activity is fraud. Be honest; this is scored for calibration |
| `pattern` | enum, see below | The fraud pattern you identified, `undocumented` if it matches none of the known ones, or `none` |
| `pattern_description` | string | Required when `pattern` is `undocumented`: two or three sentences on what the pattern is, who it affects, and how you found it. Otherwise `""` |
| `affected_txn_ids` | list of strings | Every transaction you believe is part of the same fraud episode, including the flagged one. Empty if legitimate |
| `first_suspicious_txn_id` | string or `""` | Where it started |
| `connected_card_ids` | list of strings | Other cards caught in the same compromise, ring, or device |
| `connected_device_profiles` | list of strings | Device profiles (DeviceInfo + OS + browser + screen) linking this case to other cards |
| `exposure_usd` | number | Sum of absolute amounts of `affected_txn_ids` |
| `evidence` | list of objects | Each: `claim` (string), `source` (`graph` \| `document` \| `customer` \| `external`), `ref` (query name, document section, or request id), `entity_ids` (list of IDs the claim rests on) |
| `similar_prior_cases` | list of strings | Closed-case IDs from `closed_cases_history.csv` your agent retrieved and used as memory, e.g. `["CC-0141", "CC-2671"]`. Empty if none |
| `summary` | string | Two to six sentences an analyst could read |
| `written_to_graph` | boolean | Whether your agent stored this case in TigerGraph |
| `graph_case_id` | string or `""` | The ID of the case vertex you created, if any |

#### Part 2: `sar`

| Field | Type | Meaning |
|---|---|---|
| `file` | boolean | Whether a suspicious activity report should be filed. Must agree with whether `FILE_REPORT` appears in your final actions |
| `reason` | string | Why file, or why not. Cite the policy rule |
| `narrative` | string | Required when `file` is true. The report itself: **who** (customer, cards, merchants, devices), **what** happened, **when** (dates), **where** (locations, channels), **how** it was carried out, **why** it is suspicious. Six to twelve sentences. This is what a regulator reads |
| `subjects` | list of strings | IDs of the customers, cards, merchants, and devices named in the narrative |
| `total_amount_usd` | number | Total of the suspicious activity |
| `activity_dates` | list of two strings | First and last date of the activity, `YYYY-MM-DD` |

If `file` is false: `narrative` is `""`, `subjects` is `[]`, `total_amount_usd` is 0, `activity_dates` is `[]`.

#### Part 3: `next_best_actions`

| Field | Type | Meaning |
|---|---|---|
| `initial` | list of objects | What you recommended **before** any requested evidence came back. Each: `action` (from the policy), `route` (`auto` \| `L1` \| `L2`), `reason` (cite the policy rule) |
| `final` | list of objects | What you recommend **after** the assumed responses in `evidence_requests`. Same shape. If you requested nothing, `final` equals `initial` |
| `what_changed` | string | One or two sentences on why `final` differs from `initial`, or `"nothing"` |

### `pattern` values

`card_testing` · `card_not_present_fraud` · `card_not_present_new_device` · `out_of_region_use` · `account_takeover` · `undocumented` · `none`

The first five are described in the Known Fraud Patterns section above. Use `undocumented` when the evidence shows abuse that fits none of them, and say what you found in `pattern_description`. Finding an undocumented pattern is scored.

### Example

```json
{
  "case_id": "HHG-017",
  "case": {
    "status": "closed_fraud",
    "verdict": "fraud",
    "fraud_probability": 0.86,
    "pattern": "card_testing",
    "pattern_description": "",
    "affected_txn_ids": ["T0412877", "T0412878", "T0412879", "T0412883"],
    "first_suspicious_txn_id": "T0412877",
    "connected_card_ids": ["C00877-K1"],
    "connected_device_profiles": ["SAMSUNG SM-G892A Build/NRD90M | Android 7.0 | samsung browser 6.2 | 2220x1080"],
    "exposure_usd": 268.43,
    "evidence": [
      {
        "claim": "Three online authorizations under $3 within 40 minutes, then a $259 purchase under a product code this card has never used",
        "source": "graph",
        "ref": "query:card_window(card_id=C00377-K1, hours=2)",
        "entity_ids": ["T0412877", "T0412878", "T0412879", "T0412883"]
      },
      {
        "claim": "All four came from a device profile marked New for this account (Android 7.0, Chrome for Android, 1920x1080), seen on closed case CC-0141 and on card C00877-K1 this month",
        "source": "graph",
        "ref": "query:device_neighbors(device_id=D000731)",
        "entity_ids": ["CC-0141", "C00877-K1"]
      },
      {
        "claim": "Customer denied the purchases when asked",
        "source": "customer",
        "ref": "evidence_request:1",
        "entity_ids": []
      }
    ],
    "similar_prior_cases": ["CC-0141"],
    "summary": "Textbook card testing: three sub-$3 online authorizations in 40 minutes, then a $259 purchase in a category the cardholder has never used. All four share a device profile marked New for this account, which appears on a closed case from August and on another card this month. Customer denied the activity. Card compromised; a second card is likely compromised through the same device.",
    "written_to_graph": true,
    "graph_case_id": "CASE-2016-1187"
  },
  "evidence_requests": [
    { "type": "customer_validation", "asked_after_step": 4, "assumed_response": "Customer states they did not make these purchases and still has the card" }
  ],
  "next_best_actions": {
    "initial": [
      { "action": "DECLINE_TRANSACTION", "route": "L1", "reason": "R5: testing sequence observed, purchase already cleared" },
      { "action": "VERIFY_WITH_CUSTOMER", "route": "auto", "reason": "R1: probability 0.72 on pattern alone, confirm before blocking" }
    ],
    "final": [
      { "action": "BLOCK_CARD", "route": "L1", "reason": "R2 and R5: customer denied; exposure $268 is under $2,500" },
      { "action": "CREATE_CASE", "route": "auto", "reason": "R2" },
      { "action": "FILE_REPORT", "route": "L2", "reason": "R2: shared device links this to another compromised card" },
      { "action": "MONITOR_CONNECTED_CARDS", "route": "auto", "reason": "Same device profile also used on C00877-K1" }
    ],
    "what_changed": "Customer denial raised probability from 0.72 to 0.86 and confirmed the block. The shared device profile with C00877-K1 triggers a report and monitoring of the connected card."
  },
  "sar": {
    "file": true,
    "reason": "R2: confirmed unauthorized use linked by a shared device to a second compromised card",
    "narrative": "On 2016-11-14 between 09:12 and 09:52, card C00377-K1 belonging to customer C00377 was used for three online authorizations of $1.10, $2.40, and $0.95 followed at 10:31 by a $259.98 online purchase under a product code the cardholder had never used. All four transactions came from a device profile marked New for this account, previously recorded on closed case CC-0141 (confirmed fraud, August 2016) and on card C00877-K1 on 2016-11-12. The cardholder, contacted the same day, stated they did not make these purchases and remained in possession of the card. The sequence of small authorizations followed by a larger purchase is consistent with testing of a stolen card number prior to use. The shared device indicates a common actor across at least two cardholders. Total unauthorized amount: $268.43. Card blocked and scheduled for reissue; card C00877-K1 placed under monitoring.",
    "subjects": ["C00377", "C00377-K1", "C00877-K1"],
    "total_amount_usd": 268.43,
    "activity_dates": ["2016-11-14", "2016-11-14"]
  },
  "stop_reason": "Customer denial settled the verdict; device link identified and connected card protected. Further steps would not change the actions.",
  "tool_calls": 9,
  "tokens": 12480,
  "latency_s": 18.7
}
```

### Notes

- IDs must be the ones in the dataset. Made-up IDs score zero.
- For a `legitimate` verdict, `affected_txn_ids` is empty, `exposure_usd` is 0, and `sar.file` is false.
- `uncertain` is a valid verdict and earns full credit on cases designed to be ambiguous, provided the actions follow policy R1 and R8.
- The `risk_score` on the flagged transaction is an input, not an answer. Your `fraud_probability` should reflect what you found, and may be far from it.
- Customer and analyst replies are not provided. State what you assumed in `evidence_requests`, and let `next_best_actions.final` reflect that assumption.
- Keep `summary` short. The evidence list carries the detail. The SAR narrative is the one place to be complete.

---