# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0
"""Shared retrieval-eval logic (askqp-100 I2).

Loads the committed fixtures, seeds a vault backend with the corpus, and scores
retrieval (recall@k, MRR@k) against the golden set. Used by both
``scripts/gen_eval_baseline.py`` and ``tests/test_eval_retrieval.py`` so the
baseline and the CI gate compute metrics identically.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

_EVALS = Path(__file__).resolve().parent


def load_fixtures() -> dict[str, Any]:
    """Load embeddings.npz + golden.jsonl + meta.json."""
    npz = np.load(_EVALS / "embeddings.npz", allow_pickle=False)
    golden = [
        json.loads(line)
        for line in (_EVALS / "golden.jsonl").read_text().splitlines()
        if line.strip()
    ]
    meta = json.loads((_EVALS / "meta.json").read_text())
    return {
        "doc_ids": [str(d) for d in npz["doc_ids"]],
        "doc_embeddings": npz["doc_embeddings"],
        "q_ids": [str(q) for q in npz["q_ids"]],
        "q_embeddings": npz["q_embeddings"],
        "golden": golden,
        "meta": meta,
    }


def _resource(rid: str) -> Any:
    from qp_vault.models import Resource

    return Resource(
        id=rid,
        name=f"{rid}.md",
        content_hash=f"h-{rid}",
        cid=f"vault://sha3-256/{rid}",
        trust_tier="working",
        data_classification="internal",
        resource_type="document",
        status="indexed",
        lifecycle="active",
        chunk_count=1,
        size_bytes=100,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _chunk(rid: str, content: str, embedding: list[float]) -> Any:
    from qp_vault.models import Chunk

    return Chunk(
        id=f"c-{rid}",
        resource_id=rid,
        content=content,
        cid=f"vault://sha3-256/c-{rid}",
        chunk_index=0,
        token_count=len(content.split()),
        embedding=embedding,
    )


async def seed_backend(backend: Any, fixtures: dict[str, Any]) -> None:
    """Store every corpus doc as a one-chunk resource with its fixture embedding."""
    corpus_dir = _EVALS / "corpus"
    pool = await backend._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qp_vault.chunks")
        await conn.execute("DELETE FROM qp_vault.provenance")
        await conn.execute("DELETE FROM qp_vault.collections")
        await conn.execute("DELETE FROM qp_vault.resources")
    for rid, vec in zip(fixtures["doc_ids"], fixtures["doc_embeddings"], strict=True):
        content = (corpus_dir / f"{rid}.md").read_text(encoding="utf-8")
        await backend.store_resource(_resource(rid))
        await backend.store_chunks(rid, [_chunk(rid, content, vec.tolist())])


async def _ranked_ids(backend: Any, q_vec: list[float], question: str, top_k: int) -> list[str]:
    from qp_vault.protocols import SearchQuery

    results = await backend.search(
        SearchQuery(query_embedding=q_vec, query_text=question, top_k=top_k)
    )
    seen: list[str] = []
    for r in results:
        if r.resource_id not in seen:
            seen.append(r.resource_id)
    return seen


async def evaluate(backend: Any, fixtures: dict[str, Any]) -> dict[str, float]:
    """Return overall recall@5, recall@10, MRR@10 for the seeded backend."""
    golden_by_id = {g["id"]: g for g in fixtures["golden"]}
    recall5: list[float] = []
    recall10: list[float] = []
    rr: list[float] = []
    for qid, q_vec in zip(fixtures["q_ids"], fixtures["q_embeddings"], strict=True):
        row = golden_by_id[qid]
        relevant = set(row["relevant_resource_ids"])
        ranked = await _ranked_ids(backend, q_vec.tolist(), row["question"], top_k=10)
        top5, top10 = set(ranked[:5]), set(ranked[:10])
        recall5.append(len(relevant & top5) / len(relevant))
        recall10.append(len(relevant & top10) / len(relevant))
        reciprocal = 0.0
        for i, rid in enumerate(ranked[:10]):
            if rid in relevant:
                reciprocal = 1.0 / (i + 1)
                break
        rr.append(reciprocal)
    n = len(fixtures["q_ids"])
    return {
        "recall@5": round(sum(recall5) / n, 6),
        "recall@10": round(sum(recall10) / n, 6),
        "mrr@10": round(sum(rr) / n, 6),
    }
