"""Fast smoke test suite for Paper Daily core components."""

import pytest
from omegaconf import OmegaConf

from zotero_arxiv_daily.annotator import build_annotated_text_elements, locate_spans
from zotero_arxiv_daily.feishu import normalize_reading_status
from zotero_arxiv_daily.protocol import Paper
from zotero_arxiv_daily.reranker.local import LocalReranker
from zotero_arxiv_daily.textutil import extract_json
from zotero_arxiv_daily.utils import clean_paper_markdown


def test_config_composition():
    """Verify base and custom configs load and compose cleanly."""
    from zotero_arxiv_daily.executor import as_bool

    base = OmegaConf.load("config/base.yaml")
    custom = OmegaConf.load("config/custom.yaml")
    cfg = OmegaConf.merge(base, custom)
    assert cfg.executor.reranker in ("local", "api")
    assert as_bool(cfg.research.full_text_ar5iv) is False  # Must stay false for clean daily reports


def test_paper_protocol():
    """Verify Paper model serialization and field defaults."""
    p = Paper(
        source="arxiv",
        arxiv_id="2601.00001",
        title="Agentic Workflow for LLM",
        authors=["Alice", "Bob"],
        abstract="We present an autonomous agent memory system.",
        url="https://arxiv.org/abs/2601.00001",
        venue="arXiv.org",
    )
    assert p.arxiv_id == "2601.00001"
    assert p.title_with_venue() == "Agentic Workflow for LLM (arXiv.org)"
    assert normalize_reading_status("已精读") == "✅ 已精读"
    assert normalize_reading_status("reading") == "📖 精读中"


def test_clean_paper_markdown():
    """Verify citation and ligature cleanup in paper markdown."""
    raw = "Here is a claim [[1]](#bib.bib1) and another [ 1 , 2 ] with ligatures: fi, fl."
    cleaned = clean_paper_markdown(raw)
    assert "[[1]](#bib.bib1)" not in cleaned
    assert "[1]" in cleaned
    assert "[1, 2]" in cleaned


def test_textutil_extract_json():
    """Verify robust JSON extraction from LLM outputs."""
    raw_fenced = '```json\n{"status": "ok", "score": 9.5}\n```'
    assert extract_json(raw_fenced, {}) == {"status": "ok", "score": 9.5}

    raw_text = 'Here is the result: {"name": "Test"}'
    assert extract_json(raw_text, {}) == {"name": "Test"}


def test_locate_spans():
    """Verify character offset location and deduplication for inline annotations."""
    text = "We propose an adaptive memory system that reduces drift by 35%."
    annotations = [
        {"quote": "reduces drift by 35%", "type": "claim", "comment": "量化增益"},
        {"quote": "adaptive memory system", "type": "baseline", "comment": "核心机制"},
    ]
    spans = locate_spans(text, annotations)
    assert len(spans) == 2
    assert spans[0]["quote"] == "adaptive memory system"
    assert spans[1]["quote"] == "reduces drift by 35%"


def test_daily_card_abstract_only():
    """Verify daily report card strictly renders abstract and never leaks raw method/experiment sections."""
    p = Paper(
        source="arxiv",
        title="Sample Paper",
        authors=["Alice"],
        abstract="Sample abstract describing the core finding.",
        url="https://arxiv.org/abs/2601.99999",
    )
    p.annotation_sections = [
        {"id": "S1", "title": "摘要", "text": p.abstract},
        {"id": "S2", "title": "方法", "text": "Detailed method text that must not appear in card."},
    ]
    p.inline_annotations = [
        {"source": "S1", "quote": "core finding", "type": "claim", "comment": "关键发现"},
        {"source": "S2", "quote": "must not appear", "type": "baseline", "comment": "不应渲染"},
    ]
    elements = build_annotated_text_elements(p)
    text = "".join(e.get("text_run", {}).get("content", "") for e in elements)
    assert "【摘要】" in text
    assert "core finding" in text
    assert "【方法】" not in text
    assert "must not appear" not in text


def test_tfidf_reranker():
    """Verify local TF-IDF reranker scores candidates against corpus."""
    cfg = OmegaConf.create({"reranker": {"local": {"method": "tfidf"}}})
    reranker = LocalReranker(cfg)
    s1 = ["reinforcement learning for agent memory management"]
    s2 = ["deep reinforcement learning with memory buffer", "astronomy star clusters"]
    sim = reranker.get_similarity_score(s1, s2)
    assert sim.shape == (1, 2)
    assert sim[0, 0] > sim[0, 1]  # Agent memory should match memory buffer higher than astronomy
