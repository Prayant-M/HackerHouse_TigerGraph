"""Central configuration. Every tunable dial lives here and is env-overridable.

Nothing in this module imports an LLM client. `core/` depends on this file; it
must stay free of anything that can make a network call at import time.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:  # optional; the repo runs without it
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a convenience only
    pass


REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def _env_float(key: str, default: float) -> float:
    raw = _env(key)
    return float(raw) if raw else default


def _env_int(key: str, default: int) -> int:
    raw = _env(key)
    return int(raw) if raw else default


def _env_bool(key: str, default: bool) -> bool:
    raw = _env(key).lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _path(key: str, default: str) -> Path:
    raw = _env(key)
    p = Path(raw) if raw else (REPO_ROOT / default)
    return p if p.is_absolute() else (REPO_ROOT / p)


# ---------------------------------------------------------------- paths ----
@dataclass(frozen=True)
class Paths:
    repo: Path = REPO_ROOT
    raw: Path = field(default_factory=lambda: _path("DATA_RAW_DIR", "Datasets"))
    staged: Path = field(default_factory=lambda: _path("DATA_STAGED_DIR", "data/staged"))
    policy: Path = field(default_factory=lambda: _path("POLICY_DIR", "data/policy"))
    cases_out: Path = field(default_factory=lambda: _path("BENCHMARK_OUTPUT_DIR", "cases"))
    eval_out: Path = field(default_factory=lambda: _path("EVAL_OUTPUT_DIR", "eval/reports"))
    monitoring_out: Path = field(
        default_factory=lambda: _path("MONITORING_OUTPUT_DIR", "benchmark/autonomous")
    )
    cache: Path = field(default_factory=lambda: _path("LLM_CACHE_DIR", ".cache/llm"))

    # raw inputs
    @property
    def transactions_csv(self) -> Path:
        return self.raw / "transactions.csv"

    @property
    def identity_csv(self) -> Path:
        return self.raw / "identity.csv"

    @property
    def closed_cases_csv(self) -> Path:
        return self.raw / "closed_cases_history.csv"

    @property
    def case_pack_csv(self) -> Path:
        return self.raw / "case_pack.csv"

    @property
    def dataset_readme(self) -> Path:
        return self.raw / "README.md"

    # staged artefacts
    @property
    def tx_parquet(self) -> Path:
        return self.staged / "transactions.parquet"

    @property
    def identity_parquet(self) -> Path:
        return self.staged / "identity.parquet"

    @property
    def behaviour_parquet(self) -> Path:
        return self.staged / "behaviour_emb.parquet"

    @property
    def closed_cases_parquet(self) -> Path:
        return self.staged / "closed_cases.parquet"

    @property
    def card_profile_parquet(self) -> Path:
        return self.staged / "card_profiles.parquet"

    @property
    def device_index_parquet(self) -> Path:
        return self.staged / "device_index.parquet"

    @property
    def lr_table_json(self) -> Path:
        return self.staged / "likelihood_ratios.json"

    @property
    def memory_index_npz(self) -> Path:
        return self.staged / "case_memory.npz"

    @property
    def memory_meta_parquet(self) -> Path:
        return self.staged / "case_memory_meta.parquet"

    @property
    def doc_index_npz(self) -> Path:
        return self.staged / "doc_memory.npz"

    @property
    def doc_meta_parquet(self) -> Path:
        return self.staged / "doc_memory_meta.parquet"

    @property
    def agent_cases_jsonl(self) -> Path:
        return self.staged / "agent_written_cases.jsonl"

    def ensure(self) -> None:
        for p in (self.staged, self.policy, self.cases_out, self.eval_out, self.cache,
                  self.monitoring_out):
            p.mkdir(parents=True, exist_ok=True)


PATHS = Paths()


# ------------------------------------------------------------ tigergraph ----
@dataclass(frozen=True)
class TigerGraphConfig:
    host: str = field(default_factory=lambda: _env("TG_HOST"))
    graph: str = field(default_factory=lambda: _env("TG_GRAPH_NAME", "FraudGraph"))
    username: str = field(default_factory=lambda: _env("TG_USERNAME", "tigergraph"))
    password: str = field(default_factory=lambda: _env("TG_PASSWORD"))
    secret: str = field(default_factory=lambda: _env("TG_SECRET"))
    token: str = field(default_factory=lambda: _env("TG_TOKEN"))
    restpp_port: str = field(default_factory=lambda: _env("TG_RESTPP_PORT", "9000"))
    gsql_port: str = field(default_factory=lambda: _env("TG_GSQL_PORT", "14240"))
    version: str = field(default_factory=lambda: _env("TG_VERSION", "4.2.0"))
    # Route the agent's graph reads and writes through the TigerGraph MCP server
    # (tigergraph-mcp over stdio). Off, or if the server cannot start, the store
    # talks to TigerGraph directly with pyTigerGraph.
    via_mcp: bool = field(default_factory=lambda: _env_bool("TG_VIA_MCP", True))

    @property
    def configured(self) -> bool:
        return bool(self.host) and (bool(self.password) or bool(self.secret) or bool(self.token))


TG = TigerGraphConfig()


# -------------------------------------------------------------------- llm ----
@dataclass(frozen=True)
class LLMConfig:
    provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "anthropic").lower())
    model: str = field(default_factory=lambda: _env("LLM_MODEL", "claude-sonnet-5"))
    fallback_provider: str = field(default_factory=lambda: _env("LLM_FALLBACK_PROVIDER").lower())
    fallback_model: str = field(default_factory=lambda: _env("LLM_FALLBACK_MODEL"))
    temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0))
    max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 4096))
    cache_enabled: bool = field(default_factory=lambda: _env_bool("LLM_CACHE_ENABLED", True))
    anthropic_key: str = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    openai_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    google_key: str = field(default_factory=lambda: _env("GOOGLE_API_KEY"))

    @property
    def available(self) -> bool:
        return bool(
            {"anthropic": self.anthropic_key, "openai": self.openai_key,
             "google": self.google_key}.get(self.provider, "")
        )


LLM = LLMConfig()


# ------------------------------------------------------------- embeddings ----
@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = field(default_factory=lambda: _env("EMBEDDING_PROVIDER", "auto").lower())
    model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )
    dim: int = field(default_factory=lambda: _env_int("EMBEDDING_DIM", 384))


EMBED = EmbeddingConfig()


# ------------------------------------------------------------------ agent ----
@dataclass(frozen=True)
class AgentConfig:
    max_evidence_rounds: int = field(default_factory=lambda: _env_int("MAX_EVIDENCE_ROUNDS", 3))
    min_voi_per_unit_cost: float = field(
        default_factory=lambda: _env_float("MIN_VOI_PER_UNIT_COST", 0.010)
    )
    # Posterior thresholds. Sourced from the bank policy (README "Stopping").
    t_block_all: float = field(
        default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_BLOCK_ALL", 0.85)
    )
    t_block_card: float = field(
        default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_BLOCK_CARD", 0.70)
    )
    t_decline: float = field(
        default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_DECLINE", 0.55)
    )
    t_monitor: float = field(
        default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_MONITOR", 0.30)
    )
    t_clear: float = field(default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_CLEAR", 0.15))
    t_case_open: float = field(default_factory=lambda: _env_float("POSTERIOR_THRESHOLD_CASE", 0.30))
    separation_floor: float = field(
        default_factory=lambda: _env_float("HYPOTHESIS_SEPARATION_FLOOR", 0.15)
    )
    wall_clock_timeout_s: float = field(
        default_factory=lambda: _env_float("AGENT_WALL_CLOCK_TIMEOUT_S", 240.0)
    )
    token_budget: int = field(default_factory=lambda: _env_int("AGENT_TOKEN_BUDGET", 120000))
    use_llm: bool = field(default_factory=lambda: _env_bool("AGENT_USE_LLM", True))


AGENT = AgentConfig()


# ------------------------------------------------------------- simulation ----
@dataclass(frozen=True)
class SimulationConfig:
    seed: int = field(default_factory=lambda: _env_int("SIMULATION_SEED", 4471))
    simulate: bool = field(default_factory=lambda: _env_bool("SIMULATE_CUSTOMER_RESPONSES", True))
    no_response_rate: float = field(
        default_factory=lambda: _env_float("SIMULATED_NO_RESPONSE_RATE", 0.18)
    )
    # map    = assume the most likely response (deterministic, the default)
    # sample = draw from the predictive distribution, seeded per case
    mode: str = field(default_factory=lambda: _env("SIMULATION_MODE", "map").lower())


SIM = SimulationConfig()


# ---------------------------------------------------------------- backend ----
def graph_backend() -> str:
    """`tigergraph` when credentials are present, otherwise the local mirror.

    GRAPH_BACKEND=local|tigergraph|auto  (default auto)
    """
    choice = _env("GRAPH_BACKEND", "auto").lower()
    if choice in {"local", "tigergraph"}:
        return choice
    return "tigergraph" if TG.configured else "local"
