"""Reconstructing the fraud episode.

The alert names one transaction. The answer file wants every transaction in the
same episode, where it started, which other cards are caught in it, and the
dollar exposure. Getting this wrong in either direction is expensive: a
one-transaction episode reported as twelve inflates exposure and pushes the
case over the SAR threshold it should not cross, and a twelve-transaction
episode reported as one understates the harm.

The closed-case history says what the right size looks like — median 1
transaction for card-not-present, 2 for account takeover, 4 for the
sub-threshold structuring typology, 17 for card testing — so the builder
selects by *mechanism* rather than by sweeping the window.

`exposure_usd` is the sum of absolute amounts of the selected transactions,
per Fraud Policy §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ..graphstore.base import GraphStore, TxnRow
from . import hypotheses as H
from .signals import InvestigationContext


@dataclass
class Episode:
    affected_txn_ids: list[str] = field(default_factory=list)
    first_suspicious_txn_id: str = ""
    exposure_usd: float = 0.0
    connected_card_ids: list[str] = field(default_factory=list)
    connected_device_profiles: list[str] = field(default_factory=list)
    activity_dates: list[str] = field(default_factory=list)
    basis: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "affected_txn_ids": self.affected_txn_ids,
            "first_suspicious_txn_id": self.first_suspicious_txn_id,
            "exposure_usd": round(self.exposure_usd, 2),
            "connected_card_ids": self.connected_card_ids,
            "connected_device_profiles": self.connected_device_profiles,
        }


# An episode is a burst, not "everything in the alert window". On a card doing
# forty transactions a day the 72-hour window contains a hundred ordinary legs,
# and sweeping them all reports five figures of exposure for a $39 dispute — and
# drags the case over the SAR threshold on arithmetic alone. The closed cases say
# what the real shape is: median 1 transaction for card-not-present, 2 for
# takeover, 4 for the structuring typology, 17 for card testing.
EPISODE_PROXIMITY_HOURS = 48.0
PATTERN_CAP = {
    H.CARD_TESTING: 24,       # median 17 in the closed cases
    H.UNDOCUMENTED: 8,        # median 4
}
DEFAULT_CAP = 6


def _window_rows(store: GraphStore, ctx: InvestigationContext) -> list[TxnRow]:
    ep = ctx.probes.get("episode", {})
    ids = set(str(t) for t in ep.get("window_txn_ids", []))
    ids.add(ctx.flagged.txn_id)
    lo = ctx.flagged.ts - timedelta(hours=EPISODE_PROXIMITY_HOURS)
    hi = ctx.flagged.ts + timedelta(hours=EPISODE_PROXIMITY_HOURS)
    rows = [t for t in store.card_history(ctx.card_id_safe(), ctx.as_of, window_days=7)
            if t.txn_id in ids and lo <= t.ts <= hi]
    rows.sort(key=lambda t: t.ts)
    return rows


def build(store: GraphStore, ctx: InvestigationContext, pattern: str,
          verdict: str) -> Episode:
    """Select the transactions that belong to the episode, by mechanism."""
    flagged = ctx.flagged
    if verdict == "legitimate":
        # The dataset is explicit: a legitimate verdict carries no affected
        # transactions and zero exposure.
        return Episode(basis="verdict is legitimate")

    selected: dict[str, TxnRow] = {flagged.txn_id: flagged}
    basis = "flagged transaction"
    rows = _window_rows(store, ctx)
    by_id = {t.txn_id: t for t in rows}

    def take(ids, why: str) -> None:
        nonlocal basis
        added = False
        for t in ids:
            t = str(t)
            if t in by_id and t not in selected:
                selected[t] = by_id[t]
                added = True
        if added:
            basis = why

    if pattern == H.CARD_TESTING:
        probe = ctx.probes.get("card_testing", {})
        take(probe.get("small_txn_ids", []), "card-testing sequence")
        if probe.get("follow_txn_id"):
            take([probe["follow_txn_id"]], "card-testing sequence and the purchase that followed")

    elif pattern == H.UNDOCUMENTED:
        struct = ctx.probes.get("threshold_structuring", {})
        if struct.get("matched"):
            take(struct.get("txn_ids", []), "sub-threshold structuring burst")
        else:
            dev = flagged.device_profile
            take([t.txn_id for t in rows if dev and t.device_profile == dev],
                 "transactions from the shared hub device")

    elif pattern == H.OUT_OF_REGION:
        region = flagged.region
        home = str(ctx.baseline.get("home_region") or "")
        if region and region != home:
            take([t.txn_id for t in rows
                  if t.region == region and t.channel == "in_person"],
                 f"card-present activity in region {region}, where this card has no history")

    elif pattern in {H.CNP, H.CNP_NEW_DEVICE}:
        dev = flagged.device_profile
        if pattern == H.CNP_NEW_DEVICE and dev:
            take([t.txn_id for t in rows
                  if t.device_profile == dev and t.channel == "online"],
                 "online activity from the device new to this account")
        base = ctx.baseline
        p95 = float(base.get("amt_p95") or 0.0)
        take([t.txn_id for t in rows
              if t.channel == "online" and p95 > 0 and t.amount > p95],
             "online purchases outside this card's established spending range")

    elif pattern == H.ATO:
        # Takeover is mixed-channel by definition, but "the whole window" is not
        # an episode: on a card doing forty transactions a day it would report
        # five figures of exposure and drag the case over the SAR threshold on
        # arithmetic alone. Take only the legs that are themselves anomalous.
        p95 = float(ctx.baseline.get("amt_p95") or 0.0)
        known_devices = set(ctx.baseline.get("known_devices") or [])
        take([t.txn_id for t in rows
              if (p95 > 0 and t.amount > p95)
              or (t.device_profile and t.device_profile not in known_devices)
              or t.m_mismatch_count >= 2],
             "mixed-channel legs inconsistent with the cardholder's own pattern")

    ordered = sorted(selected.values(), key=lambda t: t.ts)
    # The closed-case history is the sanity check on size: median 1 transaction
    # for card-not-present, 2 for takeover, 4 for the structuring typology, 17
    # for card testing. An episode in the dozens is a selection bug, not a
    # crime spree, so the window is trimmed to the legs nearest the alert.
    cap = PATTERN_CAP.get(pattern, DEFAULT_CAP)
    if len(ordered) > cap:
        flagged_idx = next((i for i, t in enumerate(ordered)
                            if t.txn_id == flagged.txn_id), len(ordered) - 1)
        lo = max(0, flagged_idx - cap + 1)
        ordered = ordered[lo:lo + cap]
        basis += f" (trimmed to the {cap} legs nearest the alert)"
    exposure = sum(abs(t.amount) for t in ordered)

    ring = ctx.probes.get("ring", {})
    fan = ctx.probes.get("device_fanout", {})
    connected: list[str] = []
    devices: list[str] = []
    if ctx.fired("shared_origin_ring") or ctx.fired("device_proxy_hub"):
        connected = list(ring.get("connected_card_ids", []))[:40]
        hub = ring.get("hub_device") or (flagged.device_profile
                                         if ctx.fired("device_proxy_hub") else "")
        if hub:
            devices = [hub]
        if not connected and ctx.fired("device_proxy_hub"):
            connected = [c for c in fan.get("anon_proxy_card_ids", [])
                         if c != flagged.card_id][:40]
    elif pattern == H.CNP_NEW_DEVICE and flagged.device_profile:
        devices = [flagged.device_profile]

    dates = sorted({t.ts.strftime("%Y-%m-%d") for t in ordered})
    return Episode(
        affected_txn_ids=[t.txn_id for t in ordered],
        first_suspicious_txn_id=ordered[0].txn_id if ordered else "",
        exposure_usd=exposure,
        connected_card_ids=connected,
        connected_device_profiles=devices,
        activity_dates=[dates[0], dates[-1]] if dates else [],
        basis=basis,
    )
