"""Fetch stage: loads user taste corpus, plans queries, and retrieves from multi-source academic APIs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from typing import Any

from loguru import logger

from ...core.interest import taste_corpus
from ...core.research import plan_queries
from ...protocol import Paper
from ..base import PipelineContext, PipelineStage


class FetchStage(PipelineStage):
    """Retrieves candidates across arXiv, OpenReview, HuggingFace, bioRxiv, DBLP, S2, etc."""

    name = "fetch"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        # 1. Fetch interest corpus
        corpus = self.executor.fetch_corpus()
        context.corpus = corpus
        if not corpus:
            logger.error(
                "No interest corpus found. Please configure 'topics' in config/custom.yaml "
                "or provide valid Zotero credentials."
            )
            return

        # 2. Console settings & LLM query planning
        console_settings = self.executor.console()
        context.console_settings = console_settings
        context.tracked_questions = console_settings.get("questions", [])

        if self.executor.research_cfg.get("enabled", True):
            tags_to_plan = list(console_settings.get("tags", []))
            user_pos = (
                self.executor.paper_store.get_preference_positive_texts()
                if hasattr(self.executor.paper_store, "get_preference_positive_texts")
                else []
            )
            if user_pos:
                tags_to_plan.extend(user_pos[:3])

            plan = plan_queries(
                self.executor.router,
                tags_to_plan,
                console_settings.get("questions", []),
                [p.title for p in taste_corpus(corpus)[:10]],
                state=self.executor.research_state,
            )
            if plan.get("s2_queries") and "semantic_scholar" in self.executor.retrievers:
                self.executor.retrievers["semantic_scholar"].retriever_config.queries = plan["s2_queries"]
                pos_cnt = len(plan.get("affirmative_s2", []))
                neg_cnt = len(plan.get("adversarial_s2", []))
                logger.info(
                    f"Planned {len(plan['s2_queries'])} S2 queries "
                    f"({pos_cnt} affirmative, {neg_cnt} adversarial counter-queries)"
                )
                if "openreview" in self.executor.retrievers and not self.executor.retrievers["openreview"].retriever_config.get("queries"):
                    self.executor.retrievers["openreview"].retriever_config.queries = plan["s2_queries"][:6]
                if "dblp" in self.executor.retrievers and not self.executor.retrievers["dblp"].retriever_config.get("queries"):
                    self.executor.retrievers["dblp"].retriever_config.queries = plan["s2_queries"][:6]
            if plan.get("arxiv_categories") and "arxiv" in self.executor.retrievers:
                self.executor.retrievers["arxiv"].retriever_config.category = plan["arxiv_categories"]
                logger.info(f"Planned arXiv categories: {', '.join(plan['arxiv_categories'])}")

        # 3. Parallel multi-source retrieval
        all_papers: list[Paper] = []

        def retrieve_one(item: tuple[str, Any]) -> tuple[str, list[Paper]]:
            source, retriever = item
            logger.info(f"Retrieving {source} papers...")
            return source, retriever.retrieve_papers() or []

        with ThreadPoolExecutor(max_workers=max(1, len(self.executor.retrievers))) as pool:
            for source, papers in pool.map(retrieve_one, list(self.executor.retrievers.items())):
                if not papers:
                    logger.info(f"No {source} papers found")
                    continue
                logger.info(f"Retrieved {len(papers)} {source} papers")
                all_papers.extend(papers)

        context.all_papers = all_papers
        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")

        # 4. Deduplicate across sources
        deduped = self.executor.paper_store.dedup(all_papers)
        context.deduped_papers = deduped
        logger.info(f"{len(deduped)} unique papers after cross-source deduplication")

        # 5. Filter already pushed
        force_today = (
            os.environ.get("FORCE_RERUN_TODAY", "").lower() in ("true", "1")
            or str(context.config.executor.get("force_today", False)).lower() in ("true", "1")
        )
        context.force_today = force_today
        new_papers = self.executor.paper_store.filter_already_pushed(deduped, allow_same_day=force_today)
        context.new_papers = new_papers
        logger.info(f"{len(new_papers)} new unpushed papers ready for quality filtering")
