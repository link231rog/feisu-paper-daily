"""Direct literature library & annotation bridge (Feishu, Obsidian, Zotero, Notion).

Allows local AI agents and CLI users to directly inspect, search, and restore
user deep-reading annotations (highlighted quotes, user comments, section headings,
and full bilingual paragraph context) from whichever literature library the user uses.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
import re
from typing import Any
from urllib.parse import quote

import requests
from loguru import logger
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except ImportError:
    TfidfVectorizer = None  # type: ignore[assignment,misc]
    cosine_similarity = None  # type: ignore[assignment,misc]

from ..protocol import CorpusPaper

NOTION_VERSION = "2022-06-28"
DEFAULT_CACHE_PATH = "data/library_cache.json"

_DEFAULT_PLACEHOLDERS = (
    "可在研读后直接划词批注或记录关键洞察",
    "记录论文假设漏洞、对比缺陷或未解决的边界条件",
    "记录对自身研究/业务体系的迁移启发",
)


def _split_tags(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(t).strip() for t in raw if str(t).strip()]
    return [t.strip(" []'\"") for t in re.split(r"[,\s]+", str(raw)) if t.strip(" []'\"")]


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta: dict[str, str] = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            meta[key.strip().lower()] = value.strip().strip("'\"")
    return meta, text[end + 4 :]


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _is_placeholder(text: str) -> bool:
    cleaned = text.strip(" *()\n\t")
    return not cleaned or any(p in cleaned for p in _DEFAULT_PLACEHOLDERS)


# ---------------------------------------------------------------------------
# Existing corpus loaders (used by Executor during daily reranking)
# ---------------------------------------------------------------------------


def load_obsidian_corpus(vault_path: str, include_folders: list[str] | None = None) -> list[CorpusPaper]:
    """Builds a corpus from markdown notes in a local Obsidian vault."""
    root = Path(vault_path).expanduser()
    if not root.is_dir():
        logger.warning(f"Obsidian vault not found: {root}")
        return []

    allowed = [f.strip("/") for f in (include_folders or []) if str(f).strip()]
    corpus: list[CorpusPaper] = []
    for note in root.rglob("*.md"):
        if any(part.startswith(".") for part in note.relative_to(root).parts):
            continue
        rel = note.relative_to(root).as_posix()
        if allowed and not any(rel.startswith(folder + "/") or rel.startswith(folder) for folder in allowed):
            continue
        try:
            text = note.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        meta, body = _parse_frontmatter(text)
        heading = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
        title = meta.get("title") or (heading.group(1).strip() if heading else note.stem)
        tags = _split_tags(meta.get("tags")) or re.findall(r"(?:^|\s)#([\w\-/]+)", body)
        summary = re.sub(r"\s+", " ", body).strip()[:400]
        tag_note = f" Tags: {', '.join(tags)}." if tags else ""
        corpus.append(
            CorpusPaper(
                title=title,
                abstract=f"Obsidian note: {summary}.{tag_note}",
                added_date=datetime.fromtimestamp(note.stat().st_mtime),
                paths=[f"obsidian/{rel}"] + [f"obsidian/tags/{t}" for t in tags],
                url=f"obsidian://open?vault={quote(root.name)}&file={quote(rel)}",
            )
        )

    logger.info(f"Loaded {len(corpus)} notes from Obsidian vault {root}")
    return corpus


def load_notion_corpus(token: str, database_id: str) -> list[CorpusPaper]:
    """Builds a corpus from pages in a Notion database."""
    if not token or not database_id:
        return []

    corpus: list[CorpusPaper] = []
    cursor = None
    while True:
        payload: dict = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Notion query failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()

        for page in data.get("results", []):
            props = page.get("properties", {})
            title = ""
            tags: list[str] = []
            for prop in props.values():
                ptype = prop.get("type")
                if ptype == "title" and not title:
                    title = "".join(part.get("plain_text", "") for part in prop.get("title", []))
                elif ptype == "multi_select":
                    tags.extend(option.get("name", "") for option in prop.get("multi_select", []))
                elif ptype == "select" and prop.get("select"):
                    tags.append(prop["select"].get("name", ""))
            title = title.strip()
            if not title:
                continue
            tags = [t for t in tags if t]
            tag_note = f" Tags: {', '.join(tags)}." if tags else ""
            corpus.append(
                CorpusPaper(
                    title=title,
                    abstract=f"Notion page: {title}.{tag_note}",
                    added_date=datetime.now(),
                    paths=[f"notion/{page.get('id', '')}"] + [f"notion/tags/{t}" for t in tags],
                    url=page.get("url"),
                )
            )

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    logger.info(f"Loaded {len(corpus)} pages from Notion database")
    return corpus


# ---------------------------------------------------------------------------
# 1. Feishu Wiki Direct Reader & Annotation Restorer
# ---------------------------------------------------------------------------


def _block_text(block: dict[str, Any]) -> tuple[str, str]:
    """Returns (block_kind, plain_text) for a Feishu Docx block."""
    for kind in ("heading1", "heading2", "heading3", "heading4", "text", "todo", "quote", "bullet", "ordered"):
        if kind in block:
            txt = "".join(
                el.get("text_run", {}).get("content", "")
                for el in block[kind].get("elements", [])
            ).strip()
            return kind, txt
    return "other", ""


def restore_feishu_note(
    feishu_client: Any,
    obj_token: str,
    title: str = "",
    url: str = "",
    comments_override: list[dict[str, Any]] | None = None,
    blocks_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Restores a paper's deep-reading note, user reflections, and inline annotations from Feishu."""
    blocks = blocks_override if blocks_override is not None else feishu_client.get_document_blocks(obj_token)
    if comments_override is not None:
        raw_comments = comments_override
    else:
        try:
            res = feishu_client._call_api(
                "GET", f"/drive/v1/files/{obj_token}/comments", params={"file_type": "docx"}
            )
            raw_comments = res.get("items", [])
        except Exception as exc:
            logger.warning(f"Failed to fetch comments for Feishu doc {obj_token}: {exc}")
            raw_comments = []

    parsed_blocks: list[dict[str, Any]] = []
    block_by_id: dict[str, int] = {}
    full_text_start_idx = 0

    for idx, blk in enumerate(blocks):
        kind, txt = _block_text(blk)
        bid = blk.get("block_id", "")
        entry = {
            "idx": idx,
            "id": bid,
            "kind": kind,
            "text": txt,
            "done": bool(blk.get("todo", {}).get("style", {}).get("done")) if kind == "todo" else False,
        }
        parsed_blocks.append(entry)
        if bid:
            block_by_id[bid] = idx
        if kind.startswith("heading") and ("论文完整原文" in txt or "Original Full Paper" in txt):
            full_text_start_idx = idx

    status = "⏳ 待精读"
    paper_url = ""
    reflections: dict[str, Any] = {"insights": "", "critique": "", "relevance": "", "action_items": []}
    summary_sections: dict[str, str] = {}

    cur_h2 = ""
    cur_h3 = ""
    for entry in parsed_blocks:
        kind, txt = entry["kind"], entry["text"]
        if not txt:
            continue
        if "阅读状态:" in txt and "原文直达:" in txt:
            for st in ("⏳ 待精读", "📖 精读中", "✅ 已精读", "💡 已转化"):
                if st in txt:
                    status = st
                    break
            m = re.search(r"原文直达:\s*(https?://\S+)", txt)
            if m:
                paper_url = m.group(1).strip()
            continue

        if kind == "heading2":
            cur_h2, cur_h3 = txt, ""
            continue
        if kind == "heading3":
            cur_h3 = txt
            continue

        if "Reading Notes & Reflections" in cur_h2:
            if "Key Insights" in cur_h3 and kind == "text" and not _is_placeholder(txt):
                reflections["insights"] = (reflections["insights"] + "\n" + txt).strip()
            elif "Critique" in cur_h3 and kind == "text" and not _is_placeholder(txt):
                reflections["critique"] = (reflections["critique"] + "\n" + txt).strip()
            elif "Relevance" in cur_h3 and kind == "text" and not _is_placeholder(txt):
                reflections["relevance"] = (reflections["relevance"] + "\n" + txt).strip()
            elif "Action Items" in cur_h3 and kind == "todo" and entry["done"]:
                reflections["action_items"].append(txt)
        elif cur_h2 and full_text_start_idx and entry["idx"] < full_text_start_idx:
            for key, marker in (
                ("core_summary", "一、核心一句话总结"),
                ("motivation", "二、研究动机与问题背景"),
                ("method", "三、核心架构与机制设计"),
                ("experiments", "四、关键实验与结论"),
                ("takeaways", "五、落地启示与思考"),
            ):
                if marker in cur_h2 and kind == "text":
                    summary_sections[key] = (summary_sections.get(key, "") + "\n" + txt).strip()

    # Restore inline comments with exact quote, section heading, and bilingual paragraph context
    grouped_annotations: dict[tuple[str, str], dict[str, Any]] = {}
    for cmt in raw_comments:
        quote_str = (cmt.get("quote") or "").strip()
        anchor_id = (cmt.get("extra") or {}).get("content_anchor_id") or ""
        replies = []
        for rep in (cmt.get("reply_list") or {}).get("replies", []):
            rep_txt = "".join(
                (el.get("text_run") or {}).get("text", "")
                for el in (rep.get("content") or {}).get("elements", [])
            ).strip()
            if rep_txt:
                replies.append(rep_txt)
        if not replies and not quote_str:
            continue

        # Locate the best matching paragraph block (preferring the full-text body if an orphan block exists at top)
        anchor_idx = block_by_id.get(anchor_id)
        anchor_text = parsed_blocks[anchor_idx]["text"] if anchor_idx is not None else ""
        search_needle = (quote_str[:80] or anchor_text[:80]).lower()

        best_idx = anchor_idx
        if search_needle:
            candidates = [
                b["idx"]
                for b in parsed_blocks
                if b["kind"] in ("text", "quote", "bullet") and search_needle in b["text"].lower()
            ]
            if candidates:
                # Prefer the candidate inside the full-text section so heading & bilingual neighbor are intact
                body_candidates = [i for i in candidates if i >= full_text_start_idx]
                best_idx = body_candidates[-1] if body_candidates else candidates[-1]

        section = ""
        paragraph = anchor_text
        paragraph_zh = ""

        if best_idx is not None:
            paragraph = parsed_blocks[best_idx]["text"]
            for back_i in range(best_idx - 1, -1, -1):
                if parsed_blocks[back_i]["kind"].startswith("heading"):
                    h_txt = parsed_blocks[back_i]["text"]
                    if "论文完整原文" not in h_txt:
                        section = h_txt
                        break
            # Check next 1-3 blocks for adjacent Chinese translation paragraph
            if not _has_cjk(paragraph):
                for fwd_i in range(best_idx + 1, min(len(parsed_blocks), best_idx + 4)):
                    cand = parsed_blocks[fwd_i]
                    if cand["kind"].startswith("heading"):
                        break
                    if cand["kind"] == "text" and cand["text"] and _has_cjk(cand["text"]):
                        paragraph_zh = cand["text"]
                        break

        group_key = (quote_str or cmt.get("comment_id", ""), paragraph[:120])
        if group_key not in grouped_annotations:
            grouped_annotations[group_key] = {
                "quote": quote_str,
                "comments": [],
                "section": section,
                "paragraph": paragraph,
                "paragraph_zh": paragraph_zh,
                "is_solved": bool(cmt.get("is_solved", False)),
            }
        for r in replies:
            if r not in grouped_annotations[group_key]["comments"]:
                grouped_annotations[group_key]["comments"].append(r)

    return {
        "source": "feishu",
        "id": obj_token,
        "title": title,
        "url": url,
        "paper_url": paper_url,
        "status": status,
        "summary": summary_sections,
        "reflections": {k: v for k, v in reflections.items() if v},
        "annotations": list(grouped_annotations.values()),
    }


