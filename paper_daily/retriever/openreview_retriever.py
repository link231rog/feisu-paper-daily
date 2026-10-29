from datetime import datetime
from typing import Any
import requests
from loguru import logger
from omegaconf import DictConfig

from .base import BaseRetriever, register_retriever
from ..protocol import Paper

TIMEOUT = (10, 30)


def _unwrap_or_value(field: Any) -> Any:
    """Unwraps OpenReview API v2 {'value': ...} dicts or returns v1 value directly."""
    if isinstance(field, dict) and "value" in field:
        return field["value"]
    return field


@register_retriever("openreview")
class OpenReviewRetriever(BaseRetriever):
    """Retrieves conference and workshop papers from OpenReview API v2.

    Supports both keyword search (/notes/search) and venue invitation listing (/notes).
    API docs: https://docs.openreview.net/reference/api-v2
    """

    def __init__(self, config: DictConfig):
        super().__init__(config)
        self.base_url = "https://api2.openreview.net"

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        cfg = self.retriever_config or {}
        queries = list(cfg.get("queries") or [])
        venues = list(cfg.get("venues") or [])
        limit_per_query = int(cfg.get("limit_per_query") or 15)
        headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}

        raw_notes: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        # 1. Fetch by keyword queries via /notes/search
        for q in queries:
            q_str = str(q).strip()
            if not q_str:
                continue
            params = {
                "term": q_str,
                "content": "all",
                "group": "all",
                "source": "forum",
                "limit": limit_per_query,
            }
            try:
                resp = requests.get(
                    f"{self.base_url}/notes/search",
                    params=params,
                    headers=headers,
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                notes = resp.json().get("notes") or []
                for n in notes:
                    nid = n.get("id") or n.get("forum")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        raw_notes.append(n)
            except Exception as exc:
                logger.warning(f"OpenReview search failed for query '{q_str}': {exc}")

        # 2. Fetch by venue IDs via /notes?content.venueid=...
        for venue_id in venues:
            v_str = str(venue_id).strip()
            if not v_str:
                continue
            params = {
                "content.venueid": v_str,
                "limit": limit_per_query,
            }
            try:
                resp = requests.get(
                    f"{self.base_url}/notes",
                    params=params,
                    headers=headers,
                    timeout=TIMEOUT,
                )
                resp.raise_for_status()
                notes = resp.json().get("notes") or []
                for n in notes:
                    nid = n.get("id") or n.get("forum")
                    if nid and nid not in seen_ids:
                        seen_ids.add(nid)
                        raw_notes.append(n)
            except Exception as exc:
                logger.warning(f"OpenReview venue fetch failed for '{v_str}': {exc}")

        logger.info(f"Retrieved {len(raw_notes)} raw papers from OpenReview")
        return raw_notes

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        if not isinstance(raw_paper, dict):
            return None
        content = raw_paper.get("content") or {}
        title = str(_unwrap_or_value(content.get("title")) or "").strip()
        if not title:
            return None

        abstract = str(_unwrap_or_value(content.get("abstract")) or "").strip()
        if not abstract:
            tldr_val = str(_unwrap_or_value(content.get("TL;DR")) or _unwrap_or_value(content.get("one-sentence_summary")) or "").strip()
            abstract = tldr_val
        if not abstract:
            return None

        authors_raw = _unwrap_or_value(content.get("authors")) or []
        if isinstance(authors_raw, list):
            authors = [str(a).strip() for a in authors_raw if str(a).strip()]
        elif isinstance(authors_raw, str):
            authors = [a.strip() for a in authors_raw.split(",") if a.strip()]
        else:
            authors = ["OpenReview Authors"]

        forum_id = str(raw_paper.get("forum") or raw_paper.get("id") or "").strip()
        url = f"https://openreview.net/forum?id={forum_id}" if forum_id else ""
        pdf_url = f"https://openreview.net/pdf?id={forum_id}" if forum_id else None

        venue = str(
            _unwrap_or_value(content.get("venue"))
            or _unwrap_or_value(content.get("venueid"))
            or "OpenReview"
        ).strip()

        published_date = None
        ts = raw_paper.get("pdate") or raw_paper.get("cdate") or raw_paper.get("tcdate")
        if isinstance(ts, (int, float)) and ts > 0:
            try:
                published_date = datetime.fromtimestamp(ts / 1000.0 if ts > 1e11 else ts)
            except Exception:
                published_date = None

        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            venue=venue,
            sources=[self.name],
            published_date=published_date,
        )
