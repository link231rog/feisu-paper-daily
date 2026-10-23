"""Optional interest-corpus adapters for external note libraries."""

from datetime import datetime
from pathlib import Path
import re
from urllib.parse import quote

import requests
from loguru import logger

from .protocol import CorpusPaper

NOTION_VERSION = "2022-06-28"


def _split_tags(raw) -> list[str]:
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
