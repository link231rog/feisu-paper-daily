"""Academic framework diagram and visual poster generator.

Supports:
1. "gpt-image" (default): Generates concise, professional pipeline framework diagrams
   using gpt-image models (e.g. gpt-image-2.5-sunburst via OpenAI-compatible endpoints).
2. "source_figures": Extracts original author architecture/pipeline figures directly
   from arXiv source tarball or PDF via paper2assets / PyMuPDF.
3. "paper2poster": Invokes the installed paper2poster skill when available.
"""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Optional
import urllib.request

from loguru import logger
import requests

from ..protocol import Paper


def _sanitize_slug(text: str, max_len: int = 40) -> str:
    s = re.sub(r"[^\w\u4e00-\u9fa5]+", "_", str(text or "").strip()).strip("_")
    return s[:max_len] or "paper_diagram"


def _resolve_poster_proxies(config: Any) -> list[Optional[dict[str, str]]]:
    """Build list of candidate proxies to try (direct first, then configured/local proxies)."""
    proxies_list: list[Optional[dict[str, str]]] = []

    # 1. Explicit proxy in config or env
    explicit_proxy = None
    if hasattr(config, "get"):
        explicit_proxy = config.get("poster", {}).get("proxy_url") if isinstance(config.get("poster"), dict) else None
        if not explicit_proxy and hasattr(config, "poster") and hasattr(config.poster, "proxy_url"):
            explicit_proxy = config.poster.proxy_url
    if not explicit_proxy:
        explicit_proxy = os.environ.get("POSTER_PROXY_URL") or os.environ.get("ALL_PROXY") or os.environ.get("HTTPS_PROXY")

    if explicit_proxy:
        proxies_list.append({"http": explicit_proxy, "https": explicit_proxy})

    # 2. Direct connection (default for cloud / GitHub Actions)
    proxies_list.append(None)

    # 3. Common local proxies only when running on local development machine (not GitHub Actions)
    if "GITHUB_ACTIONS" not in os.environ:
        for local_port in ["7897", "7890"]:
            local_p = f"http://127.0.0.1:{local_port}"
            p_dict = {"http": local_p, "https": local_p}
            if p_dict not in proxies_list:
                proxies_list.append(p_dict)

    return proxies_list


def build_framework_prompt(paper: Paper) -> str:
    """Builds a precise, legible visual prompt for the framework diagram."""
    title = (paper.title or "Research Paper").strip()
    flow_points: list[str] = []

    digest = getattr(paper, "critical_digest", None) or {}
    delta = digest.get("delta") or ""
    mech = digest.get("mechanism") or ""

    if mech:
        # Extract mechanism summary or key modules
        lines = [line.strip().lstrip("-*# ") for line in str(mech).split("\n") if line.strip()]
        for line in lines[:3]:
            flow_points.append(line)
    elif delta:
        flow_points.append(str(delta)[:180])
    elif paper.abstract:
        flow_points.append(paper.abstract[:200])

    flow_desc = "; ".join(flow_points) if flow_points else "Input -> Model Processing -> Output"

    prompt = (
        f"A professional academic architecture diagram and pipeline framework for '{title}'. "
        f"Components and data flow: {flow_desc}. "
        "Style: modern scientific architecture diagram, clean vector publication figure, "
        "crisp legible English labels and directional arrows, high contrast, pure white background, "
        "no messy text, professional top-tier conference paper style."
    )
    return prompt


def generate_diagram_with_gpt_image(
    paper: Paper,
    api_base: str,
    api_key: str,
    model: str = "gpt-image-2.5-sunburst",
    size: str = "1792x1024",
    output_dir: Path | str = "data/posters",
    proxies_list: Optional[list[Optional[dict[str, str]]]] = None,
) -> Optional[Path]:
    """Generates a framework diagram via OpenAI-compatible image generation API."""
    if not api_key:
        logger.debug("POSTER_API_KEY is not configured; skipping gpt-image framework generation.")
        return None

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    slug = _sanitize_slug(paper.arxiv_id or paper.title)
    dest_file = out_path / f"{slug}_framework.png"

    if dest_file.is_file() and dest_file.stat().st_size > 5000:
        logger.info(f"Reusing cached framework diagram: {dest_file}")
        return dest_file

    prompt = build_framework_prompt(paper)
    endpoint = api_base.rstrip("/") + "/images/generations"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent": "PaperDaily-Poster/1.0",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }

    if not proxies_list:
        proxies_list = [None]

    last_exc: Optional[Exception] = None
    for px in proxies_list:
        try:
            resp = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                proxies=px,
                timeout=90,
            )
            if resp.status_code == 200:
                res_json = resp.json()
                data = res_json.get("data") or []
                if not data:
                    continue
                first = data[0]
                b64 = first.get("b64_json")
                remote_url = first.get("url")

                if b64:
                    dest_file.write_bytes(base64.b64decode(b64))
                    logger.info(f"Generated and saved framework diagram to: {dest_file}")
                    return dest_file
                elif remote_url:
                    r_img = requests.get(remote_url, timeout=30, proxies=px)
                    if r_img.status_code == 200:
                        dest_file.write_bytes(r_img.content)
                        logger.info(f"Downloaded framework diagram to: {dest_file}")
                        return dest_file
            else:
                logger.warning(f"GPT-Image API returned status {resp.status_code}: {resp.text[:200]}")
        except Exception as exc:
            last_exc = exc
            continue

    if last_exc:
        logger.warning(f"Failed to generate framework diagram for '{paper.title}': {last_exc}")
    return None


