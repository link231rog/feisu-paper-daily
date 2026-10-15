import pytest
from datetime import datetime
from omegaconf import OmegaConf

from zotero_arxiv_daily.executor import Executor
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.paper_store import PaperStore


def test_multi_source_executor_pipeline(tmp_path, monkeypatch):
    store_file = str(tmp_path / "paper_store.json")

    config = OmegaConf.create({
        "topics": [
            {
                "name": "Agent Systems",
                "keywords": ["agent", "reasoning"],
                "description": "Autonomous agents using large language models",
            }
        ],
        "source": {
            "arxiv": {"category": ["cs.AI"]},
            "huggingface": {"limit": 10},
            "semantic_scholar": {"queries": ["agent"], "limit_per_query": 5},
        },
        "llm": {
            "api": {"key": None, "base_url": None},
            "generation_kwargs": {"model": "gpt-4o-mini"},
            "language": "Chinese",
        },
        "reranker": {
            "api": {
                "key": "sk-fake",
                "base_url": "http://localhost:30000/v1",
                "model": "text-embedding-3-large",
            }
        },
        "feishu": {
            "app_id": None,
            "dry_run": True,
        },
        "email": {
            "sender": None,
        },
        "paper_store": {
            "path": store_file,
        },
        "executor": {
            "debug": False,
            "send_empty": False,
            "max_paper_num": 5,
            "source": ["arxiv", "huggingface", "semantic_scholar"],
            "reranker": "api",
        },
    })

    # Prepare candidate papers across sources with an overlapping paper
    # Paper 1 is on both arXiv and Hugging Face (same arxiv_id: 2401.00001)
    paper_arxiv = Paper(
        source="arxiv",
        title="Agent Alignment via DPO",
        authors=["Alice"],
        abstract="Aligning agents with direct preference optimization.",
        url="https://arxiv.org/abs/2401.00001",
        arxiv_id="2401.00001",
        sources=["arxiv"],
        published_date=datetime(2026, 10, 15),
    )
    paper_hf = Paper(
        source="huggingface",
        title="Agent Alignment via DPO",
        authors=["Alice"],
        abstract="Aligning agents with direct preference optimization.",
        url="https://huggingface.co/papers/2401.00001",
        arxiv_id="2401.00001",
        sources=["huggingface"],
        full_text="Full text from HF",
        published_date=datetime(2026, 10, 15),
    )
    # Paper 2 is from Semantic Scholar
    paper_s2 = Paper(
        source="semantic_scholar",
        title="Reasoning in Complex Agents",
        authors=["Bob"],
        abstract="A framework for multi-step reasoning in agents.",
        url="https://arxiv.org/abs/2401.00002",
        arxiv_id="2401.00002",
        doi="10.1234/reasoning",
        sources=["semantic_scholar"],
        published_date=datetime(2026, 10, 14),
    )

    # Stub retrievers
    monkeypatch.setattr(
        "zotero_arxiv_daily.retriever.arxiv_retriever.ArxivRetriever.retrieve_papers",
        lambda self: [paper_arxiv],
    )
    monkeypatch.setattr(
        "zotero_arxiv_daily.retriever.huggingface_retriever.HuggingFaceRetriever.retrieve_papers",
        lambda self: [paper_hf],
    )
    monkeypatch.setattr(
        "zotero_arxiv_daily.retriever.semantic_scholar_retriever.SemanticScholarRetriever.retrieve_papers",
        lambda self: [paper_s2],
    )

    # Stub reranker API embedding response
    from tests.canned_responses import make_stub_openai_client
    stub_client = make_stub_openai_client()
    monkeypatch.setattr("zotero_arxiv_daily.reranker.api.OpenAI", lambda **kw: stub_client)

    executor = Executor(config)
    executor.run()

    # Verify deduplication and mark_pushed in store
    store = PaperStore(store_file)
    pushed = store.data["pushed"]

    # Both papers should be pushed
    assert "2401.00001" in pushed
    assert "10.1234/reasoning" in pushed  # preferred DOI as dedup key

    # Next run should find 0 new papers
    executor2 = Executor(config)
    executor2.run()
