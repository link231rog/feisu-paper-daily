"""WeChat Official Account draft publisher and formatter.

Integrates patterns and open-source components from:
- wechatpy/wechatpy (WeChat Official Account API & material/draft SDK)
- doocs/md & caol64/wenyan (WeChat inline CSS academic theme & link-to-footnote conversion)
- LucianaiB2004/wechat-publisher (Multi-mode article generation & automatic academic cover image)
"""

from __future__ import annotations

import json
import mimetypes
import re
import struct
import tempfile
import time
import zlib
from datetime import date
from html import escape
from pathlib import Path
from typing import Any

import requests

from .daily_report import DailyReport, build_daily_report
from ..protocol import Paper

_TOKEN_CACHE: dict[str, tuple[str, float]] = {}
_COVER_MEDIA_CACHE: dict[str, str] = {}

# ---------------------------------------------------------------------------
# 1. doocs/md & wenyan Inspired Academic Inline CSS Theme for WeChat MP
# ---------------------------------------------------------------------------

WECHAT_ACADEMIC_CSS = """
section.wx-article {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
  font-size: 15px;
  color: #1f2937;
  line-height: 1.8;
  letter-spacing: 0.02em;
  padding: 4px 2px;
  word-break: break-word;
}
h1 {
  display: table;
  margin: 24px auto 16px;
  padding: 0 16px;
  border-bottom: 2px solid #2563eb;
  color: #0f172a;
  font-size: 19px;
  font-weight: 700;
  text-align: center;
  line-height: 1.4;
}
h2 {
  display: table;
  margin: 28px 0 14px 0;
  padding: 4px 12px;
  background: #2563eb;
  color: #ffffff;
  font-size: 16px;
  font-weight: 700;
  border-radius: 4px;
  line-height: 1.4;
  letter-spacing: 0.03em;
}
h3 {
  margin: 20px 0 10px 0;
  padding-left: 10px;
  border-left: 3.5px solid #2563eb;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.4;
}
h4 {
  margin: 16px 0 8px 0;
  color: #1e40af;
  font-size: 14px;
  font-weight: 700;
}
p {
  margin: 0 0 14px 0;
  color: #334155;
  line-height: 1.8;
  font-size: 15px;
  letter-spacing: 0.02em;
}
blockquote {
  margin: 14px 0;
  padding: 12px 16px;
  background-color: #f8fafc;
  border-left: 4px solid #2563eb;
  color: #334155;
  font-size: 14px;
  border-radius: 0 6px 6px 0;
  line-height: 1.7;
}
ul, ol {
  margin: 8px 0 14px 0;
  padding-left: 20px;
  color: #334155;
  font-size: 15px;
  line-height: 1.75;
}
li {
  margin-bottom: 6px;
  line-height: 1.75;
  color: #334155;
}
code {
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
  font-size: 13px;
  background-color: #f1f5f9;
  color: #2563eb;
  padding: 2px 5px;
  border-radius: 4px;
  border: 1px solid #e2e8f0;
}
pre {
  background-color: #0f172a;
  color: #f8fafc;
  padding: 12px 14px;
  border-radius: 8px;
  overflow-x: auto;
  font-size: 13px;
  line-height: 1.6;
  margin: 14px 0;
  font-family: Menlo, Monaco, Consolas, "Courier New", monospace;
}
table {
  border-collapse: collapse;
  width: 100%;
  margin: 16px 0;
  font-size: 13.5px;
  line-height: 1.6;
}
th {
  background-color: #f1f5f9;
  color: #0f172a;
  font-weight: 700;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  text-align: left;
}
td {
  padding: 8px 12px;
  border: 1px solid #e2e8f0;
  color: #334155;
}
tr:nth-child(even) {
  background-color: #f8fafc;
}
hr {
  border: 0;
  border-top: 1px solid #e2e8f0;
  margin: 24px 0;
}
strong {
  color: #0f172a;
  font-weight: 700;
}
mark {
  background-color: #fef08a;
  color: #0f172a;
  padding: 1px 4px;
  border-radius: 2px;
  font-weight: 600;
}
sup.wx-ref {
  color: #2563eb;
  font-weight: 600;
  font-size: 12px;
  padding: 0 2px;
}
"""

