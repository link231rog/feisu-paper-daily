"""Fast smoke test suite for Paper Daily core components."""

import pytest
from omegaconf import OmegaConf

from paper_daily.annotator import build_annotated_text_elements, locate_spans
from paper_daily.feishu import normalize_reading_status
from paper_daily.protocol import Paper
from paper_daily.reranker.local import LocalReranker
from paper_daily.textutil import extract_json
from paper_daily.utils import clean_paper_markdown


def test_config_composition():
    """Verify base and custom configs load and compose cleanly."""
    from paper_daily.executor import as_bool

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
    from paper_daily.library import restore_feishu_note, restore_obsidian_note

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

    # 3. Hybrid bilingual search & ranking across restored notes
    from paper_daily.library import rank_library_notes

    ranked = rank_library_notes([feishu_note, obs_note], "外部存储 三个gap", top_k=2)
    assert len(ranked) >= 1
    assert ranked[0]["title"] == "Oblivion"
    assert ranked[0]["score"] > 5.0


def test_critical_paper_digest_and_no_icons():
    """Verify Critical-Paper-Digest deterministic scoring and strict icon-free report formatting."""
    import re
    from paper_daily.digest import (
        compute_review_confidence,
        format_digest_feishu_elements,
        format_digest_html,
    )
    from paper_daily.daily_report import _inline_annotated_html

    # 1. Deterministic scoring
    grades_high = {
        "claim_support": {"grade": "High", "reason": "实验完备"},
        "method_reusability": {"grade": "High", "reason": "即插即用"},
        "baseline_fairness": {"grade": "Medium", "reason": "对比合理"},
    }
    score, badge = compute_review_confidence(grades_high)
    assert score == int(2 * 2 + 2 * 1.5 + 1 * 1)  # 4 + 3 + 1 = 8
    assert "[强烈推荐复用]" in badge
    assert "🔥" not in badge

    grades_low = {
        "claim_support": {"grade": "Low", "reason": "仅在小数据集上有效"},
        "method_reusability": {"grade": "High", "reason": "可借鉴"},
        "baseline_fairness": {"grade": "Medium", "reason": "基线较全"},
    }
    _, badge_warn = compute_review_confidence(grades_low)
    assert "[证据存疑/基线较弱]" in badge_warn
    assert "⚠️" not in badge_warn

    # 2. Paper with critical digest
    p = Paper(
        source="arxiv",
        title="Sparse Attention Router",
        authors=["Alice"],
        abstract="We present Sparse Attention Router to achieve linear inference efficiency.",
        url="https://arxiv.org/abs/2601.11111",
    )
    p.critical_digest = {
        "delta": "基于 Query 熵值的动态 Top-K 块路由",
        "mechanism": {
            "pipeline": "长序列 Q,K,V -> 计算熵 H -> 选取 Top-k 关键块 -> 输出 O",
            "core_formula": "M_{i,j} = I(S_{i,j} >= TopK(S_i, k))",
            "symbol_dict": "H 为注意力熵，k 为保留块数",
        },
        "evidence_and_cost": {
            "metrics": "在 RULER (128K) 上比 MInference 高 +2.4%",
            "cost_and_limits": "Batch Size > 32 时显存增加 15%",
        },
        "action_or_check": "借用熵动态稀疏算子；[需查正文: 消融实验表 3]",
        "qualitative_grades": grades_high,
    }
    p.review_score = score
    p.review_badge = badge
    p.inline_annotations = [
        {"source": "S1", "quote": "linear inference efficiency", "type": "critique", "comment": "大batch显存暴涨"}
    ]
    p.annotation_sections = [{"id": "S1", "title": "摘要", "text": p.abstract}]

    # 3. Format Feishu elements and assert NO decorative emoji icons
    feishu_elems = format_digest_feishu_elements(p)
    text_content = "".join(e.get("text_run", {}).get("content", "") for e in feishu_elems)
    assert "[审稿评级]" in text_content
    assert "[核心增量]" in text_content
    assert "[方法链路与公式]" in text_content
    assert "[实验真相与代价]" in text_content
    assert "[启发与待查]" in text_content
    # Strict regex check: NO emoji icons in report text!
    assert not re.search(r"[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U00002600-\U000026FF]", text_content)

    # 4. Format HTML card and assert NO decorative emoji icons
    html_card = format_digest_html(p)
    assert "[审稿评级]" in html_card
    assert "核心公式" in html_card
    assert not re.search(r"[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U00002600-\U000026FF]", html_card)

    # 5. Inline annotated HTML and Feishu elements also icon-free
    inline_html = _inline_annotated_html(p)
    assert "[审阅批判]" in inline_html
    assert not re.search(r"[\U0001F300-\U0001F9FF\U00002700-\U000027BF\U00002600-\U000026FF]", inline_html)


def test_research_and_baseline_json_parsing():
    """Verify research and baseline pipelines call extract_json cleanly."""
    from paper_daily.baseline import extract_baselines
    from paper_daily.research import plan_queries

    class MockRouter:
        available = True
        def chat(self, messages, **kw):
            return '{"affirmative_s2": ["agent memory"], "adversarial_s2": ["kv cache"]}'

    plan = plan_queries(MockRouter(), ["agent memory"], "cs.AI")
    assert "agent memory" in plan["affirmative_s2"]
    assert "kv cache" in plan["adversarial_s2"]

    p = Paper(source="arxiv", title="T", authors=["A"], abstract="Text citing FlashAttention.", url="http://x")
    baselines = extract_baselines(MockRouter(), p)
    assert isinstance(baselines, list)


def test_dispatch_payload_overlay(monkeypatch):
    """Verify external dispatch payload from Hermes/Grok bot merges into console settings."""
    import json
    from paper_daily.console import _apply_dispatch_payload

    initial = {
        "tags": ["Agent"],
        "questions": ["Q1"],
        "custom_rules": [],
    }
    monkeypatch.setenv(
        "DISPATCH_PAYLOAD",
        json.dumps({
            "questions": ["Q2 from Hermes Bot"],
            "custom_rules": ["Zero hype rule"],
            "tags": ["Memory"],
        }),
    )
    merged = _apply_dispatch_payload(initial)
    assert "Q2 from Hermes Bot" in merged["questions"]
    assert "Zero hype rule" in merged["custom_rules"]
    assert "Memory" in merged["tags"]


def test_openreview_and_dblp_retrievers():
    """Verify OpenReview and DBLP retrievers are registered and convert API payloads into Paper objects."""
    from paper_daily.retriever import get_retriever_cls

    cfg = OmegaConf.create(
        {
            "source": {
                "openreview": {"queries": ["agent memory"], "limit_per_query": 5},
                "dblp": {"queries": ["agent memory"], "limit_per_query": 5, "min_year": 2025},
            }
        }
    )

    or_cls = get_retriever_cls("openreview")
    or_ret = or_cls(cfg)
    or_paper = or_ret.convert_to_paper(
        {
            "id": "abc123forum",
            "forum": "abc123forum",
            "content": {
                "title": {"value": "Memory-R1: Deliberative Agent Memory"},
                "abstract": {"value": "We propose Memory-R1 for long-horizon agent memory management."},
                "authors": {"value": ["Alice Zhang", "Bob Li"]},
                "venue": {"value": "ICLR 2026"},
            },
        }
    )
    assert or_paper is not None
    assert or_paper.source == "openreview"
    assert or_paper.title == "Memory-R1: Deliberative Agent Memory"
    assert or_paper.venue == "ICLR 2026"
    assert or_paper.pdf_url == "https://openreview.net/pdf?id=abc123forum"

    dblp_cls = get_retriever_cls("dblp")
    dblp_ret = dblp_cls(cfg)
    dblp_paper = dblp_ret.convert_to_paper(
        {
            "title": "Structured Graph Memory for Multi-Agent Systems.",
            "authors": {"author": [{"text": "Zixuan Huang 0001"}, {"text": "Jane Doe"}]},
            "venue": "NeurIPS",
            "year": "2025",
            "ee": "https://arxiv.org/abs/2510.12345",
        }
    )
    assert dblp_paper is not None
    assert dblp_paper.source == "dblp"
    assert dblp_paper.arxiv_id == "2510.12345"
    assert "Zixuan Huang" in dblp_paper.authors
    assert "NeurIPS 2025" in (dblp_paper.venue or "")


def test_console_custom_skills_templates_and_writeback(tmp_path):
    """Verify console parses custom skills/templates, expands external .md files, and writes back suggested questions."""
    from paper_daily.console import (
        append_suggested_questions_to_console,
        load_console_settings,
        parse_console_text,
    )

    skill_md = tmp_path / "my_review_skill.md"
    skill_md.write_text("- 核查所有消融实验是否控制了参量一致\n- 标注算力显存开销\n", encoding="utf-8")

    tpl_md = tmp_path / "my_note_template.md"
    tpl_md.write_text("- 复现路线：列出开源代码与超参配置\n", encoding="utf-8")

    console_md = tmp_path / "Console.md"
    console_md.write_text(
        "## 关注标签\n- Agent Memory\n\n"
        "## 关注问题\n- 如何降低长上下文记忆检索延迟？\n\n"
        "## 自定义 Skill\n- my_review_skill.md\n\n"
        "## 范例模板\n- my_note_template.md\n",
        encoding="utf-8",
    )

    parsed = parse_console_text(console_md.read_text(encoding="utf-8"), base_dir=tmp_path)
    assert "Agent Memory" in parsed["tags"]
    assert "如何降低长上下文记忆检索延迟？" in parsed["questions"]
    assert "核查所有消融实验是否控制了参量一致" in parsed["custom_rules"]
    assert "复现路线：列出开源代码与超参配置" in parsed["note_template"]

    cfg = OmegaConf.create(
        {
            "console": {"enabled": True, "provider": "obsidian"},
            "obsidian": {"enabled": True, "vault_path": str(tmp_path), "console_path": "Console.md"},
        }
    )
    loaded = load_console_settings(cfg)
    assert "标注算力显存开销" in loaded["custom_rules"]

    ok = append_suggested_questions_to_console(cfg, ["新追问：稀疏记忆索引在百万 token 下的召回率如何？"])
    assert ok is True
    updated_text = console_md.read_text(encoding="utf-8")
    assert "## 建议问题（待确认）" in updated_text
    assert "新追问：稀疏记忆索引在百万 token 下的召回率如何？" in updated_text


