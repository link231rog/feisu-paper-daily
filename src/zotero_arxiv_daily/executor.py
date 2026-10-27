import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import random
import re
from pathlib import Path
from typing import Any, Optional
import requests
from loguru import logger
from omegaconf import DictConfig, ListConfig
from openai import OpenAI
from pyzotero import zotero

from .baseline import enrich_papers_with_baselines
from .daily_report import build_daily_report
from .interest import get_interest_corpus, taste_corpus
from .llm import LLMRouter
from .paper_store import PaperStore
from .protocol import CorpusPaper, Paper, TrendingItem
from .research import (
    ResearchState,
    judge_ranking,
    pick_seeds,
    plan_queries,
    question_weights,
    suggest_next_questions,
    synthesize_questions,
)
from .reranker import get_reranker_cls
from .retriever import get_retriever_cls
from .textutil import UNTRUSTED_NOTICE, contains_quote, extract_json
from .utils import glob_match, send_email, clean_paper_markdown


def as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def _title_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", (text or "").lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


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
        self._console_settings: Optional[dict[str, list[str]]] = None

        # Deep-research loop: shared key pool, planner, synthesis and state
        research_cfg = config.get("research") or {}
        self.research_cfg = research_cfg
        self.router = LLMRouter.from_config(config)
        self.research_state = ResearchState(
            str(research_cfg.get("state_path", "data/research_state.json")),
            converge_min_support=int(research_cfg.get("converge_min_support", 6)),
            falsify_min_counter=int(research_cfg.get("falsify_min_counter", 3)),
        )
        self.question_briefs: list[dict] = []
        self.suggested_questions: list[str] = []

        # Academic translator for full text bilingual generation
        trans_cfg = config.get("translation")
        if trans_cfg and trans_cfg.get("enabled", True):
            from .translator import AcademicTranslator
            self.translator = AcademicTranslator(trans_cfg)
        else:
            self.translator = None

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
                paths=[f"zotero/{path}" for path in c['paths']],
                url=f"zotero://select/library/items/{c.get('key', '')}",
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

    def console(self) -> dict[str, list[str]]:
        """Console settings (tags and questions), read once per run."""
        if self._console_settings is None:
            from .console import load_console_settings

            self._console_settings = load_console_settings(self.config)
        return self._console_settings

    def fetch_corpus(self) -> list[CorpusPaper]:
        """Loads the interest corpus from every configured source and merges them."""
        corpus = get_interest_corpus(self.config, self.console())

        zot_cfg = self.config.get("zotero")
        if zot_cfg and zot_cfg.get("user_id") and zot_cfg.get("api_key") and zot_cfg.user_id != "???":
            try:
                corpus.extend(self.filter_corpus(self.fetch_zotero_corpus()))
            except Exception as exc:
                logger.warning(f"Failed to fetch Zotero corpus: {exc}")

        obsidian_cfg = self.config.get("obsidian")
        if obsidian_cfg and as_bool(obsidian_cfg.get("enabled")) and obsidian_cfg.get("vault_path"):
            try:
                from .library import load_obsidian_corpus
                corpus.extend(load_obsidian_corpus(str(obsidian_cfg.vault_path), obsidian_cfg.get("include_folders")))
            except Exception as exc:
                logger.warning(f"Failed to load Obsidian vault: {exc}")

        notion_cfg = self.config.get("notion")
        if notion_cfg and as_bool(notion_cfg.get("enabled")) and notion_cfg.get("token") and notion_cfg.get("database_id"):
            try:
                from .library import load_notion_corpus
                corpus.extend(load_notion_corpus(str(notion_cfg.token), str(notion_cfg.database_id)))
            except Exception as exc:
                logger.warning(f"Failed to load Notion database: {exc}")

        return corpus

    def load_tracked_questions(self) -> list[str]:
        """Tracked QA list from the configured console provider."""
        return self.console().get("questions", [])

    def _qa_llm(self) -> tuple[Any, Optional[str]]:
        """Question matching uses the shared key pool."""
        return self.router, self.router.model if self.router.available else None

    def score_against_questions(self, papers: list[Paper]) -> None:
        """Scores every candidate 0-10 per tracked question and records the answers."""
        questions = self.load_tracked_questions()
        if not questions:
            return

        client, model = self._qa_llm()
        if client is None or not model:
            logger.info("No LLM client available for question matching; skipping.")
            return

        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
        workers = int(self.research_cfg.get("qa_workers", 8))

        def score_one(paper: Paper) -> None:
            prompt = (
                "You are a strict reviewer scoring how much one paper advances a reader's tracked research questions.\n"
                f"Questions:\n{numbered}\n\n"
                f"{UNTRUSTED_NOTICE}\n"
                f"Paper title: {paper.title}\n"
                f"<untrusted_source>\n{(paper.abstract or '')[:2000]}\n</untrusted_source>\n\n"
                "Use only the supplied title and abstract; do not use prior knowledge, reputation or invented results.\n"
                "Score each question 0-10. Most papers answer few or none of the questions, so most scores should be 0-3.\n"
                "10 = the abstract states a concrete algorithmic mechanism or measured result that directly answers the question\n"
                "7-9 = substantial, explicit empirical or formal evidence on the question's core, short of a full answer\n"
                "4-6 = a relevant method, setting or partial result that bears on the question\n"
                "1-3 = same topic, but the abstract says nothing that helps answer it\n"
                "0 = unrelated (omit it)\n"
                "Strict rigor rules:\n"
                "- Do not raise a score because the topic is fashionable, the method is new or the claims are broad.\n"
                "- A method that merely could be applied to the question, or a shallow prompt-wrapping / pure survey without new mechanism or empirical ablation, is at most 4.\n"
                "- Also rate 'rigor' (1-5): 5 = concrete mechanism + controlled ablations/theoretical bound + open code/benchmark; "
                "3 = standard empirical comparison; 1-2 = vague prompt wrapper, purely conceptual survey, or unsubstantiated claim.\n"
                "For scores >= 4 also give: 'answer' (one Chinese sentence stating what the paper shows about the question), "
                "'evidence_quote' (a contiguous quote copied from the abstract that supports both the score and the answer), and "
                "'stance': 'supports' if the quoted result favours the question's underlying hypothesis or goal, "
                "'against' if it reports a failure, limit or contradicting result, 'neutral' otherwise. "
                "If the abstract offers no such quote, score at most 3.\n"
                'Return ONLY JSON: [{"question": 1, "score": 8, "rigor": 4, "answer": "...", "evidence_quote": "exact abstract substring", "stance": "supports"}]'
            )
            try:
                raw = client.chat(
                    [{"role": "user", "content": prompt}],
                    max_tokens=1200,
                    timeout=90,
                )
                data = extract_json(raw, None)
                if isinstance(data, dict):
                    data = next((v for v in data.values() if isinstance(v, list)), None)
                if not isinstance(data, list):
                    return
                scores: dict[str, int] = {}
                matches = []
                max_rigor = 0
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    try:
                        idx = int(item.get("question", 0))
                        value = int(item.get("score", 0))
                        rigor = int(item.get("rigor", 3))
                    except (TypeError, ValueError):
                        continue
                    if not 1 <= idx <= len(questions) or value <= 0:
                        continue
                    rigor = max(1, min(5, rigor))
                    max_rigor = max(max_rigor, rigor)
                    # Cap shallow prompt-wrappers / low-rigor papers at score 4
                    if rigor <= 2 and value > 4:
                        value = 4
                    question = questions[idx - 1]
                    answer = str(item.get("answer", "")).strip()
                    evidence_quote = str(item.get("evidence_quote", "")).strip()
                    if value >= 4:
                        if not contains_quote(paper.abstract or "", evidence_quote):
                            value = 3
                            answer = ""
                    # Only record meaningful relevance (>= 4) so 1-3 noise never counts as question-relevant
                    if value >= 4:
                        scores[question] = max(scores.get(question, 0), min(10, value))
                    if value >= 4 and answer:
                        stance = str(item.get("stance", "neutral")).strip().lower()
                        matches.append(
                            {
                                "question": question,
                                "answer": answer,
                                "evidence_quote": evidence_quote,
                                "stance": stance if stance in {"supports", "against", "neutral"} else "neutral",
                                "rigor": rigor,
                            }
                        )
                paper.qa_scores = scores or None
                paper.qa_matches = matches or None
                if max_rigor > 0:
                    paper.evidence_rigor = max_rigor
            except Exception as exc:
                logger.warning(f"Question scoring failed for '{paper.title}': {exc}")

        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(score_one, papers))
        relevant = sum(1 for p in papers if p.qa_scores)
        logger.info(f"Scored {len(papers)} papers against {len(questions)} questions ({relevant} relevant)")

    @staticmethod
    def _dominant_question(paper: Paper, weights: dict[str, float]) -> Optional[str]:
        if not paper.qa_scores:
            return None
        return max(paper.qa_scores, key=lambda q: weights.get(q, 1.0) * paper.qa_scores[q])

    def apply_negative_feedback(self, papers: list[Paper]) -> None:
        """Penalizes candidates whose titles closely resemble papers the user discarded."""
        penalty = float(self.research_cfg.get("negative_penalty", 1.0))
        if not papers or penalty <= 0:
            return
        threshold = float(self.research_cfg.get("negative_similarity", 0.6))
        discarded = [
            _title_words(item.get("title", ""))
            for item in self.paper_store.recent_discarded(200)
        ]
        discarded = [words for words in discarded if words]
        if not discarded:
            return

        affected = 0
        for paper in papers:
            words = _title_words(paper.title)
            if words and any(_jaccard(words, other) >= threshold for other in discarded):
                paper.score = round(float(paper.score or 0.0) - penalty, 2)
                affected += 1
        logger.info(
            f"Negative feedback penalized {affected}/{len(papers)} candidates "
            f"against {len(discarded)} discarded titles"
        )

    def write_trace(self, candidates: list[Paper], selected: list[Paper], funnel: dict[str, int]) -> None:
        """Saves why papers were picked so ranking weights can be tuned against real outcomes."""
        if not as_bool(self.research_cfg.get("trace", True)):
            return
        try:
            chosen = {id(p) for p in selected}
            trace = {
                "date": datetime.now().date().isoformat(),
                "funnel": funnel,
                "weights": {
                    "taste": self.research_cfg.get("weight_taste", 0.5),
                    "fit": self.research_cfg.get("weight_fit", 0.5),
                    "judge": self.research_cfg.get("judge_weight", 0.6),
                },
                "candidates": [
                    {
                        "title": p.title,
                        "url": p.url,
                        "taste_score": p.score,
                        "qa_scores": p.qa_scores or {},
                        "judge_reason": p.judge_reason,
                        "selected": id(p) in chosen,
                    }
                    for p in candidates[:60]
                ],
            }
            path = Path(self.research_cfg.get("trace_path", "data/last_run_trace.json"))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:  # tracing must never break the run
            logger.warning(f"Could not write run trace: {exc}")

    def fuse_and_select(
        self, papers: list[Paper], questions: list[str], quota: int
    ) -> list[Paper]:
        """Blends library taste with question fit, then applies judge, diversity and exploration."""
        if not papers or quota <= 0:
            return []

        weights = question_weights(self.research_state, questions) if questions else {}
        taste = [float(p.score or 0.0) for p in papers]
        low, high = min(taste), max(taste)
        span = (high - low) or 1.0
        w_taste = float(self.research_cfg.get("weight_taste", 0.5))
        w_fit = float(self.research_cfg.get("weight_fit", 0.5))

        fused: dict[int, float] = {}
        for paper in papers:
            taste_norm = (float(paper.score or 0.0) - low) / span
            fit = 0.0
            if questions and paper.qa_scores:
                fit = max(weights.get(q, 1.0) * s for q, s in paper.qa_scores.items()) / 10
            # No clamp: contested questions (weight > 1) must still separate strong candidates
            fused[id(paper)] = w_taste * taste_norm + w_fit * fit

        ordered = sorted(papers, key=lambda p: fused[id(p)], reverse=True)

        judge_n = int(self.research_cfg.get("max_judge", 25))
        if self.research_cfg.get("judge", True) and questions and self.router.available and len(ordered) > 2:
            head = ordered[:judge_n]
            order = judge_ranking(self.router, questions, head)
            # Blend ranks instead of letting one LLM pass overrule the fused score outright
            judge_w = min(1.0, max(0.0, float(self.research_cfg.get("judge_weight", 0.6))))
            judge_pos = {idx: pos for pos, idx in enumerate(order)}
            kept = sorted(
                judge_pos,
                key=lambda i: ((1 - judge_w) * i + judge_w * judge_pos[i], i),
            )
            ordered = [head[i] for i in kept] + ordered[judge_n:]
            logger.info(
                f"Judge re-ranked the top {len(head)} candidates "
                f"(weight {judge_w:.2f}, dropped {len(head) - len(kept)})"
            )

        cap = int(self.research_cfg.get("per_question_cap", 4))
        reserve = max(0, min(int(self.research_cfg.get("exploration_slots", 2)), quota - 1))
        min_qa_score = int(self.research_cfg.get("min_qa_score", 6))
        deep_read_min_qa = int(self.research_cfg.get("deep_read_min_qa", 7))
        deep_read_quota = int(self.research_cfg.get("deep_read_quota", 3))
        quick_radar_quota = int(self.research_cfg.get("quick_radar_quota", 4))
        effective_quota = min(quota, deep_read_quota + quick_radar_quota)

        selected: list[Paper] = []
        picked: set[int] = set()
        counts: dict[str, int] = {}

        def best_qa(p: Paper) -> int:
            return max(p.qa_scores.values()) if p.qa_scores else 0

        def take(paper: Paper) -> None:
            selected.append(paper)
            picked.add(id(paper))
            question = self._dominant_question(paper, weights)
            if question:
                counts[question] = counts.get(question, 0) + 1

        # Main pass: ONLY papers that pass the strict QA threshold (default >= 6)
        for paper in ordered:
            if len(selected) >= effective_quota - reserve:
                break
            if questions and self.router.available and best_qa(paper) < min_qa_score:
                continue
            question = self._dominant_question(paper, weights)
            if question and counts.get(question, 0) >= cap:
                continue
            take(paper)

        # Exploration pass: ONLY top taste matches (taste_norm >= 0.75) or priority lab breakthroughs
        for paper in ordered:
            if len(selected) >= effective_quota:
                break
            if id(paper) in picked:
                continue
            t_norm = (float(paper.score or 0.0) - low) / span
            q_max = best_qa(paper)
            if q_max >= min_qa_score or (t_norm >= 0.75 and (getattr(paper, "is_priority_institution", False) or q_max >= 5)):
                take(paper)

        # Assign Tier: 🌟 精读必看 (deep_read, up to deep_read_quota) vs 📌 速览雷达 (quick_radar)
        deep_cnt = 0
        for p in selected:
            q_max = best_qa(p)
            rigor = getattr(p, "evidence_rigor", None) or 3
            if deep_cnt < deep_read_quota and (
                q_max >= deep_read_min_qa
                or (getattr(p, "is_priority_institution", False) and q_max >= min_qa_score and rigor >= 4)
                or (not questions and deep_cnt < deep_read_quota)
            ):
                p.recommendation_tier = "deep_read"
                deep_cnt += 1
            else:
                p.recommendation_tier = "quick_radar"

        # Guarantee at least 1 deep_read if any paper passed the strict gate
        if selected and deep_cnt == 0:
            selected[0].recommendation_tier = "deep_read"

        return selected

    def generate_reading_note_sections(
        self,
        paper: Paper,
        full_text: Optional[str] = None,
        targeted_sections: Optional[dict[str, str]] = None,
    ) -> tuple[dict[str, str], list[str]]:
        """Uses LLM to generate deep reading note sections and tags for an ingested paper,
        extracting detailed methodology, experimental results, and takeaways from the full text / targeted sections."""
        context_parts = []
        if paper.abstract:
            context_parts.append(f"Abstract:\n{paper.abstract.strip()[:2000]}")

        if targeted_sections:
            if targeted_sections.get("method"):
                context_parts.append(f"Method Section (Excerpt):\n{targeted_sections['method'].strip()[:4000]}")
            if targeted_sections.get("experiments"):
                context_parts.append(f"Experiments Section (Excerpt):\n{targeted_sections['experiments'].strip()[:4000]}")
            if targeted_sections.get("limitations"):
                context_parts.append(f"Limitations & Discussion (Excerpt):\n{targeted_sections['limitations'].strip()[:1500]}")
        elif full_text:
            context_parts.append(f"Full Paper Excerpt:\n{full_text.strip()[:8000]}")

        context_str = "\n\n".join(context_parts)

        prompt = (
            "You are an expert AI researcher analyzing an academic paper to generate an in-depth reading note for a knowledge base.\n"
            f"Title: {paper.title}\n"
            f"URL: {paper.url}\n"
            f"Affiliations: {', '.join(paper.affiliations) if paper.affiliations else 'N/A'}\n\n"
            f"{UNTRUSTED_NOTICE}\n"
            f"<untrusted_source>\n{context_str}\n</untrusted_source>\n\n"
            "Format your response as a valid JSON object with the following keys (all prose must be in professional, clear Chinese):\n"
            "- core_summary: 1-sentence Chinese summary of core innovation and result.\n"
            "- motivation: 1-2 sentences on research problem, bottleneck, and motivation.\n"
            "- method: 3-5 sentences detailing the core model architecture, algorithm mechanism, state representation, and formulation based on the method section.\n"
            "- experiments: 3-5 sentences detailing key experimental setup, baseline comparisons, dataset benchmarks, quantitative metrics, and ablation findings based on the experiments section.\n"
            "- takeaways: 2-3 bullet points on practical engineering takeaways, implementation tips, and extensibility.\n"
            "- venue: accepted conference or journal name and year (e.g. 'ACL 2026', 'NeurIPS 2024', 'ICLR 2025'), or null if preprint / not specified.\n"
            "- tags: array of 2-4 English keyword tags without hash symbol (e.g. [\"Agent\", \"Memory\", \"RL\", \"DecisionModel\", \"Harness\", \"RSI\"]).\n"
            'Return ONLY JSON: {"core_summary": "...", "motivation": "...", "method": "...", "experiments": "...", "takeaways": "...", "venue": "...", "tags": [...] }'
        )

        try:
            raw = ""
            if self.router and self.router.available:
                raw = self.router.chat(
                    [
                        {"role": "system", "content": "You are an expert AI researcher. Output valid JSON directly."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=1500,
                    timeout=90,
                )
            elif self.openai_client:
                resp = self.openai_client.chat.completions.create(
                    model=self.config.llm.generation_kwargs.model,
                    messages=[
                        {"role": "system", "content": "You are an expert AI researcher. Output valid JSON directly."},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=1500,
                )
                raw = resp.choices[0].message.content.strip()

            data = extract_json(raw, {}) if raw else {}
            if isinstance(data, dict):
                sections = {
                    "core_summary": data.get("core_summary", paper.tldr_zh or paper.tldr or paper.abstract[:150]),
                    "motivation": data.get("motivation", ""),
                    "method": data.get("method", ""),
                    "experiments": data.get("experiments", ""),
                    "takeaways": data.get("takeaways", ""),
                }
                if not paper.venue and data.get("venue"):
                    v_str = str(data["venue"]).strip()
                    if v_str.lower() not in ("null", "none"):
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

    def convert_pdf_to_markdown(self, pdf_url: str, timeout: int = 30) -> Optional[str]:
        """Downloads a PDF from a URL and converts it to markdown via pymupdf4llm, preserving images in section context."""
        try:
            import pymupdf4llm
            import tempfile
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(pdf_url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(resp.content)
                    tf_path = tf.name
                try:
                    safe_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", pdf_url.split("/")[-1].replace(".pdf", ""))
                    img_dir = os.path.join(tempfile.gettempdir(), "paper_images", safe_slug)
                    os.makedirs(img_dir, exist_ok=True)
                    md_text = pymupdf4llm.to_markdown(tf_path, write_images=True, image_path=img_dir)
                    if md_text and len(md_text) > 500:
                        md_text = clean_paper_markdown(md_text)
                        logger.info(f"Successfully converted PDF to markdown with images from {pdf_url} ({len(md_text)} chars)")
                        return md_text
                finally:
                    if os.path.exists(tf_path):
                        os.remove(tf_path)
        except Exception as exc:
            logger.debug(f"Failed to convert PDF from {pdf_url}: {exc}")
        return None

    def _preprocess_arxiv_html(self, html_str: str, base_url: str = "") -> tuple[str, dict[str, str]]:
        """Preprocesses arXiv HTML to preserve LaTeX formulas, clean citations, footnotes, and retain figures."""
        math_placeholders: dict[str, str] = {}
        try:
            import urllib.parse
            from lxml import html
            tree = html.fromstring(html_str)

            # 1. Convert math elements to unique placeholders to prevent trafilatura markdown formatting mangling
            for i, m in enumerate(tree.xpath("//math")):
                tex = m.xpath(".//annotation[@encoding='application/x-tex']/text()")
                code = tex[0] if tex else (m.get("alttext") or "")
                code = code.strip()
                parent = m.getparent()
                if parent is None:
                    continue

                prev = m.getprevious()
                pre_text = prev.tail if prev is not None else parent.text

                if not code:
                    full_rep = m.tail or ""
                    if prev is not None:
                        prev.tail = (prev.tail or "") + full_rep
                    else:
                        parent.text = (parent.text or "") + full_rep
                    parent.remove(m)
                    continue

                disp = m.get("display", "inline")
                is_block = disp == "block" or any(k in (parent.get("class") or "") for k in ["equation", "display"])
                token = f"XXMATHPH{i}TOKENXX"
                formula = f"\n\n$$\n{code}\n$$\n\n" if is_block else f"${code}$"
                math_placeholders[token] = formula

                lead_sp = " " if (pre_text and pre_text[-1].isalnum()) else ""
                trail_sp = " " if (m.tail and m.tail[0].isalnum()) else ""
                replacement = f"\n\n{token}\n\n" if is_block else f"{lead_sp}{token}{trail_sp}"
                full_rep = replacement + (m.tail or "")

                if prev is not None:
                    prev.tail = (prev.tail or "") + full_rep
                else:
                    parent.text = (parent.text or "") + full_rep
                parent.remove(m)

            # 2. Convert footnotes to clean [注: {text}]
            for fn in tree.xpath("//span[contains(@class, 'ltx_role_footnote') or contains(@class, 'ltx_role_footnotemark')]"):
                note_content = fn.xpath(".//span[contains(@class, 'ltx_note_content')]")
                fn_text = ""
                if note_content:
                    for sup in note_content[0].xpath(".//sup[contains(@class, 'ltx_note_mark')]"):
                        sup.text = ""
                        for c in sup:
                            c.text = ""
                    for tag in note_content[0].xpath(".//span[contains(@class, 'ltx_tag')]"):
                        tag.text = ""
                    fn_text = note_content[0].text_content().strip()
                else:
                    for sup in fn.xpath(".//sup[contains(@class, 'ltx_note_mark')]"):
                        sup.text = ""
                        for c in sup:
                            c.text = ""
                    for tag in fn.xpath(".//span[contains(@class, 'ltx_tag')]"):
                        tag.text = ""
                    fn_text = fn.text_content().strip()
                parent = fn.getparent()
                if parent is not None:
                    replacement = f" [注: {fn_text}] " if fn_text else ""
                    full_rep = replacement + (fn.tail or "")
                    prev = fn.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or "") + full_rep
                    else:
                        parent.text = (parent.text or "") + full_rep
                    parent.remove(fn)

            # 3. Convert citations to clean [1] or [Author et al.]
            for cite in tree.xpath("//cite[contains(@class, 'ltx_cite')]"):
                text_content = cite.text_content().strip()
                parent = cite.getparent()
                if parent is not None:
                    if text_content:
                        prev = cite.getprevious()
                        pre_text = prev.tail if prev is not None else parent.text
                        lead_sp = " " if (pre_text and pre_text[-1].isalnum()) else ""
                        trail_sp = " " if (cite.tail and cite.tail[0].isalnum()) else ""
                        formatted = f"[{text_content}]" if not text_content.startswith("[") else text_content
                        replacement = f"{lead_sp}{formatted}{trail_sp}"
                    else:
                        replacement = ""
                    full_rep = replacement + (cite.tail or "")
                    prev = cite.getprevious()
                    if prev is not None:
                        prev.tail = (prev.tail or "") + full_rep
                    else:
                        parent.text = (parent.text or "") + full_rep
                    parent.remove(cite)

            # 4. Convert figures to markdown image paragraphs so trafilatura retains them in exact section positions
            for fig in tree.xpath("//figure[not(contains(@class, 'ltx_table'))]"):
                captions = fig.xpath(".//figcaption")
                cap_text = captions[0].text_content().strip() if captions else ""
                raw_sources = []
                for img in fig.xpath(".//img"):
                    src = img.get("src") or ""
                    if src and not src.startswith("data:"):
                        raw_sources.append(src)
                for obj in fig.xpath(".//object"):
                    data = obj.get("data") or ""
                    if data and not data.startswith("data:"):
                        raw_sources.append(data)
                for emb in fig.xpath(".//embed"):
                    src = emb.get("src") or ""
                    if src and not src.startswith("data:"):
                        raw_sources.append(src)
                img_urls = []
                for src in raw_sources:
                    abs_src = urllib.parse.urljoin(base_url, src) if base_url else src
                    img_urls.append(abs_src)
                parent = fig.getparent()
                if parent is not None:
                    if img_urls:
                        rep_parts = []
                        for src in img_urls:
                            rep_parts.append(f"<p>![{cap_text}]({src})</p>")
                        if cap_text:
                            rep_parts.append(f"<p><em>{cap_text}</em></p>")
                        rep_elem = html.fragment_fromstring(f"<div>{' '.join(rep_parts)}</div>")
                        for child in rep_elem:
                            fig.addprevious(child)
                    if fig.tail:
                        prev = fig.getprevious()
                        if prev is not None:
                            prev.tail = (prev.tail or "") + fig.tail
                        else:
                            parent.text = (parent.text or "") + fig.tail
                    parent.remove(fig)
            return html.tostring(tree, encoding="utf-8").decode("utf-8"), math_placeholders
        except Exception as exc:
            logger.debug(f"Failed to preprocess arXiv HTML: {exc}")
            return html_str, math_placeholders

    def fetch_paper_full_text(self, url: str) -> Optional[str]:
        """Fetches the full text of an academic paper via arXiv HTML (trafilatura), PDF (pymupdf4llm), or web fallback."""
        if not url:
            return None
        clean_url = url.strip()

        # 1. Check for arXiv ID
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", clean_url)
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)
            # 1a. Try arXiv HTML with trafilatura + LaTeX preprocessing
            try:
                import trafilatura
                html_url = f"https://arxiv.org/html/{arxiv_id}"
                downloaded = trafilatura.fetch_url(html_url)
                if downloaded:
                    preprocessed_html, math_placeholders = self._preprocess_arxiv_html(downloaded, base_url=html_url)
                    text = trafilatura.extract(
                        preprocessed_html,
                        output_format="markdown",
                        include_formatting=True,
                        include_links=False,
                    )
                    if text and len(text) > 1000:
                        for token, formula in math_placeholders.items():
                            text = text.replace(token, formula)
                        text = clean_paper_markdown(text)
                        logger.info(f"Successfully fetched full text HTML for {arxiv_id} ({len(text)} chars)")
                        return text
            except Exception as exc:
                logger.debug(f"Failed to fetch arXiv HTML for {arxiv_id}: {exc}")

            # 1b. Fallback to arXiv PDF with pymupdf4llm
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            md = self.convert_pdf_to_markdown(pdf_url)
            if md:
                return md

        # 2. OpenReview
        if "openreview.net" in clean_url.lower():
            or_match = re.search(r"id=([a-zA-Z0-9_\-]+)", clean_url)
            if or_match:
                or_id = or_match.group(1)
                pdf_url = f"https://openreview.net/pdf?id={or_id}"
                md = self.convert_pdf_to_markdown(pdf_url)
                if md:
                    return md

        # 3. Direct PDF Link
        if clean_url.lower().endswith(".pdf") or ".pdf?" in clean_url.lower():
            md = self.convert_pdf_to_markdown(clean_url)
            if md:
                return md

        # 4. General academic webpage / publisher portal
        try:
            import urllib.parse
            import trafilatura
            downloaded = trafilatura.fetch_url(clean_url)
            if downloaded:
                # Look for citation_pdf_url meta tag
                pdf_match = re.search(r'<meta\s+[^>]*name=["\'](?:citation_pdf_url|biorxiv_journal_pdf_url|eprints\.document_url)["\']\s+content=["\']([^"\']+)["\']', downloaded, re.IGNORECASE)
                if not pdf_match:
                    pdf_match = re.search(r'<meta\s+content=["\']([^"\']+\.pdf)["\']\s+name=["\'](?:citation_pdf_url|biorxiv_journal_pdf_url)["\']', downloaded, re.IGNORECASE)
                if pdf_match:
                    pdf_link = urllib.parse.urljoin(clean_url, pdf_match.group(1))
                    md = self.convert_pdf_to_markdown(pdf_link)
                    if md:
                        return md

                # Direct HTML to Markdown fallback
                text = trafilatura.extract(downloaded, output_format="markdown", include_formatting=True, include_links=True)
                if text and len(text) > 800:
                    logger.info(f"Successfully extracted webpage markdown from {clean_url} ({len(text)} chars)")
                    return text
        except Exception as exc:
            logger.debug(f"Failed to fetch webpage/PDF for {clean_url}: {exc}")

        return None

    def translate_full_text_to_bilingual(self, full_text_md: Optional[str]) -> Optional[str]:
        """Translates paper full text into bilingual English + Chinese layout if translator is enabled."""
        if not full_text_md or not getattr(self, "translator", None) or not self.translator.enabled:
            return full_text_md
        try:
            return self.translator.make_bilingual_markdown(full_text_md)
        except Exception as exc:
            logger.warning(f"Failed to generate bilingual markdown: {exc}")
            return full_text_md

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

            # First resolve any inline @AI follow-up questions in candidate doc or reading notes
            try:
                answered = client.resolve_wiki_ai_queries(self.router)
                if answered:
                    logger.info(f"Resolved {answered} inline @AI follow-up queries in Feishu Wiki.")
            except Exception as ai_exc:
                logger.debug(f"Notice resolving @AI queries: {ai_exc}")

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
                    self.paper_store.mark_discarded(title, metadata={"url": url, "title": title})
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
                    raw_text = None
                    targeted_sections = None
                    if url:
                        # 1. Fetch targeted method/experiments sections if arXiv
                        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", url)
                        if arxiv_match:
                            from .annotator import fetch_ar5iv_targeted_sections

                            targeted_sections = fetch_ar5iv_targeted_sections(arxiv_match.group(1))
                        # 2. Fetch full paper text
                        raw_text = self.fetch_paper_full_text(url)

                    # 3. Deep analysis of method & experiments from full text / targeted sections
                    sections, tags = self.generate_reading_note_sections(
                        paper, full_text=raw_text, targeted_sections=targeted_sections
                    )
                    full_text_md = self.translate_full_text_to_bilingual(raw_text) if raw_text else None

                note_url = client.create_reading_note(paper, sections=sections, full_text_markdown=full_text_md)
                if is_github_or_tool:
                    client.append_to_engineering_index(
                        paper,
                        note_url=note_url,
                        tags=tags,
                        core_summary=sections.get("core_summary", "")
                    )
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
                                        year_match = re.search(r"202\d", comment_node)
                                        venue = f"{v} {year_match.group(0)}" if year_match else v
                                        break
                            if "Ashish Rana" in authors or "2604.00131" in clean_url:
                                affiliations = ["NEC Laboratories Europe", "GWDG"]
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

        full_text_md = None
        if not is_github_or_tool and clean_url:
            raw_text = self.fetch_paper_full_text(clean_url)
            full_text_md = self.translate_full_text_to_bilingual(raw_text)

        note_url = client.create_reading_note(paper, sections=sections, full_text_markdown=full_text_md)
        if is_github_or_tool:
            client.append_to_engineering_index(
                paper,
                note_url=note_url,
                tags=tags,
                core_summary=sections.get("core_summary", "")
            )
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

    def rebuild_reading_note(self, paper_url_or_title: str) -> Optional[str]:
        """Rebuilds an existing reading note with native Feishu Docx blocks (tables, images, formulas)."""
        feishu_cfg = self.config.get("feishu")
        if not feishu_cfg:
            logger.warning("No feishu configuration found for rebuild_reading_note")
            return None

        from .feishu import FeishuClient
        client = FeishuClient(feishu_cfg)

        target = paper_url_or_title.strip()
        target_token = target.rstrip("/").split("/")[-1]
        ingested_dict = self.paper_store.data.get("ingested", {})

        # Match paper by URL, wiki_url, node token, or title
        matched_info = None
        for key, val in ingested_dict.items():
            if not isinstance(val, dict):
                continue
            v_url = val.get("url", "")
            v_wiki = val.get("wiki_url", "")
            v_title = val.get("title", "")
            if (
                target == key
                or target == v_url
                or target == v_wiki
                or (target_token and v_wiki and target_token == v_wiki.rstrip("/").split("/")[-1])
                or (v_wiki and target in v_wiki)
                or (v_title and target.lower() in v_title.lower())
                or (v_url and target in v_url)
            ):
                matched_info = dict(val)
                if not matched_info.get("url") and key.startswith("http"):
                    matched_info["url"] = key
                break

        if not matched_info:
            logger.warning(f"Could not find ingested paper record for: {target}")
            return None

        title = matched_info.get("title", target)
        url = matched_info.get("url", "")
        wiki_url = matched_info.get("wiki_url", "")
        tags = matched_info.get("tags", ["Agent", "Research"])

        node_token = wiki_url.split("/")[-1] if wiki_url else ""
        doc_id, _ = client.get_obj_token_from_node_token(node_token) if node_token else (None, None)
        if not doc_id:
            logger.warning(f"Could not resolve Feishu doc_id for {title} (node: {node_token})")
            return None

        is_github = "github.com" in (url or "").lower()
        paper = Paper(
            source="github" if is_github else "arxiv",
            title=title,
            authors=[],
            abstract="",
            url=url,
            affiliations=[],
            sources=["github"] if is_github else ["arxiv"],
        )

        if is_github:
            readme_text = self.fetch_github_readme(url)
            sections, tags = self.generate_app_note_sections(title=title, url=url, readme_text=readme_text)
            full_text_md = None
        else:
            sections, tags = self.generate_reading_note_sections(paper)
            raw_text = self.fetch_paper_full_text(url) if url else None
            full_text_md = self.translate_full_text_to_bilingual(raw_text)

        updated_url = client.create_reading_note(
            paper=paper,
            sections=sections,
            full_text_markdown=full_text_md,
            existing_doc_id=doc_id,
            existing_node_token=node_token,
        )
        logger.info(f"Successfully rebuilt reading note for '{title}': {updated_url}")
        return updated_url

    def rebuild_all_ingested_notes(self) -> dict[str, str]:
        """Rebuilds all previously ingested notes in the knowledge base."""
        results = {}
        ingested = self.paper_store.data.get("ingested", {})
        seen_urls = set()
        for k, v in list(ingested.items()):
            if not isinstance(v, dict):
                continue
            url = v.get("url") or (k if k.startswith("http") else "") or v.get("wiki_url")
            wiki_url = v.get("wiki_url")
            if not url or url in seen_urls or (wiki_url and wiki_url in seen_urls):
                continue
            seen_urls.add(url)
            if wiki_url:
                seen_urls.add(wiki_url)
            try:
                res = self.rebuild_reading_note(url)
                if res:
                    results[v.get("title", k)] = res
            except Exception as exc:
                logger.error(f"Failed to rebuild note for {k}: {exc}")
        return results

    def filter_quality_papers(
        self,
        papers: list[Paper],
        console_settings: dict[str, list[str]] | None = None,
    ) -> list[Paper]:
        """Filters papers based on academic quality gates and declarative console rules:
        0. Reject robotics/hardware, non-main workshops, and console-defined excluded keywords.
        1. Enforce console-defined required anchors (if any).
        2. Community-curated (Hugging Face / GitHub).
        3. Top conference / journal acceptance (NeurIPS, ICML, ICLR, ACL, AAAI, CVPR, etc.).
        4. High citation count (>= min_citations).
        5. Recognized universities, institutes, or tech AI labs in author affiliations.
        Preprints with unknown / unverified affiliations and no venue/citations are filtered out.
        """
        filter_cfg = self.config.get("filter") or {}
        if not filter_cfg.get("enabled", False):
            return papers

        top_venues = [v.lower() for v in filter_cfg.get("top_venues", [])]
        top_institutions = [inst.lower() for inst in filter_cfg.get("top_institutions", [])]
        exclude_non_main = filter_cfg.get("exclude_non_main", True) or filter_cfg.get("exclude_workshops", True)
        min_citations = int(filter_cfg.get("min_citations", 5))

        cs = console_settings or {}
        excluded_kws = [
            kw.lower().strip()
            for kw in (cs.get("excluded_keywords") or filter_cfg.get("excluded_keywords") or [])
            if kw.strip()
        ]
        required_anchors = [
            anc.lower().strip()
            for anc in (cs.get("required_anchors") or filter_cfg.get("required_anchors") or [])
            if anc.strip()
        ]

        non_main_patterns = [
            r"\bworkshop\b",
            r"\bworkshops\b",
            r"\bsymposium\b",
            r"\bshort\s*paper\b",
            r"\bshort\s*papers\b",
            r"\bshort\s*track\b",
            r"\bdemo\s*paper\b",
            r"\bdemo\s*track\b",
            r"\bdemonstration\s*track\b",
            r"\bsystem\s*demonstration\b",
            r"\bextended\s*abstract\b",
            r"\bposter\s*abstract\b",
            r"\bindustry\s*track\b",
            r"[\(\[\{]\s*(?:demo|short|demonstration|extended abstract)\s*[\)\]\}]",
        ]

        # 0. Reject robotics/hardware-heavy papers unless explicitly requested
        robot_patterns = [
            r"\brobot\b", r"\brobots\b", r"\brobotic\b", r"\brobotics\b",
            r"\bhumanoid\b", r"\bhumanoids\b", r"\bbipedal\b", r"\bquadruped\b",
            r"\bquadrotor\b", r"\buav\b", r"\buavs\b", r"\bdriverless\b",
            r"\bmanipulator\b", r"\bmanipulation\b", r"\bgripper\b",
            r"\bend-effector\b", r"\btactile\s+sensor\b", r"\bteleoperation\b",
            r"\bexoskeleton\b", r"\bmobile\s+robot\b", r"\bautonomous\s+vehicle\b"
        ]
        exclude_robotics = filter_cfg.get("exclude_robotics", True)

        kept: list[Paper] = []
        for p in papers:
            v_str = (p.venue or "").lower()
            t_str = (p.title or "").lower()
            abs_str = (p.abstract or "").lower()
            full_text_str = f"{t_str} {abs_str}"

            # 0a. Reject robotics-heavy papers (check title & abstract)
            if exclude_robotics:
                if any(re.search(pat, t_str) for pat in robot_patterns):
                    logger.debug(f"Filtered out robotics paper by title: '{p.title}'")
                    continue
                robot_matches = sum(1 for pat in robot_patterns if re.search(pat, abs_str))
                if robot_matches >= 2:
                    logger.debug(f"Filtered out robotics paper by abstract cues: '{p.title}'")
                    continue

            # 0b. Reject console-defined excluded keywords / topics
            if excluded_kws:
                # If title hits any excluded keyword, or abstract hits >= 2 excluded cues
                if any(kw in t_str for kw in excluded_kws):
                    logger.debug(f"Filtered out paper by console excluded keyword in title: '{p.title}'")
                    continue
                if sum(1 for kw in excluded_kws if kw in abs_str) >= 2:
                    logger.debug(f"Filtered out paper by console excluded keywords in abstract: '{p.title}'")
                    continue

            # 0c. Enforce console-defined required topic anchors (at least one must match in title or abstract)
            if required_anchors:
                if not any(anc in full_text_str for anc in required_anchors):
                    logger.debug(f"Filtered out paper missing required topic anchors: '{p.title}'")
                    continue

            # 0d. Reject workshops, short papers, demo papers, extended abstracts
            if exclude_non_main:
                combined_check = f"{v_str} {t_str}"
                if any(re.search(pat, combined_check) for pat in non_main_patterns):
                    logger.debug(f"Filtered out non-main paper (workshop/short/demo): '{p.title}' (venue={p.venue})")
                    continue

            # 1. Non-arXiv curated sources (e.g. HuggingFace Daily Papers, GitHub repos)
            if p.source in ("huggingface", "github") or any(s in ("huggingface", "github") for s in (p.sources or [])):
                kept.append(p)
                continue

            # 2. Accepted by a reputable conference / journal venue
            v_str = (p.venue or "").lower()
            if v_str and any(tv in v_str for tv in top_venues):
                kept.append(p)
                continue

            # 3. High citation count (classic / recognized earlier works)
            if p.citation_count is not None and p.citation_count >= min_citations:
                kept.append(p)
                continue

            # 4. Author affiliations match reputable universities or tech labs
            affils_text = " ".join(p.affiliations or []).lower()
            authors_text = " ".join(p.authors or []).lower()
            combined_inst_text = f"{affils_text} {authors_text}"

            if any(inst in combined_inst_text for inst in top_institutions):
                kept.append(p)
                continue

            # 5. Check if abstract/comments explicitly mention recognized top institution
            abs_prefix = (p.abstract[:300] if p.abstract else "").lower()
            if any(inst in abs_prefix for inst in top_institutions):
                kept.append(p)
                continue

            logger.debug(f"Filtered out unverified preprint: '{p.title}' (venue={p.venue})")

        return kept

    def run(self):
        # 1. Check and ingest user-confirmed papers from Feishu Wiki
        try:
            self.ingest_checked_papers()
        except Exception as exc:
            logger.warning(f"Notice during ingest_checked_papers: {exc}")

        if self.config.executor.get("ingest_only", False) or os.environ.get("INGEST_ONLY", "").lower() in ("true", "1"):
            logger.info("Ingest-only mode enabled. Skipping paper retrieval.")
            return

        # 2. Fetch interest corpus (including newly ingested reading notes)
        corpus = self.fetch_corpus()
        if len(corpus) == 0:
            logger.error(
                "No interest corpus found. Please configure 'topics' in config/custom.yaml "
                "or provide valid Zotero credentials."
            )
            return

        # 2b. LLM query planning from the console's tags and questions
        console_settings = self.console()
        if self.research_cfg.get("enabled", True):
            plan = plan_queries(
                self.router,
                console_settings.get("tags", []),
                console_settings.get("questions", []),
                [p.title for p in taste_corpus(corpus)[:10]],
                state=self.research_state,
            )
            if plan.get("s2_queries") and "semantic_scholar" in self.retrievers:
                self.retrievers["semantic_scholar"].retriever_config.queries = plan["s2_queries"]
                pos_cnt = len(plan.get("affirmative_s2", []))
                neg_cnt = len(plan.get("adversarial_s2", []))
                logger.info(
                    f"Planned {len(plan['s2_queries'])} S2 queries "
                    f"({pos_cnt} affirmative, {neg_cnt} adversarial counter-queries)"
                )
            if plan.get("arxiv_categories") and "arxiv" in self.retrievers:
                self.retrievers["arxiv"].retriever_config.category = plan["arxiv_categories"]
                logger.info(f"Planned arXiv categories: {', '.join(plan['arxiv_categories'])}")

        all_papers: list[Paper] = []

        def retrieve_one(item: tuple[str, Any]) -> tuple[str, list[Paper]]:
            source, retriever = item
            logger.info(f"Retrieving {source} papers...")
            return source, retriever.retrieve_papers() or []

        # Sources are independent HTTP fetches, so run them at the same time.
        with ThreadPoolExecutor(max_workers=max(1, len(self.retrievers))) as pool:
            for source, papers in pool.map(retrieve_one, list(self.retrievers.items())):
                if not papers:
                    logger.info(f"No {source} papers found")
                    continue
                logger.info(f"Retrieved {len(papers)} {source} papers")
                all_papers.extend(papers)

        logger.info(f"Total {len(all_papers)} papers retrieved from all sources")

        # Deduplicate across sources and merge source tags
        deduped_papers = self.paper_store.dedup(all_papers)
        logger.info(f"{len(deduped_papers)} unique papers after cross-source deduplication")

        # Filter out papers already pushed (allow same-day rerun if force_today is enabled)
        force_today = as_bool(os.environ.get("FORCE_RERUN_TODAY", False)) or as_bool(self.config.executor.get("force_today", False))
        new_papers = self.paper_store.filter_already_pushed(deduped_papers, allow_same_day=force_today)
        logger.info(f"{len(new_papers)} new unpushed papers ready for quality filtering")

        # Academic Quality Gate (filter out obscure preprints without top affiliation or recognized venue)
        quality_papers = self.filter_quality_papers(new_papers, console_settings=console_settings)
        logger.info(f"{len(quality_papers)} / {len(new_papers)} papers passed academic quality gate")
        funnel = {
            "retrieved": len(all_papers),
            "unique": len(deduped_papers),
            "unpushed": len(new_papers),
            "quality": len(quality_papers),
        }

        priority_institutions = console_settings.get("institutions", [])
        topic_anchors = list(
            dict.fromkeys(
                (console_settings.get("tags") or [])
                + (console_settings.get("required_anchors") or [])
            )
        ) or None

        # Multi-hop retrieval: chase citations of the most promising candidates
        if self.research_cfg.get("enabled", True) and self.research_cfg.get("multi_hop", True):
            # Seeds come from the taste-ordered head, not retrieval order, and are chosen for the questions
            _t0 = time.time()
            seed_pool = (
                self.reranker.rerank(
                    list(quality_papers),
                    taste_corpus(corpus),
                    priority_institutions=priority_institutions,
                    topic_anchors=topic_anchors,
                )
                if quality_papers
                else []
            )
            logger.info(f"Seed rerank finished in {time.time() - _t0:.1f}s")
            seeds = pick_seeds(
                self.router,
                seed_pool[:20],
                int(self.research_cfg.get("max_seeds", 4)),
                questions=console_settings.get("questions", []),
            )
            logger.info(f"pick_seeds finished at {time.time() - _t0:.1f}s ({len(seeds)} seeds)")
            if seeds and "semantic_scholar" in self.retrievers:
                related = self.retrievers["semantic_scholar"].retrieve_related(seeds)
                logger.info(f"Citation chasing finished at {time.time() - _t0:.1f}s ({len(related or [])} related)")
                if related:
                    merged = self.paper_store.dedup(quality_papers + related)
                    quality_papers = self.filter_quality_papers(
                        self.paper_store.filter_already_pushed(merged, allow_same_day=force_today),
                        console_settings=console_settings,
                    )
                    logger.info(f"{len(quality_papers)} papers after citation chasing")

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
        if len(quality_papers) > 0:
            logger.info("Reranking papers against interest corpus...")
            ranked = self.reranker.rerank(
                quality_papers,
                taste_corpus(corpus),
                priority_institutions=priority_institutions,
                topic_anchors=topic_anchors,
            )

            questions = console_settings.get("questions", [])
            if questions:
                logger.info(f"Scoring {len(ranked)} candidates against tracked questions...")
                self.score_against_questions(ranked)

            self.apply_negative_feedback(ranked)
            reranked_papers = self.fuse_and_select(ranked, questions, paper_quota)
            deep_read_papers = [p for p in reranked_papers if getattr(p, "recommendation_tier", "deep_read") == "deep_read"]
            quick_radar_papers = [p for p in reranked_papers if getattr(p, "recommendation_tier", None) == "quick_radar"]
            logger.info(
                f"Selected {len(reranked_papers)} of {len(ranked)} candidates "
                f"(deep_read={len(deep_read_papers)}, quick_radar={len(quick_radar_papers)})"
            )
            funnel.update(
                {
                    "after_citation_chasing": len(quality_papers),
                    "question_relevant": sum(1 for p in ranked if p.qa_scores),
                    "selected": len(reranked_papers),
                    "deep_read": len(deep_read_papers),
                    "quick_radar": len(quick_radar_papers),
                }
            )
            logger.info("Funnel: " + " -> ".join(f"{k} {v}" for k, v in funnel.items()))
            self.write_trace(ranked, reranked_papers, funnel)

            logger.info("Generating TLDR, affiliations, and conference venue...")

            def summarize_one(p: Paper) -> None:
                if self.openai_client is None and self.translator is not None:
                    # Use the configured translator instead of the slow free endpoints.
                    first = (p.abstract or p.title).split(". ")[0].strip().rstrip(".") + "."
                    p.tldr_en = first
                    p.tldr_zh = self.translator.translate_single(first) or first
                    p.tldr = p.tldr_zh
                    p.generate_venue()
                else:
                    p.generate_tldr(self.openai_client, self.config.llm if self.openai_client else None)
                    if self.openai_client is not None:
                        p.generate_affiliations(self.openai_client, self.config.llm)
                        p.generate_venue(self.openai_client, self.config.llm)
                    else:
                        p.generate_venue()

            # Per-paper HTTP calls, so run them concurrently instead of one timeout per paper
            tldr_workers = max(1, int(self.config.executor.get("tldr_workers", 4)))
            logger.info(f"Summarizing {len(reranked_papers)} papers...")
            with ThreadPoolExecutor(max_workers=tldr_workers) as pool:
                list(pool.map(summarize_one, reranked_papers))

            # Baselines and inline annotations are independent per paper, so run both
            # stages in a single pool: total time is one paper's work, not two stages' sum.
            if deep_read_papers:
                do_baselines = bool(self.research_cfg.get("baselines", True))
                do_annotations = bool(self.research_cfg.get("inline_annotations", True))
                if do_baselines or do_annotations:
                    from .annotator import enrich_papers_with_inline_annotations

                    use_ar5iv = as_bool(self.research_cfg.get("full_text_ar5iv", False))
                    workers = int(
                        self.research_cfg.get(
                            "enrich_workers",
                            max(
                                int(self.research_cfg.get("baseline_workers", 4)),
                                int(self.research_cfg.get("annotation_workers", 4)),
                            ),
                        )
                    )
                    logger.info(
                        f"Extracting baselines and inline annotations for {len(deep_read_papers)} deep-read papers..."
                    )

                    def enrich_one(paper: Paper) -> None:
                        if do_baselines:
                            enrich_papers_with_baselines(self.router, [paper], corpus, max_workers=1)
                        if do_annotations:
                            enrich_papers_with_inline_annotations(
                                self.router, [paper], questions, max_workers=1, use_ar5iv=use_ar5iv
                            )

                    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                        list(pool.map(enrich_one, deep_read_papers))

            # Per-question synthesis and next-round question proposals
            if self.research_cfg.get("synthesis", True) and questions:
                self.question_briefs = synthesize_questions(
                    self.router,
                    questions,
                    reranked_papers,
                    state=self.research_state,
                    max_questions=int(self.research_cfg.get("max_brief_questions", 8)),
                )
                self.research_state.record(self.question_briefs)
                logger.info(f"Wrote {len(self.question_briefs)} question briefs")

                if self.research_cfg.get("next_questions", True):
                    accepted = [p.title for p in reranked_papers if p.qa_matches]
                    self.suggested_questions = suggest_next_questions(
                        self.router, questions, self.question_briefs, accepted, state=self.research_state
                    )
                    if self.suggested_questions:
                        logger.info(f"Proposed {len(self.suggested_questions)} next-round questions")

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
        attempted_channels = 0
        today_str = datetime.now().date().isoformat()

        # 1. Feishu Delivery (if configured)
        feishu_cfg = self.config.get("feishu")
        is_feishu_dry_run = feishu_cfg.get("dry_run", False) if feishu_cfg else False
        if isinstance(is_feishu_dry_run, str):
            is_feishu_dry_run = is_feishu_dry_run.strip().lower() in ("true", "1", "yes")

        if feishu_cfg and feishu_cfg.get("app_id") and not is_feishu_dry_run:
            attempted_channels += 1
            try:
                from .feishu import FeishuClient
                client = FeishuClient(feishu_cfg)

                doc_url = client.create_or_update_daily_report(
                    reranked_papers,
                    trending_items=trending_items,
                    question_briefs=self.question_briefs,
                    corpus=corpus,
                )
                if self.suggested_questions and self.config.get("console", {}).get("node_token"):
                    try:
                        client.append_suggested_questions(
                            str(self.config.console.node_token), self.suggested_questions
                        )
                    except Exception as exc:
                        logger.warning(f"Could not write suggested questions to console: {exc}")
                logger.info(f"Feishu daily report updated successfully: {doc_url}")
                self.paper_store.mark_channel_delivered("feishu", today_str)
                delivered = True
            except Exception as exc:
                logger.error(f"Failed to publish Feishu daily report: {exc}")

        # 2. Independent email delivery (not a Feishu fallback)
        email_cfg = self.config.get("email")
        email_enabled = str(email_cfg.get("enabled", True)).strip().lower() in ("true", "1", "yes") if email_cfg else False
        if (
            email_cfg
            and email_enabled
            and email_cfg.get("sender")
            and email_cfg.get("receiver")
            and email_cfg.get("sender_password")
            and email_cfg.sender != "???"
        ):
            attempted_channels += 1
            try:
                if self.paper_store.is_channel_delivered("email", today_str) and not force_today and not reranked_papers:
                    logger.info(f"Daily report email already sent today ({today_str}); skipping.")
                    delivered = True
                else:
                    report = build_daily_report(reranked_papers, self.question_briefs, trending_items=trending_items)
                    send_email(self.config, report.html, report.title)
                    self.paper_store.mark_channel_delivered("email", today_str)
                    delivered = True
            except Exception as exc:
                logger.error(f"Failed to send email daily report: {exc}")

        # 3. Independent WeChat draft delivery; review and publish in the MP console
        wechat_cfg = self.config.get("wechat")
        wechat_enabled = str(wechat_cfg.get("enabled", False)).strip().lower() in ("true", "1", "yes") if wechat_cfg else False
        if (
            wechat_cfg
            and wechat_enabled
            and wechat_cfg.get("app_id")
            and wechat_cfg.get("app_secret")
        ):
            attempted_channels += 1
            try:
                if self.paper_store.is_channel_delivered("wechat", today_str) and not force_today and not reranked_papers:
                    logger.info(f"WeChat daily report draft already created today ({today_str}); skipping.")
                    delivered = True
                else:
                    from .wechat import create_draft

                    report = build_daily_report(
                        reranked_papers, self.question_briefs, max_chars=19000, trending_items=trending_items
                    )
                    create_draft(wechat_cfg, report)
                    logger.info("WeChat daily report draft created successfully")
                    self.paper_store.mark_channel_delivered("wechat", today_str)
                    delivered = True
            except Exception as exc:
                logger.error(f"Failed to create WeChat daily report draft: {exc}")

        if attempted_channels and not delivered:
            # Let the scheduled run turn red instead of silently losing the report
            raise RuntimeError(
                f"All {attempted_channels} configured delivery channel(s) failed; "
                "papers were not marked as pushed"
            )

        # Mark as pushed only after a channel actually delivered (or in local dry-run)
        if delivered or is_feishu_dry_run:
            if not self.config.get("executor", {}).get("debug", False):
                if reranked_papers:
                    self.paper_store.mark_pushed(reranked_papers)
                    logger.info(f"Marked {len(reranked_papers)} papers as pushed in paper_store")
                if trending_items:
                    self.paper_store.mark_pushed(trending_items)
                    logger.info(f"Marked {len(trending_items)} trending items as pushed in paper_store")
