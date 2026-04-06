# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""CIS Pipeline: orchestrates multi-stage content screening.

Runs content through the Content Immune System stages:
1. INNATE_SCAN — pattern-based detection (regex, blocklists)
2. RELEASE — risk-proportionate gating decision

Future stages (adaptive scan, correlate, surveil, present, remember)
will be added as the pipeline matures.
"""

from __future__ import annotations

from qp_vault.cis.innate_scan import InnateScanConfig, run_innate_scan
from qp_vault.cis.release_gate import evaluate_release
from qp_vault.enums import CISResult, CISStage, ResourceStatus
from qp_vault.models import CISPipelineStatus, CISStageRecord


class CISPipeline:
    """Content Immune System pipeline.

    Screens content through multiple stages before allowing indexing.
    Content that fails screening is quarantined.

    Args:
        innate_config: Configuration for the innate scan stage.
        enabled: Whether CIS screening is active. Default True.
    """

    def __init__(
        self,
        *,
        innate_config: InnateScanConfig | None = None,
        enabled: bool = True,
    ) -> None:
        self._innate_config = innate_config
        self._enabled = enabled

    async def screen(self, content: str) -> CISPipelineStatus:
        """Run content through the CIS pipeline.

        Args:
            content: Text content to screen.

        Returns:
            CISPipelineStatus with stage results and overall decision.
        """
        if not self._enabled:
            return CISPipelineStatus(
                stages=[
                    CISStageRecord(
                        stage=CISStage.RELEASE,
                        result=CISResult.PASS,  # nosec B105
                        details={"decision": "released", "reason": "CIS disabled"},
                    ),
                ],
                overall_result=CISResult.PASS,  # nosec B105
                recommended_status=ResourceStatus.INDEXED,
            )

        stages: list[CISStageRecord] = []

        # Stage 1: Innate scan
        innate_result = await run_innate_scan(content, self._innate_config)
        stages.append(innate_result)

        # Stage 2: Release gate
        release_result = await evaluate_release(stages)
        stages.append(release_result)

        # Determine overall result and recommended status
        overall = release_result.result
        if overall == CISResult.FAIL or overall == CISResult.FLAG:
            status = ResourceStatus.QUARANTINED
        else:
            status = ResourceStatus.INDEXED

        return CISPipelineStatus(
            stages=stages,
            overall_result=overall,
            recommended_status=status,
        )
