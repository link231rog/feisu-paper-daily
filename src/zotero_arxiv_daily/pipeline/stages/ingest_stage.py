"""Ingest stage: processes user-confirmed papers from Feishu/Obsidian reading checklists."""

from __future__ import annotations

import os
from typing import Any

from loguru import logger

from ..base import PipelineContext, PipelineStage


class IngestStage(PipelineStage):
    """Processes newly checked papers from interactive reading checklists."""

    name = "ingest"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        try:
            ingested = self.executor.ingest_checked_papers()
            context.ingested_papers = ingested or []
            if ingested:
                logger.info(f"Ingested {len(ingested)} checked papers into knowledge base.")
        except Exception as exc:
            logger.warning(f"Notice during ingest stage: {exc}")
            context.errors.append({"stage": self.name, "error": str(exc)})

        # Check for ingest-only mode
        ingest_only = (
            context.config.executor.get("ingest_only", False)
            or os.environ.get("INGEST_ONLY", "").lower() in ("true", "1")
        )
        if ingest_only:
            logger.info("Ingest-only mode enabled. Pipeline will stop after ingestion.")