def test_obsidian_ingestion_and_detail_annotations(tmp_path):
    """Verify Obsidian checked-task discovery and reading note generation with detail annotations."""
    from paper_daily.library import (
        fetch_checked_papers_from_obsidian,
        restore_obsidian_note,
        write_obsidian_reading_note,
    )

    daily_md = tmp_path / "Daily.md"
    daily_md.write_text(
        "- [x] [Episodic Memory Router](https://arxiv.org/abs/2602.00111) 核心路由机制\n",
        encoding="utf-8",
    )
    obs_cfg = {"enabled": True, "vault_path": str(tmp_path), "notes_folder": "Literature"}
    checked = fetch_checked_papers_from_obsidian(obs_cfg)
    assert len(checked) == 1
    assert checked[0]["title"] == "Episodic Memory Router"
    assert checked[0]["action"] == "ingest"

    p = Paper(
        source="arxiv",
        title="Episodic Memory Router",
        authors=["Alice"],
        abstract="We introduce an episodic gating router that reduces memory drift by 42%.",
        url="https://arxiv.org/abs/2602.00111",
        venue="ICML 2026",
    )
    p.inline_annotations = [
        {"quote": "reduces memory drift by 42%", "type": "claim", "comment": "在 LongMemEval 上的实测降低比例"}
    ]
    sections = {
        "core_summary": "提出事件门控路由器。",
        "motivation": "解决长程对话记忆漂移。",
        "method": "采用双层门控稀疏更新。",
        "experiments": "LongMemEval 提升 12%。",
        "takeaways": "可直接迁移至本地 Agent。",
        "复现路线": "已开源 PyTorch 权重与评估脚本。",
    }
    obs_url = write_obsidian_reading_note(obs_cfg, p, sections=sections, tags=["Memory", "Agent"])
    assert obs_url is not None and obs_url.startswith("obsidian://open")

    note_file = tmp_path / "Literature" / "Episodic Memory Router.md"
    assert note_file.is_file()
    restored = restore_obsidian_note(note_file, tmp_path)
    assert restored["title"] == "Episodic Memory Router"
    assert any(a["quote"] == "reduces memory drift by 42%" for a in restored["annotations"])


def test_telegram_and_digest_sections():
    """Verify Telegram message chunking and digest table/markdown extraction."""
    from paper_daily.digest import _extract_html_latexml_sections, _extract_markdown_sections
    from paper_daily.telegram import format_telegram_messages

    html_sample = """
    <section class="ltx_section"><h2>3 Methodology</h2><p>Our state transition equation is <math><annotation encoding="application/x-tex">s_{t+1} = f(s_t, a_t)</annotation></math>.</p></section>
    <section class="ltx_section"><h2>4 Experiments</h2><p>We evaluate on HotpotQA.</p></section>
    <figure class="ltx_table"><figcaption>Table 1: Main benchmark accuracy across 5 datasets (+4.8% over MemGPT).</figcaption></figure>
    """
    secs = _extract_html_latexml_sections(html_sample)
    assert "s_{t+1} = f(s_t, a_t)" in secs["method"]
    assert "Table 1" in secs["experiments"]

    md_sample = "## 3 Method\nWe design a hierarchical memory controller.\n## 4 Experiments\nTable 2 shows 15% speedup.\n"
    md_secs = _extract_markdown_sections(md_sample)
    assert "hierarchical memory controller" in md_secs["method"]
    assert "15% speedup" in md_secs["experiments"]

    p = Paper(
        source="arxiv",
        title="Hierarchical Memory Controller",
        authors=["Alice"],
        abstract="A fast memory controller.",
        url="https://arxiv.org/abs/2603.00001",
    )
    p.score = 9.2
    p.recommendation_tier = "deep_read"
    p.review_badge = "[强烈推荐复用] (高置信度)"
    p.critical_digest = {
        "delta": "双层键值记忆压缩",
        "mechanism": {"pipeline": "Query -> 稀疏路由 -> 记忆读写 -> 输出", "core_formula": "y = Wx"},
        "evidence_and_cost": {"metrics": "HotpotQA +4.8%", "cost_and_limits": "显存开销 < 2GB"},
        "action_or_check": "可直接复用路由模块",
    }
    msgs = format_telegram_messages(
        [p],
        question_briefs=[{"question": "如何压缩长程记忆？", "answer": "双层键值路由可降低 50% 显存", "gap": "多模态记忆尚待验证"}],
    )
    assert len(msgs) >= 1
    assert "Paper Daily" in msgs[0]
    assert "Hierarchical Memory Controller" in msgs[0]
    assert "双层键值记忆压缩" in msgs[0]


def test_init_wizard_multi_select_and_conditional_credentials(tmp_path):
    """Verify multi-select initialization wizard and conditional credential follow-up."""
    from paper_daily.init_wizard import (
        apply_init_configuration,
        get_agent_skill_schema,
        get_conditional_credential_prompts,
        run_interactive_init,
    )

    schema = get_agent_skill_schema()
    assert schema["skill_name"] == "paper-daily-init"
    assert len(schema["phase_1_multi_select_questions"]) == 4

    # Conditional credentials should only include llm + selected channels
    cond = get_conditional_credential_prompts(
        libraries=["obsidian", "notion"],
        sources=["arxiv", "openreview", "semantic_scholar"],
        deliveries=["telegram"],
    )
    assert set(cond.keys()) == {"llm", "obsidian", "notion", "semantic_scholar", "telegram"}
    assert "feishu" not in cond
    assert "wechat" not in cond

    vault_dir = tmp_path / "vault"
    yaml_out = tmp_path / "custom.yaml"
    env_out = tmp_path / ".env"

    payload = {
        "libraries": ["obsidian", "feishu"],
        "sources": ["arxiv", "openreview", "dblp", "news_and_trends"],
        "deliveries": ["telegram", "email"],
        "deploy_modes": ["github_actions", "agent_cli"],
        "tags": ["LLM Agents", "Episodic Memory"],
        "questions": ["How to bound episodic memory growth in long-horizon agents?"],
        "credentials": {
            "OPENAI_API_BASE": "https://api.deepseek.com/v1",
            "OPENAI_MODEL": "deepseek-chat",
            "LLM_API_KEYS": "sk-test-123",
            "OBSIDIAN_VAULT_PATH": str(vault_dir),
            "FEISHU_APP_ID": "cli_abc",
            "FEISHU_APP_SECRET": "sec_xyz",
            "TELEGRAM_BOT_TOKEN": "123456:ABCDEF",
            "TELEGRAM_CHAT_ID": "-100987654",
            "SMTP_SERVER": "smtp.qq.com",
            "SENDER": "me@qq.com",
            "SENDER_PASSWORD": "pass",
            "RECEIVER": "you@qq.com",
        },
    }
    res = apply_init_configuration(payload, custom_yaml_path=yaml_out, env_path=env_out)
    assert res["status"] == "success"
    assert yaml_out.is_file()
    assert env_out.is_file()
    assert (vault_dir / "Console.md").is_file()

    yaml_text = yaml_out.read_text(encoding="utf-8")
    assert "openreview" in yaml_text
    assert "dblp" in yaml_text
    assert "deepseek-chat" in yaml_text
    assert any("TELEGRAM_BOT_TOKEN" in cmd for cmd in res["gh_secret_commands"])

    # Also test interactive wizard with scripted answers
    inputs = iter(
        [
            "2",          # Step 1: obsidian
            "1,4",        # Step 2: arxiv, openreview
            "4",          # Step 3: telegram
            "1,2",        # Step 4: github_actions, agent_cli
            "Agent, RL",  # Step 5: tags
            "What is the sample efficiency of RL agents?",  # Step 5: questions
            "",           # OPENAI_API_BASE (default)
            "",           # OPENAI_MODEL (default)
            "sk-interactive-999",  # LLM_API_KEYS
            str(tmp_path / "vault2"),  # OBSIDIAN_VAULT_PATH
            "",           # OBSIDIAN_CONSOLE_PATH (default)
            "",           # OBSIDIAN_NOTES_FOLDER (default)
            "bot-token-777",  # TELEGRAM_BOT_TOKEN
            "chat-888",   # TELEGRAM_CHAT_ID
        ]
    )
    res2 = run_interactive_init(
        custom_yaml_path=tmp_path / "custom2.yaml",
        env_path=tmp_path / ".env2",
        input_fn=lambda _prompt: next(inputs),
    )
    assert res2["selected"]["libraries"] == ["obsidian"]
    assert res2["selected"]["sources"] == ["arxiv", "openreview"]
    assert res2["selected"]["deliveries"] == ["telegram"]
    assert "TELEGRAM_BOT_TOKEN=bot-token-777" in (tmp_path / ".env2").read_text(encoding="utf-8")

    from paper_daily.init_wizard import export_agent_skill_markdown
    skill_text = export_agent_skill_markdown()
    assert "name: paper-daily" in skill_text
    assert "gh repo fork link231rog/feisu-paper-daily --clone=false" in skill_text
    assert "gh secret set" in skill_text


