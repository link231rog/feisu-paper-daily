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


def test_restore_feishu_and_obsidian_annotations(tmp_path):
    """Verify direct annotation restoration across Feishu and Obsidian libraries."""
    from zotero_arxiv_daily.library import restore_feishu_note, restore_obsidian_note

    # 1. Feishu restoration with bilingual context & section heading
    blocks = [
        {"block_id": "b_h2_full", "block_type": 4, "heading2": {"elements": [{"text_run": {"content": "📄 论文完整原文与逐节研读区"}}]}},
        {"block_id": "b_sec1", "block_type": 4, "heading2": {"elements": [{"text_run": {"content": "1 Introduction"}}]}},
        {"block_id": "b_en", "block_type": 2, "text": {"elements": [{"text_run": {"content": "Memory-augmented agents maintain external storage across turns."}}]}},
        {"block_id": "b_zh", "block_type": 2, "text": {"elements": [{"text_run": {"content": "记忆增强智能体在多轮交互中维护外部存储。"}}]}},
    ]
    comments = [
        {
            "quote": "maintain external storage",
            "extra": {"content_anchor_id": "b_en"},
            "reply_list": {"replies": [{"content": {"elements": [{"text_run": {"text": "三个gap对应三个方法"}}]}}]},
        }
    ]
    feishu_note = restore_feishu_note(None, "doc_1", title="Oblivion", blocks_override=blocks, comments_override=comments)
    assert len(feishu_note["annotations"]) == 1
    ann = feishu_note["annotations"][0]
    assert ann["section"] == "1 Introduction"
    assert ann["comments"] == ["三个gap对应三个方法"]
    assert "Memory-augmented agents" in ann["paragraph"]
    assert "记忆增强智能体" in ann["paragraph_zh"]

    # 2. Obsidian restoration with ==highlight==^[comment]
    md_file = tmp_path / "paper.md"
    md_file.write_text(
        "---\ntitle: Memory-R1\n---\n## Method\n\nWe use ==decay-driven activation==^[核心衰减机制] to prune stale memories.\n",
        encoding="utf-8",
    )
    obs_note = restore_obsidian_note(md_file, tmp_path)
    assert obs_note["title"] == "Memory-R1"
    assert len(obs_note["annotations"]) == 1
    assert obs_note["annotations"][0]["quote"] == "decay-driven activation"
    assert obs_note["annotations"][0]["comments"] == ["核心衰减机制"]
    assert obs_note["annotations"][0]["section"] == "Method"

