"""In-line text annotator: highlights and comments directly inside paper paragraphs."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib.parse import quote

import requests
from loguru import logger

from .baseline import match_baselines_with_corpus
from .llm import LLMRouter
from .protocol import CorpusPaper, Paper


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
) -> list[dict[str, Any]]:
    """Extracts exact quote spans and inline annotations (baseline, claim, critique, counter) from paper abstract."""
    if not router.available or not paper.abstract:
        return []

    q_list = "\n".join(f"- {q}" for q in questions) if questions else "None"

    prompt = (
        "Annotate this research abstract directly with inline notes.\n\n"
        f"Title: {paper.title}\n"
        f"Abstract:\n{paper.abstract}\n\n"
        f"Tracked Questions:\n{q_list}\n\n"
        "Identify 2 to 5 exact quotes from the abstract across 4 categories:\n"
        "1. baseline: exact phrase mentioning baseline methods (e.g. ReAct, MemGPT). Include canonical name, standard venue (e.g. ICLR 2023), and 1-sentence Chinese method mechanism.\n"
        "2. claim: exact sentence that provides empirical results or mechanisms answering a tracked question. Include 1-sentence Chinese answer.\n"
        "3. critique: exact phrase of limitation, synthetic scope, or unverified assumption. Include 1-sentence Chinese critical review.\n"
        "4. counter: exact phrase presenting counter-evidence, negative results, or challenging a premise or baseline. Include 1-sentence Chinese counter analysis.\n\n"
        "Return JSON array ONLY:\n"
        "[\n"
        '  {"quote": "exact phrase from abstract", "type": "baseline", "name": "MemGPT", "venue": "arXiv 2023", "comment": "借鉴OS分页管理大模型记忆"},\n'
        '  {"quote": "exact phrase from abstract", "type": "claim", "comment": "选择性遗忘在多轮对话下降低漂移24%"},\n'
        '  {"quote": "exact phrase from abstract", "type": "critique", "comment": "仅在合成环境测试，真实人机交互泛化性存疑"},\n'
        '  {"quote": "exact phrase from abstract", "type": "counter", "comment": "在长序列消融中观察到上下文重叠导致注意力坍塌"}\n'
        "]"
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
            max_tokens=1500,
            temperature=0.1,
            timeout=50,
        )
        match = re.search(r"(\[.*\])", raw, flags=re.DOTALL)
        if not match:
            return []
        data = json.loads(match.group(1))
        valid = []
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and item.get("quote") and item.get("comment"):
                    valid.append({
                        "quote": str(item["quote"]).strip(),
                        "type": str(item.get("type", "critique")).strip(),
                        "name": str(item.get("name", "")).strip(),
                        "venue": str(item.get("venue", "")).strip(),
                        "comment": str(item["comment"]).strip(),
                    })
        return valid[:5]
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
            clean_q = re.sub(r"\s+", r"\\s+", re.escape(quote_str))
            m = re.search(clean_q, text, re.IGNORECASE)
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
    text = (paper.abstract or "").strip()
    if not text:
        return []

    annotations = getattr(paper, "inline_annotations", None) or []
    if not annotations:
        return [{"text_run": {"content": f"📄 英文摘要 (Abstract):\n{text}\n"}}]

    # Enrich baseline annotations with corpus match
    corpus = corpus or []
    for ann in annotations:
        if ann.get("type") == "baseline" and ann.get("name"):
            matched = match_baselines_with_corpus([ann], corpus)
            if matched:
                ann.update(matched[0])
                if client and ann.get("in_library") and ann.get("obj_token") and hasattr(client, "append_baseline_backlink"):
                    client.append_baseline_backlink(
                        ann["obj_token"],
                        referring_paper_title=paper.title,
                        referring_paper_url=paper.url or "",
                        comparison=ann.get("comment", ""),
                    )

    located = locate_spans(text, annotations)
    if not located:
        return [{"text_run": {"content": f"📄 英文摘要 (Abstract):\n{text}\n"}}]

    elements: list[dict[str, Any]] = [
        {"text_run": {"content": "📄 论文正文研读与 AI 行内批注 (Annotated Text):\n", "text_element_style": {"bold": True}}}
    ]

    curr = 0
    for s in located:
        if s["start"] > curr:
            elements.append({"text_run": {"content": text[curr : s["start"]]}})

        ann = s["data"]
        ann_type = ann.get("type", "critique")

        # Visual highlights:
        # baseline -> 5 (light green), claim -> 4 (light yellow), counter -> 2 (light red), critique -> 3 (light orange)
        if ann_type == "baseline":
            bg_color = 5
        elif ann_type == "claim":
            bg_color = 4
        elif ann_type == "counter":
            bg_color = 2
        else:
            bg_color = 3

        elements.append({
            "text_run": {
                "content": s["quote"],
                "text_element_style": {
                    "bold": True,
                    "background_color": bg_color,
                },
            }
        })

        # Inline annotation badge
        comment = ann.get("comment", "")
        if ann_type == "baseline":
            venue = f" [{ann['venue']}]" if ann.get("venue") else ""
            elements.append({
                "text_run": {
                    "content": f" 💬[基线: {comment}{venue} | ",
                    "text_element_style": {"text_color": 5, "background_color": 1, "italic": True},
                }
            })
            if ann.get("in_library") and ann.get("doc_url"):
                badge_prefix = ann.get("library_badge", "").split(":")[0] + ":" if ":" in ann.get("library_badge", "") else "🟢 已入库:"
                elements.append({
                    "text_run": {
                        "content": f"{badge_prefix} {ann.get('doc_title') or ann.get('name')}",
                        "text_element_style": {
                            "text_color": 5,
                            "background_color": 1,
                            "bold": True,
                            "link": {"url": ann["doc_url"]},
                        },
                    }
                })
            elif ann.get("doc_url"):
                elements.append({
                    "text_run": {
                        "content": "⚪ 出处检索",
                        "text_element_style": {
                            "text_color": 5,
                            "background_color": 1,
                            "link": {"url": ann["doc_url"]},
                        },
                    }
                })
            else:
                elements.append({
                    "text_run": {
                        "content": "⚪ 未入库",
                        "text_element_style": {"text_color": 5, "background_color": 1},
                    }
                })
            elements.append({
                "text_run": {
                    "content": "] ",
                    "text_element_style": {"text_color": 5, "background_color": 1, "italic": True},
                }
            })

        elif ann_type == "claim":
            elements.append({
                "text_run": {
                    "content": f" 🎯[核心发现: {comment}] ",
                    "text_element_style": {
                        "text_color": 2,  # red
                        "background_color": 1,
                        "bold": True,
                    },
                }
            })

        elif ann_type == "counter":
            elements.append({
                "text_run": {
                    "content": f" ⚡[反例证据: {comment}] ",
                    "text_element_style": {
                        "text_color": 2,  # red
                        "background_color": 1,
                        "bold": True,
                    },
                }
            })

        elif ann_type == "critique":
            elements.append({
                "text_run": {
                    "content": f" ⚠️[AI审阅: {comment}] ",
                    "text_element_style": {
                        "text_color": 3,  # orange
                        "background_color": 1,
                        "italic": True,
                    },
                }
            })

        curr = s["end"]

    if curr < len(text):
        elements.append({"text_run": {"content": text[curr:]}})

    elements.append({"text_run": {"content": "\n"}})
    return elements


def enrich_papers_with_inline_annotations(
    router: LLMRouter,
    papers: list[Paper],
    questions: list[str],
    max_workers: int = 4,
) -> None:
    """Extracts inline annotations for recommended papers in parallel."""
    if not router.available or not papers:
        return

    def process_one(paper: Paper) -> None:
        anns = extract_inline_annotations(router, paper, questions)
        if anns:
            paper.inline_annotations = anns
            # Also populate qa_matches for backward compatibility if present
            qa_matches = []
            for a in anns:
                if a.get("type") == "claim" and questions:
                    qa_matches.append({"question": questions[0], "answer": a.get("comment", "")})
            if qa_matches and not paper.qa_matches:
                paper.qa_matches = qa_matches

            logger.info(f"Generated {len(anns)} inline annotations for '{paper.title[:35]}'")

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        list(pool.map(process_one, papers))
