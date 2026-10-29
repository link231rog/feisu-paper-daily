import re
import time
from datetime import datetime
from typing import Any
import requests
from loguru import logger
from omegaconf import DictConfig

from .base import BaseRetriever, register_retriever
from ..protocol import Paper, extract_venue_from_text

SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
RECOMMEND_URL = "https://api.semanticscholar.org/recommendations/v1/papers/forpaper"
PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"
FIELDS = "paperId,title,authors,abstract,url,venue,publicationDate,externalIds,citationCount,influentialCitationCount"
TIMEOUT = (10, 30)


@register_retriever("semantic_scholar")
class SemanticScholarRetriever(BaseRetriever):
    """Retrieves papers from Semantic Scholar Graph API and Recommendations API.
    
    API docs: https://api.semanticscholar.org/api-docs/graph
    """
    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.api_key = self.retriever_config.get("api_key")

    def _get_headers(self) -> dict[str, str]:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
        if self.api_key:
            headers["x-api-key"] = str(self.api_key)
        return headers

    def _request_with_retry(self, url: str, params: dict[str, Any], max_retries: int = 3) -> dict[str, Any] | None:
        delay = 2.0
        for attempt in range(max_retries):
            try:
                resp = requests.get(url, params=params, headers=self._get_headers(), timeout=TIMEOUT)
                if resp.status_code == 429:
                    logger.warning(f"Semantic Scholar rate limited (429), retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2
                    continue
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                if attempt == max_retries - 1:
                    logger.warning(f"Semantic Scholar request failed ({url}): {exc}")
                    return None
                time.sleep(delay)
                delay *= 2
        return None

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        raw_papers = []
        seen_ids = set()

        queries = self.retriever_config.get("queries") or []
        limit_per_query = int(self.retriever_config.get("limit_per_query", 15))
        date_range = self.retriever_config.get("date_range")

        for query in queries:
            logger.info(f"Querying Semantic Scholar for: {query}")
            params = {
                "query": query,
                "fields": FIELDS,
                "limit": limit_per_query,
            }
            if date_range:
                params["publicationDateOrYear"] = str(date_range)
            
            data = self._request_with_retry(SEARCH_URL, params)
            if data and "data" in data:
                for p in data["data"]:
                    pid = p.get("paperId")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        raw_papers.append(p)
            time.sleep(1.0)

        # Retrieve recommendations for seed papers
        seed_papers = self.retriever_config.get("seed_papers") or []
        seed_limit = int(self.retriever_config.get("seed_limit", 10))
        for seed in seed_papers:
            # Seed can be S2 paper ID, DOI (DOI:10.1...), or arXiv (ARXIV:2401.0001)
            url = f"{RECOMMEND_URL}/{seed}"
            logger.info(f"Fetching Semantic Scholar recommendations for seed: {seed}")
            params = {
                "fields": FIELDS,
                "limit": seed_limit,
            }
            data = self._request_with_retry(url, params)
            if data and "recommendedPapers" in data:
                for p in data["recommendedPapers"]:
                    pid = p.get("paperId")
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        raw_papers.append(p)
            time.sleep(1.0)

        logger.info(f"Retrieved {len(raw_papers)} raw papers from Semantic Scholar")
        return raw_papers

    def retrieve_related(self, seed_urls: list[Any], limit: int = 8) -> list[Paper]:
        """Follows citations and references of seed papers for a second retrieval hop."""
        if not seed_urls:
            return []

        raw_papers: list[dict[str, Any]] = []
        seen: set[str] = set()
        for seed in seed_urls[:5]:
            url = getattr(seed, "url", None) if not isinstance(seed, str) else seed
            match = re.search(r"(?:arxiv\.org/abs/|huggingface\.co/papers/)([0-9.]+)", url or "")
            if not match:
                continue
            paper_id = f"ARXIV:{match.group(1)}"
            for relation in ("references", "citations"):
                data = self._request_with_retry(
                    f"{PAPER_URL}/{paper_id}/{relation}",
                    {"fields": FIELDS, "limit": limit},
                )
                for item in (data or {}).get("data", []):
                    paper = item.get("citedPaper") or item.get("citingPaper") or {}
                    pid = paper.get("paperId")
                    if pid and pid not in seen and paper.get("title"):
                        seen.add(pid)
                        raw_papers.append(paper)
                time.sleep(1.0)

        logger.info(f"Retrieved {len(raw_papers)} related papers from citation chasing")
        return self.papers_from_raw(raw_papers)

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        title = (raw_paper.get("title") or "").strip()
        if not title:
            return None

        abstract = (raw_paper.get("abstract") or "").strip()
        authors_raw = raw_paper.get("authors") or []
        authors = [
            a.get("name", "") if isinstance(a, dict) else str(a)
            for a in authors_raw
            if (isinstance(a, dict) and a.get("name")) or (isinstance(a, str) and a)
        ]

        external_ids = raw_paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        arxiv_id = external_ids.get("ArXiv")

        url = raw_paper.get("url")
        if not url:
            if arxiv_id:
                url = f"https://arxiv.org/abs/{arxiv_id}"
            elif raw_paper.get("paperId"):
                url = f"https://www.semanticscholar.org/paper/{raw_paper.get('paperId')}"
            else:
                url = ""

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None

        published_date = None
        if raw_date := raw_paper.get("publicationDate"):
            try:
                published_date = datetime.strptime(raw_date, "%Y-%m-%d")
            except Exception:
                published_date = None

        affiliations = []
        for a in authors_raw:
            if isinstance(a, dict) and a.get("affiliations"):
                for aff in a["affiliations"]:
                    if isinstance(aff, str) and aff and aff not in affiliations:
                        affiliations.append(aff)

        venue = (
            raw_paper.get("venue")
            or (raw_paper.get("publicationVenue") or {}).get("name")
            or extract_venue_from_text(abstract)
        )

        citation_count = raw_paper.get("citationCount")

        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            affiliations=affiliations or None,
            doi=doi,
            arxiv_id=arxiv_id,
            sources=[self.name],
            published_date=published_date,
            venue=venue,
            citation_count=citation_count,
        )