def test_wechat_multi_mode_and_subpackage_imports(tmp_path):
    """Verify WeChat 3-mode article generation, academic cover generation, and subpackage imports."""
    from paper_daily.channels import (
        build_wechat_articles,
        convert_links_to_wechat_footnotes,
        generate_academic_cover,
    )
    from paper_daily.core import ResearchState, compute_review_confidence, locate_spans
    from paper_daily.library import parse_console_text, rank_library_notes

    p = Paper(
        source="arxiv",
        title="Sparse Memory Routing for Long-Horizon Agents",
        authors=["Alice", "Bob"],
        abstract="We propose sparse memory routing that improves 128K recall by 6.2%.",
        url="https://arxiv.org/abs/2604.12345",
        venue="ICML 2026",
    )
    p.recommendation_tier = "deep_read"
    p.tldr = "提出稀疏记忆路由机制，在 128K 上下文召回率提升 6.2%。"
    p.qa_matches = [{"question": "如何提升长上下文记忆召回？", "answer": "稀疏记忆路由提升 6.2%"}]
    p.critical_digest = {
        "delta": "双层稀疏记忆路由",
        "mechanism": {"pipeline": "Query -> Router -> MemoryRead", "core_formula": "s = softmax(QK^T)"},
        "evidence_and_cost": {"metrics": "128K Recall +6.2%", "cost_and_limits": "额外延迟 < 3%"},
        "action_or_check": "可直接迁移路由算子",
    }
    briefs = [
        {
            "question": "如何提升长上下文记忆召回？",
            "summary": "今日文献表明双层稀疏路由可显著降低长上下文检索噪声。",
            "gap": "多模态视频记忆尚待验证",
            "evidence": [{"title": p.title, "url": p.url, "finding": p.tldr}],
            "counter_evidence": [],
        }
    ]

    articles = build_wechat_articles(
        [p],
        question_briefs=briefs,
        modes=["digest", "deep_read", "topic_review"],
    )
    assert len(articles) == 3
    assert "论文研究日报" in articles[0].title
    assert "精读｜" in articles[1].title
    assert "问题追踪｜" in articles[2].title
    assert "参考资料与原文链接" in convert_links_to_wechat_footnotes('<p><a href="https://arxiv.org/abs/2604.12345">原文</a></p>')

    cover_file = generate_academic_cover(
        title="论文研究日报",
        subtitle="Sparse Memory Routing",
        output_path=tmp_path / "cover.png",
    )
    assert cover_file.is_file() and cover_file.stat().st_size > 100

    st = ResearchState(str(tmp_path / "state.json"))
    st.record(briefs)
    assert st.gap("如何提升长上下文记忆召回？") == "多模态视频记忆尚待验证"

    # Test backward compatibility where legacy cache stored evidence_days as list and supporting as dict
    st.questions["legacy_q"] = {
        "evidence_days": ["2026-10-25", "2026-10-26"],
        "last_evidence_date": "2026-10-26",
        "supporting": {"url1": {"url": "http://1", "title": "t1"}},
        "counter": {"url2": {"url": "http://2", "title": "t2"}},
    }
    st.record([{"question": "legacy_q", "evidence": [{"url": "http://test", "title": "test"}]}])
    assert st.questions["legacy_q"]["evidence_days"] == 3
    assert isinstance(st.questions["legacy_q"]["supporting"], list)
    assert isinstance(st.questions["legacy_q"]["counter"], list)
    assert any(e.get("url") == "http://test" for e in st.questions["legacy_q"]["supporting"])

    assert callable(compute_review_confidence) and callable(locate_spans)
    assert callable(parse_console_text) and callable(rank_library_notes)


def test_recommendation_algorithms_and_4d_rubric_scoring(tmp_path):
    """Verify Max-TopK similarity, Rocchio negative feedback, MMR diversity, 4D rubric scoring, and artifact/HF signals."""
    from datetime import datetime
    from omegaconf import OmegaConf
    from paper_daily.protocol import CorpusPaper, Paper, extract_paper_artifacts
    from paper_daily.reranker.local import LocalReranker
    from paper_daily.core.digest import (
        compute_composite_paper_score,
        format_digest_html,
        normalize_rubric_scores,
        rerank_by_composite_score,
    )
    from paper_daily.core.paper_store import PaperStore

    # 1. Automatic GitHub & Project URL artifact extraction (ignoring generic pytorch/pytorch)
    text_sample = (
        "We build on https://github.com/pytorch/pytorch and release our agent memory code at "
        "https://github.com/acme-lab/sparse-agent-memory. Project page: https://acme-lab.github.io/sparse-memory/"
    )
    arts = extract_paper_artifacts(text_sample)
    assert arts["code_url"] == "https://github.com/acme-lab/sparse-agent-memory"
    assert arts["project_url"] == "https://acme-lab.github.io/sparse-memory"

    # 2. Cross-source deduplication preserves hf_upvotes, code_url, project_url
    store = PaperStore(str(tmp_path / "store.json"))
    p_arxiv = Paper(
        source="arxiv",
        title="Episodic Memory Routing for LLM Agents",
        authors=["Alice"],
        abstract="We propose episodic memory routing for long-horizon LLM agents.",
        url="https://arxiv.org/abs/2605.00001",
        arxiv_id="2605.00001",
        sources=["arxiv"],
    )
    p_hf = Paper(
        source="huggingface",
        title="Episodic Memory Routing for LLM Agents",
        authors=["Alice"],
        abstract="We propose episodic memory routing.",
        url="https://huggingface.co/papers/2605.00001",
        arxiv_id="2605.00001",
        sources=["huggingface"],
        code_url="https://github.com/alice/episodic-router",
        project_url="https://alice.github.io/episodic-router",
        hf_upvotes=48,
    )
    deduped = store.dedup([p_arxiv, p_hf])
    assert len(deduped) == 1
    assert deduped[0].code_url == "https://github.com/alice/episodic-router"
    assert deduped[0].project_url == "https://alice.github.io/episodic-router"
    assert deduped[0].hf_upvotes == 48
    assert set(deduped[0].sources or []) == {"arxiv", "huggingface"}

    # 3. Max-TopK + Rocchio Negative Feedback + MMR Diversity Selection
    cfg = OmegaConf.create(
        {
            "reranker": {
                "max_sim_alpha": 0.5,
                "top_k_anchors": 2,
                "rocchio_beta": 0.5,
                "rocchio_neg_threshold": 0.10,
                "mmr_lambda": 0.6,
                "code_boost": 0.4,
                "hf_boost_max": 0.8,
                "local": {"method": "tfidf"},
            }
        }
    )
    reranker = LocalReranker(cfg)
    corpus = [
        CorpusPaper(
            title="Hierarchical Episodic Memory for Autonomous Agents",
            abstract="Hierarchical episodic memory retrieval and kv-cache routing for long-horizon autonomous agents.",
            added_date=datetime(2026, 4, 1),
            paths=["feishu/Memory"],
        ),
        CorpusPaper(
            title="Reinforcement Learning with Verifiable Rewards",
            abstract="Policy optimization with verifiable reward signals for multi-step mathematical reasoning.",
            added_date=datetime(2026, 3, 20),
            paths=["feishu/RL"],
        ),
    ]
    c_target = Paper(
        source="arxiv",
        title="Sparse Episodic Memory Routing for Autonomous Agents",
        authors=["A"],
        abstract="We design hierarchical episodic memory routing for long-horizon autonomous agents. Code: https://github.com/org/sparse-mem",
        url="https://arxiv.org/abs/2605.00010",
        hf_upvotes=35,
    )
    c_clone = Paper(
        source="arxiv",
        title="Sparse Episodic Memory Routing for Autonomous Agents Variant",
        authors=["B"],
        abstract="We design hierarchical episodic memory routing for long-horizon autonomous agents with minor tweaks.",
        url="https://arxiv.org/abs/2605.00011",
    )
    c_rl = Paper(
        source="arxiv",
        title="Reinforcement Learning with Verifiable Rewards for Reasoning Policies",
        authors=["C"],
        abstract="Policy optimization with verifiable reward signals for multi-step mathematical reasoning. Code: https://github.com/org/rl-verifiable",
        url="https://arxiv.org/abs/2605.00012",
    )
    c_discarded_like = Paper(
        source="arxiv",
        title="3D Medical CT Segmentation with U-Net",
        authors=["D"],
        abstract="Volumetric 3D medical CT organ segmentation with convolutional U-Net.",
        url="https://arxiv.org/abs/2605.00013",
    )

    ranked_no_neg = reranker.rerank([c_target, c_clone, c_rl, c_discarded_like], corpus)
    score_before_neg = c_discarded_like.score or 0.0

    ranked_with_neg = reranker.rerank(
        [c_target, c_clone, c_rl, c_discarded_like],
        corpus,
        negative_texts=["Volumetric 3D medical CT organ segmentation with convolutional U-Net"],
    )
    assert (c_discarded_like.score or 0.0) < score_before_neg
    assert ranked_with_neg[0].title in (c_target.title, c_rl.title)
    assert c_target.matched_anchor_title == "Hierarchical Episodic Memory for Autonomous Agents"

    # MMR diversity should pick c_target first, then prefer the distinct RL paper over the near-duplicate c_clone
    mmr_picked = reranker.mmr_select(
        [c_target, c_clone, c_rl],
        k=2,
        lambda_param=0.55,
        relevance_scores={id(c_target): 8.0, id(c_clone): 7.5, id(c_rl): 7.2},
    )
    assert len(mmr_picked) == 2
    assert mmr_picked[0].title == c_target.title
    assert mmr_picked[1].title == c_rl.title

    # 4. 4D OpenReview-style Rubric & Composite Re-ranking
    rubric_high = normalize_rubric_scores(
        {"delta": 5, "rigor": 5, "actionability": 4, "reproducibility": 5},
        has_code=True,
        has_sections=True,
    )
    rubric_weak = normalize_rubric_scores(
        {"delta": 3, "rigor": 1, "actionability": 2, "reproducibility": 2},
        grades={"claim_support": {"grade": "Low"}},
        has_code=False,
        has_sections=False,
    )
    c_rl.rubric_scores = rubric_high
    c_rl.review_badge = "[强烈推荐复用] (高置信度)"
    c_rl.critical_digest = {"delta": "可验证奖励塑形", "rubric_scores": rubric_high}

    c_clone.rubric_scores = rubric_weak
    c_clone.review_badge = "[证据存疑/基线较弱]"
    c_clone.critical_digest = {"delta": "同质化微调", "rubric_scores": rubric_weak}

    comp_rl = compute_composite_paper_score(c_rl)
    comp_clone = compute_composite_paper_score(c_clone)
    assert comp_rl > comp_clone

    recalibrated = rerank_by_composite_score([c_clone, c_rl], deep_read_quota=1)
    assert recalibrated[0].title == c_rl.title
    assert recalibrated[0].recommendation_tier == "deep_read"
    assert recalibrated[1].recommendation_tier == "quick_radar"

    html_card = format_digest_html(c_rl)
    assert "[四维量化评分]" in html_card
    assert "创新:5" in html_card


