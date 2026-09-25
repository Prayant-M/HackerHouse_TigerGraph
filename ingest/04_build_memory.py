"""Stage 4 — build the vector memory: closed-case narratives + policy corpus.

Two embedding spaces land here, both stored as TigerVector attributes when the
TigerGraph backend is live:

  ClosedCase.narrative_emb   semantic recall over 5,565 analyst narratives
  PolicyDoc.text_emb         policy clauses, typologies, regulatory references

A third, `Transaction.behaviour_emb`, is engineered rather than textual and is
produced by `02_behaviour_embeddings.py`.

Run:  python ingest/04_build_memory.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Windows consoles still default to cp1252, which cannot encode the arrows and
# box characters used below; without this a clean run dies on its own log line.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - non-reconfigurable stream
    pass


from fraudagent.config import EMBED, PATHS  # noqa: E402
from fraudagent.memory.embeddings import Embedder  # noqa: E402


def log(msg: str) -> None:
    print(f"[memory] {msg}", flush=True)


def case_document(row) -> str:
    """What we embed for a closed case: the narrative plus its structured facts,
    so retrieval keys on both prose and shape."""
    return (
        f"{row.analyst_notes} "
        f"outcome={row.outcome} pattern={row.pattern} "
        f"transactions={row.n_txns} exposure_usd={row.exposure_usd:.2f} "
        f"actions={'|'.join(row.action_list)} report_filed={row.report_filed}"
    )


def main() -> None:
    t0 = time.time()
    PATHS.ensure()

    cc = pd.read_parquet(PATHS.closed_cases_parquet)
    case_texts = [case_document(r) for r in cc.itertuples()]

    chunks_path = PATHS.policy / "chunks.jsonl"
    if not chunks_path.exists():
        raise FileNotFoundError("run ingest/03_extract_policy.py first")
    docs = [json.loads(line) for line in chunks_path.read_text(encoding="utf-8").splitlines()]
    doc_texts = [f"{d['section']} — {d['title']}. {d['text']}" for d in docs]

    log(f"fitting embedder provider={EMBED.provider} on "
        f"{len(case_texts)} narratives + {len(doc_texts)} doc chunks")
    emb = Embedder().fit(case_texts + doc_texts)
    log(f"embedding dim = {emb.dim}")

    case_vecs = emb.encode(case_texts)
    doc_vecs = emb.encode(doc_texts)

    np.savez_compressed(PATHS.memory_index_npz, vectors=case_vecs.astype(np.float32))
    cc[["case_id", "customer_id", "card_id", "outcome", "pattern", "exposure_usd",
        "n_txns", "report_filed"]].assign(
        opened_at=cc["opened_at"].astype(str)).to_parquet(PATHS.memory_meta_parquet, index=False)
    log(f"wrote {PATHS.memory_index_npz} {case_vecs.shape}")

    np.savez_compressed(PATHS.doc_index_npz, vectors=doc_vecs.astype(np.float32))
    pd.DataFrame(docs).to_parquet(PATHS.doc_meta_parquet, index=False)
    log(f"wrote {PATHS.doc_index_npz} {doc_vecs.shape}")

    emb.save(PATHS.staged / "embedder.pkl")
    log(f"wrote {PATHS.staged / 'embedder.pkl'} in {time.time()-t0:.1f}s")

    # sanity: a card-testing query should surface card-testing cases first
    from fraudagent.memory.embeddings import cosine_top_k
    q = emb.encode(["run of very small online authorizations followed by a larger purchase"])[0]
    idx, sims = cosine_top_k(q, case_vecs, 5)
    log("sanity recall for a card-testing query:")
    for i, s in zip(idx, sims):
        log(f"   {cc.iloc[int(i)].case_id}  {cc.iloc[int(i)].pattern:<28} sim={s:.3f}")


if __name__ == "__main__":
    main()
