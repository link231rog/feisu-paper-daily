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
            if isinstance(item, dict) and "paper" in item and isinstance(item["paper"], dict):
                paper_dict = dict(item["paper"])
                for extra_k in ("upvotes", "githubRepo", "projectPage", "numComments"):
                    if extra_k in item and extra_k not in paper_dict:
                        paper_dict[extra_k] = item[extra_k]
                raw_papers.append(paper_dict)
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

        upvotes_raw = raw_paper.get("upvotes")
        hf_upvotes: int | None = None
        if upvotes_raw is not None:
            try:
                hf_upvotes = int(upvotes_raw)
            except (TypeError, ValueError):
                hf_upvotes = None

        code_url = (raw_paper.get("githubRepo") or "").strip() or None
        project_url = (raw_paper.get("projectPage") or "").strip() or None

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
            code_url=code_url,
            project_url=project_url,
            hf_upvotes=hf_upvotes,
        )


def enrich_with_hf_daily_signals(papers: list[Paper], limit: int = 100) -> int:
    """Enriches candidate papers with Hugging Face Daily Papers community upvotes and code/project links."""
    if not papers:
        return 0

    # Only query if any paper is missing hf_upvotes and has an arxiv_id
    needs_enrichment = [p for p in papers if p.arxiv_id and p.hf_upvotes is None]
    if not needs_enrichment:
        return 0

    headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
    try:
        resp = requests.get(
            "https://huggingface.co/api/daily_papers",
            params={"limit": limit},
            headers=headers,
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.debug(f"HuggingFace daily signal enrichment skipped: {exc}")
        return 0

    hf_index: dict[str, dict[str, Any]] = {}
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        p_obj = item.get("paper") if isinstance(item.get("paper"), dict) else item
        pid = str(p_obj.get("id") or "").strip().split("v")[0]
        if not pid:
            continue
        upvotes = p_obj.get("upvotes") if p_obj.get("upvotes") is not None else item.get("upvotes")
        gh_repo = p_obj.get("githubRepo") or item.get("githubRepo")
        proj_page = p_obj.get("projectPage") or item.get("projectPage")
        hf_index[pid] = {
            "upvotes": int(upvotes) if isinstance(upvotes, (int, float)) else None,
            "code_url": str(gh_repo).strip() if gh_repo else None,
            "project_url": str(proj_page).strip() if proj_page else None,
        }

    enriched_count = 0
    for p in papers:
        if not p.arxiv_id:
            continue
        clean_id = p.arxiv_id.strip().split("v")[0]
        sig = hf_index.get(clean_id)
        if not sig:
            continue
        if p.hf_upvotes is None and sig.get("upvotes") is not None:
            p.hf_upvotes = sig["upvotes"]
        if not p.code_url and sig.get("code_url"):
            p.code_url = sig["code_url"]
        if not p.project_url and sig.get("project_url"):
            p.project_url = sig["project_url"]
        if p.sources and "huggingface" not in p.sources:
            p.sources.append("huggingface")
        enriched_count += 1

    if enriched_count:
        logger.info(f"Enriched {enriched_count} papers with Hugging Face Daily Papers community signals")
    return enriched_count