def test_audio_podcast_briefing_and_multichannel_delivery(tmp_path, monkeypatch):
    """Verify MP3 podcast/briefing script generation, frame concatenation, and Telegram/WeChat/Feishu audio delivery."""
    from paper_daily.channels.audio import (
        build_audio_script,
        build_wechat_60s_script,
        clean_text_for_tts,
        concat_mp3_segments,
        generate_daily_audio_bundle,
        generate_mpeg1_layer3_silence,
    )
    from paper_daily.channels.telegram import send_telegram_audio
    from paper_daily.channels.wechat import upload_wechat_voice_material
    from paper_daily.channels.feishu import FeishuClient

    # 1. Text sanitization for TTS (strip LaTeX, URLs, symbols)
    raw_txt = "We optimize $L = \\sum_{i=1}^N x_i$ -> see [Code](https://github.com/org/repo) and https://arxiv.org/abs/2605.00001."
    cleaned = clean_text_for_tts(raw_txt)
    assert "$" not in cleaned
    assert "https://" not in cleaned
    assert "再到" in cleaned

    # 2. Dialogue (NotebookLM-style) and Briefing script generation
    p = Paper(
        source="arxiv",
        title="Hierarchical Memory Routing for Long-Horizon Agents",
        authors=["Alice", "Bob"],
        abstract="We propose hierarchical memory routing that boosts 128K recall by 7.5%.",
        url="https://arxiv.org/abs/2605.00100",
        venue="NeurIPS 2026",
        code_url="https://github.com/acme/hier-memory",
    )
    p.recommendation_tier = "deep_read"
    p.matched_anchor_title = "Episodic Memory Agents"
    p.rubric_scores = {"delta": 5, "rigor": 4, "actionability": 5, "reproducibility": 5}
    p.critical_digest = {
        "delta": "双层稀疏记忆路由机制",
        "mechanism": {"pipeline": "Query -> 熵值路由 -> 稀疏读写"},
        "evidence_and_cost": {"metrics": "128K 召回率提升 7.5%", "cost_and_limits": "额外延迟低于 2%"},
        "action_or_check": "可直接集成至现有 Agent 记忆模块",
    }
    briefs = [{"question": "如何降低长上下文记忆检索延迟？", "summary": "双层稀疏路由显著降低检索开销", "gap": "超百万上下文待测"}]

    dialogue_segs = build_audio_script([p], question_briefs=briefs, mode="dialogue")
    speakers = [s.speaker for s in dialogue_segs]
    assert "host" in speakers and "expert" in speakers
    assert any("双层稀疏记忆路由机制" in s.text for s in dialogue_segs)

    briefing_segs = build_audio_script([p], question_briefs=briefs, mode="briefing")
    assert all(s.speaker == "host" for s in briefing_segs)
    assert any("已开源代码" in s.text for s in briefing_segs)

    wx_segs = build_wechat_60s_script([p], question_briefs=briefs)
    assert len(wx_segs) == 1
    assert len(wx_segs[0].text) <= 210

    # 3. Pure-Python MP3 frame concatenation & daily audio bundle generation
    id3_header = b"ID3\x03\x00\x00\x00\x00\x00\x04ABCD" + generate_mpeg1_layer3_silence(100)
    merged_mp3 = concat_mp3_segments([id3_header, id3_header], pause_ms=100)
    assert merged_mp3.startswith(b"ID3")
    assert b"\xff\xfb\x90\x64" in merged_mp3

    cfg = {
        "audio": {
            "enabled": True,
            "mode": "dialogue",
            "engine": "edge-tts",
            "output_dir": str(tmp_path / "audio_out"),
            "upload_wechat_voice": True,
        }
    }
    bundle = generate_daily_audio_bundle([p], cfg, question_briefs=briefs)
    assert bundle.mp3_path.is_file() and bundle.mp3_path.stat().st_size > 400
    assert bundle.script_path.is_file()
    assert bundle.wechat_mp3_path is not None and bundle.wechat_mp3_path.is_file()

    # 4. Mock verification for Telegram sendAudio, WeChat voice upload, and Feishu audio block mount
    class DummyResp:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code
            self.text = "ok"

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def mock_post(url, **kwargs):
        if "sendAudio" in url:
            return DummyResp({"ok": True, "result": {"message_id": 777}})
        if "add_material" in url:
            return DummyResp({"errcode": 0, "media_id": "wx_voice_999"})
        if "upload_all" in url:
            return DummyResp({"code": 0, "data": {"file_token": "feishu_audio_token_123"}})
        return DummyResp({"code": 0, "data": {"tenant_access_token": "t_tok"}})

    monkeypatch.setattr("requests.post", mock_post)

    tg_mid = send_telegram_audio(
        {"bot_token": "123:ABC", "chat_id": "999"},
        audio_path=bundle.mp3_path,
        title=bundle.title,
        duration=bundle.duration_seconds,
    )
    assert tg_mid == 777

    wx_mid = upload_wechat_voice_material("wx_token", bundle.wechat_mp3_path)
    assert wx_mid == "wx_voice_999"

    feishu_client = FeishuClient({"app_id": "cli_x", "app_secret": "sec_y", "dry_run": False})
    feishu_client._has_lark_cli = False
    feishu_client._tenant_token = "t_tok"

    def mock_call_api(method, path, params=None, data=None):
        if method == "GET" and path.endswith("/blocks"):
            return {"items": [], "has_more": False}
        if method == "POST" and "/children" in path:
            return {"children": [{"block_id": "blk_file_1", "block_type": 23}]}
        if method == "PATCH":
            return {"block": {"block_id": "blk_file_1"}}
        return {}

    monkeypatch.setattr(feishu_client, "_call_api", mock_call_api)
    mounted_token = feishu_client.upload_and_mount_audio("doc_abc", str(bundle.mp3_path))
    assert mounted_token == "feishu_audio_token_123"


def test_citation_chasing_paper_type_safety_and_interest_imports(monkeypatch):
    """Verify SemanticScholarRetriever.retrieve_related accepts Paper objects, and interest module resolves imports cleanly."""
    from paper_daily.core.interest import get_interest_corpus
    from paper_daily.protocol import Paper
    from paper_daily.retriever.semantic_scholar_retriever import SemanticScholarRetriever

    # 1. Type safety: retrieve_related with Paper instance
    ssr = SemanticScholarRetriever(OmegaConf.create({"source": {"semantic_scholar": {}}}))
    monkeypatch.setattr(ssr, "_request_with_retry", lambda _url, _params: {"data": []})
    p = Paper(
        source="arxiv",
        title="Test Memory Paper",
        authors=["Alice"],
        abstract="Test abstract",
        url="https://arxiv.org/abs/2601.12345",
    )
    # Should not raise TypeError when passed Paper instances or strings
    related_from_paper = ssr.retrieve_related([p])
    assert related_from_paper == []
    related_from_str = ssr.retrieve_related(["https://arxiv.org/abs/2601.12345"])
    assert related_from_str == []

    # 2. Interest corpus Feishu and Console import paths
    cfg = OmegaConf.create({
        "feishu": {"notes_parent_node_token": "dummy_token", "dry_run": True},
        "console": {"enabled": True},
        "executor": {},
    })
    # Should not raise ModuleNotFoundError: No module named 'paper_daily.core.feishu'
    corpus = get_interest_corpus(cfg)
    assert isinstance(corpus, list)


def test_zotero_and_notion_library_restoration(monkeypatch):
    """Verify Zotero and Notion note & annotation restoration logic in library bridge."""
    from paper_daily.library.bridge import restore_notion_page, restore_zotero_item

    # 1. Zotero item with child annotation and child note
    class DummyZotero:
        def children(self, _key):
            return [
                {
                    "data": {
                        "itemType": "annotation",
                        "annotationText": "Bounded memory routing lowers latency by 3x",
                        "annotationComment": "关键基线对比",
                        "annotationPageLabel": "4",
                    }
                },
                {
                    "data": {
                        "itemType": "note",
                        "note": "<p>Personal reflection: this design can be adapted to our RL agent.</p>",
                    }
                },
            ]

    zot = DummyZotero()
    parent_item = {
        "key": "ZOT123",
        "data": {
            "key": "ZOT123",
            "title": "Scalable Episodic Memory",
            "url": "https://arxiv.org/abs/2602.00001",
            "abstractNote": "A paper on scalable memory.",
        },
    }
    zot_res = restore_zotero_item(zot, parent_item)
    assert zot_res["source"] == "zotero"
    assert zot_res["id"] == "ZOT123"
    assert len(zot_res["annotations"]) == 1
    assert zot_res["annotations"][0]["quote"] == "Bounded memory routing lowers latency by 3x"
    assert zot_res["annotations"][0]["comments"] == ["关键基线对比"]
    assert zot_res["annotations"][0]["section"] == "Page 4"
    assert "Personal reflection" in zot_res["reflections"]["notes"][0]

    # 2. Notion page with heading, callout, and text blocks
    class DummyNotionResp:
        status_code = 200

        def json(self):
            return {
                "results": [
                    {
                        "type": "heading_2",
                        "heading_2": {"rich_text": [{"plain_text": "3. Proposed Mechanism"}]},
                    },
                    {
                        "type": "callout",
                        "callout": {"rich_text": [{"plain_text": "Important insight: zero-shot memory works best"}]},
                    },
                    {
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [
                                {
                                    "plain_text": "Highlighted sentence",
                                    "annotations": {"bold": True, "color": "yellow_background"},
                                }
                            ]
                        },
                    },
                ]
            }

    monkeypatch.setattr("requests.get", lambda _url, **_kwargs: DummyNotionResp())
    notion_res = restore_notion_page("secret_token", "page_abc_123", title="Notion Paper")
    assert notion_res["source"] == "notion"
    assert len(notion_res["annotations"]) == 2
    quotes = [a["quote"] for a in notion_res["annotations"]]
    assert "Important insight: zero-shot memory works best" in quotes
    assert "Highlighted sentence" in quotes


