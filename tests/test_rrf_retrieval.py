"""RRF hybrid-retrieval integration tests (askqp-100 I1).

Requires a PostgreSQL with pgvector + pg_trgm. Run with:

    VAULT_TEST_POSTGRES_DSN=postgresql://... pytest tests/test_rrf_retrieval.py

Skipped automatically when the DSN is unset (local dev / CI without Docker).

The corpus is designed so the linear blend and RRF disagree: doc A wins on the
vector arm alone (no query words), while doc C is a weaker vector match that also
matches the text. The linear blend (vector-weighted 0.7) ranks A first; RRF gives
the text-matcher C the fusion bonus and ranks it first.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest

DSN = os.environ.get("VAULT_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="VAULT_TEST_POSTGRES_DSN not set")

_DIM = 768


def _dsn() -> str:
    return DSN if "sslmode" in DSN else f"{DSN}?sslmode=disable"


def _vec(*head: float) -> list[float]:
    """A 768-dim embedding from the given leading components (rest zero)."""
    v = list(head) + [0.0] * (_DIM - len(head))
    return v[:_DIM]


def _resource(rid: str, trust_tier: str = "working"):
    from qp_vault.models import Resource

    return Resource(
        id=rid,
        name=f"{rid}.md",
        content_hash=f"h-{rid}",
        cid=f"vault://sha3-256/{rid}",
        trust_tier=trust_tier,
        data_classification="internal",
        resource_type="document",
        status="indexed",
        lifecycle="active",
        chunk_count=1,
        size_bytes=100,
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )


def _chunk(rid: str, content: str, embedding: list[float]):
    from qp_vault.models import Chunk

    return Chunk(
        id=f"c-{rid}",
        resource_id=rid,
        content=content,
        cid=f"vault://sha3-256/c-{rid}",
        chunk_index=0,
        token_count=10,
        embedding=embedding,
    )


# (resource_id, trust_tier, content, embedding). query = [1, 0, 0, ...].
_CORPUS = [
    # Best vector match, but zero query-text overlap.
    ("A", "canonical", "tungsten carbide alloy metallurgy furnace", _vec(1.0)),
    # Weaker vector match, strong text match (repeated terms -> higher ts_rank).
    ("C", "working", "banana split banana split dessert sundae", _vec(0.5, 0.8660254)),
    # Worst vector match, weaker text match (matches once amid filler).
    ("B", "working", "banana split among many other unrelated filler words here", _vec(0.0, 1.0)),
]


async def _make_backend(rrf: bool):
    from qp_vault.storage.postgres import PostgresBackend

    b = PostgresBackend(_dsn(), ssl=False, rrf_enabled=rrf)
    await b.initialize()
    pool = await b._get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM qp_vault.chunks")
        await conn.execute("DELETE FROM qp_vault.provenance")
        await conn.execute("DELETE FROM qp_vault.collections")
        await conn.execute("DELETE FROM qp_vault.resources")
    for rid, tier, content, emb in _CORPUS:
        await b.store_resource(_resource(rid, tier))
        await b.store_chunks(rid, [_chunk(rid, content, emb)])
    return b


def _query(**overrides):
    from qp_vault.protocols import SearchQuery

    base = {
        "query_embedding": _vec(1.0),
        "query_text": "banana split",
        "top_k": 10,
        "threshold": 0.0,
    }
    base.update(overrides)
    return SearchQuery(**base)


@pytest.mark.asyncio
async def test_flag_off_is_linear_and_vector_dominated():
    b = await _make_backend(rrf=False)
    try:
        results = await b.search(_query())
        assert results, "expected results"
        # Linear blend (0.7 vector) ranks the pure-vector doc A first.
        assert results[0].resource_id == "A"
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_rrf_promotes_the_text_match():
    b = await _make_backend(rrf=True)
    try:
        results = await b.search(_query())
        assert results, "expected results"
        # RRF gives text-matchers the fusion bonus: C (best-ranked text matcher)
        # rises to the top, and the pure-vector doc A is no longer first.
        assert results[0].resource_id == "C"
        assert results[0].resource_id != "A"
        ranked = [r.resource_id for r in results]
        assert ranked.index("C") < ranked.index("A")
        assert ranked.index("B") < ranked.index("A")
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_rrf_populates_generated_fts_column():
    b = await _make_backend(rrf=True)
    try:
        pool = await b._get_pool()
        async with pool.acquire() as conn:
            missing = await conn.fetchval(
                "SELECT count(*) FROM qp_vault.chunks WHERE content_fts IS NULL"
            )
        assert missing == 0
    finally:
        await b.close()


@pytest.mark.asyncio
async def test_trust_tier_filter_applies_in_both_modes():
    from qp_vault.protocols import ResourceFilter

    for rrf in (False, True):
        b = await _make_backend(rrf=rrf)
        try:
            results = await b.search(
                _query(filters=ResourceFilter(trust_tier="canonical"))
            )
            ids = {r.resource_id for r in results}
            assert ids == {"A"}, f"rrf={rrf}: expected only canonical doc A, got {ids}"
        finally:
            await b.close()


@pytest.mark.asyncio
async def test_flag_off_ordering_is_stable_snapshot():
    """Flag off must be today's behavior exactly (regression snapshot)."""
    b = await _make_backend(rrf=False)
    try:
        results = await b.search(_query())
        assert [r.resource_id for r in results] == ["A", "C", "B"]
    finally:
        await b.close()
