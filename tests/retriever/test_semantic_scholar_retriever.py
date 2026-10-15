import pytest
from datetime import datetime
from unittest.mock import MagicMock
from omegaconf import OmegaConf

from zotero_arxiv_daily.retriever.semantic_scholar_retriever import SemanticScholarRetriever
from zotero_arxiv_daily.protocol import Paper


@pytest.fixture
def s2_config():
    return OmegaConf.create({
        "source": {
            "semantic_scholar": {
                "queries": ["agent alignment"],
                "seed_papers": ["ARXIV:2401.00001"],
                "date_range": "2026",
                "limit_per_query": 5,
                "seed_limit": 5,
                "api_key": "test-key",
            }
        }
    })


def test_semantic_scholar_retrieve_raw_papers(s2_config, monkeypatch):
    search_data = {
        "data": [
            {
                "paperId": "s2_1",
                "title": "Search Result Paper",
                "abstract": "Abstract 1",
                "authors": [{"name": "Author One"}],
                "externalIds": {"ArXiv": "2401.00002", "DOI": "10.1234/s2_1"},
                "publicationDate": "2026-02-01",
            }
        ]
    }
    rec_data = {
        "recommendedPapers": [
            {
                "paperId": "s2_2",
                "title": "Recommended Seed Paper",
                "abstract": "Abstract 2",
                "authors": [{"name": "Author Two"}],
                "externalIds": {"DOI": "10.1234/s2_2"},
                "publicationDate": "2026-03-01",
            }
        ]
    }

    def mock_get(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "recommendations" in url:
            resp.json.return_value = rec_data
        else:
            resp.json.return_value = search_data
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.get", mock_get)

    retriever = SemanticScholarRetriever(s2_config)
    raw = retriever._retrieve_raw_papers()

    assert len(raw) == 2
    titles = [p["title"] for p in raw]
    assert "Search Result Paper" in titles
    assert "Recommended Seed Paper" in titles


def test_semantic_scholar_convert_to_paper(s2_config):
    retriever = SemanticScholarRetriever(s2_config)
    raw = {
        "paperId": "s2_1",
        "title": "Semantic Paper",
        "abstract": "A study on LLM alignment.",
        "authors": [{"name": "Jane Doe"}],
        "externalIds": {"ArXiv": "2401.99999", "DOI": "10.1145/12345"},
        "publicationDate": "2026-05-20",
    }

    paper = retriever.convert_to_paper(raw)
    assert isinstance(paper, Paper)
    assert paper.title == "Semantic Paper"
    assert paper.arxiv_id == "2401.99999"
    assert paper.doi == "10.1145/12345"
    assert paper.sources == ["semantic_scholar"]
    assert paper.url == "https://arxiv.org/abs/2401.99999"
    assert paper.pdf_url == "https://arxiv.org/pdf/2401.99999.pdf"
    assert paper.published_date == datetime(2026, 5, 20)


def test_semantic_scholar_retry_on_429(s2_config, monkeypatch):
    call_count = 0

    def mock_get(*a, **kw):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        if call_count < 2:
            resp.status_code = 429
            return resp
        resp.status_code = 200
        resp.json.return_value = {"data": [{"paperId": "p1", "title": "Paper 1"}]}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("time.sleep", lambda _: None)

    retriever = SemanticScholarRetriever(s2_config)
    res = retriever._request_with_retry("https://api.semanticscholar.org/test", {})
    assert res is not None
    assert call_count == 2
