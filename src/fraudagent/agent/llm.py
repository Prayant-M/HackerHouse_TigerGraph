"""LLM access — reasoning, tool planning, synthesis and explanation only.

What the model is allowed to do here: plan which graph primitives to run,
synthesise evidence into readable prose, write the case summary and the SAR
narrative, and describe an undocumented pattern in its own words.

What it is never allowed to do: produce a probability, a likelihood ratio, an
approval route, an action, an exposure figure, or a transaction id. Those come
from `core/`, which cannot import this module. The model receives the decision
and phrases it; if it proposes an action anyway, `PolicyDecision.filter` drops
it before it can reach an answer file.

Everything degrades cleanly. With no API key the agent runs end to end on
deterministic templates — the verdicts, probabilities, actions and routes are
bit-identical, only the prose changes — so a judge can clone the repo and
reproduce the twenty answer files without buying anything.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from ..config import LLM, PATHS


@dataclass
class LLMUsage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def merge(self, other: "LLMUsage") -> None:
        self.calls += other.calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cached += other.cached
        self.errors.extend(other.errors)


class LLMClient:
    """Thin provider wrapper with an on-disk cache.

    The cache is keyed on the full prompt, so a re-run of the benchmark costs
    nothing and produces byte-identical prose. That matters more than it
    sounds: without it, "reproduce my results" is not a thing this repo can
    offer.
    """

    def __init__(self) -> None:
        self.cfg = LLM
        self.usage = LLMUsage()
        self._client: Any = None
        self._provider = LLM.provider
        self.available = LLM.available and os.environ.get("AGENT_USE_LLM", "1") != "0"
        PATHS.cache.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ cache ----
    def _cache_path(self, key: str):
        return PATHS.cache / f"{key}.json"

    @staticmethod
    def _key(system: str, prompt: str, model: str) -> str:
        blob = f"{model}\x00{system}\x00{prompt}".encode("utf-8")
        return hashlib.sha256(blob).hexdigest()[:40]

    # ----------------------------------------------------------- client ----
    def _ensure(self) -> Any:
        if self._client is not None:
            return self._client
        if self._provider == "anthropic":
            import anthropic

            self._client = anthropic.Anthropic(api_key=self.cfg.anthropic_key)
        elif self._provider == "openai":
            from openai import OpenAI

            self._client = OpenAI(api_key=self.cfg.openai_key)
        elif self._provider == "google":
            import google.generativeai as genai

            genai.configure(api_key=self.cfg.google_key)
            self._client = genai
        else:
            raise RuntimeError(f"unknown LLM_PROVIDER={self._provider!r}")
        return self._client

    # ------------------------------------------------------------- call ----
    def complete(self, system: str, prompt: str, max_tokens: int | None = None) -> str:
        """Return text, or "" when no model is configured. Never raises."""
        if not self.available:
            return ""
        model = self.cfg.model
        key = self._key(system, prompt, model)
        path = self._cache_path(key)
        if self.cfg.cache_enabled and path.exists():
            blob = json.loads(path.read_text(encoding="utf-8"))
            self.usage.calls += 1
            self.usage.cached += 1
            self.usage.input_tokens += int(blob.get("input_tokens", 0))
            self.usage.output_tokens += int(blob.get("output_tokens", 0))
            return blob["text"]

        try:
            text, in_tok, out_tok = self._invoke(system, prompt, max_tokens or
                                                 self.cfg.max_tokens)
        except Exception as exc:                      # pragma: no cover - network
            self.usage.errors.append(f"{self._provider}: {exc}")
            if self.cfg.fallback_provider and self._provider != self.cfg.fallback_provider:
                self._provider = self.cfg.fallback_provider
                self._client = None
                try:
                    text, in_tok, out_tok = self._invoke(
                        system, prompt, max_tokens or self.cfg.max_tokens)
                except Exception as exc2:
                    self.usage.errors.append(f"fallback: {exc2}")
                    return ""
            else:
                return ""

        self.usage.calls += 1
        self.usage.input_tokens += in_tok
        self.usage.output_tokens += out_tok
        if self.cfg.cache_enabled:
            path.write_text(json.dumps({"text": text, "input_tokens": in_tok,
                                        "output_tokens": out_tok,
                                        "model": model, "at": time.time()}),
                            encoding="utf-8")
        return text

    def _invoke(self, system: str, prompt: str, max_tokens: int) -> tuple[str, int, int]:
        client = self._ensure()
        if self._provider == "anthropic":
            resp = client.messages.create(
                model=self.cfg.model, max_tokens=max_tokens,
                temperature=self.cfg.temperature, system=system,
                messages=[{"role": "user", "content": prompt}])
            text = "".join(b.text for b in resp.content if b.type == "text")
            return text, resp.usage.input_tokens, resp.usage.output_tokens
        if self._provider == "openai":
            resp = client.chat.completions.create(
                model=self.cfg.model, max_tokens=max_tokens,
                temperature=self.cfg.temperature,
                messages=[{"role": "system", "content": system},
                          {"role": "user", "content": prompt}])
            u = resp.usage
            return resp.choices[0].message.content or "", u.prompt_tokens, u.completion_tokens
        model = self._ensure().GenerativeModel(self.cfg.model, system_instruction=system)
        resp = model.generate_content(prompt)
        meta = getattr(resp, "usage_metadata", None)
        return (resp.text,
                int(getattr(meta, "prompt_token_count", 0) or 0),
                int(getattr(meta, "candidates_token_count", 0) or 0))

    def complete_json(self, system: str, prompt: str,
                      max_tokens: int | None = None) -> dict[str, Any]:
        text = self.complete(system, prompt, max_tokens)
        if not text:
            return {}
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            return {}
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}


_SHARED: LLMClient | None = None


def get_llm() -> LLMClient:
    global _SHARED
    if _SHARED is None:
        _SHARED = LLMClient()
    return _SHARED
