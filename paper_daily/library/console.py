"""Reading and updating the recommendation console from whichever ecosystem the user already uses.

Every provider is reduced to the same markdown shape before parsing:

    ## 关注标签
    - Memory

    ## 关注问题
    - 现有长时记忆系统如何避免记忆漂移？

    ## 自定义规则 / 自定义 Skill
    - 重点核查实验消融表与算力开销

    ## 笔记模板 / 范例模板
    - 核心增量：一句话总结核心变量改动
    - 机制与公式：提炼模块流与关键公式
"""

import json
import os
from pathlib import Path
import re
from typing import Any

import requests
from loguru import logger

NOTION_VERSION = "2022-06-28"

_ITEM_RE = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")


def _expand_external_markdown_items(items: list[str], base_dir: Path | None = None) -> list[str]:
    """If an item points to a local .md/.txt file (e.g. a custom Skill or Template file), loads its lines."""
    expanded: list[str] = []
    root = base_dir or Path.cwd()
    for item in items:
        cleaned = item.strip().strip("`'\"")
        if cleaned.endswith((".md", ".txt")) and len(cleaned) < 240 and "\n" not in cleaned:
            cand = Path(cleaned).expanduser()
            if not cand.is_absolute():
                cand = root / cand
            if cand.is_file():
                try:
                    raw_content = cand.read_text(encoding="utf-8", errors="ignore").strip()
                    for line in raw_content.splitlines():
                        s = line.strip()
                        if not s or s.startswith("---"):
                            continue
                        m = _ITEM_RE.match(s)
                        val = m.group(1).strip() if m else s.lstrip("#").strip()
                        if val and val not in expanded:
                            expanded.append(val)
                    continue
                except OSError as exc:
                    logger.warning(f"Failed to read external skill/template file {cand}: {exc}")
        if item not in expanded:
            expanded.append(item)
    return expanded


def parse_console_text(text: str, base_dir: Path | None = None) -> dict[str, list[str]]:
    """Parses markdown-ish console text into tags, questions, institutions, excluded_keywords,
    required_anchors, custom_rules (custom skills), and note_template."""
    settings: dict[str, list[str]] = {
        "tags": [],
        "questions": [],
        "institutions": [],
        "excluded_keywords": [],
        "required_anchors": [],
        "custom_rules": [],
        "note_template": [],
    }
    section = None

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            heading = line.lstrip("#").strip()
            if "建议问题" in heading or "待确认" in heading:
                section = None
            elif any(k in heading for k in ["模板", "范例", "template", "example"]):
                section = "note_template"
            elif any(k in heading for k in ["屏蔽", "排除", "黑名单", "exclude", "block"]):
                section = "excluded_keywords"
            elif any(k in heading for k in ["必含", "核心锚点", "必须命中", "require", "anchor"]):
                section = "required_anchors"
            elif any(k in heading.lower() for k in ["自定义", "阅读规则", "审阅规则", "审稿", "skill", "custom rule", "rule"]):
                section = "custom_rules"
            elif "标签" in heading or "tag" in heading.lower():
                section = "tags"
            elif "问题" in heading or "qa" in heading.lower() or "question" in heading.lower():
                section = "questions"
            elif any(k in heading.lower() for k in ["机构", "实验室", "单位", "institution", "lab"]):
                section = "institutions"
            else:
                section = None
            continue
        if not section:
            continue
        match = _ITEM_RE.match(line)
        item = match.group(1).strip() if match else (line if section in ("custom_rules", "note_template") else "")
        if item and item not in settings[section]:
            settings[section].append(item)

    settings["custom_rules"] = _expand_external_markdown_items(settings["custom_rules"], base_dir=base_dir)
    settings["note_template"] = _expand_external_markdown_items(settings["note_template"], base_dir=base_dir)
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
    from pyzotero import zotero as pyzotero

    zot = pyzotero.Zotero(config.user_id, "user", config.api_key)
    note = zot.item(note_key)
    return _html_to_text(note.get("data", {}).get("note", ""))


def _apply_external_skill_and_template_files(settings: dict[str, list[str]], console_cfg: Any) -> dict[str, list[str]]:
    """Loads external skill_path and template_path files configured in console config."""
    if not console_cfg:
        return settings
    skill_path = console_cfg.get("skill_path")
    if skill_path:
        expanded = _expand_external_markdown_items([str(skill_path)])
        settings.setdefault("custom_rules", [])
        for r in expanded:
            if r not in settings["custom_rules"] and r != str(skill_path):
                settings["custom_rules"].append(r)

    template_path = console_cfg.get("template_path")
    if template_path:
        expanded = _expand_external_markdown_items([str(template_path)])
        settings.setdefault("note_template", [])
        for t in expanded:
            if t not in settings["note_template"] and t != str(template_path):
                settings["note_template"].append(t)
    return settings


