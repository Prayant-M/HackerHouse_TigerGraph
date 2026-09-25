"""Prose: case summaries, SAR narratives, pattern descriptions, explanations.

This is the one place the LLM writes anything, and it writes from a structured
brief that already contains every number. The model is explicitly told not to
invent identifiers or figures, and the templates below produce the same
document without it — so the deterministic path is not a degraded mode, it is
the reference the LLM output is checked against.

The SAR narrative follows FinCEN's who / what / when / where / how / why
structure, because that is what the regulator reads and what the dataset asks
for: a filing that stands on its own.
"""

from __future__ import annotations

import json
from typing import Any

from ..agent.llm import LLMClient
from ..core import hypotheses as H
from ..core.episode import Episode
from ..core.signals import InvestigationContext

SYSTEM = (
    "You are a fraud investigator at a card issuer, writing the internal record and the "
    "regulatory filing for an investigation that has already been decided.\n\n"
    "Absolute constraints:\n"
    "- Every figure, identifier, date and probability you use MUST be copied from the brief. "
    "Invent nothing. If a number is not in the brief, do not state it.\n"
    "- Do not recommend actions, assign approval routes, or state a probability the brief "
    "does not give you. Those are already decided by policy.\n"
    "- Write plainly. No marketing language, no hedging filler, no bullet lists unless asked.\n"
    "- Be specific about what the evidence is and what it is not. Say what remains uncertain."
)


def _brief(ctx: InvestigationContext, pattern: str, verdict: str, p_fraud: float,
           episode: Episode, evidence: list[dict[str, Any]], priors: list[Any],
           actions: dict[str, list[dict[str, str]]], what_changed: str,
           stop_reason: str) -> str:
    f = ctx.flagged
    return json.dumps({
        "case_id": ctx.case_id,
        "trigger": {"type": ctx.trigger_type, "as_of": str(ctx.as_of)},
        "flagged_transaction": {
            "txn_id": f.txn_id, "ts": str(f.ts), "amount_usd": round(f.amount, 2),
            "channel": f.channel, "product_cd": f.product_cd,
            "billing_region": f.region, "device_profile": f.device_profile,
            "device_status": f.device_status, "proxy": f.proxy,
            "model_risk_score": f.risk_score,
        },
        "customer_id": f.customer_id, "card_id": ctx.card_id_safe(),
        "card_baseline": {
            "prior_transactions": ctx.baseline.get("n_txns"),
            "median_amount_usd": ctx.baseline.get("amt_median"),
            "p95_amount_usd": ctx.baseline.get("amt_p95"),
            "home_region": ctx.baseline.get("home_region"),
            "online_share": ctx.baseline.get("online_share"),
        },
        "verdict": verdict, "pattern": pattern,
        "pattern_label": H.LABELS.get(pattern, pattern),
        "fraud_probability": round(p_fraud, 2),
        "episode": episode.as_dict(),
        "activity_dates": episode.activity_dates,
        "evidence": evidence,
        "prior_cases": [
            {"case_id": p.case_id, "outcome": p.outcome, "pattern": p.pattern,
             "similarity": p.similarity, "shared_entities": p.shared_entities}
            for p in priors],
        "recommended_actions": actions,
        "what_changed_after_evidence": what_changed,
        "stop_reason": stop_reason,
    }, indent=2, default=str)


# ----------------------------------------------------------------- summary --
def case_summary(llm: LLMClient, ctx: InvestigationContext, pattern: str, verdict: str,
                 p_fraud: float, episode: Episode, evidence: list[dict[str, Any]],
                 priors: list[Any], actions: dict[str, list[dict[str, str]]],
                 what_changed: str, stop_reason: str) -> str:
    brief = _brief(ctx, pattern, verdict, p_fraud, episode, evidence, priors,
                   actions, what_changed, stop_reason)
    text = llm.complete(
        SYSTEM,
        "Write the `summary` field of this fraud case: two to six sentences an analyst can "
        "read in ten seconds and act on. Say what happened, what the evidence rests on, what "
        "the conclusion is, and what is still uncertain. Do not list the actions — they are "
        "recorded separately. Plain prose, no heading, no bullet points.\n\n" + brief,
        max_tokens=600)
    return text.strip() or template_summary(ctx, pattern, verdict, p_fraud, episode,
                                            evidence, priors)


