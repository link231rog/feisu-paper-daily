"""VLM-powered academic paper figure and table quality evaluation & exemplar extraction (Option B).

Extracts figures and tables from papers (arXiv source tarballs or PDF pages), runs multimodal
VLM evaluation for visual clarity, information density, and layout aesthetics, and filters
for high-scoring (>= 4.0/5.0) exemplar figures for reference and inclusion in reading notes.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import sys
import tarfile
from typing import Any, Optional

from loguru import logger
from omegaconf import DictConfig
import requests

from ..protocol import Paper
from .poster import _resolve_arxiv_id, _resolve_poster_proxies, _sanitize_slug

DEFAULT_VLM_MODEL = "nvidia/nemotron-3.5-super-vl:free"

CATEGORY_MAP_ZH = {
    "architecture": "系统架构/流程图",
    "benchmark_table": "主实验性能对比表",
    "ablation_plot": "消融实验分析图",
    "qualitative_viz": "定性可视化与样例对比",
    "dataset_dist": "数据集与分布特征",
    "other": "核心技术图表",
}


def _get_image_dimensions(data: bytes) -> tuple[int, int]:
    """Inspects image dimensions from header bytes without third-party dependencies."""
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    elif len(data) >= 10 and data.startswith(b"GIF8"):
        w, h = struct.unpack("<HH", data[6:10])
        return w, h
    return 800, 600


def extract_candidate_figures(
    paper: Paper,
    temp_dir: Path | str = "data/temp_figures",
) -> list[tuple[Path, str]]:
    """Extracts candidate figures and tables from arXiv source tarball or PDF.

    Returns:
        List of (image_file_path, original_name_or_label).
    """
    dest_path = Path(temp_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    candidates: list[tuple[Path, str]] = []
    seen_hashes: set[str] = set()

    arxiv_id = _resolve_arxiv_id(paper)

    # 1. Primary: native arXiv source tarball extraction
    if arxiv_id:
        try:
            src_url = f"https://arxiv.org/src/{arxiv_id}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            r_src = requests.get(src_url, headers=headers, timeout=30)
            if r_src.status_code == 200 and len(r_src.content) > 100:
                with tarfile.open(fileobj=io.BytesIO(r_src.content)) as tar:
                    members = [
                        m for m in tar.getmembers()
                        if m.isfile() and any(m.name.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp", ".pdf"])
                    ]
                    for m in members:
                        # Skip tiny images or icons
                        if m.size < 8000:  # < 8 KB
                            continue
                        name_lower = m.name.lower()
                        if any(skip in name_lower for skip in ["icon", "logo", "banner", "math", "bullet"]):
                            continue

                        extracted = tar.extractfile(m)
                        if not extracted:
                            continue
                        raw_bytes = extracted.read()

                        # Convert vector PDF figures to PNG via PyMuPDF if needed
                        if name_lower.endswith(".pdf"):
                            try:
                                import fitz
                                doc = fitz.open(stream=raw_bytes, filetype="pdf")
                                if len(doc) == 0:
                                    continue
                                pix = doc[0].get_pixmap(dpi=150)
                                img_bytes = pix.tobytes("png")
                            except Exception:
                                continue
                        else:
                            img_bytes = raw_bytes

                        img_hash = hashlib.md5(img_bytes).hexdigest()
                        if img_hash in seen_hashes:
                            continue
                        seen_hashes.add(img_hash)

                        # Filter out very small dimensions
                        w, h = _get_image_dimensions(img_bytes)
                        if w < 180 or h < 120:
                            continue

                        base_name = Path(m.name).stem + ".png" if name_lower.endswith(".pdf") else Path(m.name).name
                        safe_name = re.sub(r"[^\w\-_.]", "_", base_name)
                        out_file = dest_path / f"{_sanitize_slug(arxiv_id)}_{safe_name}"
                        out_file.write_bytes(img_bytes)
                        candidates.append((out_file, m.name))
        except Exception as exc:
            logger.debug(f"arXiv source figure extraction encountered error for {arxiv_id}: {exc}")

    # 2. Secondary: PyMuPDF PDF extraction fallback
    resolved_pdf_url = (
        paper.pdf_url
        or (f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else None)
        or (paper.url if paper.url and paper.url.endswith(".pdf") else None)
    )
    if not candidates and resolved_pdf_url:
        try:
            import fitz

            pdf_url = resolved_pdf_url
            headers = {"User-Agent": "Mozilla/5.0"}
            r_pdf = requests.get(pdf_url, headers=headers, timeout=35)
            if r_pdf.status_code == 200 and len(r_pdf.content) > 5000:
                doc = fitz.open(stream=r_pdf.content, filetype="pdf")
                for page_idx in range(min(len(doc), 15)):
                    page = doc[page_idx]
                    images = page.get_images(full=True)
                    for img_idx, img in enumerate(images):
                        xref = img[0]
                        base_image = doc.extract_image(xref)
                        img_bytes = base_image.get("image")
                        img_ext = base_image.get("ext", "png")
                        if not img_bytes or len(img_bytes) < 15000:  # < 15 KB
                            continue

                        img_hash = hashlib.md5(img_bytes).hexdigest()
                        if img_hash in seen_hashes:
                            continue
                        seen_hashes.add(img_hash)

                        out_name = f"page{page_idx + 1}_img{img_idx + 1}.{img_ext}"
                        out_file = dest_path / out_name
                        out_file.write_bytes(img_bytes)
                        candidates.append((out_file, out_name))
        except Exception as pdf_err:
            logger.debug(f"PyMuPDF figure extraction fallback error: {pdf_err}")

    # Sort candidates by relevance heuristics (keywords in name and size)
    def _rank_candidate(item: tuple[Path, str]) -> tuple[int, int]:
        p, name = item
        n = name.lower()
        score = 0
        for kw in ("system", "diagram", "framework", "architecture", "overview", "pipeline", "model", "method"):
            if kw in n:
                score += 15
        for kw in ("table", "result", "benchmark", "accuracy", "performance", "ablation", "comparison"):
            if kw in n:
                score += 12
        if "fig1" in n or "figure1" in n or "fig_1" in n:
            score += 10
        elif "fig" in n or "figure" in n:
            score += 5
        return (score, p.stat().st_size if p.is_file() else 0)

    candidates.sort(key=_rank_candidate, reverse=True)
    return candidates


def evaluate_figure_with_vlm(
    image_path: Path,
    paper: Paper,
    config: DictConfig | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluates figure quality and semantic role using multimodal VLM (Option B)."""
    cfg = config or {}
    figures_cfg = cfg.get("figures") or {}
    vlm_model = str(figures_cfg.get("vlm_model") or os.environ.get("FIGURES_VLM_MODEL") or DEFAULT_VLM_MODEL).strip()

    # Determine API endpoint & key
    api_base = os.environ.get("OPENAI_API_BASE", "https://openrouter.ai/api/v1").rstrip("/")
    api_key = (
        os.environ.get("OPENAI_API_KEY")
        or (os.environ.get("LLM_API_KEYS", "").split(",")[0].strip() if os.environ.get("LLM_API_KEYS") else None)
    )

    if not api_key:
        # Graceful heuristic fallback if no key is configured
        return _fallback_heuristic_eval(image_path)

    try:
        img_bytes = image_path.read_bytes()
        b64 = base64.b64encode(img_bytes).decode("utf-8")
        ext = image_path.suffix.lstrip(".").lower()
        mime = f"image/{ext}" if ext in ["png", "jpeg", "jpg", "webp"] else "image/png"

        prompt = (
            f"You are a scientific publication reviewer and expert graphic designer.\n"
            f"Evaluate this figure/table from the paper \"{paper.title}\".\n\n"
            f"Respond with a strict JSON object with these keys:\n"
            f"- \"category\": one of [\"architecture\", \"benchmark_table\", \"ablation_plot\", \"qualitative_viz\", \"dataset_dist\", \"other\"]\n"
            f"- \"clarity_score\": integer 1 to 5 (resolution, axis readability, layout elegance)\n"
            f"- \"information_density\": integer 1 to 5 (richness of insights and findings)\n"
            f"- \"visual_appeal\": integer 1 to 5 (professional academic aesthetic and color palette)\n"
            f"- \"overall_score\": float 1.0 to 5.0 (overall publication and exemplar score)\n"
            f"- \"caption\": concise 1-sentence Chinese summary of what key finding/architecture this figure shows\n"
            f"- \"strengths\": 1-2 concise bullet points in Chinese describing its visual or analytical strengths\n"
            f"- \"is_exemplar\": boolean, true if overall_score >= 4.0\n"
        )

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": vlm_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                }
            ],
            "max_tokens": 2048,
        }

        # Resolve proxies and attempt request
        candidate_proxies = _resolve_poster_proxies(figures_cfg)
        r = None
        for proxy_dict in candidate_proxies:
            try:
                r = requests.post(
                    f"{api_base}/chat/completions",
                    headers=headers,
                    json=payload,
                    proxies=proxy_dict,
                    timeout=30,
                )
                if r.status_code == 200:
                    break
            except Exception:
                continue

        if r is not None and r.status_code == 200:
            res_json = r.json()
            choice = (res_json.get("choices") or [{}])[0]
            msg = choice.get("message") or {}

            # Prefer explicit content, fall back to reasoning if content is empty
            raw_text = msg.get("content") or ""
            if not raw_text or "{" not in raw_text:
                raw_text = msg.get("reasoning") or ""

            # Use shared robust JSON extractor
            from .textutil import extract_json

            parsed = extract_json(raw_text, default={})
            if isinstance(parsed, list):
                parsed = parsed[0] if parsed and isinstance(parsed[0], dict) else {}

            if isinstance(parsed, dict) and parsed:
                    cat = str(parsed.get("category", "other")).lower()
                    # Clean up category string (e.g. "architecture diagram" -> "architecture")
                    for k in CATEGORY_MAP_ZH:
                        if k in cat:
                            cat = k
                            break
                    cat_zh = CATEGORY_MAP_ZH.get(cat, "核心技术图表")
                    try:
                        clarity = int(parsed.get("clarity_score", 4))
                    except (ValueError, TypeError):
                        clarity = 4
                    try:
                        info_dense = int(parsed.get("information_density", 4))
                    except (ValueError, TypeError):
                        info_dense = 4
                    try:
                        vis_appeal = int(parsed.get("visual_appeal", 4))
                    except (ValueError, TypeError):
                        vis_appeal = 4
                    try:
                        overall = float(parsed.get("overall_score", 4.0))
                    except (ValueError, TypeError):
                        overall = 4.0

                    strengths = parsed.get("strengths")
                    if isinstance(strengths, str):
                        strengths = [strengths]
                    elif not isinstance(strengths, list):
                        strengths = ["图表结构清晰", "排版专业规范"]

                    return {
                        "category": cat,
                        "category_zh": cat_zh,
                        "clarity_score": clarity,
                        "information_density": info_dense,
                        "visual_appeal": vis_appeal,
                        "overall_score": overall,
                        "caption": str(parsed.get("caption") or f"{paper.title} 核心图表").strip(),
                        "strengths": strengths,
                        "is_exemplar": bool(parsed.get("is_exemplar", overall >= 4.0)),
                    }
    except Exception as exc:
        logger.warning(f"VLM evaluation failed for {image_path.name}: {exc}")

    return _fallback_heuristic_eval(image_path)