def extract_source_method_figure(paper: Paper, output_dir: Path | str = "data/posters") -> Optional[Path]:
    """Attempts to extract the author's original Method/Pipeline figure from arXiv source."""
    if not paper.arxiv_id:
        return None

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_slug(paper.arxiv_id)
    dest_file = out_path / f"{slug}_method_fig.png"

    if dest_file.is_file() and dest_file.stat().st_size > 5000:
        return dest_file

    # Check for installed paper2assets source_figures script
    candidate_scripts = [
        Path.home() / ".claude/skills/paper2assets/scripts/source_figures.py",
        Path.home() / ".agents/skills/paper2assets/scripts/source_figures.py",
        Path("/Users/huangzixuan/Documents/Dev/ResearchStudio/ResearchStudio-Reel/skills/paper2assets/scripts/source_figures.py"),
    ]
    script_path = next((p for p in candidate_scripts if p.is_file()), None)
    if not script_path:
        return None

    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        cmd = [
            sys.executable,
            str(script_path),
            "--arxiv",
            str(paper.arxiv_id),
            "--outdir",
            tmp_dir,
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            fig_dir = Path(tmp_dir) / "assets" / "figures"
            if fig_dir.is_dir():
                figures = list(fig_dir.glob("*.png")) + list(fig_dir.glob("*.jpg"))
                if figures:
                    # Pick figure 1 or largest figure as method overview
                    figures.sort(key=lambda f: f.stat().st_size, reverse=True)
                    target_fig = figures[0]
                    dest_file.write_bytes(target_fig.read_bytes())
                    logger.info(f"Extracted original method figure from arXiv to: {dest_file}")
                    return dest_file
        except Exception as exc:
            logger.debug(f"Source figure extraction failed: {exc}")

    return None


def generate_paper_poster(paper: Paper, config: Any) -> Optional[Path]:
    """Main entrypoint to generate or extract a visual framework diagram/poster for a paper."""
    poster_cfg = {}
    if hasattr(config, "get"):
        poster_cfg = config.get("poster") or {}
    elif hasattr(config, "poster"):
        poster_cfg = config.poster

    enabled = False
    if hasattr(poster_cfg, "get"):
        enabled = str(poster_cfg.get("enabled", False)).strip().lower() in ("true", "1", "yes")
    elif hasattr(poster_cfg, "enabled"):
        enabled = bool(poster_cfg.enabled)

    if not enabled and os.environ.get("POSTER_ENABLED", "").strip().lower() not in ("true", "1", "yes"):
        return None

    engine = "gpt-image"
    if hasattr(poster_cfg, "get"):
        engine = str(poster_cfg.get("engine", "gpt-image")).strip().lower()
    elif hasattr(poster_cfg, "engine"):
        engine = str(poster_cfg.engine).strip().lower()

    output_dir = "data/posters"
    if hasattr(poster_cfg, "get") and poster_cfg.get("output_dir"):
        output_dir = poster_cfg.get("output_dir")

    api_base = "https://sub.umapis.com/v1"
    if hasattr(poster_cfg, "get") and poster_cfg.get("api_base"):
        api_base = poster_cfg.get("api_base")
    api_base = os.environ.get("POSTER_API_BASE", api_base)

    api_key = os.environ.get("POSTER_API_KEY", "")
    if not api_key and hasattr(poster_cfg, "get") and poster_cfg.get("api_key"):
        api_key = str(poster_cfg.get("api_key") or "")

    model = "gpt-image-2.5-sunburst"
    if hasattr(poster_cfg, "get") and poster_cfg.get("model"):
        model = str(poster_cfg.get("model"))
    model = os.environ.get("POSTER_MODEL", model)

    size = "1792x1024"
    if hasattr(poster_cfg, "get") and poster_cfg.get("size"):
        size = str(poster_cfg.get("size"))
    size = os.environ.get("POSTER_SIZE", size)

    proxies_list = _resolve_poster_proxies(config)

    # 1. Primary engine
    result_path: Optional[Path] = None
    if engine in ("source_figures", "source_extract"):
        result_path = extract_source_method_figure(paper, output_dir=output_dir)

    if not result_path:
        result_path = generate_diagram_with_gpt_image(
            paper,
            api_base=api_base,
            api_key=api_key,
            model=model,
            size=size,
            output_dir=output_dir,
            proxies_list=proxies_list,
        )

    # Fallback to source figure extraction if gpt-image failed and paper has arXiv
    if not result_path and engine != "source_figures":
        result_path = extract_source_method_figure(paper, output_dir=output_dir)

    if result_path and result_path.is_file():
        paper.poster_path = str(result_path)

    return result_path