def test_email_delivery_with_mp3_attachment(tmp_path, monkeypatch):
    """Verify send_email constructs MIME multipart with MP3 audio attachment and sanitizes credentials."""
    from paper_daily.channels.daily_report import build_daily_report
    from paper_daily.protocol import Paper
    from paper_daily.utils import send_email

    mp3_file = tmp_path / "briefing.mp3"
    mp3_file.write_bytes(b"\xff\xfb\x90\x64" + b"\x00" * 128)

    cfg = OmegaConf.create({
        "email": {
            "sender": "  sender@qq.com \n",
            "receiver": " receiver1@qq.com , receiver2@qq.com \n",
            "sender_password": "  secret_token_123 \n",
            "smtp_server": " smtp.qq.com ",
            "smtp_port": 465,
        }
    })

    sent_messages = []

    class MockSMTP_SSL:
        def __init__(self, server, port, timeout=30):
            assert server == "smtp.qq.com"
            assert port == 465

        def login(self, user, password):
            assert user == "sender@qq.com"
            assert password == "secret_token_123"

        def sendmail(self, from_addr, to_addrs, msg_str):
            sent_messages.append({"from": from_addr, "to": to_addrs, "body": msg_str})

        def quit(self):
            pass

    monkeypatch.setattr("smtplib.SMTP_SSL", MockSMTP_SSL)

    send_email(
        cfg,
        html="<h1>Daily Literature Digest</h1>",
        subject="[Paper Daily] 2026-10-28 Report",
        attachments=[str(mp3_file)],
    )

    assert len(sent_messages) == 1
    record = sent_messages[0]
    import email
    parsed_msg = email.message_from_string(record["body"])
    assert parsed_msg.is_multipart()
    assert record["to"] == ["receiver1@qq.com", "receiver2@qq.com"]
    assert "audio/mpeg" in record["body"]
    assert "briefing.mp3" in record["body"]

    # Test CID inline images for framework diagrams
    poster_png = tmp_path / "framework.png"
    poster_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 30)
    p_visual = Paper(
        source="arxiv",
        title="Visual RL Paper",
        authors=["Alice"],
        abstract="abs",
        url="http://arxiv/1",
        arxiv_id="2610.12345",
    )
    p_visual.poster_path = str(poster_png)
    report_with_img = build_daily_report([p_visual])
    assert "cid:poster_1_2610_12345" in report_with_img.html
    assert len(report_with_img.inline_images) == 1

    send_email(
        cfg,
        html=report_with_img.html,
        subject="[Paper Daily] Visual Report",
        attachments=[str(mp3_file)],
        inline_images=report_with_img.inline_images,
    )
    assert len(sent_messages) == 2
    rec2 = sent_messages[1]
    assert "image/png" in rec2["body"]
    assert "<poster_1_2610_12345>" in rec2["body"]


def test_biorxiv_medrxiv_chemrxiv_retrievers(monkeypatch):
    """Verify bioRxiv, medRxiv, and ChemRxiv paper ingestion and metadata normalization."""
    from paper_daily.retriever.biorxiv_retriever import BiorxivRetriever
    from paper_daily.retriever.chemrxiv_retriever import ChemrxivRetriever
    from paper_daily.retriever.medrxiv_retriever import MedrxivRetriever

    # 1. bioRxiv
    bio = BiorxivRetriever(OmegaConf.create({"source": {"biorxiv": {"category": "neuroscience"}}}))
    raw_bio = {
        "title": "Neural Dynamics in LLM Memory Formations",
        "authors": "Alice Smith; Bob Jones",
        "abstract": "We investigate neural dynamics.",
        "doi": "10.1101/2026.01.01.123456",
        "version": "1",
        "date": "2026-01-01",
        "category": "neuroscience",
    }
    p_bio = bio.convert_to_paper(raw_bio)
    assert p_bio is not None
    assert p_bio.title == "Neural Dynamics in LLM Memory Formations"
    assert p_bio.source == "biorxiv"
    assert "Alice Smith" in p_bio.authors

    # 2. medRxiv
    med = MedrxivRetriever(OmegaConf.create({"source": {"medrxiv": {"category": "epidemiology"}}}))
    p_med = med.convert_to_paper(raw_bio)
    assert p_med is not None
    assert p_med.source == "medrxiv"

    # 3. ChemRxiv
    chem = ChemrxivRetriever(OmegaConf.create({"source": {"chemrxiv": {"lookback_hours": 48}}, "executor": {"debug": False}}))
    raw_chem = {
        "DOI": "10.26434/chemrxiv.2026.123",
        "title": ["Molecular Memory Representation with Graph Networks"],
        "author": [{"given": "Carol", "family": "White"}],
        "abstract": "Graph neural networks for chemical representations.",
        "created": {"date-time": "2026-01-01T00:00:00Z"},
        "URL": "https://doi.org/10.26434/chemrxiv.2026.123",
    }
    p_chem = chem.convert_to_paper(raw_chem)
    assert p_chem is not None
    assert p_chem.title == "Molecular Memory Representation with Graph Networks"
    assert p_chem.source == "chemrxiv"
    assert "Carol White" in p_chem.authors


def test_notebooklm_pipeline_and_dual_mode_topics(tmp_path, monkeypatch):
    """Verify NotebookLM topic grouping, persistent auto-volume split, daily mode, and dual-track audio."""
    import datetime
    from pathlib import Path
    from paper_daily.channels.notebooklm import (
        _resolve_auth_json,
        group_papers_by_topic,
        run_notebooklm_pipeline,
    )
    from paper_daily.protocol import Paper

    # 1. Topic grouping
    p1 = Paper(source="arxiv", title="Episodic Memory Agents", authors=["A"], abstract="abs", url="http://1", matched_anchor_title="Agent Memory")
    p2 = Paper(source="arxiv", title="Reinforcement Learning on Graphs", authors=["B"], abstract="abs", url="http://2")
    p2.tags = ["RL", "Reasoning"]
    p3 = Paper(source="arxiv", title="General LLM Reasoning Benchmark", authors=["C"], abstract="abs", url="http://3")
    p3.tags = ["Reasoning"]

    grouped = group_papers_by_topic([p1, p2, p3], configured_topics=["RL", "Reasoning"])
    assert "Agent Memory" in grouped
    assert "RL" in grouped
    assert grouped["Agent Memory"][0].title == "Episodic Memory Agents"

    # 2. Auth resolution from cookies string and JSON
    monkeypatch.setenv("NOTEBOOKLM_COOKIES", "SID=secret_sid_123; HSID=secret_hsid_456")
    resolved_json = _resolve_auth_json()
    assert resolved_json is not None
    assert "secret_sid_123" in resolved_json
    assert "secret_hsid_456" in resolved_json

    # 3. Mock NotebookLMClient to test persistent volume split & daily mode
    created_notebooks = []
    created_sources = []
    generated_tasks = []

    class DummyNotebook:
        def __init__(self, nb_id, title, sources_count=0):
            self.id = nb_id
            self.title = title
            self.sources_count = sources_count

    class MockNotebooksNS:
        def __init__(self):
            # Simulate an existing Vol.1 that reached 45 sources
            self._nbs = [DummyNotebook("nb_vol1", "[Topic] Agent Memory", sources_count=45)]

        async def list(self):
            return list(self._nbs)

        async def create(self, title):
            nb_id = f"nb_{len(created_notebooks) + 1}"
            nb = DummyNotebook(nb_id, title, sources_count=0)
            self._nbs.append(nb)
            created_notebooks.append((nb_id, title))
            return nb

    class MockSourcesNS:
        async def list(self, nb_id):
            return []

        async def add_url(self, nb_id, url, title=None, wait=True, wait_timeout=60.0):
            created_sources.append(("url", nb_id, url, title))
            return None

        async def add_text(self, nb_id, text, title=None):
            created_sources.append(("text", nb_id, title))
            return None

    class MockArtifactsNS:
        async def generate_audio(self, nb_id, **kwargs):
            generated_tasks.append((nb_id, kwargs))
            class Status:
                task_id = "task_999"
            return Status()

        async def wait_for_completion(self, nb_id, task_id, timeout=300.0):
            class Status:
                state = "COMPLETED"
            return Status()

        async def download_audio(self, nb_id, output_path):
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"\xff\xfb\x90\x64" * 10)  # Dummy MP3
            return str(p)

    class MockClientContext:
        def __init__(self):
            self.notebooks = MockNotebooksNS()
            self.sources = MockSourcesNS()
            self.artifacts = MockArtifactsNS()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    import notebooklm
    monkeypatch.setattr(notebooklm.NotebookLMClient, "from_storage", lambda *args, **kwargs: MockClientContext())

    out_dir = tmp_path / "nblm_audio"
    cfg = OmegaConf.create({
        "notebooklm": {
            "enabled": True,
            "notebook_mode": "persistent",
            "max_sources_per_notebook": 45,
            "generate_audio": True,
            "audio_language": "zh",
            "audio_format": "deep_dive",
            "audio_length": "default",
            "max_topics": 1,
            "output_dir": str(out_dir),
        }
    })

    # Run pipeline in persistent mode: Vol.1 is full (45 sources), so it should auto-split into Vol.2!
    bundles = run_notebooklm_pipeline([p1], cfg)
    assert len(bundles) == 1
    assert bundles[0].engine == "notebooklm"
    assert "NotebookLM 深度播客" in bundles[0].title
    assert bundles[0].mp3_path.is_file()

    # Verify Vol.2 was created due to auto-volume split threshold
    assert any("Vol.2" in title for _, title in created_notebooks)
    assert any(url == p1.url for kind, _, url, _ in created_sources if kind == "url")

    # Run pipeline in daily mode
    cfg_daily = OmegaConf.create({
        "notebooklm": {
            "enabled": True,
            "notebook_mode": "daily",
            "generate_audio": True,
            "output_dir": str(out_dir),
        }
    })
    created_notebooks.clear()
    bundles_daily = run_notebooklm_pipeline([p1], cfg_daily)
    assert len(bundles_daily) == 1
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    assert any(today_str in title for _, title in created_notebooks)