_INLINE_TAG_STYLES: dict[str, str] = {
    "h1": "display:table;margin:24px auto 16px;padding:0 16px;border-bottom:2px solid #2563eb;color:#0f172a;font-size:19px;font-weight:700;text-align:center;line-height:1.4;",
    "h2": "display:table;margin:28px 0 14px 0;padding:4px 12px;background:#2563eb;color:#ffffff;font-size:16px;font-weight:700;border-radius:4px;line-height:1.4;letter-spacing:0.03em;",
    "h3": "margin:20px 0 10px 0;padding-left:10px;border-left:3.5px solid #2563eb;color:#0f172a;font-size:15px;font-weight:700;line-height:1.4;",
    "h4": "margin:16px 0 8px 0;color:#1e40af;font-size:14px;font-weight:700;",
    "p": "margin:0 0 14px 0;color:#334155;line-height:1.8;font-size:15px;letter-spacing:0.02em;",
    "blockquote": "margin:14px 0;padding:12px 16px;background-color:#f8fafc;border-left:4px solid #2563eb;color:#334155;font-size:14px;border-radius:0 6px 6px 0;line-height:1.7;",
    "ul": "margin:8px 0 14px 0;padding-left:20px;color:#334155;font-size:15px;line-height:1.75;",
    "ol": "margin:8px 0 14px 0;padding-left:20px;color:#334155;font-size:15px;line-height:1.75;",
    "li": "margin-bottom:6px;line-height:1.75;color:#334155;",
    "code": "font-family:Menlo,Monaco,Consolas,monospace;font-size:13px;background-color:#f1f5f9;color:#2563eb;padding:2px 5px;border-radius:4px;border:1px solid #e2e8f0;",
    "table": "border-collapse:collapse;width:100%;margin:16px 0;font-size:13.5px;line-height:1.6;",
    "th": "background-color:#f1f5f9;color:#0f172a;font-weight:700;padding:8px 12px;border:1px solid #cbd5e1;text-align:left;",
    "td": "padding:8px 12px;border:1px solid #e2e8f0;color:#334155;",
    "hr": "border:0;border-top:1px solid #e2e8f0;margin:24px 0;",
    "strong": "color:#0f172a;font-weight:700;",
}


def convert_links_to_wechat_footnotes(html_or_md: str) -> str:
    """Convert external hyperlinks into WeChat-compliant numbered footnotes [1], [2] at the bottom."""
    footnotes: list[tuple[str, str]] = []
    seen_urls: dict[str, int] = {}

    def _register_link(label: str, url: str) -> str:
        clean_url = url.strip()
        clean_label = label.strip() or clean_url
        if not clean_url.startswith(("http://", "https://")):
            return clean_label
        if clean_url not in seen_urls:
            seen_urls[clean_url] = len(footnotes) + 1
            footnotes.append((clean_label, clean_url))
        idx = seen_urls[clean_url]
        return f'{clean_label}<sup class="wx-ref" style="color:#2563eb;font-weight:600;font-size:12px;">[{idx}]</sup>'

    # 1. Convert HTML <a href="...">label</a>
    def _replace_html_a(match: re.Match) -> str:
        url = match.group(1)
        label = re.sub(r"<[^>]+>", "", match.group(2))
        return _register_link(label, url)

    converted = re.sub(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        _replace_html_a,
        html_or_md,
        flags=re.IGNORECASE | re.DOTALL,
    )

    # 2. Convert Markdown [label](url) (avoiding ![alt](img))
    def _replace_md_link(match: re.Match) -> str:
        label = match.group(1)
        url = match.group(2)
        return _register_link(label, url)

    converted = re.sub(r"(?<!!)\[([^\]]+)\]\((https?://[^)\s]+)\)", _replace_md_link, converted)

    if footnotes:
        ref_items = "".join(
            f'<li style="margin-bottom:4px;font-size:13px;color:#64748b;word-break:break-all;">'
            f"[{i}] {escape(label)}: {escape(url)}</li>"
            for i, (label, url) in enumerate(footnotes, 1)
        )
        ref_section = (
            '<h2 style="display:table;margin:28px 0 14px 0;padding:4px 12px;background:#2563eb;color:#ffffff;font-size:16px;font-weight:700;border-radius:4px;line-height:1.4;letter-spacing:0.03em;">参考资料与原文链接</h2>'
            f'<ol style="margin:8px 0 16px 0;padding-left:20px;font-size:13px;color:#64748b;line-height:1.7;">{ref_items}</ol>'
        )
        if "</section>" in converted:
            converted = converted.replace("</section>", f"{ref_section}</section>", 1)
        else:
            converted = f"{converted}\n{ref_section}"

    return converted