# ---------------------------------------------------------------------------
# 2. Obsidian Vault Direct Reader & Annotation Restorer
# ---------------------------------------------------------------------------


def restore_obsidian_note(note_path: Path, vault_root: Path | None = None) -> dict[str, Any]:
    """Restores a paper note and inline annotations directly from an Obsidian markdown file."""
    text = note_path.read_text(encoding="utf-8", errors="ignore")
    meta, body = _parse_frontmatter(text)
    heading_m = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    title = meta.get("title") or (heading_m.group(1).strip() if heading_m else note_path.stem)
    tags = _split_tags(meta.get("tags")) or re.findall(r"(?:^|\s)#([\w\-/]+)", body)
    rel = note_path.relative_to(vault_root).as_posix() if vault_root else note_path.name
    vault_name = vault_root.name if vault_root else ""

    annotations: list[dict[str, Any]] = []
    reflections: dict[str, Any] = {}
    current_section = ""

    paragraphs = re.split(r"\n\s*\n", body)
    for idx, para in enumerate(paragraphs):
        p_strip = para.strip()
        if not p_strip:
            continue
        if p_strip.startswith("#"):
            current_section = p_strip.lstrip("#").strip()
            continue

        # 1. Obsidian ==highlight== syntax with optional inline ^[comment] or %%comment%%
        for m in re.finditer(r"==([^=\n]+)==(?:\^\[([^\]]+)\]|\s*%%([^%]+)%%)?", p_strip):
            quote_str = m.group(1).strip()
            inline_cmt = (m.group(2) or m.group(3) or "").strip()
            comments = [inline_cmt] if inline_cmt else []
            # Also check if the immediately following block is a blockquote comment (> ...)
            if idx + 1 < len(paragraphs):
                next_p = paragraphs[idx + 1].strip()
                if next_p.startswith(">") and not next_p.startswith("> [!"):
                    comments.append(re.sub(r"^>\s*", "", next_p, flags=re.MULTILINE).strip())
            annotations.append(
                {
                    "quote": quote_str,
                    "comments": comments,
                    "section": current_section,
                    "paragraph": re.sub(r"==([^=\n]+)==", r"\1", p_strip),
                    "paragraph_zh": "",
                }
            )

        # 2. Obsidian Callout / Quote annotation blocks (> [!quote] or > [!note])
        callout_m = re.match(r"^>\s*\[!(quote|cite|note|important)\][^\n]*\n((?:>.*\n?)+)", p_strip, re.IGNORECASE)
        if callout_m:
            quote_body = re.sub(r"^>\s?", "", callout_m.group(2), flags=re.MULTILINE).strip()
            comments = []
            if idx + 1 < len(paragraphs):
                next_p = paragraphs[idx + 1].strip()
                if not next_p.startswith(("#", ">")):
                    comments.append(next_p)
            annotations.append(
                {
                    "quote": quote_body,
                    "comments": comments,
                    "section": current_section,
                    "paragraph": quote_body,
                    "paragraph_zh": "",
                }
            )

        if any(k in current_section.lower() for k in ("reflection", "insight", "critique", "思考", "批注", "笔记")):
            if not _is_placeholder(p_strip) and not p_strip.startswith("=="):
                reflections.setdefault("notes", []).append(p_strip)

    return {
        "source": "obsidian",
        "id": rel,
        "title": title,
        "url": f"obsidian://open?vault={quote(vault_name)}&file={quote(rel)}" if vault_name else str(note_path),
        "paper_url": meta.get("url") or meta.get("source") or "",
        "status": meta.get("status") or "",
        "tags": tags,
        "summary": {},
        "reflections": reflections,
        "annotations": annotations,
    }