def test_pipeline_dag_fallback_chain_and_agent_reach(tmp_path, monkeypatch):
    """Verify Pipeline DAG stage sequencing, Agent-Reach fallback chains, and external CLI assembly."""
    import json
    from omegaconf import OmegaConf
    from paper_daily.pipeline import (
        Backend,
        FallbackChain,
        PipelineContext,
        PipelineEngine,
        PipelineStage,
    )
    from paper_daily.pipeline.backends.agent_reach import AgentReachCLI
    from paper_daily.pipeline.backends.fulltext_backends import AgentReachReadBackend
    from paper_daily.pipeline.stages.enrich_stage import EnrichStage
    from paper_daily.protocol import Paper

    # 1. Test FallbackChain (Agent-Reach style ordered backends)
    class FailingBackend(Backend[str]):
        name = "failing_primary"

        def execute(self, *args, **kwargs):
            raise ConnectionError("Network timeout on primary backend")

    class WorkingBackend(Backend[str]):
        name = "working_secondary"

        def execute(self, *args, **kwargs):
            return "# Full Text Extracted via Secondary Backend"

    chain = FallbackChain[str]([FailingBackend(), WorkingBackend()], name="test_chain")
    res = chain.execute("https://example.com/paper.pdf")
    assert res.ok is True
    assert res.backend_name == "working_secondary"
    assert "Full Text Extracted" in res.data
    assert res.elapsed_seconds >= 0.0

    # 2. Test AgentReachCLI Mocking
    class MockProcess:
        def __init__(self, stdout_text, returncode=0):
            self.stdout = stdout_text
            self.stderr = ""
            self.returncode = returncode

    # Mock Bilibili search
    def mock_subprocess_run(cmd, *args, **kwargs):
        if "bilibili" in cmd:
            payload = {
                "ok": True,
                "result": [
                    {"title": "【顶会精读】Agent 记忆架构深度拆解", "bvid": "BV1xx411c7X", "author": "AI科研社"}
                ],
            }
            return MockProcess(json.dumps(payload))
        if "read" in cmd:
            payload = {
                "ok": True,
                "result": "# Paper Markdown Body via Agent Reach\n\nClean extracted text with no ads. Comprehensive architecture breakdown for agents and models.",
            }
            return MockProcess(json.dumps(payload))
        return MockProcess("{\"ok\": false}")

    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/local/bin/agent-reach" if cmd == "agent-reach" else None)
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)

    assert AgentReachCLI.is_installed() is True
    bili_items = AgentReachCLI.search_bilibili("Agent Memory", limit=1)
    assert len(bili_items) == 1
    assert "Agent 记忆架构" in bili_items[0]["title"]

    # Test AgentReachReadBackend
    read_backend = AgentReachReadBackend()
    assert read_backend.is_available() is True
    read_res = read_backend.execute("https://some-paywalled-blog.com/paper")
    assert read_res is not None
    assert "Paper Markdown Body" in read_res

    # 3. Test PipelineEngine & Context stage execution
    stage_log = []

    class StageA(PipelineStage):
        name = "stage_a"

        def run(self, context: PipelineContext) -> None:
            stage_log.append("A")
            context.funnel["stage_a"] = 100

    class StageB(PipelineStage):
        name = "stage_b"

        def run(self, context: PipelineContext) -> None:
            stage_log.append("B")
            context.funnel["stage_b"] = 50

    engine = PipelineEngine([StageA(), StageB()])
    ctx = PipelineContext(config=OmegaConf.create({"executor": {"send_empty": True}}))
    engine.execute(ctx)

    assert stage_log == ["A", "B"]
    assert ctx.funnel["stage_a"] == 100
    assert ctx.funnel["stage_b"] == 50
    assert "stage_a" in ctx.stage_durations
    assert "stage_b" in ctx.stage_durations

    # 4. Test EnrichStage with AgentReach assembly
    p = Paper(
        source="arxiv",
        title="Scalable Memory Architecture for LLM Agents",
        authors=["Alice", "Bob"],
        abstract="Novel hierarchical memory for long-horizon planning.",
        url="https://arxiv.org/abs/2610.12345",
    )
    p.recommendation_tier = "deep_read"

    cfg_with_ar = OmegaConf.create({
        "agent_reach": {
            "enabled": True,
            "channels": ["bilibili"],
            "max_papers_to_enrich": 1,
            "timeout": 5.0,
        },
        "news_and_trends": {"enabled": False},
        "executor": {"tldr_workers": 1},
    })

    class DummyExecutor:
        def __init__(self):
            self.research_cfg = {"baselines": False, "synthesis": False}

    enrich_stage = EnrichStage(DummyExecutor())
    ctx_enrich = PipelineContext(config=cfg_with_ar)
    ctx_enrich.reranked_papers = [p]
    ctx_enrich.deep_read_papers = [p]

    enrich_stage.run(ctx_enrich)
    assert p.url in ctx_enrich.enrichments
    assert "bilibili" in ctx_enrich.enrichments[p.url]
    assert len(ctx_enrich.enrichments[p.url]["bilibili"]) == 1


def test_wechat_doocs_md_and_proxy_support(tmp_path, monkeypatch):
    """Verify doocs/md table/code formatting and outbound proxy/api_base forwarding for WeChat."""
    from paper_daily.channels.wechat import (
        create_draft,
        get_access_token,
        markdown_to_wechat_html,
        upload_cover,
        upload_wechat_voice_material,
    )
    from paper_daily.channels.daily_report import DailyReport

    # 1. Verify doocs/md Markdown styling (table scroll wrap & Mac code block window header)
    md_sample = (
        "# 论文日报\n\n"
        "## 01 核心增量\n\n"
        "| 模型 | 参数 | 召回率 |\n"
        "|---|---|---|\n"
        "| Baseline | 7B | 82.1% |\n"
        "| Ours | 7B | 88.5% |\n\n"
        "```python\n"
        "def forward(x):\n"
        "    return router(x)\n"
        "```\n"
    )
    html_out = markdown_to_wechat_html(md_sample)
    assert "overflow-x:auto" in html_out
    assert "background:#ef4444" in html_out  # Mac red dot
    assert "background:#f59e0b" in html_out  # Mac yellow dot
    assert "background:#10b981" in html_out  # Mac green dot
    assert "<table" in html_out

    # 2. Verify proxy_url and api_base forwarding across requests
    captured_requests = []

    class DummyResp:
        def __init__(self, data, status_code=200):
            self._data = data
            self.status_code = status_code

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def mock_get(url, **kwargs):
        captured_requests.append(("GET", url, kwargs))
        if "/cgi-bin/token" in url:
            return DummyResp({"access_token": "mock_wx_token_123", "expires_in": 7200})
        return DummyResp({})

    def mock_post(url, **kwargs):
        captured_requests.append(("POST", url, kwargs))
        if "/material/add_material" in url:
            return DummyResp({"media_id": "media_cover_888"})
        if "/cgi-bin/draft/add" in url:
            return DummyResp({"media_id": "draft_media_999"})
        return DummyResp({})

    monkeypatch.setattr("requests.get", mock_get)
    monkeypatch.setattr("requests.post", mock_post)

    cfg = {
        "app_id": "wx_app_test",
        "app_secret": "wx_secret_test",
        "api_base": "https://custom.wechat.proxy/v1",
        "proxy_url": "http://user:pass@127.0.0.1:8080",
        "author": "Paper Daily",
    }

    # Test token fetching through custom api_base and proxy
    token = get_access_token(
        cfg["app_id"],
        cfg["app_secret"],
        api_base=cfg["api_base"],
        proxy_url=cfg["proxy_url"],
    )
    assert token == "mock_wx_token_123"
    assert any(
        req[0] == "GET"
        and "custom.wechat.proxy/v1/cgi-bin/token" in req[1]
        and req[2].get("proxies") == {"http": "http://user:pass@127.0.0.1:8080", "https": "http://user:pass@127.0.0.1:8080"}
        for req in captured_requests
    )

    # Test cover upload through custom proxy
    dummy_img = tmp_path / "test_cover.png"
    dummy_img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
    cover_media = upload_cover(
        token,
        str(dummy_img),
        api_base=cfg["api_base"],
        proxy_url=cfg["proxy_url"],
    )
    assert cover_media == "media_cover_888"
    assert any(
        req[0] == "POST"
        and "custom.wechat.proxy/v1/cgi-bin/material/add_material" in req[1]
        and req[2].get("proxies") == {"http": "http://user:pass@127.0.0.1:8080", "https": "http://user:pass@127.0.0.1:8080"}
        for req in captured_requests
    )

    # Test voice upload through custom proxy
    dummy_voice = tmp_path / "voice.mp3"
    dummy_voice.write_bytes(b"\xff\xfb\x90\x64" * 10)
    voice_media = upload_wechat_voice_material(
        token,
        dummy_voice,
        api_base=cfg["api_base"],
        proxy_url=cfg["proxy_url"],
    )
    assert voice_media == "media_cover_888"

    # Test create_draft through custom proxy
    rep = DailyReport(title="今日文献精选", html="<p>正文内容</p>", digest="精选导读")
    draft_id = create_draft(cfg, rep)
    assert draft_id == "draft_media_999"
    assert any(
        req[0] == "POST"
        and "custom.wechat.proxy/v1/cgi-bin/draft/add" in req[1]
        and req[2].get("proxies") == {"http": "http://user:pass@127.0.0.1:8080", "https": "http://user:pass@127.0.0.1:8080"}
        for req in captured_requests
    )