def template_summary(ctx: InvestigationContext, pattern: str, verdict: str,
                     p_fraud: float, episode: Episode, evidence: list[dict[str, Any]],
                     priors: list[Any]) -> str:
    f = ctx.flagged
    trigger = {
        "risk_score": f"The bank's model scored transaction {f.txn_id} at {f.risk_score:.2f}",
        "customer_report": f"Cardholder {f.customer_id} disputed transaction {f.txn_id}",
        "analyst_request": f"An analyst asked for a review of transaction {f.txn_id}",
    }.get(ctx.trigger_type, f"Transaction {f.txn_id} was flagged")

    parts = [
        f"{trigger} (${f.amount:,.2f}, {f.channel.replace('_', ' ')}"
        + (f", billing region {f.region}" if f.region else "") + ")."
    ]
    top = [e["claim"] for e in evidence[:3]]
    if top:
        parts.append("The investigation found: " + "; ".join(t[0].lower() + t[1:] for t in top)
                     + ".")
    if verdict == "legitimate":
        parts.append(
            f"On the evidence this is genuine cardholder activity — assessed fraud "
            f"probability {p_fraud:.2f} — so no transactions are treated as compromised and "
            f"exposure is zero.")
    elif verdict == "fraud":
        parts.append(
            f"The activity is assessed as {H.SHORT_LABELS.get(pattern, pattern)} at "
            f"probability {p_fraud:.2f}, covering {len(episode.affected_txn_ids)} "
            f"transaction(s) worth ${episode.exposure_usd:,.2f}.")
    else:
        parts.append(
            f"The evidence is genuinely ambiguous — fraud probability {p_fraud:.2f} — and "
            f"neither clearing nor blocking is defensible on what is known.")
    if episode.connected_card_ids:
        parts.append(f"{len(episode.connected_card_ids)} other card(s) share the same origin "
                     f"and are drawn into the same compromise.")
    if priors:
        p = priors[0]
        parts.append(f"Closed case {p.case_id} ({p.outcome.replace('_', ' ')}, "
                     f"{p.pattern.replace('_', ' ')}) is the closest prior investigation.")
    return " ".join(parts)


# --------------------------------------------------------------------- SAR --
def sar_narrative(llm: LLMClient, ctx: InvestigationContext, pattern: str, p_fraud: float,
                  episode: Episode, evidence: list[dict[str, Any]], priors: list[Any],
                  reason: str) -> str:
    brief = _brief(ctx, pattern, "fraud", p_fraud, episode, evidence, priors,
                   {}, "", "")
    text = llm.complete(
        SYSTEM,
        "Write the narrative of a Suspicious Activity Report for this case, following FinCEN "
        "narrative guidance. Six to twelve sentences, continuous prose, no headings and no "
        "bullets. It must stand entirely on its own to a regulator who has seen nothing else, "
        "and it must cover, in this order: WHO (customer, cards, devices), WHAT happened, "
        "WHEN (dates and times from the brief), WHERE (billing regions and channels), HOW the "
        "activity was carried out, and WHY it is suspicious. Name the total amount. Use only "
        "identifiers and figures present in the brief.\n\n"
        f"Filing reason: {reason}\n\n" + brief,
        max_tokens=900)
    return text.strip() or template_sar(ctx, pattern, p_fraud, episode, evidence, priors)


def template_sar(ctx: InvestigationContext, pattern: str, p_fraud: float,
                 episode: Episode, evidence: list[dict[str, Any]],
                 priors: list[Any]) -> str:
    f = ctx.flagged
    dates = episode.activity_dates or [f.ts.strftime("%Y-%m-%d")] * 2
    n = len(episode.affected_txn_ids)
    channels = "online" if f.channel == "online" else "card-present"
    s = [
        f"Customer {f.customer_id}, holder of card {ctx.card_id_safe()}, is the subject of "
        f"this report.",
        f"Between {dates[0]} and {dates[-1]}, {n} transaction(s) totalling "
        f"${episode.exposure_usd:,.2f} were identified as unauthorised on that card, the "
        f"earliest being transaction {episode.first_suspicious_txn_id} and the transaction "
        f"that triggered review being {f.txn_id} for ${f.amount:,.2f}.",
        f"The activity was conducted through the {channels} channel"
        + (f" in billing region {f.region}" if f.region else "") + ".",
    ]
    if f.device_profile:
        s.append(
            f"The transactions originated from device profile '{f.device_profile}'"
            + (f", which the issuer's identity record marks '{f.device_status}' for this "
               f"account" if f.device_status else "")
            + (f", reached through an {f.proxy.split(':')[-1].lower()} proxy" if f.proxy else "")
            + ".")
    mech = {
        H.CARD_TESTING: "The sequence — several very small online authorisations followed by a "
                        "materially larger purchase — is consistent with a stolen card number "
                        "being validated before use.",
        H.CNP: "The purchases are inconsistent with the cardholder's established merchants and "
               "amounts and were made without the physical instrument.",
        H.CNP_NEW_DEVICE: "The purchases were made without the physical card, from a device "
                          "with no prior history on the account.",
        H.OUT_OF_REGION: "Card-present purchases were made in a billing region in which the "
                         "cardholder has no history, while their ordinary activity continued "
                         "elsewhere, indicating the instrument was cloned rather than "
                         "travelling.",
        H.ATO: "Activity mixed channels in a way inconsistent with the cardholder's own "
               "pattern and coincided with device and identity match-flag anomalies, "
               "indicating compromised credentials rather than a stolen card number.",
        H.UNDOCUMENTED: "The activity matches no documented typology in the issuer's manual "
                        "and is described in the accompanying case record.",
    }.get(pattern, "")
    if mech:
        s.append(mech)
    if episode.connected_card_ids:
        s.append(
            f"The same origin appears on {len(episode.connected_card_ids)} other card(s) "
            f"belonging to unrelated customers within the same window, including "
            f"{', '.join(episode.connected_card_ids[:5])}, indicating a common actor across "
            f"multiple cardholders rather than an isolated compromise.")
    if priors:
        s.append(f"Closed investigation {priors[0].case_id} recorded "
                 f"{priors[0].outcome.replace('_', ' ')} on comparable activity.")
    s.append(f"The issuer assesses the probability of fraud at {p_fraud:.2f} on the evidence "
             f"set out above. Total suspicious amount: ${episode.exposure_usd:,.2f}.")
    return " ".join(s)


