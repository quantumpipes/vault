"""Shared test fixtures for qp-vault."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def tmp_vault_path(tmp_path: Path) -> Path:
    """Fresh temporary directory for a vault."""
    vault_dir = tmp_path / "test-vault"
    vault_dir.mkdir()
    return vault_dir


@pytest.fixture
def sample_texts() -> list[str]:
    """Standard set of test documents."""
    return [
        "Standard operating procedure for incident response. When an incident "
        "is detected, the on-call engineer must acknowledge within 15 minutes. "
        "Severity is classified as P0 (critical), P1 (high), P2 (medium), or "
        "P3 (low). P0 incidents require immediate escalation to the incident "
        "commander.",
        "Draft proposal for new employee onboarding process. The current "
        "onboarding takes 3 weeks. We propose reducing to 2 weeks by "
        "parallelizing equipment setup and access provisioning. This requires "
        "IT and HR to coordinate on day-one readiness.",
        "Meeting notes from engineering standup 2026-03-15. Discussed: "
        "migration to new auth service is 80% complete. Blocker: legacy "
        "API clients need updated tokens. Action item: send deprecation "
        "notice by Friday.",
    ]
