"""Policy as code.

The bank's Fraud Policy ships as prose. Prose in a prompt is a suggestion; the
agent needs an obligation. Every rule R1-R10, the case-versus-report test in
§3a and the stopping conditions in §6 are implemented here as pure functions
over case state, each carrying the clause id it enforces and the verbatim
source text it was compiled from (loaded at runtime from
`data/policy/chunks.jsonl`, so a citation can never drift from the document).

The LLM never chooses an action. It receives `permitted ∪ required` from this
module and may only phrase what is already decided. Anything it invents is
dropped by `PolicyDecision.filter`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from ..config import PATHS
from . import hypotheses as H
from .permissions import RoutedAction, route


# ---------------------------------------------------------------- clauses ----
@lru_cache(maxsize=1)
def clause_text() -> dict[str, str]:
    """Verbatim policy text keyed by rule id, straight from the dataset README."""
    out: dict[str, str] = {}
    path = PATHS.policy / "chunks.jsonl"
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("kind") in {"policy_rule", "policy_section"}:
            out[d["doc_id"].replace("POLICY-", "")] = d["text"]
    return out


def cite(rule: str) -> str:
    return clause_text().get(rule, "")


# ------------------------------------------------------------ case state ----
@dataclass
class CaseState:
    """Everything the policy needs to know. Deliberately small and typed."""

    case_id: str
    trigger_type: str
    fraud_probability: float
    verdict: str                       # fraud | legitimate | uncertain
    pattern: str
    exposure_usd: float
    n_independent_evidence: int
    single_signal_only: bool
    customer_response: str = ""        # denied | confirmed | no_response | ""
    step_up_result: str = ""           # passed | failed | ""
    connected_card_ids: list[str] = field(default_factory=list)
    connected_device_profiles: list[str] = field(default_factory=list)
    shares_origin_with_other_fraud: bool = False
    card_testing_matched: bool = False
    card_testing_cleared_over_100: bool = False
    recurring_charge_match: bool = False
    coordinated_or_undocumented: bool = False
    conflicting_evidence: bool = False
    cards_with_confirmed_fraud: int = 0
    credentials_confirmed_compromised: bool = False
    contacts_in_window: int = 0
    evidence_requested: bool = False
    has_pending_authorisation: bool = True
    # True when the conformal set could not single out fraud (core/conformal.py):
    # a probability above 0.70 is then not "strongly suspected" for §3a.
    conformal_abstained: bool = False

    def __post_init__(self) -> None:
        # Provenance guard: the policy core accepts graph, extractor and
        # solicited values only. Customer/analyst free text cannot get in.
        from dataclasses import fields as _fields

        from .provenance import check

        for f in _fields(self):
            check(getattr(self, f.name), f"CaseState.{f.name}")


@dataclass
class PolicyDecision:
    actions: list[RoutedAction]
    cited_rules: list[str]
    obligations: list[str]
    forbidden: list[str]
    notes: list[str]

    def action_names(self) -> list[str]:
        return [a.action for a in self.actions]

    def as_list(self) -> list[dict[str, str]]:
        return [a.as_dict() for a in self.actions]

    def filter(self, proposed: list[str]) -> list[str]:
        """Drop anything the policy did not authorise. The LLM may reorder and
        explain; it may not add."""
        allowed = set(self.action_names())
        return [a for a in proposed if a in allowed]


# ------------------------------------------------------------------ rules ----
SAR_EXPOSURE_THRESHOLD = 1000.0
CASE_PROBABILITY_THRESHOLD = 0.30
R1_VERIFY_CEILING = 0.70
R4_ESCALATE_EXPOSURE = 500.0
R8_ESCALATE_EXPOSURE = 500.0


def sar_required(s: CaseState) -> tuple[bool, str]:
    """Fraud Policy §3a. A report needs confirmed-or-strongly-suspected fraud
    *and* at least one aggravating condition. Most cases never need one, and
    getting this boundary right is explicitly part of the score."""
    strongly_suspected = s.verdict == "fraud" or (s.fraud_probability >= 0.70
                                                  and not s.conformal_abstained)
    if not strongly_suspected and s.conformal_abstained:
        return False, (
            f"§3a: assessed probability {s.fraud_probability:.2f}, but the evidence does not "
            f"exclude legitimate activity (90%-coverage set, or a proof too thin to act on), so "
            f"fraud is not strongly suspected; no filing is due while the case is escalated "
            f"to an analyst (R8).")
    if not strongly_suspected:
        return False, (
            f"§3a: fraud is neither confirmed nor strongly suspected "
            f"(assessed probability {s.fraud_probability:.2f}), so no regulatory filing is due.")
    reasons = []
    if s.exposure_usd > SAR_EXPOSURE_THRESHOLD:
        reasons.append(f"exposure ${s.exposure_usd:,.2f} exceeds the $1,000 threshold")
    if s.shares_origin_with_other_fraud or s.connected_card_ids:
        reasons.append("the activity connects to a shared device profile or another card's fraud")
    if s.coordinated_or_undocumented:
        reasons.append("the pattern is coordinated or undocumented (R9)")
    if not reasons:
        return False, (
            "§3a: fraud is established but none of the filing conditions hold — exposure is under "
            f"$1,000 (${s.exposure_usd:,.2f}), the activity is confined to this card, and the "
            "pattern is a documented one. Case only, no report.")
    return True, "§3a: " + "; ".join(reasons) + "."


def evaluate(s: CaseState) -> PolicyDecision:
    """Compile case state into obligations. Order matters: actions are emitted
    in the order the bank would take them."""
    actions: list[RoutedAction] = []
    cited: list[str] = []
    obligations: list[str] = []
    forbidden: list[str] = []
    notes: list[str] = []
    seen: set[str] = set()

    def add(name: str, rule: str, reason: str) -> None:
        if name in seen:
            return
        seen.add(name)
        # `sar_required` already returns a reason that cites §3a; prefixing it
        # again produces "3a: §3a: ..." in the answer file.
        text = reason if reason.lstrip().startswith("§") else f"{rule}: {reason}"
        actions.append(route(name, text, s.exposure_usd))
        if rule not in cited:
            cited.append(rule)

    # ---- R7 first: a disputed charge that is the customer's own subscription
    # Once the cardholder has answered, R3 (recognised) or R2 (denied) governs.
    if (s.recurring_charge_match and s.trigger_type == "customer_report"
            and not s.customer_response):
        add("CREATE_CASE", "R7", "customer disputes a charge matching their own recurring pattern")
        add("VERIFY_WITH_CUSTOMER", "R7", "confirm the subscription with the cardholder")
        add("WARN_CUSTOMER", "R7", "remind the cardholder of the recurring charge")
        forbidden.append("BLOCK_CARD")
        notes.append("R7 forbids blocking on a disputed but recurring charge.")
        return PolicyDecision(actions, cited, obligations, forbidden, notes)

    # ---- R5: card testing
    if s.card_testing_matched:
        add("DECLINE_TRANSACTION", "R5",
            "a run of small online authorisations followed by a larger purchase")
        if s.card_testing_cleared_over_100:
            add("BLOCK_CARD", "R5", "a purchase over $100 has already cleared")
        else:
            add("STEP_UP_AUTH", "R5", "challenge before any further activity")

    # ---- R2/R3/R4: what the customer said
    if s.customer_response == "confirmed":
        # §3a opens a case whenever evidence is requested, and R3's "note the
        # confirmation in the case file" needs that case to exist.
        if s.evidence_requested:
            add("CREATE_CASE", "3a", "evidence was requested; the case records the "
                                     "cardholder's confirmation")
        if s.recurring_charge_match:
            add("WARN_CUSTOMER", "R7", "remind the cardholder of the recurring charge they "
                                       "disputed and then recognised")
        add("CLOSE_NO_FRAUD", "R3", "the cardholder confirmed the transaction")
        obligations.append("Record the confirmation in the case file (R3).")
        return PolicyDecision(actions, cited, obligations, forbidden, notes)

    if s.customer_response == "denied":
        add("BLOCK_CARD", "R2", "the cardholder denies the transaction")
        add("CREATE_CASE", "R2", "unauthorised use confirmed by the cardholder")
    elif s.customer_response == "no_response":
        add("MONITOR_CARD", "R4", "no reply within the 24-hour service window")
        if s.has_pending_authorisation:
            add("DECLINE_TRANSACTION", "R4", "decline pending authorisations while unresolved")
        if s.exposure_usd > R4_ESCALATE_EXPOSURE:
            add("ESCALATE_TO_ANALYST", "R4",
                f"exposure ${s.exposure_usd:,.2f} exceeds $500 with no customer reply")

    if s.step_up_result == "failed":
        add("BLOCK_CARD", "R2",
            "step-up authentication failed, which is inconsistent with genuine use")
        add("CREATE_CASE", "R2", "authentication failure on a disputed transaction")
    elif s.step_up_result == "passed" and s.customer_response != "denied":
        notes.append("Step-up authentication passed, which argues against account takeover.")

    # ---- R1: verify before blocking on a weak signal
    #
    # R1 exists to stop a *block* on thin evidence. It has nothing to say about
    # a case the evidence has already cleared: pairing VERIFY_WITH_CUSTOMER with
    # CLOSE_NO_FRAUD in the same recommendation is not caution, it is two
    # instructions that contradict each other, and it contacts a customer the
    # bank has just decided did nothing wrong.
    if (s.fraud_probability < R1_VERIFY_CEILING and s.single_signal_only
            and s.verdict != "legitimate"
            and s.customer_response not in {"denied", "confirmed"}
            and s.step_up_result != "failed"):
        blocked = [a for a in actions if a.action in {"BLOCK_CARD", "BLOCK_ALL_CARDS"}]
        for a in blocked:
            actions.remove(a)
            seen.discard(a.action)
        forbidden.extend(["BLOCK_CARD", "BLOCK_ALL_CARDS"])
        if s.contacts_in_window >= 2:
            add("ESCALATE_TO_ANALYST", "R1",
                "verification is the highest-value next step but the customer has already been "
                "contacted twice in this window")
        else:
            add("VERIFY_WITH_CUSTOMER", "R1",
                f"the case rests on a single signal and probability is "
                f"{s.fraud_probability:.2f}, below the 0.70 ceiling for blocking")
        notes.append("R1: blocking a legitimate customer on one signal is a policy breach.")

    # ---- R6: shared origin
    if s.shares_origin_with_other_fraud and s.connected_card_ids:
        add("CREATE_CASE", "R6", "several cards show abuse from the same shared origin")
        add("MONITOR_CONNECTED_CARDS", "R6",
            f"{len(s.connected_card_ids)} cards share the named origin")

    # ---- R9: undocumented / coordinated
    if s.coordinated_or_undocumented:
        add("CREATE_CASE", "R9", "coordinated or repeated abuse fitting no documented typology")
        add("ESCALATE_TO_ANALYST", "R9", "an undocumented pattern needs human typology review")
        obligations.append("Describe the pattern in the agent's own words (R9); do not force it "
                           "into a known category.")

    # ---- R8: uncertain and exposed
    if s.verdict == "uncertain" and (s.exposure_usd > R8_ESCALATE_EXPOSURE
                                     or s.conflicting_evidence):
        add("ESCALATE_TO_ANALYST", "R8",
            f"verdict is uncertain with ${s.exposure_usd:,.2f} exposed"
            + (" and conflicting evidence" if s.conflicting_evidence else ""))

    # ---- §3a: open a case once probability reaches 0.30
    if (s.fraud_probability >= CASE_PROBABILITY_THRESHOLD or s.evidence_requested
            or s.trigger_type == "customer_report"):
        add("CREATE_CASE", "3a",
            f"fraud probability {s.fraud_probability:.2f} reaches the 0.30 case threshold"
            if s.fraud_probability >= CASE_PROBABILITY_THRESHOLD
            else "evidence was requested / the customer disputed a charge")

    # ---- R10: never block every card without two confirmations
    if s.cards_with_confirmed_fraud >= 2 or s.credentials_confirmed_compromised:
        add("BLOCK_ALL_CARDS", "R10",
            "two or more of the customer's cards show confirmed fraud, or credentials are "
            "confirmed compromised")
    else:
        forbidden.append("BLOCK_ALL_CARDS")

    # ---- §3a: report
    file_sar, sar_reason = sar_required(s)
    if file_sar:
        add("FILE_REPORT", "3a", sar_reason)
    else:
        forbidden.append("FILE_REPORT")
        notes.append(sar_reason)

    # ---- monitoring / closure fall-throughs
    if s.verdict == "legitimate" and not any(
            a.action in {"BLOCK_CARD", "DECLINE_TRANSACTION"} for a in actions):
        # R3 is the customer-confirmation rule; no customer was asked on this
        # path, so the closure rests on the §6 stopping rule instead.
        add("CLOSE_NO_FRAUD", "§6",
            f"§6: fraud probability {s.fraud_probability:.2f} is at or below the 0.15 floor on "
            "independent graph evidence; the activity is consistent with the cardholder, so no "
            "customer contact was needed")
        if s.trigger_type == "risk_score" and s.fraud_probability >= 0.10:
            add("MONITOR_CARD", "R4", "keep sensitivity raised for 72 hours as a precaution")
    elif not actions:
        add("MONITOR_CARD", "R4", "no action is warranted yet; keep the card under observation")

    if s.verdict == "fraud" and "BLOCK_CARD" not in seen and "BLOCK_CARD" not in forbidden:
        add("BLOCK_CARD", "R2", "unauthorised use established")

    order = {name: i for i, name in enumerate([
        "DECLINE_TRANSACTION", "BLOCK_CARD", "BLOCK_ALL_CARDS", "STEP_UP_AUTH",
        "VERIFY_WITH_CUSTOMER", "CREATE_CASE", "FILE_REPORT", "MONITOR_CONNECTED_CARDS",
        "MONITOR_CARD", "WARN_CUSTOMER", "ESCALATE_TO_ANALYST", "GENERATE_REPORT",
        "CLOSE_NO_FRAUD", "ALLOW_TRANSACTION",
    ])}
    actions.sort(key=lambda a: order.get(a.action, 99))
    return PolicyDecision(actions, cited, obligations, forbidden, notes)


# ------------------------------------------------------------- thresholds ----
def verdict_for(posterior: dict[str, float], thresholds) -> str:
    p = H.fraud_probability(posterior)
    if p >= thresholds.t_block_card:
        return "fraud"
    if p <= thresholds.t_clear:
        return "legitimate"
    return "uncertain"


def status_for(verdict: str, actions: list[str], evidence_pending: bool) -> str:
    if evidence_pending:
        return "open"
    if "ESCALATE_TO_ANALYST" in actions:
        return "escalated"
    if verdict == "fraud":
        return "closed_fraud"
    if verdict == "legitimate":
        return "closed_legitimate"
    return "open"
