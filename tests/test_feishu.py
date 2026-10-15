from datetime import datetime
from unittest.mock import MagicMock
import pytest
from omegaconf import OmegaConf

from zotero_arxiv_daily.feishu import FeishuClient
from zotero_arxiv_daily.protocol import Paper


@pytest.fixture
def feishu_config():
    return OmegaConf.create({
        "app_id": "test_app_id",
        "app_secret": "test_app_secret",
        "daily_folder_token": "fld_test",
        "dry_run": False,
    })


def test_feishu_dry_run():
    cfg = OmegaConf.create({"dry_run": True})
    client = FeishuClient(cfg)
    url = client.create_or_update_daily_report([])
    assert "dry_run" in url


def test_feishu_create_daily_report(feishu_config, monkeypatch):
    client = FeishuClient(feishu_config)

    def mock_request(method_or_url, url=None, *args, **kwargs):
        target_url = str(url if url else method_or_url)
        resp = MagicMock()
        resp.status_code = 200
        if "tenant_access_token" in target_url:
            val = {"code": 0, "tenant_access_token": "test_token"}
        elif "/docx/v1/documents" in target_url and "children" not in target_url:
            val = {"code": 0, "data": {"document": {"document_id": "doc_123"}}}
        elif "children" in target_url:
            val = {"code": 0, "data": {"children": []}}
        else:
            val = {"code": 0, "data": {}}
        resp.json = lambda: val
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.post", mock_request)
    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Sample Paper Title",
        authors=["Alice"],
        abstract="This is the abstract.",
        url="https://arxiv.org/abs/2401.00001",
        tldr_en="English TLDR",
        tldr_zh="中文摘要",
        sources=["arxiv"],
        published_date=datetime(2026, 10, 15),
    )

    doc_url = client.create_or_update_daily_report([paper])
    assert doc_url == "https://feishu.cn/docx/doc_123"


def test_feishu_fetch_checked_papers(feishu_config, monkeypatch):
    client = FeishuClient(feishu_config)

    blocks_response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "block_type": 4,  # heading2
                    "heading2": {"elements": [{"text_run": {"content": "1. Paper Alpha"}}]},
                },
                {
                    "block_type": 17,  # todo
                    "todo": {"style": {"done": True}},
                },
                {
                    "block_type": 4,  # heading2
                    "heading2": {"elements": [{"text_run": {"content": "2. Paper Beta"}}]},
                },
                {
                    "block_type": 17,  # todo
                    "todo": {"style": {"done": False}},
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = blocks_response
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.request", lambda *a, **kw: mock_resp)
    client._tenant_token = "mock_token"

    checked = client.fetch_checked_papers("doc_123")
    assert checked == ["1. Paper Alpha"]


def test_feishu_wiki_create_daily_report(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test_app_id",
        "app_secret": "test_app_secret",
        "wiki_space_id": "space_123",
        "daily_parent_node_token": "parent_node_123",
        "dry_run": False,
    })
    client = FeishuClient(cfg)

    def mock_request(method_or_url, url=None, *args, **kwargs):
        target_url = str(url if url else method_or_url)
        resp = MagicMock()
        resp.status_code = 200
        if "tenant_access_token" in target_url:
            val = {"code": 0, "tenant_access_token": "test_token"}
        elif "/wiki/v2/spaces/space_123/nodes" in target_url:
            val = {
                "code": 0,
                "data": {
                    "node": {
                        "node_token": "wiki_node_abc",
                        "obj_token": "docx_obj_abc",
                        "url": "https://feishu.cn/wiki/wiki_node_abc",
                    }
                }
            }
        elif "children" in target_url:
            val = {"code": 0, "data": {"children": []}}
        else:
            val = {"code": 0, "data": {}}
        resp.json = lambda: val
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.post", mock_request)
    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Wiki Test Paper",
        authors=["Alice"],
        abstract="Abstract content",
        url="https://arxiv.org/abs/2401.99999",
    )
    url = client.create_or_update_daily_report([paper])
    assert url == "https://feishu.cn/wiki/wiki_node_abc"


