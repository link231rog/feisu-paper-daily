"""Digest stage: evaluates papers with the built-in Critical-Paper-Digest 4D rubric and recalibrates tiers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any

from loguru import logger

from ...core.digest import rerank_by_composite_score, run_critical_paper_digest
from ...protocol import Paper
from ..base import PipelineContext, PipelineStage


class DigestStage(PipelineStage):
    """Executes the Critical-Paper-Digest skill, generates deterministic rubrics, and recalibrates ranking."""

    name = "digest"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        if not context.reranked_papers:
            return

        custom_rules = context.console_settings.get("custom_rules", [])
        note_template = context.console_settings.get("note_template", [])
        library_baselines = [c.title for c in (context.corpus or [])[:30]]
        digest_workers = max(1, int(context.config.executor.get("tldr_workers", 4)))

        logger.info(
            f"Running Critical-Paper-Digest skill for {len(context.reranked_papers)} papers "
            f"(tier1={len(context.deep_read_papers)})..."
        )

        def process_paper_digest(p: Paper) -> None:
            is_tier1 = p in context.deep_read_papers
            # 1. Critical-Paper-Digest review skill
            run_critical_paper_digest(
                self.executor.router,
                p,
                questions=context.tracked_questions,
                library_baselines=library_baselines,
                user_custom_rules=custom_rules,
                user_note_template=note_template,
                is_tier1=is_tier1,
            )
            # 2. Extract conference venue and affiliations if not populated
            if not p.venue:
                p.generate_venue(self.executor.openai_client, context.config.llm if self.executor.openai_client else None)
            if self.executor.openai_client is not None and not p.affiliations:
                p.generate_affiliations(self.executor.openai_client, context.config.llm)
            # 3. Fallback for TL;DR if LLM failed
            if not p.tldr_zh:
                if self.executor.translator is not None:
                    first = (p.abstract or p.title).split(". ")[0].strip().rstrip(".") + "."
                    p.tldr_en = first
                    p.tldr_zh = self.executor.translator.translate_single(first) or first
                    p.tldr = p.tldr_zh
                elif p.abstract:
                    p.tldr = p.abstract[:150]

        with ThreadPoolExecutor(max_workers=digest_workers) as pool:
            list(pool.map(process_paper_digest, context.reranked_papers))

        # Calibrate daily ranking & tier assignment using 4D rubric composite scores
        research_cfg = self.executor.research_cfg
        if str(research_cfg.get("rerank_by_rubric", True)).lower() in ("true", "1"):
            deep_quota = int(research_cfg.get("deep_read_quota", 3))
            recalibrated = rerank_by_composite_score(context.reranked_papers, deep_read_quota=deep_quota)
            context.reranked_papers = recalibrated
            context.deep_read_papers = [p for p in recalibrated if getattr(p, "recommendation_tier", "deep_read") == "deep_read"]
            context.quick_radar_papers = [p for p in recalibrated if getattr(p, "recommendation_tier", None) == "quick_radar"]

        self.executor.write_trace(context.ranked_papers, context.reranked_papers, context.funnel)

        logger.info(f"=== Recommended Papers ({len(context.reranked_papers)} papers) ===")
        for idx, p in enumerate(context.reranked_papers, 1):
            src_tag = f"[{', '.join(p.sources or [p.source])}]"
            score_str = f"(Score: {p.score:.2f})" if p.score is not None else ""
            logger.info(f"{idx}. {src_tag} {score_str} {p.title_with_venue()}")
            logger.info(f"   URL: {p.url}")
            logger.info(f"   TL;DR: {p.tldr}\n")
