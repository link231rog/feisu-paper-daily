import requests
from datetime import datetime
from typing import Any
from loguru import logger
from omegaconf import DictConfig

from .base import BaseRetriever, register_retriever
from ..protocol import Paper

TIMEOUT = (10, 30)


@register_retriever("huggingface")
class HuggingFaceRetriever(BaseRetriever):
    """Retrieves daily papers from Hugging Face Daily Papers API.
    
    API docs: https://huggingface.co/docs/hub/api
    Endpoint: https://huggingface.co/api/daily_papers
    """
    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.endpoint = "https://huggingface.co/api/daily_papers"

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        target_date = self.retriever_config.get("date")
        if target_date:
            params["date"] = str(target_date)
        
        limit = self.retriever_config.get("limit")
        if limit:
            params["limit"] = int(limit)

        headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
        logger.info(f"Fetching Hugging Face daily papers with params={params}")
        
        try:
            response = requests.get(self.endpoint, params=params, headers=headers, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.warning(f"Failed to fetch Hugging Face papers: {exc}")
            return []

        raw_papers = []
        for item in data:
            if isinstance(item, dict) and "paper" in item:
                raw_papers.append(item["paper"])
            elif isinstance(item, dict) and "id" in item:
                raw_papers.append(item)

        if limit and len(raw_papers) > limit:
            raw_papers = raw_papers[:limit]

        logger.info(f"Retrieved {len(raw_papers)} raw papers from Hugging Face")
        return raw_papers

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        title = (raw_paper.get("title") or "").strip()
        if not title:
            return None

        abstract = (raw_paper.get("summary") or "").strip()
        authors_raw = raw_paper.get("authors") or []
        authors = [
            a.get("name", "") if isinstance(a, dict) else str(a)
            for a in authors_raw
            if (isinstance(a, dict) and a.get("name")) or (isinstance(a, str) and a)
        ]

        paper_id = (raw_paper.get("id") or "").strip()
        arxiv_id = paper_id if paper_id else None

        published_date = None
        if raw_date := raw_paper.get("publishedAt"):
            try:
                # Handle ISO format like 2026-10-15T03:32:00.000Z
                clean_date = raw_date.replace("Z", "+00:00")
                published_date = datetime.fromisoformat(clean_date)
            except Exception:
                published_date = None

        affiliations = []
        if org := raw_paper.get("organization"):
            if isinstance(org, dict):
                org_name = org.get("fullname") or org.get("name")
                if org_name:
                    affiliations.append(org_name)
            elif isinstance(org, str):
                affiliations.append(org)

        url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""
        pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf" if paper_id else None

        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            affiliations=affiliations or None,
            arxiv_id=arxiv_id,
            sources=[self.name],
            published_date=published_date,
        )
