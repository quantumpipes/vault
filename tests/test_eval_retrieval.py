"""Golden-set retrieval eval gate (askqp-100 I2).

Requires PostgreSQL with pgvector + pg_trgm. Runs on committed embedding
fixtures, so it never calls a model service. Run with:

    VAULT_TEST_POSTGRES_DSN=postgresql://... pytest tests/test_eval_retrieval.py

Skipped when the DSN is unset (CI/dev without Docker).

Gates recall@5/10 + MRR@10 for BOTH the legacy blend and RRF against the
committed baseline, proves RRF meets or beats legacy (the default-flip
criterion), and includes a degradation guard so a broken harness cannot pass.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "evals"))

import eval_lib  # noqa: E402

DSN = os.environ.get("VAULT_TEST_POSTGRES_DSN", "")
pytestmark = pytest.mark.skipif(not DSN, reason="VAULT_TEST_POSTGRES_DSN not set")

_TOLERANCE = 0.02
_BASELINE = json.loads((_ROOT / "evals" / "baseline.json").read_text())


def _dsn() -> str:
    return DSN if "sslmode" in DSN else f"{DSN}?sslmode=disable"


async def _backend(rrf: bool):
    from qp_vault.storage.postgres import PostgresBackend

    b = PostgresBackend(_dsn(), ssl=False, rrf_enabled=rrf)
    await b.initialize()
    return b


def test_corpus_hash_matches_baseline():
    """A silent corpus edit must fail loudly with a regenerate hint."""
    fixtures = eval_lib.load_fixtures()
    assert fixtures["meta"]["corpus_hash"] == _BASELINE["corpus_hash"], (
        "corpus_hash changed: regenerate fixtures (evals/build_corpus.py + "
        "scripts/gen_eval_embeddings.py) and the baseline (scripts/gen_eval_baseline.py)."
    )


@pytest.mark.asyncio
async def test_legacy_meets_baseline():
    fixtures = eval_lib.load_fixtures()
    b = await _backend(rrf=False)
    try:
        await eval_lib.seed_backend(b, fixtures)
        metrics = await eval_lib.evaluate(b, fixtures)
    finally:
        await b.close()
    for key, floor in _BASELINE["legacy"].items():
        assert metrics[key] >= floor - _TOLERANCE, f"legacy {key}: {metrics[key]} < {floor - _TOLERANCE}"


@pytest.mark.asyncio
async def test_rrf_meets_baseline():
    fixtures = eval_lib.load_fixtures()
    b = await _backend(rrf=True)
    try:
        await eval_lib.seed_backend(b, fixtures)
        metrics = await eval_lib.evaluate(b, fixtures)
    finally:
        await b.close()
    for key, floor in _BASELINE["rrf"].items():
        assert metrics[key] >= floor - _TOLERANCE, f"rrf {key}: {metrics[key]} < {floor - _TOLERANCE}"


@pytest.mark.asyncio
async def test_rrf_at_least_matches_legacy():
    """The RRF default-flip criterion: RRF recall@10 >= legacy recall@10."""
    fixtures = eval_lib.load_fixtures()
    legacy = await _backend(rrf=False)
    rrf = await _backend(rrf=True)
    try:
        await eval_lib.seed_backend(legacy, fixtures)
        legacy_m = await eval_lib.evaluate(legacy, fixtures)
        await eval_lib.seed_backend(rrf, fixtures)
        rrf_m = await eval_lib.evaluate(rrf, fixtures)
    finally:
        await legacy.close()
        await rrf.close()
    assert rrf_m["recall@10"] >= legacy_m["recall@10"] - _TOLERANCE


@pytest.mark.asyncio
async def test_deterministic_across_runs():
    fixtures = eval_lib.load_fixtures()
    b = await _backend(rrf=True)
    try:
        await eval_lib.seed_backend(b, fixtures)
        first = await eval_lib.evaluate(b, fixtures)
        second = await eval_lib.evaluate(b, fixtures)
    finally:
        await b.close()
    assert first == second


@pytest.mark.asyncio
async def test_degradation_guard_detects_damage():
    """Damaged queries (random vectors, blank text) must score far below baseline.

    Proves the harness measures real retrieval quality: a harness that always
    passed would not detect this.
    """
    fixtures = eval_lib.load_fixtures()
    rng = np.random.default_rng(0)
    damaged = dict(fixtures)
    damaged["q_embeddings"] = rng.standard_normal(fixtures["q_embeddings"].shape).astype(np.float32)
    damaged["golden"] = [{**g, "question": ""} for g in fixtures["golden"]]

    b = await _backend(rrf=False)
    try:
        await eval_lib.seed_backend(b, fixtures)
        metrics = await eval_lib.evaluate(b, damaged)
    finally:
        await b.close()
    # recall@5 (5 of 12 docs) collapses under random ranking with no text signal.
    assert metrics["recall@5"] < _BASELINE["legacy"]["recall@5"] - 0.1
