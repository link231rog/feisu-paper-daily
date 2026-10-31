"""Unified Markdown-first daily report engine for Email, WeChat, and literature archives.

Features:
1. Markdown-first architecture: compiles the entire report into standard academic Markdown.
2. User-customizable templates: loads from `templates/daily_report.md` (or custom configured path),
   falling back to a built-in default template.
3. High-compatibility HTML rendering: translates Markdown into fully inlined, mobile-friendly HTML
   with CID image anchors via Python `markdown` and `premailer`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from html import escape
import os
from pathlib import Path
import re
from typing import Any

import jinja2
from loguru import logger
import markdown
import premailer

from ..core.annotator import locate_spans
from ..core.digest import format_rubric_summary_line
from ..protocol import Paper

DEFAULT_EMAIL_CSS = """
body, section {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    color: #24292e;
    line-height: 1.68;
    font-size: 14.5px;
    max-width: 780px;
    margin: 0 auto;
    padding: 20px 16px;
    background-color: #ffffff;
}
h1 {
    font-size: 22px;
    font-weight: 700;
    color: #0052cc;
    border-bottom: 2px solid #eaecef;
    padding-bottom: 8px;
    margin-top: 0;
    margin-bottom: 16px;
}
h2 {
    font-size: 17px;
    font-weight: 600;
    color: #1f2328;
    border-bottom: 1px solid #eaecef;
    padding-bottom: 6px;
    margin-top: 26px;
    margin-bottom: 12px;
}
h3 {
    font-size: 15px;
    font-weight: 600;
    color: #24292e;
    margin-top: 16px;
    margin-bottom: 8px;
}
p {
    margin: 8px 0;
}
blockquote {
    border-left: 3.5px solid #0052cc;
    background-color: #f8fafc;
    color: #1e293b;
    padding: 10px 14px;
    margin: 12px 0;
    border-radius: 4px;
    font-size: 13.5px;
    line-height: 1.6;
}
blockquote p {
    margin: 4px 0;
}
code {
    background-color: rgba(175, 184, 193, 0.2);
    padding: 2px 5px;
    border-radius: 4px;
    font-family: ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    font-size: 85%;
    color: #0969da;
}
pre {
    background-color: #f6f8fa;
    padding: 12px;
    border-radius: 6px;
    overflow-x: auto;
}
pre code {
    background: none;
    padding: 0;
    color: inherit;
}
a {
    color: #0052cc;
    text-decoration: none;
}
a:hover {
    text-decoration: underline;
}
hr {
    border: 0;
    border-top: 1px solid #e1e4e8;
    margin: 24px 0;
}
ul, ol {
    padding-left: 20px;
    margin: 8px 0;
}
li {
    margin-bottom: 4px;
}
img {
    max-width: 100%;
    height: auto;
    border-radius: 6px;
    border: 1px solid #e1e4e8;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
    display: block;
    margin: 12px auto;
}
table {
    border-collapse: collapse;
    width: 100%;
    margin: 14px 0;
}
th, td {
    border: 1px solid #d0d7de;
    padding: 6px 10px;
    font-size: 13px;
}
th {
    background-color: #f6f8fa;
    font-weight: 600;
}
"""

DEFAULT_MARKDOWN_TEMPLATE = """# {{ title }}

> 今日精选 {{ papers|length }} 篇前沿学术文献，附研究问题进展与多模态架构解析。

{% if question_briefs %}
## ❓ 今日问题进展
{% for brief in question_briefs %}
### {{ loop.index }}. {{ brief.question }}
- **核心进展**：{{ brief.summary }}
- **收敛状态**：`{{ brief.status }}`
{% if brief.counter_evidence %}- **反例依据**：{{ brief.counter_evidence }}{% endif %}
{% if brief.gap %}- **待验证缺口**：{{ brief.gap }}{% endif %}

{% endfor %}
{% endif %}

{% if trending_items %}
## ⚡ AI 动态与开源热点
{% for item in trending_items %}
### [{{ item.title }}]({{ item.url }})
{{ item.summary }}

{% endfor %}
{% endif %}

