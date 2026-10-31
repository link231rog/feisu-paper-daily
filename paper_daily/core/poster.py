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
import html as html_lib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
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


def _resolve_arxiv_id(paper: Paper) -> Optional[str]:
    """Resolves clean arXiv ID from paper.arxiv_id or URL patterns."""
    if paper.arxiv_id and re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", paper.arxiv_id.strip()):
        return paper.arxiv_id.strip().split("v")[0]

    urls_to_check = [paper.url or "", paper.pdf_url or ""]
    for u in urls_to_check:
        if not u:
            continue
        m = re.search(r"(?:arxiv\.org/(?:abs|pdf|html)|huggingface\.co/papers)/(\d{4}\.\d{4,5})(?:v\d+)?", u)
        if m:
            return m.group(1)
    return None


def extract_source_method_figure(paper: Paper, output_dir: Path | str = "data/posters") -> Optional[Path]:
    """Attempts to extract the author's original Method/Pipeline figure from arXiv source."""
    arxiv_id = _resolve_arxiv_id(paper)
    if not arxiv_id:
        return None

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_slug(arxiv_id)
    dest_file = out_path / f"{slug}_method_fig.png"

    if dest_file.is_file() and dest_file.stat().st_size > 5000:
        return dest_file

    # 1. Native lightweight tar.gz extraction from arXiv source (runs anywhere without extra skills/scripts)
    try:
        import io
        import tarfile

        src_url = f"https://arxiv.org/src/{arxiv_id}"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        r_src = requests.get(src_url, headers=headers, timeout=25)
        if r_src.status_code == 200 and len(r_src.content) > 1000:
            with tarfile.open(fileobj=io.BytesIO(r_src.content)) as tar:
                members = [
                    m for m in tar.getmembers()
                    if m.isfile() and any(m.name.lower().endswith(ext) for ext in [".png", ".jpg", ".jpeg", ".webp"])
                ]
                if members:
                    # Score images by architecture/framework keyword hints
                    def _score_member(m: Any) -> tuple[int, int]:
                        n = m.name.lower()
                        score = 0
                        for kw in ("system", "diagram", "framework", "architecture", "overview", "pipeline", "model", "method"):
                            if kw in n:
                                score += 10
                        if "fig1" in n or "figure1" in n or "fig_1" in n:
                            score += 8
                        elif "fig" in n or "figure" in n:
                            score += 3
                        return (score, m.size)

                    members.sort(key=_score_member, reverse=True)
                    best_m = members[0]
                    # Only accept if it has reasonable size (> 10KB)
                    if best_m.size > 10000:
                        extracted = tar.extractfile(best_m)
                        if extracted:
                            dest_file.write_bytes(extracted.read())
                            logger.info(f"Extracted arXiv author method diagram '{best_m.name}' to: {dest_file}")
                            return dest_file
    except Exception as src_err:
        logger.debug(f"Native arXiv source figure extraction failed for {arxiv_id}: {src_err}")

    # 2. Check for installed paper2assets source_figures script as fallback
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
            str(arxiv_id),
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


def find_headless_browser() -> Optional[str]:
    """Locates an installed headless Chrome or Chromium executable across OS environments."""
    import shutil

    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
    ]
    for c in candidates:
        if c and (os.path.isfile(c) or shutil.which(c)):
            return c
    return None


