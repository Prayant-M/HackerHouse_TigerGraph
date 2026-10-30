"""Conformal abstention (Innovation 4).

"Uncertain" is chosen by a coverage guarantee, not a hand-picked threshold, and
it widens automatically when a case looks like nothing calibration has seen —
which is exactly the brief's warning about January.

* **Calibrate** (eval/conformal_calibrate.py) on replayed closed cases and
  matched controls. Nonconformity = 1 - p(true class), where p comes from the
  same pure decision core the agent uses (core/proof.decide). Label-conditional
  (Mondrian by class) so each class gets its own guarantee at alpha = 0.1.
* **Decide.** Prediction set = every class whose nonconformity is within its
  class quantile. {fraud, legit} or {} means the evidence does not separate the
  classes at 90% coverage: the case is uncertain.
* **Support check.** The flagged transaction's behaviour vector is compared with
  its k nearest calibration transactions; beyond the calibration 95th
  percentile the case is outside support and the set widens to both classes.
* **Taint** from core/quality.py widens the set too.

The set can only *widen* a fraud verdict to uncertain; it never narrows one
into a block, and a legitimate verdict (which cannot wrong anyone) is reported
but left alone. Solicited evidence (a customer confirming or denying) is outside what
calibration saw, so a settled case is reported but not overridden.

Caveat stated up front: the closed cases are a selected sample, so coverage
holds for "cases like the ones the bank investigated", not for all traffic.
"""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

import numpy as np

from ..config import PATHS

ALPHA = 0.10
K_NEIGHBOURS = 10


@lru_cache(maxsize=1)
def calibration() -> dict[str, Any] | None:
    p = PATHS.staged / "conformal.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _support_matrix() -> np.ndarray | None:
    p = PATHS.staged / "conformal_support.npy"
    return np.load(p) if p.exists() else None


def knn_distance(vec: np.ndarray, ref: np.ndarray, k: int = K_NEIGHBOURS,
                 exclude_self: bool = False) -> float:
    d = np.linalg.norm(ref - vec[None, :], axis=1)
    if exclude_self:
        d = d[d > 1e-9]
    k = min(k, len(d))
    return float(np.sort(d)[:k].mean()) if k else float("inf")


def prediction_set(p_fraud: float, cal: dict[str, Any]) -> list[str]:
    q = cal["quantiles"]
    out = []
    if 1.0 - p_fraud <= q["fraud"]:
        out.append("fraud")
    if p_fraud <= q["legit"]:              # 1 - p(legit) = p_fraud
        out.append("legit")
    return out


def assess(p_fraud: float, behaviour_vec: np.ndarray | None, tainted: bool,
           customer_settled: bool) -> dict[str, Any]:
    cal = calibration()
    if cal is None:
        return {"available": False,
                "note": "conformal calibration not built (eval/conformal_calibrate.py)"}
    base = prediction_set(p_fraud, cal)
    out: dict[str, Any] = {"available": True, "alpha": cal["alpha"],
                           "p_fraud_graph_only": round(p_fraud, 4),
                           "quantiles": cal["quantiles"], "base_set": base,
                           "calibrated_on": cal.get("calibrated_on"),
                           "widened_by": []}
    S = set(base)
    ref = _support_matrix()
    if behaviour_vec is not None and ref is not None:
        dist = knn_distance(np.asarray(behaviour_vec, dtype=float), ref)
        thr = float(cal["support_threshold"])
        out.update(support_distance=round(dist, 4), support_threshold=round(thr, 4),
                   outside_support=dist > thr)
        if dist > thr:
            S |= {"fraud", "legit"}
            out["widened_by"].append("outside_support")
    else:
        out.update(outside_support=None, support_note="no behaviour vector for the flagged txn")
    if tainted:
        S |= {"fraud", "legit"}
        out["widened_by"].append("data_quality_taint")
    final = sorted(S) if S else []
    out["set"] = final
    out["uncertain"] = len(final) != 1
    out["customer_settled"] = customer_settled
    out["applies"] = not customer_settled
    return out


def apply(verdict: str, conformal: dict[str, Any]) -> tuple[str, str]:
    """Widen-only: a fraud or legitimate verdict becomes uncertain when the set
    does not single out that class."""
    if not conformal.get("available") or not conformal.get("applies"):
        return verdict, ""
    S = set(conformal.get("set", []))
    # Only a fraud verdict can wrong a customer, so only a fraud verdict is
    # widened. A legitimate verdict outside support is reported, not changed:
    # turning it into "uncertain" would contact a customer for no gain.
    if verdict != "fraud" or S == {"fraud"}:
        return verdict, ""
    why = ("the prediction set is " + ("{" + ", ".join(sorted(S)) + "}" if S else "empty")
           + f" at {int(100 * (1 - conformal['alpha']))}% coverage"
           + (f" (widened by {', '.join(conformal['widened_by'])})"
              if conformal.get("widened_by") else ""))
    return "uncertain", why
