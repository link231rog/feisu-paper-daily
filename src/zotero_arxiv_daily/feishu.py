import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from typing import Any, Optional, Union
import requests
from loguru import logger
from omegaconf import DictConfig

from .protocol import Paper, CorpusPaper, TrendingItem, map_to_core_pillars

FEISHU_BASE_URL = "https://open.feishu.cn/open-apis"

READING_STATUS_TODO = "⏳ 待精读"
READING_STATUS_READING = "📖 精读中"
READING_STATUS_DONE = "✅ 已精读"
READING_STATUS_TRANSFORMED = "💡 已转化"

READING_STATUSES = [
    READING_STATUS_TODO,
    READING_STATUS_READING,
    READING_STATUS_DONE,
    READING_STATUS_TRANSFORMED,
]

READING_STATUS_BAR = "[ ⏳ 待精读 | 📖 精读中 | ✅ 已精读 | 💡 已转化 ]"


def normalize_reading_status(status_str: Optional[str]) -> str:
    """Normalizes various status aliases to the standard 4 reading lifecycle states."""
    if not status_str:
        return READING_STATUS_TODO
    s = str(status_str).strip()
    if s in READING_STATUSES:
        return s
    s_lower = s.lower()
    if any(k in s_lower for k in ["待", "todo", "wait", "pending"]):
        return READING_STATUS_TODO
    if any(k in s_lower for k in ["中", "reading", "in_progress", "doing"]):
        return READING_STATUS_READING
    if any(k in s_lower for k in ["已精读", "done", "finished", "completed", "read"]):
        return READING_STATUS_DONE
    if any(k in s_lower for k in ["转化", "transformed", "actioned", "applied"]):
        return READING_STATUS_TRANSFORMED
    return s


