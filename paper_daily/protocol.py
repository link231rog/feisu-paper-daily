from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, TypeVar
from datetime import datetime
import re
from loguru import logger
import json
RawPaperItem = TypeVar('RawPaperItem')


def _request_llm(openai_client: Any, llm_params: dict, messages: list[dict]) -> str:
    api_mode = llm_params.get("api_mode", "chat_completion")
    generation_kwargs = dict(llm_params.get("generation_kwargs", {}))

    if api_mode == "chat_completion":
        response = openai_client.chat.completions.create(
            messages=messages,
            **generation_kwargs,
        )
        return response.choices[0].message.content

    if api_mode == "response":
        max_tokens = generation_kwargs.pop("max_tokens", None)
        if max_tokens is not None and "max_output_tokens" not in generation_kwargs:
            generation_kwargs["max_output_tokens"] = max_tokens
        response = openai_client.responses.create(
            input=messages,
            **generation_kwargs,
        )
        return response.output_text

    raise ValueError(
        f"Unsupported llm.api_mode: {api_mode}. "
        "Expected 'chat_completion' or 'response'."
    )


@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    full_text: Optional[str] = None
    tldr: Optional[str] = None
    tldr_en: Optional[str] = None
    tldr_zh: Optional[str] = None
    affiliations: Optional[list[str]] = None
    score: Optional[float] = None
    doi: Optional[str] = None
    arxiv_id: Optional[str] = None
    sources: Optional[list[str]] = None  # merged from multiple retrievers, e.g. ["arxiv", "huggingface"]
    published_date: Optional[datetime] = None
    venue: Optional[str] = None
    citation_count: Optional[int] = None
    qa_matches: Optional[list[dict]] = None  # [{"question": str, "answer": str}]
    qa_scores: Optional[dict[str, int]] = None  # {question: 0-10 relevance}
    judge_reason: Optional[str] = None  # why the final judge ranked it here
    baselines: Optional[list[dict]] = None  # [{"name": str, "method_summary": str, "venue": str, "comparison": str, ...}]
    inline_annotations: Optional[list[dict]] = None  # [{"source": str, "quote": str, "type": str, "comment": str, ...}]
    annotation_sections: Optional[list[dict]] = None  # [{"id": "S1", "title": "摘要", "text": "原文"}]
    recommendation_tier: Optional[str] = None  # "deep_read" ([精读必看]) or "quick_radar" ([速览雷达])
    evidence_rigor: Optional[int] = None  # 1-5 score for methodological rigor and empirical depth
    is_priority_institution: bool = False
    critical_digest: Optional[dict[str, Any]] = None  # Structured output from Critical-Paper-Digest skill
    review_score: Optional[int] = None  # Deterministic review confidence score
    review_badge: Optional[str] = None  # Qualitative review badge e.g. [强烈推荐复用] (高置信度)
    code_url: Optional[str] = None  # Open-source GitHub / HuggingFace repository URL
    project_url: Optional[str] = None  # Project page or demo URL
    hf_upvotes: Optional[int] = None  # Hugging Face Daily Papers community upvotes
    rubric_scores: Optional[dict[str, int]] = None  # 4D 1-5 scores: delta, rigor, actionability, reproducibility
    composite_score: Optional[float] = None  # Calibrated 0-10 score combining recall + 4D rubric + external signals
    matched_anchor_title: Optional[str] = None  # Highest-matching positive corpus paper title
    poster_path: Optional[str] = None  # Path to generated/extracted framework diagram or academic poster
    poster_url: Optional[str] = None  # Remote or uploaded URL / media token

    def __post_init__(self) -> None:
        if not self.code_url or not self.project_url:
            artifacts = extract_paper_artifacts(f"{self.abstract or ''}\n{self.full_text[:2000] if self.full_text else ''}")
            if not self.code_url and artifacts.get("code_url"):
                self.code_url = artifacts["code_url"]
            if not self.project_url and artifacts.get("project_url"):
                self.project_url = artifacts["project_url"]

    @property
    def published_year(self) -> Optional[int]:
        """Extracts publication or preprint submission year."""
        if self.published_date:
            return self.published_date.year
        if self.venue:
            m = re.search(r'\b(20\d{2})\b', self.venue)
            if m:
                return int(m.group(1))
        if self.arxiv_id:
            m = re.match(r'^(\d{2})\d{2}\.', self.arxiv_id)
            if m:
                return 2000 + int(m.group(1))
        return None

    def is_recent(self, min_year: int = 2025) -> bool:
        """Checks if paper is from recent years (default 2025-2026)."""
        y = self.published_year
        return y is not None and y >= min_year

    def title_with_venue(self) -> str:
        """Returns the paper's English title with accepted conference/journal suffix if known."""
        clean_title = self.title.strip()
        if not self.venue:
            return clean_title
        v = self.venue.strip()
        if v.lower() in clean_title.lower():
            return clean_title
        return f"{clean_title} ({v})"

    def dedup_key(self) -> str:
        if self.doi:
            d = self.doi.lower().strip()
            for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
                if d.startswith(prefix):
                    d = d[len(prefix):]
                    break
            return d.strip()
        if self.arxiv_id:
            return self.arxiv_id.strip()
        return re.sub(r'[^a-z0-9]', '', self.title.lower())

    def generate_tldr(self, openai_client: Optional[OpenAI] = None, llm_params: Optional[dict] = None) -> str:
        if llm_params and str(llm_params.get("language", "")).lower() == "english":
            self.tldr = self.abstract
            self.tldr_zh = self.abstract
            self.tldr_en = self.abstract
            return self.tldr

        from .utils import translate_to_chinese
        first_sentence = self.abstract.split(". ")[0] if self.abstract else self.title
        if len(first_sentence) < 60 and self.abstract and ". " in self.abstract:
            parts = self.abstract.split(". ")
            first_sentence = ". ".join(parts[:2])

        clean_sentence = first_sentence.strip().rstrip(".") + "."
        self.tldr_en = clean_sentence
        self.tldr_zh = translate_to_chinese(clean_sentence)
        self.tldr = self.tldr_zh
        return self.tldr

    def _generate_affiliations_with_llm(self, openai_client: OpenAI, llm_params: dict) -> Optional[list[str]]:
        if self.full_text is not None:
            prompt = (
                "Given the beginning of a paper, extract the affiliations of the authors in a python list format, "
                f"which is sorted by the author order. If there is no affiliation found, return an empty list '[]':\n\n{self.full_text[:6000]}"
            )
            affiliations = _request_llm(
                openai_client,
                llm_params,
                [
                    {
                        "role": "system",
                        "content": "You are an assistant who perfectly extracts affiliations of authors from a paper. You should return a python list of affiliations sorted by the author order, like [\"TsingHua University\",\"Peking University\"]. If an affiliation is consisted of multi-level affiliations, like 'Department of Computer Science, TsingHua University', you should return the top-level affiliation 'TsingHua University' only. Do not contain duplicated affiliations. If there is no affiliation found, you should return an empty list [ ]. You should only return the final list of affiliations, and do not return any intermediate results.",
                    },
                    {"role": "user", "content": prompt},
                ],
            )

            affiliations = re.search(r'\[.*?\]', affiliations, flags=re.DOTALL).group(0)
            affiliations = json.loads(affiliations)
            # dict.fromkeys dedupes while keeping the author order the prompt asks for
            affiliations = list(dict.fromkeys(str(a).strip() for a in affiliations if str(a).strip()))

            return affiliations
    
    def generate_affiliations(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        try:
            affiliations = self._generate_affiliations_with_llm(openai_client,llm_params)
            self.affiliations = affiliations
            return affiliations
        except Exception as e:
            logger.warning(f"Failed to generate affiliations of {self.url}: {e}")
            self.affiliations = None
            return None

    def generate_venue(self, openai_client: Optional[OpenAI] = None, llm_params: Optional[dict] = None) -> Optional[str]:
        """Extracts or generates accepted conference/journal venue."""
        if self.venue:
            return self.venue

        # 1. Try regex extraction on full text or abstract
        if v := extract_venue_from_text(self.abstract):
            self.venue = v
            return v
        if self.full_text and (v := extract_venue_from_text(self.full_text[:3000])):
            self.venue = v
            return v

        # 2. Try LLM extraction if available
        if openai_client and llm_params:
            try:
                sample_text = (self.full_text[:2000] if self.full_text else self.abstract[:1000]) or ""
                prompt = (
                    "Given the paper title and preview below, identify whether this paper mentions being accepted to "
                    "or published in an academic conference or journal (e.g., 'ACL 2026', 'NeurIPS 2024', 'ICLR 2025', 'CVPR 2025').\n"
                    f"Title: {self.title}\n"
                    f"Text: {sample_text}\n\n"
                    "Report a venue only if the text explicitly says the paper was accepted to, published in or presented at it "
                    "(e.g. 'Accepted at ACL 2026'). Do not guess from the topic, the authors or the writing style, and do not "
                    "treat a workshop on a venue's topic or a cited venue as the paper's own venue. "
                    "If accepted or published, return ONLY the conference or journal name and year (e.g. 'ACL 2026'). "
                    "If not specified or preprint, return 'None'."
                )
                resp = _request_llm(
                    openai_client,
                    llm_params,
                    [
                        {"role": "system", "content": "You are a concise academic conference identifier."},
                        {"role": "user", "content": prompt}
                    ]
                )
                res_str = resp.strip().strip("'\"`.")
                if res_str and res_str.lower() != "none" and len(res_str) <= 30:
                    self.venue = res_str
                    return res_str
            except Exception as e:
                logger.debug(f"Notice generating venue for {self.title}: {e}")

        return None


def extract_venue_from_text(text: Optional[str]) -> Optional[str]:
    """Extracts accepted conference or journal name from text, comments, or journal references."""
    if not text:
        return None

    # Common major conference acronyms + year, e.g. "ACL 2026", "NeurIPS 2024", "ICLR 2025"
    conf_pattern = re.compile(
        r"\b(ACL|EMNLP|NAACL|EACL|AACL|COLING|NeurIPS|ICLR|ICML|CVPR|ICCV|ECCV|AAAI|IJCAI|KDD|SIGIR|WWW|WSDM|RecSys|TACL|TMLR|JMLR)\s*(?:20\d{2}|['’]\d{2})\b",
        re.IGNORECASE,
    )
    if m := conf_pattern.search(text):
        return m.group(0).upper().replace("’", "'")

    # Patterns like: "Accepted to ACL 2026", "Accepted at ICLR", "To appear in CVPR 2025"
    m2 = re.search(
        r"(?:accepted\s+(?:to|at|by|for)|to\s+appear\s+in|published\s+(?:in|at))\s+([A-Za-z0-9\s\-\.\'\"]+(?:20\d\d)?)",
        text,
        re.IGNORECASE,
    )
    if m2:
        candidate = m2.group(1).strip().strip(".,;:()")
        candidate = re.split(r",|\.|\band\b|;", candidate)[0].strip()
        if len(candidate) <= 30 and any(c.isupper() for c in candidate):
            return candidate

    return None


_IGNORED_GENERIC_REPOS = {
    "pytorch/pytorch",
    "huggingface/transformers",
    "huggingface/datasets",
    "openai/openai-python",
    "google/jax",
    "vllm-project/vllm",
    "langchain-ai/langchain",
}


def extract_paper_artifacts(text: Optional[str]) -> dict[str, Optional[str]]:
    """Extracts open-source code repository URL and project page URL from paper abstract, comment, or full text."""
    result: dict[str, Optional[str]] = {"code_url": None, "project_url": None}
    if not text:
        return result

    # 1. Extract GitHub / GitLab / HuggingFace code or dataset links
    gh_pattern = re.compile(
        r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)",
        re.IGNORECASE,
    )
    for m in gh_pattern.finditer(text):
        repo_slug = m.group(1).rstrip(".,;:)]}'\"").removesuffix(".git")
        if repo_slug.lower() in _IGNORED_GENERIC_REPOS:
            continue
        if "/" in repo_slug and not repo_slug.lower().endswith((".png", ".jpg", ".pdf", ".svg")):
            result["code_url"] = f"https://github.com/{repo_slug}"
            break

    if not result["code_url"]:
        hf_pattern = re.compile(
            r"https?://huggingface\.co/(?:spaces|datasets|models|[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+)",
            re.IGNORECASE,
        )
        for m in hf_pattern.finditer(text):
            candidate = m.group(0).rstrip(".,;:)]}'\"")
            if "/papers/" not in candidate.lower():
                result["code_url"] = candidate
                break

    # 2. Extract Project Page URLs (*.github.io, project page cues, etc.)
    io_pattern = re.compile(
        r"https?://[A-Za-z0-9_.\-]+\.github\.io(?:/[A-Za-z0-9_.\-/]*)?",
        re.IGNORECASE,
    )
    if m_io := io_pattern.search(text):
        result["project_url"] = m_io.group(0).rstrip(".,;:)]}'\"/")
    else:
        proj_cue = re.compile(
            r"(?:project\s+page|project\s+website|website|homepage|demo)\s*(?:is\s+available\s+at|at|:)?\s*(https?://[^\s,;)>\]]+)",
            re.IGNORECASE,
        )
        if m_proj := proj_cue.search(text):
            url_cand = m_proj.group(1).rstrip(".,;:)]}'\"/")
            if "github.com/" not in url_cand.lower() and "arxiv.org/" not in url_cand.lower():
                result["project_url"] = url_cand

    return result


@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]
    url: Optional[str] = None
    node_token: Optional[str] = None
    obj_token: Optional[str] = None


@dataclass
class TrendingItem:
    source: str  # "github", "hacker_news", "openai_blog", "deepmind_blog", "huggingface_blog"
    title: str
    url: str
    category: str  # "github_repo" or "breaking_news"
    tags: list[str] = field(default_factory=list)
    stars: Optional[int] = None
    description: Optional[str] = None
    summary_en: Optional[str] = None
    summary_zh: Optional[str] = None
    published_date: Optional[datetime] = None

    def dedup_key(self) -> str:
        # Canonical GitHub repo deduplication key: github:owner/repo
        if "github.com/" in self.url.lower():
            match = re.search(r'github\.com/([^/]+/[^/#?]+)', self.url.lower())
            if match:
                repo_id = match.group(1).removesuffix(".git").strip()
                return f"github:{repo_id}"
        # For news: clean URL (strip query params, trailing slashes)
        clean_url = re.sub(r'[?#].*$', '', self.url.lower()).rstrip('/')
        if clean_url:
            return f"news:{clean_url}"
        clean_title = re.sub(r'[^a-z0-9]', '', self.title.lower())
        return f"news_title:{clean_title}"