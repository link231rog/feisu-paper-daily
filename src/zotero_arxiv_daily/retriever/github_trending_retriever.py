import os
import re
import requests
from datetime import datetime, timedelta, timezone
from typing import Any
from loguru import logger
from omegaconf import DictConfig

from ..protocol import TrendingItem

TIMEOUT = (10, 30)


class GithubTrendingRetriever:
    """Retrieves trending and newly starred AI repositories from GitHub.
    Uses canonical owner/repo deduplication to avoid repeat recommendations.
    """
    def __init__(self, config: DictConfig):
        self.config = config
        self.cfg = config.get("news_and_trends", {})
        self.gh_cfg = self.cfg.get("github", {})
        self.token = os.environ.get("GITHUB_TOKEN")

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "PaperDaily/1.0 (compatible)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _match_tags(self, repo_data: dict[str, Any]) -> list[str]:
        """Matches repo topics, name, and description against configured tag keywords."""
        tags_cfg = self.cfg.get("tags", [])
        if not tags_cfg:
            return ["GitHub"]

        matched = []
        name = repo_data.get("full_name", "").lower()
        desc = (repo_data.get("description") or "").lower()
        topics = [t.lower() for t in repo_data.get("topics", [])]
        combined_text = f"{name} {desc} {' '.join(topics)}"

        for tag_item in tags_cfg:
            tag_name = tag_item.get("name")
            keywords = tag_item.get("keywords", [])
            for kw in keywords:
                pattern = r'\b' + re.escape(kw.lower()) + r'\b'
                if re.search(pattern, combined_text):
                    if tag_name not in matched:
                        matched.append(tag_name)
                    break

        return matched or ["GitHub"]

    def retrieve_trending(self) -> list[TrendingItem]:
        if not self.gh_cfg.get("enabled", True):
            return []

        topics = self.gh_cfg.get("topics", ["llm", "ai-agent", "diffusion"])
        days_back = int(self.gh_cfg.get("days_back", 7))
        min_stars = int(self.cfg.get("min_github_stars", 50))
        limit_per_topic = int(self.gh_cfg.get("limit_per_topic", 10))
        since_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")

        headers = self._get_headers()
        seen_repo_keys: set[str] = set()
        trending_items: list[TrendingItem] = []

        for topic in topics:
            # fork:false prevents forks, pushed:>since guarantees recent activity
            query = f"topic:{topic} fork:false pushed:>{since_date} stars:>={min_stars}"
            api_url = f"https://api.github.com/search/repositories?q={query}&sort=stars&order=desc&per_page={limit_per_topic}"
            logger.info(f"Querying GitHub trending for topic '{topic}' (stars >= {min_stars})...")

            try:
                resp = requests.get(api_url, headers=headers, timeout=TIMEOUT)
                if resp.status_code == 403:
                    logger.warning("GitHub API rate limit hit. Skipping further GitHub queries.")
                    break
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning(f"Failed to query GitHub for topic '{topic}': {exc}")
                continue

            for item in data.get("items", []):
                full_name = item.get("full_name", "")
                if not full_name:
                    continue

                canonical_key = f"github:{full_name.lower().strip()}"
                if canonical_key in seen_repo_keys:
                    continue
                seen_repo_keys.add(canonical_key)

                matched_tags = self._match_tags(item)
                desc = item.get("description") or ""

                created_str = item.get("created_at")
                pub_date = None
                if created_str:
                    try:
                        pub_date = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
                    except Exception:
                        pub_date = None

                trending_items.append(
                    TrendingItem(
                        source="GitHub",
                        title=full_name,
                        url=item.get("html_url", f"https://github.com/{full_name}"),
                        category="github_repo",
                        tags=matched_tags,
                        stars=item.get("stargazers_count", 0),
                        description=desc,
                        summary_en=desc,
                        summary_zh=None,
                        published_date=pub_date,
                    )
                )

        logger.info(f"Retrieved {len(trending_items)} unique GitHub trending repositories")
        return trending_items
