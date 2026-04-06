# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Release gate: risk-proportionate gating before indexing.

Evaluates CIS stage results and decides whether content should be:
- RELEASED (indexed normally)
- HELD (quarantined for human review)
- REJECTED (blocked from indexing)
"""

from __future__ import annotations

from qp_vault.enums import CISResult, CISStage
from qp_vault.models import CISStageRecord


async def evaluate_release(
    stage_records: list[CISStageRecord],
) -> CISStageRecord:
    """Evaluate whether content should be released for indexing.

    Decision logic:
    - If any stage FAIL'd: FAIL (reject)
    - If any stage FLAG'd: FLAG (quarantine for review)
    - Otherwise: PASS (release)

    Args:
        stage_records: Results from previous CIS stages.

    Returns:
        CISStageRecord for the RELEASE stage.
    """
    has_fail = any(r.result == CISResult.FAIL for r in stage_records)
    has_flag = any(r.result == CISResult.FLAG for r in stage_records)

    if has_fail:
        failed_stages = [r.stage.value for r in stage_records if r.result == CISResult.FAIL]
        return CISStageRecord(
            stage=CISStage.RELEASE,
            result=CISResult.FAIL,
            details={"decision": "rejected", "failed_stages": failed_stages},
        )

    if has_flag:
        flagged_stages = [r.stage.value for r in stage_records if r.result == CISResult.FLAG]
        return CISStageRecord(
            stage=CISStage.RELEASE,
            result=CISResult.FLAG,
            details={"decision": "quarantined", "flagged_stages": flagged_stages},
        )

    return CISStageRecord(
        stage=CISStage.RELEASE,
        result=CISResult.PASS,  # nosec B105
        details={"decision": "released", "stages_passed": len(stage_records)},
    )
