"""Provenance labels: free text can never become a decision input.

Every value that reaches the policy core is labelled by where it came from:
graph (a query result), extractor (an allow-listed fact from core/text_facts),
solicited (a customer / step-up / analyst reply), or LLM. Free text from a
customer or analyst enters the agent as `UntrustedText`, a `str` subclass that
carries its label with it through any assignment. `CaseState` (the only input
the policy core accepts) refuses to be constructed if any field, at any depth,
is untrusted text — so the claim "the decision cannot depend on the text" is a
runtime assertion, not a promise. The M2 fuzz in eval/metamorphic.py is the
empirical half of the same claim.
"""

from __future__ import annotations

from typing import Any


class ProvenanceError(TypeError):
    """A value whose provenance the decision core does not accept."""


class UntrustedText(str):
    """Customer- or analyst-written text. Data, never instruction."""

    provenance = "untrusted_text"


ACCEPTED = frozenset({"graph", "extractor", "solicited", "policy"})


def check(value: Any, where: str = "CaseState") -> None:
    if isinstance(value, UntrustedText):
        raise ProvenanceError(f"{where}: untrusted free text cannot be a decision input")
    if isinstance(value, dict):
        for k, v in value.items():
            check(k, where)
            check(v, f"{where}.{k}")
    elif isinstance(value, (list, tuple, set, frozenset)):
        for v in value:
            check(v, where)
