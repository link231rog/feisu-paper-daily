import pytest
from datetime import datetime
from unittest.mock import MagicMock
from omegaconf import OmegaConf

from zotero_arxiv_daily.protocol import TrendingItem
from zotero_arxiv_daily.paper_store import PaperStore
from zotero_arxiv_daily.retriever.github_trending_retriever import GithubTrendingRetriever
from zotero_arxiv_daily.retriever.news_retriever import NewsRetriever


@pytest.fixture
def trending_config():
    return OmegaConf.create({
        "news_and_trends": {
            "enabled": True,
            "min_github_stars": 50,
            "max_items": 5,
            "github": {
                "enabled": True,
                "topics": ["llm", "agent"],
                "days_back": 7,
                "limit_per_topic": 5,
            },
            "news": {
                "enabled": True,
                "min_hn_points": 50,
            },
            "tags": [
                {"name": "Agent", "keywords": ["agent", "multi-agent", "workflow"]},
                {"name": "Diffusion", "keywords": ["diffusion", "flux", "image"]},
                {"name": "OpenSource", "keywords": ["open-source", "open-weights", "vllm"]},
            ]
        }
    })


def test_trending_item_dedup_key():
    item1 = TrendingItem(
        source="GitHub",
        title="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm",
        category="github_repo",
    )
    item2 = TrendingItem(
        source="GitHub",
        title="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm.git?tab=readme",
        category="github_repo",
    )
    assert item1.dedup_key() == item2.dedup_key() == "github:vllm-project/vllm"

    news1 = TrendingItem(
        source="Hacker News",
        title="DeepSeek-V3 Released",
        url="https://news.ycombinator.com/item?id=12345",
        category="breaking_news",
    )
    news2 = TrendingItem(
        source="Hacker News",
        title="DeepSeek-V3 Released",
        url="https://news.ycombinator.com/item?id=12345#comments",
        category="breaking_news",
    )
    assert news1.dedup_key() == news2.dedup_key() == "news:https://news.ycombinator.com/item"


def test_paper_store_dedup_trending(tmp_path):
    store = PaperStore(str(tmp_path / "store.json"))
    item1 = TrendingItem(
        source="GitHub",
        title="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm",
        category="github_repo",
        stars=100,
        tags=["OpenSource"],
        description="First desc",
    )
    item2 = TrendingItem(
        source="GitHub",
        title="vllm-project/vllm",
        url="https://github.com/vllm-project/vllm.git",
        category="github_repo",
        stars=250,
        tags=["Agent"],
        description="Second desc",
    )
    deduped = store.dedup_trending([item1, item2])
    assert len(deduped) == 1
    # Merged tags and took highest stars
    assert set(deduped[0].tags) == {"OpenSource", "Agent"}
    assert deduped[0].stars == 250


def test_paper_store_filter_already_pushed_trending(tmp_path):
    store = PaperStore(str(tmp_path / "store.json"))
    item = TrendingItem(
        source="GitHub",
        title="openai/swarm",
        url="https://github.com/openai/swarm",
        category="github_repo",
    )
    # Mark as pushed
    store.mark_pushed([item])

    # Next day attempt to push
    unpushed = store.filter_already_pushed([item])
    assert len(unpushed) == 0


def test_github_retriever_tag_matching(trending_config):
    retriever = GithubTrendingRetriever(trending_config)
    repo_data = {
        "full_name": "test/agent-system",
        "description": "A multi-agent workflow framework",
        "topics": ["agent", "python"],
    }
    tags = retriever._match_tags(repo_data)
    assert "Agent" in tags


def test_github_retriever_mocked(trending_config, monkeypatch):
    retriever = GithubTrendingRetriever(trending_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "items": [
            {
                "full_name": "browser-use/browser-use",
                "html_url": "https://github.com/browser-use/browser-use",
                "description": "Make websites accessible for AI agents",
                "stargazers_count": 5000,
                "topics": ["agent", "automation"],
                "created_at": "2026-10-10T00:00:00Z",
            }
        ]
    }
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

    items = retriever.retrieve_trending()
    assert len(items) == 1
    assert items[0].title == "browser-use/browser-use"
    assert "Agent" in items[0].tags
    assert items[0].stars == 5000
