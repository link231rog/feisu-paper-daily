from datetime import datetime, timedelta, timezone
from time import sleep
from typing import Any

import requests
from loguru import logger

from .base import BaseRetriever, register_retriever
from ..protocol import Paper


@register_retriever("chemrxiv")
class ChemrxivRetriever(BaseRetriever):
    """Retrieve recent preprints from chemRxiv via the Cambridge Open Engage public API.

    chemRxiv publishes preprints continuously rather than in daily batches, so this
    retriever collects every item published within the last ``lookback_hours`` hours
    (24 by default) instead of keeping only the latest posting date as the bioRxiv
    retriever does. Items are fetched newest-first and pagination stops as soon as
    an item older than the cutoff is seen.
    """

    api_url = "https://chemrxiv.org/engage/chemrxiv/public-api/v1/items"
    article_url = "https://chemrxiv.org/engage/chemrxiv/article-details/{id}"
    page_size = 50  # API maximum
    max_pages = 20  # safety cap: 1000 items is far more than one day of chemRxiv output
    lookback_hours = 24
    request_headers = {
        "User-Agent": "zotero-arxiv-daily (https://github.com/TideDra/zotero-arxiv-daily)",
        "Accept": "application/json",
    }

    def _get_json(self, params: dict[str, Any]) -> dict[str, Any]:
        retry_num = 10
        delay_time = 10
        for i in range(retry_num):
            try:
                response = requests.get(
                    self.api_url,
                    params=params,
                    headers=self.request_headers,
                    timeout=60,
                )
                response.raise_for_status()
                return response.json()
            except Exception as e:
                if i == retry_num - 1:
                    raise e
                logger.warning(f"Failed to retrieve papers: {str(e)}. Retry in {delay_time} seconds.")
                sleep(delay_time)

    @staticmethod
    def _parse_date(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    def _retrieve_raw_papers(self) -> list[dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.lookback_hours)
        categories = self.retriever_config.category
        if categories is not None:
            categories = {c.lower() for c in categories}

        collection = []
        for page in range(self.max_pages):
            result = self._get_json(
                {
                    "limit": self.page_size,
                    "skip": page * self.page_size,
                    "sort": "PUBLISHED_DATE_DESC",
                }
            )
            hits = result.get("itemHits", [])
            if not hits:
                break
            reached_cutoff = False
            for hit in hits:
                item = hit.get("item", hit)
                published = self._parse_date(item.get("publishedDate"))
                if published is None:
                    logger.warning(f"Skipping chemRxiv item without a valid publishedDate: {item.get('id')}")
                    continue
                if published < cutoff:
                    reached_cutoff = True
                    break
                if categories is not None:
                    item_categories = {c.get("name", "").lower() for c in item.get("categories", [])}
                    if not item_categories & categories:
                        continue
                collection.append(item)
            if reached_cutoff or len(hits) < self.page_size:
                break

        if len(collection) == 0:
            logger.warning(f"No chemRxiv paper found in the last {self.lookback_hours} hours.")
        if self.config.executor.debug:
            collection = collection[:10]
        return collection

    def convert_to_paper(self, raw_paper: dict[str, Any]) -> Paper | None:
        title = raw_paper["title"]
        authors = [
            f"{a.get('firstName', '')} {a.get('lastName', '')}".strip()
            for a in raw_paper.get("authors", [])
        ]
        authors = [a for a in authors if a]
        abstract = raw_paper.get("abstract", "")
        url = self.article_url.format(id=raw_paper["id"])
        pdf_url = (raw_paper.get("asset") or {}).get("original", {}).get("url")
        full_text = None  # chemRxiv sits behind Cloudflare; do not scrape the PDF
        return Paper(
            source=self.name,
            title=title,
            authors=authors,
            abstract=abstract,
            url=url,
            pdf_url=pdf_url,
            full_text=full_text,
        )
