"""Data-quality taint (challenge C11).

Bad data looks like fraud, or hides it. For each investigation this finds the
gaps that matter to *this* decision — missing identity / device records, empty
billing regions, placeholder values, and card history too thin to judge — and
says whether the investigation can be trusted because of them.

A tainted case does not get a different verdict by fiat. Taint widens the
conformal prediction set (core/conformal.py) to {fraud, legit}, which routes
the case to uncertain + ESCALATE_TO_ANALYST under R8 when exposure or conflict
warrants it, and caps the confidence the answer may claim. Every issue lists
the record ids it rests on, so the taint is itself attested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Placeholder values observed in the data: a domain that stands for "not given",
# device strings with empty components, the zero region.
PLACEHOLDER_EMAILS = frozenset({"anonymous.com", "", "nan", "none", "unknown"})
THIN_HISTORY_TXNS = 5

# Which gaps actually blind which evidence. A gap only taints the case if the
# evidence it blinds could have changed the decision.
BLINDS = {
    "missing_identity": ("device_new_on_account", "device_shared_across_cards",
                         "anonymising_proxy", "device_proxy_hub", "peer_purchases"),
    "empty_billing_region": ("region_unseen", "out_of_region_card_present",
                             "home_activity_continues", "sustained_regional_stay"),
    "placeholder_email": ("email_mismatch",),
    "placeholder_device": ("device_new_on_account", "device_shared_across_cards"),
    "thin_history": ("amount_anomalous", "amount_extreme", "region_unseen",
                     "device_new_on_account"),
}


@dataclass
class QualityReport:
    issues: list[dict[str, Any]] = field(default_factory=list)
    tainted: bool = False
    severity: str = "none"          # none | low | high
    confidence_cap: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"tainted": self.tainted, "severity": self.severity,
                "confidence_cap": self.confidence_cap, "issues": self.issues}


def _placeholder_device(dp: str) -> bool:
    if not dp:
        return False
    parts = [p.strip() for p in dp.split("|")]
    return len(parts) > 1 and sum(1 for p in parts if not p) >= 2


def assess(ctx) -> QualityReport:
    """Pure function of the investigation context."""
    f = ctx.flagged
    rep = QualityReport()
    window = ctx.probes.get("episode", {}) or {}
    window_ids = [str(x) for x in (window.get("txn_ids") or [])][:50]
    n_base = int(ctx.baseline.get("n_txns", 0) or 0)

    def issue(kind: str, ids: list[str], detail: str, weight: str) -> None:
        rep.issues.append({"kind": kind, "record_ids": ids, "detail": detail,
                           "weight": weight, "blinds": list(BLINDS.get(kind, ()))})

    if not f.has_identity or not f.device_profile:
        issue("missing_identity", [f.txn_id],
              "the flagged transaction has no identity record, so device, proxy and "
              "shared-device evidence is unavailable rather than clean", "high"
              if f.channel == "online" else "low")
    elif _placeholder_device(f.device_profile):
        issue("placeholder_device", [f.txn_id],
              f"device profile {f.device_profile!r} is mostly empty components", "low")
    if not str(f.region or "").strip() or str(f.region) in {"nan", "None"}:
        issue("empty_billing_region", [f.txn_id],
              "the flagged transaction has no billing region, so regional evidence is "
              "unavailable", "high" if f.channel != "online" else "low")
    if str(f.email_p or "").strip().lower() in PLACEHOLDER_EMAILS:
        issue("placeholder_email", [f.txn_id],
              f"purchaser email domain is a placeholder ({f.email_p or 'empty'!r})", "low")
    if n_base < THIN_HISTORY_TXNS:
        issue("thin_history", [ctx.card_id_safe()],
              f"the card has {n_base} transactions before the suspect window; a baseline "
              f"needs at least {THIN_HISTORY_TXNS}", "high")
    no_id = window.get("n_without_identity")
    if no_id is not None and window_ids and int(no_id) >= max(2, len(window_ids) // 2):
        issue("window_identity_gaps", window_ids,
              f"{no_id} of {len(window_ids)} transactions in the suspect window lack "
              "identity records", "low")

    highs = [i for i in rep.issues if i["weight"] == "high"]
    rep.tainted = bool(highs)
    rep.severity = "high" if highs else ("low" if rep.issues else "none")
    rep.confidence_cap = 0.90 if highs else None
    return rep
