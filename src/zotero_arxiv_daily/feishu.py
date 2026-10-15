import json
import re
import shutil
import subprocess
from datetime import datetime
from typing import Any, Optional
import requests
from loguru import logger
from omegaconf import DictConfig

from .protocol import Paper, CorpusPaper, TrendingItem, map_to_core_pillars

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"


class FeishuClient:
    """Feishu API client supporting both direct HTTP (via App ID & Secret) 
    and local lark-cli fallback.
    """
    def __init__(self, config: DictConfig):
        self.config = config
        self.app_id = config.get("app_id")
        self.app_secret = config.get("app_secret")
        self.daily_folder_token = config.get("daily_folder_token")
        self.notes_folder_token = config.get("notes_folder_token")
        self.wiki_space_id = config.get("wiki_space_id")
        self.daily_parent_node_token = config.get("daily_parent_node_token")
        self.notes_parent_node_token = config.get("notes_parent_node_token")
        self.master_index_node_token = config.get("master_index_node_token")
        self.tag_graph_node_token = config.get("tag_graph_node_token")
        dry_run_val = config.get("dry_run", False)
        if isinstance(dry_run_val, str):
            self.dry_run = dry_run_val.strip().lower() in ("true", "1", "yes")
        else:
            self.dry_run = bool(dry_run_val)
        self._tenant_token: Optional[str] = None
        self._has_lark_cli = shutil.which("lark-cli") is not None

    def _get_tenant_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token

        if not self.app_id or not self.app_secret:
            raise ValueError("app_id and app_secret must be set for Feishu direct HTTP access.")

        url = f"{FEISHU_BASE_URL}/auth/v3/tenant_access_token/internal"
        resp = requests.post(url, json={"app_id": str(self.app_id), "app_secret": str(self.app_secret)}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Failed to get Feishu tenant access token: {data}")
        self._tenant_token = data.get("tenant_access_token")
        return self._tenant_token

    def _call_api(self, method: str, path: str, params: Optional[dict] = None, data: Optional[dict] = None) -> dict[str, Any]:
        """Calls Feishu API via HTTP or via local lark-cli."""
        # 1. Try direct HTTP if app_secret is configured
        if self.app_id and self.app_secret:
            token = self._get_tenant_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8",
            }
            url = f"{FEISHU_BASE_URL}{path}"
            resp = requests.request(method, url, headers=headers, params=params, json=data, timeout=30)
            resp.raise_for_status()
            res_json = resp.json()
            if res_json.get("code") != 0 and res_json.get("code") is not None:
                raise RuntimeError(f"Feishu API error ({path}): {res_json}")
            return res_json.get("data", res_json)

        # 2. Fallback to local lark-cli
        if self._has_lark_cli:
            cmd = ["lark-cli", "api", method, f"/open-apis{path}"]
            if params:
                cmd.extend(["--params", json.dumps(params)])
            if data:
                cmd.extend(["--data", json.dumps(data)])
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if result.returncode != 0:
                raise RuntimeError(f"lark-cli error ({result.returncode}): {result.stderr or result.stdout}")
            res_json = json.loads(result.stdout)
            if not res_json.get("ok", True):
                raise RuntimeError(f"Feishu API error via lark-cli: {res_json}")
            return res_json.get("data", res_json)

        raise ValueError("Neither Feishu app credentials (app_id/app_secret) nor lark-cli are available.")

    def _ensure_doc_permissions(self, doc_id: str) -> None:
        """Grants tenant-wide edit rights and adds authorized openids as full_access members."""
        try:
            # 1. Allow everyone in the tenant to edit (so todos can be clicked)
            self._call_api(
                "PATCH",
                f"/drive/v1/permissions/{doc_id}/public",
                params={"type": "docx"},
                data={"link_share_entity": "tenant_editable"}
            )
        except Exception as exc:
            logger.warning(f"Notice setting public link_share_entity on {doc_id}: {exc}")

        # 2. Add specific collaborators if known
        target_openids = []
        if user_id := self.config.get("user_id") or self.config.get("user_openid"):
            target_openids.append(str(user_id))

        # Discover authorized user_ids from contact scopes if available
        try:
            scopes_res = self._call_api("GET", "/contact/v3/scopes")
            scopes_data = scopes_res.get("data", scopes_res)
            for uid in scopes_data.get("user_ids", []):
                if uid not in target_openids:
                    target_openids.append(uid)
        except Exception:
            pass

        for uid in target_openids:
            try:
                self._call_api(
                    "POST",
                    f"/drive/v1/permissions/{doc_id}/members",
                    params={"type": "docx"},
                    data={"member_type": "openid", "member_id": uid, "perm": "full_access"}
                )
                logger.info(f"Added member {uid} with full_access to document {doc_id}")
            except Exception as exc:
                logger.debug(f"Notice adding member {uid} to {doc_id}: {exc}")

    def create_or_update_daily_report(
        self,
        papers: list[Paper],
        trending_items: Optional[list[TrendingItem]] = None,
        folder_token: Optional[str] = None
    ) -> str:
        """Creates or updates a daily paper digest in Feishu Docx."""
        if self.dry_run:
            logger.info("Feishu dry-run enabled. Skipping document creation.")
            return "https://feishu.cn/docx/dry_run"

        today = datetime.now().strftime("%Y-%m-%d")
        title = f"每日论文速递 ({today})"

        doc_id = None
        doc_url = None

        if self.wiki_space_id:
            logger.info(f"Creating Feishu Docx inside Wiki space '{self.wiki_space_id}' under parent '{self.daily_parent_node_token}'...")
            node_payload: dict[str, Any] = {
                "obj_type": "docx",
                "node_type": "origin",
                "parent_node_token": str(self.daily_parent_node_token or ""),
                "title": title,
            }
            node_res = self._call_api(
                "POST",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"space_id": str(self.wiki_space_id)},
                data=node_payload,
            )
            node = node_res.get("node", {})
            doc_id = node.get("obj_token")
            doc_url = node.get("url") or f"https://feishu.cn/wiki/{node.get('node_token')}"
        else:
            target_folder = folder_token or self.daily_folder_token or ""
            create_payload: dict[str, Any] = {"title": title}
            if target_folder:
                create_payload["folder_token"] = target_folder

            logger.info(f"Creating Feishu Docx document: '{title}' in folder '{target_folder}'...")
            doc_res = self._call_api("POST", "/docx/v1/documents", data=create_payload)
            doc = doc_res.get("document", {})
            doc_id = doc.get("document_id")
            doc_url = f"https://feishu.cn/docx/{doc_id}"

        if not doc_id:
            raise RuntimeError(f"Failed to get document_id from Feishu response")

        # Ensure document edit permissions so checkboxes are clickable
        self._ensure_doc_permissions(doc_id)

        # Build clean blocks (no emoji, no match score, bilingual TL;DR, clean todo checkbox)
        children: list[dict[str, Any]] = [
            {
                "block_type": 2,
                "text": {
                    "elements": [
                        {
                            "text_run": {
                                "content": "说明：若需深入精读某篇论文，请勾选对应卡片下方的待办框。下次云端执行时将自动拉取结构化正文沉淀至个人文献库。\n"
                            }
                        }
                    ]
                }
            }
        ]

        # Section 1: Academic Papers
        if papers:
            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {"text_run": {"content": "一、每日精选学术论文"}}
                    ]
                }
            })

        for idx, p in enumerate(papers, 1):
            title_display = p.title_with_venue()
            # Heading 2: 1. Paper Title (Conference)
            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {
                            "text_run": {
                                "content": f"{idx}. {title_display}"
                            }
                        }
                    ]
                }
            })

            # Todo block: [ ] 确认精读入库
            children.append({
                "block_type": 17,
                "todo": {
                    "style": {"done": False},
                    "elements": [
                        {
                            "text_run": {
                                "content": "确认精读入库"
                            }
                        }
                    ]
                }
            })

            # Meta text: 来源: [arXiv] | 日期: ... | 录用会议: ... | 发表单位/实验室: ... | 原文链接: ...
            src_str = ", ".join(p.sources or [p.source])
            date_str = p.published_date.strftime("%Y-%m-%d") if p.published_date else today
            affil_str = ", ".join(p.affiliations) if p.affiliations else "N/A"
            venue_line = f"录用会议: {p.venue}\n" if getattr(p, "venue", None) else ""
            meta_prefix = (
                f"来源: [{src_str}] | 日期: {date_str}\n"
                f"{venue_line}"
                f"发表单位/实验室: {affil_str}\n"
                f"原文链接: "
            )
            children.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": meta_prefix}},
                        {"text_run": {"content": p.url or "N/A"}},
                    ]
                }
            })

            # TL;DR (English as primary, Chinese directly below)
            en_summary = p.tldr_en or (p.abstract[:200] + "..." if p.abstract else "N/A")
            zh_summary = p.tldr_zh or p.tldr or ""
            tldr_text = f"TL;DR: {en_summary}"
            if zh_summary and zh_summary != en_summary:
                tldr_text += f"\n{zh_summary}"

            children.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"{tldr_text}\n"}}
                    ]
                }
            })

        # Section 2: AI Dynamics & GitHub Trending
        if trending_items:
            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {"text_run": {"content": "二、AI 动态与 GitHub 热点"}}
                    ]
                }
            })

            for idx, item in enumerate(trending_items, 1):
                tags_str = " ".join(f"[#{t}]" for t in (item.tags or ["Hot"]))
                stars_str = f" (⭐ {item.stars:,})" if item.stars else ""

                # Heading 3: 1. [#Agent] vllm-project/vllm (⭐ 28,400)
                children.append({
                    "block_type": 5,
                    "heading3": {
                        "elements": [
                            {"text_run": {"content": f"{idx}. {tags_str} {item.title}{stars_str}"}}
                        ]
                    }
                })

                # Meta: 来源: ... | 原文链接: ...
                children.append({
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": f"来源: {item.source} | 原文链接: "}},
                            {"text_run": {"content": item.url}},
                        ]
                    }
                })

                # TL;DR (EN + ZH)
                summary_en = item.summary_en or item.description or item.title
                summary_zh = item.summary_zh or ""
                tldr_text = f"TL;DR: {summary_en}"
                if summary_zh and summary_zh != summary_en:
                    tldr_text += f"\n{summary_zh}"

                children.append({
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": f"{tldr_text}\n"}}
                        ]
                    }
                })

        # Append blocks to the document
        logger.info(f"Writing {len(children)} blocks to document {doc_id}...")
        self._call_api(
            "POST",
            f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            data={"children": children, "index": 0}
        )

        doc_url = doc_url or f"https://feishu.cn/docx/{doc_id}"
        logger.info(f"Feishu daily report published successfully: {doc_url}")
        return doc_url

    def fetch_reading_notes(self) -> list[CorpusPaper]:
        """Fetches reading notes from Wiki space or Drive folder to use as interest corpus."""
        if self.dry_run:
            return []

        corpus: list[CorpusPaper] = []
        if self.wiki_space_id and self.notes_parent_node_token:
            try:
                res = self._call_api(
                    "GET",
                    f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                    params={"parent_node_token": str(self.notes_parent_node_token)}
                )
                items = res.get("items", [])
                for item in items:
                    title = item.get("title", "")
                    clean_title = re.sub(r"^📄\s*\[精读\]\s*", "", title).strip()
                    corpus.append(
                        CorpusPaper(
                            title=clean_title,
                            abstract=f"User curated deep reading note: {clean_title}",
                            added_date=datetime.now(),
                            paths=[f"wiki/notes/{clean_title}"],
                        )
                    )
                logger.info(f"Loaded {len(corpus)} reading notes from Feishu Wiki space")
                return corpus
            except Exception as exc:
                logger.warning(f"Failed to fetch reading notes from Wiki: {exc}")

        if self.notes_folder_token:
            try:
                res = self._call_api("GET", "/drive/v1/files", params={"folder_token": str(self.notes_folder_token)})
                items = res.get("files", [])
                for f in items:
                    name = f.get("name", "")
                    corpus.append(
                        CorpusPaper(
                            title=name,
                            abstract=f"User curated reading note: {name}",
                            added_date=datetime.now(),
                            paths=[f"drive/notes/{name}"],
                        )
                    )
                logger.info(f"Loaded {len(corpus)} reading notes from Drive folder")
            except Exception as exc:
                logger.warning(f"Failed to fetch reading notes from Drive: {exc}")

        return corpus

    def delete_document_blocks(self, document_id: str, block_ids: list[str]) -> bool:
        """Deletes specified top-level block IDs from a Feishu document."""
        if not block_ids or self.dry_run:
            return True
        try:
            root_res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks/{document_id}")
            root_children = root_res.get("block", {}).get("children", [])

            target_set = set(block_ids)
            indices = [idx for idx, cid in enumerate(root_children) if cid in target_set]
            if not indices:
                return False

            # Group contiguous indices
            chunks = []
            for idx in sorted(indices):
                if chunks and idx == chunks[-1][-1] + 1:
                    chunks[-1].append(idx)
                else:
                    chunks.append([idx])

            for chunk in reversed(chunks):
                start_idx = chunk[0]
                end_idx = chunk[-1] + 1
                self._call_api(
                    "DELETE",
                    f"/docx/v1/documents/{document_id}/blocks/{document_id}/children/batch_delete",
                    data={"start_index": start_idx, "end_index": end_idx}
                )
            return True
        except Exception as exc:
            logger.error(f"Failed to delete blocks from document {document_id}: {exc}")
            return False

    def fetch_checked_paper_details(self, document_id: str) -> list[dict[str, Any]]:
        """Scans document blocks for todo items marked as done and extracts rich paper metadata."""
        res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks")
        items = res.get("items", [])
        checked_papers: list[dict[str, Any]] = []

        last_heading = ""
        last_heading_id = ""

        for i, item in enumerate(items):
            b_type = item.get("block_type")
            b_id = item.get("block_id", "")
            if b_type in (4, 5):  # heading2 or heading3
                h_key = "heading2" if b_type == 4 else "heading3"
                elements = item.get(h_key, {}).get("elements", [])
                raw_heading = "".join(el.get("text_run", {}).get("content", "") for el in elements).strip()
                if not re.match(r"^[一二三四五六七八九十]+、", raw_heading):
                    last_heading = raw_heading
                    last_heading_id = b_id
            elif b_type == 17 and last_heading:  # todo
                todo = item.get("todo", {})
                elements = todo.get("elements", [])
                todo_text = "".join(el.get("text_run", {}).get("content", "") for el in elements).strip()
                if todo.get("style", {}).get("done", False):
                    cleaned_title = re.sub(r"^\d+\.\s*", "", last_heading).strip()
                    url = ""
                    affiliations = []
                    sources = []
                    tldr_text = ""

                    is_delete = any(k in todo_text.lower() for k in ["删除", "移出", "淘汰", "discard", "delete"])
                    action = "delete" if is_delete else "ingest"

                    # Collect card block IDs from last_heading_id up to next heading
                    card_block_ids = [last_heading_id] if last_heading_id else []
                    for j in range(items.index(item) - 1, -1, -1):
                        prev = items[j]
                        if prev.get("block_id") == last_heading_id:
                            break
                        if prev.get("block_id") not in card_block_ids:
                            card_block_ids.insert(1, prev.get("block_id"))
                    for j in range(i, len(items)):
                        curr = items[j]
                        if curr.get("block_type") in (4, 5) and curr.get("block_id") != last_heading_id:
                            break
                        if curr.get("block_id") not in card_block_ids:
                            card_block_ids.append(curr.get("block_id"))

                    # Inspect succeeding blocks for metadata and TL;DR
                    for j in range(i + 1, min(i + 5, len(items))):
                        next_item = items[j]
                        if next_item.get("block_type") in (4, 5):
                            break
                        if next_item.get("block_type") == 2:  # text block
                            full_block_text = "".join(
                                el.get("text_run", {}).get("content", "")
                                for el in next_item.get("text", {}).get("elements", [])
                            )
                            if "原文链接:" in full_block_text or "原文/开源主页:" in full_block_text or "官方/开源主页:" in full_block_text:
                                url_match = re.search(r"https?://\S+", full_block_text)
                                if url_match:
                                    url = url_match.group(0).rstrip(" \n\r")
                            if "发表单位/实验室:" in full_block_text or "研发团队:" in full_block_text:
                                affil_match = re.search(r"(?:发表单位/实验室|研发团队):\s*([^\n]+)", full_block_text)
                                if affil_match:
                                    raw_affil = affil_match.group(1).strip()
                                    if raw_affil != "N/A":
                                        affiliations = [a.strip() for a in raw_affil.split(",") if a.strip()]
                            if "来源:" in full_block_text:
                                src_match = re.search(r"来源:\s*\[([^\]]+)\]", full_block_text)
                                if src_match:
                                    sources = [s.strip() for s in src_match.group(1).split(",") if s.strip()]
                            if "TL;DR:" in full_block_text:
                                tldr_text = full_block_text.replace("TL;DR:", "").strip()

                    checked_papers.append({
                        "raw_heading": last_heading,
                        "title": cleaned_title or last_heading,
                        "url": url,
                        "affiliations": affiliations,
                        "sources": sources,
                        "tldr": tldr_text,
                        "document_id": document_id,
                        "todo_block_id": item.get("block_id", ""),
                        "action": action,
                        "todo_text": todo_text,
                        "card_block_ids": card_block_ids,
                    })
        return checked_papers

    def fetch_checked_papers(self, document_id: str) -> list[str]:
        """Scans document blocks for todo items marked as done (backwards-compatible heading list)."""
        details = self.fetch_checked_paper_details(document_id)
        return [d["raw_heading"] for d in details]

    def fetch_checked_papers_from_wiki(self) -> list[dict[str, Any]]:
        """Discovers checked papers across all daily reports in the Wiki space."""
        if not self.wiki_space_id or not self.daily_parent_node_token or self.dry_run:
            return []

        all_checked: list[dict[str, Any]] = []
        try:
            res = self._call_api(
                "GET",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"parent_node_token": str(self.daily_parent_node_token)}
            )
            reports = res.get("items", [])
            for r in reports:
                doc_id = r.get("obj_token")
                if doc_id:
                    checked = self.fetch_checked_paper_details(doc_id)
                    all_checked.extend(checked)
        except Exception as exc:
            logger.warning(f"Failed to scan daily reports in Wiki: {exc}")
        return all_checked

    def create_reading_note(self, paper: Paper, sections: Optional[dict[str, str]] = None) -> str:
        """Creates a structured deep reading note under the Wiki notes parent node."""
        if self.dry_run:
            return "https://feishu.cn/docx/dry_run_note"

        sections = sections or {}
        today = datetime.now().strftime("%Y-%m-%d")
        title = paper.title_with_venue()

        doc_id = None
        note_url = None

        if self.wiki_space_id:
            parent_token = self.notes_parent_node_token or ""
            node_payload = {
                "obj_type": "docx",
                "node_type": "origin",
                "parent_node_token": str(parent_token),
                "title": title,
            }
            node_res = self._call_api(
                "POST",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"space_id": str(self.wiki_space_id)},
                data=node_payload,
            )
            node = node_res.get("node", {})
            doc_id = node.get("obj_token")
            note_url = node.get("url") or f"https://feishu.cn/wiki/{node.get('node_token')}"
        else:
            folder = self.notes_folder_token or ""
            create_payload = {"title": title}
            if folder:
                create_payload["folder_token"] = folder
            doc_res = self._call_api("POST", "/docx/v1/documents", data=create_payload)
            doc_id = doc_res.get("document", {}).get("document_id")
            note_url = f"https://feishu.cn/docx/{doc_id}"

        if not doc_id:
            raise RuntimeError(f"Failed to create reading note document for '{paper.title}'")

        self._ensure_doc_permissions(doc_id)

        # Build reading note blocks
        src_str = ", ".join(paper.sources or [paper.source])
        affil_str = ", ".join(paper.affiliations) if paper.affiliations else "N/A"
        date_str = paper.published_date.strftime("%Y-%m-%d") if paper.published_date else today
        venue_str = getattr(paper, "venue", None) or "Preprint"

        core_summary = sections.get("core_summary") or paper.tldr_zh or paper.tldr or paper.abstract[:200]
        motivation = sections.get("motivation") or (
            "针对大模型智能体在复杂环境中推理与记忆管理效率低下的痛点，探索自适应机制。"
        )
        method = sections.get("method") or (
            "提出强化学习驱动的动态策略，在极低监督样本下通过奖励机制探索最优状态转移与决策流转。"
        )
        experiments = sections.get("experiments") or (
            "在标准基准评测上展现了显著优于静态基准的准确度与更优的推理资源利用率。"
        )
        takeaways = sections.get("takeaways") or (
            "1. 适用于自主智能体工作流与长程记忆持久化。\n2. 机制具备跨领域泛化潜力。"
        )

        blocks: list[dict[str, Any]] = [
            {
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"来源: [{src_str}] | 日期: {date_str} | 录用会议/期刊: {venue_str}\n"}},
                        {"text_run": {"content": f"发表单位/实验室: {affil_str}\n"}},
                        {"text_run": {"content": f"原文直达: {paper.url or 'N/A'}\n"}},
                    ]
                }
            },
            {
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": "一、核心一句话总结"}}]}
            },
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"{core_summary}\n"}}]}
            },
            {
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": "二、研究动机与问题背景"}}]}
            },
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"{motivation}\n"}}]}
            },
            {
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": "三、核心架构与机制设计"}}]}
            },
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"{method}\n"}}]}
            },
            {
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": "四、关键实验与结论"}}]}
            },
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"{experiments}\n"}}]}
            },
            {
                "block_type": 4,
                "heading2": {"elements": [{"text_run": {"content": "五、落地启示与思考"}}]}
            },
            {
                "block_type": 2,
                "text": {"elements": [{"text_run": {"content": f"{takeaways}\n"}}]}
            },
        ]

        self._call_api(
            "POST",
            f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
            data={"children": blocks, "index": 0}
        )
        logger.info(f"Published reading note successfully: {note_url}")
        return note_url

    def append_to_master_index(
        self,
        paper: Paper,
        note_url: str,
        tags: Optional[list[str]] = None,
        core_summary: str = ""
    ) -> None:
        """Appends a new paper card entry to the Feishu Wiki master index document."""
        if not self.master_index_node_token or self.dry_run:
            return

        # 1. Resolve master index obj_token (document_id)
        master_doc_id = None
        try:
            node_info = self._call_api("GET", f"/wiki/v2/spaces/get_node", params={"token": str(self.master_index_node_token)})
            node = node_info.get("node", {})
            master_doc_id = node.get("obj_token")
        except Exception:
            master_doc_id = str(self.master_index_node_token)

        if not master_doc_id:
            logger.warning(f"Could not resolve document ID for master index node {self.master_index_node_token}")
            return

        # 2. Count existing entries to assign next sequential index
        try:
            blocks_res = self._call_api("GET", f"/docx/v1/documents/{master_doc_id}/blocks")
            blocks = blocks_res.get("items", [])
            heading3_count = sum(1 for b in blocks if b.get("block_type") == 5)
            next_idx = heading3_count + 1
        except Exception:
            next_idx = 1

        core_pillars = map_to_core_pillars(tags, title=paper.title, text=paper.abstract or "")
        tags_str = " ".join(f"[#{p}]" for p in core_pillars)
        affil_str = ", ".join(paper.affiliations) if paper.affiliations else "N/A"
        summary = core_summary or paper.tldr_zh or paper.tldr or (paper.abstract[:150] + "...")

        full_title = paper.title_with_venue()
        venue_str = getattr(paper, "venue", None) or "Preprint"

        index_blocks: list[dict[str, Any]] = [
            {
                "block_type": 5,
                "heading3": {
                    "elements": [
                        {"text_run": {"content": f"{next_idx}. {tags_str} {full_title}"}}
                    ]
                }
            },
            {
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"• 全称: {full_title}\n"}},
                        {"text_run": {"content": f"• 录用会议/期刊: {venue_str}\n"}},
                        {"text_run": {"content": f"• 发表单位: {affil_str}\n"}},
                        {"text_run": {"content": f"• 📘 精读笔记直达: {note_url}\n"}},
                        {"text_run": {"content": f"• 原文: {paper.url or 'N/A'}\n"}},
                        {"text_run": {"content": f"• 核心一句话: {summary}\n"}},
                    ]
                }
            }
        ]

        try:
            self._call_api(
                "POST",
                f"/docx/v1/documents/{master_doc_id}/blocks/{master_doc_id}/children",
                data={"children": index_blocks, "index": -1}
            )
            logger.info(f"Appended paper '{paper.title}' to Feishu Wiki master index document")
        except Exception as exc:
            logger.error(f"Failed to append to master index: {exc}")

    def append_to_tag_graph(
        self,
        paper: Paper,
        note_url: str,
        tags: Optional[list[str]] = None,
        core_summary: str = ""
    ) -> None:
        """Appends a new deep-read paper card entry to the Feishu Wiki Tag Knowledge Graph document."""
        if not self.tag_graph_node_token or self.dry_run:
            return

        # 1. Resolve tag graph doc_id
        tag_doc_id = None
        try:
            node_info = self._call_api("GET", f"/wiki/v2/spaces/get_node", params={"token": str(self.tag_graph_node_token)})
            node = node_info.get("node", {})
            tag_doc_id = node.get("obj_token")
        except Exception:
            tag_doc_id = str(self.tag_graph_node_token)

        if not tag_doc_id:
            logger.warning(f"Could not resolve document ID for tag graph node {self.tag_graph_node_token}")
            return

        # 2. Determine matching pillars among the 4 core research directions
        core_pillars = map_to_core_pillars(tags, title=paper.title, text=paper.abstract or "")
        tags_str = " ".join(f"[#{p}]" for p in core_pillars)
        affil_str = ", ".join(paper.affiliations) if paper.affiliations else "N/A"
        summary = core_summary or paper.tldr_zh or paper.tldr or (paper.abstract[:150] + "...")
        full_title = paper.title_with_venue()
        venue_str = getattr(paper, "venue", None) or "Preprint"

        blocks: list[dict[str, Any]] = [
            {
                "block_type": 5,
                "heading3": {
                    "elements": [
                        {"text_run": {"content": f"• {tags_str} {full_title}"}}
                    ]
                }
            },
            {
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"  - 录用会议/期刊: {venue_str}\n"}},
                        {"text_run": {"content": f"  - 发表单位: {affil_str}\n"}},
                        {"text_run": {"content": f"  - 📘 精读笔记直达: {note_url}\n"}},
                        {"text_run": {"content": f"  - 原文来源: {paper.url or 'N/A'}\n"}},
                        {"text_run": {"content": f"  - 核心突破: {summary}\n"}},
                    ]
                }
            }
        ]

        try:
            self._call_api(
                "POST",
                f"/docx/v1/documents/{tag_doc_id}/blocks/{tag_doc_id}/children",
                data={"children": blocks, "index": -1}
            )
            logger.info(f"Appended paper '{paper.title}' to Tag Knowledge Graph document")
        except Exception as exc:
            logger.error(f"Failed to append to tag graph document: {exc}")
