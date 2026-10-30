"""Online academic literature search, similarity reranking, and direct library ingestion for Coding Agents.

Provides fast, unauthenticated multi-source retrieval (arXiv, Semantic Scholar, DBLP),
Max-TopK similarity & MMR diversity reranking, and zero-checklist direct note ingestion
into the user's active literature library (Feishu, Obsidian, Notion, Zotero).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import re
from typing import Any, Optional
from urllib.parse import quote
import xml.etree.ElementTree as ET

from loguru import logger
import requests

from ..protocol import Paper, extract_paper_artifacts
from ..reranker.local import LocalReranker


TOP_VENUES = (
    "neurips", "iclr", "icml", "acl", "emnlp", "cvpr", "iccv", "eccv",
    "aaai", "kdd", "sigir", "coling", "naacl", "tacl", "ieee", "acm"
)


def normalize_paper_url(url_or_id: str) -> str:
    """Normalizes an arXiv ID, DOI, or URL into a canonical paper URL."""
    s = str(url_or_id or "").strip()
    if not s:
        return ""
    # Plain arXiv ID: e.g. 2401.12345 or 2401.12345v2
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s):
        return f"https://arxiv.org/abs/{s}"
    # Prefixed arXiv ID: e.g. arxiv:2401.12345
    if s.lower().startswith("arxiv:"):
        return f"https://arxiv.org/abs/{s.split(':', 1)[1].strip()}"
    # Plain DOI: e.g. 10.1145/...
    if s.startswith("10.") and "/" in s:
        return f"https://doi.org/{s}"
    return s


def search_arxiv(query: str, limit: int = 10, timeout: int = 15) -> list[Paper]:
    """Retrieves candidate papers from official arXiv Search API (free, unauthenticated)."""
    q_clean = query.strip()
    if not q_clean:
        return []

    url = f"https://export.arxiv.org/api/query?search_query=all:{quote(q_clean)}&start=0&max_results={max(1, limit)}&sortBy=relevance&sortOrder=descending"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"arXiv search API returned status {resp.status_code}")
            return []
        root = ET.fromstring(resp.text)
    except Exception as exc:
        logger.warning(f"Failed to query arXiv search API: {exc}")
        return []

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        raw_title = entry.findtext("atom:title", default="", namespaces=ns)
        title = " ".join(raw_title.split())
        raw_summary = entry.findtext("atom:summary", default="", namespaces=ns)
        abstract = " ".join(raw_summary.split())
        if not title:
            continue

        authors = []
        for a_node in entry.findall("atom:author", ns):
            name = a_node.findtext("atom:name", default="", namespaces=ns)
            if name:
                authors.append(name.strip())

        paper_id_url = entry.findtext("atom:id", default="", namespaces=ns).strip()
        arxiv_match = re.search(r"(\d{4}\.\d{4,5})", paper_id_url)
        arxiv_id = arxiv_match.group(1) if arxiv_match else None

        abs_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else paper_id_url
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None

        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                pdf_url = link.attrib.get("href")
            elif link.attrib.get("rel") == "alternate":
                abs_url = link.attrib.get("href") or abs_url

        published_str = entry.findtext("atom:published", default="", namespaces=ns)
        pub_dt = None
        if published_str:
            try:
                pub_dt = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
            except Exception:
                pass

        venue = None
        comment_node = entry.findtext("arxiv:comment", default="", namespaces=ns)
        if comment_node:
            for v in ["NeurIPS", "ICLR", "ICML", "ACL", "EMNLP", "CVPR", "ICCV", "ECCV", "AAAI", "KDD", "SIGIR"]:
                if v.lower() in comment_node.lower():
                    ym = re.search(r"202\d", comment_node)
                    venue = f"{v} {ym.group(0)}" if ym else v
                    break

        primary_cat = ""
        cat_node = entry.find("arxiv:primary_category", ns)
        if cat_node is not None:
            primary_cat = cat_node.attrib.get("term", "")
        if not venue and primary_cat:
            venue = f"arXiv ({primary_cat})"

        artifacts = extract_paper_artifacts(f"{title}\n{abstract}\n{comment_node or ''}")
        p = Paper(
            source="arxiv",
            title=title,
            authors=authors,
            abstract=abstract,
            url=abs_url,
            pdf_url=pdf_url,
            arxiv_id=arxiv_id,
            published_date=pub_dt,
            venue=venue or "arXiv preprint",
            code_url=artifacts.get("code_url"),
            project_url=artifacts.get("project_url"),
        )
        papers.append(p)

    return papers


def search_semantic_scholar(
    query: str,
    limit: int = 10,
    api_key: str | None = None,
    timeout: int = 15,
) -> list[Paper]:
    """Retrieves candidate papers from Semantic Scholar Graph API (with rate limit catch)."""
    q_clean = query.strip()
    if not q_clean:
        return []

    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    params = {
        "query": q_clean,
        "limit": max(1, limit),
        "fields": "title,authors,abstract,url,venue,year,citationCount,openAccessPdf,externalIds",
    }
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
    if api_key and str(api_key).strip() and str(api_key).strip() != "???":
        headers["x-api-key"] = str(api_key).strip()

    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 429:
            logger.debug("Semantic Scholar search rate-limited (429); skipping.")
            return []
        if resp.status_code != 200:
            logger.debug(f"Semantic Scholar returned status {resp.status_code}")
            return []
        data = resp.json().get("data") or []
    except Exception as exc:
        logger.debug(f"Semantic Scholar request skipped: {exc}")
        return []

    papers: list[Paper] = []
    for item in data:
        title = (item.get("title") or "").strip()
        if not title:
            continue
        abstract = (item.get("abstract") or "").strip()
        authors = [a.get("name") for a in (item.get("authors") or []) if a.get("name")]
        year = item.get("year")
        venue = item.get("venue") or (f"Year {year}" if year else "Academic Paper")
        pub_dt = datetime(year, 1, 1) if year else None

        ext = item.get("externalIds") or {}
        arxiv_id = ext.get("ArXiv")
        doi = ext.get("DOI")

        p_url = item.get("url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "")
        pdf_info = item.get("openAccessPdf") or {}
        pdf_url = pdf_info.get("url") or (f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None)

        artifacts = extract_paper_artifacts(f"{title}\n{abstract}")
        p = Paper(
            source="semantic_scholar",
            title=title,
            authors=authors,
            abstract=abstract,
            url=p_url or f"https://doi.org/{doi}" if doi else "https://api.semanticscholar.org",
            pdf_url=pdf_url,
            arxiv_id=arxiv_id,
            doi=doi,
            published_date=pub_dt,
            venue=venue,
            citation_count=item.get("citationCount"),
            code_url=artifacts.get("code_url"),
            project_url=artifacts.get("project_url"),
        )
        papers.append(p)

    return papers


def search_dblp(query: str, limit: int = 10, timeout: int = 15) -> list[Paper]:
    """Retrieves candidate papers from DBLP Computer Science Bibliography API."""
    q_clean = query.strip()
    if not q_clean:
        return []

    url = "https://dblp.org/search/publ/api"
    params = {"q": q_clean, "format": "json", "h": max(1, limit)}
    headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            return []
        hits = ((resp.json().get("result") or {}).get("hits") or {}).get("hit") or []
        if isinstance(hits, dict):
            hits = [hits]
    except Exception as exc:
        logger.debug(f"DBLP search skipped: {exc}")
        return []

    papers: list[Paper] = []
    for h in hits:
        info = h.get("info") or {}
        raw_t = info.get("title") or ""
        title = raw_t.rstrip(".").strip()
        if not title:
            continue

        raw_authors = info.get("authors", {}).get("author") or []
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        authors = [str(a.get("text") or a) for a in raw_authors if a]

        year_str = str(info.get("year") or "")
        year = int(year_str) if year_str.isdigit() else None
        pub_dt = datetime(year, 1, 1) if year else None

        venue = info.get("venue") or "Computer Science Publication"
        ee = info.get("ee") or info.get("url") or ""
        ee_url = ee if isinstance(ee, str) else (ee[0] if isinstance(ee, list) and ee else "")

        p = Paper(
            source="dblp",
            title=title,
            authors=authors,
            abstract="",
            url=ee_url or f"https://dblp.org/rec/{info.get('key', '')}",
            published_date=pub_dt,
            venue=f"{venue} {year}" if year else venue,
        )
        papers.append(p)

    return papers


def search_and_rank_papers(
    query: str,
    top_k: int = 5,
    sources: list[str] | None = None,
    config: Any = None,
) -> list[Paper]:
    """Concurrent multi-source search followed by TF-IDF relevance scoring, venue/recency boosting, and MMR diversity."""
    q_clean = query.strip()
    if not q_clean:
        return []

    active_sources = [s.lower().strip() for s in (sources or ["arxiv", "semantic_scholar", "dblp"])]
    s2_key = None
    if config:
        s2_key = (
            config.get("source", {}).get("semantic_scholar", {}).get("api_key")
            if hasattr(config, "get")
            else None
        )

    candidates: list[Paper] = []
    fetch_limit = max(top_k * 3, 10)

    # Concurrently query academic sources
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = []
        if "arxiv" in active_sources:
            futures.append(pool.submit(search_arxiv, q_clean, limit=fetch_limit))
        if "semantic_scholar" in active_sources:
            futures.append(pool.submit(search_semantic_scholar, q_clean, limit=fetch_limit, api_key=s2_key))
        if "dblp" in active_sources:
            futures.append(pool.submit(search_dblp, q_clean, limit=fetch_limit))

        for f in futures:
            try:
                candidates.extend(f.result() or [])
            except Exception as exc:
                logger.debug(f"Search future error: {exc}")

    if not candidates:
        return []

    # 1. Deduplicate by canonical title / arXiv ID
    unique_candidates: list[Paper] = []
    seen_keys: set[str] = set()
    for c in candidates:
        dkey = c.dedup_key()
        if dkey in seen_keys:
            continue
        seen_keys.add(dkey)
        unique_candidates.append(c)

    if not unique_candidates:
        return []

    # 2. Score semantic relevance to query using TF-IDF
    cand_texts = [f"{c.title or ''}. {c.abstract or ''}".strip(". ") for c in unique_candidates]
    sim_scores = LocalReranker._tfidf_similarity([q_clean], cand_texts)[0]  # shape (len(candidates),)

    current_year = datetime.now().year
    recency_years = {current_year, current_year - 1}

    for idx, c in enumerate(unique_candidates):
        base_sim = float(sim_scores[idx]) if idx < len(sim_scores) else 0.0
        score = base_sim * 8.0

        # Exact keyword occurrences in title
        q_words = re.findall(r"[a-z0-9\u4e00-\u9fff]{2,}", q_clean.lower())
        c_title_l = (c.title or "").lower()
        if q_words:
            matched_words = sum(1 for w in q_words if w in c_title_l)
            score += round((matched_words / len(q_words)) * 2.0, 2)

        # Recency boost
        if c.published_year in recency_years:
            score += 0.6
        elif c.published_year and c.published_year >= (current_year - 3):
            score += 0.3

        # Venue boost
        v_lower = (c.venue or "").lower()
        if any(v in v_lower for v in TOP_VENUES):
            score += 0.6

        # Open-source code boost
        if getattr(c, "code_url", None):
            score += 0.5

        # High citation boost
        if getattr(c, "citation_count", None) and c.citation_count > 0:
            import math
            score += min(0.8, round(math.log1p(c.citation_count) * 0.15, 2))

        c.score = round(max(0.1, score), 2)

    unique_candidates.sort(key=lambda x: (x.score or 0.0), reverse=True)

    # 3. Apply MMR diversity selection (lambda=0.75) to prevent redundant near-duplicates
    reranker = LocalReranker(config or {})
    final_papers = reranker.mmr_select(unique_candidates, k=top_k, lambda_param=0.75)
    return final_papers


def find_papers(
    query: str,
    top_k: int = 5,
    sources: list[str] | None = None,
    config: Any = None,
) -> list[dict[str, Any]]:
    """High-level function returning serialized dictionaries of found and ranked papers."""
    ranked = search_and_rank_papers(query, top_k=top_k, sources=sources, config=config)
    results: list[dict[str, Any]] = []
    for p in ranked:
        results.append(
            {
                "title": p.title,
                "authors": p.authors,
                "year": p.published_year,
                "venue": p.venue or "Preprint",
                "score": p.score,
                "abstract": p.abstract,
                "url": p.url,
                "pdf_url": p.pdf_url or (f"https://arxiv.org/pdf/{p.arxiv_id}.pdf" if p.arxiv_id else None),
                "code_url": p.code_url,
                "source": p.source,
                "arxiv_id": p.arxiv_id,
            }
        )
    return results


def format_found_papers_markdown(papers: list[dict[str, Any]], query: str) -> str:
    """Formats ranked paper search results into clean, actionable Markdown for Coding Agents."""
    if not papers:
        return f"未检索到与 '{query}' 相关的学术文献。"

    lines = [
        f"# 📚 学术文献检索与重排推荐 (Query: \"{query}\")",
        f"已按多源检索与 MMR 算法优选前 {len(papers)} 篇核心文献：\n",
    ]

    for idx, p in enumerate(papers, 1):
        score_val = f"{p['score']:.2f}" if "score" in p and p["score"] is not None else "N/A"
        lines.append(f"## {idx}. {p['title']} (相关度评分: {score_val})")
        if p.get("authors"):
            lines.append(f"- **作者**: {', '.join(p['authors'][:5])}{' 等' if len(p['authors']) > 5 else ''}")
        if p.get("venue"):
            lines.append(f"- **发表/收录**: `{p['venue']}`")
        if p.get("year"):
            lines.append(f"- **年份**: {p['year']}")
        if p.get("url"):
            pdf_link = f" | [PDF 原文]({p['pdf_url']})" if p.get("pdf_url") else ""
            lines.append(f"- **文献直达**: {p['url']}{pdf_link}")
        if p.get("code_url"):
            lines.append(f"- **开源代码**: {p['code_url']}")
        if p.get("abstract"):
            clean_abs = " ".join(p["abstract"].split())
            if len(clean_abs) > 300:
                clean_abs = clean_abs[:300] + "..."
            lines.append(f"- **核心摘要**:\n  > {clean_abs}")
        # One-line direct ingestion command for Coding Agents
        target_url = p.get("url") or (f"https://arxiv.org/abs/{p['arxiv_id']}" if p.get("arxiv_id") else "")
        if target_url:
            lines.append(f"- **一键入库指令**: `paper-library ingest \"{target_url}\"`\n")

    return "\n".join(lines)


def ingest_paper_direct(
    url_or_id: str,
    provider: str = "auto",
    generate_poster: bool = False,
    config: Any = None,
) -> dict[str, Any]:
    """Directly ingests a paper by URL or arXiv ID into the target literature library without interactive checklist."""
    from .bridge import _load_runtime_config
    from ..executor import Executor

    clean_url = normalize_paper_url(url_or_id)
    if not clean_url:
        raise ValueError("A valid paper URL or arXiv ID must be provided.")

    cfg = config or _load_runtime_config()
    executor = Executor(cfg)

    note_url = executor.ingest_paper_by_url(clean_url, provider=provider, generate_poster=generate_poster)
    if not note_url:
        # Fallback to local paper store entry if external library provider is disabled/dry_run
        return {
            "status": "warning",
            "message": f"Paper was registered in local store, but no active library provider (Feishu/Obsidian/Notion/Zotero) successfully returned a note URL. Check provider credentials.",
            "url": clean_url,
            "provider": provider,
        }

    return {
        "status": "success",
        "url": clean_url,
        "note_url": note_url,
        "provider": provider,
        "message": f"Successfully ingested paper directly into {provider} knowledge base: {note_url}",
    }


def generate_poster_for_paper_direct(
    url_or_id: str,
    config: Any = None,
) -> dict[str, Any]:
    """Generates an academic framework diagram / visual poster for a given paper URL or arXiv ID."""
    from .bridge import _load_runtime_config
    from ..core.poster import generate_paper_poster
    from ..executor import Executor

    clean_url = normalize_paper_url(url_or_id)
    if not clean_url:
        raise ValueError("A valid paper URL or arXiv ID must be provided.")

    cfg = config or _load_runtime_config()
    executor = Executor(cfg)

    # Minimal Paper representation
    p = Paper(
        source="arxiv" if "arxiv.org" in clean_url else "web",
        title=f"Paper ({clean_url})",
        authors=[],
        abstract="",
        url=clean_url,
        arxiv_id=clean_url.split("abs/")[-1].split("pdf/")[-1].removesuffix(".pdf") if "arxiv.org" in clean_url else None,
    )

    try:
        raw_text = executor.fetch_paper_full_text(clean_url)
        if raw_text:
            p.full_text = raw_text
            first_lines = [l.strip("# \t") for l in raw_text.splitlines() if l.strip()]
            if first_lines and len(first_lines[0]) > 5:
                p.title = first_lines[0][:120]
        from ..core.digest import run_critical_paper_digest
        run_critical_paper_digest(executor.router, p, questions=[], library_baselines=[])
    except Exception as exc:
        logger.debug(f"Pre-digest for poster generation notice: {exc}")

    img_path = generate_paper_poster(p, cfg)
    if img_path and img_path.is_file():
        return {
            "status": "success",
            "url": clean_url,
            "title": p.title,
            "poster_path": str(img_path),
            "file_uri": f"file://{img_path.resolve()}",
            "size_kb": round(img_path.stat().st_size / 1024, 1),
        }
    return {
        "status": "failed",
        "url": clean_url,
        "message": "Failed to generate or extract framework diagram. Check POSTER_API_KEY or network connectivity.",
    }
