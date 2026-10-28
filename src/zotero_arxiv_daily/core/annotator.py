"""In-line critical annotation locator, renderer, and interactive @AI follow-up resolver."""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..protocol import CorpusPaper, Paper
from .textutil import extract_json

logger = logging.getLogger(__name__)

ANNOTATION_STYLES: dict[str, dict[str, Any]] = {
    "baseline": {
        "label": "[基线对比",
        "text_color": 5,        # Blue
        "background_color": 5,  # Light Blue
    },
    "claim": {
        "label": "[核心增量",
        "text_color": 4,        # Green
        "background_color": 4,  # Light Green
    },
    "critique": {
        "label": "[审阅批判",
        "text_color": 2,        # Orange
        "background_color": 2,  # Light Orange
    },
}


def fetch_ar5iv_targeted_sections(arxiv_id_or_url: str, max_chars: int = 8500) -> dict[str, str]:
    """Compatibility wrapper delegating to digest.fetch_arxiv_targeted_sections."""
    from .digest import fetch_arxiv_targeted_sections

    return fetch_arxiv_targeted_sections(arxiv_id_or_url)


def _fuzzy_find_span(text: str, quote: str) -> Optional[tuple[int, int]]:
    """Finds the character span (start, end) of quote inside text."""
    if not text or not quote:
        return None
    q = quote.strip().strip('"\'“”‘’')
    if len(q) < 6:
        return None

    idx = text.find(q)
    if idx != -1:
        return idx, idx + len(q)

    idx_ci = text.lower().find(q.lower())
    if idx_ci != -1:
        return idx_ci, idx_ci + len(q)

    words = [re.escape(w) for w in re.split(r"\s+", q) if w]
    if len(words) >= 3:
        pattern = r"\s+".join(words)
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return m.start(), m.end()

    if len(words) >= 6:
        head = r"\s+".join(words[:3])
        tail = r"\s+".join(words[-3:])
        m = re.search(f"{head}.{{1,240}}?{tail}", text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return m.start(), m.end()

    return None


def locate_spans(text: str, raw_annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolves non-overlapping character spans sorted by position in text."""
    resolved: list[dict[str, Any]] = []
    for item in raw_annotations or []:
        if not isinstance(item, dict):
            continue
        quote = str(item.get("exact_quote") or item.get("quote") or "").strip()
        comment = str(item.get("comment") or "").strip()
        ann_type = str(item.get("type") or "claim").strip().lower()
        if ann_type not in ANNOTATION_STYLES:
            ann_type = "claim"
        if not quote or not comment:
            continue

        span = _fuzzy_find_span(text, quote)
        if not span:
            continue
        start, end = span

        overlaps = any(not (end <= r["start"] or start >= r["end"]) for r in resolved)
        if overlaps:
            continue

        resolved.append(
            {
                "type": ann_type,
                "quote": text[start:end],
                "start": start,
                "end": end,
                "comment": comment,
                "target": str(item.get("target") or "").strip(),
                "baseline_name": str(item.get("baseline_name") or "").strip(),
                "data": item,
            }
        )

    resolved.sort(key=lambda x: x["start"])
    return resolved


def _match_library_doc(
    baseline_name: str,
    corpus: Optional[list[CorpusPaper]],
    client: Any = None,
) -> Optional[dict[str, str]]:
    """Checks if a baseline name matches any paper or tag in the user's library."""
    if not baseline_name:
        return None
    norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", baseline_name.lower())
    if len(norm) < 2:
        return None

    for cp in corpus or []:
        cp_norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", (cp.title or "").lower())
        if norm in cp_norm or cp_norm in norm:
            url = getattr(cp, "url", None) or ""
            if url:
                return {"title": cp.title, "url": url}

    tag_map = getattr(client, "reading_note_tags", None) or {}
    for tag, titles in tag_map.items():
        t_norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", tag.lower())
        if norm == t_norm and titles:
            return {"title": f"#{tag}: {titles[0][:35]}", "url": ""}

    return None


def resolve_inline_ai_followups(
    router: Any,
    title: str,
    abstract: str,
    arxiv_id_or_url: str = "",
    user_queries: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    """Resolves user '@AI:' inline questions against paper abstract + targeted sections."""
    if not user_queries or not getattr(router, "available", False):
        return []

    fulltext_excerpt = ""
    if arxiv_id_or_url:
        secs = fetch_ar5iv_targeted_sections(arxiv_id_or_url)
        fulltext_excerpt = "\n\n".join(v for v in (secs or {}).values() if v)[:7000]

    context = f"Title: {title}\nAbstract:\n{abstract}\n"
    if fulltext_excerpt:
        context += f"\nPaper Full-Text Excerpts (Method & Experiments):\n{fulltext_excerpt}\n"

    q_block = "\n".join(f"{idx + 1}. {q}" for idx, q in enumerate(user_queries[:5]))
    prompt = (
        f"{context}\n"
        f"User Inline Follow-up Questions (@AI):\n{q_block}\n\n"
        "Answer each question directly and rigorously in Chinese (2-4 sentences per question), "
        "citing concrete details, equations, or experimental numbers from the paper text above. "
        "If the paper does not report the requested detail, state that explicitly.\n"
        'Return ONLY valid JSON: {"answers": [{"question": "...", "answer": "..."}]}'
    )
    try:
        raw = (
            router.chat([{"role": "user", "content": prompt}], max_tokens=1000)
            if hasattr(router, "chat")
            else router.complete(
                task="inline_followup",
                prompt=prompt,
                system_prompt="You are a technical co-reader answering specific questions inside a paper margin. Output JSON only.",
                temperature=0.2,
                max_tokens=1000,
                response_json=True,
            )
        )
        parsed = extract_json(raw)
        results: list[dict[str, str]] = []
        for item in parsed.get("answers") or []:
            q = str(item.get("question") or "").strip()
            a = str(item.get("answer") or "").strip()
            if q and a:
                results.append({"question": q, "answer": a})
        return results
    except Exception as exc:
        logger.warning(f"Failed to resolve inline @AI follow-ups for '{title[:40]}': {exc}")
        return []


def build_annotated_text_elements(
    paper: Paper,
    corpus: Optional[list[CorpusPaper]] = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Builds Feishu Docx text_run elements strictly for the paper abstract with inline highlights and notes."""
    sections = getattr(paper, "annotation_sections", None) or []
    abstract_section = next(
        (s for s in sections if s.get("id") == "S1" or "摘要" in str(s.get("title", "")) or "abstract" in str(s.get("title", "")).lower()),
        None,
    )
    source_text = (abstract_section.get("text") if abstract_section else None) or paper.abstract or ""
    source_text = source_text.strip()

    raw_anns = [
        a for a in (getattr(paper, "inline_annotations", None) or [])
        if isinstance(a, dict) and a.get("source", "S1") in ("S1", "", None)
    ]
    spans = locate_spans(source_text, raw_anns)
    if not spans:
        return [{"text_run": {"content": f"【摘要】\n{source_text}\n"}}]

    elements: list[dict[str, Any]] = [
        {
            "text_run": {
                "content": "【摘要】原文与审阅批注 (蓝基线 / 绿贡献 / 橙质疑):\n",
                "text_element_style": {"bold": True},
            }
        }
    ]

    cursor = 0
    for idx, sp in enumerate(spans, start=1):
        start, end = sp["start"], sp["end"]
        if start > cursor:
            elements.append({"text_run": {"content": source_text[cursor:start]}})

        style_cfg = ANNOTATION_STYLES.get(sp["type"], ANNOTATION_STYLES["claim"])
        bg_color = style_cfg["background_color"]
        txt_color = style_cfg["text_color"]

        elements.append(
            {
                "text_run": {
                    "content": f"{source_text[start:end]} [注{idx}]",
                    "text_element_style": {
                        "background_color": bg_color,
                        "bold": True,
                    },
                }
            }
        )

        badge_prefix = style_cfg["label"]
        target_str = f" · {sp['target']}" if sp.get("target") else ""
        elements.append(
            {
                "text_run": {
                    "content": f"\n  -> {badge_prefix} #{idx}{target_str}] ",
                    "text_element_style": {
                        "bold": True,
                        "text_color": txt_color,
                    },
                }
            }
        )
        elements.append(
            {
                "text_run": {
                    "content": sp["comment"],
                    "text_element_style": {
                        "italic": True,
                        "text_color": txt_color,
                    },
                }
            }
        )

        b_name = sp.get("baseline_name") or (sp.get("target") if sp["type"] == "baseline" else "")
        lib_match = _match_library_doc(b_name, corpus, client=client) if b_name else None
        if lib_match and lib_match.get("url"):
            elements.append({"text_run": {"content": " | 关联笔记: ", "text_element_style": {"text_color": txt_color}}})
            elements.append(
                {
                    "text_run": {
                        "content": f"《{lib_match['title']}》",
                        "text_element_style": {
                            "link": {"url": lib_match["url"]},
                            "text_color": txt_color,
                        },
                    }
                }
            )
        elements.append({"text_run": {"content": "\n"}})
        cursor = end

    if cursor < len(source_text):
        elements.append({"text_run": {"content": source_text[cursor:] + "\n"}})

    return elements