def _apply_dispatch_payload(settings: dict[str, list[str]]) -> dict[str, list[str]]:
    """Merges dynamic parameters from external bot/cloud dispatch payload (Hermes/Grok/curl)."""
    dispatch_raw = os.environ.get("DISPATCH_PAYLOAD", "").strip()
    if not dispatch_raw:
        return settings

    try:
        payload = json.loads(dispatch_raw)
        if isinstance(payload, dict):
            for k in (
                "tags",
                "questions",
                "institutions",
                "excluded_keywords",
                "required_anchors",
                "custom_rules",
                "note_template",
            ):
                items = payload.get(k)
                if isinstance(items, list):
                    settings.setdefault(k, [])
                    for it in items:
                        s = str(it).strip()
                        if s and s not in settings[k]:
                            settings[k].append(s)
                elif isinstance(items, str) and items.strip():
                    settings.setdefault(k, [])
                    s = items.strip()
                    if s not in settings[k]:
                        settings[k].append(s)
    except Exception as exc:
        logger.debug(f"Could not parse DISPATCH_PAYLOAD: {exc}")
    return settings


def load_console_settings(config: Any, feishu_client: Any = None) -> dict[str, list[str]]:
    """Reads tags, questions, custom skills, and note templates from the first configured console provider.

    Precedence: Feishu document, Obsidian note, Notion page, Zotero note, then
    the static lists in ``console.tags`` / ``console.questions``.
    """
    console_cfg = config.get("console")
    if not console_cfg or str(console_cfg.get("enabled", True)).lower() in ("false", "0", "no"):
        return _apply_dispatch_payload({"tags": [], "questions": [], "custom_rules": [], "note_template": []})

    provider = str(console_cfg.get("provider", "auto")).lower()
    static: dict[str, list[str]] = {
        "tags": [str(t) for t in (console_cfg.get("tags") or [])],
        "questions": [str(q) for q in (console_cfg.get("questions") or [])],
        "institutions": [str(i) for i in (console_cfg.get("institutions") or [])],
        "excluded_keywords": [str(k) for k in (console_cfg.get("excluded_keywords") or [])],
        "required_anchors": [str(a) for a in (console_cfg.get("required_anchors") or [])],
        "custom_rules": [str(r) for r in (console_cfg.get("custom_rules") or [])],
        "note_template": [str(t) for t in (console_cfg.get("note_template") or [])],
    }

    def enabled(name: str) -> bool:
        return provider in ("auto", name)

    if enabled("feishu") and console_cfg.get("node_token"):
        try:
            if feishu_client is None:
                from ..channels.feishu import FeishuClient

                feishu_client = FeishuClient(config.get("feishu"))
            remote = feishu_client.fetch_console_settings(str(console_cfg.get("node_token")))
            if remote.get("tags") or remote.get("questions") or remote.get("custom_rules") or remote.get("note_template"):
                remote = _apply_external_skill_and_template_files(remote, console_cfg)
                return _apply_dispatch_payload(remote)
        except Exception as exc:
            logger.warning(f"Could not read Feishu console: {exc}")

    obsidian_cfg = config.get("obsidian")
    if enabled("obsidian") and obsidian_cfg and obsidian_cfg.get("console_path") and obsidian_cfg.get("vault_path"):
        try:
            vault_dir = Path(str(obsidian_cfg.get("vault_path"))).expanduser()
            note = vault_dir / str(obsidian_cfg.get("console_path"))
            parsed = parse_console_text(note.read_text(encoding="utf-8", errors="ignore"), base_dir=vault_dir)
            parsed = _apply_external_skill_and_template_files(parsed, console_cfg)
            return _apply_dispatch_payload(parsed)
        except Exception as exc:
            logger.warning(f"Could not read Obsidian console note: {exc}")

    notion_cfg = config.get("notion")
    if enabled("notion") and notion_cfg and notion_cfg.get("token") and notion_cfg.get("console_page_id"):
        try:
            parsed = parse_console_text(_notion_page_text(str(notion_cfg.get("token")), str(notion_cfg.get("console_page_id"))))
            parsed = _apply_external_skill_and_template_files(parsed, console_cfg)
            return _apply_dispatch_payload(parsed)
        except Exception as exc:
            logger.warning(f"Could not read Notion console page: {exc}")

    zot_cfg = config.get("zotero")
    if enabled("zotero") and zot_cfg and zot_cfg.get("console_note_key") and zot_cfg.get("user_id") and zot_cfg.get("api_key"):
        try:
            parsed = parse_console_text(_zotero_note_text(zot_cfg, str(zot_cfg.get("console_note_key"))))
            parsed = _apply_external_skill_and_template_files(parsed, console_cfg)
            return _apply_dispatch_payload(parsed)
        except Exception as exc:
            logger.warning(f"Could not read Zotero console note: {exc}")

    static = _apply_external_skill_and_template_files(static, console_cfg)
    return _apply_dispatch_payload(static)