## 📚 今日推荐论文
{% for paper in papers %}
### {{ loop.index }}. [{{ paper.tier_badge }}] {{ paper.title }}
- **作者**：{{ paper.authors_str }}
- **原文链接**：[{{ paper.url }}]({{ paper.url }})
{% if paper.code_url %}- **开源代码**：[{{ paper.code_url }}]({{ paper.code_url }}){% endif %}
{% if paper.project_url %}- **项目主页**：[{{ paper.project_url }}]({{ paper.project_url }}){% endif %}

{% if paper.poster_cid %}
![方法架构与核心流程图](cid:{{ paper.poster_cid }})
*▲ 方法架构与核心流程图 (Framework / Pipeline Overview)*
{% endif %}

{% if paper.has_digest %}
> **[审稿评级]**：**{{ paper.review_badge }}** *(复用度: {{ paper.r_grade }} | 证据支撑: {{ paper.s_grade }} | 基线公平: {{ paper.f_grade }})*
{% if paper.rubric_summary %}> **[四维评分]**：{{ paper.rubric_summary }}{% endif %}
> - **核心增量 (Delta)**：{{ paper.delta }}
> - **方法链路 (Mechanism)**：`{{ paper.pipeline }}`
{% if paper.core_formula and paper.core_formula != 'N/A' and paper.core_formula != 'N/A (需查正文)' %}> - **核心公式**：`{{ paper.core_formula }}`{% endif %}
{% if paper.symbol_dict and paper.symbol_dict != 'N/A' and paper.symbol_dict != 'N/A (需查正文)' %}> - **符号释义**：{{ paper.symbol_dict }}{% endif %}
> - **实验真相 (Truth & Cost)**：{{ paper.truth_metrics }}
{% if paper.truth_costs %}> - **代价与边界**：{{ paper.truth_costs }}{% endif %}
> - **启发与待查**：{{ paper.action_or_check }}
{% else %}
- **核心摘要**：{{ paper.tldr }}
{% if paper.judge_reason %}- **推荐理由**：{{ paper.judge_reason }}{% endif %}
{% endif %}

{% if paper.annotated_markdown %}
{{ paper.annotated_markdown }}
{% endif %}

---
{% endfor %}

