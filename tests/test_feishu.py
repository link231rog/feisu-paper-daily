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