def test_feishu_create_reading_note(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test_app_id",
        "app_secret": "test_app_secret",
        "wiki_space_id": "space_123",
        "notes_parent_node_token": "notes_parent_123",
        "dry_run": False,
    })
    client = FeishuClient(cfg)

    def mock_request(method_or_url, url=None, *args, **kwargs):
        target_url = str(url if url else method_or_url)
        resp = MagicMock()
        resp.status_code = 200
        if "tenant_access_token" in target_url:
            val = {"code": 0, "tenant_access_token": "test_token"}
        elif "/wiki/v2/spaces/space_123/nodes" in target_url:
            val = {
                "code": 0,
                "data": {
                    "node": {
                        "node_token": "note_wiki_123",
                        "obj_token": "note_docx_123",
                        "url": "https://feishu.cn/wiki/note_wiki_123",
                    }
                }
            }
        elif "children" in target_url:
            val = {"code": 0, "data": {"children": []}}
        else:
            val = {"code": 0, "data": {}}
        resp.json = lambda: val
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.post", mock_request)
    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Memory-R1",
        authors=["Bob"],
        abstract="Agent memory via RL",
        affiliations=["LMU Munich", "Cambridge"],
        url="https://arxiv.org/abs/2508.19828",
    )
    note_url = client.create_reading_note(paper, {"core_summary": "Core summary test"})
    assert note_url == "https://feishu.cn/wiki/note_wiki_123"


def test_feishu_fetch_checked_paper_details(monkeypatch):
    cfg = OmegaConf.create({"app_id": "test", "app_secret": "test"})
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    blocks_response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "block_id": "b1",
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "1. Memory-R1: RL for Agent Memory"}}]},
                },
                {
                    "block_id": "b2",
                    "block_type": 17,
                    "todo": {"style": {"done": True}},
                },
                {
                    "block_id": "b3",
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": "来源: [arXiv] | 日期: 2026-10-15\n发表单位/实验室: LMU Munich, Cambridge\n原文链接: https://arxiv.org/abs/2508.19828"}}
                        ]
                    },
                },
                {
                    "block_id": "b4",
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": "TL;DR: Reinforcement learning agent memory.\n强化学习驱动记忆管理。"}}
                        ]
                    },
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = blocks_response
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.request", lambda *a, **kw: mock_resp)

    details = client.fetch_checked_paper_details("doc_daily")
    assert len(details) == 1
    assert details[0]["title"] == "Memory-R1: RL for Agent Memory"
    assert details[0]["url"] == "https://arxiv.org/abs/2508.19828"
    assert details[0]["affiliations"] == ["LMU Munich", "Cambridge"]
    assert details[0]["sources"] == ["arXiv"]
    assert "Reinforcement learning" in details[0]["tldr"]
    assert details[0]["action"] == "ingest"


