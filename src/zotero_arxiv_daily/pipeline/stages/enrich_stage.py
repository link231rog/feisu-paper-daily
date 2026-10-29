"""Enrich stage: enriches papers with baseline linkages, question synthesis, AI trends, and Agent-Reach external intelligence."""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from ...core.baseline import enrich_papers_with_baselines
from ...core.research import suggest_next_questions, synthesize_questions
from ...protocol import Paper, TrendingItem
from ..backends.agent_reach import AgentReachCLI
from ..base import PipelineContext, PipelineStage


class EnrichStage(PipelineStage):
    """Augments literature candidates with baseline linkages, community pulse, and external talks."""

    name = "enrich"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        if not context.reranked_papers:
            return

        digest_workers = max(1, int(context.config.executor.get("tldr_workers", 4)))
        research_cfg = self.executor.research_cfg

        # 1. Baseline linkage extraction for deep-read papers
        if context.deep_read_papers and bool(research_cfg.get("baselines", True)):
            logger.info(f"Extracting baseline linkages for {len(context.deep_read_papers)} papers...")
            enrich_papers_with_baselines(
                self.executor.router,
                context.deep_read_papers,
                context.corpus,
                max_workers=digest_workers,
            )

        # 2. Per-question synthesis and next-round question proposals
        questions = context.tracked_questions
        if research_cfg.get("synthesis", True) and questions:
            context.question_briefs = synthesize_questions(
                self.executor.router,
                questions,
                context.reranked_papers,
                state=self.executor.research_state,
                max_questions=int(research_cfg.get("max_brief_questions", 8)),
            )
            self.executor.research_state.record(context.question_briefs)
            logger.info(f"Wrote {len(context.question_briefs)} question briefs")

            if research_cfg.get("next_questions", True):
                accepted = [p.title for p in context.reranked_papers if p.qa_matches]
                suggested = suggest_next_questions(
                    self.executor.router,
                    questions,
                    context.question_briefs,
                    accepted,
                    state=self.executor.research_state,
                )
                context.suggested_questions = suggested or []
                if suggested:
                    logger.info(f"Proposed {len(suggested)} next-round questions")
                    try:
                        from ...library.console import append_suggested_questions_to_console

                        append_suggested_questions_to_console(context.config, suggested)
                    except Exception as exc:
                        logger.warning(f"Could not write suggested questions to console: {exc}")

        # 3. Retrieve AI Dynamics and GitHub Trends
        trends_cfg = context.config.get("news_and_trends") or {}
        if trends_cfg.get("enabled", True):
            try:
                from ...retriever.github_trending_retriever import GithubTrendingRetriever
                from ...retriever.news_retriever import NewsRetriever

                gh_retriever = GithubTrendingRetriever(context.config)
                news_retriever = NewsRetriever(context.config)

                raw_trending: list[TrendingItem] = []
                raw_trending.extend(gh_retriever.retrieve_trending())
                raw_trending.extend(news_retriever.retrieve_news())

                deduped = self.executor.paper_store.dedup_trending(raw_trending)
                unpushed = self.executor.paper_store.filter_already_pushed(deduped)
                unpushed.sort(key=lambda x: (x.stars or 0), reverse=True)

                total_daily_quota = context.config.executor.get("total_daily_quota")
                if total_daily_quota:
                    max_trends = min(int(trends_cfg.get("max_items", 4)), max(1, int(total_daily_quota) // 3))
                else:
                    max_trends = int(trends_cfg.get("max_items", 4))

                trending_items = unpushed[:max_trends]

                # Generate concise Chinese summary
                if self.executor.openai_client is not None and trending_items:
                    for t_item in trending_items:
                        if not t_item.summary_zh and t_item.description:
                            try:
                                prompt = (
                                    "Translate and summarize the following AI project or news into one concise Chinese sentence:\n"
                                    f"Title: {t_item.title}\n"
                                    f"Description: {t_item.description}"
                                )
                                resp = self.executor.openai_client.chat.completions.create(
                                    model=context.config.llm.generation_kwargs.model,
                                    messages=[
                                        {"role": "system", "content": "You are a concise translator for technical AI news."},
                                        {"role": "user", "content": prompt},
                                    ],
                                    max_tokens=150,
                                )
                                t_item.summary_zh = resp.choices[0].message.content.strip()
                            except Exception:
                                t_item.summary_zh = t_item.description

                context.trending_items = trending_items
            except Exception as exc:
                logger.warning(f"Failed to retrieve AI news/trends: {exc}")

        # 4. Agent-Reach External Social & Multimedia Intelligence (Zero-install pipeline assembly)
        ar_cfg = context.config.get("agent_reach") or {}
        ar_enabled = str(ar_cfg.get("enabled", False)).lower() in ("true", "1")
        if ar_enabled and AgentReachCLI.is_installed():
            channels = [str(c).lower().strip() for c in ar_cfg.get("channels", ["bilibili", "youtube"])]
            max_enrich = int(ar_cfg.get("max_papers_to_enrich", 3))
            timeout = float(ar_cfg.get("timeout", 15.0))

            target_papers = (context.deep_read_papers or context.reranked_papers)[:max_enrich]
            logger.info(f"Enriching top {len(target_papers)} papers via Agent-Reach (channels={channels})...")

            for p in target_papers:
                clean_title = re.sub(r"\s+", " ", p.title or "").strip()
                if not clean_title:
                    continue

                p_enrich: dict[str, Any] = {}

                # Bilibili tech breakdowns
                if "bilibili" in channels:
                    bili_res = AgentReachCLI.search_bilibili(clean_title, limit=2, timeout=timeout)
                    if bili_res:
                        p_enrich["bilibili"] = bili_res

                # YouTube presentations & talks
                if "youtube" in channels:
                    yt_res = AgentReachCLI.search_youtube(clean_title, limit=2, timeout=timeout)
                    if yt_res:
                        p_enrich["youtube"] = yt_res

                # Reddit community discussions
                if "reddit" in channels:
                    reddit_res = AgentReachCLI.search_reddit(clean_title, limit=2, timeout=timeout)
                    if reddit_res:
                        p_enrich["reddit"] = reddit_res

                # GitHub repo issues / discussions
                if "github" in channels and p.code_url:
                    gh_res = AgentReachCLI.inspect_github_repo(p.code_url, timeout=timeout)
                    if gh_res:
                        p_enrich["github"] = gh_res

                if p_enrich:
                    context.enrichments[p.url] = p_enrich
                    logger.info(f"Agent-Reach enriched '{clean_title[:40]}' with {list(p_enrich.keys())}")
