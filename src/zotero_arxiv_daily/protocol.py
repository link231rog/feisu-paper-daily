from dataclasses import dataclass, field
from typing import Optional, TypeVar
from datetime import datetime
import re
import tiktoken
from openai import OpenAI
from loguru import logger
import json
RawPaperItem = TypeVar('RawPaperItem')


def _request_llm(openai_client: OpenAI, llm_params: dict, messages: list[dict]) -> str:
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

    def _generate_tldr_with_llm(self, openai_client:OpenAI,llm_params:dict) -> str:
        prompt = (
            "Given the following information of a paper, generate two one-sentence TLDR summaries:\n"
            "1. One sentence in English.\n"
            "2. One sentence in Chinese.\n\n"
            "Format your output strictly as:\n"
            "EN: <One sentence English TLDR>\n"
            "ZH: <One sentence Chinese TLDR>\n\n"
        )
        if self.title:
            prompt += f"Title:\n {self.title}\n\n"

        if self.abstract:
            prompt += f"Abstract: {self.abstract}\n\n"

        if self.full_text:
            prompt += f"Preview of main content:\n {self.full_text}\n\n"

        if not self.full_text and not self.abstract:
            logger.warning(f"Neither full text nor abstract is provided for {self.url}")
            return "Failed to generate TLDR. Neither full text nor abstract is provided"
        
        # use gpt-4o tokenizer for estimation
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
        prompt = enc.decode(prompt_tokens)
        
        tldr = _request_llm(
            openai_client,
            llm_params,
            [
                {
                    "role": "system",
                    "content": "You are an assistant who perfectly summarizes scientific papers. Provide a concise, clear one-sentence TLDR in English and one in Chinese.",
                },
                {"role": "user", "content": prompt},
            ],
        )
        return tldr
    
    def generate_tldr(self, openai_client: Optional[OpenAI] = None, llm_params: Optional[dict] = None) -> str:
        if openai_client is not None and llm_params is not None:
            try:
                tldr_raw = self._generate_tldr_with_llm(openai_client, llm_params)
                en_match = re.search(r'EN:\s*(.+?)(?=\nZH:|$)', tldr_raw, flags=re.DOTALL)
                zh_match = re.search(r'ZH:\s*(.+)', tldr_raw, flags=re.DOTALL)
                if en_match and zh_match:
                    self.tldr_en = en_match.group(1).strip()
                    self.tldr_zh = zh_match.group(1).strip()
                    self.tldr = self.tldr_zh
                    return self.tldr
                elif tldr_raw.strip():
                    self.tldr = tldr_raw.strip()
                    self.tldr_zh = self.tldr
                    self.tldr_en = self.abstract[:200] + "..." if self.abstract else self.tldr
                    return self.tldr
            except Exception as e:
                logger.warning(f"Failed to generate LLM tldr of {self.url}: {e}, using free translation fallback")

        # If language requested is English, keep raw abstract as fallback
        if llm_params and str(llm_params.get("language", "")).lower() == "english":
            self.tldr = self.abstract
            self.tldr_zh = self.abstract
            self.tldr_en = self.abstract
            return self.tldr

        # Free translation fallback (Google / MyMemory)
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


    def _generate_affiliations_with_llm(self, openai_client:OpenAI,llm_params:dict) -> Optional[list[str]]:
        if self.full_text is not None:
            prompt = f"Given the beginning of a paper, extract the affiliations of the authors in a python list format, which is sorted by the author order. If there is no affiliation found, return an empty list '[]':\n\n{self.full_text}"
            # use gpt-4o tokenizer for estimation
            enc = tiktoken.encoding_for_model("gpt-4o")
            prompt_tokens = enc.encode(prompt)
            prompt_tokens = prompt_tokens[:2000]  # truncate to 2000 tokens
            prompt = enc.decode(prompt_tokens)
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
            affiliations = list(set(affiliations))
            affiliations = [str(a) for a in affiliations]

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


@dataclass
class CorpusPaper:
    title: str
    abstract: str
    added_date: datetime
    paths: list[str]


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


def map_to_core_pillars(tags: Optional[list[str]] = None, title: str = "", text: str = "") -> list[str]:
    """Strictly maps arbitrary keywords/tags and context into the user's 4 core research pillars:
    - Memory (Agent Memory)
    - DecisionModel (Decision Model)
    - MAS (Multi-Agent System)
    - RL (Reinforcement Learning)
    """
    tags = tags or []
    corpus = f"{' '.join(tags)} {title} {text}".lower()
    matched = []
    # 1. Memory: specifically related to external/episodic/working memory
    if any(k in corpus for k in ["memory", "episodic memory", "working memory", "memgpt", "long-context", "memory management", "memory-r1"]):
        matched.append("Memory")
    # 2. DecisionModel: dedicated decision endpoints, System-One, deliberative models
    if any(k in corpus for k in ["decision", "decisionmodel", "decision model", "autothink", "deliberat", "world model", "system-one", "system 1", "systemone", "rubric", "choice"]):
        matched.append("DecisionModel")
    # 3. MAS: strictly Multi-Agent Systems, NOT general single-agent
    if any(k in corpus for k in ["multi-agent", "multiagent", "multi agent", "mas", "swarm", "cooperative agent", "adversarial agent", "agent communication", "agent society"]):
        matched.append("MAS")
    # 4. RL: reinforcement learning paradigms
    if any(k in corpus for k in ["reinforcement learning", "reinforcementlearning", "ppo", "grpo", "reward", "policy gradient", "actor-critic", "q-learning", "reinforce"]) or re.search(r'\b(rl)\b', corpus):
        matched.append("RL")
    # 5. Benchmark: evaluation benchmarks and datasets
    if any(k in corpus for k in ["benchmark", "benchmarks", "dataset", "datasets", "eval-suite"]):
        matched.append("Benchmark")
    return matched or ["Research"]