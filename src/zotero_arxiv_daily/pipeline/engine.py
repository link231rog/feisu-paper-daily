"""Pipeline DAG engine: orchestrates stage execution with telemetry, lifecycle hooks, and error isolation."""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from loguru import logger

from .base import PipelineContext, PipelineStage
from .stages.delivery_stage import DeliveryStage
from .stages.digest_stage import DigestStage
from .stages.enrich_stage import EnrichStage
from .stages.fetch_stage import FetchStage
from .stages.ingest_stage import IngestStage
from .stages.rerank_stage import RerankStage


class PipelineEngine:
    """Configurable DAG pipeline orchestrator."""

    def __init__(self, stages: Optional[list[PipelineStage]] = None):
        self.stages: list[PipelineStage] = stages or []
        self._before_stage_hooks: list[Callable[[PipelineStage, PipelineContext], None]] = []
        self._after_stage_hooks: list[Callable[[PipelineStage, PipelineContext, float], None]] = []

    def add_stage(self, stage: PipelineStage) -> PipelineEngine:
        self.stages.append(stage)
        return self

    def register_before_hook(self, hook: Callable[[PipelineStage, PipelineContext], None]) -> None:
        self._before_stage_hooks.append(hook)

    def register_after_hook(self, hook: Callable[[PipelineStage, PipelineContext, float], None]) -> None:
        self._after_stage_hooks.append(hook)

    @classmethod
    def create_default(cls, executor: Any) -> PipelineEngine:
        """Constructs the standard 6-stage literature pipeline."""
        return cls(
            stages=[
                IngestStage(executor),
                FetchStage(executor),
                RerankStage(executor),
                EnrichStage(executor),
                DigestStage(executor),
                DeliveryStage(executor),
            ]
        )

    def execute(self, context: PipelineContext) -> PipelineContext:
        """Executes registered pipeline stages in order, isolating transient failures."""
        logger.info(f"Starting Literature Pipeline DAG with {len(self.stages)} stages...")
        pipeline_start = time.time()

        for idx, stage in enumerate(self.stages, 1):
            if not stage.is_enabled(context):
                logger.info(f"[{idx}/{len(self.stages)}] Stage '{stage.name}' is disabled; skipping.")
                continue

            for hook in self._before_stage_hooks:
                try:
                    hook(stage, context)
                except Exception as hook_err:
                    logger.debug(f"Before hook error for stage '{stage.name}': {hook_err}")

            stage_start = time.time()
            logger.info(f"[{idx}/{len(self.stages)}] Executing stage: '{stage.name}'...")

            try:
                stage.run(context)
            except Exception as exc:
                elapsed = time.time() - stage_start
                context.stage_durations[stage.name] = elapsed
                context.errors.append({"stage": stage.name, "error": str(exc)})
                logger.error(f"Stage '{stage.name}' failed after {elapsed:.2f}s: {exc}")
                raise

            elapsed = time.time() - stage_start
            context.stage_durations[stage.name] = elapsed
            logger.info(f"Stage '{stage.name}' finished in {elapsed:.2f}s")

            for hook in self._after_stage_hooks:
                try:
                    hook(stage, context, elapsed)
                except Exception as hook_err:
                    logger.debug(f"After hook error for stage '{stage.name}': {hook_err}")

            # Early exit conditions
            if stage.name == "ingest" and (
                context.config.executor.get("ingest_only", False)
                or str(context.config.executor.get("ingest_only", "")).lower() in ("true", "1")
            ):
                logger.info("Ingest-only mode triggered early exit.")
                break

            if stage.name == "fetch" and not context.corpus:
                logger.warning("No corpus loaded. Exiting pipeline early.")
                break

            if stage.name == "rerank" and not context.reranked_papers and not context.config.executor.send_empty:
                logger.info("No papers passed reranking and send_empty is false. Exiting pipeline early.")
                break

        total_elapsed = time.time() - pipeline_start
        logger.info(f"Literature Pipeline DAG finished successfully in {total_elapsed:.2f}s")
        return context