def _apply_inline_tag_styles(html: str) -> str:
    """Ensure every standard block tag has WeChat-compatible inline style attributes with doocs/md aesthetics."""
    try:
        from premailer import transform

        wrapped = f"<html><head><style>{WECHAT_ACADEMIC_CSS}</style></head><body><section class='wx-article'>{html}</section></body></html>"
        inlined = transform(wrapped, remove_classes=False, strip_important=False)
        body_match = re.search(r"<body[^>]*>(.*)</body>", inlined, flags=re.IGNORECASE | re.DOTALL)
        if body_match:
            html = body_match.group(1).strip()
    except Exception:
        pass

    out = html

    # 1. Ensure tables are wrapped in mobile horizontal-scroll container
    def _wrap_table(m: re.Match) -> str:
        tbl = m.group(0)
        return f'<div style="max-width:100%;overflow-x:auto;margin:16px 0;-webkit-overflow-scrolling:touch;">{tbl}</div>'

    if 'overflow-x:auto' not in out:
        out = re.sub(r"<table[\s\S]*?</table>", _wrap_table, out, flags=re.IGNORECASE)

    # 2. Decorate pre code blocks with doocs/md Mac window dots
    def _mac_code_card(m: re.Match) -> str:
        code_body = m.group(1)
        return (
            '<section style="margin:16px 0;background-color:#0f172a;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.12);">'
            '<div style="display:flex;align-items:center;padding:8px 12px;background-color:#1e293b;border-bottom:1px solid #334155;">'
            '<span style="width:10px;height:10px;border-radius:50%;background:#ef4444;display:inline-block;margin-right:6px;"></span>'
            '<span style="width:10px;height:10px;border-radius:50%;background:#f59e0b;display:inline-block;margin-right:6px;"></span>'
            '<span style="width:10px;height:10px;border-radius:50%;background:#10b981;display:inline-block;"></span>'
            '</div>'
            f'<pre style="background:transparent;color:#f8fafc;padding:12px 14px;margin:0;overflow-x:auto;font-family:Menlo,Monaco,Consolas,monospace;font-size:13px;line-height:1.6;">{code_body}</pre>'
            '</section>'
        )

    if 'style="width:10px;height:10px;border-radius:50%;background:#ef4444' not in out:
        out = re.sub(r"<pre[^>]*>([\s\S]*?)</pre>", _mac_code_card, out, flags=re.IGNORECASE)

    # 3. Apply tag-level inline fallback styles
    for tag, style in _INLINE_TAG_STYLES.items():
        out = re.sub(
            rf"<{tag}(?![^>]*style=)([^>]*)>",
            rf'<{tag} style="{style}"\1>',
            out,
            flags=re.IGNORECASE,
        )
    if not out.strip().startswith("<section"):
        out = (
            '<section class="wx-article" style="font-family:-apple-system,BlinkMacSystemFont,PingFang SC,sans-serif;'
            'font-size:15px;color:#1f2937;line-height:1.8;padding:4px 2px;">'
            f"{out}</section>"
        )
    return out