# ---------------------------------------------------------------------------
# 3. Zotero Direct Reader & PDF Annotation Restorer
# ---------------------------------------------------------------------------


def restore_zotero_item(zot: Any, item: dict[str, Any]) -> dict[str, Any]:
    """Restores a paper item and its child PDF annotations/notes directly from Zotero."""
    data = item.get("data", {})
    key = item.get("key") or data.get("key", "")
    title = data.get("title", "Untitled")
    annotations: list[dict[str, Any]] = []
    notes: list[str] = []

    try:
        children = zot.children(key)
    except Exception:
        children = []

    for child in children:
        cdata = child.get("data", {})
        ctype = cdata.get("itemType")
        if ctype == "annotation":
            quote_str = (cdata.get("annotationText") or "").strip()
            comment_str = (cdata.get("annotationComment") or "").strip()
            page_lbl = cdata.get("annotationPageLabel") or ""
            if quote_str or comment_str:
                annotations.append(
                    {
                        "quote": quote_str,
                        "comments": [comment_str] if comment_str else [],
                        "section": f"Page {page_lbl}" if page_lbl else "",
                        "paragraph": quote_str,
                        "paragraph_zh": "",
                    }
                )
        elif ctype == "note":
            raw_html = cdata.get("note", "")
            clean_note = re.sub(r"<[^>]+>", " ", raw_html).strip()
            if clean_note:
                notes.append(clean_note)

    return {
        "source": "zotero",
        "id": key,
        "title": title,
        "url": f"zotero://select/library/items/{key}",
        "paper_url": data.get("url", ""),
        "status": "",
        "summary": {"abstract": data.get("abstractNote", "")},
        "reflections": {"notes": notes} if notes else {},
        "annotations": annotations,
    }


# ---------------------------------------------------------------------------
# 4. Notion Direct Reader & Block/Comment Restorer
# ---------------------------------------------------------------------------


