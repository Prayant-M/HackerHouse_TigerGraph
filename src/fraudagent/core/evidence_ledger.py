"""The Bayesian evidence ledger.

Belief over the seven hypotheses, updated in log space from *measured*
class-conditional probabilities. No LLM import reaches this file, and a test in
`tests/test_core_purity.py` fails the build if one ever does — the decision
layer cannot hallucinate because it cannot call a model.

Where the numbers come from, in descending order of trustworthiness:

1. **Measured.** `data/staged/likelihood_ratios.json`, produced by replaying
   every closed investigation through the same extractor the agent uses.
2. **Structural.** Hard matchers for the undocumented typologies, whose
   signature is near-deterministic and whose support in the history is too thin
   (5 and 4 cases) for a smoothed estimate to carry it.
3. **Solicited.** Customer and step-up responses, entered with an explicit
   reliability below 1.0 because customers forget and channels fail.

An LLM is never permitted to emit a likelihood ratio.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..config import PATHS
from . import hypotheses as H
from .signals import Signal

# Structural overrides. The two undocumented typologies were mined from 9 closed
# cases in total, which is not enough for a smoothed table to express how
# specific their signature is. Each entry is a per-hypothesis likelihood ratio.
STRUCTURAL_LR: dict[str, dict[str, float]] = {
    "threshold_structuring": {
        H.UNDOCUMENTED: 60.0, H.CNP: 1.5, H.CNP_NEW_DEVICE: 1.2,
        H.NONE: 0.08, H.OUT_OF_REGION: 0.2, H.ATO: 0.5, H.CARD_TESTING: 0.6,
    },
    "device_proxy_hub": {
        H.UNDOCUMENTED: 12.0, H.CNP_NEW_DEVICE: 2.0, H.CNP: 1.2,
        H.NONE: 0.35, H.OUT_OF_REGION: 0.3, H.ATO: 0.8, H.CARD_TESTING: 1.0,
    },
    "card_testing_sequence": {
        H.CARD_TESTING: 45.0, H.CNP: 1.2, H.CNP_NEW_DEVICE: 1.2,
        H.NONE: 0.1, H.OUT_OF_REGION: 0.2, H.ATO: 0.8, H.UNDOCUMENTED: 1.0,
    },
    "out_of_region_card_present": {
        H.OUT_OF_REGION: 8.0, H.ATO: 1.3, H.NONE: 0.5,
        H.CNP: 0.15, H.CNP_NEW_DEVICE: 0.15, H.CARD_TESTING: 0.2,
        H.UNDOCUMENTED: 0.6,
    },
    "home_activity_continues": {
        H.OUT_OF_REGION: 4.0, H.ATO: 1.2, H.NONE: 0.3,
        H.CNP: 0.8, H.CNP_NEW_DEVICE: 0.8, H.CARD_TESTING: 0.8,
        H.UNDOCUMENTED: 0.8,
    },
    "sustained_regional_stay": {
        # a trip, not a clone — the dataset README says so explicitly
        H.NONE: 4.0, H.OUT_OF_REGION: 0.25, H.ATO: 0.6,
        H.CNP: 0.9, H.CNP_NEW_DEVICE: 0.9, H.CARD_TESTING: 0.9,
        H.UNDOCUMENTED: 0.9,
    },
    "matches_cleared_alert_template": {
        H.NONE: 5.0, H.CNP: 0.35, H.CNP_NEW_DEVICE: 0.4, H.ATO: 0.3,
        H.OUT_OF_REGION: 0.4, H.CARD_TESTING: 0.15, H.UNDOCUMENTED: 0.15,
    },
    "recurring_charge": {
        H.NONE: 9.0, H.CNP: 0.12, H.CNP_NEW_DEVICE: 0.12, H.ATO: 0.2,
        H.OUT_OF_REGION: 0.3, H.CARD_TESTING: 0.2, H.UNDOCUMENTED: 0.2,
    },
    "device_new_on_account": {
        # A new device tells you *which* typology, not *whether* it is fraud.
        # The dataset README says so outright — "still not proof: people buy new
        # phones" — and 98% of the cleared "new phone" investigations fire this
        # signal. So it steers the pattern and leaves P(legitimate) alone.
        H.CNP_NEW_DEVICE: 2.6, H.CNP: 0.7, H.ATO: 1.3, H.NONE: 1.0,
        H.OUT_OF_REGION: 0.25, H.CARD_TESTING: 1.1, H.UNDOCUMENTED: 1.1,
    },
    "mixed_channel_shift": {
        H.ATO: 4.0, H.NONE: 0.7, H.CNP: 0.6, H.CNP_NEW_DEVICE: 0.6,
        H.OUT_OF_REGION: 0.9, H.CARD_TESTING: 0.8, H.UNDOCUMENTED: 1.0,
    },
    "online_burst_2_to_4": {
        H.CNP: 2.2, H.CNP_NEW_DEVICE: 1.8, H.NONE: 0.7, H.ATO: 0.8,
        H.OUT_OF_REGION: 0.1, H.CARD_TESTING: 1.5, H.UNDOCUMENTED: 1.4,
    },
}

# Solicited evidence. Reliability below 1.0 damps the update; see `update`.
SOLICITED_LR: dict[str, dict[str, float]] = {
    "customer_denied": {
        H.NONE: 0.12, H.CNP: 3.0, H.CNP_NEW_DEVICE: 3.0, H.ATO: 3.0,
        H.OUT_OF_REGION: 3.0, H.CARD_TESTING: 3.0, H.UNDOCUMENTED: 3.0,
    },
    "customer_confirmed": {
        H.NONE: 14.0, H.CNP: 0.08, H.CNP_NEW_DEVICE: 0.08, H.ATO: 0.1,
        H.OUT_OF_REGION: 0.08, H.CARD_TESTING: 0.1, H.UNDOCUMENTED: 0.1,
    },
    "customer_no_response": {
        H.NONE: 0.8, H.CNP: 1.15, H.CNP_NEW_DEVICE: 1.15, H.ATO: 1.15,
        H.OUT_OF_REGION: 1.15, H.CARD_TESTING: 1.15, H.UNDOCUMENTED: 1.15,
    },
    "step_up_passed": {
        H.NONE: 3.5, H.ATO: 0.12, H.CNP: 0.5, H.CNP_NEW_DEVICE: 0.5,
        H.OUT_OF_REGION: 0.7, H.CARD_TESTING: 0.5, H.UNDOCUMENTED: 0.6,
    },
    "step_up_failed": {
        H.NONE: 0.12, H.ATO: 6.0, H.CNP: 2.0, H.CNP_NEW_DEVICE: 2.5,
        H.OUT_OF_REGION: 1.2, H.CARD_TESTING: 2.0, H.UNDOCUMENTED: 2.0,
    },
    "analyst_confirms_ring": {
        H.UNDOCUMENTED: 5.0, H.CNP_NEW_DEVICE: 1.5, H.NONE: 0.2,
        H.CNP: 1.0, H.ATO: 1.0, H.OUT_OF_REGION: 0.5, H.CARD_TESTING: 1.0,
    },
    "analyst_no_prior_relationship": {
        H.UNDOCUMENTED: 0.6, H.NONE: 1.6, H.CNP: 0.9, H.CNP_NEW_DEVICE: 0.9,
        H.ATO: 0.9, H.OUT_OF_REGION: 1.0, H.CARD_TESTING: 0.9,
    },
}

# No investigation on this evidence is certain. Reporting 1.00 is not
# confidence, it is a missing error bar, and `fraud_probability` is explicitly
# scored for calibration — so the reported posterior is clamped. The ceiling is
# above the 0.85 action threshold in policy §6, so clamping never changes an
# action; it only stops the number claiming more than the evidence supports.
CONFIDENCE_CEILING = 0.97
CONFIDENCE_FLOOR = 0.02

RELIABILITY = {
    "graph": 1.0,
    "structural": 1.0,
    "customer": 0.85,       # customers forget, and customers occasionally lie
    "step_up": 0.92,
    "analyst": 0.95,
    "behavioural": 0.9,
}


@lru_cache(maxsize=1)
def calibration() -> dict[str, Any]:
    if not PATHS.lr_table_json.exists():
        return {}
    return json.loads(PATHS.lr_table_json.read_text(encoding="utf-8"))


@dataclass
class LedgerEntry:
    label: str
    source: str
    likelihood_ratios: dict[str, float]
    reliability: float
    posterior_before: dict[str, float]
    posterior_after: dict[str, float]
    claim: str = ""
    ref: str = ""
    entity_ids: list[str] = field(default_factory=list)

    @property
    def delta_fraud(self) -> float:
        return (H.fraud_probability(self.posterior_after)
                - H.fraud_probability(self.posterior_before))


def _normalise(scores: dict[str, float]) -> dict[str, float]:
    total = sum(scores.values())
    if total <= 0:
        return H.uniform_prior()
    return {h: v / total for h, v in scores.items()}


def apply_lr(posterior: dict[str, float], lrs: dict[str, float],
             reliability: float = 1.0) -> dict[str, float]:
    """One Bayes step. Reliability shrinks each ratio toward 1 (no information),
    which is the honest way to say "this source is usually but not always right"."""
    out: dict[str, float] = {}
    for h, p in posterior.items():
        lr = float(lrs.get(h, 1.0))
        damped = 1.0 + (lr - 1.0) * reliability
        out[h] = p * max(damped, 1e-9)
    return _normalise(out)


# Rare structural signals whose *absence* is not evidence. `peer_purchases` fires
# on 8.5% of confirmed fraud and 0.4% of cleared cases, so its presence is a
# measured 22x; but folding in "did not fire" on every other case nudged each
# one away from card-not-present fraud, and on the October holdout that cost
# nineteen correct pattern calls. Absence of a rare hub is not a finding.
FIRED_ONLY: frozenset[str] = frozenset({"peer_purchases"})


class EvidenceLedger:
    """Append-only belief state. Every entry records the posterior on both sides
    of its own update, so the case file can show exactly what moved the needle."""

    def __init__(self, prior: dict[str, float], damping: float | None = None) -> None:
        self.posterior: dict[str, float] = _normalise(dict(prior))
        self.prior: dict[str, float] = dict(self.posterior)
        self.entries: list[LedgerEntry] = []
        cal = calibration()
        self.damping: float = damping if damping is not None else float(cal.get("damping", 0.7))
        self.tables: dict[str, dict[str, float]] = cal.get("class_conditional_p", {})
        self.learned_signals: set[str] = set(cal.get("signals", []))

    # ------------------------------------------------------ measured LRs ----
    def measured_lr(self, signal_name: str, fired: bool) -> dict[str, float] | None:
        """Class-conditional likelihood ratio for one signal, from the replay."""
        if not self.tables or signal_name not in self.learned_signals:
            return None
        probs: dict[str, float] = {}
        for h in H.HYPOTHESES:
            tbl = self.tables.get(h)
            if not tbl or signal_name not in tbl:
                return None
            p = min(max(float(tbl[signal_name]), 1e-4), 1 - 1e-4)
            probs[h] = p if fired else (1.0 - p)
        mean = sum(probs.values()) / len(probs)
        if mean <= 0:
            return None
        # express as a ratio against the average hypothesis, then damp for the
        # naive-independence violation measured on the held-out split
        return {h: (p / mean) ** self.damping for h, p in probs.items()}

    # ------------------------------------------------------------ update ----
    def add(self, label: str, source: str, lrs: dict[str, float], reliability: float,
            claim: str = "", ref: str = "", entity_ids: list[str] | None = None) -> LedgerEntry:
        before = dict(self.posterior)
        self.posterior = apply_lr(self.posterior, lrs, reliability)
        entry = LedgerEntry(label=label, source=source, likelihood_ratios=
                            {k: round(v, 4) for k, v in lrs.items()},
                            reliability=reliability, posterior_before=before,
                            posterior_after=dict(self.posterior), claim=claim, ref=ref,
                            entity_ids=entity_ids or [])
        self.entries.append(entry)
        return entry

    def add_signal(self, sig: Signal) -> LedgerEntry | None:
        """Fold one extracted signal in. Structural overrides win over the
        measured table where they exist, because they encode a typology
        signature the history is too thin to teach."""
        structural = STRUCTURAL_LR.get(sig.name)
        if structural is not None and sig.fired:
            # The same damping the held-out split fitted for the measured table
            # applies here. These signals are not independent of the measured
            # ones — a structuring burst also shows up as a velocity burst and as
            # an online burst — and undamped they compound into a posterior of
            # 1.00 that no evidence set in this dataset earns.
            lrs = {h: (1.0 + (v - 1.0) * max(sig.strength, 0.35)) ** self.damping
                   for h, v in structural.items()}
            return self.add(sig.name, "structural", lrs, RELIABILITY["structural"],
                            sig.claim, sig.ref, sig.entity_ids)
        if not sig.fired and sig.name in FIRED_ONLY:
            return None
        lrs = self.measured_lr(sig.name, sig.fired)
        if lrs is None:
            return None
        spread = max(lrs.values()) / max(min(lrs.values()), 1e-6)
        if spread < 1.05:
            return None                      # carries no information; do not clutter the ledger
        rel = RELIABILITY["behavioural"] if sig.name.startswith("behavioural") \
            else RELIABILITY["graph"]
        return self.add(sig.name, "measured", lrs, rel,
                        sig.claim if sig.fired else f"NOT observed: {sig.name}",
                        sig.ref, sig.entity_ids if sig.fired else [])

    def add_solicited(self, key: str, claim: str, ref: str,
                      reliability: float | None = None) -> LedgerEntry | None:
        lrs = SOLICITED_LR.get(key)
        if lrs is None:
            return None
        if reliability is None:
            reliability = RELIABILITY["step_up"] if key.startswith("step_up") else (
                RELIABILITY["analyst"] if key.startswith("analyst") else RELIABILITY["customer"])
        return self.add(key, "solicited", lrs, reliability, claim, ref)

    # ------------------------------------------------------- inspection ----
    def reported(self) -> dict[str, float]:
        """The posterior as reported, with the confidence ceiling applied.

        The clamp is redistributed across the fraud hypotheses rather than
        dropped, so the pattern ranking is untouched and only the headline
        probability is made honest.
        """
        p = H.fraud_probability(self.posterior)
        if CONFIDENCE_FLOOR <= p <= CONFIDENCE_CEILING:
            return dict(self.posterior)
        target = min(max(p, CONFIDENCE_FLOOR), CONFIDENCE_CEILING)
        out = dict(self.posterior)
        if p <= 0 or p >= 1:
            return out
        scale = target / p
        for h in H.FRAUD_HYPOTHESES:
            out[h] = out.get(h, 0.0) * scale
        out[H.NONE] = 1.0 - target
        return out

    @property
    def fraud_probability(self) -> float:
        return H.fraud_probability(self.reported())

    @property
    def top_pattern(self) -> str:
        return max(self.posterior.items(), key=lambda kv: kv[1])[0]

    @property
    def margin(self) -> float:
        (_, p1), (_, p2) = H.top_two(self.posterior)
        return p1 - p2

    def entropy(self) -> float:
        return -sum(p * math.log(p + 1e-12) for p in self.posterior.values())

    def contradictions(self) -> list[tuple[str, str]]:
        """Pairs of entries that pushed P(fraud) in opposite directions by more
        than five points each. A conflicted case is worth saying so about."""
        up = [e for e in self.entries if e.delta_fraud > 0.05]
        down = [e for e in self.entries if e.delta_fraud < -0.05]
        return [(a.label, b.label) for a in up for b in down][:6]

    def top_movers(self, k: int = 5) -> list[LedgerEntry]:
        return sorted(self.entries, key=lambda e: -abs(e.delta_fraud))[:k]

    def snapshot(self) -> dict[str, float]:
        return {h: round(p, 4) for h, p in self.reported().items()}

    def clone(self) -> "EvidenceLedger":
        c = EvidenceLedger(self.prior, self.damping)
        c.posterior = dict(self.posterior)
        c.entries = list(self.entries)
        c.tables = self.tables
        c.learned_signals = self.learned_signals
        return c


def trigger_prior(trigger_type: str) -> dict[str, float]:
    """Operating prior conditioned on how the alert arrived.

    Measured pattern mix from the closed cases, but with a P(legitimate) that
    comes from the dataset's own guidance rather than from the case file's base
    rate: the file is 84% fraud because it *is* a case file.
    """
    cal = calibration()
    priors = cal.get("operating_priors", {})
    if trigger_type in priors:
        return _normalise({h: float(v) for h, v in priors[trigger_type].items()})
    mix = cal.get("fraud_pattern_mix") or {
        H.CNP: 0.30, H.ATO: 0.26, H.CNP_NEW_DEVICE: 0.23,
        H.OUT_OF_REGION: 0.20, H.CARD_TESTING: 0.003, H.UNDOCUMENTED: 0.002,
    }
    p_none = {"risk_score": 0.62, "customer_report": 0.20,
              "analyst_request": 0.35}.get(trigger_type, 0.5)
    return _normalise({H.NONE: p_none, **{h: (1 - p_none) * w for h, w in mix.items()}})
