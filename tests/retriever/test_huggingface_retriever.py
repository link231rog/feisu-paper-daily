import pytest
from datetime import datetime
from unittest.mock import MagicMock
from omegaconf import OmegaConf

from zotero_arxiv_daily.retriever.huggingface_retriever import HuggingFaceRetriever
from zotero_arxiv_daily.protocol import Paper


@pytest.fixture
def hf_config():
    return OmegaConf.create({
        "source": {
            "huggingface": {
                "date": "2026-10-15",
                "limit": 10,
            }
        }
    })


def test_huggingface_retriever_retrieve_raw_papers_success(hf_config, monkeypatch):
    mock_data = [
        {
            "paper": {
                "id": "2401.00001",
                "title": "Agent Alignment with Direct Preference Optimization",
                "summary": "This paper presents a new alignment technique.",
                "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
                "publishedAt": "2026-10-15T08:00:00.000Z",
                "upvotes": 42,
            }
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_data
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.get", lambda *a, **kw: mock_resp)

    retriever = HuggingFaceRetriever(hf_config)
    raw_papers = retriever._retrieve_raw_papers()

    assert len(raw_papers) == 1
    assert raw_papers[0]["id"] == "2401.00001"
    assert raw_papers[0]["title"] == "Agent Alignment with Direct Preference Optimization"


def test_huggingface_retriever_convert_to_paper(hf_config):
    retriever = HuggingFaceRetriever(hf_config)
    raw = {
        "id": "2401.00001",
        "title": "Agent Alignment with Direct Preference Optimization",
        "summary": "This paper presents a new alignment technique.",
        "authors": [{"name": "Alice Smith"}, {"name": "Bob Jones"}],
        "publishedAt": "2026-10-15T08:00:00.000Z",
    }

    paper = retriever.convert_to_paper(raw)
    assert isinstance(paper, Paper)
    assert paper.title == "Agent Alignment with Direct Preference Optimization"
    assert paper.arxiv_id == "2401.00001"
    assert paper.sources == ["huggingface"]
    assert paper.url == "https://huggingface.co/papers/2401.00001"
    assert paper.pdf_url == "https://arxiv.org/pdf/2401.00001.pdf"
    assert len(paper.authors) == 2
    assert paper.authors[0] == "Alice Smith"
    assert paper.published_date is not None
    assert paper.published_date.year == 2026


def test_huggingface_retriever_handles_api_failure(hf_config, monkeypatch):
    def mock_get(*a, **kw):
        raise ConnectionError("Network unreachable")

    monkeypatch.setattr("requests.get", mock_get)

    retriever = HuggingFaceRetriever(hf_config)
    raw_papers = retriever._retrieve_raw_papers()
    assert raw_papers == []