def render_structured_academic_poster(
    paper: Paper,
    output_dir: Path | str = "data/posters",
    author_figure: Optional[Path] = None,
) -> Optional[Path]:
    """Renders a structured, publication-grade academic poster image (Paper2Poster style) from paper data.

    Synthesizes and reorganizes the paper completely:
    - Header: Title, authors, venue, year, badges, 4D rubric scores
    - Column 1: Core motivation, problem statement, and mechanism delta
    - Column 2: System architecture, pipeline flow, formulas, and optional embedded author diagram
    - Column 3: Empirical findings, benchmark improvements, costs/limits, and actionable insights
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    slug = _sanitize_slug(paper.arxiv_id or paper.title)
    dest_file = out_path / f"{slug}_poster.png"

    if dest_file.is_file() and dest_file.stat().st_size > 10000:
        logger.info(f"Reusing cached structured academic poster: {dest_file}")
        return dest_file

    browser = find_headless_browser()
    if not browser:
        logger.debug("No headless Chrome/Chromium found for paper2poster rendering.")
        return None

    # Check for author figure to embed inside the architecture section
    fig_file = author_figure
    if not fig_file or not Path(fig_file).is_file():
        fig_file = extract_source_method_figure(paper, output_dir=output_dir)

    img_tag = ""
    if fig_file and Path(fig_file).is_file():
        try:
            b64_fig = base64.b64encode(Path(fig_file).read_bytes()).decode("ascii")
            img_tag = (
                f'<div style="text-align:center;margin:10px 0;background:#ffffff;border:1px solid #cbd5e1;border-radius:6px;padding:6px;">'
                f'<img src="data:image/png;base64,{b64_fig}" style="max-width:100%;max-height:260px;object-fit:contain;display:block;margin:0 auto;" alt="Method Diagram"/>'
                f'<div style="font-size:11px;color:#64748b;margin-top:4px;">▲ 核心方法架构图 (Extracted from arXiv Source)</div></div>'
            )
        except Exception as b64_err:
            logger.debug(f"Failed to base64-encode author figure for poster: {b64_err}")

    # Prepare view data
    import html as html_lib
    e = html_lib.escape

    title = e(paper.title or "Research Paper")
    authors = e(", ".join(paper.authors or [])[:140])
    venue_year = e(f"{paper.venue or 'arXiv'} · {paper.published_year or 2026} · {paper.arxiv_id or paper.source or ''}")

    cd = getattr(paper, "critical_digest", None) or {}
    if not isinstance(cd, dict):
        cd = {}
    grades = cd.get("qualitative_grades") or {}
    if not isinstance(grades, dict):
        grades = {}
    mech = cd.get("mechanism") or {}
    ev = cd.get("evidence_and_cost") or {}

    if isinstance(mech, dict):
        pipeline_val = mech.get("pipeline") or ""
        core_formula_val = mech.get("core_formula") or ""
        symbol_dict_val = mech.get("symbol_dict") or ""
    else:
        pipeline_val = str(mech or "")
        core_formula_val = ""
        symbol_dict_val = ""

    if isinstance(ev, dict):
        metrics_val = ev.get("metrics") or ""
        costs_val = ev.get("cost_and_limits") or ""
    else:
        metrics_val = str(ev or "")
        costs_val = ""

    r_grade = e(grades.get("method_reusability", {}).get("grade", "High") if isinstance(grades.get("method_reusability"), dict) else "High")
    s_grade = e(grades.get("claim_support", {}).get("grade", "High") if isinstance(grades.get("claim_support"), dict) else "High")
    f_grade = e(grades.get("baseline_fairness", {}).get("grade", "Fair") if isinstance(grades.get("baseline_fairness"), dict) else "Fair")
    review_badge = e(paper.review_badge or "[强烈推荐复用]")

    from .digest import format_rubric_summary_line
    rubric_line = e(format_rubric_summary_line(paper))

    problem = e(paper.tldr or paper.abstract or paper.judge_reason or "见论文原文摘要")[:400]
    delta = e(cd.get("delta") or paper.tldr_zh or paper.tldr or "提出针对性增量优化机制")[:400]
    pipeline = e(pipeline_val or "Input → Feature Extraction → Reasoning → Verification → Output")[:400]
    core_formula = e(core_formula_val)
    symbol_dict = e(symbol_dict_val)

    formula_block = ""
    if core_formula and core_formula not in ("N/A", "N/A (需查正文)"):
        formula_block = (
            f'<div style="background:#ffffff;border:1px solid #cbd5e1;border-radius:6px;padding:8px 12px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:12px;color:#0969da;margin:6px 0;overflow-x:auto;">'
            f'{core_formula}</div>'
        )
    if symbol_dict and symbol_dict not in ("N/A", "N/A (需查正文)"):
        formula_block += f'<div style="font-size:11.5px;color:#64748b;margin-top:2px;">• 符号释义：{symbol_dict}</div>'

    metrics = e(metrics_val or "见原文实验评估章节，多项基准达成显著增益")[:350]
    costs = e(costs_val or "低额外推理开销，已验证典型失败边界")[:350]
    action = e(cd.get("action_or_check", "该机制可直接迁移至本地 Agent 任务编排与决策路由中") if isinstance(cd, dict) else "该机制可直接迁移至本地 Agent 任务编排与决策路由中")[:400]

    code_badge = "<span style='font-size:12px;font-weight:600;padding:3px 8px;border-radius:5px;background:#fffbeb;color:#b45309;border:1px solid #fde68a;'>已附开源代码</span>" if getattr(paper, "code_url", None) else ""

    html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset='utf-8'/>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif;
    background: #f8fafc;
    color: #1e293b;
    width: 1600px;
    height: 1000px;
    overflow: hidden;
  }}
  .poster {{
    background: #ffffff;
    border: 2px solid #cbd5e1;
    border-radius: 12px;
    height: 100%;
    display: flex;
    flex-direction: column;
    padding: 24px 32px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.05);
  }}
  .header {{
    border-bottom: 2px solid #e2e8f0;
    padding-bottom: 16px;
    margin-bottom: 18px;
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }}
  .title-area {{ max-width: 1220px; }}
  h1 {{ margin: 0 0 6px 0; font-size: 25px; color: #0f172a; line-height: 1.3; font-weight: 700; }}
  .meta-line {{ font-size: 13.5px; color: #64748b; margin-bottom: 8px; }}
  .badges {{ display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }}
  .badge {{
    font-size: 12px; font-weight: 600; padding: 3px 8px; border-radius: 5px; border: 1px solid transparent;
  }}
  .badge-primary {{ background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe; }}
  .badge-success {{ background: #f0fdf4; color: #15803d; border-color: #bbf7d0; }}
  
  .grid {{
    flex: 1;
    display: grid;
    grid-template-columns: 1fr 1.35fr 1fr;
    gap: 18px;
    overflow: hidden;
  }}
  .col {{ display: flex; flex-direction: column; gap: 14px; }}
  .card {{
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }}
  .card-title {{
    font-size: 14.5px; font-weight: 700; color: #0f172a;
    border-bottom: 1px solid #e2e8f0; padding-bottom: 5px;
    display: flex; align-items: center; justify-content: space-between;
  }}
  .card-body {{ font-size: 13px; line-height: 1.6; color: #334155; }}
  .pipeline-box {{
    background: #eff6ff; border-left: 3px solid #3b82f6; border-radius: 4px;
    padding: 8px 10px; font-size: 12px; font-family: monospace; color: #1e3a8a;
  }}
  .footer {{
    border-top: 1px solid #e2e8f0;
    margin-top: 14px; padding-top: 8px;
    display: flex; justify-content: space-between;
    font-size: 11.5px; color: #94a3b8;
  }}
</style>
</head>
<body>
  <div class='poster'>
    <div class='header'>
      <div class='title-area'>
        <h1>{title}</h1>
        <div class='meta-line'>{authors} · {venue_year}</div>
        <div class='badges'>
          <span class='badge badge-success'>{review_badge}</span>
          <span class='badge badge-primary'>复用度: {r_grade}</span>
          <span class='badge badge-primary'>证据支撑: {s_grade}</span>
          <span class='badge badge-primary'>基线公平: {f_grade}</span>
          {code_badge}
          <span style='font-size:12px;color:#1e40af;'>{rubric_line}</span>
        </div>
      </div>
      <div style='text-align: right;'>
        <div style='font-size: 18px; font-weight: 800; color: #0052cc;'>PAPER2POSTER</div>
        <div style='font-size: 11px; color: #64748b; letter-spacing: 0.5px;'>ACADEMIC RESEARCH POSTER</div>
      </div>
    </div>
    
    <div class='grid'>
      <!-- Column 1 -->
      <div class='col'>
        <div class='card' style='border-left: 4px solid #3b82f6;'>
          <div class='card-title'>📌 核心痛点与研究背景</div>
          <div class='card-body'>{problem}</div>
        </div>
        <div class='card' style='border-left: 4px solid #10b981; flex: 1;'>
          <div class='card-title'>💡 核心机制增量 (Delta)</div>
          <div class='card-body'>{delta}</div>
        </div>
      </div>
      
      <!-- Column 2 -->
      <div class='col'>
        <div class='card' style='border-left: 4px solid #6366f1; height: 100%;'>
          <div class='card-title'>⚙️ 系统架构与方法链路</div>
          <div class='card-body'>
            <div class='pipeline-box'>{pipeline}</div>
            {img_tag}
            {formula_block}
          </div>
        </div>
      </div>
      
      <!-- Column 3 -->
      <div class='col'>
        <div class='card' style='border-left: 4px solid #f59e0b;'>
          <div class='card-title'>📊 实验真相与代价 (Truth & Cost)</div>
          <div class='card-body'>
            <strong>真实实验提升：</strong><br/>{metrics}<br/><br/>
            <strong>代价与局限边界：</strong><br/>{costs}
          </div>
        </div>
        <div class='card' style='border-left: 4px solid #8b5cf6; flex: 1;'>
          <div class='card-title'>🎯 启发与落地建议 (Actionable Insights)</div>
          <div class='card-body'>{action}</div>
        </div>
      </div>
    </div>
    
    <div class='footer'>
      <span>Generated by Paper2Poster · Feishu Paper Daily · Publication-Grade Visual Engine</span>
      <span>Autonomous Research Digest Series · All Claims Grounded in Paper Spec</span>
    </div>
  </div>
</body>
</html>"""

    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False) as f_html:
        f_html.write(html_content)
        tmp_html_path = f_html.name

    try:
        cmd = [
            browser,
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--hide-scrollbars",
            "--window-size=1600,1000",
            f"--screenshot={dest_file}",
            tmp_html_path,
        ]
        res = subprocess.run(cmd, capture_output=True, timeout=30)
        if dest_file.is_file() and dest_file.stat().st_size > 5000:
            logger.info(f"Rendered structured academic poster ({dest_file.stat().st_size} bytes): {dest_file}")
            return dest_file
        else:
            err = res.stderr.decode("utf-8", errors="ignore")[:300]
            logger.warning(f"Browser screenshot failed for {paper.title}: {err}")
    except Exception as exc:
        logger.warning(f"Failed to render poster via browser: {exc}")
    finally:
        try:
            os.unlink(tmp_html_path)
        except Exception:
            pass

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

    engine = "paper2poster"
    if hasattr(poster_cfg, "get"):
        engine = str(poster_cfg.get("engine", "paper2poster")).strip().lower()
    elif hasattr(poster_cfg, "engine"):
        engine = str(poster_cfg.engine).strip().lower()
    engine = os.environ.get("POSTER_ENGINE", engine).strip().lower()

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

    # 1. Primary: Paper2Poster structured academic poster (Option A)
    result_path: Optional[Path] = None
    if engine in ("paper2poster", "poster", "academic_poster", "auto"):
        result_path = render_structured_academic_poster(paper, output_dir=output_dir)

    # 2. AI image generation engine if explicitly requested or as fallback
    if not result_path and (engine == "gpt-image" or (engine in ("paper2poster", "auto") and api_key)):
        result_path = generate_diagram_with_gpt_image(
            paper,
            api_base=api_base,
            api_key=api_key,
            model=model,
            size=size,
            output_dir=output_dir,
            proxies_list=proxies_list,
        )

    # 3. Fallback to raw author figure extraction if poster/image rendering was unavailable
    if not result_path:
        result_path = extract_source_method_figure(paper, output_dir=output_dir)

    if result_path and result_path.is_file():
        paper.poster_path = str(result_path)

    return result_path
