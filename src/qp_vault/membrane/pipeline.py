# Copyright 2026 Quantum Pipes Technologies, LLC
# SPDX-License-Identifier: Apache-2.0

"""Membrane Pipeline: orchestrates multi-stage content screening.

Runs content through the Membrane stages:
1. REMEMBER: check against known attack pattern registry (fast pre-check)
2. INNATE_SCAN: pattern-based detection (regex, blocklists)
3. ADAPTIVE_SCAN: LLM-based semantic screening (optional)
4. CORRELATE: cross-document contradiction detection (optional)
5. RELEASE: risk-proportionate gating decision

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
    from qp_vault.membrane.correlate import CorrelateConfig
    from qp_vault.membrane.remember import AttackRegistry


class MembranePipeline:
    """Membrane pipeline.

    Screens content through multiple stages before allowing indexing.
    Content that fails screening is rejected. Flagged content is quarantined.

    Args:
        innate_config: Configuration for the innate scan stage.
        adaptive_config: Configuration for the adaptive (LLM) scan stage.
        correlate_config: Configuration for cross-document correlation.
        attack_registry: Attack pattern registry for the REMEMBER stage.
        enabled: Whether Membrane screening is active. Default True.
    """

    def __init__(
        self,
        *,
        innate_config: InnateScanConfig | None = None,
        adaptive_config: AdaptiveScanConfig | None = None,
        correlate_config: CorrelateConfig | None = None,
        attack_registry: AttackRegistry | None = None,
        enabled: bool = True,
    ) -> None:
        self._innate_config = innate_config
        self._adaptive_config = adaptive_config
        self._correlate_config = correlate_config
        self._attack_registry = attack_registry
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

        # Stage 1: REMEMBER (fast pre-check against known attack patterns)
        from qp_vault.membrane.remember import run_remember
        remember_result = await run_remember(content, self._attack_registry)
        stages.append(remember_result)

        # Stage 2: Innate scan (regex patterns)
        innate_result = await run_innate_scan(content, self._innate_config)
        stages.append(innate_result)

        # Stage 3: Adaptive scan (LLM-based, optional)
        from qp_vault.membrane.adaptive_scan import run_adaptive_scan
        adaptive_result = await run_adaptive_scan(content, self._adaptive_config)
        stages.append(adaptive_result)

        # Stage 4: Correlate (cross-document contradiction, optional)
        from qp_vault.membrane.correlate import run_correlate
        correlate_result = await run_correlate(content, self._correlate_config)
        stages.append(correlate_result)

        # Stage 5: Release gate (aggregates all prior results)
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

        # Learn from flagged content (feed REMEMBER registry)
        if overall in (MembraneResult.FAIL, MembraneResult.FLAG) and self._attack_registry:
            all_flags = []
            for s in stages:
                all_flags.extend(s.matched_patterns)
            self._attack_registry.learn(content, all_flags, aggregate_risk)

        return MembranePipelineStatus(
            stages=stages,
            overall_result=overall,
            recommended_status=status,
            aggregate_risk_score=aggregate_risk,
        )
