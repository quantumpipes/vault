#!/usr/bin/env python3
# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0
"""Compute and commit the retrieval-eval baseline (askqp-100 I2).

Seeds a Postgres backend with the corpus (fixture embeddings) and records
recall@5/10 + MRR@10 for both the legacy blend and RRF into ``evals/baseline.json``.
The CI gate then asserts metrics stay at or above these numbers.

Run from repos/vault against an isolated pgvector DB:

    VAULT_TEST_POSTGRES_DSN=postgresql://... python scripts/gen_eval_baseline.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "evals"))

import eval_lib  # noqa: E402


async def _run() -> int:
    dsn = os.environ.get("VAULT_TEST_POSTGRES_DSN", "")
    if not dsn:
        print("VAULT_TEST_POSTGRES_DSN is required", file=sys.stderr)
        return 1
    dsn = dsn if "sslmode" in dsn else f"{dsn}?sslmode=disable"
    from qp_vault.storage.postgres import PostgresBackend

    fixtures = eval_lib.load_fixtures()
    modes = {}
    for name, rrf in (("legacy", False), ("rrf", True)):
        backend = PostgresBackend(dsn, ssl=False, rrf_enabled=rrf)
        await backend.initialize()
        await eval_lib.seed_backend(backend, fixtures)
        modes[name] = await eval_lib.evaluate(backend, fixtures)
        await backend.close()

    baseline = {
        "model": fixtures["meta"]["model"],
        "corpus_hash": fixtures["meta"]["corpus_hash"],
        "legacy": modes["legacy"],
        "rrf": modes["rrf"],
    }
    (_ROOT / "evals" / "baseline.json").write_text(json.dumps(baseline, indent=2) + "\n")
    print(json.dumps(baseline, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run()))