def test_agent_literature_find_and_ingest(tmp_path, monkeypatch):
    """Verifies Coding Agent active literature search, MMR reranking, and zero-checklist direct ingestion."""
    from paper_daily.library.finder import (
        find_papers,
        format_found_papers_markdown,
        ingest_paper_direct,
        normalize_paper_url,
    )

    # 1. URL & ID normalization
    assert normalize_paper_url("2401.12345") == "https://arxiv.org/abs/2401.12345"
    assert normalize_paper_url("2401.12345v2") == "https://arxiv.org/abs/2401.12345v2"
    assert normalize_paper_url("arxiv:2401.99999") == "https://arxiv.org/abs/2401.99999"
    assert normalize_paper_url("10.1145/3613904.3642456") == "https://doi.org/10.1145/3613904.3642456"

    # 2. Mock online search backends (arXiv and DBLP)
    sample_arxiv_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
      <entry>
        <id>http://arxiv.org/abs/2602.13530v1</id>
        <title>REMem: Reasoning with Episodic Memory in Language Agent</title>
        <summary>A foundational study on episodic memory architecture for LLM agents. Code: https://github.com/agent/remem</summary>
        <author><name>Yiheng Shu</name></author>
        <published>2026-02-15T00:00:00Z</published>
        <arxiv:comment>Accepted to ICLR 2026</arxiv:comment>
      </entry>
      <entry>
        <id>http://arxiv.org/abs/2501.99999v1</id>
        <title>Language Agent Planning with World Models</title>
        <summary>Planning algorithms for autonomous code agents.</summary>
        <author><name>Jane Doe</name></author>
        <published>2025-01-10T00:00:00Z</published>
      </entry>
    </feed>
    """

    class MockResp:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

        def json(self):
            import json
            return json.loads(self.text)

    def mock_requests_get(url, *args, **kwargs):
        if "export.arxiv.org" in url:
            return MockResp(sample_arxiv_xml)
        if "dblp.org" in url:
            return MockResp(
                json.dumps(
                    {
                        "result": {
                            "hits": {
                                "hit": [
                                    {
                                        "info": {
                                            "title": "Autonomous Coding Agent Architecture Benchmark.",
                                            "authors": {"author": [{"text": "Alice"}]},
                                            "year": "2026",
                                            "venue": "ICSE 2026",
                                            "ee": "https://doi.org/10.1145/icse2026",
                                        }
                                    }
                                ]
                            }
                        }
                    }
                )
            )
        return MockResp("{}", status_code=404)

    monkeypatch.setattr("requests.get", mock_requests_get)

    cfg = OmegaConf.create({
        "executor": {"source": ["arxiv"], "reranker": "local"},
        "reranker": {"local": {"method": "tfidf"}, "max_sim_alpha": 0.45},
    })

    found = find_papers("episodic memory agent", top_k=2, config=cfg)
    assert len(found) >= 1
    top1 = found[0]
    assert "REMem" in top1["title"]
    assert top1["venue"] == "ICLR 2026"
    assert top1["year"] == 2026
    assert top1["code_url"] == "https://github.com/agent/remem"
    assert top1["score"] > 0

    # Test Markdown formatting
    md = format_found_papers_markdown(found, "episodic memory agent")
    assert "REMem" in md
    assert "一键入库指令" in md
    assert "paper-library ingest" in md

    # 3. Direct Ingestion into active library (Obsidian)
    vault_dir = tmp_path / "test_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    store_file = tmp_path / "paper_store.json"

    ingest_cfg = OmegaConf.create({
        "executor": {"source": ["arxiv"], "reranker": "local"},
        "reranker": {"local": {"method": "tfidf"}},
        "paper_store": {"path": str(store_file)},
        "obsidian": {
            "enabled": True,
            "vault_path": str(vault_dir),
            "notes_folder": "Literature",
        },
        "feishu": {"app_id": "", "dry_run": True},
    })

    # Mock full text fetch to return sample markdown
    from paper_daily.pipeline.base import BackendResult
    monkeypatch.setattr(
        "paper_daily.pipeline.backends.fulltext_backends.FallbackChain.execute",
        lambda *args, **kwargs: BackendResult(
            ok=True,
            data="# REMem Full Paper\n\nMethod and architecture description.",
            backend_name="mock",
        ),
    )

    ingest_res = ingest_paper_direct(
        "https://arxiv.org/abs/2602.13530",
        provider="obsidian",
        config=ingest_cfg,
    )

    assert ingest_res["status"] == "success"
    assert "obsidian://" in ingest_res["note_url"]

    # Verify Markdown note exists in Obsidian vault
    note_files = list((vault_dir / "Literature").glob("*.md"))
    assert len(note_files) == 1
    note_content = note_files[0].read_text(encoding="utf-8")
    assert "REMem" in note_content
    assert "一、核心一句话总结" in note_content

    # Verify PaperStore marked paper as ingested
    from paper_daily.core import PaperStore
    store = PaperStore(str(store_file))
    assert store.is_ingested("https://arxiv.org/abs/2602.13530")


def test_feishu_rich_text_formatting_and_user_preference_learning(tmp_path, monkeypatch):
    """Verifies Feishu Docx rich-text formatting (clickable links, colored badges) and explicit user preference learning."""
    from paper_daily.channels.feishu import extract_user_reason
    from paper_daily.core import PaperStore
    from paper_daily.core.digest import format_digest_feishu_elements
    from paper_daily.library.console import parse_console_text, sync_user_preferences_to_console
    from paper_daily.protocol import Paper

    # 1. Test extract_user_reason
    assert extract_user_reason("确认精读入库（可在此输入入库理由/个性偏好，AI 自动记忆学习）") == ""
    assert extract_user_reason("移出待选（可在此输入淘汰理由/排除特征，AI 自动加入负向排除）") == ""
    assert extract_user_reason("移出待选 纯 Prompt 调优水文，没有底层架构创新") == "纯 Prompt 调优水文，没有底层架构创新"
    assert extract_user_reason("确认精读入库：关注这个轻量级路由机制") == "关注这个轻量级路由机制"
    assert extract_user_reason("[x] 移出待选（可在此输入淘汰理由） 缺乏开源代码支撑") == "缺乏开源代码支撑"

    # 2. Test format_digest_feishu_elements rich text styling
    p = Paper(
        source="arxiv",
        title="LOW N: Diffusion VLM Decoding Routing",
        authors=["Author A"],
        abstract="A method for VLM decoding routing.",
        url="https://arxiv.org/abs/2604.12345",
        code_url="https://github.com/test/lown",
        project_url="https://test.github.io/lown/",
        review_badge="[强烈推荐复用] (高置信度)",
        critical_digest={
            "delta": "提出 LOW N 无需训练的扩散 VLM 解码路由",
            "qualitative_grades": {
                "method_reusability": {"grade": "High"},
                "claim_support": {"grade": "High"},
                "baseline_fairness": {"grade": "Unknown"},
            },
            "mechanism": {
                "pipeline": "Masked Tokens -> 一致性认证",
                "core_formula": "N/A (需查正文)",
                "symbol_dict": "N/A (需查正文)",
            },
            "evidence_and_cost": {
                "metrics": "在 10 个基准上保持 99.6% 性能",
                "cost_and_limits": "免训练、免阈值调优",
            },
            "action_or_check": "【启发】轻量草稿+重量验证范式。【需查正文: 1. 具体一致性判定指标；2. 消融实验。】",
        },
    )

    elements = format_digest_feishu_elements(p)
    assert elements

    # Check clickable code & project links
    code_el = next((el for el in elements if el.get("text_run", {}).get("content") == "代码仓库 ↗"), None)
    assert code_el is not None
    assert code_el["text_run"]["text_element_style"]["link"]["url"] == "https://github.com/test/lown"
    assert code_el["text_run"]["text_element_style"]["bold"] is True

    proj_el = next((el for el in elements if el.get("text_run", {}).get("content") == "项目主页 ↗"), None)
    assert proj_el is not None
    assert proj_el["text_run"]["text_element_style"]["link"]["url"] == "https://test.github.io/lown/"

    # Check review badge color (pink/red=1 for 强烈推荐复用)
    badge_el = next((el for el in elements if "[强烈推荐复用]" in el.get("text_run", {}).get("content", "")), None)
    assert badge_el is not None
    assert badge_el["text_run"]["text_element_style"]["text_color"] == 1

    # Check that N/A formula and symbol lines were cleanly omitted
    all_content = "".join(el.get("text_run", {}).get("content", "") for el in elements)
    assert "核心公式" not in all_content
    assert "符号释义" not in all_content
    assert "真实提升：" in all_content
    assert "【启发】" in all_content
    assert "【需查正文】" in all_content

    # 3. Test PaperStore user preference recording and cues
    store_file = tmp_path / "pref_store.json"
    store = PaperStore(str(store_file))

    store.record_user_preference("negative", "纯 Prompt 调优水文，没有底层架构创新", title="Paper 1")
    store.record_user_preference("positive", "轻量级路由机制，与自身项目契合", title="Paper 2")

    prefs = store.get_user_preferences()
    assert len(prefs["negative"]) == 1
    assert prefs["negative"][0]["reason"] == "纯 Prompt 调优水文，没有底层架构创新"
    assert len(prefs["positive"]) == 1
    assert prefs["positive"][0]["reason"] == "轻量级路由机制，与自身项目契合"

    assert "纯 Prompt 调优水文，没有底层架构创新" in store.get_preference_negative_texts()
    assert "轻量级路由机制，与自身项目契合" in store.get_preference_positive_texts()

    # Test discard with reason
    store.mark_discarded("Paper 1", metadata={"title": "Paper 1", "abstract": "abs", "reason": "纯 Prompt 调优水文"})
    discarded_texts = store.recent_discarded_texts()
    assert any("Dislike Reason: 纯 Prompt 调优水文" in t for t in discarded_texts)

    # 4. Test console preference parsing and Obsidian writeback
    console_md = """
# 核心标签
- Agent
- Memory