def _build_annotation_workspace_blocks(
    sections: dict[str, Any],
    is_app_note: bool = False
) -> list[dict[str, Any]]:
    """Builds top-level blocks for the Personal Reading Annotation & Reflection Workspace.

    Includes:
    - 💡 核心亮点与认知刷新 (Key Insights & Surprises)
    - ❓ 批判性质疑与硬伤 (Critique, Method Flaws, Limitations)
    - 🎯 与我当前研究的结合点 (Relevance to my Research / Idea / Baseline adoption)
    - 📌 衍生待办 Action Items (Todo checkboxes for experiments, paper tracking, code reproduction)
    """
    insights_content = (
        sections.get("personal_insights")
        or sections.get("insights")
        or "• [请在此记录触动最大的一两个核心机制、新范式或反直觉结论...]\n"
    )
    critique_content = (
        sections.get("personal_critique")
        or sections.get("critique")
        or "• [请在此记录假设是否过强、基线是否不公平、评测泄漏或算力开销过大等局限...]\n"
    )
    relevance_content = (
        sections.get("personal_relevance")
        or sections.get("relevance")
        or "• [请在此记录与当前选题的契合度，可否作为Baseline、借鉴其架构/Prompt或消融方案...]\n"
    )

    action_items = sections.get("action_items")
    if not action_items:
        if is_app_note:
            action_items = [
                "克隆代码仓库并在本地环境完成依赖配置与试运行",
                "编写/适配当前智能体工作流的 Tool Wrapper 或 Prompt 模板",
                "实测边界情况与错误恢复机制，沉淀最佳实践",
            ]
        else:
            action_items = [
                "复现论文核心算法 / 部署运行 Demo",
                "引入当前对比实验作为 Baseline 评测",
                "追踪跟踪作者后续工作、引用开源进展与评测更新",
            ]

    blocks: list[dict[str, Any]] = [
        {
            "block_type": 4,
            "heading2": {
                "elements": [
                    {"text_run": {"content": "✍️ 个人研读批注与思考区 (My Reading Notes & Reflections)"}}
                ]
            }
        },
        {
            "block_type": 5,
            "heading3": {
                "elements": [
                    {"text_run": {"content": "💡 核心亮点与认知刷新 (Key Insights & Surprises)"}}
                ]
            }
        },
        {
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": insights_content}}
                ]
            }
        },
        {
            "block_type": 5,
            "heading3": {
                "elements": [
                    {"text_run": {"content": "❓ 批判性质疑与硬伤 (Critique, Method Flaws, Limitations)"}}
                ]
            }
        },
        {
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": critique_content}}
                ]
            }
        },
        {
            "block_type": 5,
            "heading3": {
                "elements": [
                    {"text_run": {"content": "🎯 与我当前研究的结合点 (Relevance to my Research / Idea / Baseline adoption)"}}
                ]
            }
        },
        {
            "block_type": 2,
            "text": {
                "elements": [
                    {"text_run": {"content": relevance_content}}
                ]
            }
        },
        {
            "block_type": 5,
            "heading3": {
                "elements": [
                    {"text_run": {"content": "📌 衍生待办 Action Items"}}
                ]
            }
        },
    ]

    for item in action_items:
        blocks.append({
            "block_type": 17,
            "todo": {
                "style": {"done": False},
                "elements": [{"text_run": {"content": str(item)}}]
            }
        })

    return blocks


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
        self.candidate_node_token = config.get("candidate_node_token")
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

    def get_document_blocks(self, document_id: str) -> list[dict[str, Any]]:
        """Fetches all blocks for a given document."""
        try:
            res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks", params={"page_size": 500})
            return res.get("items", [])
        except Exception as exc:
            logger.warning(f"Failed to fetch blocks for document {document_id}: {exc}")
            return []

    def get_obj_token_from_node_token(self, node_token: str) -> tuple[Optional[str], Optional[str]]:
        """Gets (obj_token, url) for a given Wiki node token."""
        try:
            res = self._call_api("GET", "/wiki/v2/spaces/get_node", params={"token": node_token})
            node = res.get("node", {})
            obj_token = node.get("obj_token")
            url = node.get("url") or f"https://feishu.cn/wiki/{node_token}"
            return obj_token, url
        except Exception as exc:
            logger.warning(f"Failed to get node for token {node_token}: {exc}")
            return None, None

    def get_or_create_candidate_document(self, folder_token: Optional[str] = None) -> tuple[str, str]:
        """Gets or creates the persistent candidate document ('文献候选库')."""
        title = "文献候选库"

        # 1. If explicit candidate_node_token is configured
        if self.candidate_node_token:
            obj_token, url = self.get_obj_token_from_node_token(str(self.candidate_node_token))
            if obj_token:
                return obj_token, url

        # 2. If inside Wiki space, check if '文献候选库' or '候选文档' already exists under daily_parent_node_token
        if self.wiki_space_id and self.daily_parent_node_token:
            try:
                res = self._call_api(
                    "GET",
                    f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                    params={"parent_node_token": str(self.daily_parent_node_token), "page_size": 50}
                )
                items = res.get("items", [])
                for item in items:
                    if item.get("title") in (title, "候选文档"):
                        node_token = item.get("node_token")
                        obj_token = item.get("obj_token")
                        url = item.get("url") or f"https://feishu.cn/wiki/{node_token}"
                        return obj_token, url
            except Exception as exc:
                logger.warning(f"Error checking candidate document in Wiki: {exc}")

            # Not found -> create persistent origin node
            logger.info(f"Creating persistent candidate document '{title}' in Wiki space '{self.wiki_space_id}' under parent '{self.daily_parent_node_token}'...")
            node_payload: dict[str, Any] = {
                "obj_type": "docx",
                "node_type": "origin",
                "parent_node_token": str(self.daily_parent_node_token),
                "title": title,
            }
            node_res = self._call_api(
                "POST",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"space_id": str(self.wiki_space_id)},
                data=node_payload,
            )
            node = node_res.get("node", {})
            obj_token = node.get("obj_token")
            url = node.get("url") or f"https://feishu.cn/wiki/{node.get('node_token')}"
            return obj_token, url

        # 3. Fallback to Drive folder
        target_folder = folder_token or self.daily_folder_token or ""
        create_payload: dict[str, Any] = {"title": title}
        if target_folder:
            create_payload["folder_token"] = target_folder
        doc_res = self._call_api("POST", "/docx/v1/documents", data=create_payload)
        doc = doc_res.get("document", {})
        doc_id = doc.get("document_id")
        doc_url = f"https://feishu.cn/docx/{doc_id}"
        return doc_id, doc_url

    def create_or_update_daily_report(
        self,
        papers: list[Paper],
        trending_items: Optional[list[TrendingItem]] = None,
        folder_token: Optional[str] = None,
        reading_plan: Optional[list[Any]] = None,
    ) -> str:
        """Publishes candidate papers and trending items into the persistent '候选文档' in Feishu Docx."""
        if self.dry_run:
            logger.info("Feishu dry-run enabled. Skipping document creation.")
            return "https://feishu.cn/docx/dry_run"

        # 1. Target persistent candidate document
        doc_id, doc_url = self.get_or_create_candidate_document(folder_token)
        if not doc_id:
            raise RuntimeError("Failed to resolve candidate document_id in Feishu")

        # Ensure document edit permissions so checkboxes are clickable
        self._ensure_doc_permissions(doc_id)

        # 2. Inspect existing blocks in the document to prevent duplicates and determine next sequential index
        existing_blocks = self.get_document_blocks(doc_id)
        existing_urls: set[str] = set()
        existing_titles: set[str] = set()
        existing_card_count = 0

        for b in existing_blocks:
            b_type = b.get("block_type")
            if b_type in (4, 5):  # heading2 or heading3
                h_key = "heading2" if b_type == 4 else "heading3"
                txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get(h_key, {}).get("elements", [])).strip()
                if re.match(r"^\d+\.", txt):
                    existing_card_count += 1
                    clean = re.sub(r"^\d+\.\s*", "", txt).strip().lower()
                    existing_titles.add(clean)
            elif b_type == 2:  # text
                txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
                for u in re.findall(r"https?://\S+", txt):
                    existing_urls.add(u.rstrip(" \n\r"))

        children: list[dict[str, Any]] = []

        # 3. If document is fresh (only page root block), initialize header and reading plan (no timestamps)
        if len(existing_blocks) <= 1:
            children.extend([
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": "说明：若需深入精读某篇论文或收录项目，请勾选对应卡片下方的待办框。下次云端执行时将自动拉取结构化正文沉淀至个人文献库并同步创建飞书多端待办。\n"
                                }
                            }
                        ]
                    }
                },
                {
                    "block_type": 4,
                    "heading2": {
                        "elements": [
                            {"text_run": {"content": "🎯 精读任务规划 (Reading Plan)"}}
                        ]
                    }
                },
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {
                                "text_run": {
                                    "content": (
                                        "建议精读节奏: 1~2篇核心前沿 / 1个工程实践工具\n"
                                        "💡 规划说明: 勾选下方目标制定精读安排；勾选卡片下方的【确认精读入库】将同步创建深度研读工作区与飞书多端待办。\n"
                                    )
                                }
                            }
                        ]
                    }
                },
                {
                    "block_type": 17,
                    "todo": {
                        "style": {"done": False},
                        "elements": [{"text_run": {"content": "⚡ 通读浏览: 快速扫读候选列表所有 TL;DR 与热点趋势，筛选重点候选"}}]
                    }
                },
                {
                    "block_type": 17,
                    "todo": {
                        "style": {"done": False},
                        "elements": [{"text_run": {"content": "📖 核心精读: 锁定 1-2 篇高匹配度论文，完成【个人研读批注与思考区】填写"}}]
                    }
                },
                {
                    "block_type": 17,
                    "todo": {
                        "style": {"done": False},
                        "elements": [{"text_run": {"content": "🎯 落地转化: 提炼可复用的实验 Baseline、算法机制或工程 Action Item"}}]
                    }
                },
            ])

            if reading_plan:
                for p_item in reading_plan:
                    p_text = p_item if isinstance(p_item, str) else p_item.get("text", "")
                    p_done = False if isinstance(p_item, str) else p_item.get("done", False)
                    if p_text:
                        children.append({
                            "block_type": 17,
                            "todo": {
                                "style": {"done": p_done},
                                "elements": [{"text_run": {"content": f"📌 精读目标: {p_text}"}}]
                            }
                        })
            elif papers:
                top_count = min(2, len(papers))
                for p_idx in range(top_count):
                    p = papers[p_idx]
                    label = "🔥 优先精读" if p_idx == 0 else "🔥 进阶研读"
                    children.append({
                        "block_type": 17,
                        "todo": {
                            "style": {"done": False},
                            "elements": [{"text_run": {"content": f"{label}: {p.title_with_venue()} (~30min 研读批注)"}}]
                        }
                    })

            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {"text_run": {"content": "一、候选学术论文与研究工作"}}
                    ]
                }
            })

        # 4. Filter and sequentially append academic papers
        papers_to_add: list[Paper] = []
        for p in papers:
            p_clean = p.clean_title.lower() if hasattr(p, "clean_title") else p.title.strip().lower()
            if p.url and p.url in existing_urls:
                continue
            if p_clean in existing_titles or p.title.strip().lower() in existing_titles:
                continue
            papers_to_add.append(p)

        for p in papers_to_add:
            existing_card_count += 1
            idx = existing_card_count
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

            # Todo block 1: [ ] 确认精读入库
            children.append({
                "block_type": 17,
                "todo": {
                    "style": {"done": False},
                    "elements": [{"text_run": {"content": "确认精读入库"}}]
                }
            })
            # Todo block 2: [ ] 移出待选
            children.append({
                "block_type": 17,
                "todo": {
                    "style": {"done": False},
                    "elements": [{"text_run": {"content": "移出待选"}}]
                }
            })

            # Meta text: 来源: [arXiv] | 发表年份/日期: ... | 录用会议: ... | 发表单位/实验室: ... | 原文链接: ...
            src_str = ", ".join(p.sources or [p.source])
            date_str = p.published_date.strftime("%Y-%m-%d") if p.published_date else ""
            date_part = f" | 日期: {date_str}" if date_str else ""
            affil_str = ", ".join(p.affiliations) if p.affiliations else "N/A"
            venue_line = f"录用会议: {p.venue}\n" if getattr(p, "venue", None) else ""
            meta_prefix = (
                f"来源: [{src_str}]{date_part}\n"
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

            # TL;DR
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

        # 5. Filter and sequentially append AI Dynamics & GitHub Trending items
        if trending_items:
            trends_to_add: list[TrendingItem] = []
            for item in trending_items:
                i_clean = item.title.strip().lower()
                if item.url and item.url in existing_urls:
                    continue
                if i_clean in existing_titles:
                    continue
                trends_to_add.append(item)

            if trends_to_add:
                # Add section heading if this is the first batch or fresh document
                has_trending_header = any(
                    "AI 动态与 GitHub 热点" in "".join(
                        el.get("text_run", {}).get("content", "")
                        for el in b.get("heading2", {}).get("elements", [])
                    )
                    for b in existing_blocks if b.get("block_type") == 4
                )
                if not has_trending_header:
                    children.append({
                        "block_type": 4,
                        "heading2": {
                            "elements": [
                                {"text_run": {"content": "二、AI 动态与 GitHub 热点"}}
                            ]
                        }
                    })

                for item in trends_to_add:
                    existing_card_count += 1
                    idx = existing_card_count
                    tags_str = " ".join(f"[#{t}]" for t in (item.tags or ["Hot"]))
                    stars_str = f" (⭐ {item.stars:,})" if item.stars else ""

                    # Heading 3: 21. [#Agent] vllm-project/vllm (⭐ 28,400)
                    children.append({
                        "block_type": 5,
                        "heading3": {
                            "elements": [
                                {"text_run": {"content": f"{idx}. {tags_str} {item.title}{stars_str}"}}
                            ]
                        }
                    })

                    # Todo 1: Confirm ingest
                    children.append({
                        "block_type": 17,
                        "todo": {
                            "style": {"done": False},
                            "elements": [{"text_run": {"content": "确认入库"}}]
                        }
                    })
                    # Todo 2: Discard
                    children.append({
                        "block_type": 17,
                        "todo": {
                            "style": {"done": False},
                            "elements": [{"text_run": {"content": "移出待选"}}]
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

        # 6. Append blocks in batches of 50 if there are new blocks
        if children:
            logger.info(f"Writing {len(children)} candidate blocks to document {doc_id} in batches of 50...")
            batch_size = 50
            for i in range(0, len(children), batch_size):
                chunk = children[i : i + batch_size]
                self._call_api(
                    "POST",
                    f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    data={"children": chunk, "index": -1}
                )

        doc_url = doc_url or f"https://feishu.cn/docx/{doc_id}"
        logger.info(f"Feishu candidate document updated successfully: {doc_url}")
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
                is_system_header = bool(
                    re.match(r"^[一二三四五六七八九十]+、", raw_heading)
                    or "今日精读任务规划" in raw_heading
                    or "Reading Plan" in raw_heading
                    or "任务规划" in raw_heading
                    or "个人研读批注" in raw_heading
                )
                if not is_system_header:
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
        """Discovers checked papers across candidate document and daily reports in the Wiki space."""
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
            doc_ids = [r.get("obj_token") for r in reports if r.get("obj_token")]
            if self.candidate_node_token:
                cand_obj, _ = self.get_obj_token_from_node_token(str(self.candidate_node_token))
                if cand_obj and cand_obj not in doc_ids:
                    doc_ids.append(cand_obj)
            for doc_id in doc_ids:
                checked = self.fetch_checked_paper_details(doc_id)
                all_checked.extend(checked)
        except Exception as exc:
            logger.warning(f"Failed to scan daily reports in Wiki: {exc}")
        return all_checked

    def fetch_unreviewed_cards_from_wiki(self) -> list[dict[str, Any]]:
        """Discovers unreviewed (pending) candidate cards across daily reports in the Wiki space."""
        if not self.wiki_space_id or not self.daily_parent_node_token or self.dry_run:
            return []

        unreviewed_cards: list[dict[str, Any]] = []
        try:
            res = self._call_api(
                "GET",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"parent_node_token": str(self.daily_parent_node_token)}
            )
            reports = res.get("items", [])
            for r in reports:
                doc_id = r.get("obj_token")
                if not doc_id:
                    continue
                blocks_res = self._call_api("GET", f"/docx/v1/documents/{doc_id}/blocks")
                items = blocks_res.get("items", [])

                current_card = None
                for item in items:
                    b_type = item.get("block_type")
                    if b_type in (4, 5):
                        h_key = "heading2" if b_type == 4 else "heading3"
                        elements = item.get(h_key, {}).get("elements", [])
                        raw_heading = "".join(el.get("text_run", {}).get("content", "") for el in elements).strip()
                        is_system_header = bool(
                            re.match(r"^[一二三四五六七八九十]+、", raw_heading)
                            or "今日精读任务规划" in raw_heading
                            or "Reading Plan" in raw_heading
                            or "任务规划" in raw_heading
                            or "个人研读批注" in raw_heading
                        )
                        if not is_system_header:
                            if current_card and not current_card["has_done"]:
                                unreviewed_cards.append(current_card)
                            current_card = {
                                "title": re.sub(r"^\d+\.\s*", "", raw_heading).strip(),
                                "raw_heading": raw_heading,
                                "document_id": doc_id,
                                "url": "",
                                "affiliations": [],
                                "sources": [],
                                "tldr": "",
                                "has_done": False,
                            }
                    elif b_type == 17 and current_card:
                        if item.get("todo", {}).get("style", {}).get("done", False):
                            current_card["has_done"] = True
                    elif b_type == 2 and current_card:
                        full_text = "".join(el.get("text_run", {}).get("content", "") for el in item.get("text", {}).get("elements", []))
                        if "原文链接:" in full_text or "原文/开源主页:" in full_text or "官方/开源主页:" in full_text:
                            url_match = re.search(r"https?://\S+", full_text)
                            if url_match:
                                current_card["url"] = url_match.group(0).rstrip(" \n\r")
                        if "TL;DR:" in full_text:
                            current_card["tldr"] = full_text.replace("TL;DR:", "").strip()

                if current_card and not current_card["has_done"]:
                    unreviewed_cards.append(current_card)

        except Exception as exc:
            logger.warning(f"Failed to fetch unreviewed cards from Wiki: {exc}")
        return unreviewed_cards

    def create_reading_note(
        self,
        paper: Paper,
        sections: Optional[dict[str, Any]] = None,
        status: str = READING_STATUS_TODO,
    ) -> str:
        """Creates a structured deep reading note or AI tool / skill note under the Wiki notes parent node."""
        if self.dry_run:
            return "https://feishu.cn/docx/dry_run_note"

        sections = sections or {}
        today = datetime.now().strftime("%Y-%m-%d")
        title = paper.title_with_venue()
        current_status = normalize_reading_status(status)

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

        is_app_note = bool(
            sections.get("scenarios_and_triggers")
            or sections.get("quick_start")
            or sections.get("usage_examples")
            or ("github.com" in (paper.url or "").lower())
        )

        blocks: list[dict[str, Any]] = []

        if is_app_note:
            overview = sections.get("overview") or sections.get("core_summary") or paper.tldr_zh or paper.tldr or paper.abstract[:200]
            scenarios = sections.get("scenarios_and_triggers") or "适用于自主智能体工作流执行、工具调用与开发环境自动化。"
            quick_start = sections.get("quick_start") or f"1. 获取项目: git clone {paper.url or 'N/A'}\n2. 配置前置依赖与必要环境变量。"
            usage_examples = sections.get("usage_examples") or f"# 详细使用与调用示例请参阅仓库主页:\n# {paper.url or 'N/A'}"
            tips = sections.get("key_features_and_tips") or "1. 遵循工具入参调用规范。\n2. 注意运行环境版本兼容性。"

            # Top Metadata & Status Block
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"🏷️ 阅读状态: {current_status}  {READING_STATUS_BAR}\n"}},
                        {"text_run": {"content": f"项目类型: AI 应用 / 开源项目 / Agent Skill\n"}},
                        {"text_run": {"content": f"来源: [{src_str}] | 项目主页: {paper.url or 'N/A'}\n"}},
                        {"text_run": {"content": f"收录日期: {date_str}\n"}},
                    ]
                }
            })

            # Top: Personal Annotation and Reflection Workspace
            blocks.extend(_build_annotation_workspace_blocks(sections, is_app_note=True))

            # Structured Sections
            blocks.extend([
                {
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "一、项目定位与核心功能"}}]}
                },
                {
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": f"{overview}\n"}}]}
                },
                {
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "二、适用场景与触发时机 (When to Use / Triggers)"}}]}
                },
                {
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": f"{scenarios}\n"}}]}
                },
                {
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "三、环境依赖与快速上手 (Installation & Setup)"}}]}
                },
                {
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": f"{quick_start}\n"}}]}
                },
                {
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "四、具体使用方式与调用示例 (Usage & Examples)"}}]}
                },
                {
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": f"{usage_examples}\n"}}]}
                },
                {
                    "block_type": 4,
                    "heading2": {"elements": [{"text_run": {"content": "五、核心配置与注意事项 (Configuration & Tips)"}}]}
                },
                {
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": f"{tips}\n"}}]}
                },
            ])
        else:
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

            # Top Metadata & Status Block
            blocks.append({
                "block_type": 2,
                "text": {
                    "elements": [
                        {"text_run": {"content": f"🏷️ 阅读状态: {current_status}  {READING_STATUS_BAR}\n"}},
                        {"text_run": {"content": f"来源: [{src_str}] | 日期: {date_str} | 录用会议/期刊: {venue_str}\n"}},
                        {"text_run": {"content": f"发表单位/实验室: {affil_str}\n"}},
                        {"text_run": {"content": f"原文直达: {paper.url or 'N/A'}\n"}},
                    ]
                }
            })

            # Top: Personal Annotation and Reflection Workspace
            blocks.extend(_build_annotation_workspace_blocks(sections, is_app_note=False))

            # Structured Sections
            blocks.extend([
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
            ])

        # Append blocks in batches of 50 to respect Feishu Docx API limit
        batch_size = 50
        for i in range(0, len(blocks), batch_size):
            chunk = blocks[i : i + batch_size]
            self._call_api(
                "POST",
                f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                data={"children": chunk, "index": -1}
            )
        logger.info(f"Published reading note successfully: {note_url}")
        return note_url

    def append_to_master_index(
        self,
        paper: Paper,
        note_url: str,
        tags: Optional[list[str]] = None,
        core_summary: str = "",
        status: str = READING_STATUS_TODO,
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
        current_status = normalize_reading_status(status)

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
                        {"text_run": {"content": f"• 🏷️ 阅读状态: {current_status}  {READING_STATUS_BAR}\n"}},
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

    def get_reading_status(self, document_id: str) -> Optional[str]:
        """Inspects the reading lifecycle status of a document."""
        if self.dry_run:
            return READING_STATUS_TODO
        try:
            res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks")
            items = res.get("items", [])
            for item in items:
                if item.get("block_type") == 2:  # text
                    full_text = "".join(
                        el.get("text_run", {}).get("content", "")
                        for el in item.get("text", {}).get("elements", [])
                    )
                    if "阅读状态:" in full_text:
                        after_status = full_text.split("阅读状态:", 1)[1]
                        status_part = after_status.split("[")[0].strip()
                        for st in READING_STATUSES:
                            if st in status_part:
                                return st
                        match = re.search(r"^([^\n\[\]|]+)", status_part)
                        if match:
                            return normalize_reading_status(match.group(1).strip())
            return None
        except Exception as exc:
            logger.warning(f"Failed to get reading status from document {document_id}: {exc}")
            return None

    def update_reading_status(self, document_id: str, new_status: str) -> bool:
        """Updates the reading lifecycle status in a Feishu document."""
        target_status = normalize_reading_status(new_status)
        if self.dry_run:
            logger.info(f"[Dry-run] Updated document {document_id} reading status to: {target_status}")
            return True

        try:
            res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks")
            items = res.get("items", [])
            for item in items:
                if item.get("block_type") == 2:
                    elements = item.get("text", {}).get("elements", [])
                    full_text = "".join(el.get("text_run", {}).get("content", "") for el in elements)
                    if "阅读状态:" in full_text:
                        block_id = item.get("block_id")
                        new_line = f"🏷️ 阅读状态: {target_status}  {READING_STATUS_BAR}"
                        updated_text = re.sub(
                            r"🏷️?\s*阅读状态:[^\n]*",
                            new_line,
                            full_text
                        )
                        self._call_api(
                            "PATCH",
                            f"/docx/v1/documents/{document_id}/blocks/{block_id}",
                            data={
                                "update_text_elements": {
                                    "elements": [{"text_run": {"content": updated_text}}]
                                }
                            }
                        )
                        logger.info(f"Updated document {document_id} reading status to '{target_status}'")
                        return True
            logger.warning(f"Could not find reading status block in document {document_id}")
            return False
        except Exception as exc:
            logger.error(f"Failed to update reading status in document {document_id}: {exc}")
            return False

    def create_reading_task(
        self,
        paper: Optional[Paper] = None,
        title: Optional[str] = None,
        note_url: Optional[str] = None,
        due_time: Optional[Union[datetime, str, int, float]] = None,
        assignee_id: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Creates a Lark Task (v2) for reading planning with due date and note link.

        API: POST /task/v2/tasks
        """
        task_title = title or (f"📖 精读: {paper.title_with_venue()}" if paper else "📖 论文精读任务")

        # Construct task description
        if description:
            desc_str = description
        else:
            desc_lines = []
            if note_url:
                desc_lines.append(f"📘 精读笔记直达: {note_url}")
            if paper and paper.url:
                desc_lines.append(f"🔗 原文直达: {paper.url}")
            if paper and (paper.tldr_zh or paper.tldr):
                desc_lines.append(f"💡 核心摘要: {paper.tldr_zh or paper.tldr}")
            if tags:
                desc_lines.append(f"🏷️ 方向标签: {' '.join(f'[#{t}]' for t in tags)}")
            desc_lines.append("\n【研读待办建议】:")
            desc_lines.append("1. 研读核心架构与方法创新点")
            desc_lines.append("2. 在笔记中记录批判性质疑与结合点")
            desc_lines.append("3. 评估 Baseline 接入与实验复现价值")
            desc_str = "\n".join(desc_lines)

        # Parse due date
        is_all_day = False
        if due_time is None:
            now = datetime.now()
            due_dt = datetime(now.year, now.month, now.day, 23, 59, 59) + timedelta(days=1)
            ts_ms = str(int(due_dt.timestamp() * 1000))
        elif isinstance(due_time, datetime):
            ts_ms = str(int(due_time.timestamp() * 1000))
        elif isinstance(due_time, (int, float)):
            val = int(due_time)
            if val < 10000000000:  # in seconds
                val *= 1000
            ts_ms = str(val)
        elif isinstance(due_time, str):
            due_str = due_time.strip()
            if due_str.isdigit():
                val = int(due_str)
                if val < 10000000000:
                    val *= 1000
                ts_ms = str(val)
            else:
                try:
                    dt = datetime.strptime(due_str, "%Y-%m-%d")
                    ts_ms = str(int(dt.timestamp() * 1000))
                    is_all_day = True
                except ValueError:
                    try:
                        dt = datetime.fromisoformat(due_str)
                        ts_ms = str(int(dt.timestamp() * 1000))
                    except ValueError:
                        now = datetime.now()
                        due_dt = datetime(now.year, now.month, now.day, 23, 59, 59) + timedelta(days=1)
                        ts_ms = str(int(due_dt.timestamp() * 1000))
        else:
            now = datetime.now()
            due_dt = datetime(now.year, now.month, now.day, 23, 59, 59) + timedelta(days=1)
            ts_ms = str(int(due_dt.timestamp() * 1000))

        due_obj = {
            "timestamp": ts_ms,
            "is_all_day": is_all_day,
        }

        origin_obj = {
            "platform_i18n_name": {
                "zh_cn": "飞书论文速递",
                "en_us": "Feishu Paper Daily",
            },
            "href": {
                "url": note_url or (paper.url if paper else "https://open.feishu.cn"),
                "title": "打开精读笔记" if note_url else "打开原文",
            }
        }

        target_assignee = assignee_id or self.config.get("user_id") or self.config.get("user_openid")
        members = []
        if target_assignee:
            members.append({
                "id": str(target_assignee),
                "type": "user",
                "role": "assignee",
            })

        payload: dict[str, Any] = {
            "summary": task_title,
            "description": desc_str,
            "due": due_obj,
            "origin": origin_obj,
        }
        if members:
            payload["members"] = members

        if self.dry_run:
            logger.info(f"[Dry-run] Lark Task created: '{task_title}' (due: {ts_ms})")
            return {
                "guid": "dry_run_task_guid",
                "summary": task_title,
                "url": "https://feishu.cn/task/dry_run",
                "due": due_obj,
            }

        logger.info(f"Creating Lark Task: '{task_title}' via /task/v2/tasks...")
        res = self._call_api("POST", "/task/v2/tasks", data=payload)
        task_data = res.get("task", res.get("data", res))
        logger.info(f"Lark Task created successfully: guid={task_data.get('guid')}")
        return task_data
