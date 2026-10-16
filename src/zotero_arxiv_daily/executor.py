from datetime import datetime
import json
import random
import re
from typing import Any, Optional
import requests
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
            "- tags: array of 2-4 English keyword tags without hash symbol (e.g. [\"Agent\", \"Memory\", \"RL\", \"Harness\", \"RSI\"])\n"
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

    def fetch_github_readme(self, url: str) -> str:
        """Fetches the README markdown content from a GitHub repository."""
        if not url or "github.com" not in url.lower():
            return ""
        match = re.search(r"github\.com/([^/]+)/([^/#?]+)", url)
        if not match:
            return ""
        owner, repo = match.group(1), match.group(2).removesuffix(".git")
        headers = {"User-Agent": "Mozilla/5.0"}
        for branch in ["main", "master", "HEAD"]:
            raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md"
            try:
                resp = requests.get(raw_url, headers=headers, timeout=8)
                if resp.status_code == 200 and len(resp.text) > 50:
                    return resp.text
            except Exception:
                continue
        return ""

    def generate_app_note_sections(self, title: str, url: str, readme_text: str = "", tldr: str = "") -> tuple[dict[str, str], list[str]]:
        """Uses LLM to analyze a GitHub project, AI application, or Agent Skill into an engineering-oriented note."""
        if not self.openai_client:
            sections = {
                "overview": tldr or f"{title} 是一个实用的开源 AI 应用 / 工具项目。",
                "scenarios_and_triggers": "适用于自主智能体工作流执行、工具调用与本地开发环境自动化。",
                "quick_start": f"1. 克隆代码仓库: git clone {url}\n2. 安装相关依赖并配置环境变量。",
                "usage_examples": f"# 运行核心脚本或 CLI 命令\n# 具体请参阅仓库主页: {url}",
                "key_features_and_tips": "1. 规范入参与返回格式。\n2. 注意配置鉴权密钥与前置依赖版本。",
            }
            return sections, ["Tool", "Agent"]

        prompt = (
            f"请深度分析以下 GitHub 开源项目 / AI 应用 / Agent Skill，并生成一份面向实际工程落地的使用沉淀笔记：\n"
            f"项目名称: {title}\n"
            f"项目主页/URL: {url}\n"
            f"简介/TL;DR: {tldr}\n"
            f"README 内容摘要:\n{readme_text[:8000] if readme_text else '（暂未直接获取到完整 README，请结合项目名称与公开知识进行分析）'}\n\n"
            "请以严格的 JSON 格式输出，包含以下键（必须使用中文清晰陈述）：\n"
            "- overview: 1-2 句话精炼总结该项目的核心定位与解决的核心痛点。\n"
            "- scenarios_and_triggers: 详细分析其适用场景。特别如果是 Agent Skill 或工具，请务必具体写明：\n"
            "  1. 触发关键词与意图（Triggers: 用户说什么或什么场景下应该调用它）\n"
            "  2. 适用 Agent 角色\n"
            "  3. 典型使用时机\n"
            "- quick_start: 环境依赖与快速上手。列出具体安装命令（如 pip/npm/brew/docker/git clone）、前置依赖环境与必要环境变量/配置准备。\n"
            "- usage_examples: 具体使用方式与调用示例。给出具体的 CLI 命令行指令、代码调用片段（Python/TypeScript/Shell）、参数说明以及输入输出样例。\n"
            "- key_features_and_tips: 核心功能特性与避坑指南。列出核心配置项、注意事项或已知限制。\n"
            "- tags: 2-4个英文标签，如 [\"Agent\", \"Skill\", \"Memory\", \"Tool\", \"MAS\", \"DecisionModel\", \"Harness\", \"RSI\"]\n"
        )
        try:
            resp = self.openai_client.chat.completions.create(
                model=self.config.llm.generation_kwargs.model,
                messages=[
                    {"role": "system", "content": "你是一位资深的 AI Agent 架构师与系统工程师，擅长提炼 GitHub 开源项目与 Agent Skill 的核心用法与工程落地规范。"},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_tokens=1500,
            )
            content = resp.choices[0].message.content.strip()
            data = json.loads(content)
            sections = {
                "overview": data.get("overview", tldr or title),
                "scenarios_and_triggers": data.get("scenarios_and_triggers", ""),
                "quick_start": data.get("quick_start", ""),
                "usage_examples": data.get("usage_examples", ""),
                "key_features_and_tips": data.get("key_features_and_tips", ""),
            }
            tags = data.get("tags") or ["Agent", "Tool"]
            return sections, tags
        except Exception as exc:
            logger.warning(f"LLM app note generation fallback: {exc}")
            sections = {
                "overview": tldr or f"{title} 开源项目与工具方案。",
                "scenarios_and_triggers": "适用于自动化智能体工作流执行与工具链集成。",
                "quick_start": f"git clone {url}\ncd <repo> && pip install -r requirements.txt",
                "usage_examples": f"# 运行命令行或 API 调用\n# 详情参见: {url}",
                "key_features_and_tips": "确保环境依赖版本匹配与 API Key 正确配置。",
            }
            return sections, ["Agent", "Tool"]

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
                action = item.get("action", "ingest")
                doc_id = item.get("document_id", "")
                card_block_ids = item.get("card_block_ids", [])

                if action == "delete":
                    logger.info(f"User marked '{title}' for removal/deletion. Deleting card from document {doc_id} and permanently blacklisting...")
                    if doc_id and card_block_ids:
                        client.delete_document_blocks(doc_id, card_block_ids)
                    self.paper_store.mark_discarded(title, metadata={"url": url})
                    if url:
                        self.paper_store.mark_discarded(url)
                    continue

                if not title:
                    continue

                if self.paper_store.is_ingested(title) or (url and self.paper_store.is_ingested(url)):
                    logger.debug(f"Paper '{title}' has already been ingested. Skipping.")
                    continue

                is_github_or_tool = (
                    "github.com" in (url or "").lower()
                    or item.get("category") == "github_repo"
                    or any(s in (item.get("sources") or []) for s in ["github", "tool", "skill"])
                    or "skill" in title.lower()
                )

                logger.info(f"Ingesting user-confirmed {'GitHub tool/skill' if is_github_or_tool else 'paper'}: '{title}'...")
                paper = Paper(
                    source=item.get("sources", ["github" if is_github_or_tool else "arxiv"])[0] if item.get("sources") else ("github" if is_github_or_tool else "arxiv"),
                    title=title,
                    authors=[],
                    abstract=item.get("tldr", ""),
                    url=url,
                    affiliations=item.get("affiliations", []),
                    sources=item.get("sources", []),
                    tldr=item.get("tldr", ""),
                    tldr_zh=item.get("tldr", ""),
                )

                if is_github_or_tool:
                    readme_text = self.fetch_github_readme(url)
                    sections, tags = self.generate_app_note_sections(
                        title=title,
                        url=url,
                        readme_text=readme_text,
                        tldr=item.get("tldr", "")
                    )
                    paper.venue = "GitHub / Open Source Tool"
                else:
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

                if feishu_cfg.get("create_tasks", True):
                    try:
                        task_res = client.create_reading_task(
                            paper=paper,
                            note_url=note_url,
                            tags=tags,
                        )
                        task_guid = task_res.get("guid") or task_res.get("task", {}).get("guid")
                        logger.info(f"Created Lark Task for '{title}': guid={task_guid}")
                    except Exception as t_exc:
                        logger.warning(f"Notice: creating Lark task for '{title}': {t_exc}")

                self.paper_store.mark_ingested(
                    paper,
                    {
                        "title": title,
                        "url": url,
                        "wiki_url": note_url,
                        "tags": tags,
                    }
                )
                if doc_id and card_block_ids:
                    client.delete_document_blocks(doc_id, card_block_ids)
                ingested_urls.append(note_url)
                logger.info(f"Successfully ingested '{title}' into Wiki Knowledge Base: {note_url}")

            return ingested_urls
        except Exception as exc:
            logger.warning(f"Error during paper ingestion check: {exc}")
            return []

    def ingest_paper_by_url(self, url: str, category: Optional[str] = None) -> Optional[str]:
        """Directly ingests a paper or open-source tool/skill by URL into the Wiki Knowledge Base."""
        feishu_cfg = self.config.get("feishu")
        if not feishu_cfg:
            logger.warning("No feishu configuration found for ingest_paper_by_url")
            return None

        clean_url = url.strip()
        title = ""
        abstract = ""
        authors = []
        affiliations = []
        venue = None
        sources = []

        is_github_or_tool = (
            "github.com" in clean_url.lower()
            or category == "github_repo"
        )

        if is_github_or_tool:
            sources = ["github"]
            match = re.search(r"github\.com/([^/]+)/([^/#?]+)", clean_url)
            if match:
                title = f"{match.group(1)}/{match.group(2).removesuffix('.git')}"
            else:
                title = clean_url
            readme_text = self.fetch_github_readme(clean_url)
            sections, tags = self.generate_app_note_sections(title=title, url=clean_url, readme_text=readme_text)
            venue = "GitHub / Open Source Tool"
        elif "arxiv.org" in clean_url.lower():
            sources = ["arxiv"]
            import xml.etree.ElementTree as ET
            arxiv_match = re.search(r"(\d{4}\.\d{4,5})", clean_url)
            arxiv_id = arxiv_match.group(1) if arxiv_match else ""
            if arxiv_id:
                try:
                    api_url = f"https://export.arxiv.org/api/query?id_list={arxiv_id}"
                    resp = requests.get(api_url, timeout=10)
                    if resp.status_code == 200:
                        root = ET.fromstring(resp.text)
                        ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
                        entry = root.find("atom:entry", ns)
                        if entry is not None:
                            raw_t = entry.findtext("atom:title", default="", namespaces=ns)
                            title = " ".join(raw_t.split())
                            raw_abs = entry.findtext("atom:summary", default="", namespaces=ns)
                            abstract = " ".join(raw_abs.split())
                            for author_node in entry.findall("atom:author", ns):
                                a_name = author_node.findtext("atom:name", default="", namespaces=ns)
                                if a_name:
                                    authors.append(a_name)
                            comment_node = entry.findtext("arxiv:comment", default="", namespaces=ns)
                            if comment_node:
                                for v in ["NeurIPS", "ICLR", "ICML", "ACL", "EMNLP", "CVPR", "ICCV", "ECCV", "AAAI"]:
                                    if v.lower() in comment_node.lower():
                                        venue = v
                                        break
                except Exception as exc:
                    logger.warning(f"Failed to query arXiv API for {arxiv_id}: {exc}")
            
            if not title:
                title = f"Paper ({arxiv_id or clean_url})"

            paper_obj = Paper(
                source="arxiv",
                title=title,
                authors=authors,
                abstract=abstract,
                url=clean_url,
                affiliations=affiliations,
                sources=sources,
                venue=venue,
            )
            sections, tags = self.generate_reading_note_sections(paper_obj)
        else:
            sources = ["web"]
            title = clean_url
            paper_obj = Paper(
                source="web",
                title=title,
                authors=[],
                abstract="",
                url=clean_url,
                affiliations=[],
                sources=sources,
            )
            sections, tags = self.generate_reading_note_sections(paper_obj)

        from .feishu import FeishuClient
        client = FeishuClient(feishu_cfg)

        paper = Paper(
            source=sources[0] if sources else "web",
            title=title,
            authors=authors,
            abstract=abstract,
            url=clean_url,
            affiliations=affiliations,
            sources=sources,
            venue=venue,
            tldr=sections.get("core_summary", ""),
            tldr_zh=sections.get("core_summary", ""),
        )

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

        if feishu_cfg.get("create_tasks", True):
            try:
                task_res = client.create_reading_task(
                    paper=paper,
                    note_url=note_url,
                    tags=tags,
                )
                task_guid = task_res.get("guid") or task_res.get("task", {}).get("guid")
                logger.info(f"Created Lark Task for '{title}': guid={task_guid}")
            except Exception as t_exc:
                logger.warning(f"Notice: creating Lark task for '{title}': {t_exc}")

        self.paper_store.mark_ingested(
            paper,
            {
                "title": title,
                "url": clean_url,
                "wiki_url": note_url,
                "tags": tags,
            }
        )
        if clean_url:
            self.paper_store.mark_ingested(clean_url, {"title": title, "wiki_url": note_url})
        logger.info(f"Directly ingested '{title}' into Wiki Knowledge Base: {note_url}")
        return note_url

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

        # Quota allocation: balance papers and trending items to adhere to total_daily_quota (default 15)
        trends_cfg = self.config.get("news_and_trends") or {}
        total_daily_quota = self.config.executor.get("total_daily_quota")
        if total_daily_quota is not None:
            total_quota = int(total_daily_quota)
            max_trends = min(int(trends_cfg.get("max_items", 4)), max(1, total_quota // 3))
            paper_quota = max(1, total_quota - max_trends)
        else:
            paper_quota = int(self.config.executor.get("max_paper_num", 15))
            max_trends = int(trends_cfg.get("max_items", 4))

        reranked_papers: list[Paper] = []
        if len(new_papers) > 0:
            logger.info("Reranking papers against interest corpus...")
            reranked_papers = self.reranker.rerank(new_papers, corpus)
            reranked_papers = reranked_papers[:paper_quota]

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
                if self.config.executor.get("total_daily_quota"):
                    max_trends = min(int(trends_cfg.get("max_items", 4)), max(1, int(self.config.executor.total_daily_quota) // 3))
                else:
                    max_trends = int(trends_cfg.get("max_items", 4))
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
        is_feishu_dry_run = feishu_cfg.get("dry_run", False) if feishu_cfg else False
        if isinstance(is_feishu_dry_run, str):
            is_feishu_dry_run = is_feishu_dry_run.strip().lower() in ("true", "1", "yes")

        if feishu_cfg and feishu_cfg.get("app_id") and not is_feishu_dry_run:
            try:
                from .feishu import FeishuClient
                client = FeishuClient(feishu_cfg)

                doc_url = client.create_or_update_daily_report(reranked_papers, trending_items=trending_items)
                logger.info(f"Feishu candidate document updated successfully: {doc_url}")
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
        if delivered or is_feishu_dry_run or not email_cfg or email_cfg.get("sender") is None:
            if not self.config.get("executor", {}).get("debug", False):
                if reranked_papers:
                    self.paper_store.mark_pushed(reranked_papers)
                    logger.info(f"Marked {len(reranked_papers)} papers as pushed in paper_store")
                if trending_items:
                    self.paper_store.mark_pushed(trending_items)
                    logger.info(f"Marked {len(trending_items)} trending items as pushed in paper_store")
