"""Rerank stage: filters academic quality, executes citation chasing, and performs MMR multi-objective fusion."""

from __future__ import annotations

import time
from typing import Any

from loguru import logger

from ...core.interest import taste_corpus
from ...core.research import pick_seeds
from ...protocol import Paper
from ..base import PipelineContext, PipelineStage


class RerankStage(PipelineStage):
    """Reranks candidates against taste corpus, negative prototypes, and tracked questions."""

    name = "rerank"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        if not context.new_papers:
            logger.info("No new papers to rerank.")
            return

        # 1. Enrich arXiv candidates with Hugging Face Daily Papers cold-start upvotes
        hf_cfg = (context.config.get("source") or {}).get("huggingface") or {}
        if str(hf_cfg.get("enrich_daily_signals", True)).lower() in ("true", "1"):
            from ...retriever.huggingface_retriever import enrich_with_hf_daily_signals

            enrich_with_hf_daily_signals(context.new_papers, limit=int(hf_cfg.get("limit", 100) or 100))

        # 2. Academic Quality Gate
        quality_papers = self.executor.filter_quality_papers(
            context.new_papers, console_settings=context.console_settings
        )
        context.quality_papers = quality_papers
        logger.info(f"{len(quality_papers)} / {len(context.new_papers)} papers passed academic quality gate")

        context.funnel = {
            "retrieved": len(context.all_papers),
            "unique": len(context.deduped_papers),
            "unpushed": len(context.new_papers),
            "quality": len(quality_papers),
        }

        priority_institutions = context.console_settings.get("institutions", [])
        topic_anchors = list(
            dict.fromkeys(
                (context.console_settings.get("tags") or [])
                + (context.console_settings.get("required_anchors") or [])
            )
        ) or None
        negative_texts = list(
            dict.fromkeys(
                self.executor.paper_store.recent_discarded_texts(200)
                + (context.console_settings.get("excluded_keywords") or [])
            )
        ) or None

        # 3. Multi-hop citation chasing
        research_cfg = self.executor.research_cfg
        if research_cfg.get("enabled", True) and research_cfg.get("multi_hop", True):
            _t0 = time.time()
            seed_pool = (
                self.executor.reranker.rerank(
                    list(quality_papers),
                    taste_corpus(context.corpus),
                    priority_institutions=priority_institutions,
                    topic_anchors=topic_anchors,
                    negative_texts=negative_texts,
                )
                if quality_papers
                else []
            )
            logger.info(f"Seed rerank finished in {time.time() - _t0:.1f}s")
            seeds = pick_seeds(
                self.executor.router,
                seed_pool[:20],
                int(research_cfg.get("max_seeds", 4)),
                questions=context.tracked_questions,
            )
            logger.info(f"pick_seeds finished at {time.time() - _t0:.1f}s ({len(seeds)} seeds)")
            if seeds and "semantic_scholar" in self.executor.retrievers:
                seed_urls = [s.url for s in seeds if getattr(s, "url", None)]
                related = self.executor.retrievers["semantic_scholar"].retrieve_related(seed_urls or seeds)
                logger.info(f"Citation chasing finished at {time.time() - _t0:.1f}s ({len(related or [])} related)")
                if related:
                    merged = self.executor.paper_store.dedup(quality_papers + related)
                    quality_papers = self.executor.filter_quality_papers(
                        self.executor.paper_store.filter_already_pushed(merged, allow_same_day=context.force_today),
                        console_settings=context.console_settings,
                    )
                    context.quality_papers = quality_papers
                    logger.info(f"{len(quality_papers)} papers after citation chasing")

        # 4. Quota allocation
        trends_cfg = context.config.get("news_and_trends") or {}
        total_daily_quota = context.config.executor.get("total_daily_quota")
        if total_daily_quota is not None:
            total_quota = int(total_daily_quota)
            max_trends = min(int(trends_cfg.get("max_items", 4)), max(1, total_quota // 3))
            paper_quota = max(1, total_quota - max_trends)
        else:
            paper_quota = int(context.config.executor.get("max_paper_num", 15))

        if not quality_papers:
            logger.info("No quality papers left after filtering.")
            return

        # 5. Core Reranking
        logger.info("Reranking papers against interest corpus...")
        ranked = self.executor.reranker.rerank(
            quality_papers,
            taste_corpus(context.corpus),
            priority_institutions=priority_institutions,
            topic_anchors=topic_anchors,
            negative_texts=negative_texts,
        )
        context.ranked_papers = ranked

        # 6. Score against questions
        if context.tracked_questions:
            logger.info(f"Scoring {len(ranked)} candidates against tracked questions...")
            self.executor.score_against_questions(ranked)

        self.executor.apply_negative_feedback(ranked)

        # 7. Fuse & select
        reranked = self.executor.fuse_and_select(ranked, context.tracked_questions, paper_quota)
        context.reranked_papers = reranked

        deep_read = [p for p in reranked if getattr(p, "recommendation_tier", "deep_read") == "deep_read"]
        quick_radar = [p for p in reranked if getattr(p, "recommendation_tier", None) == "quick_radar"]
        context.deep_read_papers = deep_read
        context.quick_radar_papers = quick_radar

        logger.info(
            f"Selected {len(reranked)} of {len(ranked)} candidates "
            f"(deep_read={len(deep_read)}, quick_radar={len(quick_radar)})"
        )
        context.funnel.update(
            {
                "after_citation_chasing": len(quality_papers),
                "question_relevant": sum(1 for p in ranked if p.qa_scores),
                "selected": len(reranked),
                "deep_read": len(deep_read),
                "quick_radar": len(quick_radar),
            }
        )