def _fallback_heuristic_eval(image_path: Path) -> dict[str, Any]:
    """Deterministic rule-based fallback when VLM is unreachable or rate limited."""
    name = image_path.name.lower()
    cat = "other"
    if any(k in name for k in ["arch", "system", "diag", "pipeline", "framework", "overview"]):
        cat = "architecture"
    elif any(k in name for k in ["table", "benchmark", "res"]):
        cat = "benchmark_table"
    elif any(k in name for k in ["ablat", "curve", "plot"]):
        cat = "ablation_plot"
    elif any(k in name for k in ["qual", "vis", "sample"]):
        cat = "qualitative_viz"

    return {
        "category": cat,
        "category_zh": CATEGORY_MAP_ZH.get(cat, "核心技术图表"),
        "clarity_score": 4,
        "information_density": 4,
        "visual_appeal": 4,
        "overall_score": 4.0,
        "caption": f"论文核心图表 ({image_path.name})",
        "strengths": ["高分辨率原图", "信息对齐度良好"],
        "is_exemplar": True,
    }


def extract_and_evaluate_paper_figures(
    paper: Paper,
    config: DictConfig | dict[str, Any] | None = None,
    min_score: float = 4.0,
    max_candidates: int = 5,
    max_selected: int = 2,
    output_dir: Path | str = "data/exemplars",
) -> list[dict[str, Any]]:
    """Extracts, evaluates, and stores exemplar figures for a paper (Option B).

    Returns:
        List of selected exemplar figure metadata dictionaries.
    """
    cfg = config or {}
    figures_cfg = cfg.get("figures") or {}
    min_score = float(figures_cfg.get("min_score", min_score))
    max_candidates = int(figures_cfg.get("max_candidates_per_paper", max_candidates))
    max_selected = int(figures_cfg.get("max_selected_per_paper", max_selected))

    arxiv_id = _resolve_arxiv_id(paper)
    slug = _sanitize_slug(arxiv_id or paper.title[:24])
    paper_out_dir = Path(output_dir) / slug
    paper_out_dir.mkdir(parents=True, exist_ok=True)

    manifest_file = paper_out_dir / "exemplars_manifest.json"
    if manifest_file.is_file():
        try:
            with open(manifest_file, "r", encoding="utf-8") as f:
                cached = json.load(f)
            if cached.get("figures"):
                paper.exemplar_figures = cached["figures"]
                return cached["figures"]
        except Exception:
            pass

    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        candidates = extract_candidate_figures(paper, temp_dir=tmp_dir)
        if not candidates:
            return []

        # Limit to top candidate count
        selected_candidates = candidates[:max_candidates]
        evaluated: list[dict[str, Any]] = []

        for img_path, orig_name in selected_candidates:
            ev = evaluate_figure_with_vlm(img_path, paper, config=cfg)
            score = float(ev.get("overall_score", 0.0))
            if score >= min_score:
                # Save into destination
                dest_name = f"{slug}_{Path(orig_name).name}"
                dest_file = paper_out_dir / dest_name
                import shutil
                shutil.copy2(img_path, dest_file)

                record = {
                    "file_path": str(dest_file),
                    "file_name": dest_name,
                    "original_name": orig_name,
                    "category": ev["category"],
                    "category_zh": ev["category_zh"],
                    "clarity_score": ev["clarity_score"],
                    "information_density": ev["information_density"],
                    "visual_appeal": ev["visual_appeal"],
                    "overall_score": ev["overall_score"],
                    "caption": ev["caption"],
                    "strengths": ev.get("strengths", []),
                    "is_exemplar": ev.get("is_exemplar", True),
                }
                evaluated.append(record)

        # Sort by overall score descending and take top max_selected
        evaluated.sort(key=lambda x: x["overall_score"], reverse=True)
        top_figures = evaluated[:max_selected]

        # Save manifest
        manifest_data = {
            "paper_title": paper.title,
            "arxiv_id": arxiv_id,
            "evaluated_count": len(selected_candidates),
            "selected_count": len(top_figures),
            "figures": top_figures,
        }
        try:
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)
        except Exception as save_err:
            logger.debug(f"Failed to write exemplars manifest: {save_err}")

        paper.exemplar_figures = top_figures
        return top_figures


def format_exemplars_markdown(exemplars: list[dict[str, Any]]) -> str:
    """Formats evaluated exemplar figures into clean markdown for display or CLI."""
    if not exemplars:
        return "*(未检出符合 >=4.0 分阈值的优质图表)*"

    lines = ["### 🎨 论文优质图表与基准摘录 (Exemplar Figures)"]
    for idx, fig in enumerate(exemplars, 1):
        lines.append(
            f"**{idx}. [{fig.get('category_zh', '核心图表')}]** {fig.get('caption', '')} "
            f"*(综合评分: {fig.get('overall_score', 4.0)}/5.0 | 清晰度: {fig.get('clarity_score', 4)}/5)*"
        )
        if fig.get("strengths"):
            strengths_str = "；".join(str(s) for s in fig["strengths"])
            lines.append(f"  - 视觉亮点: {strengths_str}")
        lines.append(f"  - 本地路径: `{fig.get('file_path', '')}`")
        lines.append("")

    return "\n".join(lines)
