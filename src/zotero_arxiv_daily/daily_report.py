"""Shared daily report for email and WeChat Official Account drafts."""

from dataclasses import dataclass
from datetime import date
from html import escape

from .annotator import locate_spans
from .protocol import Paper


@dataclass
class DailyReport:
    title: str
    html: str
    digest: str


def _text(value: object, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _inline_annotated_html(paper: Paper) -> str:
    """Render source sentences with their comments immediately after the matching span."""
    sections = paper.annotation_sections or [{"id": "S1", "title": "摘要", "text": paper.abstract or ""}]
    rendered = []
    labels = {"baseline": "基线", "claim": "核心发现", "counter": "反例证据", "critique": "AI 审阅"}
    colors = {"baseline": "#e8f5e9", "claim": "#fff9c4", "counter": "#ffebee", "critique": "#fff3e0"}
    for section in sections:
        annotations = [a for a in (paper.inline_annotations or []) if a.get("source", "S1") == section["id"]]
        spans = locate_spans(section["text"], annotations)
        if not spans:
            continue
        parts = [f"<h3>原文 · {escape(section['title'])}</h3><p>"]
        curr = 0
        for span in spans:
            parts.append(escape(section["text"][curr:span["start"]]))
            ann = span["data"]
            comment = _text(ann["comment"])
            if ann.get("inference") and "推断" not in comment:
                comment = f"推断：{comment}"
            parts.append(
                f'<mark style="background:{colors.get(ann["type"], "#fff3e0")}">{escape(span["quote"])}</mark>'
                f"<strong>［{labels.get(ann['type'], 'AI 批注')}：{escape(comment)}］</strong>"
            )
            curr = span["end"]
        parts.append(escape(section["text"][curr:]))
        parts.append("</p>")
        rendered.append("".join(parts))
    return "".join(rendered)


def build_daily_report(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    report_date: date | None = None,
    max_chars: int | None = None,
    trending_items: list | None = None,
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
        item = [f"<h2>{index}. {escape(_text(paper.title, 500))}</h2>"]
        if paper.authors:
            item.append(f"<p>{escape(_text(', '.join(paper.authors), 500))}</p>")
        if paper.url:
            url = escape(paper.url, quote=True)
            item.append(f'<p><a href="{url}">查看论文原文</a></p>')
        if paper.tldr:
            item.append(f"<p><strong>核心摘要：</strong>{escape(_text(paper.tldr, 3000))}</p>")
        if paper.judge_reason:
            item.append(f"<p><strong>推荐理由：</strong>{escape(_text(paper.judge_reason))}</p>")
        annotated_html = _inline_annotated_html(paper)
        if annotated_html:
            item.append(annotated_html)
        else:
            for qa in paper.qa_matches or []:
                item.append(
                    f"<p><strong>{escape(_text(qa.get('question'), 300))}</strong><br>"
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
    return DailyReport(title=title[:32], html=html, digest=digest)
