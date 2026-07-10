#!/usr/bin/env python3
# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0
"""Author the retrieval-eval corpus + golden set (askqp-100 I2).

Writes ``corpus/*.md`` and ``golden.jsonl`` deterministically. The content is
synthetic operational documentation (no private data). Run from repos/vault:

    python evals/build_corpus.py
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent

# doc id -> markdown body. Distinctive vocabulary per topic so each golden
# question has an unambiguous target.
CORPUS: dict[str, str] = {
    "incident-response": (
        "# Incident Response\n\n"
        "When an incident is detected, the on-call engineer must acknowledge it "
        "within 15 minutes. Severity is classified as P0 (critical), P1 (high), "
        "P2 (medium), or P3 (low). A P0 incident requires immediate escalation to "
        "the incident commander and a status page update.\n"
    ),
    "onboarding": (
        "# Employee Onboarding\n\n"
        "Current onboarding takes three weeks. The goal is to reduce it to two "
        "weeks by parallelizing equipment setup and access provisioning. IT and HR "
        "coordinate to guarantee day-one readiness for every new hire.\n"
    ),
    "auth-migration": (
        "# Authentication Service Migration\n\n"
        "The migration to the new authentication service is under way. Legacy API "
        "clients must obtain updated tokens before the old endpoint is retired. A "
        "deprecation notice goes out to integrators one month ahead of cutover.\n"
    ),
    "backup-policy": (
        "# Backup Policy\n\n"
        "Full database backups run nightly at 02:00 UTC and are retained for 30 "
        "days. A monthly snapshot is archived to cold storage for one year. Restore "
        "drills are performed quarterly to prove the backups are usable.\n"
    ),
    "data-retention": (
        "# Data Retention\n\n"
        "Customer records are retained for seven years to meet financial reporting "
        "obligations. Application logs are kept for 90 days. Personally "
        "identifiable information is purged within 30 days of account deletion.\n"
    ),
    "api-rate-limits": (
        "# API Rate Limits\n\n"
        "Each API key is allowed 600 requests per minute, with a short burst "
        "allowance of 100. Exceeding the ceiling returns HTTP 429 with a "
        "Retry-After header indicating when to try again.\n"
    ),
    "encryption-standards": (
        "# Encryption Standards\n\n"
        "Data at rest is encrypted with AES-256-GCM. Data in transit uses TLS 1.3. "
        "Keys are rotated every quarter. Deprecated algorithms such as RSA-1024 and "
        "MD5 are prohibited across all services.\n"
    ),
    "kubernetes-deploy": (
        "# Kubernetes Deployment\n\n"
        "Services deploy with a rolling update strategy and readiness probes. Every "
        "workload runs a minimum of three replicas. Major releases use a blue-green "
        "cutover so traffic shifts only after the new version is healthy.\n"
    ),
    "postgres-tuning": (
        "# PostgreSQL Tuning\n\n"
        "Connection pooling is handled by pgbouncer in transaction mode. "
        "shared_buffers is set to roughly 25 percent of system memory. Autovacuum "
        "thresholds are lowered on high-write tables to avoid bloat.\n"
    ),
    "oncall-rotation": (
        "# On-Call Rotation\n\n"
        "The on-call rotation is weekly, with a primary and a secondary engineer. "
        "Handoff happens every Monday at 10:00. If the primary does not respond, the "
        "page escalates to the secondary automatically.\n"
    ),
    "code-review": (
        "# Code Review Policy\n\n"
        "Every pull request requires two approvals before merge. Self-merge is not "
        "allowed. Continuous integration must be green. Changes that touch "
        "authentication require an additional security review.\n"
    ),
    "release-process": (
        "# Release Process\n\n"
        "A production release requires two approvals and a green CI pipeline. During "
        "a code freeze before a major release, no new features may land: only "
        "critical bug fixes are permitted. Release notes are mandatory.\n"
    ),
}

# Golden retrieval set. relevant_resource_ids are doc ids that SHOULD be retrieved.
GOLDEN: list[dict] = [
    {"id": "q001", "question": "How long does the on-call engineer have to acknowledge an incident?",
     "relevant_resource_ids": ["incident-response"], "category": "lookup"},
    {"id": "q002", "question": "What is the goal for reducing new-hire onboarding time?",
     "relevant_resource_ids": ["onboarding"], "category": "lookup"},
    {"id": "q003", "question": "What does a P0 incident severity require?",
     "relevant_resource_ids": ["incident-response"], "category": "acronym"},
    {"id": "q004", "question": "Which two teams coordinate to make a new hire ready on day one?",
     "relevant_resource_ids": ["onboarding"], "category": "synthesis"},
    {"id": "q005", "question": "When are full database backups taken and how long are they kept?",
     "relevant_resource_ids": ["backup-policy"], "category": "lookup"},
    {"id": "q006", "question": "How many years are customer records kept?",
     "relevant_resource_ids": ["data-retention"], "category": "paraphrase"},
    {"id": "q007", "question": "What is the request ceiling per minute for an API key?",
     "relevant_resource_ids": ["api-rate-limits"], "category": "lookup"},
    {"id": "q008", "question": "Which algorithm encrypts data at rest?",
     "relevant_resource_ids": ["encryption-standards"], "category": "acronym"},
    {"id": "q009", "question": "How many approvals does a production release need?",
     "relevant_resource_ids": ["release-process", "code-review"], "category": "synthesis"},
    {"id": "q010", "question": "What is not permitted during a code freeze?",
     "relevant_resource_ids": ["release-process"], "category": "negation"},
]


def main() -> None:
    corpus_dir = _HERE / "corpus"
    corpus_dir.mkdir(exist_ok=True)
    for doc_id, body in sorted(CORPUS.items()):
        (corpus_dir / f"{doc_id}.md").write_text(body, encoding="utf-8")
    with (_HERE / "golden.jsonl").open("w", encoding="utf-8") as f:
        for row in GOLDEN:
            f.write(json.dumps({**row, "author": "bootstrap", "added": "2026-07-10"}) + "\n")
    print(f"wrote {len(CORPUS)} corpus docs + {len(GOLDEN)} golden questions")


if __name__ == "__main__":
    main()
