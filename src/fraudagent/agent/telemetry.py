"""Run telemetry, redaction and the egress log.

* **Per case:** wall time, tokens, model cost estimate, graph tool calls,
  retries, LLM template fallbacks, written to `logs/run.jsonl` and
  `eval/reports/run_summary.csv`.
* **Redaction:** every log line passes through `redact()`, which removes the
  values of secrets present in the environment (keys, passwords, tokens, the
  approval signing key) and masks raw personal fields (email addresses,
  phone-like numbers). Pseudonymous ids (C01234-K1) stay: they are what makes a
  log line attestable.
* **Egress:** every call that leaves the bank boundary — the LLM provider and
  the TigerGraph workspace — is appended to `logs/egress.jsonl` with what kind
  of data it carried. Embeddings are computed locally and never leave.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from ..config import PATHS

LOGS = Path(os.environ.get("LOGS_DIR", "") or PATHS.repo / "logs")
_lock = threading.Lock()
_SECRET_KEYS = ("KEY", "PASSWORD", "SECRET", "TOKEN")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")

# Rough public list prices per million tokens, for the cost-per-case estimate.
PRICE_PER_MTOK = {"input": 3.0, "output": 15.0}


def _secrets() -> list[str]:
    vals = []
    for k, v in os.environ.items():
        if any(s in k.upper() for s in _SECRET_KEYS) and v and len(v) >= 6 \
                and k.upper() not in {"AGENT_TOKEN_BUDGET", "LLM_MAX_TOKENS"}:
            vals.append(v)
    return sorted(set(vals), key=len, reverse=True)


def redact(text: str) -> str:
    out = str(text)
    for v in _secrets():
        out = out.replace(v, "[REDACTED]")
    out = _EMAIL.sub("[EMAIL]", out)
    out = _PHONE.sub(lambda m: m.group(0) if m.group(0).replace(" ", "").isdigit()
                     and len(m.group(0)) <= 12 else "[PHONE]", out)
    return out


def _write(name: str, rec: dict[str, Any]) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    line = redact(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **rec},
                             default=str))
    with _lock, (LOGS / name).open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def egress(rec: dict[str, Any]) -> None:
    _write("egress.jsonl", rec)


def log_run(rec: dict[str, Any]) -> None:
    _write("run.jsonl", rec)


def cost_usd(input_tokens: int, output_tokens: int, cached_calls: int = 0) -> float:
    return round(input_tokens / 1e6 * PRICE_PER_MTOK["input"]
                 + output_tokens / 1e6 * PRICE_PER_MTOK["output"], 5)


def p95(values: list[float]) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    i = max(0, min(len(v) - 1, int(round(0.95 * (len(v) - 1)))))
    return round(v[i], 3)
