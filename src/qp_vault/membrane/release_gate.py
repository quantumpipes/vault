# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Release gate: risk-proportionate gating before indexing.

Evaluates Membrane stage results and decides whether content should be:
- RELEASED (indexed normally)
- HELD (quarantined for human review)
- REJECTED (blocked from indexing)
"""

from __future__ import annotations

from qp_vault.enums import MembraneResult, MembraneStage
from qp_vault.models import MembraneStageRecord


async def evaluate_release(
    stage_records: list[MembraneStageRecord],
) -> MembraneStageRecord:
    """Evaluate whether content should be released for indexing.

    Decision logic:
    - If any stage FAIL'd: FAIL (reject)
    - If any stage FLAG'd: FLAG (quarantine for review)
    - Otherwise: PASS (release)

    Args:
        stage_records: Results from previous Membrane stages.

    Returns:
        MembraneStageRecord for the RELEASE stage.
    """
    has_fail = any(r.result == MembraneResult.FAIL for r in stage_records)
    has_flag = any(r.result == MembraneResult.FLAG for r in stage_records)

    if has_fail:
        failed = [r.stage.value for r in stage_records if r.result == MembraneResult.FAIL]
        return MembraneStageRecord(
            stage=MembraneStage.RELEASE,
            result=MembraneResult.FAIL,
            reasoning=f"Rejected: {', '.join(failed)} failed",
        )

    if has_flag:
        flagged = [r.stage.value for r in stage_records if r.result == MembraneResult.FLAG]
        return MembraneStageRecord(
            stage=MembraneStage.RELEASE,
            result=MembraneResult.FLAG,
            reasoning=f"Quarantined: {', '.join(flagged)} flagged",
        )

    return MembraneStageRecord(
        stage=MembraneStage.RELEASE,
        result=MembraneResult.PASS,  # nosec B105
        reasoning=f"Released: {len(stage_records)} stages passed",
    )