def restore_notion_page(token: str, page_id: str, title: str = "", url: str = "") -> dict[str, Any]:
    """Restores a paper page and its highlighted spans/quote blocks directly from Notion."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }
    annotations: list[dict[str, Any]] = []
    current_section = ""

    try:
        resp = requests.get(f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100", headers=headers, timeout=20)
        blocks = resp.json().get("results", []) if resp.status_code == 200 else []
    except Exception:
        blocks = []

    for blk in blocks:
        btype = blk.get("type", "")
        bdata = blk.get(btype) or {}
        rich = bdata.get("rich_text") or []
        full_txt = "".join(r.get("plain_text", "") for r in rich).strip()
        if not full_txt:
            continue
        if btype.startswith("heading_"):
            current_section = full_txt
            continue
        if btype in ("quote", "callout"):
            annotations.append(
                {
                    "quote": full_txt,
                    "comments": [],
                    "section": current_section,
                    "paragraph": full_txt,
                    "paragraph_zh": "",
                }
            )
        else:
            for r in rich:
                color = (r.get("annotations") or {}).get("color", "default")
                if color and color != "default":
                    annotations.append(
                        {
                            "quote": r.get("plain_text", "").strip(),
                            "comments": [f"Highlight ({color})"],
                            "section": current_section,
                            "paragraph": full_txt,
                            "paragraph_zh": "",
                        }
                    )

    return {
        "source": "notion",
        "id": page_id,
        "title": title,
        "url": url,
        "paper_url": "",
        "status": "",
        "summary": {},
        "reflections": {},
        "annotations": annotations,
    }


# ---------------------------------------------------------------------------
# 5. Incremental Revision Cache & Hybrid Bilingual Scorer
# ---------------------------------------------------------------------------


def _load_cache(cache_path: str = DEFAULT_CACHE_PATH) -> dict[str, Any]:
    p = Path(cache_path)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "entries" in data:
                return data
        except Exception:
            pass
    return {"version": 1, "synced_at": 0.0, "entries": {}}


def _save_cache(cache: dict[str, Any], cache_path: str = DEFAULT_CACHE_PATH) -> None:
    p = Path(cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False)
        os.replace(tmp, p)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _enabled_providers(config: Any, provider: str = "auto") -> list[str]:
    p = (provider or "auto").lower()
    if p != "auto":
        return [p]
    active: list[str] = []
    feishu_cfg = config.get("feishu") or {}
    if feishu_cfg.get("app_id") and (feishu_cfg.get("notes_parent_node_token") or feishu_cfg.get("notes_folder_token")):
        active.append("feishu")
    obs_cfg = config.get("obsidian") or {}
    if obs_cfg.get("vault_path") and Path(str(obs_cfg.get("vault_path"))).expanduser().is_dir():
        active.append("obsidian")
    zot_cfg = config.get("zotero") or {}
    if zot_cfg.get("id") and zot_cfg.get("key"):
        active.append("zotero")
    not_cfg = config.get("notion") or {}
    if not_cfg.get("token") and not_cfg.get("database_id"):
        active.append("notion")
    return active or ["feishu"]


def _fetch_feishu_comments(client: Any, obj_token: str) -> list[dict[str, Any]]:
    try:
        res = client._call_api("GET", f"/drive/v1/files/{obj_token}/comments", params={"file_type": "docx"})
        return res.get("items", [])
    except Exception as exc:
        logger.warning(f"Failed to fetch comments for Feishu doc {obj_token}: {exc}")
        return []


def _comment_signature(cmts: list[dict[str, Any]]) -> str:
    return "|".join(f"{c.get('comment_id')}:{c.get('update_time')}" for c in cmts)


def sync_library_notes(
    config: Any,
    provider: str = "auto",
    refresh: bool = False,
    cache_ttl: int = 300,
    cache_path: str = DEFAULT_CACHE_PATH,
) -> list[dict[str, Any]]:
    """Incrementally syncs notes from active providers using revision/mtime invalidation."""
    cache = _load_cache(cache_path)
    entries: dict[str, Any] = cache.setdefault("entries", {})
    now = time.time()
    target_providers = _enabled_providers(config, provider)

    # Fast path: if cache was synced within TTL and no forced refresh, return cached notes directly
    if not refresh and (now - float(cache.get("synced_at", 0))) < cache_ttl and entries:
        cached_notes = [
            e["note"] for e in entries.values() if e.get("note", {}).get("source") in target_providers
        ]
        if cached_notes:
            return cached_notes

    results: list[dict[str, Any]] = []
    dirty = False

    for prov in target_providers:
        if prov == "feishu":
            from ..channels.feishu import FeishuClient

            client = FeishuClient(config.feishu)
            notes = [cp for cp in client.fetch_reading_notes() if cp.obj_token]
            # Check comments in parallel (polite 3-worker pool with retry in _call_api)
            with ThreadPoolExecutor(max_workers=3) as pool:
                cmts_list = list(pool.map(lambda cp: _fetch_feishu_comments(client, cp.obj_token), notes))

            for cp, cmts in zip(notes, cmts_list):
                ckey = f"feishu:{cp.obj_token}"
                edit_time = int(cp.added_date.timestamp()) if cp.added_date else 0
                c_sig = _comment_signature(cmts)
                existing = entries.get(ckey)

                # Only pull the 500-block Docx tree if edit_time or comment_signature changed (or not cached yet)
                if (
                    existing
                    and not refresh
                    and existing.get("edit_time") == edit_time
                    and existing.get("comment_sig") == c_sig
                ):
                    results.append(existing["note"])
                    continue

                restored = restore_feishu_note(
                    client, cp.obj_token, title=cp.title, url=cp.url or "", comments_override=cmts
                )
                entries[ckey] = {
                    "edit_time": edit_time,
                    "comment_sig": c_sig,
                    "checked_at": now,
                    "note": restored,
                }
                results.append(restored)
                dirty = True

        elif prov == "obsidian":
            obs_cfg = config.get("obsidian") or {}
            root = Path(str(obs_cfg.get("vault_path", ""))).expanduser()
            if root.is_dir():
                for md in root.rglob("*.md"):
                    if any(part.startswith(".") for part in md.relative_to(root).parts):
                        continue
                    rel = md.relative_to(root).as_posix()
                    ckey = f"obsidian:{rel}"
                    mtime = int(md.stat().st_mtime)
                    existing = entries.get(ckey)
                    if existing and not refresh and existing.get("edit_time") == mtime:
                        results.append(existing["note"])
                        continue
                    restored = restore_obsidian_note(md, root)
                    entries[ckey] = {"edit_time": mtime, "checked_at": now, "note": restored}
                    results.append(restored)
                    dirty = True

        elif prov == "zotero":
            from pyzotero import zotero as pyzotero

            zot_cfg = config.get("zotero") or {}
            zot = pyzotero.Zotero(str(zot_cfg.get("id")), "user", str(zot_cfg.get("key")))
            for item in zot.top(limit=50):
                if item.get("data", {}).get("itemType") in ("attachment", "note", "annotation"):
                    continue
                key = item.get("key") or item.get("data", {}).get("key", "")
                ver = int(item.get("version") or 0)
                ckey = f"zotero:{key}"
                existing = entries.get(ckey)
                if existing and not refresh and existing.get("edit_time") == ver:
                    results.append(existing["note"])
                    continue
                restored = restore_zotero_item(zot, item)
                entries[ckey] = {"edit_time": ver, "checked_at": now, "note": restored}
                results.append(restored)
                dirty = True

        elif prov == "notion":
            not_cfg = config.get("notion") or {}
            for cp in load_notion_corpus(str(not_cfg.get("token", "")), str(not_cfg.get("database_id", ""))):
                pid = cp.paths[0].split("/", 1)[-1] if cp.paths else ""
                if not pid:
                    continue
                ckey = f"notion:{pid}"
                existing = entries.get(ckey)
                if existing and not refresh:
                    results.append(existing["note"])
                    continue
                restored = restore_notion_page(str(not_cfg.get("token")), pid, title=cp.title, url=cp.url or "")
                entries[ckey] = {"edit_time": 0, "checked_at": now, "note": restored}
                results.append(restored)
                dirty = True

    cache["synced_at"] = now
    if dirty or refresh or not Path(cache_path).exists():
        _save_cache(cache, cache_path)
    return results


def _tokenize_query(query: str) -> list[str]:
    """Splits a bilingual query into English words, CJK phrases, and CJK sliding 2-grams."""
    q = query.lower().strip()
    raw_parts = re.findall(r"[\u4e00-\u9fff]+|[a-z0-9_\-]+", q)
    tokens: list[str] = []
    for p in raw_parts:
        if p not in tokens:
            tokens.append(p)
        if _has_cjk(p) and len(p) >= 2:
            for i in range(len(p) - 1):
                bg = p[i : i + 2]
                if bg not in tokens:
                    tokens.append(bg)
    return tokens


def _score_annotation(ann: dict[str, Any], raw_q: str, tokens: list[str]) -> float:
    """Computes field-weighted relevance score for a single inline annotation."""
    cmt_text = " ".join(ann.get("comments") or []).lower()
    quote_text = (ann.get("quote") or "").lower()
    sec_text = (ann.get("section") or "").lower()
    para_text = f"{ann.get('paragraph') or ''} {ann.get('paragraph_zh') or ''}".lower()

    score = 0.0
    if raw_q in cmt_text:
        score += 6.0
    if raw_q in quote_text:
        score += 4.5
    if raw_q in para_text:
        score += 3.0

    for tok in tokens:
        weight_scale = 1.0 if len(tok) > 2 else 0.5
        if tok in cmt_text:
            score += 3.0 * weight_scale
        if tok in quote_text:
            score += 2.2 * weight_scale
        if tok in sec_text:
            score += 1.2 * weight_scale
        if tok in para_text:
            score += 1.0 * weight_scale
    return round(score, 3)


def rank_library_notes(notes: list[dict[str, Any]], query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Ranks library notes and their annotations using hybrid field-weighted tokens + char/word TF-IDF."""
    raw_q = query.strip().lower()
    if not raw_q or not notes:
        return []
    tokens = _tokenize_query(raw_q)

    # 1. Build combined bilingual representation per note for char_wb TF-IDF cosine similarity
    note_blobs: list[str] = []
    for n in notes:
        parts = [n.get("title", ""), " ".join(str(v) for v in (n.get("summary") or {}).values())]
        parts.extend(str(v) for v in (n.get("reflections") or {}).values())
        for a in n.get("annotations") or []:
            parts.extend([a.get("section", ""), a.get("quote", ""), " ".join(a.get("comments") or [])])
            parts.extend([a.get("paragraph", ""), a.get("paragraph_zh", "")])
        note_blobs.append(" ".join(p for p in parts if p))

    tfidf_scores = [0.0] * len(notes)
    if any(b.strip() for b in note_blobs):
        try:
            vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), lowercase=True)
            mat = vec.fit_transform([raw_q] + note_blobs)
            sims = cosine_similarity(mat[0:1], mat[1:])[0]
            tfidf_scores = [float(s) for s in sims]
        except Exception:
            pass

    scored_notes: list[dict[str, Any]] = []
    for idx, n in enumerate(notes):
        title_l = (n.get("title") or "").lower()
        refl_l = " ".join(str(v) for v in (n.get("reflections") or {}).values()).lower()
        summ_l = " ".join(str(v) for v in (n.get("summary") or {}).values()).lower()

        base_score = tfidf_scores[idx] * 5.0
        if raw_q in title_l:
            base_score += 5.0
        if raw_q in refl_l:
            base_score += 4.0
        for tok in tokens:
            w = 1.0 if len(tok) > 2 else 0.5
            if tok in title_l:
                base_score += 2.0 * w
            if tok in refl_l:
                base_score += 2.0 * w
            if tok in summ_l:
                base_score += 0.6 * w

        # Score individual annotations
        ranked_anns: list[dict[str, Any]] = []
        max_ann_score = 0.0
        for a in n.get("annotations") or []:
            a_score = _score_annotation(a, raw_q, tokens)
            if a_score > 0:
                a_copy = dict(a)
                a_copy["score"] = a_score
                ranked_anns.append(a_copy)
                if a_score > max_ann_score:
                    max_ann_score = a_score

        ranked_anns.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        total_score = round(base_score + max_ann_score, 3)

        # Require at least one meaningful lexical or strong TF-IDF match
        if max_ann_score > 0 or base_score >= 1.5:
            n_copy = dict(n)
            n_copy["score"] = total_score
            if ranked_anns:
                n_copy["annotations"] = ranked_anns
            scored_notes.append(n_copy)

    scored_notes.sort(key=lambda x: x.get("score", 0.0), reverse=True)
    return scored_notes[:top_k]