def append_suggested_questions_to_console(
    config: Any,
    suggested_questions: list[str],
    feishu_client: Any = None,
) -> bool:
    """Writes suggested follow-up questions back to the user's configured console (Feishu, Obsidian, Notion, or Zotero)."""
    clean_questions = [str(q).strip() for q in (suggested_questions or []) if str(q).strip()]
    if not clean_questions:
        return False

    console_cfg = config.get("console") or {}
    provider = str(console_cfg.get("provider", "auto")).lower()

    def enabled(name: str) -> bool:
        return provider in ("auto", name)

    wrote_any = False

    # 1. Feishu Console
    if enabled("feishu") and console_cfg.get("node_token"):
        try:
            if feishu_client is None:
                from ..channels.feishu import FeishuClient

                feishu_client = FeishuClient(config.get("feishu"))
            feishu_client.append_suggested_questions(str(console_cfg.get("node_token")), clean_questions)
            wrote_any = True
        except Exception as exc:
            logger.warning(f"Could not write suggested questions to Feishu console: {exc}")

    # 2. Obsidian Console
    obsidian_cfg = config.get("obsidian") or {}
    if enabled("obsidian") and obsidian_cfg.get("vault_path") and obsidian_cfg.get("console_path"):
        try:
            note_path = Path(str(obsidian_cfg.get("vault_path"))).expanduser() / str(obsidian_cfg.get("console_path"))
            if note_path.is_file():
                existing_text = note_path.read_text(encoding="utf-8", errors="ignore")
                new_q = [q for q in clean_questions if q not in existing_text]
                if new_q:
                    section_header = "## 建议问题（待确认）"
                    bullet_lines = "\n".join(f"- {q}" for q in new_q)
                    if section_header in existing_text:
                        updated = existing_text.rstrip() + "\n" + bullet_lines + "\n"
                    else:
                        updated = existing_text.rstrip() + f"\n\n{section_header}\n{bullet_lines}\n"
                    note_path.write_text(updated, encoding="utf-8")
                    wrote_any = True
        except Exception as exc:
            logger.warning(f"Could not write suggested questions to Obsidian console: {exc}")

    # 3. Notion Console
    notion_cfg = config.get("notion") or {}
    if enabled("notion") and notion_cfg.get("token") and notion_cfg.get("console_page_id"):
        try:
            token = str(notion_cfg.get("token"))
            page_id = str(notion_cfg.get("console_page_id"))
            existing_text = _notion_page_text(token, page_id)
            new_q = [q for q in clean_questions if q not in existing_text]
            if new_q:
                children: list[dict[str, Any]] = []
                if "建议问题" not in existing_text:
                    children.append(
                        {
                            "object": "block",
                            "type": "heading_2",
                            "heading_2": {
                                "rich_text": [{"type": "text", "text": {"content": "建议问题（待确认）"}}]
                            },
                        }
                    )
                for q in new_q:
                    children.append(
                        {
                            "object": "block",
                            "type": "bulleted_list_item",
                            "bulleted_list_item": {
                                "rich_text": [{"type": "text", "text": {"content": q[:1900]}}]
                            },
                        }
                    )
                resp = requests.patch(
                    f"https://api.notion.com/v1/blocks/{page_id}/children",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Notion-Version": NOTION_VERSION,
                        "Content-Type": "application/json",
                    },
                    json={"children": children},
                    timeout=20,
                )
                if resp.status_code == 200:
                    wrote_any = True
        except Exception as exc:
            logger.warning(f"Could not write suggested questions to Notion console: {exc}")

    return wrote_any
