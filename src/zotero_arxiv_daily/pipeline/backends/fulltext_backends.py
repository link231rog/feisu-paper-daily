"""Fulltext extraction backends arranged into an ordered fallback chain."""

from __future__ import annotations

import os
import re
import tempfile
from typing import Any, Optional
import urllib.parse

from loguru import logger
import requests

from ...utils import clean_paper_markdown
from ..base import Backend, FallbackChain
from .agent_reach import AgentReachCLI


def _preprocess_arxiv_html(html_str: str, base_url: str = "") -> tuple[str, dict[str, str]]:
    """Preprocesses arXiv HTML to preserve LaTeX formulas and retain figures."""
    math_placeholders: dict[str, str] = {}
    try:
        from lxml import html

        tree = html.fromstring(html_str)

        for i, m in enumerate(tree.xpath("//math")):
            tex = m.xpath(".//annotation[@encoding='application/x-tex']/text()")
            code = tex[0] if tex else (m.get("alttext") or "")
            code = code.strip()
            parent = m.getparent()
            if parent is None:
                continue

            display = m.get("display") == "block" or "display" in (m.get("class") or "")
            wrapper = f"$${code}$$" if display else f"${code}$"
            token = f"MATHPLACEHOLDER{i}XYZ"
            math_placeholders[token] = wrapper

            span = html.Element("span")
            span.text = f" {token} "
            parent.replace(m, span)

        # Retain figures and images
        for fig in tree.xpath("//figure | //div[contains(@class, 'ltx_figure')]"):
            img = fig.xpath(".//img")
            cap = fig.xpath(".//figcaption//text() | .//*[contains(@class, 'ltx_caption')]//text()")
            caption_text = " ".join("".join(cap).split()) if cap else ""
            if img:
                src = img[0].get("src") or ""
                if src and base_url:
                    src = urllib.parse.urljoin(base_url, src)
                if src:
                    md_fig = html.Element("p")
                    md_fig.text = f"\n\n![{caption_text}]({src})\n*{caption_text}*\n\n"
                    parent = fig.getparent()
                    if parent is not None:
                        parent.replace(fig, md_fig)
                        continue
            parent = fig.getparent()
            if parent is not None:
                parent.remove(fig)
        return html.tostring(tree, encoding="utf-8").decode("utf-8"), math_placeholders
    except Exception as exc:
        logger.debug(f"Failed to preprocess arXiv HTML: {exc}")
        return html_str, math_placeholders


class ArxivHtmlBackend(Backend[str]):
    """Attempts to extract structured markdown from ar5iv / arXiv experimental HTML."""

    name = "arxiv_html"

    def execute(self, url: str, **kwargs: Any) -> Optional[str]:
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", url)
        if not arxiv_match:
            return None

        arxiv_id = arxiv_match.group(1)
        html_url = f"https://arxiv.org/html/{arxiv_id}"

        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(html_url)
            if not downloaded:
                return None

            preprocessed, placeholders = _preprocess_arxiv_html(downloaded, base_url=html_url)
            text = trafilatura.extract(
                preprocessed,
                output_format="markdown",
                include_formatting=True,
                include_links=False,
            )
            if text and len(text) > 1000:
                for token, formula in placeholders.items():
                    text = text.replace(token, formula)
                text = clean_paper_markdown(text)
                return text
        except Exception as exc:
            logger.debug(f"ArxivHtmlBackend failed for {arxiv_id}: {exc}")
        return None


class PyMuPDFBackend(Backend[str]):
    """Downloads PDF and extracts structured markdown with layout and figures via pymupdf4llm."""

    name = "pymupdf_pdf"

    def execute(self, url: str, timeout: int = 30, **kwargs: Any) -> Optional[str]:
        pdf_url = url
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", url)
        if arxiv_match:
            pdf_url = f"https://arxiv.org/pdf/{arxiv_match.group(1)}.pdf"
        elif "openreview.net" in url.lower():
            or_match = re.search(r"id=([a-zA-Z0-9_\-]+)", url)
            if or_match:
                pdf_url = f"https://openreview.net/pdf?id={or_match.group(1)}"
        elif not (url.lower().endswith(".pdf") or ".pdf?" in url.lower()):
            # Check meta tags for citation_pdf_url
            try:
                import trafilatura

                downloaded = trafilatura.fetch_url(url)
                if downloaded:
                    pdf_match = re.search(
                        r'<meta\s+[^>]*name=["\'](?:citation_pdf_url|biorxiv_journal_pdf_url|eprints\.document_url)["\']\s+content=["\']([^"\']+)["\']',
                        downloaded,
                        re.IGNORECASE,
                    )
                    if not pdf_match:
                        pdf_match = re.search(
                            r'<meta\s+content=["\']([^"\']+\.pdf)["\']\s+name=["\'](?:citation_pdf_url|biorxiv_journal_pdf_url)["\']',
                            downloaded,
                            re.IGNORECASE,
                        )
                    if pdf_match:
                        pdf_url = urllib.parse.urljoin(url, pdf_match.group(1))
                    else:
                        return None
                else:
                    return None
            except Exception:
                return None

        try:
            import pymupdf4llm

            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = requests.get(pdf_url, headers=headers, timeout=timeout)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(resp.content)
                    tf_path = tf.name
                try:
                    safe_slug = re.sub(r"[^a-zA-Z0-9_\-]", "_", pdf_url.split("/")[-1].replace(".pdf", ""))
                    img_dir = os.path.join(tempfile.gettempdir(), "paper_images", safe_slug)
                    os.makedirs(img_dir, exist_ok=True)
                    md_text = pymupdf4llm.to_markdown(tf_path, write_images=True, image_path=img_dir)
                    if md_text and len(md_text) > 500:
                        return clean_paper_markdown(md_text)
                finally:
                    if os.path.exists(tf_path):
                        os.remove(tf_path)
        except Exception as exc:
            logger.debug(f"PyMuPDFBackend failed for {pdf_url}: {exc}")
        return None


class AgentReachReadBackend(Backend[str]):
    """Uses external agent-reach CLI to read pages with anti-scraping / browser rendering."""

    name = "agent_reach_read"

    def is_available(self) -> bool:
        return AgentReachCLI.is_installed()

    def execute(self, url: str, **kwargs: Any) -> Optional[str]:
        text = AgentReachCLI.read_url(url, timeout=25.0)
        if text and len(text) > 50:
            return clean_paper_markdown(text)
        return None


class TrafilaturaBackend(Backend[str]):
    """Standard HTML text extractor via trafilatura."""

    name = "trafilatura_web"

    def execute(self, url: str, **kwargs: Any) -> Optional[str]:
        try:
            import trafilatura

            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                text = trafilatura.extract(
                    downloaded,
                    output_format="markdown",
                    include_formatting=True,
                    include_links=False,
                )
                if text and len(text) > 500:
                    return clean_paper_markdown(text)
        except Exception as exc:
            logger.debug(f"TrafilaturaBackend failed for {url}: {exc}")
        return None


def create_default_fulltext_chain() -> FallbackChain[str]:
    """Assembles the fulltext extraction fallback chain."""
    return FallbackChain[str](
        backends=[
            ArxivHtmlBackend(),
            PyMuPDFBackend(),
            AgentReachReadBackend(),
            TrafilaturaBackend(),
        ],
        name="fulltext_extraction_chain",
    )
