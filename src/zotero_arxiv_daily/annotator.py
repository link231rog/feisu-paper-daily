"""In-line text annotator: highlights and comments directly inside paper paragraphs."""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import requests
from loguru import logger

from .baseline import match_baselines_with_corpus
from .llm import LLMRouter
from .protocol import CorpusPaper, Paper
from .textutil import UNTRUSTED_NOTICE, extract_json


def fetch_ar5iv_targeted_sections(arxiv_id: str) -> dict[str, str]:
    """Fetches structured Method, Experiments & Limitations from ar5iv HTML without heavy PDF OCR."""
    if not arxiv_id:
        return {}

    clean_id = re.sub(r"^arxiv:\s*", "", arxiv_id, flags=re.IGNORECASE).strip()
    url = f"https://ar5iv.labs.arxiv.org/html/{clean_id}"
    try:
        resp = requests.get(url, timeout=12)
        if resp.status_code != 200:
            return {}
        html = resp.text
        sections = {"method": "", "experiments": "", "limitations": ""}
        # Lightweight section regex parser
        sec_pattern = re.compile(
            r'<(?:section|div)[^>]*(?:class=["\'][^"\']*(?:ltx_section|ltx_subsection)[^"\']*)[^>]*>(.*?)</(?:section|div)>',
            re.DOTALL | re.IGNORECASE,
        )
        for match in sec_pattern.finditer(html):
            chunk = match.group(1)
            # Find heading
            h_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', chunk, re.DOTALL | re.IGNORECASE)
            heading = re.sub(r'<[^>]+>', ' ', h_match.group(1)).strip().lower() if h_match else ""
            body = re.sub(r'<[^>]+>', ' ', chunk).strip()[:5000]
            if any(k in heading for k in ("method", "approach", "architecture", "framework")):
                sections["method"] += body + "\n"
            elif any(k in heading for k in ("experiment", "evaluation", "ablation", "result")):
                sections["experiments"] += body + "\n"
            elif any(k in heading for k in ("limitation", "discussion", "failure", "conclusion")):
                sections["limitations"] += body + "\n"
        return sections
    except Exception as exc:
        logger.debug(f"ar5iv section fetch skipped for {clean_id}: {exc}")
        return {}


