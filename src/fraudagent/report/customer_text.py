"""Customer-visible text, built so it *cannot* tip off.

Policy §9: nothing a customer sees may reveal that a suspicious activity report
is being considered or filed. Scanning output for banned words is the usual
control; here it is the second layer. The first is the type system: every
customer-facing string is built by `render()` from a `CustomerView`, and
`CustomerView` has no field that could carry SAR state, the verdict, the fraud
probability, the pattern, connected cards or anything else case-internal. A
function cannot leak what it is never given.

`tests/test_tipoff.py` toggles the SAR flag (and the verdict, probability and
pattern) on every answer and diffs the customer text: zero bytes change.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields

# Second layer: words that must never reach a customer.
BANNED = re.compile(
    r"\b(sar|suspicious activity|regulat\w*|report(?:ed|ing)? to|investigat\w*|fraud ring|"
    r"money laundering|law enforcement|compliance|file a report|filing|case id|graph|"
    r"probability|verdict|analyst|escalat\w*|ring|compromis\w*)\b", re.I)


@dataclass(frozen=True)
class CustomerView:
    """Everything a customer message may depend on. Deliberately nothing else."""

    request_type: str            # customer_validation | step_up_auth | warn
    channel: str
    amount_usd: float
    txn_date: str                # YYYY-MM-DD
    card_suffix: str             # last characters of the card id
    online: bool


ALLOWED_FIELDS = frozenset(f.name for f in fields(CustomerView))


def render(view: CustomerView) -> str:
    amt = f"${view.amount_usd:,.2f}"
    where = "online" if view.online else "in store"
    if view.request_type == "customer_validation":
        text = (f"We noticed a {amt} {where} purchase on your card ending {view.card_suffix} "
                f"on {view.txn_date}. Did you make this purchase? Reply YES or NO.")
    elif view.request_type == "step_up_auth":
        text = (f"To continue using your card ending {view.card_suffix}, please confirm this "
                f"session with the one-time passcode we sent to your registered device.")
    elif view.request_type == "warn":
        text = (f"A reminder: your card ending {view.card_suffix} has a regular {amt} charge. "
                f"If you no longer recognise it, contact us.")
    else:
        text = f"Please contact us about your card ending {view.card_suffix}."
    if BANNED.search(text):                                   # pragma: no cover - by design
        raise ValueError(f"customer text failed the tip-off scan: {text!r}")
    return text


def view_from(request_type: str, channel: str, flagged) -> CustomerView:
    """Build the view from a transaction row. Takes the row, not the case."""
    card = str(getattr(flagged, "card_id", "") or "")
    return CustomerView(
        request_type=request_type, channel=channel,
        amount_usd=round(float(getattr(flagged, "amount", 0.0) or 0.0), 2),
        txn_date=str(getattr(flagged, "ts", ""))[:10],
        card_suffix=card[-6:] if card else "",
        online=str(getattr(flagged, "channel", "")) == "online")


def scan(text: str) -> list[str]:
    return sorted({m.group(0).lower() for m in BANNED.finditer(text or "")})
