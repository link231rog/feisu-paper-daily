"""Shared daily report for email and WeChat Official Account drafts."""

from dataclasses import dataclass, field
from datetime import date
from html import escape
from pathlib import Path
import re
from typing import Any

from ..core.annotator import locate_spans
from ..protocol import Paper


@dataclass
class DailyReport:
    title: str
    html: str
    digest: str
    inline_images: dict[str, str] = field(default_factory=dict)


def _text(value: object, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _inline_annotated_html(paper: Paper) -> str:
    """Render continuous abstract text followed by structured insight bullets (strictly no icons).
    Full-text method & experiment deep analysis is reserved for confirmed ingestion."""
    sections = paper.annotation_sections or [{"id": "S1", "title": "摘要", "text": paper.abstract or ""}]
    abstract_section = next((s for s in sections if s.get("id") == "S1" or s.get("title") == "摘要"), None)
    if not abstract_section or not abstract_section.get("text"):
        return ""

    annotations = [a for a in (paper.inline_annotations or []) if a.get("source", "S1") == "S1"]
    spans = locate_spans(abstract_section["text"], annotations)
    if not spans:
        return ""

    labels = {"baseline": "基线", "claim": "核心发现", "counter": "反例/局限", "critique": "审阅批判"}
    colors = {"baseline": "#e8f5e9", "claim": "#fff9c4", "counter": "#ffebee", "critique": "#fff3e0"}

    # 1. Clean original abstract with highlighted spans
    text = abstract_section["text"]
    parts = [f"<h3>原文 · {escape(abstract_section.get('title', '摘要'))}</h3><p style='line-height:1.75;color:#333;'>"]
    curr = 0
    for span in spans:
        parts.append(escape(text[curr:span["start"]]))
        ann_type = span["data"].get("type", "critique")
        parts.append(
            f'<mark style="background:{colors.get(ann_type, "#fff3e0")};font-weight:600;">{escape(span["quote"])}</mark>'
        )
        curr = span["end"]
    parts.append(escape(text[curr:]))
    parts.append("</p>")

    # 2. Structured note bullets below the abstract (no icons)
    parts.append("<div style='background:#fafafa;border-left:3px solid #0052cc;padding:8px 12px;margin:10px 0;border-radius:4px;'>")
    parts.append("<strong style='color:#0052cc;'>AI 审阅与证据解读：</strong><ul style='margin:4px 0 0 0;padding-left:18px;'>")
    for span in spans:
        ann = span["data"]
        ann_type = ann.get("type", "critique")
        comment = _text(ann.get("comment", ""))
        if ann.get("inference") and "推断" not in comment:
            comment = f"推断：{comment}"
        quote_sub = span["quote"].strip()
        if len(quote_sub) > 50:
            quote_sub = quote_sub[:47] + "..."

        label = labels.get(ann_type, "审阅批注")
        parts.append(
            f"<li style='margin-bottom:4px;'><strong>[{label}]</strong> "
            f"<span style='background:{colors.get(ann_type, '#fff3e0')};font-style:italic;'>\"{escape(quote_sub)}\"</span>"
            f" -> {escape(comment)}</li>"
        )
    parts.append("</ul></div>")
    return "".join(parts)


def build_daily_report(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    report_date: date | None = None,
    max_chars: int | None = None,
    trending_items: list | None = None,
    include_posters: bool = True,
) -> DailyReport:
    """Build a self-contained report; max_chars is only needed by WeChat."""
    report_date = report_date or date.today()
    title = f"论文研究日报 {report_date:%Y-%m-%d}"
    header = [
        '<section style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;color:#222;line-height:1.7">',
        f"<h1>{escape(title)}</h1>",
        f"<p>今日精选 {len(papers)} 篇论文，附研究问题进展与 AI 批注。</p>",
    ]
    footer = ["<p>由 Feishu Paper Daily 自动生成，请核验论文原文。</p>", "</section>"]
    inline_images: dict[str, str] = {}

    brief_parts = []
    for brief in question_briefs or []:
        item = [f"<h2>研究问题：{escape(_text(brief.get('question'), 300))}</h2>"]
        if brief.get("summary"):
            item.append(f"<p>{escape(_text(brief['summary']))}</p>")
        if brief.get("status"):
            item.append(f"<p><strong>状态：</strong>{escape(_text(brief['status'], 30))}</p>")
        if brief.get("counter_evidence"):
            names = "；".join(_text(e.get("title"), 160) for e in brief["counter_evidence"])
            item.append(f"<p><strong>反例：</strong>{escape(names)}</p>")
        if brief.get("gap"):
            item.append(f"<p><strong>待验证：</strong>{escape(_text(brief['gap'], 500))}</p>")
        block = "".join(item)
        if max_chars is None or len("".join(header + brief_parts + [block] + footer)) <= max_chars:
            brief_parts.append(block)

    content_parts = brief_parts
    for item in trending_items or []:
        block = [f"<h2>AI 动态：{escape(_text(item.title, 300))}</h2>"]
        if item.url:
            block.append(f'<p><a href="{escape(item.url, quote=True)}">查看原文</a></p>')
        if item.summary_zh or item.description:
            block.append(f"<p>{escape(_text(item.summary_zh or item.description, 2000))}</p>")
        block_html = "".join(block)
        if max_chars is None or len("".join(header + content_parts + [block_html] + footer)) <= max_chars:
            content_parts.append(block_html)

    omitted = 0
    for index, paper in enumerate(papers, 1):
        tier = getattr(paper, "recommendation_tier", None) or "deep_read"
        tier_badge = "[精读必看]" if tier == "deep_read" else "[速览雷达]"
        item = [f"<h2>{index}. {tier_badge} {escape(_text(paper.title, 500))}</h2>"]
        if paper.authors:
            item.append(f"<p>{escape(_text(', '.join(paper.authors), 500))}</p>")
        if paper.url:
            url = escape(paper.url, quote=True)
            item.append(f'<p><a href="{url}">查看论文原文</a></p>')

        poster_path = getattr(paper, "poster_path", None)
        if include_posters and poster_path and Path(poster_path).is_file():
            clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(getattr(paper, "arxiv_id", "") or f"paper_{index}")).strip("_")
            cid = f"poster_{index}_{clean_slug}"
            inline_images[cid] = str(poster_path)
            item.append(
                f'<div style="margin:16px 0 20px 0;text-align:center;">'
                f'<img src="cid:{cid}" style="max-width:100%;height:auto;border-radius:8px;border:1px solid #e1e4e8;box-shadow:0 2px 10px rgba(0,0,0,0.06);display:block;margin:0 auto;" alt="方法架构与流程图" />'
                f'<p style="margin:6px 0 0 0;font-size:12px;color:#6a737d;line-height:1.4;">▲ 方法架构与核心流程图 (Framework / Pipeline Overview)</p>'
                f'</div>'
            )

        if getattr(paper, "critical_digest", None):
            from ..core.digest import format_digest_html
            item.append(format_digest_html(paper))
        else:
            if paper.tldr:
                item.append(f"<p><strong>核心摘要：</strong>{escape(_text(paper.tldr, 3000))}</p>")
            if paper.judge_reason:
                item.append(f"<p><strong>推荐理由：</strong>{escape(_text(paper.judge_reason))}</p>")

        if tier == "deep_read":
            annotated_html = _inline_annotated_html(paper)
            if annotated_html:
                item.append(annotated_html)
            elif not getattr(paper, "critical_digest", None):
                for qa in paper.qa_matches or []:
                    item.append(
                        f"<p><strong>[{escape(_text(qa.get('question'), 300))}]</strong><br>"
                        f"{escape(_text(qa.get('answer')))}</p>"
                    )
        else:
            annotated_html = _inline_annotated_html(paper)
            if annotated_html:
                item.append(annotated_html)
            elif not getattr(paper, "critical_digest", None):
                for qa in (paper.qa_matches or [])[:2]:
                    item.append(
                        f"<p><strong>[{escape(_text(qa.get('question'), 300))}]</strong>："
                        f"{escape(_text(qa.get('answer')))}</p>"
                    )
        block = "".join(item)
        if max_chars is not None:
            size = len("".join(header + content_parts + [block] + footer))
            if size > max_chars:
                omitted = len(papers) - index + 1
                break
        content_parts.append(block)

    if omitted:
        notice = f"<p>另有 {omitted} 篇论文因公众号篇幅限制未收录，请查看邮件日报。</p>"
        if len("".join(header + content_parts + [notice] + footer)) <= max_chars:
            content_parts.append(notice)
    html = "".join(header + content_parts + footer)
    digest = f"今日精选 {len(papers)} 篇论文，{len(question_briefs or [])} 个研究问题有新进展。"[:120]
    return DailyReport(title=title[:32], html=html, digest=digest, inline_images=inline_images)