> 由 Feishu Paper Daily 自动生成，请核验论文原文。
"""


@dataclass
class DailyReport:
    """Artifact produced by the unified daily report pipeline."""

    title: str
    html: str
    digest: str
    inline_images: dict[str, str] = field(default_factory=dict)
    markdown: str = ""


def _text(value: object, limit: int = 1200) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _inline_annotated_html(paper: Paper) -> str:
    """Render continuous abstract text followed by structured insight bullets (strictly no icons).
    Preserved for backward-compatibility with external callers."""
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


def _inline_annotated_markdown(paper: Paper) -> str:
    """Render structured markdown highlights and insight bullets for a paper."""
    sections = paper.annotation_sections or [{"id": "S1", "title": "摘要", "text": paper.abstract or ""}]
    abstract_section = next((s for s in sections if s.get("id") == "S1" or s.get("title") == "摘要"), None)
    if not abstract_section or not abstract_section.get("text"):
        return ""

    annotations = [a for a in (paper.inline_annotations or []) if a.get("source", "S1") == "S1"]
    spans = locate_spans(abstract_section["text"], annotations)
    if not spans:
        return ""

    labels = {"baseline": "基线", "claim": "核心发现", "counter": "反例/局限", "critique": "审阅批判"}
    lines = ["\n**AI 审阅与证据解读**："]
    for span in spans:
        ann = span["data"]
        ann_type = ann.get("type", "critique")
        comment = _text(ann.get("comment", ""))
        quote_sub = span["quote"].strip()
        if len(quote_sub) > 50:
            quote_sub = quote_sub[:47] + "..."
        label = labels.get(ann_type, "审阅批注")
        lines.append(f"- **[{label}]** *\"{quote_sub}\"* → {comment}")

    return "\n".join(lines)


def _load_report_template(template_path: str | Path | None = None, config: Any = None) -> str:
    """Resolves and loads the markdown report template from path, config, or default fallback."""
    # 1. Direct parameter
    if template_path:
        p = Path(template_path).expanduser()
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8")
            except Exception as exc:
                logger.warning(f"Failed to read custom template from {p}: {exc}")

    # 2. Config options (email.template_path or report.template_path)
    if config:
        cfg_path = None
        if hasattr(config, "get"):
            cfg_path = (config.get("email") or {}).get("template_path") or (config.get("report") or {}).get("template_path")
        elif hasattr(config, "email") and hasattr(config.email, "template_path"):
            cfg_path = config.email.template_path
        if cfg_path:
            p = Path(cfg_path).expanduser()
            if p.is_file():
                try:
                    return p.read_text(encoding="utf-8")
                except Exception as exc:
                    logger.warning(f"Failed to read template from config path {p}: {exc}")

    # 3. Default workspace file (templates/daily_report.md)
    default_file = Path(__file__).resolve().parents[2] / "templates" / "daily_report.md"
    if default_file.is_file():
        try:
            return default_file.read_text(encoding="utf-8")
        except Exception as exc:
            logger.debug(f"Could not read default template file {default_file}: {exc}")

    # 4. In-memory string fallback
    return DEFAULT_MARKDOWN_TEMPLATE


def _prepare_view_models(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    trending_items: list | None = None,
    include_posters: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, str]]:
    """Transforms raw papers, briefs, and trending items into template-ready dictionaries."""
    inline_images: dict[str, str] = {}
    paper_views: list[dict[str, Any]] = []

    for index, p in enumerate(papers, 1):
        tier = getattr(p, "recommendation_tier", None) or "deep_read"
        tier_badge = "精读必看" if tier == "deep_read" else "速览雷达"

        poster_cid: str | None = None
        poster_path = getattr(p, "poster_path", None)
        if include_posters and poster_path and Path(poster_path).is_file():
            clean_slug = re.sub(r"[^a-zA-Z0-9_]", "_", str(getattr(p, "arxiv_id", "") or f"paper_{index}")).strip("_")
            poster_cid = f"poster_{index}_{clean_slug}"
            inline_images[poster_cid] = str(poster_path)

        cd = getattr(p, "critical_digest", None) or {}
        grades = cd.get("qualitative_grades") or {}
        mech = cd.get("mechanism") or {}
        ev = cd.get("evidence_and_cost") or {}

        p_view: dict[str, Any] = {
            "index": index,
            "title": _text(p.title, 500),
            "authors_str": _text(", ".join(p.authors or []), 500),
            "url": p.url or "",
            "code_url": getattr(p, "code_url", None),
            "project_url": getattr(p, "project_url", None),
            "tier": tier,
            "tier_badge": tier_badge,
            "poster_cid": poster_cid,
            "poster_path": str(poster_path) if poster_path else None,
            "has_digest": bool(cd),
            "review_badge": p.review_badge or "[仅作了解]",
            "r_grade": grades.get("method_reusability", {}).get("grade", "N/A"),
            "s_grade": grades.get("claim_support", {}).get("grade", "N/A"),
            "f_grade": grades.get("baseline_fairness", {}).get("grade", "N/A"),
            "rubric_summary": format_rubric_summary_line(p),
            "delta": _text(cd.get("delta") or p.tldr_zh or p.tldr or "暂无核心增量记录", 800),
            "pipeline": _text(mech.get("pipeline", "N/A"), 500),
            "core_formula": _text(mech.get("core_formula", "N/A"), 300),
            "symbol_dict": _text(mech.get("symbol_dict", "N/A"), 500),
            "truth_metrics": _text(ev.get("metrics", "N/A"), 500),
            "truth_costs": _text(ev.get("cost_and_limits", ""), 500),
            "action_or_check": _text(cd.get("action_or_check", "N/A"), 800),
            "tldr": _text(p.tldr or p.abstract or "", 2000),
            "judge_reason": _text(p.judge_reason or "", 500),
            "annotated_markdown": _inline_annotated_markdown(p),
        }
        paper_views.append(p_view)

    brief_views: list[dict[str, Any]] = []
    for b in question_briefs or []:
        counter = "；".join(_text(e.get("title"), 160) for e in b.get("counter_evidence") or [])
        brief_views.append({
            "question": _text(b.get("question"), 300),
            "summary": _text(b.get("summary"), 800),
            "status": _text(b.get("status"), 30),
            "counter_evidence": counter,
            "gap": _text(b.get("gap"), 500),
        })

    trending_views: list[dict[str, Any]] = []
    for t in trending_items or []:
        trending_views.append({
            "title": _text(getattr(t, "title", ""), 300),
            "url": getattr(t, "url", ""),
            "summary": _text(getattr(t, "summary_zh", "") or getattr(t, "description", ""), 1500),
        })

    return paper_views, brief_views, trending_views, inline_images


def render_report_markdown(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    trending_items: list | None = None,
    title: str = "论文研究日报",
    template_path: str | Path | None = None,
    config: Any = None,
    include_posters: bool = True,
) -> tuple[str, dict[str, str]]:
    """Renders structured academic Markdown using Jinja2 and user-customizable templates."""
    paper_views, brief_views, trending_views, inline_images = _prepare_view_models(
        papers,
        question_briefs=question_briefs,
        trending_items=trending_items,
        include_posters=include_posters,
    )

    template_src = _load_report_template(template_path=template_path, config=config)

    # 1. Try Jinja2 rendering
    try:
        env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
        template = env.from_string(template_src)
        rendered_md = template.render(
            title=title,
            papers=paper_views,
            question_briefs=brief_views,
            trending_items=trending_views,
        )
        return rendered_md.strip(), inline_images
    except Exception as exc:
        logger.warning(f"Jinja2 template rendering failed ({exc}); falling back to default template.")

    # 2. Safe fallback to default template
    env = jinja2.Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True)
    template = env.from_string(DEFAULT_MARKDOWN_TEMPLATE)
    rendered_md = template.render(
        title=title,
        papers=paper_views,
        question_briefs=brief_views,
        trending_items=trending_views,
    )
    return rendered_md.strip(), inline_images


def markdown_to_email_html(md_text: str, custom_css: str | None = None) -> str:
    """Converts academic markdown to styled, email-safe HTML with inlined CSS."""
    raw_html = markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "nl2br"],
    )
    css = custom_css or DEFAULT_EMAIL_CSS
    full_html = f"<!DOCTYPE html><html><head><meta charset='utf-8'/><style>{css}</style></head><body><section>{raw_html}</section></body></html>"

    try:
        inlined = premailer.transform(
            full_html,
            keep_style_tags=False,
            strip_important=False,
        )
        return inlined
    except Exception as exc:
        logger.warning(f"Premailer CSS inlining failed ({exc}); returning wrapped HTML.")
        return full_html


def build_daily_report(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    report_date: date | None = None,
    max_chars: int | None = None,
    trending_items: list | None = None,
    include_posters: bool = True,
    template_path: str | Path | None = None,
    config: Any = None,
) -> DailyReport:
    """Main entrypoint: builds an editable Markdown-driven daily report, returning HTML & CID inline images."""
    report_date = report_date or date.today()
    title = f"论文研究日报 {report_date:%Y-%m-%d}"

    # Render full markdown
    rendered_md, inline_images = render_report_markdown(
        papers,
        question_briefs=question_briefs,
        trending_items=trending_items,
        title=title,
        template_path=template_path,
        config=config,
        include_posters=include_posters,
    )

    rendered_html = markdown_to_email_html(rendered_md)

    # WeChat max_chars truncation handling
    if max_chars is not None and len(rendered_html) > max_chars:
        active_papers = list(papers)
        while active_papers and len(rendered_html) > max_chars:
            active_papers.pop()
            omitted = len(papers) - len(active_papers)
            sub_md, sub_images = render_report_markdown(
                active_papers,
                question_briefs=question_briefs,
                trending_items=trending_items,
                title=title,
                template_path=template_path,
                config=config,
                include_posters=include_posters,
            )
            notice = f"\n\n> 另有 {omitted} 篇论文因篇幅限制未收录，请查阅完整邮件日报。\n"
            rendered_md = sub_md + notice
            inline_images = sub_images
            rendered_html = markdown_to_email_html(rendered_md)

    digest = f"今日精选 {len(papers)} 篇论文，{len(question_briefs or [])} 个研究问题有新进展。"[:120]
    return DailyReport(
        title=title[:32],
        html=rendered_html,
        digest=digest,
        inline_images=inline_images,
        markdown=rendered_md,
    )
