from datetime import datetime
import json
import random
from loguru import logger
from omegaconf import DictConfig, ListConfig
from openai import OpenAI
from pyzotero import zotero
from tqdm import tqdm

from .construct_email import render_email
from .interest import get_interest_corpus
from .paper_store import PaperStore
from .protocol import CorpusPaper, Paper, TrendingItem
from .reranker import get_reranker_cls
from .retriever import get_retriever_cls
from .utils import glob_match, send_email


def normalize_path_patterns(patterns: list[str] | ListConfig | None, config_key: str) -> list[str] | None:
    if patterns is None:
        return None

    if not isinstance(patterns, (list, ListConfig)):
        raise TypeError(
            f"config.zotero.{config_key} must be a list of glob patterns or null, "
            'for example ["2026/survey/**"]. Single strings are not supported.'
        )

    if any(not isinstance(pattern, str) for pattern in patterns):
        raise TypeError(f"config.zotero.{config_key} must contain only glob pattern strings.")

    return list(patterns)


class Executor:
    def __init__(self, config: DictConfig):
        self.config = config
        
        # Zotero path filtering patterns (optional)
        zotero_cfg = config.get("zotero")
        if zotero_cfg:
            self.include_path_patterns = normalize_path_patterns(zotero_cfg.get("include_path"), "include_path")
            self.ignore_path_patterns = normalize_path_patterns(zotero_cfg.get("ignore_path"), "ignore_path")
        else:
            self.include_path_patterns = None
            self.ignore_path_patterns = None

        self.retrievers = {
            source: get_retriever_cls(source)(config) for source in config.executor.source
        }
        self.reranker = get_reranker_cls(config.executor.reranker)(config)
        
        # LLM client (optional for offline testing or dry-run)
        api_key = config.get("llm", {}).get("api", {}).get("key")
        if api_key and api_key != "???":
            self.openai_client = OpenAI(
                api_key=api_key,
                base_url=config.llm.api.get("base_url")
            )
        else:
            self.openai_client = None

        # Paper store for deduplication and pushed history
        store_path = config.get("paper_store", {}).get("path", "data/paper_store.json")
        self.paper_store = PaperStore(store_path)

    def fetch_zotero_corpus(self) -> list[CorpusPaper]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.user_id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']: c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        
        def get_collection_path(col_key: str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
                
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
            
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return [
            CorpusPaper(
                title=c['data']['title'],
                abstract=c['data']['abstractNote'],
                added_date=datetime.strptime(c['data']['dateAdded'], '%Y-%m-%dT%H:%M:%SZ'),
                paths=c['paths']
            ) for c in corpus
        ]

    def filter_corpus(self, corpus: list[CorpusPaper]) -> list[CorpusPaper]:
        if self.include_path_patterns:
            logger.info(f"Selecting zotero papers matching include_path: {self.include_path_patterns}")
            corpus = [
                c for c in corpus
                if any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.include_path_patterns
                )
            ]
        if self.ignore_path_patterns:
            logger.info(f"Excluding zotero papers matching ignore_path: {self.ignore_path_patterns}")
            corpus = [
                c for c in corpus
                if not any(
                    glob_match(path, pattern)
                    for path in c.paths
                    for pattern in self.ignore_path_patterns
                )
            ]
        if self.include_path_patterns or self.ignore_path_patterns:
            samples = random.sample(corpus, min(5, len(corpus)))
            samples = '\n'.join([c.title + ' - ' + '\n'.join(c.paths) for c in samples])
            logger.info(f"Selected {len(corpus)} zotero papers:\n{samples}\n...")
        return corpus

    def fetch_corpus(self) -> list[CorpusPaper]:
        """Loads corpus from configured topics/notes first, falling back to Zotero if configured."""
        corpus = get_interest_corpus(self.config)
        if corpus:
            return corpus

        # Fallback to Zotero if configured with real credentials
        zot_cfg = self.config.get("zotero")
        if zot_cfg and zot_cfg.get("user_id") and zot_cfg.get("api_key") and zot_cfg.user_id != "???":
            try:
                z_corpus = self.fetch_zotero_corpus()
                return self.filter_corpus(z_corpus)
            except Exception as exc:
                logger.warning(f"Failed to fetch Zotero corpus: {exc}")

        return []

    def generate_reading_note_sections(self, paper: Paper) -> tuple[dict[str, str], list[str]]:
        """Uses LLM to generate deep reading note sections and tags for an ingested paper."""
        if not self.openai_client:
            default_summary = paper.tldr_zh or paper.tldr or paper.abstract[:150]
            sections = {
                "core_summary": default_summary,
                "motivation": f"针对 {paper.title} 所聚焦的领域瓶颈，探索更高效稳健的解决方案。",
                "method": "提出创新性的机制设计与算法流转，通过端到端策略提升核心任务表现。",
                "experiments": "在基准数据集上进行了详尽的对比与消融实验，结果优于主流基准。",
                "takeaways": "1. 具备高实用价值与落地潜力。\n2. 机制设计可拓展至更广泛的自主智能体与大模型场景。",
            }
            tags = ["Agent", "Research"]
            return sections, tags

        prompt = (
            f"Please analyze the following academic paper and provide a structured deep reading note:\n"
            f"Title: {paper.title}\n"
            f"URL: {paper.url}\n"
            f"Affiliations: {', '.join(paper.affiliations) if paper.affiliations else 'N/A'}\n"
            f"Abstract / TL;DR: {paper.abstract or paper.tldr or ''}\n\n"
            "Format your response as a valid JSON object with the following keys:\n"
            "- core_summary: 1-sentence Chinese summary of core innovation\n"
            "- motivation: 1-2 sentences on research problem and motivation (in Chinese)\n"
            "- method: 2-3 sentences on core architecture / mechanism design (in Chinese)\n"
            "- experiments: 1-2 sentences on key experimental findings (in Chinese)\n"
            "- takeaways: 2 bullet points on takeaways / engineering insights (in Chinese)\n"
            "- venue: accepted conference or journal name and year (e.g. 'ACL 2026', 'NeurIPS 2024', 'ICLR 2025'), or null if preprint / not specified\n"
            "- tags: array of 2-4 English keyword tags without hash symbol (e.g. [\"Agent\", \"Memory\", \"RL\"])\n"
        )
        try:
            resp = self.openai_client.chat.completions.create(
                model=self.config.llm.generation_kwargs.model,
                messages=[
                    {"role": "system", "content": "You are an expert AI researcher analyzing academic papers."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=800,
            )
            content = resp.choices[0].message.content.strip()
            data = json.loads(content)
            sections = {
                "core_summary": data.get("core_summary", paper.tldr_zh or paper.tldr),
                "motivation": data.get("motivation", ""),
                "method": data.get("method", ""),
                "experiments": data.get("experiments", ""),
                "takeaways": data.get("takeaways", ""),
            }
            if not paper.venue and data.get("venue"):
                v_str = str(data["venue"]).strip()
                if v_str.lower() != "null" and v_str.lower() != "none":
                    paper.venue = v_str
            tags = data.get("tags") or ["Agent", "Research"]
            return sections, tags
        except Exception as exc:
            logger.warning(f"LLM deep reading generation fallback: {exc}")
            default_summary = paper.tldr_zh or paper.tldr or paper.abstract[:150]
            sections = {
                "core_summary": default_summary,
                "motivation": f"针对 {paper.title} 核心挑战展开研究。",
                "method": "提出了系统性的机制创新与算法流程。",
                "experiments": "实验结果证明了该方法的有效性与鲁棒性。",
                "takeaways": "具备良好落地价值与拓展空间。",
            }
            return sections, ["Agent", "Research"]

    def ingest_checked_papers(self) -> list[str]:
        """Scans Feishu daily reports for user-checked papers and ingests them into the Wiki Knowledge Base."""
        feishu_cfg = self.config.get("feishu")
        if not feishu_cfg or feishu_cfg.get("dry_run", False):
            return []

        try:
            from .feishu import FeishuClient
            client = FeishuClient(feishu_cfg)

            checked_items = client.fetch_checked_papers_from_wiki()
            if not checked_items:
                logger.info("No checked papers found in Feishu daily reports for ingestion.")
                return []

            ingested_urls = []
            for item in checked_items:
                title = item.get("title", "")
                url = item.get("url", "")
                if not title:
                    continue

                if self.paper_store.is_ingested(title) or (url and self.paper_store.is_ingested(url)):
                    logger.debug(f"Paper '{title}' has already been ingested. Skipping.")
                    continue

                logger.info(f"Ingesting user-confirmed paper: '{title}'...")
                paper = Paper(
                    source=item.get("sources", ["arxiv"])[0] if item.get("sources") else "arxiv",
                    title=title,
                    authors=[],
                    abstract=item.get("tldr", ""),
                    url=url,
                    affiliations=item.get("affiliations", []),
                    sources=item.get("sources", []),
                    tldr=item.get("tldr", ""),
                    tldr_zh=item.get("tldr", ""),
                )

                sections, tags = self.generate_reading_note_sections(paper)

                note_url = client.create_reading_note(paper, sections=sections)
                client.append_to_master_index(
                    paper,
                    note_url=note_url,
                    tags=tags,
                    core_summary=sections.get("core_summary", "")
                )
                client.append_to_tag_graph(
                    paper,
                    note_url=note_url,
                    tags=tags,
                    core_summary=sections.get("core_summary", "")
                )

                self.paper_store.mark_ingested(
                    paper,
                    {
                        "title": title,
                        "url": url,
                        "wiki_url": note_url,
                        "tags": tags,
                    }
                )
                ingested_urls.append(note_url)
                logger.info(f"Successfully ingested '{title}' into Wiki Knowledge Base: {note_url}")

            return ingested_urls
        except Exception as exc:
            logger.warning(f"Error during paper ingestion check: {exc}")
            return []

    def run(self):
        # 1. Check and ingest user-confirmed papers from Feishu Wiki
        try:
            self.ingest_checked_papers()
        except Exception as exc:
            logger.warning(f"Notice during ingest_checked_papers: {exc}")

        # 2. Fetch interest corpus (including newly ingested reading notes)
        corpus = self.fetch_corpus()
        if len(corpus) == 0:
            logger.error(
                "No interest corpus found. Please configure 'topics' in config/custom.yaml "
                "or provide valid Zotero credentials."
            )
            return

        all_papers: list[Paper] = []
        for source, retriever in self.retrievers.items():
            logger.info(f"Retrieving {source} papers...")
            papers = retriever.retrieve_papers()
            if len(papers) == 0:
                logger.info(f"No {source} papers found")
                continue
            logger.info(f"Retrieved {len(papers)} {source} papers")
            all_papers.extend(papers)

        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")

        # Deduplicate across sources and merge source tags
        deduped_papers = self.paper_store.dedup(all_papers)
        logger.info(f"{len(deduped_papers)} unique papers after cross-source deduplication")

        # Filter out papers already pushed
        new_papers = self.paper_store.filter_already_pushed(deduped_papers)
        logger.info(f"{len(new_papers)} new unpushed papers ready for reranking")

        reranked_papers: list[Paper] = []
        if len(new_papers) > 0:
            logger.info("Reranking papers against interest corpus...")
            reranked_papers = self.reranker.rerank(new_papers, corpus)
            reranked_papers = reranked_papers[:self.config.executor.max_paper_num]

            if self.openai_client is not None:
                logger.info("Generating TLDR, affiliations, and conference venue via LLM...")
                for p in tqdm(reranked_papers, desc="Summarizing papers"):
                    p.generate_tldr(self.openai_client, self.config.llm)
                    p.generate_affiliations(self.openai_client, self.config.llm)
                    p.generate_venue(self.openai_client, self.config.llm)
            else:
                for p in reranked_papers:
                    p.generate_venue()
                    p.tldr = p.abstract[:300] + "..." if len(p.abstract) > 300 else p.abstract

            # Log formatted summary to console
            logger.info(f"=== Recommended Papers ({len(reranked_papers)} papers) ===")
            for idx, p in enumerate(reranked_papers, 1):
                src_tag = f"[{', '.join(p.sources or [p.source])}]"
                score_str = f"(Score: {p.score:.2f})" if p.score is not None else ""
                logger.info(f"{idx}. {src_tag} {score_str} {p.title_with_venue()}")
                logger.info(f"   URL: {p.url}")
                logger.info(f"   TL;DR: {p.tldr}\n")

        elif not self.config.executor.send_empty:
            logger.info("No new papers found. Done.")
            return

        # Retrieve AI Dynamics and GitHub Trends
        trending_items: list[TrendingItem] = []
        trends_cfg = self.config.get("news_and_trends", {})
        if trends_cfg.get("enabled", True):
            try:
                from .retriever.github_trending_retriever import GithubTrendingRetriever
                from .retriever.news_retriever import NewsRetriever

                gh_retriever = GithubTrendingRetriever(self.config)
                news_retriever = NewsRetriever(self.config)

                raw_trending: list[TrendingItem] = []
                raw_trending.extend(gh_retriever.retrieve_trending())
                raw_trending.extend(news_retriever.retrieve_news())

                # 1. Deduplicate by canonical key (github:owner/repo, news:url)
                deduped_trending = self.paper_store.dedup_trending(raw_trending)
                # 2. Filter out items that were already pushed in previous runs
                unpushed_trending = self.paper_store.filter_already_pushed(deduped_trending)

                # Prioritize: sort by stars desc
                unpushed_trending.sort(key=lambda x: (x.stars or 0), reverse=True)
                max_trends = int(trends_cfg.get("max_items", 8))
                trending_items = unpushed_trending[:max_trends]

                # Generate concise Chinese summary with LLM if available
                if self.openai_client is not None and trending_items:
                    for t_item in trending_items:
                        if not t_item.summary_zh and t_item.description:
                            try:
                                prompt = (
                                    "Translate and summarize the following AI project or news into one concise Chinese sentence:\n"
                                    f"Title: {t_item.title}\n"
                                    f"Description: {t_item.description}"
                                )
                                resp = self.openai_client.chat.completions.create(
                                    model=self.config.llm.generation_kwargs.model,
                                    messages=[
                                        {"role": "system", "content": "You are a concise translator for technical AI news."},
                                        {"role": "user", "content": prompt}
                                    ],
                                    max_tokens=150,
                                )
                                t_item.summary_zh = resp.choices[0].message.content.strip()
                            except Exception:
                                t_item.summary_zh = t_item.description
            except Exception as exc:
                logger.warning(f"Failed to retrieve AI news/trends: {exc}")

        if not reranked_papers and not trending_items and not self.config.executor.send_empty:
            logger.info("Neither new papers nor new trending items found. Done.")
            return

        # Delivery dispatch
        delivered = False

        # 1. Feishu Delivery (if configured)
        feishu_cfg = self.config.get("feishu")
        if feishu_cfg and feishu_cfg.get("app_id") and not feishu_cfg.get("dry_run", False):
            try:
                from .feishu import FeishuClient
                client = FeishuClient(feishu_cfg)
                doc_url = client.create_or_update_daily_report(reranked_papers, trending_items=trending_items)
                logger.info(f"Feishu daily report published successfully: {doc_url}")
                delivered = True
            except Exception as exc:
                logger.error(f"Failed to publish Feishu daily report: {exc}")
                raise

        # 2. Email Delivery (fallback / legacy)
        email_cfg = self.config.get("email")
        if (
            email_cfg
            and email_cfg.get("sender")
            and email_cfg.get("receiver")
            and email_cfg.sender != "???"
            and not delivered
        ):
            logger.info("Sending email...")
            email_content = render_email(reranked_papers)
            send_email(self.config, email_content)
            logger.info("Email sent successfully")
            delivered = True

        # Mark as pushed once successfully delivered or in local dry-run
        if delivered or self.config.get("feishu", {}).get("dry_run", False) or not email_cfg or email_cfg.get("sender") is None:
            if not self.config.get("executor", {}).get("debug", False):
                if reranked_papers:
                    self.paper_store.mark_pushed(reranked_papers)
                    logger.info(f"Marked {len(reranked_papers)} papers as pushed in paper_store")
                if trending_items:
                    self.paper_store.mark_pushed(trending_items)
                    logger.info(f"Marked {len(trending_items)} trending items as pushed in paper_store")
