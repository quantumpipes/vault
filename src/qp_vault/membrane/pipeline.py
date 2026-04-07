# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Membrane Pipeline: orchestrates multi-stage content screening.

Runs content through the Membrane stages:
1. INNATE_SCAN: pattern-based detection (regex, blocklists)
2. ADAPTIVE_SCAN: LLM-based semantic screening (optional, requires LLMScreener)
3. RELEASE: risk-proportionate gating decision

Stages are sequential. Each produces a MembraneStageRecord. The release
gate aggregates all prior results into a final pass/quarantine/reject decision.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from qp_vault.enums import MembraneResult, MembraneStage, ResourceStatus
from qp_vault.membrane.innate_scan import InnateScanConfig, run_innate_scan
from qp_vault.membrane.release_gate import evaluate_release
from qp_vault.models import MembranePipelineStatus, MembraneStageRecord

if TYPE_CHECKING:
    from qp_vault.membrane.adaptive_scan import AdaptiveScanConfig


class MembranePipeline:
    """Membrane pipeline.

    Screens content through multiple stages before allowing indexing.
    Content that fails screening is rejected. Flagged content is quarantined.

    Args:
        innate_config: Configuration for the innate scan stage.
        adaptive_config: Configuration for the adaptive (LLM) scan stage.
                        If None or screener is None, adaptive scan is skipped.
        enabled: Whether Membrane screening is active. Default True.
    """

    def __init__(
        self,
        *,
        innate_config: InnateScanConfig | None = None,
        adaptive_config: AdaptiveScanConfig | None = None,
        enabled: bool = True,
    ) -> None:
        self._innate_config = innate_config
        self._adaptive_config = adaptive_config
        self._enabled = enabled

    async def screen(self, content: str) -> MembranePipelineStatus:
        """Run content through the Membrane pipeline.

        Args:
            content: Text content to screen.

        Returns:
            MembranePipelineStatus with stage results and overall decision.
        """
        if not self._enabled:
            return MembranePipelineStatus(
                stages=[
                    MembraneStageRecord(
                        stage=MembraneStage.RELEASE,
                        result=MembraneResult.PASS,  # nosec B105
                        reasoning="Released: screening disabled",
                    ),
                ],
                overall_result=MembraneResult.PASS,  # nosec B105
                recommended_status=ResourceStatus.INDEXED,
            )

        stages: list[MembraneStageRecord] = []

        # Stage 1: Innate scan (regex patterns)
        innate_result = await run_innate_scan(content, self._innate_config)
        stages.append(innate_result)

        # Stage 2: Adaptive scan (LLM-based, optional)
        from qp_vault.membrane.adaptive_scan import run_adaptive_scan
        adaptive_result = await run_adaptive_scan(content, self._adaptive_config)
        stages.append(adaptive_result)

        # Stage 3: Release gate (aggregates all prior results)
        release_result = await evaluate_release(stages)
        stages.append(release_result)

        # Determine overall result and recommended status
        overall = release_result.result
        if overall in (MembraneResult.FAIL, MembraneResult.FLAG):
            status = ResourceStatus.QUARANTINED
        else:
            status = ResourceStatus.INDEXED

        # Compute aggregate risk score from non-skipped stages
        risk_scores = [s.risk_score for s in stages if s.result != MembraneResult.SKIP]
        aggregate_risk = max(risk_scores) if risk_scores else 0.0

        return MembranePipelineStatus(
            stages=stages,
            overall_result=overall,
            recommended_status=status,
            aggregate_risk_score=aggregate_risk,
        )
