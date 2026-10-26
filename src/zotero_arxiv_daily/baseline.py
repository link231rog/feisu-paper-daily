"""Baseline method extraction, attribution, and bi-directional library linking."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

from loguru import logger

from .llm import LLMRouter
from .protocol import CorpusPaper, Paper
from .textutil import UNTRUSTED_NOTICE, extract_json


_json_block = extract_json


def extract_baselines(router: LLMRouter, paper: Paper) -> list[dict[str, Any]]:
    """Extracts 2-4 key baseline methods from the paper's title and abstract."""
    if not router.available or not paper.abstract:
        return []

    prompt = (
        "Extract baseline methods explicitly named in this abstract. Return at most 4, but fewer or zero is expected when none are named.\n"
        "Use only the supplied text: do not add familiar methods, publication venues, results, mechanisms or comparisons from prior knowledge.\n\n"
        f"{UNTRUSTED_NOTICE}\n"
        f"Paper title: {paper.title}\n"
        f"<untrusted_source>\n{paper.abstract[:2000]}\n</untrusted_source>\n\n"
        "For each baseline:\n"
        "1. name: method name exactly as written in the abstract.\n"
        "2. method_summary: Chinese summary supported by the abstract; use '摘要未说明具体机制' when absent.\n"
        "3. venue: empty string unless explicitly stated in the abstract.\n"
        "4. comparison: Chinese explanation supported by the abstract; use '摘要仅提及该方法，未给出比较结果' when absent.\n"
        "Do not treat the proposed method itself as its own baseline.\n"
        "Return ONLY a JSON array:\n"
        '[{"name": "...", "method_summary": "...", "venue": "", "comparison": "..."}]\n'
        "If no specific baseline is explicitly named, return []."
    )

    try:
        raw = router.chat([{"role": "user", "content": prompt}], max_tokens=1000, timeout=60)
        data = _json_block(raw, [])
        if not isinstance(data, list):
            return []
        valid: list[dict[str, Any]] = []
        for item in data:
            if isinstance(item, dict) and item.get("name") and item.get("method_summary"):
                valid.append({
                    "name": str(item["name"]).strip(),
                    "method_summary": str(item["method_summary"]).strip(),
                    "venue": str(item.get("venue", "")).strip(),
                    "comparison": str(item.get("comparison", "")).strip(),
                })
        return valid[:4]
    except Exception as exc:
        logger.warning(f"Failed to extract baselines for '{paper.title}': {exc}")
        return []


def _normalize_title(text: str) -> str:
    """Strips leading emojis, wiki prefixes, tags and punctuation for fuzzy matching."""
    text = re.sub(r"^[📄📝💡📌\s]*\[[^\]]*\]\s*", "", text)
    text = re.sub(r"\[#[^\]]+\]", "", text)
    return re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]", "", text).lower()


def resolve_library_link(cp: CorpusPaper) -> dict[str, str]:
    """Generates native deep-links, badges, and wikilinks across Feishu, Notion, Zotero, and Obsidian."""
    # Every loader prefixes paths with its ecosystem ("zotero/", "notion/", ...); match the
    # first segment only so a note titled "Notion ..." cannot be mislabelled.
    prefixes = {(p or "").split("/", 1)[0].lower() for p in (cp.paths or [])}
    if "obsidian" in prefixes:
        return {
            "badge": f"🟣 [Obsidian已入库: {cp.title}]",
            "uri": cp.url or "",
            "wikilink": f"[[{cp.title}]]",
            "source": "obsidian",
        }
    if "notion" in prefixes:
        return {
            "badge": f"⚫ [Notion已入库: {cp.title}]",
            "uri": cp.url or "",
            "source": "notion",
        }
    if "zotero" in prefixes:
        return {
            "badge": f"🔴 [Zotero已入库: {cp.title}]",
            "uri": cp.url or "",
            "source": "zotero",
        }
    return {
        "badge": f"🟢 [飞书已入库: {cp.title}]",
        "uri": cp.url or (f"https://feishu.cn/wiki/{cp.node_token}" if cp.node_token else ""),
        "source": "feishu",
    }


def match_baselines_with_corpus(
    baselines: list[dict[str, Any]],
    corpus: list[CorpusPaper],
) -> list[dict[str, Any]]:
    """Matches extracted baselines against the user's reading notes or personal library."""
    if not baselines:
        return []

    # Pre-index corpus by normalized title
    corpus_lookup: list[tuple[str, str, CorpusPaper]] = []
    for cp in corpus:
        norm = _normalize_title(cp.title)
        if norm:
            corpus_lookup.append((norm, cp.title.lower(), cp))

    enriched: list[dict[str, Any]] = []
    for b in baselines:
        name = b["name"]
        norm_name = _normalize_title(name)
        matched_cp: CorpusPaper | None = None

        if norm_name and len(norm_name) >= 2:
            # 1. Exact or substring match in normalized title
            for norm_title, raw_title_lower, cp in corpus_lookup:
                if norm_name == norm_title:
                    matched_cp = cp
                    break
                if len(norm_name) >= 3 and (norm_name in norm_title or norm_title in norm_name):
                    matched_cp = cp
                    break
                # Word boundary match (e.g. "ReAct" in "ReAct: Synergizing Reasoning...")
                if re.search(rf"\b{re.escape(name.lower())}\b", raw_title_lower):
                    matched_cp = cp
                    break

        item = dict(b)
        if matched_cp is not None:
            lib_info = resolve_library_link(matched_cp)
            item["in_library"] = True
            item["doc_title"] = matched_cp.title
            item["doc_url"] = lib_info["uri"] or (
                f"https://feishu.cn/wiki/{matched_cp.node_token}"
                if matched_cp.node_token
                else None
            )
            item["library_badge"] = lib_info["badge"]
            item["library_source"] = lib_info.get("source", "feishu")
            item["wikilink"] = lib_info.get("wikilink")
            item["node_token"] = getattr(matched_cp, "node_token", None)
            item["obj_token"] = getattr(matched_cp, "obj_token", None)
        else:
            item["in_library"] = False
            item["doc_title"] = None
            search_query = quote(f"{name} {b.get('venue', '')}".strip())
            item["doc_url"] = f"https://www.semanticscholar.org/search?q={search_query}"
            item["library_badge"] = "⚪ [未入库: 出处检索]"
            item["library_source"] = None
            item["wikilink"] = None
            item["node_token"] = None
            item["obj_token"] = None

        enriched.append(item)

    return enriched


def enrich_papers_with_baselines(
    router: LLMRouter,
    papers: list[Paper],
    corpus: list[CorpusPaper],
    max_workers: int = 4,
) -> None:
    """Extracts and matches baselines for a batch of recommended papers in parallel."""
    if not router.available or not papers:
        return

    def process_one(paper: Paper) -> None:
        raw_baselines = extract_baselines(router, paper)
        if raw_baselines:
            matched = match_baselines_with_corpus(raw_baselines, corpus)
            paper.baselines = matched
            in_lib_count = sum(1 for m in matched if m.get("in_library"))
            logger.info(
                f"Extracted {len(matched)} baselines for '{paper.title[:35]}' "
                f"({in_lib_count} in library)"
            )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(process_one, papers))