# ------------------------------------------------------- undocumented text --
def pattern_description(llm: LLMClient, ctx: InvestigationContext,
                        sub_typology: str, probe: dict[str, Any]) -> str:
    sub = H.SUB_TYPOLOGIES.get(sub_typology)
    if sub is None:
        return ""
    text = llm.complete(
        SYSTEM,
        "This activity matches none of the five documented fraud patterns. Describe the "
        "pattern you found in two or three sentences: what it is, who it affects, and how it "
        "was found. Use the measured figures given. Do not name it as one of the documented "
        "typologies.\n\n"
        f"Working name: {sub.name}\n"
        f"What the closed cases show: {sub.description}\n"
        f"Seed cases: {', '.join(sub.seed_cases)}\n"
        f"Measured on this case: {json.dumps(probe, default=str)}\n",
        max_tokens=400)
    if text.strip():
        return text.strip()
    if sub_typology == "threshold_structuring":
        return (
            f"{probe.get('n_txns', 0)} online purchases were made on this card inside "
            f"{probe.get('window_minutes', 0)} minutes, each amount parked just beneath the "
            f"${probe.get('threshold_usd', 500):,.0f} authorisation ceiling (mean headroom "
            f"{probe.get('headroom_pct', 0)}%), totalling ${probe.get('total_usd', 0):,.2f}. "
            f"The shape defeats per-transaction review because every individual leg looks "
            f"ordinary; only the burst as a whole is anomalous. It was found by scanning the "
            f"card's recent online activity for clusters concentrated immediately below round "
            f"authorisation thresholds, and matches five confirmed-fraud closed cases "
            f"({', '.join(sub.seed_cases)}) that the bank's own analysts could not fit to a "
            f"documented typology.")
    return (
        f"A single device profile — {ctx.flagged.device_profile} — reached through an "
        f"anonymising proxy appears across {probe.get('n_cards_anon_proxy', 0)} unrelated "
        f"cardholders inside thirty days, marked new on each account it touches. No individual "
        f"account shows a documented typology; the abuse is only visible as a hub in the "
        f"card-device projection, which is why it has to be found by traversal rather than by "
        f"scoring. It matches four confirmed-fraud closed cases "
        f"({', '.join(sub.seed_cases)}) recorded as undocumented.")


# ------------------------------------------------------------ explanation --
def explanation(llm: LLMClient, ctx: InvestigationContext, p_fraud: float,
                evidence: list[dict[str, Any]], requested: list[dict[str, Any]],
                actions: dict[str, list[dict[str, str]]], stop_reason: str,
                remaining: str, counterfactual: str) -> dict[str, str]:
    """Policy §7: what evidence was used, why more was requested, why these
    actions, and what would change the answer."""
    used = "; ".join(e["claim"] for e in evidence[:6]) or "no corroborating graph evidence"
    if requested:
        r = requested[0]
        why_more = (
            f"Belief sat at a level that supported no defensible action on its own, and "
            f"{r.get('name', r.get('type'))} carried the highest expected information per unit "
            f"of customer friction "
            f"({r.get('expected_info_gain', 0):.3f} nats at cost {r.get('cost', 0):.0f}), "
            f"so it was requested before any blocking action was recommended, as policy R1 "
            f"requires.")
    else:
        why_more = ("No further evidence was requested: nothing available would have moved the "
                    "decision enough to justify the friction of asking.")
    why_actions = "; ".join(
        f"{a['action']} ({a['route']}) — {a['reason']}"
        for a in actions.get("final", []) or actions.get("initial", []))
    return {
        "evidence_used": used,
        "why_more_evidence_was_requested": why_more,
        "why_these_actions": why_actions,
        "remaining_uncertainty": remaining,
        "counterfactual": counterfactual,
        "stop_reason": stop_reason,
    }