def test_feishu_fetch_checked_paper_details_delete_action(monkeypatch):
    cfg = OmegaConf.create({"app_id": "test", "app_secret": "test"})
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    blocks_response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "block_id": "b1",
                    "block_type": 5,
                    "heading3": {"elements": [{"text_run": {"content": "1. [#Benchmark] Obsolete Dataset"}}]},
                },
                {
                    "block_id": "b2",
                    "block_type": 17,
                    "todo": {
                        "style": {"done": True},
                        "elements": [{"text_run": {"content": "移出待选 (标记删除)"}}],
                    },
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = blocks_response
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.request", lambda *a, **kw: mock_resp)

    details = client.fetch_checked_paper_details("doc_daily")
    assert len(details) == 1
    assert details[0]["action"] == "delete"
    assert "Obsolete Dataset" in details[0]["title"]


def test_feishu_delete_document_blocks(monkeypatch):
    cfg = OmegaConf.create({"app_id": "test", "app_secret": "test"})
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    calls = []

    def mock_call_api(method, path, params=None, data=None):
        calls.append((method, path, data))
        if method == "GET" and "blocks/doc_123" in path:
            return {"block": {"children": ["b1", "b2", "b3", "b4", "b5"]}}
        elif method == "DELETE":
            return {"code": 0}
        return {}

    monkeypatch.setattr(client, "_call_api", mock_call_api)

    success = client.delete_document_blocks("doc_123", ["b2", "b3"])
    assert success is True
    assert any(c[0] == "DELETE" and c[2] == {"start_index": 1, "end_index": 3} for c in calls)


def test_feishu_append_to_tag_graph(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "tag_graph_node_token": "node_tag_graph",
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    calls = []

    def mock_request(method, url, *args, **kwargs):
        calls.append((method, url, kwargs.get("json", {})))
        resp = MagicMock()
        resp.status_code = 200
        if "get_node" in url:
            resp.json.return_value = {"code": 0, "data": {"node": {"obj_token": "doc_tag_graph"}}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Memory-R1: RL for Agent Memory",
        authors=["Alice"],
        abstract="Reinforcement learning for multi-agent memory decision.",
        url="https://arxiv.org/abs/2508.19828",
        venue="ACL 2026",
    )

    client.append_to_tag_graph(paper, note_url="https://feishu.cn/wiki/test_note", tags=["Memory", "RL"])
    assert len(calls) == 2
    # Verify the posted blocks include the matched pillars
    post_call = calls[1]
    assert "POST" == post_call[0]
    assert "doc_tag_graph" in post_call[1]
    children = post_call[2]["children"]
    heading = children[0]["heading3"]["elements"][0]["text_run"]["content"]
    assert "#Memory" in heading
    assert "#RL" in heading
    assert "ACL 2026" in heading


def test_feishu_create_reading_note_academic_workspace(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "notes_folder_token": "fld_notes",
        "dry_run": False,
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    posted_blocks = []

    def mock_request(method, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if method == "POST" and "/docx/v1/documents" in url and "children" not in url:
            resp.json.return_value = {"code": 0, "data": {"document": {"document_id": "doc_note_academic"}}}
        elif "children" in url:
            posted_blocks.extend(kwargs.get("json", {}).get("children", []))
            resp.json.return_value = {"code": 0, "data": {}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Agent Decision Alignment",
        authors=["Alice", "Bob"],
        abstract="Decision policies for autonomous agents.",
        url="https://arxiv.org/abs/2601.12345",
        affiliations=["MIT", "Stanford"],
        venue="ICLR 2026",
    )

    client.create_reading_note(paper, sections={"personal_insights": "Insight text", "personal_critique": "Critique text"})

    # Check top status and metadata
    status_block = posted_blocks[0]
    status_text = "".join(el.get("text_run", {}).get("content", "") for el in status_block["text"]["elements"])
    assert "🏷️ 阅读状态: ⏳ 待精读" in status_text
    assert "来源: [arxiv]" in status_text
    assert "ICLR 2026" in status_text

    # Check annotation workspace heading
    assert any(b.get("heading2", {}).get("elements", [{}])[0].get("text_run", {}).get("content", "") == "✍️ 个人研读批注与思考区 (My Reading Notes & Reflections)" for b in posted_blocks)

    # Check specific workspace headings
    heading3_contents = [
        b.get("heading3", {}).get("elements", [{}])[0].get("text_run", {}).get("content", "")
        for b in posted_blocks if b.get("block_type") == 5
    ]
    assert "💡 核心亮点与认知刷新 (Key Insights & Surprises)" in heading3_contents
    assert "❓ 批判性质疑与硬伤 (Critique, Method Flaws, Limitations)" in heading3_contents
    assert "🎯 与我当前研究的结合点 (Relevance to my Research / Idea / Baseline adoption)" in heading3_contents
    assert "📌 衍生待办 Action Items" in heading3_contents

    # Check action items todos
    todos = [
        "".join(el.get("text_run", {}).get("content", "") for el in b.get("todo", {}).get("elements", []))
        for b in posted_blocks if b.get("block_type") == 17
    ]
    assert any("复现论文核心算法" in t for t in todos)
    assert any("Baseline 评测" in t for t in todos)


def test_feishu_create_reading_note_app_workspace(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "notes_folder_token": "fld_notes",
        "dry_run": False,
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    posted_blocks = []

    def mock_request(method, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if method == "POST" and "/docx/v1/documents" in url and "children" not in url:
            resp.json.return_value = {"code": 0, "data": {"document": {"document_id": "doc_note_app"}}}
        elif "children" in url:
            posted_blocks.extend(kwargs.get("json", {}).get("children", []))
            resp.json.return_value = {"code": 0, "data": {}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="github",
        title="agent-tool-skill",
        authors=[],
        abstract="A tool skill for LLM agents.",
        url="https://github.com/example/agent-tool-skill",
    )

    client.create_reading_note(
        paper,
        sections={
            "scenarios_and_triggers": "When user wants tool execution",
            "quick_start": "git clone https://github.com/example/agent-tool-skill",
        },
        status="📖 精读中"
    )

    # Check top status
    status_block = posted_blocks[0]
    status_text = "".join(el.get("text_run", {}).get("content", "") for el in status_block["text"]["elements"])
    assert "🏷️ 阅读状态: 📖 精读中" in status_text
    assert "项目类型: AI 应用 / 开源项目 / Agent Skill" in status_text

    # Check App todos
    todos = [
        "".join(el.get("text_run", {}).get("content", "") for el in b.get("todo", {}).get("elements", []))
        for b in posted_blocks if b.get("block_type") == 17
    ]
    assert any("克隆代码仓库" in t for t in todos)
    assert any("Tool Wrapper" in t for t in todos)


def test_feishu_append_to_master_index_reading_status(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "master_index_node_token": "node_master",
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    calls = []

    def mock_request(method, url, *args, **kwargs):
        calls.append((method, url, kwargs.get("json", {})))
        resp = MagicMock()
        resp.status_code = 200
        if "get_node" in url:
            resp.json.return_value = {"code": 0, "data": {"node": {"obj_token": "doc_master"}}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Test Paper",
        authors=["Alice"],
        abstract="Test abstract",
        url="https://arxiv.org/abs/2601.00001",
    )

    client.append_to_master_index(paper, note_url="https://feishu.cn/wiki/test_note", status="⏳ 待精读")
    post_calls = [c for c in calls if c[0] == "POST"]
    assert len(post_calls) == 1
    post_call = post_calls[0]
    children = post_call[2]["children"]
    card_text = "".join(el.get("text_run", {}).get("content", "") for el in children[1]["text"]["elements"])
    assert "• 🏷️ 阅读状态: ⏳ 待精读" in card_text
    assert "[ ⏳ 待精读 | 📖 精读中 | ✅ 已精读 | 💡 已转化 ]" in card_text


def test_feishu_reading_status_lifecycle_and_update(monkeypatch):
    cfg = OmegaConf.create({"app_id": "test", "app_secret": "test"})
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    blocks_data = [
        {
            "block_id": "blk_status",
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": "🏷️ 阅读状态: ⏳ 待精读  [ ⏳ 待精读 | 📖 精读中 | ✅ 已精读 | 💡 已转化 ]\n来源: [arXiv]\n"}}
                ]
            }
        }
    ]

    patch_calls = []

    def mock_request(method, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if method == "GET" and "blocks" in url:
            resp.json.return_value = {"code": 0, "data": {"items": blocks_data}}
        elif method == "PATCH" and "blocks" in url:
            patch_calls.append((url, kwargs.get("json", {})))
            resp.json.return_value = {"code": 0, "data": {}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    # 1. Get status
    status = client.get_reading_status("doc_123")
    assert status == "⏳ 待精读"

    # 2. Update status
    updated = client.update_reading_status("doc_123", "✅ 已精读")
    assert updated is True
    assert len(patch_calls) == 1
    new_content = patch_calls[0][1]["update_text_elements"]["elements"][0]["text_run"]["content"]
    assert "🏷️ 阅读状态: ✅ 已精读" in new_content
    assert "[ ⏳ 待精读 | 📖 精读中 | ✅ 已精读 | 💡 已转化 ]" in new_content


def test_feishu_daily_report_reading_plan(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "daily_folder_token": "fld_daily",
        "dry_run": False,
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    posted_blocks = []

    def mock_request(method, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if method == "POST" and "/docx/v1/documents" in url and "children" not in url:
            resp.json.return_value = {"code": 0, "data": {"document": {"document_id": "doc_daily_plan"}}}
        elif "children" in url:
            posted_blocks.extend(kwargs.get("json", {}).get("children", []))
            resp.json.return_value = {"code": 0, "data": {}}
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper1 = Paper(
        source="arxiv",
        title="Top Paper Alpha",
        authors=["Alice"],
        abstract="Alpha abstract",
        url="https://arxiv.org/abs/2601.11111",
        venue="NeurIPS 2026",
    )
    paper2 = Paper(
        source="arxiv",
        title="Second Paper Beta",
        authors=["Bob"],
        abstract="Beta abstract",
        url="https://arxiv.org/abs/2601.22222",
    )

    client.create_or_update_daily_report([paper1, paper2])

    # Verify Reading Plan Heading
    heading2_texts = [
        b.get("heading2", {}).get("elements", [{}])[0].get("text_run", {}).get("content", "")
        for b in posted_blocks if b.get("block_type") == 4
    ]
    assert "🎯 今日精读任务规划 (Today's Reading Plan)" in heading2_texts

    # Verify Todos in Reading Plan
    todos = [
        "".join(el.get("text_run", {}).get("content", "") for el in b.get("todo", {}).get("elements", []))
        for b in posted_blocks if b.get("block_type") == 17
    ]
    assert any("⚡ 今日通读" in t for t in todos)
    assert any("📖 核心精读" in t for t in todos)
    assert any("🎯 落地转化" in t for t in todos)
    assert any("🔥 优先精读: Top Paper Alpha (NeurIPS 2026)" in t for t in todos)
    assert any("🔥 进阶研读: Second Paper Beta" in t for t in todos)


def test_feishu_create_reading_task(monkeypatch):
    cfg = OmegaConf.create({
        "app_id": "test",
        "app_secret": "test",
        "user_id": "ou_test_user",
        "dry_run": False,
    })
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    captured_payload = {}

    def mock_request(method, url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "/task/v2/tasks" in url:
            captured_payload.update(kwargs.get("json", {}))
            resp.json.return_value = {
                "code": 0,
                "data": {
                    "task": {
                        "guid": "task_guid_123",
                        "summary": captured_payload.get("summary"),
                        "url": "https://applink.feishu.cn/client/todo/detail?guid=task_guid_123",
                    }
                }
            }
        else:
            resp.json.return_value = {"code": 0, "data": {}}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("requests.request", mock_request)

    paper = Paper(
        source="arxiv",
        title="Agent Task Planning Paper",
        authors=["Alice"],
        abstract="Autonomous task planning.",
        url="https://arxiv.org/abs/2601.99999",
        venue="ACL 2026",
    )

    task_res = client.create_reading_task(
        paper=paper,
        note_url="https://feishu.cn/wiki/test_note_123",
        due_time="2026-10-20",
        tags=["Agent", "Planning"],
    )

    assert task_res["guid"] == "task_guid_123"
    assert "📖 精读: Agent Task Planning Paper (ACL 2026)" in captured_payload["summary"]
    assert "https://feishu.cn/wiki/test_note_123" in captured_payload["description"]
    assert "https://arxiv.org/abs/2601.99999" in captured_payload["description"]
    assert captured_payload["due"]["is_all_day"] is True
    assert captured_payload["origin"]["href"]["url"] == "https://feishu.cn/wiki/test_note_123"
    assert captured_payload["members"][0]["id"] == "ou_test_user"
    assert captured_payload["members"][0]["role"] == "assignee"


def test_feishu_create_reading_task_dry_run():
    cfg = OmegaConf.create({
        "app_id": "test",
        "dry_run": True,
    })
    client = FeishuClient(cfg)
    paper = Paper(
        source="arxiv",
        title="Dry Run Paper",
        authors=["Alice"],
        abstract="Test abstract",
        url="https://arxiv.org/abs/2601.00000",
    )
    res = client.create_reading_task(paper)
    assert res["guid"] == "dry_run_task_guid"
    assert "Dry Run Paper" in res["summary"]


def test_feishu_fetch_checked_papers_ignores_reading_plan_headers(monkeypatch):
    cfg = OmegaConf.create({"app_id": "test", "app_secret": "test"})
    client = FeishuClient(cfg)
    client._tenant_token = "mock"

    blocks_response = {
        "code": 0,
        "data": {
            "items": [
                {
                    "block_id": "b0",
                    "block_type": 4,  # heading2
                    "heading2": {"elements": [{"text_run": {"content": "🎯 今日精读任务规划 (Today's Reading Plan)"}}]},
                },
                {
                    "block_id": "b0_todo",
                    "block_type": 17,  # todo in reading plan checked!
                    "todo": {"style": {"done": True}, "elements": [{"text_run": {"content": "⚡ 今日通读"}}]},
                },
                {
                    "block_id": "b1",
                    "block_type": 4,  # heading2
                    "heading2": {"elements": [{"text_run": {"content": "1. Real Paper Alpha"}}]},
                },
                {
                    "block_id": "b2",
                    "block_type": 17,  # todo
                    "todo": {"style": {"done": True}, "elements": [{"text_run": {"content": "确认精读入库"}}]},
                },
            ]
        }
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = blocks_response
    mock_resp.raise_for_status = MagicMock()

    monkeypatch.setattr("requests.request", lambda *a, **kw: mock_resp)

    checked = client.fetch_checked_papers("doc_daily")
    # Must ONLY contain the real paper, NOT the reading plan!
    assert checked == ["1. Real Paper Alpha"]


