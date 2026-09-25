"""The hypothesis space.

We deliberately model the competing *explanations*, not "fraud yes/no", because
the type determines the action — and because the answer file is scored on
`pattern`. The space is therefore exactly the enum the dataset asks for, so no
lossy mapping step sits between what the agent believes and what it reports.

`UNDOCUMENTED` carries two sub-typologies mined out of the closed cases; see
`core/patterns.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

NONE = "none"
CARD_TESTING = "card_testing"
CNP = "card_not_present_fraud"
CNP_NEW_DEVICE = "card_not_present_new_device"
OUT_OF_REGION = "out_of_region_use"
ATO = "account_takeover"
UNDOCUMENTED = "undocumented"

HYPOTHESES: tuple[str, ...] = (
    NONE, CARD_TESTING, CNP, CNP_NEW_DEVICE, OUT_OF_REGION, ATO, UNDOCUMENTED,
)

FRAUD_HYPOTHESES: tuple[str, ...] = tuple(h for h in HYPOTHESES if h != NONE)

LABELS: dict[str, str] = {
    NONE: "Legitimate — unusual but genuine cardholder behaviour",
    CARD_TESTING: "Card testing — small probing authorisations before a larger hit",
    CNP: "Card-not-present fraud — card data used online without the instrument",
    CNP_NEW_DEVICE: "Card-not-present fraud from a device new to this account",
    OUT_OF_REGION: "Out-of-region use — card-present activity in an unfamiliar billing region",
    ATO: "Account takeover — credentials compromised, mixed-channel abuse",
    UNDOCUMENTED: "Undocumented typology — coordinated abuse matching no known pattern",
}


# The dataset's own names for the typologies, used wherever prose has to state a
# conclusion. `LABELS` carries the bank manual's *definition* of each pattern,
# which is the right thing to show an analyst choosing between hypotheses and
# the wrong thing to paste into a case summary: the definition asserts facts
# ("in an unfamiliar billing region") that a particular case may not have, and
# the reader is left with a summary that contradicts its own evidence list.
SHORT_LABELS: dict[str, str] = {
    NONE: "legitimate activity",
    CARD_TESTING: "card testing",
    CNP: "card-not-present fraud",
    CNP_NEW_DEVICE: "card-not-present fraud from a device new to the account",
    OUT_OF_REGION: "out-of-region use",
    ATO: "account takeover",
    UNDOCUMENTED: "an undocumented typology",
}


@dataclass(frozen=True)
class SubTypology:
    """An undocumented pattern discovered by mining the closed cases."""

    key: str
    name: str
    description: str
    seed_cases: tuple[str, ...]


SUB_TYPOLOGIES: dict[str, SubTypology] = {
    "threshold_structuring": SubTypology(
        key="threshold_structuring",
        name="Sub-threshold authorisation structuring",
        description=(
            "A burst of online purchases inside roughly forty minutes, each amount parked "
            "just beneath a round authorisation ceiling (typically $500), so that no single "
            "authorisation trips the bank's per-transaction review while the aggregate runs "
            "to several thousand dollars. It affects single cardholders rather than rings, "
            "and it is invisible to per-transaction scoring because every leg looks ordinary."
        ),
        seed_cases=("CC-3748", "CC-3841", "CC-3907", "CC-4086", "CC-4124"),
    ),
    "device_hub_ring": SubTypology(
        key="device_hub_ring",
        name="Shared-device compromise ring behind an anonymising proxy",
        description=(
            "One device profile — the same handset model, OS, browser and screen, reached "
            "through an anonymous proxy — appears on a run of unrelated cardholders inside a "
            "single month, each seeing it for the first time. No individual account shows a "
            "classic typology; the abuse is only visible as a hub in the card-device "
            "projection, which is why it must be found by traversal rather than by scoring."
        ),
        seed_cases=("CC-2649", "CC-2971", "CC-2985", "CC-3035"),
    ),
}


def uniform_prior() -> dict[str, float]:
    return {h: 1.0 / len(HYPOTHESES) for h in HYPOTHESES}


def fraud_probability(posterior: dict[str, float]) -> float:
    return float(sum(posterior.get(h, 0.0) for h in FRAUD_HYPOTHESES))


def top_two(posterior: dict[str, float]) -> tuple[tuple[str, float], tuple[str, float]]:
    ranked = sorted(posterior.items(), key=lambda kv: -kv[1])
    first = ranked[0]
    second = ranked[1] if len(ranked) > 1 else ("", 0.0)
    return first, second


def normalise(raw: dict[str, float]) -> dict[str, float]:
    total = sum(max(v, 0.0) for v in raw.values())
    if total <= 0:
        return uniform_prior()
    return {h: max(v, 0.0) / total for h, v in raw.items()}
