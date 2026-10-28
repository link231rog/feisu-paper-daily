import re
from datetime import datetime
from typing import Any
import requests
from loguru import logger
from omegaconf import DictConfig

from .base import BaseRetriever, register_retriever
from ..protocol import Paper

TIMEOUT = (10, 30)


@register_retriever("dblp")
class DBLPRetriever(BaseRetriever):
    """Retrieves computer science publications from DBLP Search API.

    API docs: https://dblp.org/faq/How+to+use+the+dblp+search+API.html
    Endpoint: https://dblp.org/search/publ/api
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.endpoint = "https://dblp.org/search/publ/api"

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        cfg = self.retriever_config or {}
        queries = list(cfg.get("queries") or [])
        limit_per_query = int(cfg.get("limit_per_query") or 15)
        min_year = int(cfg.get("min_year") or (datetime.now().year - 1))
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}

        raw_hits: list[dict[str, Any]] = []
        seen_keys: set[str] = set()

        for q in queries:
            q_str = str(q).strip()
            if not q_str:
                continue
            params = {
                "q": q_str,
                "format": "json",
                "h": limit_per_query,
            }
            try:
                resp = requests.get(self.endpoint, params=params, headers=headers, timeout=TIMEOUT)
                resp.raise_for_status()
                data = resp.json()
                hits = ((data.get("result") or {}).get("hits") or {}).get("hit") or []
                if isinstance(hits, dict):
                    hits = [hits]
                for h in hits:
                    info = h.get("info") or {}
                    key = info.get("key") or info.get("url") or info.get("title")
                    year_str = str(info.get("year") or "")
                    if year_str.isdigit() and int(year_str) < min_year:
                        continue
                    if key and key not in seen_keys:
                        seen_keys.add(key)
                        raw_hits.append(info)
            except Exception as exc:
                logger.warning(f"DBLP search failed for query '{q_str}': {exc}")

        logger.info(f"Retrieved {len(raw_hits)} raw publications from DBLP")
        return raw_hits

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        if not isinstance(raw_paper, dict):
            return None
        title = str(raw_paper.get("title") or "").strip().rstrip(".")
        if not title:
            return None

        authors_node = (raw_paper.get("authors") or {}).get("author") or []
        if isinstance(authors_node, dict):
            authors_node = [authors_node]
        elif isinstance(authors_node, str):
            authors_node = [{"text": authors_node}]

        authors: list[str] = []
        for a in authors_node:
            if isinstance(a, dict):
                name = a.get("text") or a.get("name") or ""
            else:
                name = str(a)
            name = re.sub(r"\s+\d{4}$", "", str(name).strip())
            if name:
                authors.append(name)
        if not authors:
            authors = ["DBLP Authors"]

        venue_raw = raw_paper.get("venue")
        if isinstance(venue_raw, list):
            venue = ", ".join(str(v) for v in venue_raw if v)
        else:
            venue = str(venue_raw or "DBLP").strip()

        year_str = str(raw_paper.get("year") or "").strip()
        if year_str and year_str not in venue:
            venue = f"{venue} {year_str}".strip()

        ee = raw_paper.get("ee")
        if isinstance(ee, list):
            url = str(ee[0]) if ee else ""
        else:
            url = str(ee or raw_paper.get("url") or "").strip()

        doi = str(raw_paper.get("doi") or "").strip() or None
        arxiv_id = None
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", f"{url} {doi or ''} {venue}")
        if arxiv_match:
            arxiv_id = arxiv_match.group(1)

        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None
        published_date = None
        if year_str.isdigit():
            try:
                published_date = datetime(int(year_str), 1, 1)
            except Exception:
                published_date = None

        # DBLP metadata does not embed full abstracts; synthesize a rich searchable metadata abstract
        # if not later merged with arXiv/Semantic Scholar during cross-source deduplication.
        abstract = str(raw_paper.get("abstract") or "").strip()
        if not abstract:
            abstract = f"Published in {venue}. Title: {title}. Authors: {', '.join(authors[:6])}."

        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            doi=doi,
            arxiv_id=arxiv_id,
            venue=venue,
            sources=[self.name],
            published_date=published_date,
        )
