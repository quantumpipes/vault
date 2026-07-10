#!/usr/bin/env python3
# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0
"""Generate committed embedding fixtures for the retrieval eval (askqp-100 I2).

Reads ``evals/corpus/*.md`` + ``evals/golden.jsonl``, embeds each with a local
Ollama model (the sovereign default ``nomic-embed-text``), and writes
``evals/embeddings.npz`` + ``evals/meta.json``. Committing the embeddings lets
the CI eval gate run with NO model service (it never calls Ollama).

Run from repos/vault (needs Ollama on :11434):

    python scripts/gen_eval_embeddings.py [--model nomic-embed-text] [--force]

``--force`` overrides the recorded-model guard and rewrites meta.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[1]
_EVALS = _ROOT / "evals"
_OLLAMA = "http://localhost:11434/api/embeddings"


def _embed(text: str, model: str) -> list[float]:
    body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(_OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (localhost only)
        payload = json.loads(resp.read())
    emb = payload.get("embedding")
    if not emb:
        raise RuntimeError(f"no embedding returned for model {model!r}: {payload.get('error')}")
    return emb


def _corpus_hash(docs: dict[str, str]) -> str:
    joined = "\n".join(f"{k}\n{v}" for k, v in sorted(docs.items()))
    return hashlib.sha3_256(joined.encode("utf-8")).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    meta_path = _EVALS / "meta.json"
    if meta_path.exists() and not args.force:
        recorded = json.loads(meta_path.read_text()).get("model")
        if recorded and recorded != args.model:
            print(
                f"refusing: meta.json records model {recorded!r} but --model is "
                f"{args.model!r}. Re-run with --force to overwrite.",
                file=sys.stderr,
            )
            return 1

    docs = {p.stem: p.read_text(encoding="utf-8") for p in sorted((_EVALS / "corpus").glob("*.md"))}
    golden = [
        json.loads(line)
        for line in (_EVALS / "golden.jsonl").read_text().splitlines()
        if line.strip()
    ]
    if not docs or not golden:
        print("corpus or golden set is empty; run evals/build_corpus.py first", file=sys.stderr)
        return 1

    doc_ids = sorted(docs)
    doc_vecs = np.array([_embed(docs[d], args.model) for d in doc_ids], dtype=np.float32)
    q_ids = [row["id"] for row in golden]
    q_vecs = np.array([_embed(row["question"], args.model) for row in golden], dtype=np.float32)

    np.savez(
        _EVALS / "embeddings.npz",
        doc_ids=np.array(doc_ids),
        doc_embeddings=doc_vecs,
        q_ids=np.array(q_ids),
        q_embeddings=q_vecs,
    )
    meta_path.write_text(
        json.dumps(
            {
                "model": args.model,
                "dimension": int(doc_vecs.shape[1]),
                "corpus_hash": _corpus_hash(docs),
                "doc_count": len(doc_ids),
                "question_count": len(q_ids),
            },
            indent=2,
        )
        + "\n"
    )
    print(f"wrote embeddings.npz ({len(doc_ids)} docs, {len(q_ids)} questions, dim {doc_vecs.shape[1]})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