def list_library_notes(
    config: Any,
    provider: str = "auto",
    annotated_only: bool = False,
    refresh: bool = False,
) -> list[dict[str, Any]]:
    """Lists literature notes from the user's active library providers (with incremental cache)."""
    notes = sync_library_notes(config, provider=provider, refresh=refresh)
    if annotated_only:
        return [n for n in notes if n.get("annotations") or n.get("reflections")]
    return notes


def query_library_notes(
    config: Any,
    query: str,
    provider: str = "auto",
    search_annotations: bool = False,
    refresh: bool = False,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Retrieves and ranks paper annotations matching title/ID or hybrid bilingual search query."""
    q = query.strip().lower()
    notes = sync_library_notes(config, provider=provider, refresh=refresh)
    if not search_annotations:
        exact = [
            n
            for n in notes
            if q in (n.get("title") or "").lower()
            or q == (n.get("id") or "").lower()
            or q in (n.get("paper_url") or "").lower()
            or q in (n.get("url") or "").lower()
        ]
        return exact[:top_k] if exact else rank_library_notes(notes, query, top_k=top_k)
    return rank_library_notes(notes, query, top_k=top_k)


def format_restored_note_markdown(note: dict[str, Any]) -> str:
    """Formats a restored note and its inline annotations into clean agent-ready Markdown."""
    score_str = f" (相关度: {note['score']:.2f})" if "score" in note else ""
    lines = [
        f"# {note.get('title')}{score_str}",
        f"- **来源库**: `{note.get('source')}` (`{note.get('id')}`)",
    ]
    if note.get("status"):
        lines.append(f"- **阅读状态**: {note['status']}")
    if note.get("paper_url"):
        lines.append(f"- **论文原文**: {note['paper_url']}")
    if note.get("url"):
        lines.append(f"- **笔记直达**: {note['url']}")

    anns = note.get("annotations") or []
    lines.append(f"\n## 🎯 精读划词批注与上下文还原 ({len(anns)} 处)")
    if not anns:
        lines.append("*(暂无划词批注)*")
    for idx, ann in enumerate(anns, 1):
        sec = f" [{ann['section']}]" if ann.get("section") else ""
        lines.append(f"\n### 批注 #{idx}{sec}")
        if ann.get("quote"):
            lines.append(f"- **划词原文**: \"{ann['quote']}\"")
        for c_idx, cmt in enumerate(ann.get("comments") or [], 1):
            lines.append(f"- **我的批注 ({c_idx})**: **{cmt}**")
        if ann.get("paragraph") and ann["paragraph"] != ann.get("quote"):
            lines.append(f"- **所在完整原段**: {ann['paragraph']}")
        if ann.get("paragraph_zh"):
            lines.append(f"- **对应中文译段**: {ann['paragraph_zh']}")

    refl = note.get("reflections") or {}
    if refl:
        lines.append("\n## ✍️ 个人研读思考与待办")
        for k, v in refl.items():
            lines.append(f"- **{k}**: {v}")

    summ = note.get("summary") or {}
    if summ:
        lines.append("\n## 📌 论文核心结构摘要")
        for k, label in (
            ("core_summary", "核心一句话"),
            ("motivation", "研究动机"),
            ("method", "核心方法"),
            ("experiments", "关键实验"),
            ("takeaways", "落地启示"),
            ("abstract", "摘要"),
        ):
            if summ.get(k):
                lines.append(f"- **{label}**: {summ[k]}")

    return "\n".join(lines)


def _load_runtime_config() -> Any:
    from dotenv import load_dotenv
    from omegaconf import OmegaConf

    load_dotenv(".env")
    base = OmegaConf.load("config/base.yaml") if Path("config/base.yaml").exists() else OmegaConf.create({})
    custom = OmegaConf.load("config/custom.yaml") if Path("config/custom.yaml").exists() else OmegaConf.create({})
    return OmegaConf.merge(base, custom)


def trigger_pipeline_dispatch(
    repo: Optional[str] = None,
    token: Optional[str] = None,
    event_type: str = "paper-daily",
    force_today: bool = False,
    ingest_only: bool = False,
    questions: Optional[list[str]] = None,
    custom_rules: Optional[list[str]] = None,
    tags: Optional[list[str]] = None,
) -> dict[str, Any]:
    """Triggers remote GitHub Actions Paper Daily pipeline via repository_dispatch webhook.
    Compatible with external agents (Hermes, Grok bot, Telegram/Discord bots, curl, Dify)."""
    import subprocess

    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        try:
            res = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
            token = res.stdout.strip()
        except Exception:
            pass
    if not token:
        raise ValueError("GitHub token required (set GITHUB_TOKEN or authenticate via 'gh auth login')")

    if not repo:
        repo = os.environ.get("GITHUB_REPOSITORY")
        if not repo:
            try:
                res = subprocess.run(
                    ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                repo = res.stdout.strip()
            except Exception:
                pass
    if not repo:
        repo = "link231rog/feisu-paper-daily"

    payload: dict[str, Any] = {
        "force_today": force_today,
        "ingest_only": ingest_only,
    }
    if questions:
        payload["questions"] = questions
    if custom_rules:
        payload["custom_rules"] = custom_rules
    if tags:
        payload["tags"] = tags

    url = f"https://api.github.com/repos/{repo}/dispatches"
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "Paper-Daily-Agent-Bridge",
    }
    resp = requests.post(
        url,
        json={"event_type": event_type, "client_payload": payload},
        headers=headers,
        timeout=15,
    )
    if resp.status_code in (200, 204):
        return {
            "status": "success",
            "repo": repo,
            "event_type": event_type,
            "message": f"Successfully triggered '{event_type}' on GitHub Actions ({repo})",
            "client_payload": payload,
        }
    raise RuntimeError(f"GitHub API returned {resp.status_code}: {resp.text}")


# ---------------------------------------------------------------------------
# 6. Multi-Platform Reading Note Ingestion & Detail Annotation Writers
# ---------------------------------------------------------------------------

_STANDARD_SECTION_TITLES = (
    ("core_summary", "一、核心一句话总结"),
    ("motivation", "二、研究动机与问题背景"),
    ("method", "三、核心架构与机制设计"),
    ("experiments", "四、关键实验与结论"),
    ("takeaways", "五、落地启示与思考"),
)


def apply_inline_annotations_to_markdown(
    text: str,
    inline_annotations: list[dict[str, Any]] | None = None,
) -> str:
    """Applies detail annotations in-place using ==quote==^[comment] syntax."""
    if not text or not inline_annotations:
        return text
    annotated = text
    for ann in inline_annotations:
        quote_str = str(ann.get("quote") or ann.get("exact_quote") or "").strip()
        comment_str = str(ann.get("comment") or "").strip().replace("]", ")")
        ann_type = str(ann.get("type") or "note").strip()
        if not quote_str or len(quote_str) < 4:
            continue
        replacement = f"=={quote_str}==^[({ann_type}) {comment_str}]" if comment_str else f"=={quote_str}=="
        if quote_str in annotated and f"=={quote_str}==" not in annotated:
            annotated = annotated.replace(quote_str, replacement, 1)
    return annotated


def write_obsidian_reading_note(
    obsidian_cfg: Any,
    paper: Any,
    sections: dict[str, str],
    tags: list[str],
    full_text_markdown: str | None = None,
    inline_annotations: list[dict[str, Any]] | None = None,
) -> str | None:
    """Writes a structured deep-reading note with detail annotations into an Obsidian vault."""
    if not obsidian_cfg or not obsidian_cfg.get("vault_path"):
        return None
    vault_root = Path(str(obsidian_cfg.get("vault_path"))).expanduser()
    if not vault_root.is_dir():
        return None

    notes_folder = str(obsidian_cfg.get("notes_folder") or "Literature").strip("/")
    target_dir = vault_root / notes_folder if notes_folder else vault_root
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_title = re.sub(r'[\\/:*?"<>|]+', "_", (paper.title or "Untitled")).strip()[:120]
    note_path = target_dir / f"{safe_title}.md"

    anns = inline_annotations if inline_annotations is not None else (getattr(paper, "inline_annotations", None) or [])
    tag_list = ", ".join(tags or ["Research"])
    lines = [
        "---",
        f'title: "{(paper.title or "").replace(chr(34), chr(39))}"',
        f'url: "{paper.url or ""}"',
        f"tags: [{tag_list}]",
        f'venue: "{getattr(paper, "venue", "") or ""}"',
        'status: "⏳ 待精读"',
        f'date: "{datetime.now().strftime("%Y-%m-%d")}"',
        "---",
        "",
        f"# {paper.title}",
        "",
        f"- **原文链接**: {paper.url or 'N/A'}",
        f"- **发表会议/期刊**: {getattr(paper, 'venue', None) or 'Preprint'}",
        "",
    ]

    # Standard + custom template sections
    rendered_keys: set[str] = set()
    for key, label in _STANDARD_SECTION_TITLES:
        if sections.get(key):
            lines.extend([f"## {label}", "", str(sections[key]).strip(), ""])
            rendered_keys.add(key)

    for key, val in (sections or {}).items():
        if key not in rendered_keys and val:
            lines.extend([f"## {key}", "", str(val).strip(), ""])

    # Detail annotations section
    if anns:
        lines.extend(["## 细节批注与审稿核查", ""])
        for ann in anns:
            q_str = str(ann.get("quote") or ann.get("exact_quote") or "").strip()
            c_str = str(ann.get("comment") or "").strip()
            t_str = str(ann.get("type") or "claim").strip()
            if q_str:
                lines.append(f"- =={q_str}==^[{c_str}]")
                if c_str:
                    lines.append(f"  > [{t_str}] {c_str}")
        lines.append("")

    # Reflections template for user & Agent bridge
    lines.extend(
        [
            "## Reading Notes & Reflections",
            "",
            "### Key Insights",
            "可在研读后直接划词批注或记录关键洞察",
            "",
            "### Critique",
            "记录论文假设漏洞、对比缺陷或未解决的边界条件",
            "",
        ]
    )

    if full_text_markdown:
        annotated_body = apply_inline_annotations_to_markdown(full_text_markdown, anns)
        lines.extend(["## 论文完整原文与逐节研读区", "", annotated_body.strip(), ""])
    elif getattr(paper, "abstract", None):
        annotated_abs = apply_inline_annotations_to_markdown(paper.abstract, anns)
        lines.extend(["## 摘要批注原文", "", annotated_abs.strip(), ""])

    note_path.write_text("\n".join(lines), encoding="utf-8")
    rel = note_path.relative_to(vault_root).as_posix()
    return f"obsidian://open?vault={quote(vault_root.name)}&file={quote(rel)}"


def write_notion_reading_note(
    notion_cfg: Any,
    paper: Any,
    sections: dict[str, str],
    tags: list[str],
    full_text_markdown: str | None = None,
    inline_annotations: list[dict[str, Any]] | None = None,
) -> str | None:
    """Creates a structured deep-reading note page in a Notion database."""
    if not notion_cfg or not notion_cfg.get("token") or not notion_cfg.get("database_id"):
        return None
    token = str(notion_cfg.get("token")).strip()
    database_id = str(notion_cfg.get("database_id")).strip()
    anns = inline_annotations if inline_annotations is not None else (getattr(paper, "inline_annotations", None) or [])

    children: list[dict[str, Any]] = []
    if paper.url:
        children.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": f"原文直达: {paper.url}"}}]
                },
            }
        )

    rendered_keys: set[str] = set()
    for key, label in _STANDARD_SECTION_TITLES:
        if sections.get(key):
            children.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": label}}]},
                }
            )
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": str(sections[key])[:1900]}}]
                    },
                }
            )
            rendered_keys.add(key)

    for key, val in (sections or {}).items():
        if key not in rendered_keys and val:
            children.append(
                {
                    "object": "block",
                    "type": "heading_2",
                    "heading_2": {"rich_text": [{"type": "text", "text": {"content": str(key)[:100]}}]},
                }
            )
            children.append(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": str(val)[:1900]}}]},
                }
            )

    if anns:
        children.append(
            {
                "object": "block",
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": "细节批注与审稿核查"}}]},
            }
        )
        for ann in anns[:15]:
            q_str = str(ann.get("quote") or ann.get("exact_quote") or "").strip()
            c_str = str(ann.get("comment") or "").strip()
            t_str = str(ann.get("type") or "claim").strip()
            color = {"baseline": "blue_background", "claim": "green_background", "critique": "orange_background"}.get(
                t_str, "yellow_background"
            )
            children.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": q_str[:900]},
                                "annotations": {"color": color},
                            },
                            {
                                "type": "text",
                                "text": {"content": f" — [{t_str}] {c_str}"[:900]},
                            },
                        ]
                    },
                }
            )

    payload = {
        "parent": {"database_id": database_id},
        "properties": {
            "Name": {"title": [{"text": {"content": (paper.title or "Untitled")[:200]}}]},
        },
        "children": children[:95],
    }
    resp = requests.post(
        "https://api.notion.com/v1/pages",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    if resp.status_code in (200, 201):
        data = resp.json()
        return data.get("url") or f"https://www.notion.so/{data.get('id', '').replace('-', '')}"
    logger.warning(f"Notion page creation failed ({resp.status_code}): {resp.text[:200]}")
    return None


def write_zotero_reading_note(
    zotero_cfg: Any,
    paper: Any,
    sections: dict[str, str],
    tags: list[str],
    inline_annotations: list[dict[str, Any]] | None = None,
) -> str | None:
    """Creates a paper item and structured child note in Zotero."""
    uid = zotero_cfg.get("user_id") or zotero_cfg.get("id") if zotero_cfg else None
    api_key = zotero_cfg.get("api_key") or zotero_cfg.get("key") if zotero_cfg else None
    if not uid or not api_key or str(uid) == "???":
        return None
    try:
        from pyzotero import zotero as pyzotero
        import html

        zot = pyzotero.Zotero(str(uid), "user", str(api_key))
        template = zot.item_template("preprint")
        template["title"] = paper.title or "Untitled"
        template["url"] = paper.url or ""
        template["abstractNote"] = getattr(paper, "abstract", "") or ""
        template["tags"] = [{"tag": t} for t in (tags or [])]
        created = zot.create_items([template])
        item_key = ""
        if isinstance(created, dict) and created.get("successful"):
            first = next(iter(created["successful"].values()))
            item_key = first.get("key") or first.get("data", {}).get("key", "")

        anns = inline_annotations if inline_annotations is not None else (getattr(paper, "inline_annotations", None) or [])
        html_parts = [f"<h1>{html.escape(paper.title or '')}</h1>"]
        for key, label in _STANDARD_SECTION_TITLES:
            if sections.get(key):
                html_parts.append(f"<h2>{html.escape(label)}</h2><p>{html.escape(str(sections[key]))}</p>")
        if anns:
            html_parts.append("<h2>细节批注与审稿核查</h2><ul>")
            for ann in anns:
                q_str = html.escape(str(ann.get("quote") or ann.get("exact_quote") or ""))
                c_str = html.escape(str(ann.get("comment") or ""))
                html_parts.append(f"<li><mark>{q_str}</mark>: <strong>{c_str}</strong></li>")
            html_parts.append("</ul>")

        note_item = zot.item_template("note")
        note_item["note"] = "\n".join(html_parts)
        if item_key:
            note_item["parentItem"] = item_key
        zot.create_items([note_item])
        return f"zotero://select/library/items/{item_key}" if item_key else "zotero://select/library"
    except Exception as exc:
        logger.warning(f"Failed to write Zotero reading note: {exc}")
        return None


def fetch_checked_papers_from_obsidian(obsidian_cfg: Any) -> list[dict[str, Any]]:
    """Scans Obsidian vault markdown files for checked paper tasks `- [x] [Title](url)`."""
    if not obsidian_cfg or not obsidian_cfg.get("vault_path"):
        return []
    root = Path(str(obsidian_cfg.get("vault_path"))).expanduser()
    if not root.is_dir():
        return []

    task_re = re.compile(r"^-\s*\[[xX]\]\s*\[([^\]]+)\]\((https?://[^\s)]+)\)(.*)$")
    checked: list[dict[str, Any]] = []
    for md in root.rglob("*.md"):
        if any(part.startswith(".") for part in md.relative_to(root).parts):
            continue
        try:
            lines = md.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for line in lines:
            m = task_re.match(line.strip())
            if m:
                title, url, tail = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
                action = "delete" if any(k in tail.lower() for k in ("删除", "屏蔽", "discard", "delete")) else "ingest"
                from ..channels.feishu import extract_user_reason
                user_reason = extract_user_reason(tail)
                checked.append({
                    "title": title,
                    "url": url,
                    "action": action,
                    "tldr": tail.lstrip("-: "),
                    "user_reason": user_reason,
                })
    return checked


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="paper-library",
        description="Direct CLI bridge for AI agents to inspect & restore annotations from Feishu, Obsidian, Notion, or Zotero.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="Incrementally sync & warm local revision cache from active library")
    p_sync.add_argument("--provider", default="auto", choices=["auto", "feishu", "obsidian", "zotero", "notion"])
    p_sync.add_argument("--refresh", action="store_true", help="Force full refresh from remote library")

    p_list = sub.add_parser("list", help="List papers in the user's literature library")
    p_list.add_argument("--provider", default="auto", choices=["auto", "feishu", "obsidian", "zotero", "notion"])
    p_list.add_argument("--annotated-only", action="store_true", help="Only return papers with user annotations")
    p_list.add_argument("--refresh", action="store_true", help="Check remote library for updates immediately")
    p_list.add_argument("--json", action="store_true", help="Output raw JSON")

    p_get = sub.add_parser("get", help="Restore annotations and context for a paper by title or ID")
    p_get.add_argument("query", help="Paper title substring, arXiv ID, or document token")
    p_get.add_argument("--provider", default="auto", choices=["auto", "feishu", "obsidian", "zotero", "notion"])
    p_get.add_argument("--refresh", action="store_true", help="Check remote library for updates immediately")
    p_get.add_argument("--json", action="store_true", help="Output raw JSON")

    p_search = sub.add_parser("search", help="Hybrid bilingual semantic & keyword search across annotations")
    p_search.add_argument("query", help="Keywords or phrase to search across comments, quotes, and bilingual text")
    p_search.add_argument("--provider", default="auto", choices=["auto", "feishu", "obsidian", "zotero", "notion"])
    p_search.add_argument("--top-k", type=int, default=5, help="Max matched papers to return (default: 5)")
    p_search.add_argument("--refresh", action="store_true", help="Check remote library for updates immediately")
    p_search.add_argument("--json", action="store_true", help="Output raw JSON")

    p_trig = sub.add_parser("trigger", help="Trigger remote GitHub Actions pipeline via repository_dispatch (for Hermes, Grok bot, curl)")
    p_trig.add_argument("--repo", default=None, help="GitHub repository e.g. 'owner/repo' (defaults to git config or link231rog/feisu-paper-daily)")
    p_trig.add_argument("--token", default=None, help="GitHub personal access token (defaults to GITHUB_TOKEN or gh CLI)")
    p_trig.add_argument("--event", default="paper-daily", choices=["paper-daily", "ingest"], help="Event type: 'paper-daily' (full) or 'ingest' (confirmed ingestion)")
    p_trig.add_argument("--force-today", action="store_true", help="Re-evaluate and deliver papers pushed earlier today")
    p_trig.add_argument("--ingest-only", action="store_true", help="Only run paper ingestion for user-checked papers")
    p_trig.add_argument("--question", action="append", dest="questions", help="Ad-hoc research question to append for this run")
    p_trig.add_argument("--rule", action="append", dest="rules", help="Ad-hoc custom review rule to append for this run")
    p_trig.add_argument("--tag", action="append", dest="tags", help="Ad-hoc topic tag to append for this run")
    p_trig.add_argument("--json", action="store_true", help="Output raw JSON")

    p_init = sub.add_parser("init", help="Interactive multi-select & Agent Skill initialization wizard")
    p_init.add_argument("--schema", action="store_true", help="Output JSON schema of multi-select questions for AI Agents")
    p_init.add_argument("--print-skill", action="store_true", help="Print the Agent SKILL.md definition")
    p_init.add_argument("--from-json", default=None, help="Apply configuration from JSON string or file path")
    p_init.add_argument("--config-out", default="config/custom.yaml", help="Target path for generated custom.yaml")
    p_init.add_argument("--env-out", default=".env", help="Target path for generated .env file")

    p_find = sub.add_parser("find", help="Online academic literature search & MMR reranking for Coding Agents")
    p_find.add_argument("query", help="Keywords or description of coding problem/technology to search")
    p_find.add_argument("--top-k", type=int, default=5, help="Number of papers to recommend (default: 5)")
    p_find.add_argument("--source", action="append", dest="sources", help="Specific sources (arxiv, semantic_scholar, dblp)")
    p_find.add_argument("--json", action="store_true", help="Output raw JSON for agent parsing")

    p_ingest = sub.add_parser("ingest", help="Directly ingest paper by URL or arXiv ID into knowledge base without checklist")
    p_ingest.add_argument("url", help="Paper URL (arXiv, OpenReview, GitHub, or arXiv ID e.g. 2401.12345)")
    p_ingest.add_argument("--provider", default="auto", choices=["auto", "feishu", "obsidian", "notion", "zotero"], help="Target library provider (default: auto)")
    p_ingest.add_argument("--json", action="store_true", help="Output raw JSON for agent parsing")

    args = parser.parse_args()
    if args.cmd == "init":
        from ..init_wizard import handle_init_cli

        init_argv: list[str] = []
        if args.schema:
            init_argv.append("--schema")
        if args.print_skill:
            init_argv.append("--print-skill")
        if args.from_json:
            init_argv.extend(["--from-json", args.from_json])
        init_argv.extend(["--config-out", args.config_out, "--env-out", args.env_out])
        handle_init_cli(init_argv)
        return

    cfg = _load_runtime_config()

    if args.cmd == "sync":
        t0 = time.time()
        notes = sync_library_notes(cfg, provider=args.provider, refresh=args.refresh, cache_ttl=0)
        ann_notes = [n for n in notes if n.get("annotations") or n.get("reflections")]
        total_anns = sum(len(n.get("annotations") or []) for n in notes)
        print(
            f"[增量同步完成] ({time.time() - t0:.2f}s): 共 {len(notes)} 篇精读文献, "
            f"{len(ann_notes)} 篇含个人批注/思考, 累计 {total_anns} 处原位划词批注。"
        )
    elif args.cmd == "list":
        notes = list_library_notes(
            cfg, provider=args.provider, annotated_only=args.annotated_only, refresh=args.refresh
        )
        if args.json:
            print(json.dumps(notes, ensure_ascii=False, indent=2))
        else:
            for n in notes:
                ann_cnt = f" | [已批注 {len(n.get('annotations') or [])} 条]" if n.get("annotations") else ""
                print(f"[{n['source']}] {n['title']} (id={n['id']}){ann_cnt} -> {n.get('url', '')}")
    elif args.cmd in ("get", "search"):
        top_k = getattr(args, "top_k", 5)
        notes = query_library_notes(
            cfg,
            args.query,
            provider=args.provider,
            search_annotations=(args.cmd == "search"),
            refresh=args.refresh,
            top_k=top_k,
        )
        if args.json:
            print(json.dumps(notes, ensure_ascii=False, indent=2))
        elif not notes:
            print(f"未在文献库中找到匹配 '{args.query}' 的文献或批注。")
        else:
            print("\n\n---\n\n".join(format_restored_note_markdown(n) for n in notes))
    elif args.cmd == "trigger":
        try:
            res = trigger_pipeline_dispatch(
                repo=args.repo,
                token=args.token,
                event_type=args.event,
                force_today=args.force_today,
                ingest_only=args.ingest_only,
                questions=args.questions,
                custom_rules=args.rules,
                tags=args.tags,
            )
            if args.json:
                print(json.dumps(res, ensure_ascii=False, indent=2))
            else:
                print(f"[触发成功] 已向 GitHub Actions ({res['repo']}) 发送 '{res['event_type']}' 事件调度请求。")
        except Exception as exc:
            print(f"[触发失败] {exc}")
    elif args.cmd == "find":
        from .finder import find_papers, format_found_papers_markdown

        found = find_papers(args.query, top_k=args.top_k, sources=args.sources, config=cfg)
        if args.json:
            print(json.dumps(found, ensure_ascii=False, indent=2))
        else:
            print(format_found_papers_markdown(found, args.query))
    elif args.cmd == "ingest":
        from .finder import ingest_paper_direct

        res = ingest_paper_direct(args.url, provider=args.provider, config=cfg)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if res.get("status") == "success":
                print(f"[入库成功] {res.get('message')}")
            else:
                print(f"[{res.get('status', '提示')}] {res.get('message')}")


if __name__ == "__main__":
    main()