def markdown_to_wechat_html(md_text: str) -> str:
    """Convert Markdown or hybrid HTML into WeChat Official Account inline-styled HTML."""
    with_footnotes = convert_links_to_wechat_footnotes(md_text)
    try:
        import markdown as md_lib

        raw_html = md_lib.markdown(
            with_footnotes,
            extensions=["tables", "fenced_code", "nl2br"],
        )
    except Exception:
        # Lightweight Markdown to HTML fallback for bare Python environments
        lines = with_footnotes.splitlines()
        html_lines: list[str] = []
        in_list = False
        for line in lines:
            s = line.strip()
            if not s:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                continue
            if s.startswith("### "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h3>{s[4:]}</h3>")
            elif s.startswith("## "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h2>{s[3:]}</h2>")
            elif s.startswith("# "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h1>{s[2:]}</h1>")
            elif s.startswith("> "):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<blockquote><p>{s[2:]}</p></blockquote>")
            elif s.startswith("- ") or s.startswith("* "):
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                item_body = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s[2:])
                html_lines.append(f"<li>{item_body}</li>")
            elif s.startswith("<"):
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(s)
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                para = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
                html_lines.append(f"<p>{para}</p>")
        if in_list:
            html_lines.append("</ul>")
        raw_html = "\n".join(html_lines)

    return _apply_inline_tag_styles(raw_html)


# ---------------------------------------------------------------------------
# 2. Automatic Academic Cover Image Generator (PyMuPDF + Pure-Python Fallback)
# ---------------------------------------------------------------------------

def _write_minimal_academic_png(output_path: Path, width: int = 900, height: int = 383) -> Path:
    """Generate a valid 900x383 (2.35:1) academic navy-and-blue gradient PNG using standard library zlib."""
    rows: list[bytes] = []
    for y in range(height):
        row = bytearray([0])  # Filter type 0 (None)
        is_border = 18 <= y <= 22 or (height - 22) <= y <= (height - 18)
        for x in range(width):
            if is_border and 36 <= x <= width - 36:
                # Academic accent bar (#3b82f6)
                row.extend((59, 130, 246))
            elif 36 <= x <= 42 and 40 <= y <= height - 40:
                # Left vertical accent (#60a5fa)
                row.extend((96, 165, 250))
            else:
                # Deep academic slate gradient (#0f172a -> #1e293b)
                r = 15 + int(15 * (x / width))
                g = 23 + int(18 * (y / height))
                b = 42 + int(28 * (x / width))
                row.extend((r, g, b))
        rows.append(bytes(row))

    raw_data = b"".join(rows)

    def _chunk(chunk_type: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(chunk_type + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw_data, level=6))
        + _chunk(b"IEND", b"")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(png_bytes)
    return output_path


def generate_academic_cover(
    title: str,
    subtitle: str = "Paper Daily · Academic Research Digest",
    output_path: str | Path | None = None,
) -> Path:
    """Generate a 900x383 (2.35:1) minimalist academic cover image for WeChat Official Account drafts."""
    if output_path is None:
        out = Path(tempfile.gettempdir()) / "paper_daily_wechat_cover.png"
    else:
        out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    try:
        import fitz  # PyMuPDF

        doc = fitz.open()
        page = doc.new_page(width=900, height=383)

        # Deep academic slate background (#0f172a)
        page.draw_rect(fitz.Rect(0, 0, 900, 383), color=(0.06, 0.09, 0.16), fill=(0.06, 0.09, 0.16))
        # Subtle inner card frame
        page.draw_rect(fitz.Rect(28, 24, 872, 359), color=(0.20, 0.28, 0.42), width=1.2)
        # Left vertical blue accent bar (#3b82f6)
        page.draw_rect(fitz.Rect(52, 58, 60, 325), color=(0.23, 0.51, 0.96), fill=(0.23, 0.51, 0.96))

        # Top badge & date
        badge_text = f"PAPER DAILY  |  {date.today().isoformat()}"
        page.insert_text(
            fitz.Point(80, 88),
            badge_text,
            fontsize=14,
            color=(0.58, 0.64, 0.72),
            fontname="helv",
        )

        # Main title (supports CJK via built-in china-ss font in PyMuPDF)
        clean_title = (title or "论文研究日报").strip()
        line1 = clean_title[:22]
        line2 = clean_title[22:44]
        try:
            page.insert_text(fitz.Point(80, 165), line1, fontsize=28, color=(0.97, 0.98, 0.99), fontname="china-ss")
            if line2:
                page.insert_text(fitz.Point(80, 212), line2, fontsize=28, color=(0.97, 0.98, 0.99), fontname="china-ss")
            page.insert_text(
                fitz.Point(80, 295),
                (subtitle or "多信源抓取 · 文献库批注 · 问题追踪")[:42],
                fontsize=16,
                color=(0.38, 0.65, 0.98),
                fontname="china-ss",
            )
        except Exception:
            page.insert_text(fitz.Point(80, 175), "Paper Daily Research Brief", fontsize=28, color=(0.97, 0.98, 0.99), fontname="helv")
            page.insert_text(fitz.Point(80, 230), date.today().isoformat(), fontsize=18, color=(0.38, 0.65, 0.98), fontname="helv")

        pix = page.get_pixmap(dpi=144)
        pix.save(str(out))
        doc.close()
        return out
    except Exception:
        return _write_minimal_academic_png(out)


# ---------------------------------------------------------------------------
# 3. Three WeChat Article Mode Builders (Digest / Deep-Read / Topic Review)
# ---------------------------------------------------------------------------

def _text(value: object, limit: int = 1200) -> str:
    return " ".join(str(value or "").split())[:limit]


def build_digest_wechat_article(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    trending_items: list | None = None,
    report_date: date | None = None,
    max_chars: int = 18500,
) -> DailyReport:
    """Mode 1: 每日研究精选合集推文（多篇汇总加导语 + 内联样式 + 文末参考链接角标）."""
    raw_report = build_daily_report(
        papers,
        question_briefs=question_briefs,
        report_date=report_date,
        max_chars=max_chars,
        trending_items=trending_items,
        include_posters=False,
    )
    wechat_html = _apply_inline_tag_styles(convert_links_to_wechat_footnotes(raw_report.html))
    return DailyReport(
        title=raw_report.title[:64],
        html=wechat_html,
        digest=raw_report.digest[:120],
    )


def build_single_paper_deep_read_article(
    paper: Paper,
    router: Any = None,
    report_date: date | None = None,
) -> DailyReport:
    """Mode 2: 单篇重点论文深度解读推文."""
    report_date = report_date or date.today()
    short_title = _text(paper.title, 44)
    article_title = f"精读｜{short_title}"[:64]

    cd = getattr(paper, "critical_digest", None) or {}
    delta = _text(cd.get("delta") or paper.tldr or paper.judge_reason or paper.abstract, 400)
    mech = cd.get("mechanism") or {}
    pipeline = _text(mech.get("pipeline") or "", 500)
    formula = _text(mech.get("core_formula") or "", 300)
    symbol_dict = _text(mech.get("symbol_dict") or "", 300)
    ev = cd.get("evidence_and_cost") or {}
    metrics = _text(ev.get("metrics") or "", 500)
    cost_limits = _text(ev.get("cost_and_limits") or "", 500)
    action_check = _text(cd.get("action_or_check") or "", 400)

    # Optional LLM narrative lead-in if router is available
    lead_in = ""
    if router is not None and getattr(router, "available", False):
        try:
            prompt = (
                "请将以下论文信息改写为一段 120 字以内的微信公众号学术导语（平实、客观、无表情符号、直击研究痛点与核心增量）：\n"
                f"标题：{paper.title}\n摘要：{paper.abstract}\n核心增量：{delta}"
            )
            raw_lead = (
                router.complete(task="wechat_lead", prompt=prompt, max_tokens=220)
                if hasattr(router, "complete")
                else router.chat([{"role": "user", "content": prompt}], max_tokens=220)
            )
            lead_in = _text(raw_lead, 260)
        except Exception:
            lead_in = ""

    if not lead_in:
        lead_in = f"本文聚焦 {paper.title_with_venue()}，梳理其针对现有基线的核心变量改动、模块链路与实验算力开销。"

    md_parts: list[str] = [
        f"# {paper.title_with_venue()}",
        f"> **导读**：{lead_in}",
        "## 01 核心增量与基线对比",
        f"- **一句话增量**：{delta}",
    ]
    if paper.authors:
        md_parts.append(f"- **作者团队**：{_text(', '.join(paper.authors), 200)}")
    if getattr(paper, "review_badge", None):
        md_parts.append(f"- **审稿置信度**：{paper.review_badge}（评分：{getattr(paper, 'review_score', '-')}/10）")
    from ..core.digest import format_rubric_summary_line
    if rubric_str := format_rubric_summary_line(paper):
        md_parts.append(f"- **四维量化评估**：{rubric_str}")
    if getattr(paper, "baseline_links", None):
        bl_items = [
            f"{b.get('name', '基线')}（{b.get('relation', '对比')}：{b.get('delta', '')}）"
            for b in (paper.baseline_links or [])[:3]
            if isinstance(b, dict)
        ]
        if bl_items:
            md_parts.append(f"- **文献库基线关联**：{'；'.join(bl_items)}")

    md_parts.append("## 02 方法链路与关键公式")
    if pipeline:
        md_parts.append(f"- **模块执行链路**：`{pipeline}`")
    if formula:
        md_parts.append(f"- **核心公式**：`{formula}`")
    if symbol_dict:
        md_parts.append(f"- **符号定义**：{symbol_dict}")
    if not (pipeline or formula):
        md_parts.append(f"{_text(paper.abstract, 800)}")

    md_parts.append("## 03 实验核查与算力开销")
    if metrics:
        md_parts.append(f"- **关键涨点与实验结果**：{metrics}")
    if cost_limits:
        md_parts.append(f"- **算力开销与失效边界**：{cost_limits}")
    if action_check:
        md_parts.append(f"- **复用建议与待核查项**：{action_check}")
    if not (metrics or cost_limits):
        md_parts.append("- 摘要阶段暂未披露完整消融表格，勾选沉淀至文献库后将自动拉取全文图表核查。")

    if paper.inline_annotations:
        md_parts.append("## 04 原文关键证据批注")
        for ann in paper.inline_annotations[:5]:
            q = _text(ann.get("quote"), 120)
            c = _text(ann.get("comment"), 180)
            if q and c:
                md_parts.append(f'- **「{q}」** → {c}')

    link_items: list[str] = []
    if paper.url:
        link_items.append(f"[查看论文原文]({paper.url})")
    if getattr(paper, "code_url", None):
        link_items.append(f"[开源代码仓库]({paper.code_url})")
    if getattr(paper, "project_url", None):
        link_items.append(f"[项目主页]({paper.project_url})")
    if link_items:
        md_parts.append("\n" + " ｜ ".join(link_items))

    html = markdown_to_wechat_html("\n\n".join(md_parts))
    digest = f"深度解读：{delta}"[:120]
    return DailyReport(title=article_title, html=html, digest=digest)


def build_topic_review_article(
    question_briefs: list[dict],
    papers: list[Paper] | None = None,
    report_date: date | None = None,
) -> DailyReport | None:
    """Mode 3: 围绕追踪问题的专题综述推文."""
    if not question_briefs:
        return None
    report_date = report_date or date.today()
    primary_q = _text(question_briefs[0].get("question") or "前沿研究问题追踪", 36)
    title = f"问题追踪｜{primary_q}"[:64]

    md_parts: list[str] = [
        f"# 研究问题专题追踪（{report_date:%Y-%m-%d}）",
        f"> 围绕控制台追踪的 {len(question_briefs)} 个核心科学问题，汇总今日新发表文献的支持证据、反例边界与待验证盲区。",
    ]

    for idx, brief in enumerate(question_briefs, 1):
        q_text = _text(brief.get("question"), 200)
        status = _text(brief.get("status") or "持续追踪", 40)
        summary = _text(brief.get("summary") or brief.get("answer") or "", 600)
        gap = _text(brief.get("gap") or "", 400)
        md_parts.append(f"## 问题 {idx}：{q_text}")
        md_parts.append(f"- **当前收敛状态**：{status}")
        if summary:
            md_parts.append(f"- **证据综述**：{summary}")

        supporting = brief.get("supporting_evidence") or brief.get("support_evidence") or []
        if supporting:
            sup_names = "；".join(_text(e.get("title", e) if isinstance(e, dict) else e, 120) for e in supporting[:3])
            md_parts.append(f"- **支持证据**：{sup_names}")

        counters = brief.get("counter_evidence") or []
        if counters:
            cnt_names = "；".join(_text(e.get("title", e) if isinstance(e, dict) else e, 120) for e in counters[:3])
            md_parts.append(f"- **反例与失效边界**：{cnt_names}")

        if gap:
            md_parts.append(f"- **当前盲区与后续追问**：{gap}")

    # Attach matching papers with links
    matched_papers = [p for p in (papers or []) if getattr(p, "qa_matches", None)]
    if matched_papers:
        md_parts.append("## 今日关联文献列表")
        for p in matched_papers[:6]:
            if p.url:
                md_parts.append(f"- [{_text(p.title, 120)}]({p.url})：{_text(p.tldr or p.judge_reason, 160)}")
            else:
                md_parts.append(f"- **{_text(p.title, 120)}**：{_text(p.tldr or p.judge_reason, 160)}")

    html = markdown_to_wechat_html("\n\n".join(md_parts))
    digest = f"围绕「{primary_q}」等 {len(question_briefs)} 个追踪问题的跨文献证据综述与反例梳理。"[:120]
    return DailyReport(title=title, html=html, digest=digest)


def build_wechat_articles(
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    trending_items: list | None = None,
    modes: list[str] | None = None,
    router: Any = None,
    report_date: date | None = None,
) -> list[DailyReport]:
    """Build WeChat Official Account article drafts according to configured article_modes."""
    active_modes = [str(m).strip().lower() for m in (modes or ["digest", "deep_read", "topic_review"]) if str(m).strip()]
    if not active_modes:
        active_modes = ["digest"]

    articles: list[DailyReport] = []
    report_date = report_date or date.today()

    if "digest" in active_modes and (papers or trending_items or question_briefs):
        articles.append(
            build_digest_wechat_article(
                papers,
                question_briefs=question_briefs,
                trending_items=trending_items,
                report_date=report_date,
            )
        )

    if "deep_read" in active_modes and papers:
        deep_candidates = [p for p in papers if getattr(p, "recommendation_tier", "deep_read") == "deep_read"] or papers[:1]
        top_paper = deep_candidates[0]
        articles.append(
            build_single_paper_deep_read_article(
                top_paper,
                router=router,
                report_date=report_date,
            )
        )

    if "topic_review" in active_modes and question_briefs:
        topic_art = build_topic_review_article(
            question_briefs,
            papers=papers,
            report_date=report_date,
        )
        if topic_art is not None:
            articles.append(topic_art)

    return articles


# ---------------------------------------------------------------------------
# 4. WeChat Official Account API Client (Proxy & api_base Supported)
# ---------------------------------------------------------------------------

def _resolve_request_kwargs(
    config: dict[str, Any] | Any | None = None,
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> tuple[str, dict[str, str] | None]:
    """Resolve normalized API base URL and requests proxy mapping."""
    cfg = config or {}
    if hasattr(cfg, "get"):
        base = str(api_base or cfg.get("api_base") or "https://api.weixin.qq.com").rstrip("/")
        p_url = str(proxy_url or cfg.get("proxy_url") or "").strip() or None
    else:
        base = str(api_base or "https://api.weixin.qq.com").rstrip("/")
        p_url = str(proxy_url or "").strip() or None

    proxies = {"http": p_url, "https": p_url} if p_url else None
    return base, proxies


def _response(response: requests.Response) -> dict:
    response.raise_for_status()
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError(f"WeChat returned non-JSON response ({response.status_code})") from exc
    errcode = data.get("errcode", 0)
    if errcode:
        errmsg = data.get("errmsg", "unknown")
        if errcode == 40164:
            raise RuntimeError(
                f"WeChat API error 40164 (IP not in whitelist): {errmsg}. "
                "Please add the current runner/machine public IP to WeChat MP Console -> Development -> Basic Config -> IP Whitelist, "
                "or configure 'proxy_url' / 'api_base' to route through a fixed outbound proxy."
            )
        raise RuntimeError(f"WeChat API error {errcode}: {errmsg}")
    return data


def _get_wechatpy_client(app_id: str, app_secret: str) -> Any | None:
    """Return a wechatpy.WeChatClient instance if wechatpy is installed."""
    try:
        from wechatpy import WeChatClient

        return WeChatClient(app_id, app_secret)
    except Exception:
        return None


def get_access_token(
    app_id: str,
    app_secret: str,
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> str:
    now = time.time()
    base, proxies = _resolve_request_kwargs(api_base=api_base, proxy_url=proxy_url)
    cache_key = f"{app_id}:{base}"
    cached = _TOKEN_CACHE.get(cache_key)
    if cached and now < cached[1]:
        return cached[0]

    # Try wechatpy client if on standard endpoint with no custom proxy
    if base == "https://api.weixin.qq.com" and not proxies:
        client = _get_wechatpy_client(app_id, app_secret)
        if client is not None:
            try:
                token = client.fetch_access_token()["access_token"]
                _TOKEN_CACHE[cache_key] = (token, now + 6900)
                return token
            except Exception:
                pass

    data = _response(requests.get(
        f"{base}/cgi-bin/token",
        params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        proxies=proxies,
        timeout=30,
    ))
    token = data.get("access_token")
    if not token:
        raise RuntimeError("WeChat token response has no access_token")
    _TOKEN_CACHE[cache_key] = (token, now + int(data.get("expires_in", 7200)) - 300)
    return token


def upload_cover(
    access_token: str,
    image_path: str,
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> str:
    """Upload a permanent cover image to WeChat material library and return media_id."""
    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"WeChat cover image not found: {path.name}")
    base, proxies = _resolve_request_kwargs(api_base=api_base, proxy_url=proxy_url)
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    with path.open("rb") as image:
        data = _response(requests.post(
            f"{base}/cgi-bin/material/add_material",
            params={"access_token": access_token, "type": "image"},
            files={"media": (path.name, image, content_type)},
            proxies=proxies,
            timeout=30,
        ))
    if not data.get("media_id"):
        raise RuntimeError("WeChat cover upload response has no media_id")
    return data["media_id"]


def upload_article_image(
    access_token: str,
    image_path: str,
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> str:
    """Upload an inline article image to WeChat CDN (mmbiz.qpic.cn) via /cgi-bin/media/uploadimg."""
    path = Path(image_path)
    if not path.is_file():
        raise ValueError(f"WeChat inline image not found: {path.name}")
    base, proxies = _resolve_request_kwargs(api_base=api_base, proxy_url=proxy_url)
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    with path.open("rb") as image:
        data = _response(requests.post(
            f"{base}/cgi-bin/media/uploadimg",
            params={"access_token": access_token},
            files={"media": (path.name, image, content_type)},
            proxies=proxies,
            timeout=30,
        ))
    url = data.get("url")
    if not url:
        raise RuntimeError("WeChat uploadimg response has no url")
    return url


def resolve_thumb_media_id(
    config: dict | Any,
    access_token: str,
    title: str = "论文研究日报",
    subtitle: str = "Paper Daily · Academic Digest",
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> str:
    """Resolve thumb_media_id from config, local cover_path, or auto-generated academic cover."""
    cfg = config if hasattr(config, "get") else {}
    thumb_media_id = str(cfg.get("thumb_media_id") or "").strip()
    if thumb_media_id:
        return thumb_media_id

    base, proxies = _resolve_request_kwargs(cfg, api_base, proxy_url)
    p_url = cfg.get("proxy_url") or proxy_url

    cover_path = str(cfg.get("cover_path") or "").strip()
    if cover_path and Path(cover_path).is_file():
        cache_key = f"file:{cover_path}:{base}"
        if cache_key not in _COVER_MEDIA_CACHE:
            _COVER_MEDIA_CACHE[cache_key] = upload_cover(access_token, cover_path, api_base=base, proxy_url=p_url)
        return _COVER_MEDIA_CACHE[cache_key]

    # Auto-generate minimalist academic cover image when not configured
    cache_key = f"auto:{date.today().isoformat()}:{title[:24]}:{base}"
    if cache_key not in _COVER_MEDIA_CACHE:
        generated_cover = generate_academic_cover(title=title, subtitle=subtitle)
        _COVER_MEDIA_CACHE[cache_key] = upload_cover(access_token, str(generated_cover), api_base=base, proxy_url=p_url)
    return _COVER_MEDIA_CACHE[cache_key]


def _build_draft_article_payload(
    config: dict | Any,
    report: DailyReport,
    thumb_media_id: str,
) -> dict[str, Any]:
    cfg = config if hasattr(config, "get") else {}
    article: dict[str, Any] = {
        "title": report.title[:64],
        "author": str(cfg.get("author") or "Paper Daily")[:16],
        "digest": report.digest[:120],
        "content": report.html,
        "thumb_media_id": thumb_media_id,
        "show_cover_pic": 0,
        "need_open_comment": int(cfg.get("need_open_comment", 0)),
        "only_fans_can_comment": int(cfg.get("only_fans_can_comment", 0)),
    }
    if cfg.get("content_source_url"):
        article["content_source_url"] = str(cfg["content_source_url"])
    return article


def create_draft(
    config: dict | Any,
    report: DailyReport | list[DailyReport],
) -> str:
    """Create a WeChat Official Account draft (single or multi-article bundle); never auto-publishes."""
    app_id = str(config["app_id"])
    app_secret = str(config["app_secret"])
    base, proxies = _resolve_request_kwargs(config)
    proxy_url = config.get("proxy_url") if hasattr(config, "get") else None
    token = get_access_token(app_id, app_secret, api_base=base, proxy_url=proxy_url)

    reports = report if isinstance(report, list) else [report]
    if not reports:
        raise ValueError("Cannot create an empty WeChat draft")

    articles_payload: list[dict[str, Any]] = []
    for rep in reports[:8]:  # WeChat allows up to 8 articles per draft item
        thumb_id = resolve_thumb_media_id(
            config,
            token,
            title=rep.title,
            subtitle=rep.digest,
            api_base=base,
            proxy_url=proxy_url,
        )
        articles_payload.append(_build_draft_article_payload(config, rep, thumb_id))

    data = _response(requests.post(
        f"{base}/cgi-bin/draft/add",
        params={"access_token": token},
        data=json.dumps({"articles": articles_payload}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        proxies=proxies,
        timeout=30,
    ))
    if not data.get("media_id"):
        raise RuntimeError("WeChat draft response has no media_id")
    return data["media_id"]


def upload_wechat_voice_material(
    access_token: str,
    mp3_path: str | Path,
    api_base: str | None = None,
    proxy_url: str | None = None,
) -> str:
    """Upload a <=60s, <=2MB MP3 voice guide to WeChat Official Account permanent voice material library."""
    path = Path(mp3_path)
    if not path.is_file():
        raise ValueError(f"WeChat voice MP3 not found: {path.name}")
    size_bytes = path.stat().st_size
    if size_bytes > 2 * 1024 * 1024:
        raise ValueError(f"WeChat voice material exceeds 2MB limit ({size_bytes} bytes): {path.name}")

    base, proxies = _resolve_request_kwargs(api_base=api_base, proxy_url=proxy_url)
    with path.open("rb") as voice_file:
        data = _response(
            requests.post(
                f"{base}/cgi-bin/material/add_material",
                params={"access_token": access_token, "type": "voice"},
                files={"media": (path.name, voice_file, "audio/mpeg")},
                proxies=proxies,
                timeout=45,
            )
        )
    media_id = data.get("media_id")
    if not media_id:
        raise RuntimeError("WeChat voice material upload response has no media_id")
    return str(media_id)


def publish_wechat_drafts(
    config: dict | Any,
    papers: list[Paper],
    question_briefs: list[dict] | None = None,
    trending_items: list | None = None,
    router: Any = None,
    voice_mp3_path: str | Path | None = None,
) -> str:
    """Build multi-mode WeChat articles (digest, deep_read, topic_review), optionally upload 60s voice material, and push to WeChat Draft Box."""
    raw_modes = config.get("article_modes") if hasattr(config, "get") else None
    if isinstance(raw_modes, str):
        modes = [m.strip() for m in raw_modes.split(",") if m.strip()]
    elif isinstance(raw_modes, (list, tuple)):
        modes = [str(m).strip() for m in raw_modes if str(m).strip()]
    else:
        modes = ["digest", "deep_read", "topic_review"]

    articles = build_wechat_articles(
        papers,
        question_briefs=question_briefs,
        trending_items=trending_items,
        modes=modes,
        router=router,
    )
    if not articles:
        articles = [
            build_digest_wechat_article(
                papers,
                question_briefs=question_briefs,
                trending_items=trending_items,
            )
        ]

    base, proxies = _resolve_request_kwargs(config)
    proxy_url = config.get("proxy_url") if hasattr(config, "get") else None

    if voice_mp3_path and Path(voice_mp3_path).is_file():
        try:
            app_id = str(config["app_id"])
            app_secret = str(config["app_secret"])
            token = get_access_token(app_id, app_secret, api_base=base, proxy_url=proxy_url)
            voice_media_id = upload_wechat_voice_material(token, voice_mp3_path, api_base=base, proxy_url=proxy_url)
            voice_banner = (
                '<blockquote style="margin:14px 0;padding:12px 16px;background-color:#eff6ff;'
                'border-left:4px solid #2563eb;color:#1e3a8a;font-size:13.5px;border-radius:0 6px 6px 0;">'
                f"<strong>[今日 60 秒语音导读已同步上传至公众号素材库]</strong>（语音 Media ID: <code>{escape(voice_media_id)}</code>，可在公众号后台编辑器一键插入顶部音频条）"
                "</blockquote>"
            )
            first = articles[0]
            if "<section" in first.html:
                first_html = re.sub(r"(<section[^>]*>)", rf"\1{voice_banner}", first.html, count=1)
            else:
                first_html = f"{voice_banner}\n{first.html}"
            articles[0] = DailyReport(title=first.title, html=first_html, digest=first.digest)
        except Exception:
            pass

    return create_draft(config, articles)
