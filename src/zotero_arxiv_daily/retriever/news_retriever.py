import re
import requests
import feedparser
from datetime import datetime, timezone
from typing import Any
from loguru import logger
from omegaconf import DictConfig

from ..protocol import TrendingItem

TIMEOUT = (10, 30)


class NewsRetriever:
    """Retrieves breaking AI news and lab updates from Hacker News and official RSS feeds."""
    def __init__(self, config: DictConfig):
        self.config = config
        self.cfg = config.get("news_and_trends", {})
        self.news_cfg = self.cfg.get("news", {})

    def _match_tags(self, title: str, text: str) -> list[str]:
        tags_cfg = self.cfg.get("tags", [])
        if not tags_cfg:
            return ["Breaking"]

        combined = f"{title.lower()} {text.lower()}"
        matched = []
        for tag_item in tags_cfg:
            tag_name = tag_item.get("name")
            keywords = tag_item.get("keywords", [])
            for kw in keywords:
                pattern = r'\b' + re.escape(kw.lower()) + r'\b'
                if re.search(pattern, combined):
                    if tag_name not in matched:
                        matched.append(tag_name)
                    break

        return matched or ["Breaking"]

    def _fetch_hacker_news(self) -> list[TrendingItem]:
        min_points = int(self.news_cfg.get("min_hn_points", 60))
        url = (
            "https://hn.algolia.com/api/v1/search_by_date?"
            "tags=story&query=AI+OR+LLM+OR+OpenAI+OR+Anthropic+OR+DeepSeek"
            f"&numericFilters=points%3E{min_points}&hitsPerPage=15"
        )
        logger.info(f"Fetching Hacker News AI stories (points > {min_points})...")
        try:
            resp = requests.get(url, headers={"User-Agent": "PaperDaily/1.0"}, timeout=TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(f"Failed to fetch Hacker News stories: {exc}")
            return []

        items: list[TrendingItem] = []
        for hit in data.get("hits", []):
            title = hit.get("title", "")
            target_url = hit.get("url") or f"https://news.ycombinator.com/item?id={hit.get('objectID')}"
            points = hit.get("points", 0)
            tags = self._match_tags(title, "")
            
            items.append(
                TrendingItem(
                    source="Hacker News",
                    title=title,
                    url=target_url,
                    category="breaking_news",
                    tags=tags,
                    stars=points,  # represent community upvotes
                    description=f"Hacker News upvotes: {points}",
                    summary_en=title,
                    summary_zh=None,
                    published_date=datetime.now(timezone.utc),
                )
            )
        return items

    def _fetch_rss_feeds(self) -> list[TrendingItem]:
        feeds = self.news_cfg.get("feeds", [
            {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml"},
            {"name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml"},
        ])

        items: list[TrendingItem] = []
        for f in feeds:
            feed_name = f.get("name", "RSS")
            feed_url = f.get("url")
            if not feed_url:
                continue

            try:
                parsed = feedparser.parse(feed_url)
                for entry in parsed.entries[:5]:
                    title = getattr(entry, "title", "").strip()
                    link = getattr(entry, "link", "").strip()
                    summary = getattr(entry, "summary", "").strip()
                    # Clean HTML tags from summary
                    clean_summary = re.sub(r'<[^>]+>', ' ', summary).strip()
                    tags = self._match_tags(title, clean_summary)

                    items.append(
                        TrendingItem(
                            source=feed_name,
                            title=title,
                            url=link,
                            category="breaking_news",
                            tags=tags,
                            description=clean_summary[:300],
                            summary_en=clean_summary[:300] if clean_summary else title,
                            summary_zh=None,
                            published_date=datetime.now(timezone.utc),
                        )
                    )
            except Exception as exc:
                logger.warning(f"Failed to parse RSS feed '{feed_name}': {exc}")

        return items

    def retrieve_news(self) -> list[TrendingItem]:
        if not self.news_cfg.get("enabled", True):
            return []

        all_items: list[TrendingItem] = []
        all_items.extend(self._fetch_hacker_news())
        all_items.extend(self._fetch_rss_feeds())

        # In-memory deduplication by canonical URL
        seen_keys: set[str] = set()
        unique_items: list[TrendingItem] = []
        for item in all_items:
            key = item.dedup_key()
            if key not in seen_keys:
                seen_keys.add(key)
                unique_items.append(item)

        logger.info(f"Retrieved {len(unique_items)} unique AI breaking news items")
        return unique_items
