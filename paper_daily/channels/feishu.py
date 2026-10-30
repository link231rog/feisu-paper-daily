import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unicodedata
from datetime import datetime, timedelta
from typing import Any, Optional, Union
import requests
from loguru import logger
from omegaconf import DictConfig

from ..protocol import Paper, CorpusPaper, TrendingItem
from ..utils import clean_paper_markdown

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


def extract_user_reason(todo_text: str) -> str:
    """Extracts user-typed preference reason from a checked todo line, removing standard labels and hints."""
    s = str(todo_text or "").strip()
    if not s:
        return ""
    # Strip parenthesized or bracketed default prompt hints
    s = re.sub(r"[（\(](?:可在此输入|可直接输入|可选).*?[）\)]", "", s)
    # Strip standard action keywords at the beginning
    s = re.sub(
        r"^\[?[xX✓✔]?\]?\s*(?:确认精读入库|精读入库|确认入库|入库|移出待选|移出|删除待选|删除|淘汰|delete|discard|ingest)\s*[:：\-—]*\s*",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = s.strip(" :：-—\t\r\n")
    return s if len(s) >= 2 else ""


def _build_annotation_workspace_markdown(
    sections: dict[str, Any],
    is_app_note: bool = False
) -> str:
    """Builds markdown for the Personal Reading Annotation & Reflection Workspace with Feishu XML checkboxes."""
    insights = (
        sections.get("personal_insights")
        or sections.get("insights")
        or ""
    )
    critique = (
        sections.get("personal_critique")
        or sections.get("critique")
        or ""
    )
    relevance = (
        sections.get("personal_relevance")
        or sections.get("relevance")
        or ""
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

    lines = [
        "## ✍️ Reading Notes & Reflections",
        "",
        "### 💡 Key Insights & Surprises",
        insights if insights else "*(可在研读后直接划词批注或记录关键洞察)*",
        "",
        "### ❓ Critique, Method Flaws, Limitations",
        critique if critique else "*(记录论文假设漏洞、对比缺陷或未解决的边界条件)*",
        "",
        "### 🎯 Relevance to my Research / Idea / Baseline adoption",
        relevance if relevance else "*(记录对自身研究/业务体系的迁移启发)*",
        "",
        "### 📌 Action Items",
    ]
    for item in action_items:
        lines.append(f"<checkbox done=\"false\">{item}</checkbox>")
    lines.append("")
    return "\n".join(lines)


def _split_markdown_chunks(
    text: str,
    max_chunk_chars: int = 6000,
    max_images_per_chunk: int = 2,
) -> list[str]:
    """Splits markdown into safe chunks for Feishu Docs AI endpoint, respecting section boundaries and image density."""
    if not text:
        return []

    sections = re.split(r"(?=\n(?:#{1,3}\s|!\[))", text)
    chunks = []
    current_chunk = []
    current_len = 0
    current_imgs = 0

    for sec in sections:
        if not sec:
            continue
        sec_len = len(sec)
        sec_imgs = len(re.findall(r"!\[.*?\]\(.*?\)", sec))

        if (current_len + sec_len <= max_chunk_chars) and (current_imgs + sec_imgs <= max_images_per_chunk or current_imgs == 0):
            current_chunk.append(sec)
            current_len += sec_len
            current_imgs += sec_imgs
        else:
            if current_chunk:
                chunks.append("".join(current_chunk))
                current_chunk = []
                current_len = 0
                current_imgs = 0

            if sec_len > max_chunk_chars:
                paragraphs = re.split(r"(?=\n\n)", sec)
                p_chunk = []
                p_len = 0
                p_imgs = 0
                for p in paragraphs:
                    p_img_count = len(re.findall(r"!\[.*?\]\(.*?\)", p))
                    if (p_len + len(p) <= max_chunk_chars) and (p_imgs + p_img_count <= max_images_per_chunk or p_imgs == 0):
                        p_chunk.append(p)
                        p_len += len(p)
                        p_imgs += p_img_count
                    else:
                        if p_chunk:
                            chunks.append("".join(p_chunk))
                            p_chunk = []
                            p_len = 0
                            p_imgs = 0
                        if len(p) > max_chunk_chars:
                            for i in range(0, len(p), max_chunk_chars):
                                chunks.append(p[i : i + max_chunk_chars])
                        else:
                            p_chunk.append(p)
                            p_len = len(p)
                            p_imgs = p_img_count
                if p_chunk:
                    chunks.append("".join(p_chunk))
            else:
                current_chunk.append(sec)
                current_len = sec_len
                current_imgs = sec_imgs

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


def autocrop_image_to_png(
    image_data: Union[str, bytes],
    ext: str = ".png",
    pad: int = 15,
    whitespace_threshold: float = 0.03,
) -> tuple[Optional[str], int, int]:
    """Inspects an image (SVG, PNG, JPG, WebP, etc.) and crops it tightly to its non-white content boundary.

    Args:
        image_data: Either a local file path (str) or raw file bytes (bytes).
        ext: File extension (e.g. '.svg', '.png', '.jpg').
        pad: Padding in pixels to keep around the cropped content boundary.
        whitespace_threshold: Minimum fraction of whitespace on any side to trigger cropping for raster images.
                              (SVGs are always cropped to ensure crisp bounding boxes).

    Returns:
        (temp_png_path, width, height) if cropping was performed,
        (None, orig_width, orig_height) if no cropping was necessary or on error.
    """
    try:
        import pymupdf
        import numpy as np

        if isinstance(image_data, str):
            if not os.path.exists(image_data):
                return None, 0, 0
            doc = pymupdf.open(image_data)
        else:
            doc = pymupdf.open(stream=image_data, filetype=ext.lstrip("."))

        if len(doc) == 0:
            return None, 0, 0

        page = doc[0]
        # Initial render at 150 DPI for fast bounding box detection
        pix = page.get_pixmap(dpi=150)
        samples = np.frombuffer(pix.samples, dtype=np.uint8).reshape((pix.height, pix.width, pix.n))
        rgb = samples[:, :, :3]
        non_white = np.any(rgb < 245, axis=2)
        if pix.alpha:
            non_white = non_white & (samples[:, :, 3] > 10)

        y_idx, x_idx = np.where(non_white)
        if len(y_idx) == 0 or len(x_idx) == 0:
            return None, pix.width, pix.height

        ymin, ymax = int(y_idx.min()), int(y_idx.max())
        xmin, xmax = int(x_idx.min()), int(x_idx.max())

        top_ws = ymin / pix.height
        bot_ws = (pix.height - ymax) / pix.height
        left_ws = xmin / pix.width
        right_ws = (pix.width - xmax) / pix.width

        is_svg = ext.lower().endswith("svg")
        # For raster images, only crop if there is notable white space
        if not is_svg and max(top_ws, bot_ws, left_ws, right_ws) < whitespace_threshold:
            return None, pix.width, pix.height

        scale_x = page.rect.width / pix.width
        scale_y = page.rect.height / pix.height
        p_xmin = max(0, xmin * scale_x - pad)
        p_xmax = min(page.rect.width, xmax * scale_x + pad)
        p_ymin = max(0, ymin * scale_y - pad)
        p_ymax = min(page.rect.height, ymax * scale_y + pad)

        clip = pymupdf.Rect(p_xmin, p_ymin, p_xmax, p_ymax)
        # Render final cropped image at 200 DPI for high fidelity
        final_pix = page.get_pixmap(dpi=200, clip=clip)
        tf = tempfile.NamedTemporaryFile(dir="/tmp", suffix=".png", delete=False)
        final_pix.save(tf.name)
        tf.close()
        return tf.name, final_pix.width, final_pix.height
    except Exception as exc:
        logger.debug(f"autocrop_image_to_png failed: {exc}")
        return None, 0, 0


def parse_inline_elements(text: str) -> list[dict[str, Any]]:
    """Parses inline Markdown formatting into Feishu Docx elements."""
    elements: list[dict[str, Any]] = []

    # Pre-normalize HTML bold and italic tags to markdown
    text = re.sub(r"<(?:b|strong)>(.*?)</(?:b|strong)>", r"**\1**", text, flags=re.IGNORECASE)
    text = re.sub(r"<(?:i|em)>(.*?)</(?:i|em)>", r"*\1*", text, flags=re.IGNORECASE)

    pattern = re.compile(
        r"(\$[^$\n]+\$)"                             # 1. inline LaTeX equation
        r"|(\[[^\]]+\]\([^\s\)]+\))"                 # 2. markdown link [text](url)
        r"|(\*\*\*[^*]+\*\*\*)"                      # 3. bold + italic ***text***
        r"|(\*\*[^*]+\*\*|__[^\_]+__)"               # 4. bold **text** or __text__
        r"|(`[^`\n]+`)"                              # 5. inline code `code`
        r"|(~~[^~]+~~)"                              # 6. strikethrough ~~text~~
        r"|((?<!\w)\*[^*\n]+?\*(?!\w)|(?<!\w)_[^_\n]+?_(?!\w))" # 7. italic *text* or _text_
    )

    pos = 0
    for match in pattern.finditer(text):
        start, end = match.span()
        if start > pos:
            plain = text[pos:start]
            if plain:
                elements.append({"text_run": {"content": plain}})

        token = match.group(0)
        # 1. Math equation
        if token.startswith("$") and token.endswith("$") and len(token) > 2:
            eq_content = token[1:-1].strip()
            elements.append({"equation": {"content": eq_content}})
        # 2. Markdown Link
        elif token.startswith("[") and "](" in token and token.endswith(")"):
            link_match = re.match(r"\[([^\]]+)\]\((https?://[^\s\)]+)\)", token)
            if link_match:
                link_text, link_url = link_match.groups()
                elements.append({
                    "text_run": {
                        "content": link_text,
                        "text_element_style": {"link": {"url": link_url}},
                    }
                })
            else:
                elements.append({"text_run": {"content": token}})
        # 3. Bold + Italic
        elif token.startswith("***") and token.endswith("***") and len(token) > 6:
            content = token[3:-3]
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"bold": True, "italic": True},
                }
            })
        # 4. Bold (**text** or __text__)
        elif ((token.startswith("**") and token.endswith("**")) or (token.startswith("__") and token.endswith("__"))) and len(token) > 4:
            content = token[2:-2]
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"bold": True},
                }
            })
        # 5. Inline Code
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            code_text = token[1:-1]
            elements.append({
                "text_run": {
                    "content": code_text,
                    "text_element_style": {"inline_code": True},
                }
            })
        # 6. Strikethrough
        elif token.startswith("~~") and token.endswith("~~") and len(token) > 4:
            content = token[2:-2]
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"strikethrough": True},
                }
            })
        # 7. Italic (*text* or _text_)
        elif ((token.startswith("*") and token.endswith("*")) or (token.startswith("_") and token.endswith("_"))) and len(token) > 2:
            content = token[1:-1]
            elements.append({
                "text_run": {
                    "content": content,
                    "text_element_style": {"italic": True},
                }
            })
        pos = end

    if pos < len(text):
        plain = text[pos:]
        if plain:
            elements.append({"text_run": {"content": plain}})

    return elements or [{"text_run": {"content": ""}}]


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
        self.engineering_parent_node_token = config.get("engineering_parent_node_token")
        self.console_node_token = config.get("console_node_token")
        self.reading_note_tags: dict[str, list[str]] = {}
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
            for attempt in range(3):
                resp = requests.request(method, url, headers=headers, params=params, json=data, timeout=60)
                if resp.status_code in (429, 502, 503, 504) or (resp.status_code == 400 and "99991400" in resp.text):
                    if attempt < 2:
                        time.sleep(0.6 * (attempt + 1))
                        continue
                resp.raise_for_status()
                break
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

    def optimize_document_images(self, doc_id: str, note_markdown: str) -> int:
        """Finds each image block in a document created by Docs AI, downloads its source,
        removes excess whitespace borders, and updates the block with the tight cropped image.
        """
        if self.dry_run or not note_markdown:
            return 0

        img_matches = re.findall(r"!\[(.*?)\]\((.*?)\)", note_markdown)
        if not img_matches:
            return 0

        all_blocks = self.get_document_blocks(doc_id)
        doc_img_blocks = [b for b in all_blocks if b.get("block_type") == 27]
        if not doc_img_blocks:
            return 0

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        updated_count = 0
        for idx, blk in enumerate(doc_img_blocks):
            if idx >= len(img_matches):
                break
            cap, src = img_matches[idx]
            src = src.strip()
            if not src:
                continue

            ext = os.path.splitext(src.split("?")[0])[1].lower() or ".png"
            b_id = blk.get("block_id")
            if not b_id:
                continue

            try:
                if src.startswith("http://") or src.startswith("https://"):
                    resp = requests.get(src, headers=headers, timeout=20)
                    if resp.status_code != 200 or not resp.content:
                        continue
                    img_data: Union[str, bytes] = resp.content
                else:
                    if not os.path.exists(src):
                        continue
                    img_data = src

                cropped_path, w, h = autocrop_image_to_png(img_data, ext=ext)
                if not cropped_path or not os.path.exists(cropped_path):
                    continue

                try:
                    file_token = None
                    if self._has_lark_cli:
                        cmd = [
                            "lark-cli", "docs", "+media-upload",
                            "--as", "bot",
                            "--doc-id", str(doc_id),
                            "--parent-node", str(b_id),
                            "--parent-type", "docx_image",
                            "--file", str(cropped_path),
                            "--format", "json",
                        ]
                        res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                        if res.returncode == 0 and res.stdout.strip():
                            try:
                                res_json = json.loads(res.stdout)
                                file_token = res_json.get("data", {}).get("file_token")
                            except Exception:
                                pass

                    if not file_token and self.app_id and self.app_secret:
                        token = self._get_tenant_token()
                        upload_url = f"{FEISHU_BASE_URL}/drive/v1/medias/upload_all"
                        filename = os.path.basename(cropped_path)
                        with open(cropped_path, "rb") as f:
                            file_bytes = f.read()
                        data = {
                            "file_name": filename,
                            "parent_type": "docx_image",
                            "parent_node": str(b_id),
                            "size": len(file_bytes),
                        }
                        files = {"file": (filename, file_bytes, "image/png")}
                        auth_headers = {"Authorization": f"Bearer {token}"}
                        resp = requests.post(upload_url, headers=auth_headers, data=data, files=files, timeout=30)
                        if resp.status_code == 200:
                            res_json = resp.json()
                            if res_json.get("code") == 0:
                                file_token = res_json.get("data", {}).get("file_token")

                    if file_token:
                        payload = {
                            "requests": [
                                {
                                    "block_id": str(b_id),
                                    "replace_image": {
                                        "token": str(file_token),
                                        "width": int(w),
                                        "height": int(h),
                                    }
                                }
                            ]
                        }
                        self._call_api("PATCH", f"/docx/v1/documents/{doc_id}/blocks/batch_update", data=payload)
                        logger.info(f"Tight-cropped image block {b_id} ({src}) to {w}x{h}")
                        updated_count += 1
                finally:
                    if cropped_path and os.path.exists(cropped_path):
                        os.remove(cropped_path)
            except Exception as err:
                logger.warning(f"Failed to optimize image block {b_id} ({src}): {err}")

        logger.info(f"Optimized {updated_count}/{len(doc_img_blocks)} images to tight bounds for doc {doc_id}")
        return updated_count

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
        """Fetches all blocks for a given document with full pagination."""
        all_items: list[dict[str, Any]] = []
        page_token = None
        while True:
            params: dict[str, Any] = {"page_size": 500}
            if page_token:
                params["page_token"] = page_token
            try:
                res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks", params=params)
                items = res.get("items", [])
                all_items.extend(items)
                has_more = res.get("has_more", False)
                page_token = res.get("page_token")
                if not has_more or not page_token:
                    break
            except Exception as exc:
                logger.warning(f"Failed to fetch blocks for document {document_id}: {exc}")
                break
        return all_items

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

    def get_or_create_daily_document(self, folder_token: Optional[str] = None) -> tuple[str, str]:
        """Gets or creates today's standalone report; never appends to the legacy candidate document."""
        from datetime import date

        title = f"论文研究日报 {date.today().isoformat()}"
        if self.wiki_space_id and self.daily_parent_node_token:
            try:
                res = self._call_api(
                    "GET",
                    f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                    params={"parent_node_token": str(self.daily_parent_node_token), "page_size": 50},
                )
                for item in res.get("items", []):
                    if item.get("title") == title:
                        node_token = item.get("node_token")
                        return item.get("obj_token"), item.get("url") or f"https://feishu.cn/wiki/{node_token}"
            except Exception as exc:
                logger.warning(f"Error checking daily report in Wiki: {exc}")

            node_res = self._call_api(
                "POST",
                f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                params={"space_id": str(self.wiki_space_id)},
                data={
                    "obj_type": "docx",
                    "node_type": "origin",
                    "parent_node_token": str(self.daily_parent_node_token),
                    "title": title,
                },
            )
            node = node_res.get("node", {})
            return node.get("obj_token"), node.get("url") or f"https://feishu.cn/wiki/{node.get('node_token')}"

        target_folder = folder_token or self.daily_folder_token or ""
        if target_folder:
            res = self._call_api("GET", "/drive/v1/files", params={"folder_token": target_folder, "page_size": 200})
            for item in res.get("files", []):
                if item.get("name") == title and item.get("type") == "docx":
                    token = item.get("token")
                    return token, item.get("url") or f"https://feishu.cn/docx/{token}"
        create_payload: dict[str, Any] = {"title": title}
        if target_folder:
            create_payload["folder_token"] = target_folder
        doc_res = self._call_api("POST", "/docx/v1/documents", data=create_payload)
        doc_id = doc_res.get("document", {}).get("document_id")
        return doc_id, f"https://feishu.cn/docx/{doc_id}"

    def _get_root_children(self, document_id: str) -> list[str]:
        """Returns the current ordered list of child block IDs for the document root."""
        root_res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks/{document_id}")
        return root_res.get("block", {}).get("children", [])

    def upload_and_mount_audio(
        self,
        document_id: str,
        audio_path: str,
        index: int = 0,
        allow_multiple: bool = False,
    ) -> Optional[str]:
        """Uploads an MP3 audio file to Feishu Drive and mounts it as a playable File Block at the top of a Docx document."""
        if self.dry_run or not audio_path or not os.path.isfile(audio_path):
            return None

        try:
            existing_blocks = self.get_document_blocks(document_id)
            audio_blocks = [b for b in existing_blocks if b.get("block_type") == 23]
            if not allow_multiple and audio_blocks:
                logger.info(f"Audio file block already mounted in Feishu document {document_id}; skipping.")
                return None
            if allow_multiple and len(audio_blocks) >= 3:
                logger.info(f"Maximum audio blocks (3) already mounted in Feishu document {document_id}; skipping.")
                return None

            create_res = self._call_api(
                "POST",
                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                data={
                    "children": [{"block_type": 23, "file": {"token": ""}}],
                    "index": index,
                },
            )
            children = create_res.get("children") or []
            if not children:
                return None

            created_block = children[0]
            file_block_id = created_block.get("block_id")
            if created_block.get("block_type") == 33 and created_block.get("children"):
                file_block_id = created_block["children"][0]
            if not file_block_id:
                return None

            file_token: Optional[str] = None
            if self._has_lark_cli:
                cmd = [
                    "lark-cli",
                    "docs",
                    "+media-upload",
                    "--as",
                    "bot",
                    "--doc-id",
                    str(document_id),
                    "--parent-node",
                    str(file_block_id),
                    "--parent-type",
                    "docx_file",
                    "--file",
                    str(audio_path),
                    "--format",
                    "json",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if res.returncode == 0 and res.stdout.strip():
                    try:
                        res_json = json.loads(res.stdout)
                        file_token = res_json.get("data", {}).get("file_token")
                    except Exception:
                        pass

            if not file_token and self.app_id and self.app_secret:
                token = self._get_tenant_token()
                upload_url = f"{FEISHU_BASE_URL}/drive/v1/medias/upload_all"
                filename = os.path.basename(audio_path)
                with open(audio_path, "rb") as f_audio:
                    file_bytes = f_audio.read()
                data = {
                    "file_name": filename,
                    "parent_type": "docx_file",
                    "parent_node": str(file_block_id),
                    "size": len(file_bytes),
                }
                files = {"file": (filename, file_bytes, "audio/mpeg")}
                auth_headers = {"Authorization": f"Bearer {token}"}
                resp = requests.post(upload_url, headers=auth_headers, data=data, files=files, timeout=60)
                if resp.status_code == 200:
                    res_json = resp.json()
                    if res_json.get("code") == 0:
                        file_token = res_json.get("data", {}).get("file_token")

            if file_token:
                self._call_api(
                    "PATCH",
                    f"/docx/v1/documents/{document_id}/blocks/{file_block_id}",
                    data={"replace_file": {"token": str(file_token)}},
                )
                logger.info(f"Mounted MP3 audio block ({file_token}) in Feishu document {document_id}")
                return str(file_token)
        except Exception as exc:
            logger.warning(f"Failed to upload/mount MP3 audio block in Feishu document {document_id}: {exc}")
        return None

    def create_or_update_daily_report(
        self,
        papers: list[Paper],
        trending_items: Optional[list[TrendingItem]] = None,
        folder_token: Optional[str] = None,
        question_briefs: Optional[list[dict]] = None,
        corpus: Optional[list[CorpusPaper]] = None,
        audio_path: Optional[str] = None,
    ) -> str:
        """Publishes one standalone, date-scoped daily report in Feishu Docx."""
        if self.dry_run:
            logger.info("Feishu dry-run enabled. Skipping document creation.")
            return "https://feishu.cn/docx/dry_run"

        # 1. Target today's standalone report
        doc_id, doc_url = self.get_or_create_daily_document(folder_token)
        if not doc_id:
            raise RuntimeError("Failed to resolve daily report document_id in Feishu")

        # Ensure document edit permissions so checkboxes are clickable
        self._ensure_doc_permissions(doc_id)

        if audio_path:
            audio_list = [audio_path] if isinstance(audio_path, (str, os.PathLike)) else list(audio_path)
            for a_idx, a_path in enumerate(audio_list):
                if a_path and os.path.isfile(str(a_path)):
                    self.upload_and_mount_audio(doc_id, str(a_path), index=a_idx, allow_multiple=len(audio_list) > 1)

        # 2. Inspect existing blocks in the document to prevent duplicates and detect sections
        root_children = self._get_root_children(doc_id)
        existing_blocks = self.get_document_blocks(doc_id)
        existing_urls: set[str] = set()
        existing_titles: set[str] = set()
        existing_card_count = 0

        SECTION_PAPER = "今日推荐论文"
        SECTION_BRIEFS = "今日问题进展"
        SECTION_TRENDING = "AI 动态与 GitHub 热点"

        paper_header_id: Optional[str] = None
        briefs_header_id: Optional[str] = None
        trending_header_id: Optional[str] = None

        for b in existing_blocks:
            b_id = b.get("block_id")
            b_type = b.get("block_type")
            if b_type in (4, 5):  # heading2 or heading3
                h_key = "heading2" if b_type == 4 else "heading3"
                txt = "".join(el.get("text_run", {}).get("content", "") for el in b.get(h_key, {}).get("elements", [])).strip()

                if SECTION_PAPER in txt:
                    paper_header_id = b_id
                elif SECTION_BRIEFS in txt:
                    briefs_header_id = b_id
                elif SECTION_TRENDING in txt:
                    trending_header_id = b_id
                else:
                    # Title block for a paper or trending item
                    existing_titles.add(txt.lower())
                    clean = re.sub(r"^\d+\.\s*", "", txt).strip().lower()
                    existing_titles.add(clean)
                    # Strip venue/parentheses e.g. "Title (ACL 2026)" -> "Title"
                    no_venue = re.sub(r"\s*[\(\[].*?[\)\]]\s*$", "", clean).strip()
                    if no_venue:
                        existing_titles.add(no_venue)
                    if b_type == 4:
                        existing_card_count += 1
            elif b_type == 2:  # text
                for el in b.get("text", {}).get("elements", []):
                    link_url = el.get("text_element_style", {}).get("link", {}).get("url")
                    if link_url:
                        existing_urls.add(link_url.strip())
                    txt = el.get("text_run", {}).get("content", "")
                    for u in re.findall(r"https?://\S+", txt):
                        existing_urls.add(u.rstrip(" \n\r"))

        # Collect existing brief block IDs to cleanly replace them if updating briefs today
        old_brief_block_ids: list[str] = []
        if briefs_header_id and briefs_header_id in root_children:
            start_i = root_children.index(briefs_header_id)
            end_i = root_children.index(trending_header_id) if trending_header_id and trending_header_id in root_children else len(root_children)
            old_brief_block_ids = root_children[start_i:end_i]

        def insert_blocks(blocks_to_insert: list[dict[str, Any]], target_index: int = -1) -> None:
            if not blocks_to_insert:
                return
            batch_size = 50
            curr_idx = target_index
            for i in range(0, len(blocks_to_insert), batch_size):
                chunk = blocks_to_insert[i : i + batch_size]
                self._call_api(
                    "POST",
                    f"/docx/v1/documents/{doc_id}/blocks/{doc_id}/children",
                    data={"children": chunk, "index": curr_idx}
                )
                if curr_idx != -1:
                    curr_idx += len(chunk)

        # 3. Filter and append academic papers
        papers_to_add: list[Paper] = []
        for p in papers:
            p_clean = p.clean_title.lower() if hasattr(p, "clean_title") else p.title.strip().lower()
            p_raw = p.title.strip().lower()
            if p.url and p.url in existing_urls:
                continue
            if p_clean in existing_titles or p_raw in existing_titles:
                continue
            papers_to_add.append(p)

        paper_blocks: list[dict[str, Any]] = []
        if (not paper_header_id or len(existing_blocks) <= 1) and (papers_to_add or not existing_blocks):
            paper_blocks.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {"text_run": {"content": "一、今日推荐论文"}}
                    ]
                }
            })
            paper_header_id = "pending"

        for p in papers_to_add:
            existing_card_count += 1
            idx = existing_card_count
            title_display = p.title_with_venue()

            # Heading 2: Paper Title (Conference) (no sequential numbering)
            paper_blocks.append({
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {
                            "text_run": {
                                "content": title_display
                            }
                        }
                    ]
                }
            })

            # Todo block 1: [ ] 确认精读入库 (支持输入个性理由)
            paper_blocks.append({
                "block_type": 17,
                "todo": {
                    "style": {"done": False},
                    "elements": [
                        {"text_run": {"content": "确认精读入库", "text_element_style": {"bold": True}}},
                        {"text_run": {"content": "（可在此输入入库理由/个性偏好，AI 自动记忆学习）", "text_element_style": {"text_color": 7, "italic": True}}},
                    ]
                }
            })
            # Todo block 2: [ ] 移出待选 (支持输入淘汰特征)
            paper_blocks.append({
                "block_type": 17,
                "todo": {
                    "style": {"done": False},
                    "elements": [
                        {"text_run": {"content": "移出待选", "text_element_style": {"bold": True}}},
                        {"text_run": {"content": "（可在此输入淘汰理由/排除特征，AI 自动加入负向排除）", "text_element_style": {"text_color": 7, "italic": True}}},
                    ]
                }
            })

            # Meta text: 来源: [arXiv] | 发表年份/日期: ... | 录用会议: ... | 发表单位/实验室: ... | 原文链接: ...
            tier = getattr(p, "recommendation_tier", None) or "deep_read"
            tier_label = "[精读必看]" if tier == "deep_read" else "[速览雷达]"
            qa_max = max(p.qa_scores.values()) if getattr(p, "qa_scores", None) else None
            rigor = getattr(p, "evidence_rigor", None)
            score_badges = []
            if qa_max is not None:
                score_badges.append(f"问题推进: {qa_max}/10")
            if rigor is not None:
                score_badges.append(f"证据硬核度: {rigor}/5")
            if getattr(p, "is_priority_institution", False):
                score_badges.append("[核心关注机构]")
            badge_str = f" ({' · '.join(score_badges)})" if score_badges else ""

            src_str = ", ".join(p.sources or [p.source])
            date_str = p.published_date.strftime("%Y-%m-%d") if p.published_date else ""
            date_part = f" | 日期: {date_str}" if date_str else ""
            affil_str = ", ".join(p.affiliations) if p.affiliations else "N/A"

            meta_elements: list[dict[str, Any]] = [
                {"text_run": {"content": "推荐层级: ", "text_element_style": {"bold": True}}},
                {"text_run": {"content": f"{tier_label}", "text_element_style": {"bold": True, "text_color": 5 if tier == "deep_read" else 4}}},
                {"text_run": {"content": f"{badge_str}\n", "text_element_style": {"text_color": 7}}},
                {"text_run": {"content": f"来源: [{src_str}]{date_part}\n"}},
            ]
            if getattr(p, "venue", None):
                meta_elements.extend([
                    {"text_run": {"content": "录用会议/期刊: ", "text_element_style": {"bold": True}}},
                    {"text_run": {"content": f"{p.venue}\n"}},
                ])
            meta_elements.extend([
                {"text_run": {"content": "发表单位/团队: ", "text_element_style": {"bold": True}}},
                {"text_run": {"content": f"{affil_str}\n"}},
                {"text_run": {"content": "原文直达: ", "text_element_style": {"bold": True}}},
            ])
            if p.url and p.url.startswith("http"):
                meta_elements.append({
                    "text_run": {
                        "content": "点击查看原文 ↗",
                        "text_element_style": {"bold": True, "link": {"url": p.url}},
                    }
                })
            else:
                meta_elements.append({"text_run": {"content": p.url or "N/A"}})

            if getattr(p, "pdf_url", None) and str(p.pdf_url).startswith("http"):
                meta_elements.extend([
                    {"text_run": {"content": "  ·  "}},
                    {
                        "text_run": {
                            "content": "PDF 原文 ↗",
                            "text_element_style": {"bold": True, "link": {"url": str(p.pdf_url)}},
                        }
                    },
                ])
            meta_elements.append({"text_run": {"content": "\n"}})

            paper_blocks.append({
                "block_type": 2,
                "text": {
                    "elements": meta_elements
                }
            })

            # Critical-Paper-Digest or fallback TL;DR
            if getattr(p, "critical_digest", None):
                from ..core.digest import format_digest_feishu_elements

                digest_elements = format_digest_feishu_elements(p, corpus=corpus, client=self)
                paper_blocks.append({
                    "block_type": 2,
                    "text": {
                        "elements": digest_elements
                    }
                })
            else:
                from ..utils import translate_to_chinese

                en_summary = p.tldr_en or (p.abstract[:250] + "..." if p.abstract else "N/A")
                zh_summary = p.tldr_zh or p.tldr or ""

                if not zh_summary or not re.search(r"[\u4e00-\u9fff]", zh_summary):
                    zh_summary = translate_to_chinese(en_summary)

                if zh_summary and re.search(r"[\u4e00-\u9fff]", zh_summary):
                    tldr_text = f"TL;DR: {en_summary}\n中文速览: {zh_summary}"
                else:
                    tldr_text = f"TL;DR: {en_summary}"

                if getattr(p, "judge_reason", None):
                    tldr_text += f"\n入选理由: {p.judge_reason}"

                paper_blocks.append({
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": f"{tldr_text}\n"}}
                        ]
                    }
                })

            # In-line annotations & abstract rendering
            if getattr(p, "inline_annotations", None):
                from ..core.annotator import build_annotated_text_elements

                annotated_elements = build_annotated_text_elements(p, corpus=corpus, client=self)
                paper_blocks.append({
                    "block_type": 2,
                    "text": {
                        "elements": annotated_elements
                    }
                })
            elif tier == "quick_radar" and p.qa_matches:
                qa_lines = ["[关键证据速览]:"]
                for match in p.qa_matches[:2]:
                    qa_lines.append(f"  • [{match.get('question', '')}] -> {match.get('answer', '')}")
                paper_blocks.append({
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": "\n".join(qa_lines) + "\n"}}
                        ]
                    }
                })
            else:
                # Fallback to plain English abstract and standalone cards
                if p.abstract and p.abstract.strip():
                    clean_abs = p.abstract.strip()
                    paper_blocks.append({
                        "block_type": 2,
                        "text": {
                            "elements": [{"text_run": {"content": f"英文摘要 (Abstract):\n{clean_abs}\n"}}]
                        }
                    })

                # Tracked-question matches
                if p.qa_matches:
                    qa_lines = ["[关注问题匹配]:"]
                    for match in p.qa_matches:
                        qa_lines.append(f"Q: {match.get('question', '')}\nA: {match.get('answer', '')}")
                    paper_blocks.append({
                        "block_type": 2,
                        "text": {
                            "elements": [
                                {"text_run": {"content": "\n".join(qa_lines) + "\n"}}
                            ]
                        }
                    })

                # Baseline analysis and bi-directional linking
                if getattr(p, "baselines", None):
                    bl_elements: list[dict[str, Any]] = [
                        {"text_run": {"content": "核心对比基线 (Baselines):\n"}}
                    ]
                    for b in p.baselines:
                        name = b.get("name", "")
                        venue = b.get("venue", "")
                        venue_part = f" [{venue}]" if venue else ""
                        summary = b.get("method_summary", "")
                        comp = b.get("comparison", "")
                        b_doc_url = b.get("library_url", "")
                        b_doc_title = b.get("library_title", "")
                        in_lib = b.get("in_library", False)

                        bl_elements.append({
                            "text_run": {
                                "content": f"• {name}{venue_part}: ",
                                "text_element_style": {"bold": True}
                            }
                        })
                        bl_elements.append({
                            "text_run": {
                                "content": f"{summary}\n  📊 对比: {comp}\n  "
                            }
                        })
                        if in_lib and b_doc_url:
                            badge_lbl = b.get("library_badge", "🟢 [已入库笔记: ")
                            prefix = (badge_lbl.split(":")[0] + ": ") if ":" in badge_lbl else "🟢 [已入库笔记: "
                            bl_elements.append({"text_run": {"content": prefix}})
                            bl_elements.append({
                                "text_run": {
                                    "content": f"{b_doc_title or name}",
                                    "text_element_style": {"link": {"url": b_doc_url}}
                                }
                            })
                            bl_elements.append({"text_run": {"content": "]\n"}})
                        elif b_doc_url:
                            bl_elements.append({"text_run": {"content": "⚪ [未入库: "}})
                            bl_elements.append({
                                "text_run": {
                                    "content": "出处检索",
                                    "text_element_style": {"link": {"url": b_doc_url}}
                                }
                            })
                            bl_elements.append({"text_run": {"content": "]\n"}})
                        else:
                            bl_elements.append({"text_run": {"content": "⚪ [未入库]\n"}})

                        # Bi-directional backlink to the matched in-library document
                        if in_lib and b.get("obj_token") and comp:
                            self.append_baseline_backlink(
                                b["obj_token"],
                                referring_paper_title=p.title,
                                referring_paper_url=p.url or "",
                                comparison=comp,
                            )

                    paper_blocks.append({
                        "block_type": 2,
                        "text": {
                            "elements": bl_elements
                        }
                    })

        if paper_blocks:
            if briefs_header_id and briefs_header_id in root_children:
                ins_idx = root_children.index(briefs_header_id)
            elif trending_header_id and trending_header_id in root_children:
                ins_idx = root_children.index(trending_header_id)
            else:
                ins_idx = -1
            logger.info(f"Writing {len(paper_blocks)} paper blocks to document {doc_id} at index {ins_idx}...")
            insert_blocks(paper_blocks, ins_idx)
            root_children = self._get_root_children(doc_id)

        # 4. Research question briefs (cleanly replace existing briefs if updated)
        has_briefs = bool(question_briefs)
        if has_briefs:
            from datetime import date

            if old_brief_block_ids:
                logger.info(f"Replacing {len(old_brief_block_ids)} existing question brief blocks in document {doc_id}...")
                self.delete_document_blocks(doc_id, old_brief_block_ids)
                root_children = self._get_root_children(doc_id)

            brief_blocks: list[dict[str, Any]] = [{
                "block_type": 4,
                "heading2": {
                    "elements": [
                        {"text_run": {"content": f"二、今日问题进展（{date.today().isoformat()}）"}}
                    ]
                }
            }]
            for brief in question_briefs:
                q_title = str(brief.get("question") or "").strip()
                brief_blocks.append({
                    "block_type": 5,
                    "heading3": {
                        "elements": [{"text_run": {"content": q_title}}]
                    }
                })
                body = brief.get("summary", "")
                evidence = brief.get("evidence") or []
                if evidence:
                    body += "\n正向证据: " + "；".join(
                        f"{e.get('title', '')} ({e.get('url', '')})" for e in evidence[:4]
                    )
                counter_ev = brief.get("counter_evidence") or []
                if counter_ev:
                    body += "\n反例/局限证据: " + "；".join(
                        f"{c.get('title', '')} ({c.get('url', '')})" for c in counter_ev[:3]
                    )
                if brief.get("gap"):
                    body += f"\n仍待解决: {brief['gap']}"
                brief_blocks.append({
                    "block_type": 2,
                    "text": {"elements": [{"text_run": {"content": body + "\n"}}]}
                })

            if trending_header_id and trending_header_id in root_children:
                b_ins_idx = root_children.index(trending_header_id)
            else:
                b_ins_idx = -1
            logger.info(f"Writing {len(brief_blocks)} question brief blocks to document {doc_id} at index {b_ins_idx}...")
            insert_blocks(brief_blocks, b_ins_idx)
            root_children = self._get_root_children(doc_id)

        # 5. Filter and append AI Dynamics & GitHub Trending items
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
                trend_blocks: list[dict[str, Any]] = []
                if not trending_header_id:
                    trends_no = "三" if (has_briefs or briefs_header_id) else "二"
                    trend_blocks.append({
                        "block_type": 4,
                        "heading2": {
                            "elements": [
                                {"text_run": {"content": f"{trends_no}、AI 动态与 GitHub 热点"}}
                            ]
                        }
                    })

                for item in trends_to_add:
                    existing_card_count += 1
                    tags_str = " ".join(f"[#{t}]" for t in (item.tags or ["Hot"]))
                    stars_str = f" (⭐ {item.stars:,})" if item.stars else ""

                    # Heading 3: [#Agent] vllm-project/vllm (⭐ 28,400)
                    trend_blocks.append({
                        "block_type": 5,
                        "heading3": {
                            "elements": [
                                {"text_run": {"content": f"{tags_str} {item.title}{stars_str}"}}
                            ]
                        }
                    })

                    # Todo 1: Confirm ingest
                    trend_blocks.append({
                        "block_type": 17,
                        "todo": {
                            "style": {"done": False},
                            "elements": [{"text_run": {"content": "确认入库"}}]
                        }
                    })
                    # Todo 2: Discard
                    trend_blocks.append({
                        "block_type": 17,
                        "todo": {
                            "style": {"done": False},
                            "elements": [{"text_run": {"content": "移出待选"}}]
                        }
                    })

                    # Meta: 来源: ... | 原文链接: ...
                    trend_blocks.append({
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

                    trend_blocks.append({
                        "block_type": 2,
                        "text": {
                            "elements": [
                                {"text_run": {"content": f"{tldr_text}\n"}}
                            ]
                        }
                    })

                logger.info(f"Writing {len(trend_blocks)} trending blocks to document {doc_id}...")
                insert_blocks(trend_blocks, -1)

        doc_url = doc_url or f"https://feishu.cn/docx/{doc_id}"
        logger.info(f"Feishu daily report updated successfully: {doc_url}")
        return doc_url


    def fetch_console_settings(self, node_token: str) -> dict[str, list[str]]:
        """Reads tracked tags and questions from the Feishu recommendation console document."""
        from ..library.console import feishu_blocks_to_text, parse_console_text

        obj_token, _ = self.get_obj_token_from_node_token(str(node_token))
        if not obj_token:
            return {"tags": [], "questions": []}
        return parse_console_text(feishu_blocks_to_text(self.get_document_blocks(obj_token)))

    def append_suggested_questions(self, node_token: str, questions: list[str]) -> None:
        """Appends LLM-proposed follow-up questions to the console for human approval."""
        if self.dry_run or not questions:
            return
        obj_token, _ = self.get_obj_token_from_node_token(str(node_token))
        if not obj_token:
            return

        blocks = self.get_document_blocks(obj_token)
        known = set()
        for block in blocks:
            if block.get("block_type") == 12:
                known.add(
                    "".join(
                        el.get("text_run", {}).get("content", "")
                        for el in block.get("bullet", {}).get("elements", [])
                    ).strip()
                )

        fresh = [q for q in questions if q.strip() and q.strip() not in known]
        if not fresh:
            return

        has_heading = any(
            "建议问题" in "".join(
                el.get("text_run", {}).get("content", "")
                for el in block.get("heading2", {}).get("elements", [])
            )
            for block in blocks
            if block.get("block_type") == 4
        )

        children: list[dict[str, Any]] = []
        if not has_heading:
            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [{"text_run": {"content": "建议问题（待确认）"}}]
                }
            })
        for question in fresh:
            children.append({
                "block_type": 12,
                "bullet": {"elements": [{"text_run": {"content": question}}]},
            })

        self._call_api(
            "POST",
            f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
            data={"children": children, "index": -1},
        )
        logger.info(f"Appended {len(fresh)} suggested questions to the console")

    def sync_user_preferences(
        self,
        node_token: str,
        preferences: dict[str, list[dict[str, Any]]],
    ) -> None:
        """Appends or updates learned user preferences in the Feishu console document for human visibility."""
        if self.dry_run or not preferences:
            return
        obj_token, _ = self.get_obj_token_from_node_token(str(node_token))
        if not obj_token:
            return

        blocks = self.get_document_blocks(obj_token)
        known = set()
        for block in blocks:
            if block.get("block_type") == 12:
                known.add(
                    "".join(
                        el.get("text_run", {}).get("content", "")
                        for el in block.get("bullet", {}).get("elements", [])
                    ).strip()
                )

        pos_items = preferences.get("positive") or []
        neg_items = preferences.get("negative") or []

        bullets_to_add: list[tuple[str, str, int]] = []
        for p in pos_items[:10]:
            r = str(p.get("reason") or "").strip()
            if r and not any(r in k for k in known):
                bullets_to_add.append(("👍 偏好特征: ", r, 4))  # green
        for n in neg_items[:10]:
            r = str(n.get("reason") or "").strip()
            if r and not any(r in k for k in known):
                bullets_to_add.append(("👎 排除特征: ", r, 2))  # orange

        if not bullets_to_add:
            return

        has_heading = any(
            "用户偏好记忆" in "".join(
                el.get("text_run", {}).get("content", "")
                for el in block.get("heading2", {}).get("elements", [])
            )
            for block in blocks
            if block.get("block_type") == 4
        )

        children: list[dict[str, Any]] = []
        if not has_heading:
            children.append({
                "block_type": 4,
                "heading2": {
                    "elements": [{"text_run": {"content": "用户偏好记忆库 (AI 学习偏好)"}}]
                }
            })
        for label, reason, color in bullets_to_add:
            children.append({
                "block_type": 12,
                "bullet": {
                    "elements": [
                        {"text_run": {"content": label, "text_element_style": {"bold": True, "text_color": color}}},
                        {"text_run": {"content": reason}},
                    ]
                },
            })

        self._call_api(
            "POST",
            f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
            data={"children": children, "index": -1},
        )
        logger.info(f"Appended {len(bullets_to_add)} user preference cues to Feishu console")

    def append_baseline_backlink(
        self,
        obj_token: str,
        referring_paper_title: str,
        referring_paper_url: str,
        comparison: str,
    ) -> bool:
        """Appends a backlink note to an existing library document when cited as a baseline."""
        if self.dry_run or not obj_token:
            return False

        try:
            blocks = self.get_document_blocks(obj_token)
            clean_ref_title = referring_paper_title.strip()
            # Avoid duplicate backlink insertions
            for b in blocks:
                for el in (b.get("text", {}) or {}).get("elements", []):
                    c = el.get("text_run", {}).get("content", "")
                    if clean_ref_title[:35] in c:
                        logger.debug(f"Backlink already present in doc {obj_token} for '{clean_ref_title[:30]}'")
                        return False

            from datetime import date
            today_str = date.today().isoformat()

            children: list[dict[str, Any]] = [
                {
                    "block_type": 2,
                    "text": {
                        "elements": [
                            {"text_run": {"content": f"📌 后续文献对比追踪 ({today_str}):\n", "text_element_style": {"bold": True}}},
                            {"text_run": {"content": "新论文: "}},
                            {"text_run": {"content": f"《{referring_paper_title}》", "text_element_style": {"link": {"url": referring_paper_url or ""}}}},
                            {"text_run": {"content": f"\n对比评价: {comparison}\n"}},
                        ]
                    }
                }
            ]

            self._call_api(
                "POST",
                f"/docx/v1/documents/{obj_token}/blocks/{obj_token}/children",
                data={"children": children, "index": -1},
            )
            logger.info(f"Appended baseline backlink to doc {obj_token} from '{clean_ref_title[:30]}'")
            return True
        except Exception as exc:
            logger.warning(f"Failed to append baseline backlink to {obj_token}: {exc}")
            return False

    def fetch_reading_notes(self) -> list[CorpusPaper]:
        """Fetches reading notes from Wiki space or Drive folder to use as interest corpus."""
        if self.dry_run:
            return []

        corpus: list[CorpusPaper] = []
        if self.wiki_space_id and self.notes_parent_node_token:
            try:
                items: list[dict[str, Any]] = []
                page_token = None
                while True:
                    params: dict[str, Any] = {"parent_node_token": str(self.notes_parent_node_token), "page_size": 50}
                    if page_token:
                        params["page_token"] = page_token
                    res = self._call_api("GET", f"/wiki/v2/spaces/{self.wiki_space_id}/nodes", params=params)
                    items.extend(res.get("items", []))
                    if not res.get("has_more") or not res.get("page_token"):
                        break
                    page_token = res.get("page_token")

                for item in items:
                    title = item.get("title", "")
                    clean_title = re.sub(r"^📄\s*\[精读\]\s*", "", title).strip()
                    tags = re.findall(r"\[#([^\]]+)\]", title)
                    for tag in tags:
                        self.reading_note_tags.setdefault(tag.strip(), []).append(clean_title)
                    tag_note = f" Tags: {', '.join(tags)}." if tags else ""
                    node_tok = item.get("node_token")
                    obj_tok = item.get("obj_token")
                    wiki_url = item.get("url") or (f"https://feishu.cn/wiki/{node_tok}" if node_tok else None)
                    edit_ts = item.get("obj_edit_time") or item.get("obj_create_time")
                    added_dt = datetime.fromtimestamp(int(edit_ts)) if str(edit_ts or "").isdigit() else datetime.now()
                    corpus.append(
                        CorpusPaper(
                            title=clean_title,
                            abstract=f"User curated deep reading note: {clean_title}.{tag_note}",
                            added_date=added_dt,
                            paths=[f"wiki/notes/{clean_title}"],
                            url=wiki_url,
                            node_token=node_tok,
                            obj_token=obj_tok,
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
                    f_tok = f.get("token")
                    d_url = f.get("url") or (f"https://feishu.cn/docs/{f_tok}" if f_tok else None)
                    corpus.append(
                        CorpusPaper(
                            title=name,
                            abstract=f"User curated reading note: {name}",
                            added_date=datetime.now(),
                            paths=[f"drive/notes/{name}"],
                            url=d_url,
                            obj_token=f_tok,
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

            # Ensure each deletion range does not exceed Feishu's 50-block batch limit
            safe_ranges = []
            for chunk in chunks:
                for sub_i in range(0, len(chunk), 50):
                    sub = chunk[sub_i : sub_i + 50]
                    safe_ranges.append((sub[0], sub[-1] + 1))

            for start_idx, end_idx in reversed(safe_ranges):
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
                    or "Reading Notes" in raw_heading
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

                    user_reason = extract_user_reason(todo_text)
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
                        "user_reason": user_reason,
                        "card_block_ids": card_block_ids,
                    })
        return checked_papers

    def resolve_document_ai_queries(self, document_id: str, router: Any) -> int:
        """Scans a Feishu document for unanswered '@AI:' or '@paper-bot' queries and writes answers in-place."""
        if self.dry_run or not document_id or not getattr(router, "available", False):
            return 0

        from ..core.annotator import resolve_inline_ai_followups

        try:
            root_res = self._call_api("GET", f"/docx/v1/documents/{document_id}/blocks/{document_id}")
            root_children = root_res.get("block", {}).get("children", [])
            items = self.get_document_blocks(document_id)
        except Exception as exc:
            logger.debug(f"Could not read document {document_id} for @AI queries: {exc}")
            return 0

        last_title = ""
        last_url = ""
        last_abstract = ""
        answered_count = 0

        # Collect existing texts to check if already answered
        all_texts = [
            "".join(el.get("text_run", {}).get("content", "") for el in b.get("text", {}).get("elements", []))
            for b in items if b.get("block_type") == 2
        ]

        for item in items:
            b_type = item.get("block_type")
            b_id = item.get("block_id", "")
            if b_type in (4, 5):
                h_key = "heading2" if b_type == 4 else "heading3"
                raw_h = "".join(el.get("text_run", {}).get("content", "") for el in item.get(h_key, {}).get("elements", [])).strip()
                if not re.match(r"^[一二三四五六七八九十]+、", raw_h):
                    last_title = re.sub(r"^\d+\.\s*", "", raw_h).strip()
                    last_url = ""
                    last_abstract = ""
            elif b_type == 2:
                txt = "".join(el.get("text_run", {}).get("content", "") for el in item.get("text", {}).get("elements", [])).strip()
                if "原文链接:" in txt or "原文/开源主页:" in txt:
                    m = re.search(r"https?://\S+", txt)
                    if m:
                        last_url = m.group(0).rstrip(" \n\r")
                elif "英文摘要" in txt or "论文正文研读" in txt or "TL;DR:" in txt:
                    last_abstract += txt + "\n"

                # Check for @AI: or @paper-bot query
                q_match = re.search(r"(?:@AI|@paper-bot)\s*[:：]?\s*(.+)", txt, re.IGNORECASE)
                if q_match and "🤖 [AI 追问解答" not in txt:
                    query_str = q_match.group(1).strip()
                    if not query_str or any(f"Q: {query_str[:25]}" in t for t in all_texts):
                        continue

                    qa_pairs = resolve_inline_ai_followups(
                        router=router,
                        title=last_title or "Paper",
                        abstract=last_abstract[:2500],
                        arxiv_id_or_url=last_url,
                        user_queries=[query_str],
                    )
                    if qa_pairs:
                        ans_text = qa_pairs[0]["answer"]
                        insert_idx = (root_children.index(b_id) + 1) if b_id in root_children else -1
                        reply_block = {
                            "block_type": 2,
                            "text": {
                                "elements": [
                                    {
                                        "text_run": {
                                            "content": f"🤖 [AI 追问解答 | Q: {query_str}]\n",
                                            "text_element_style": {"bold": True, "text_color": 5, "background_color": 4},
                                        }
                                    },
                                    {
                                        "text_run": {
                                            "content": f"💡 {ans_text}\n",
                                            "text_element_style": {"italic": True},
                                        }
                                    },
                                ]
                            },
                        }
                        try:
                            self._call_api(
                                "POST",
                                f"/docx/v1/documents/{document_id}/blocks/{document_id}/children",
                                data={"children": [reply_block], "index": insert_idx},
                            )
                            answered_count += 1
                            logger.info(f"Resolved inline @AI query in {document_id}: '{query_str[:30]}'")
                        except Exception as w_exc:
                            logger.warning(f"Failed to write @AI answer to {document_id}: {w_exc}")

        return answered_count

    def resolve_wiki_ai_queries(self, router: Any) -> int:
        """Scans candidate document and recent reading notes in Wiki for '@AI:' inline questions."""
        if not self.wiki_space_id or self.dry_run or not getattr(router, "available", False):
            return 0

        doc_ids: list[str] = []
        for parent_tok in [self.daily_parent_node_token, self.notes_parent_node_token]:
            if parent_tok:
                try:
                    res = self._call_api(
                        "GET",
                        f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                        params={"parent_node_token": str(parent_tok), "page_size": 15},
                    )
                    for r in res.get("items", []):
                        obj = r.get("obj_token")
                        if obj and obj not in doc_ids:
                            doc_ids.append(obj)
                except Exception:
                    pass

        total_answered = 0
        for d_id in doc_ids[:10]:
            total_answered += self.resolve_document_ai_queries(d_id, router)
        return total_answered

    def fetch_checked_papers(self, document_id: str) -> list[str]:
        """Scans document blocks for todo items marked as done (backwards-compatible heading list)."""
        details = self.fetch_checked_paper_details(document_id)
        return [d["raw_heading"] for d in details]

    def fetch_checked_papers_from_wiki(self) -> list[dict[str, Any]]:
        """Discovers checked papers across daily reports in the Wiki space."""
        if not self.wiki_space_id or self.dry_run:
            return []

        all_checked: list[dict[str, Any]] = []
        doc_ids: list[str] = []
        try:
            if self.daily_parent_node_token:
                try:
                    res = self._call_api(
                        "GET",
                        f"/wiki/v2/spaces/{self.wiki_space_id}/nodes",
                        params={"parent_node_token": str(self.daily_parent_node_token)}
                    )
                    reports = res.get("items", [])
                    doc_ids.extend([r.get("obj_token") for r in reports if r.get("obj_token")])
                except Exception as exc:
                    logger.debug(f"Notice listing daily_parent_node_token: {exc}")

            for doc_id in doc_ids:
                checked = self.fetch_checked_paper_details(doc_id)
                all_checked.extend(checked)
        except Exception as exc:
            logger.warning(f"Failed to scan daily reports in Wiki: {exc}")
        return all_checked

    def create_reading_note(
        self,
        paper: Paper,
        sections: Optional[dict[str, Any]] = None,
        status: str = READING_STATUS_TODO,
        full_text_markdown: Optional[str] = None,
        existing_doc_id: Optional[str] = None,
        existing_node_token: Optional[str] = None,
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
        old_children_to_clean: list[str] = []
        commented_block_ids: set[str] = set()

        is_app_note = bool(
            sections.get("scenarios_and_triggers")
            or sections.get("quick_start")
            or sections.get("usage_examples")
            or ("github.com" in (paper.url or "").lower())
        )

        if existing_doc_id:
            doc_id = existing_doc_id
            if existing_node_token:
                note_url = f"https://feishu.cn/wiki/{existing_node_token}"
            else:
                note_url = f"https://feishu.cn/docx/{doc_id}"
            try:
                root_res = self._call_api("GET", f"/docx/v1/documents/{doc_id}/blocks/{doc_id}")
                old_children_to_clean = root_res.get("block", {}).get("children", [])
                for blk in self.get_document_blocks(doc_id):
                    if blk.get("comment_ids"):
                        commented_block_ids.add(blk.get("block_id"))
            except Exception as scan_err:
                logger.warning(f"Failed to scan existing doc blocks for cleanup: {scan_err}")
        elif self.wiki_space_id:
            parent_token = (
                self.engineering_parent_node_token
                if (is_app_note and self.engineering_parent_node_token)
                else (self.notes_parent_node_token or "")
            )
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

        # If updating an existing document, clean up old blocks that don't have user comments
        if old_children_to_clean:
            blocks_to_delete = [cid for cid in old_children_to_clean if cid not in commented_block_ids]
            if blocks_to_delete:
                logger.info(f"Cleaning up {len(blocks_to_delete)} old blocks from {doc_id} (preserving {len(commented_block_ids)} commented blocks)")
                self.delete_document_blocks(doc_id, blocks_to_delete)

        # Build reading note as native Markdown (with standard Feishu XML callouts & checkboxes)
        note_markdown = self._build_reading_note_markdown(
            paper=paper,
            sections=sections,
            current_status=current_status,
            today=today,
            is_app_note=is_app_note,
            full_text_markdown=full_text_markdown,
        )

        if not self.dry_run:
            # Chunk markdown into safe sections (~6000 chars, max 2 images per chunk) to prevent server timeout
            chunks = _split_markdown_chunks(note_markdown, max_chunk_chars=6000, max_images_per_chunk=2)
            for chunk_idx, chunk in enumerate(chunks):
                if not chunk.strip():
                    continue
                for attempt in range(3):
                    try:
                        self._call_api(
                            "PUT",
                            f"/docs_ai/v1/documents/{doc_id}",
                            data={
                                "block_id": "-1",
                                "command": "block_insert_after",
                                "content": chunk,
                                "format": "markdown",
                                "revision_id": -1,
                            }
                        )
                        break
                    except Exception as chunk_err:
                        if attempt < 2:
                            logger.warning(f"Retrying chunk {chunk_idx+1}/{len(chunks)} after error: {chunk_err}")
                            time.sleep(2 * (attempt + 1))
                        else:
                            raise chunk_err

            # Tight-crop images to correct visual boundaries and update dimensions
            try:
                self.optimize_document_images(doc_id, note_markdown)
            except Exception as opt_err:
                logger.warning(f"Image optimization warning for {doc_id}: {opt_err}")

        logger.info(f"Published reading note successfully: {note_url}")
        return note_url

    def _build_reading_note_markdown(
        self,
        paper: Paper,
        sections: dict[str, Any],
        current_status: str,
        today: str,
        is_app_note: bool,
        full_text_markdown: Optional[str] = None,
    ) -> str:
        """Builds complete reading note in native Markdown with Feishu XML extensions."""
        src_str = ", ".join(paper.sources or [paper.source])
        affil_str = ", ".join(paper.affiliations) if paper.affiliations else "N/A"
        date_str = paper.published_date.strftime("%Y-%m-%d") if paper.published_date else today
        venue_str = getattr(paper, "venue", None) or "Preprint"

        parts: list[str] = []

        if is_app_note:
            overview = sections.get("overview") or sections.get("core_summary") or paper.tldr_zh or paper.tldr or paper.abstract[:200]
            scenarios = sections.get("scenarios_and_triggers") or "适用于自主智能体工作流执行、工具调用与开发环境自动化。"
            quick_start = sections.get("quick_start") or f"1. 获取项目: git clone {paper.url or 'N/A'}\n2. 配置前置依赖与必要环境变量。"
            usage_examples = sections.get("usage_examples") or f"# 详细使用与调用示例请参阅仓库主页:\n# {paper.url or 'N/A'}"
            tips = sections.get("key_features_and_tips") or "1. 遵循工具入参调用规范。\n2. 注意运行环境版本兼容性。"

            parts.append(f"""<callout emoji="🏷️" background-color="light-gray">
<p>🏷️ <b>阅读状态</b>: {current_status}  {READING_STATUS_BAR}<br/>
<b>项目类型</b>: AI 应用 / 开源项目 / Agent Skill<br/>
<b>来源</b>: [{src_str}] | <b>项目主页</b>: <a href="{paper.url or ''}">{paper.url or 'N/A'}</a><br/>
<b>收录日期</b>: {date_str}</p>
</callout>""")

            parts.append(_build_annotation_workspace_markdown(sections, is_app_note=True))

            parts.append(f"""## 一、项目定位与核心功能

{overview}

## 二、适用场景与触发时机 (When to Use / Triggers)

{scenarios}

## 三、环境依赖与快速上手 (Installation & Setup)

{quick_start}

## 四、具体使用方式与调用示例 (Usage & Examples)

{usage_examples}

## 五、核心配置与注意事项 (Configuration & Tips)

{tips}""")
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

            parts.append(f"""<callout emoji="📄" background-color="light-gray">
<p>🏷️ <b>阅读状态</b>: {current_status}  {READING_STATUS_BAR}<br/>
<b>来源</b>: [{src_str}] | <b>发表时间</b>: {date_str} | <b>评级/会议</b>: {venue_str}<br/>
<b>发表单位/实验室</b>: {affil_str}<br/>
<b>原文直达</b>: <a href="{paper.url or ''}">{paper.url or 'N/A'}</a></p>
</callout>""")

            parts.append(_build_annotation_workspace_markdown(sections, is_app_note=False))

            hero_img_md = ""
            first_img_match = re.search(r"!\[(.*?)\]\((.*?)\)", full_text_markdown or "")
            if first_img_match:
                hero_cap = first_img_match.group(1).strip() or "Figure 1: 核心系统架构与工作流设计"
                hero_src = first_img_match.group(2).strip()
                hero_img_md = f"\n\n![{hero_cap}]({hero_src})\n*{hero_cap}*\n"

            parts.append(f"""## 一、核心一句话总结

{core_summary}

## 二、研究动机与问题背景

{motivation}

## 三、核心架构与机制设计

{method}{hero_img_md}

## 四、关键实验与结论

{experiments}

## 五、落地启示与思考

{takeaways}""")

            reserved_keys = {
                "core_summary",
                "motivation",
                "method",
                "experiments",
                "takeaways",
                "overview",
                "scenarios_and_triggers",
                "quick_start",
                "usage_examples",
                "key_features_and_tips",
            }
            for custom_key, custom_val in (sections or {}).items():
                if custom_key not in reserved_keys and isinstance(custom_val, str) and custom_val.strip():
                    parts.append(f"## {custom_key}\n\n{custom_val.strip()}")

            anns = getattr(paper, "inline_annotations", None) or []
            if anns:
                ann_lines = ["## 细节批注与审稿核查", ""]
                for ann in anns:
                    q_str = str(ann.get("quote") or ann.get("exact_quote") or "").strip()
                    c_str = str(ann.get("comment") or "").strip()
                    t_str = str(ann.get("type") or "claim").strip()
                    if q_str:
                        ann_lines.append(f"- **「{q_str}」** (`{t_str}`)：{c_str}")
                parts.append("\n".join(ann_lines))

        if full_text_markdown and full_text_markdown.strip():
            parts.append("""---

## 📄 论文完整原文与逐节研读区 (Original Full Paper & In-line Annotation)

> 💡 **提示**：您可以直接在下方论文原文中划词选中任意语句或段落，点击「划词评论 / 添加批注」，直接在原文对应位置记录您的研读想法与疑问。
""")
            cleaned_full_text = clean_paper_markdown(full_text_markdown)
            parts.append(cleaned_full_text)

        return "\n\n".join(parts)

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

        tag_list = [t for t in (tags or getattr(paper, "tags", None) or ["Research"]) if t]
        tags_str = " ".join(f"[#{p}]" for p in tag_list)
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
                        {"text_run": {"content": f"• {tags_str} {full_title}"}}
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

    def append_to_engineering_index(
        self,
        paper: Paper,
        note_url: str,
        tags: Optional[list[str]] = None,
        core_summary: str = "",
        status: str = READING_STATUS_TODO,
    ) -> None:
        """Appends a new engineering asset (Skill / GitHub Repo / AI App) entry to the Engineering Hub index document."""
        if not self.engineering_parent_node_token or self.dry_run:
            return

        eng_doc_id = None
        try:
            node_info = self._call_api("GET", f"/wiki/v2/spaces/get_node", params={"token": str(self.engineering_parent_node_token)})
            node = node_info.get("node", {})
            eng_doc_id = node.get("obj_token")
        except Exception:
            eng_doc_id = str(self.engineering_parent_node_token)

        if not eng_doc_id:
            logger.warning(f"Could not resolve document ID for engineering parent node {self.engineering_parent_node_token}")
            return

        try:
            blocks_res = self._call_api("GET", f"/docx/v1/documents/{eng_doc_id}/blocks")
            blocks = blocks_res.get("items", [])
            heading3_count = sum(1 for b in blocks if b.get("block_type") == 5)
            next_idx = heading3_count + 1
        except Exception:
            next_idx = 1

        tag_list = tags or ["Engineering", "GitHub"]
        tags_str = " ".join(f"[#{t}]" for t in tag_list)
        summary = core_summary or paper.tldr_zh or paper.tldr or (paper.abstract[:150] + "...")
        full_title = paper.title_with_venue()
        current_status = normalize_reading_status(status)

        index_blocks: list[dict[str, Any]] = [
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
                        {"text_run": {"content": f"• 🏷️ 状态: {current_status}  {READING_STATUS_BAR}\n"}},
                        {"text_run": {"content": f"• 仓库/项目地址: {paper.url or 'N/A'}\n"}},
                        {"text_run": {"content": f"• 🛠️ 工程笔记直达: {note_url}\n"}},
                        {"text_run": {"content": f"• 核心功能与亮点: {summary}\n"}},
                    ]
                }
            }
        ]

        try:
            self._call_api(
                "POST",
                f"/docx/v1/documents/{eng_doc_id}/blocks/{eng_doc_id}/children",
                data={"children": index_blocks, "index": -1}
            )
            logger.info(f"Appended engineering asset '{paper.title}' to Feishu Wiki engineering index document")
        except Exception as exc:
            logger.error(f"Failed to append to engineering index: {exc}")

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

        tag_list = [t for t in (tags or getattr(paper, "tags", None) or ["Research"]) if t]
        tags_str = " ".join(f"[#{p}]" for p in tag_list)
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