# 用户偏好记忆库 (AI 学习偏好)
- 👍 偏好特征: 轻量级路由机制 (来源: Paper 2)
- 👎 排除特征: 纯 Prompt 水文 (来源: Paper 1)
"""
    settings = parse_console_text(console_md)
    assert "轻量级路由机制" in settings["required_anchors"]
    assert "纯 Prompt 水文" in settings["excluded_keywords"]

    # Test writeback to Obsidian console note
    vault_dir = tmp_path / "obs_vault"
    vault_dir.mkdir(parents=True, exist_ok=True)
    console_note = vault_dir / "Console.md"
    console_note.write_text("# Console Note\n\n## 核心标签\n- RL\n", encoding="utf-8")

    cfg = OmegaConf.create({
        "console": {"provider": "obsidian"},
        "obsidian": {
            "vault_path": str(vault_dir),
            "console_path": "Console.md",
        },
    })
    res = sync_user_preferences_to_console(cfg, prefs)
    assert res is True
    updated_console = console_note.read_text(encoding="utf-8")
    assert "用户偏好记忆库" in updated_console
    assert "👍 偏好特征: 轻量级路由机制" in updated_console
    assert "👎 排除特征: 纯 Prompt 调优水文" in updated_console


def test_visual_framework_diagram_and_poster_generation(tmp_path, monkeypatch):
    """Verify academic framework diagram generation, caching, and Feishu image block mounting."""
    import base64
    from paper_daily.core.poster import (
        build_framework_prompt,
        generate_diagram_with_gpt_image,
        generate_paper_poster,
    )
    from paper_daily.channels.feishu import FeishuClient
    from paper_daily.library.finder import generate_poster_for_paper_direct
    from paper_daily.protocol import Paper

    p = Paper(
        source="arxiv",
        title="Episodic Memory Routing for Autonomous Agents",
        authors=["Alice", "Bob"],
        abstract="We present an episodic memory routing framework.",
        url="https://arxiv.org/abs/2604.99999",
        arxiv_id="2604.99999",
        critical_digest={
            "delta": "Dynamic certificate-guided memory indexing",
            "mechanism": "Context -> Index -> Verification -> Dispatch",
        },
    )

    # 1. Prompt formulation
    prompt = build_framework_prompt(p)
    assert "Episodic Memory Routing" in prompt
    assert "Context -> Index -> Verification -> Dispatch" in prompt
    assert "clean vector publication figure" in prompt

    # 2. Mock OpenAI-compatible API for gpt-image-2.5
    out_dir = tmp_path / "posters"
    out_dir.mkdir(parents=True, exist_ok=True)
    dummy_png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 6000
    b64_dummy = base64.b64encode(dummy_png_bytes).decode("ascii")

    class MockResp:
        def __init__(self, status_code=200, json_data=None):
            self.status_code = status_code
            self._json = json_data or {"data": [{"b64_json": b64_dummy}]}
            self.text = "ok"

        def json(self):
            return self._json

    def mock_post(url, **kwargs):
        if "images/generations" in url:
            assert kwargs.get("json", {}).get("model") == "gpt-image-2.5-sunburst"
            return MockResp(200)
        if "upload_all" in url:
            return MockResp(200, {"code": 0, "data": {"file_token": "img_token_123"}})
        return MockResp(200)

    monkeypatch.setattr("requests.post", mock_post)

    img_path = generate_diagram_with_gpt_image(
        p,
        api_base="https://sub.umapis.com/v1",
        api_key="sk-test-mock-key",
        output_dir=out_dir,
    )
    assert img_path is not None
    assert img_path.is_file()
    assert img_path.stat().st_size > 5000

    # Test cache reuse
    img_path2 = generate_diagram_with_gpt_image(
        p,
        api_base="https://sub.umapis.com/v1",
        api_key="sk-test-mock-key",
        output_dir=out_dir,
    )
    assert img_path2 == img_path

    # 3. Test FeishuClient image upload and daily report block mounting
    feishu = FeishuClient({
        "app_id": "cli_mock",
        "app_secret": "sec_mock",
        "dry_run": False,
    })
    feishu._has_lark_cli = False
    feishu._tenant_token = "mock_tok"

    uploaded = feishu.upload_image_to_drive("doc_123", str(img_path))
    assert uploaded is not None
    assert uploaded["file_token"] == "img_token_123"

    # Test daily report block creation with visual poster
    p.poster_path = str(img_path)
    p.inline_annotations = [{"quote": "Raw redundant quote", "comment": "Comment"}]

    created_blocks = []
    patched_blocks = []

    def mock_call_api(method, path, params=None, data=None):
        if method == "GET" and path.endswith("/blocks"):
            return [{"block_id": "root_1", "block_type": 1}]
        if method == "POST" and "children" in path:
            children = (data or {}).get("children") or []
            created_blocks.extend(children)
            return {"children": [{"block_id": f"b_{i}", "block_type": c.get("block_type")} for i, c in enumerate(children)]}
        if method == "PATCH" and "replace_image" in (data or {}):
            patched_blocks.append((path, data))
            return {"msg": "success"}
        return {}

    monkeypatch.setattr(feishu, "_call_api", mock_call_api)
    monkeypatch.setattr(feishu, "get_or_create_daily_document", lambda folder: ("doc_123", "https://feishu.cn/docx/123"))

    feishu.create_or_update_daily_report([p])

    # Verify that an image block (block_type: 27) was mounted and patched with token
    img_block = next((b for b in created_blocks if b.get("block_type") == 27), None)
    assert img_block is not None
    assert any("replace_image" in data and data["replace_image"]["token"] == "img_token_123" for _, data in patched_blocks)

    # Verify that redundant inline_annotations and raw quotes were cleanly omitted
    has_inline_quote = any(
        "Raw redundant quote" in "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
        for b in created_blocks if b.get("block_type") == 2
    )
    assert not has_inline_quote

    # 4. Test direct poster generation function for coding agent
    cfg_direct = OmegaConf.create({
        "poster": {
            "enabled": True,
            "api_key": "sk-test-mock-key",
            "api_base": "https://sub.umapis.com/v1",
            "output_dir": str(out_dir),
        }
    })
    res = generate_poster_for_paper_direct("https://arxiv.org/abs/2604.99999", config=cfg_direct)
    assert res["status"] == "success"
    assert res["poster_path"] == str(img_path)
    assert "file://" in res["file_uri"]


def test_academic_web_translator_and_latex_preservation(monkeypatch):
    """Verify free web translation engine with LaTeX formula preservation, concurrency, and error fallback."""
    from paper_daily.core.translator import (
        AcademicTranslator,
        protect_latex_and_tokens,
        restore_latex_and_tokens,
    )

    # 1. Formula & token protection and restoration
    raw_md = (
        "The objective is defined as $\\mathcal{L} = \\alpha \\mathcal{L}_1 + \\beta \\mathcal{L}_2$, "
        "where `alpha = 0.5` is set. Furthermore: $$\\sum_{i=1}^n x_i = 1$$ holds."
    )
    protected, placeholders = protect_latex_and_tokens(raw_md)
    assert "XINLMATH" in protected
    assert "XCODESPAN" in protected
    assert "XDISPMATH" in protected
    restored = restore_latex_and_tokens(protected, placeholders)
    assert restored == raw_md

    # 2. Mock web translation requests (Bing & Google)
    class MockWebResp:
        def __init__(self, status_code, json_data=None, text=""):
            self.status_code = status_code
            self._json = json_data
            self.text = text

        def json(self):
            return self._json

    def mock_get(url, **kwargs):
        if "cn.bing.com/Translator" in url:
            html = 'IG:"TEST_IG_123" data-iid="translator.999" params_AbusePreventionHelper = [1793,"test_token",3600000];'
            return MockWebResp(200, text=html)
        if "translate.google.com" in url:
            params = kwargs.get("params", {})
            q = params.get("q", "")
            return MockWebResp(200, json_data=[[[f"谷歌译文: {q}", q, None, None]]])
        return MockWebResp(404)

    def mock_post(url, **kwargs):
        if "ttranslatev3" in url:
            data = kwargs.get("data", {})
            q = data.get("text", "")
            return MockWebResp(200, json_data=[{"translations": [{"text": f"必应译文: {q}"}]}])
        return MockWebResp(404)

    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: mock_get(url, **kw))
    monkeypatch.setattr("requests.Session.post", lambda self, url, **kw: mock_post(url, **kw))

    translator = AcademicTranslator({"enabled": True, "engine": "web", "concurrency": 3})

    # Test single paragraph translation
    zh = translator.translate_paragraph("Diffusion models achieve strong empirical results under $\\lambda > 0$.")
    assert "必应译文" in zh
    assert "$\\lambda > 0$" in zh

    # Test full text bilingual markdown generation
    doc = (
        "# 1. Introduction\n\n"
        "We propose a novel framework for scalable multimodal generation.\n\n"
        "$$\\min_\\theta \\mathbb{E}[\\|f_\\theta(x) - y\\|^2]$$\n\n"
        "Our method demonstrates superior performance over strong baselines."
    )
    bilingual = translator.make_bilingual_markdown(doc)
    assert "# 1. Introduction" in bilingual
    assert "$$\\min_\\theta" in bilingual
    assert "> 必应译文" in bilingual
    assert "Our method demonstrates" in bilingual

    # 3. Test fallback to Google when Bing fails
    def mock_post_fail(url, **kwargs):
        return MockWebResp(500)

    monkeypatch.setattr("requests.Session.post", lambda self, url, **kw: mock_post_fail(url, **kw))
    zh_google = translator.translate_paragraph("Testing fallback to Google.")
    assert "谷歌译文" in zh_google

    # 4. Test total fallback to original text when all engines fail
    def mock_get_fail(url, **kwargs):
        return MockWebResp(500)

    monkeypatch.setattr("requests.Session.get", lambda self, url, **kw: mock_get_fail(url, **kw))
    zh_orig = translator.translate_paragraph("Completely offline fallback.")
    assert zh_orig == "Completely offline fallback."


def test_markdown_daily_report_template_and_customization(tmp_path):
    """Verify Markdown-first daily report engine, user-customizable template, and fallback."""
    from paper_daily.channels.daily_report import (
        build_daily_report,
        markdown_to_email_html,
        render_report_markdown,
    )
    from paper_daily.protocol import Paper

    p = Paper(
        source="arxiv",
        title="Scalable Attention Routing",
        authors=["Alice", "Bob"],
        abstract="We present scalable attention routing.",
        url="https://arxiv.org/abs/2610.99999",
        arxiv_id="2610.99999",
    )
    p.critical_digest = {
        "delta": "全新稀疏注意力机制",
        "qualitative_grades": {
            "method_reusability": {"grade": "High"},
            "claim_support": {"grade": "High"},
            "baseline_fairness": {"grade": "High"},
        },
        "mechanism": {"pipeline": "Input -> Router -> Attention", "core_formula": "A = softmax(QK^T)"},
        "evidence_and_cost": {"metrics": "Speedup 2.5x"},
        "action_or_check": "建议验证长上下文表现",
    }
    p.review_badge = "[强烈推荐复用]"

    # 1. Test default workspace template (templates/daily_report.md)
    rep_default = build_daily_report([p])
    assert "论文研究日报" in rep_default.title
    assert "Scalable Attention Routing" in rep_default.markdown
    assert "全新稀疏注意力机制" in rep_default.markdown
    assert "强烈推荐复用" in rep_default.markdown
    assert "<h1" in rep_default.html
    assert "style=" in rep_default.html  # Verify premailer inlined CSS

    # 2. Test user-customized template
    custom_tmpl = tmp_path / "my_custom_report.md"
    custom_tmpl.write_text(
        "# [Custom Header] {{ title }}\n\n"
        "Total Papers: {{ papers|length }}\n\n"
        "{% for p in papers %}\n"
        "## {{ loop.index }}. {{ p.title }}\n"
        "- Link: [Read Paper]({{ p.url }})\n"
        "- My Review: {{ p.review_badge }}\n"
        "- Mechanism: {{ p.pipeline }}\n"
        "{% endfor %}\n\n"
        "Footer Note: Custom Signature\n",
        encoding="utf-8",
    )

    rep_custom = build_daily_report([p], template_path=custom_tmpl)
    assert "[Custom Header]" in rep_custom.markdown
    assert "Total Papers: 1" in rep_custom.markdown
    assert "Footer Note: Custom Signature" in rep_custom.markdown
    assert "[Custom Header]" in rep_custom.html
    assert "Custom Signature" in rep_custom.html

    # 3. Test safe fallback when custom template has syntax error
    broken_tmpl = tmp_path / "broken.md"
    broken_tmpl.write_text("{% for p in papers %} Missing endfor tag!", encoding="utf-8")
    rep_broken = build_daily_report([p], template_path=broken_tmpl)
    # Should safely fall back to default template without crashing
    assert "Scalable Attention Routing" in rep_broken.markdown
    assert "论文研究日报" in rep_broken.title
    assert rep_broken.html is not None







