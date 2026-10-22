"""Reading the recommendation console from whichever ecosystem the user already uses.

Every provider is reduced to the same markdown shape before parsing:

    ## 关注标签
    - Memory

    ## 关注问题
    - 现有长时记忆系统如何避免记忆漂移？
"""

import re
from typing import Any

import requests
from loguru import logger

NOTION_VERSION = "2022-06-28"

_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")


def parse_console_text(text: str) -> dict[str, list[str]]:
    """Parses markdown-ish console text into tags and questions."""
    settings: dict[str, list[str]] = {"tags": [], "questions": []}
    section = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if "标签" in heading:
                section = "tags"
            elif "问题" in heading or "QA" in heading.upper():
                section = "questions"
            else:
                section = None
            continue
        if not section:
            continue
        match = _ITEM_RE.match(line)
        if not match:
            continue
        item = match.group(1).strip()
        if item and item not in settings[section]:
            settings[section].append(item)

    return settings


def feishu_blocks_to_text(blocks: list[dict[str, Any]]) -> str:
    """Flattens Feishu docx blocks into markdown lines."""
    lines: list[str] = []
    for block in blocks:
        b_type = block.get("block_type")
        if b_type in (3, 4, 5, 6, 7):
            level = {3: 2, 4: 2, 5: 3, 6: 4, 7: 5}[b_type]
            key = {3: "heading1", 4: "heading2", 5: "heading3", 6: "heading4", 7: "heading5"}[b_type]
            text = "".join(
                el.get("text_run", {}).get("content", "") for el in block.get(key, {}).get("elements", [])
            )
            lines.append("#" * level + " " + text)
        elif b_type in (12, 13):
            key = "bullet" if b_type == 12 else "ordered"
            text = "".join(
                el.get("text_run", {}).get("content", "") for el in block.get(key, {}).get("elements", [])
            )
            lines.append("- " + text)
        elif b_type == 2:
            text = "".join(
                el.get("text_run", {}).get("content", "") for el in block.get("text", {}).get("elements", [])
            )
            lines.append(text)
    return "\n".join(lines)


def _html_to_text(html: str) -> str:
    text = re.sub(r"<br\s*/?>|</p>|</div>|</li>", "\n", html or "", flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\n{3,}", "\n\n", text)


def _notion_rich_text(items: list[dict[str, Any]]) -> str:
    return "".join(part.get("plain_text", "") for part in items or [])


def _notion_page_text(token: str, page_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
    }
    lines: list[str] = []
    cursor = None
    while True:
        params = {"page_size": 100}
        if cursor:
            params["start_cursor"] = cursor
        resp = requests.get(
            f"https://api.notion.com/v1/blocks/{page_id}/children",
            headers=headers,
            params=params,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Notion page read failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()

        for block in data.get("results", []):
            b_type = block.get("type", "")
            payload = block.get(b_type, {})
            text = _notion_rich_text(payload.get("rich_text"))
            if b_type in ("heading_1", "heading_2", "heading_3"):
                level = {"heading_1": 2, "heading_2": 2, "heading_3": 3}[b_type]
                lines.append("#" * level + " " + text)
            elif b_type == "bulleted_list_item":
                lines.append("- " + text)
            elif b_type == "numbered_list_item":
                lines.append("- " + text)
            elif b_type == "paragraph":
                lines.append(text)

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return "\n".join(lines)


def _zotero_note_text(config: Any, note_key: str) -> str:
    import zotero as pyzotero

    zot = pyzotero.Zotero(config.user_id, "user", config.api_key)
    note = zot.item(note_key)
    return _html_to_text(note.get("data", {}).get("note", ""))


def load_console_settings(config: Any, feishu_client: Any = None) -> dict[str, list[str]]:
    """Reads tags and questions from the first configured console provider.

    Precedence: Feishu document, Obsidian note, Notion page, Zotero note, then
    the static lists in ``console.tags`` / ``console.questions``.
    """
    console_cfg = config.get("console")
    if not console_cfg or str(console_cfg.get("enabled", True)).lower() in ("false", "0", "no"):
        return {"tags": [], "questions": []}

    provider = str(console_cfg.get("provider", "auto")).lower()
    static = {
        "tags": [str(t) for t in (console_cfg.get("tags") or [])],
        "questions": [str(q) for q in (console_cfg.get("questions") or [])],
    }

    def enabled(name: str) -> bool:
        return provider in ("auto", name)

    if enabled("feishu") and console_cfg.get("node_token"):
        try:
            if feishu_client is None:
                from .feishu import FeishuClient

                feishu_client = FeishuClient(config.feishu)
            remote = feishu_client.fetch_console_settings(str(console_cfg.node_token))
            if remote.get("tags") or remote.get("questions"):
                return remote
        except Exception as exc:
            logger.warning(f"Could not read Feishu console: {exc}")

    obsidian_cfg = config.get("obsidian")
    if enabled("obsidian") and obsidian_cfg and obsidian_cfg.get("console_path") and obsidian_cfg.get("vault_path"):
        try:
            from pathlib import Path

            note = Path(str(obsidian_cfg.vault_path)).expanduser() / str(obsidian_cfg.console_path)
            return parse_console_text(note.read_text(encoding="utf-8", errors="ignore"))
        except Exception as exc:
            logger.warning(f"Could not read Obsidian console note: {exc}")

    notion_cfg = config.get("notion")
    if enabled("notion") and notion_cfg and notion_cfg.get("token") and notion_cfg.get("console_page_id"):
        try:
            return parse_console_text(_notion_page_text(str(notion_cfg.token), str(notion_cfg.console_page_id)))
        except Exception as exc:
            logger.warning(f"Could not read Notion console page: {exc}")

    zot_cfg = config.get("zotero")
    if enabled("zotero") and zot_cfg and zot_cfg.get("console_note_key") and zot_cfg.get("user_id") and zot_cfg.get("api_key"):
        try:
            return parse_console_text(_zotero_note_text(zot_cfg, str(zot_cfg.console_note_key)))
        except Exception as exc:
            logger.warning(f"Could not read Zotero console note: {exc}")

    return static