def extract_inline_annotations(
    router: LLMRouter,
    paper: Paper,
    questions: list[str],
    use_ar5iv: bool = False,
) -> list[dict[str, Any]]:
    """Extracts exact quote spans and inline annotations (baseline, claim, critique, counter) from paper abstract.
    Full-text method & experiment deep analysis is reserved for confirmed ingestion."""
    if not router.available or not paper.abstract:
        return []

    q_list = "\n".join(f"- {i}. {q}" for i, q in enumerate(questions, 1)) if questions else "None"
    sections = [{"id": "S1", "title": "摘要", "text": paper.abstract.strip()}]
    if use_ar5iv:
        arxiv_id = paper.arxiv_id
        if not arxiv_id and paper.url and "arxiv.org" in paper.url:
            m = re.search(r"(\d{4}\.\d{4,5})", paper.url)
            if m:
                arxiv_id = m.group(1)
        if arxiv_id:
            fetched = fetch_ar5iv_targeted_sections(arxiv_id)
            for key, title in (("method", "方法"), ("experiments", "实验"), ("limitations", "局限与讨论")):
                text = fetched.get(key, "").strip()
                if text:
                    sections.append({"id": f"S{len(sections) + 1}", "title": title, "text": text[:5000]})
    paper.annotation_sections = sections
    source_text = "\n\n".join(f"[{s['id']}] {s['title']}\n{s['text']}" for s in sections)
    source_text = f"<untrusted_source>\n{source_text}\n</untrusted_source>"

    prompt = (
        "Annotate the supplied abstract inline. Each comment must immediately follow the exact source sentence or phrase it discusses.\n"
        f"{UNTRUSTED_NOTICE}\n\n"
        f"Title: {paper.title}\n{source_text}\n\n"
        f"Tracked Questions:\n{q_list}\n\n"
        "Return 0 to 4 high-value annotations on the abstract (ideally 2 to 3). Do not annotate trivial background sentences; select ONLY key claims, surprising counter-findings, or pivotal baselines.\n"
        "For each annotation, 'source' is 'S1' and 'quote' is a contiguous, case-insensitive substring of THAT section, copied verbatim, ideally one sentence or a phrase of at most about 35 words (never a whole paragraph). Never attach a comment to a different sentence.\n"
        "Categories:\n"
        "- baseline: a method actually named in the source as a comparison or foundation. Do not add baselines from memory.\n"
        "- claim: a mechanism or empirical result that directly answers a tracked question. Include its question number.\n"
        "- critique: an explicit limitation, restricted evaluation scope or assumption visible in the quote. A reviewer inference must be explicitly labeled '推断'.\n"
        "- counter: only a reported result that directly contradicts another claim or a tracked hypothesis. An ordinary limitation is NOT counter-evidence.\n"
        "Do not infer missing experiments, venues, numbers or comparisons. Prefer no annotation over a speculative one.\n\n"
        'Return ONLY JSON: [{"source":"S1", "quote":"exact source substring", "type":"claim", "name":"", "venue":"", "question":1, "comment":"中文批注", "inference":false}]'
    )

    try:
        raw = router.chat(
            [
                {
                    "role": "system",
                    "content": "You are an expert academic annotator. Output JSON directly with minimal thinking.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=2500,
            temperature=0.1,
            timeout=60,
        )
        data = extract_json(raw, None)
        if isinstance(data, dict):
            # Some models wrap the array: {"annotations": [...]}
            data = next((v for v in data.values() if isinstance(v, list)), None)
        valid = []
        returned = 0
        unlocated = 0
        if isinstance(data, list):
            returned = len(data)
            for item in data:
                if not isinstance(item, dict) or not item.get("quote") or not item.get("comment"):
                    continue
                quote_text = str(item["quote"]).strip()
                ann_type = str(item.get("type", "")).strip()
                if ann_type not in {"baseline", "claim", "critique", "counter"}:
                    continue
                source = str(item.get("source", "S1")).strip()
                section = next((s for s in sections if s["id"] == source), None)
                if section is None or not locate_spans(section["text"], [{"quote": quote_text, "type": ann_type}]):
                    unlocated += 1
                    continue
                question = item.get("question")
                if ann_type == "claim":
                    if not isinstance(question, int) or not 1 <= question <= len(questions):
                        continue
                else:
                    question = None
                valid.append({
                    "source": source,
                    "quote": quote_text,
                    "type": ann_type,
                    "name": str(item.get("name", "")).strip(),
                    "venue": str(item.get("venue", "")).strip(),
                    "question": questions[question - 1] if question else None,
                    "comment": str(item["comment"]).strip(),
                    "inference": bool(item.get("inference", False)),
                })
        if returned and len(valid) < returned:
            logger.info(
                f"Annotations for '{paper.title[:35]}': {returned} returned, {len(valid)} kept, "
                f"{unlocated} quote(s) not found in source"
            )
        elif not returned:
            logger.info(f"Annotations for '{paper.title[:35]}': model returned none usable")
        return valid[:8]
    except Exception as exc:
        logger.warning(f"Failed to extract inline annotations for '{paper.title}': {exc}")
        return []


def locate_spans(text: str, annotations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Locates non-overlapping character offsets for annotations in text."""
    spans = []
    text_lower = text.lower()

    for ann in annotations:
        quote_str = ann.get("quote", "").strip()
        if not quote_str:
            continue

        # 1. Exact match
        idx = text.find(quote_str)
        matched_len = len(quote_str)

        # 2. Case-insensitive match
        if idx == -1:
            idx = text_lower.find(quote_str.lower())

        # 3. Normalized whitespace regex match
        if idx == -1:
            parts = [re.escape(part) for part in quote_str.split()]
            m = re.search(r"\s+".join(parts), text, re.IGNORECASE) if parts else None
            if m:
                idx = m.start()
                matched_len = len(m.group(0))

        # 4. Fallback for baselines: search baseline name directly
        if idx == -1 and ann.get("type") == "baseline" and ann.get("name"):
            for b_name in ann["name"].split(";"):
                b_clean = b_name.strip()
                if b_clean and len(b_clean) >= 3:
                    m = re.search(rf"\b{re.escape(b_clean)}\b", text, re.IGNORECASE)
                    if m:
                        idx = m.start()
                        matched_len = len(m.group(0))
                        break

        if idx != -1:
            spans.append({
                "start": idx,
                "end": idx + matched_len,
                "quote": text[idx : idx + matched_len],
                "data": ann,
            })

    # Sort by start offset
    spans.sort(key=lambda s: s["start"])

    # Discard overlapping spans
    filtered = []
    last_end = 0
    for s in spans:
        if s["start"] >= last_end:
            filtered.append(s)
            last_end = s["end"]

    return filtered


def build_annotated_text_elements(
    paper: Paper,
    corpus: list[CorpusPaper] | None = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Builds Feishu Docx elements with inline text highlights and comment badges."""
    sections = paper.annotation_sections or [{"id": "S1", "title": "摘要", "text": (paper.abstract or "").strip()}]
    annotations = getattr(paper, "inline_annotations", None) or []
    if not sections:
        return []

    corpus = corpus or []
    for ann in annotations:
        if ann.get("type") == "baseline" and ann.get("name"):
            matched = match_baselines_with_corpus([ann], corpus)
            if matched:
                ann.update(matched[0])
                if (
                    client
                    and ann.get("in_library")
                    and ann.get("library_source") == "feishu"
                    and ann.get("obj_token")
                    and hasattr(client, "append_baseline_backlink")
                ):
                    client.append_baseline_backlink(
                        ann["obj_token"], referring_paper_title=paper.title,
                        referring_paper_url=paper.url or "", comparison=ann.get("comment", ""),
                    )

    located_by_source: dict[str, list[dict]] = {}
    for section in sections:
        source_annotations = [a for a in annotations if a.get("source", "S1") == section["id"]]
        located_by_source[section["id"]] = locate_spans(section["text"], source_annotations)

    abstract_section = next((s for s in sections if s.get("id") == "S1" or s.get("title") == "摘要"), None)
    abstract_located = located_by_source.get("S1") or []
    if not abstract_section or not abstract_located:
        return [{"text_run": {"content": f"📄 英文摘要 (Abstract):\n{paper.abstract or ''}\n"}}]

    elements: list[dict[str, Any]] = [
        {"text_run": {"content": "📄 原文与核心洞察批注：\n", "text_element_style": {"bold": True}}}
    ]
    elements.append({"text_run": {"content": f"\n【{abstract_section.get('title', '摘要')}】\n", "text_element_style": {"bold": True}}})

    # 1. Continuous clean abstract text with light highlight on quotes
    text = abstract_section["text"]
    curr = 0
    for s in abstract_located:
        if s["start"] > curr:
            elements.append({"text_run": {"content": text[curr:s["start"]]}})
        ann_type = s["data"].get("type", "critique")
        # 5: Green/teal (baseline), 4: Yellow/gold (claim), 2: Coral/red (counter), 3: Light orange (critique)
        bg_color = {"baseline": 5, "claim": 4, "counter": 2}.get(ann_type, 3)
        elements.append({
            "text_run": {
                "content": s["quote"],
                "text_element_style": {"background_color": bg_color, "bold": True},
            }
        })
        curr = s["end"]
    if curr < len(text):
        elements.append({"text_run": {"content": text[curr:]}})
    elements.append({"text_run": {"content": "\n\n"}})

    # 2. Structured, readable notes grouped neatly below the abstract
    elements.append({
        "text_run": {
            "content": "💡 AI 审阅与证据解读：\n",
            "text_element_style": {"bold": True, "text_color": 1},
        }
    })
    for s in abstract_located:
        elements.extend(_render_note_bullet_elements(s))
    elements.append({"text_run": {"content": "\n"}})

    return elements


def _render_note_bullet_elements(s: dict[str, Any]) -> list[dict[str, Any]]:
    """Renders one clean, bullet-styled note with quote anchor and commentary."""
    elements: list[dict[str, Any]] = []
    ann = s["data"]
    ann_type = ann.get("type", "critique")

    badge_info = {
        "claim": ("🎯", "核心发现", 4),
        "counter": ("⚡", "反例/局限证据", 2),
        "critique": ("⚠️", "AI 审阅", 3),
        "baseline": ("💬", "对比基线", 5),
    }.get(ann_type, ("💡", "分析批注", 1))

    icon, type_label, tag_color = badge_info
    comment = ann.get("comment", "").strip()
    if ann.get("inference") and "推断" not in comment:
        comment = f"推断：{comment}"

    # Bullet point line: • 🎯 [核心发现] Quote: "..." -> Comment
    elements.append({"text_run": {"content": f"  • {icon} [{type_label}] ", "text_element_style": {"bold": True, "text_color": tag_color}}})

    # Short quote anchor (truncated if long)
    quote_display = s["quote"].strip()
    if len(quote_display) > 60:
        quote_display = quote_display[:57] + "..."
    elements.append({
        "text_run": {
            "content": f'"{quote_display}"',
            "text_element_style": {"italic": True, "background_color": tag_color},
        }
    })
    elements.append({"text_run": {"content": " ➔ ", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"{comment}"}})

    # Baselines specific linking
    if ann_type == "baseline":
        venue = f" [{ann['venue']}]" if ann.get("venue") else ""
        if ann.get("in_library") and ann.get("doc_url"):
            badge_prefix = ann.get("library_badge", "").split(":")[0] + ":" if ":" in ann.get("library_badge", "") else "🟢 已入库:"
            elements.append({
                "text_run": {
                    "content": f" ({badge_prefix} {ann.get('doc_title') or ann.get('name')}{venue})",
                    "text_element_style": {"bold": True, "link": {"url": ann["doc_url"]}},
                }
            })
        elif ann.get("doc_url"):
            elements.append({
                "text_run": {
                    "content": f" (⚪ 出处检索{venue})",
                    "text_element_style": {"link": {"url": ann["doc_url"]}},
                }
            })
    elements.append({"text_run": {"content": "\n"}})
    return elements


def resolve_inline_ai_followups(
    router: LLMRouter,
    title: str,
    abstract: str,
    arxiv_id_or_url: str,
    user_queries: list[str],
) -> list[dict[str, str]]:
    """Resolves @AI inline questions injected by the user in Feishu / Obsidian / Notion."""
    if not router.available or not user_queries:
        return []

    arxiv_id = ""
    m = re.search(r"(\d{4}\.\d{4,5})", arxiv_id_or_url or "")
    if m:
        arxiv_id = m.group(1)

    secs = fetch_ar5iv_targeted_sections(arxiv_id) if arxiv_id else {}
    context_parts = [f"Title: {title}", f"Abstract: {abstract}"]
    if secs.get("method"):
        context_parts.append(f"Method Section:\n{secs['method'][:3500]}")
    if secs.get("experiments"):
        context_parts.append(f"Experiments Section:\n{secs['experiments'][:4000]}")
    if secs.get("limitations"):
        context_parts.append(f"Limitations Section:\n{secs['limitations'][:2500]}")

    context_str = "\n\n".join(context_parts)
    results: list[dict[str, str]] = []

    for q in user_queries:
        prompt = (
            "You are answering a researcher's inline follow-up question (@AI) inside a paper reading document.\n\n"
            f"{context_str}\n\n"
            f"Researcher's Question: {q}\n\n"
            "Provide a concise, grounded Chinese answer (80-160 字). Cite specific experimental settings, "
            "metrics, or section details if present in the paper context; if not explicitly stated in the text, "
            "state that clearly."
        )
        try:
            ans = router.chat([{"role": "user", "content": prompt}], max_tokens=800, temperature=0.2)
            if ans and ans.strip():
                results.append({"question": q, "answer": ans.strip()})
        except Exception as exc:
            logger.warning(f"Failed to resolve @AI query '{q}' for '{title}': {exc}")
    return results


def enrich_papers_with_inline_annotations(
    router: LLMRouter,
    papers: list[Paper],
    questions: list[str],
    max_workers: int = 4,
    use_ar5iv: bool = True,
) -> None:
    """Extracts inline annotations for recommended papers in parallel."""
    if not router.available or not papers:
        return

    def process_one(paper: Paper) -> None:
        anns = extract_inline_annotations(router, paper, questions, use_ar5iv=use_ar5iv)
        if anns:
            paper.inline_annotations = anns
            # Preserve the claim's actual question; never default to the first question.
            qa_matches = [
                {"question": a["question"], "answer": a["comment"]}
                for a in anns
                if a.get("type") == "claim" and a.get("question")
            ]
            if qa_matches:
                existing = {(m.get("question"), m.get("answer")) for m in paper.qa_matches or []}
                paper.qa_matches = (paper.qa_matches or []) + [
                    m for m in qa_matches if (m["question"], m["answer"]) not in existing
                ]

            logger.info(f"Generated {len(anns)} inline annotations for '{paper.title[:35]}'")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(process_one, papers))
