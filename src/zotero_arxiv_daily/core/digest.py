"""Critical-Paper-Digest: Default high-density journal-club review protocol and section extraction.

Extracts targeted paper slices (Method, Experiments, Limitations) from arXiv HTML/ar5iv/e-print,
invokes the default Critical-Paper-Digest review prompt with anti-hype verification,
and deterministically computes qualitative review confidence scores and 4D OpenReview-style rubrics.

Open-source references and citations:
- SakanaAI/AI-Scientist (https://github.com/SakanaAI/AI-Scientist) & OpenReview Rubric (https://openreview.net):
  Multi-dimensional quantitative peer-review rubric (Delta, Rigor, Actionability, Reproducibility) and confidence calibration.
- link231rog/feisu-paper-daily (https://github.com/link231rog/feisu-paper-daily):
  Targeted LaTeXML/ar5iv section extraction and anti-hype evidence verification.
"""

import io
import re
import tarfile
from typing import Any, Optional
from urllib.parse import quote

import requests
from loguru import logger

from .llm import LLMRouter
from ..protocol import CorpusPaper, Paper
from .textutil import UNTRUSTED_NOTICE, extract_json

GRADE_WEIGHTS = {"High": 2, "Medium": 1, "Low": -2, "Unknown": 0}


def fetch_arxiv_targeted_sections(arxiv_id: str) -> dict[str, str]:
    """Extracts Method, Experiments, and Limitations slices from arXiv HTML, ar5iv, or e-print TeX."""
    if not arxiv_id:
        return {}

    clean_id = re.sub(r"^arxiv:\s*", "", arxiv_id, flags=re.IGNORECASE).strip()
    clean_id = re.sub(r"v\d+$", "", clean_id)  # Strip version for html canonical URL
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    }

    # 1. Primary: Official arXiv HTML (https://arxiv.org/html/{id})
    url_official = f"https://arxiv.org/html/{clean_id}"
    try:
        resp = requests.get(url_official, headers=headers, timeout=12)
        if resp.status_code == 200 and "<html" in resp.text.lower():
            sections = _extract_html_latexml_sections(resp.text)
            if any(sections.values()):
                logger.debug(f"Retrieved targeted sections from official arXiv HTML for {clean_id}")
                return sections
    except Exception as exc:
        logger.debug(f"arXiv HTML fetch skipped for {clean_id}: {exc}")

    # 2. Fallback: ar5iv (https://ar5iv.labs.arxiv.org/html/{id})
    url_ar5iv = f"https://ar5iv.labs.arxiv.org/html/{clean_id}"
    try:
        resp = requests.get(url_ar5iv, headers=headers, timeout=12)
        if resp.status_code == 200 and "<html" in resp.text.lower():
            sections = _extract_html_latexml_sections(resp.text)
            if any(sections.values()):
                logger.debug(f"Retrieved targeted sections from ar5iv HTML for {clean_id}")
                return sections
    except Exception as exc:
        logger.debug(f"ar5iv fetch skipped for {clean_id}: {exc}")

    # 3. Fallback: In-memory e-print TeX tarball (https://arxiv.org/e-print/{id})
    url_eprint = f"https://arxiv.org/e-print/{clean_id}"
    try:
        resp = requests.get(url_eprint, headers=headers, timeout=15)
        if resp.status_code == 200 and len(resp.content) > 1000:
            sections = _extract_eprint_tex_sections(resp.content)
            if any(sections.values()):
                logger.debug(f"Retrieved targeted sections from in-memory e-print TeX for {clean_id}")
                return sections
    except Exception as exc:
        logger.debug(f"e-print TeX extraction skipped for {clean_id}: {exc}")

    return {}


def _clean_latexml_chunk(chunk: str) -> str:
    """Replaces math annotations with clean LaTeX and strips tags."""
    # Preserve math formula LaTeX annotations e.g. <annotation encoding="application/x-tex">E=mc^2</annotation>
    clean = re.sub(
        r'<annotation\s+encoding=["\']application/x-tex["\']>(.*?)</annotation>',
        r' $\1$ ',
        chunk,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Strip remaining XML/HTML tags
    clean = re.sub(r'<[^>]+>', ' ', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def _extract_html_latexml_sections(html: str) -> dict[str, str]:
    """Parses Method, Experiments (including Tables & Figure captions), and Limitations from LaTeXML HTML."""
    sections = {"method": "", "experiments": "", "limitations": ""}
    sec_pattern = re.compile(
        r'<(?:section|div)[^>]*(?:class=["\'][^"\']*(?:ltx_section|ltx_subsection)[^"\']*)[^>]*>(.*?)</(?:section|div)>',
        re.DOTALL | re.IGNORECASE,
    )

    for match in sec_pattern.finditer(html):
        chunk = match.group(1)
        h_match = re.search(r'<h[1-6][^>]*>(.*?)</h[1-6]>', chunk, re.DOTALL | re.IGNORECASE)
        heading = re.sub(r'<[^>]+>', ' ', h_match.group(1)).strip().lower() if h_match else ""
        body = _clean_latexml_chunk(chunk)
        if not body:
            continue

        if any(k in heading for k in ("method", "approach", "architecture", "framework", "formulation", "model")):
            if len(sections["method"]) < 4000:
                sections["method"] += (f"\n[Heading: {heading}]\n" + body[:2000]).strip() + "\n"
        elif any(k in heading for k in ("experiment", "evaluation", "ablation", "result", "benchmark")):
            if len(sections["experiments"]) < 4000:
                sections["experiments"] += (f"\n[Heading: {heading}]\n" + body[:2000]).strip() + "\n"
        elif any(k in heading for k in ("limitation", "discussion", "failure", "conclusion")):
            if len(sections["limitations"]) < 1800:
                sections["limitations"] += (f"\n[Heading: {heading}]\n" + body[:1200]).strip() + "\n"

    # Extract explicit table contents and figure captions for experimental verification
    fig_table_pattern = re.compile(
        r'<figure[^>]*(?:class=["\'][^"\']*(?:ltx_table|ltx_figure)[^"\']*)[^>]*>(.*?)</figure>',
        re.DOTALL | re.IGNORECASE,
    )
    table_snippets: list[str] = []
    for ft_match in fig_table_pattern.finditer(html):
        ft_text = _clean_latexml_chunk(ft_match.group(1))
        if ft_text and len(ft_text) > 30:
            table_snippets.append(ft_text[:600])
        if len(table_snippets) >= 4:
            break
    if table_snippets and len(sections["experiments"]) < 4500:
        sections["experiments"] += "\n[Tables & Figures]\n" + "\n".join(table_snippets)

    return sections


def _extract_markdown_sections(md_text: str) -> dict[str, str]:
    """Splits plain/PDF markdown into Method, Experiments, and Limitations slices."""
    sections = {"method": "", "experiments": "", "limitations": ""}
    if not md_text:
        return sections
    chunks = re.split(r"(?m)^#{1,3}\s+(.+)$", md_text)
    for i in range(1, len(chunks), 2):
        sec_title = chunks[i].strip().lower()
        sec_body = re.sub(r"\s+", " ", chunks[i + 1] if i + 1 < len(chunks) else "").strip()
        if not sec_body:
            continue
        if any(k in sec_title for k in ("method", "approach", "architecture", "framework", "model", "formulation")):
            if len(sections["method"]) < 4000:
                sections["method"] += f"\n[Section: {sec_title}]\n" + sec_body[:2000]
        elif any(k in sec_title for k in ("experiment", "evaluation", "ablation", "result", "benchmark", "table")):
            if len(sections["experiments"]) < 4000:
                sections["experiments"] += f"\n[Section: {sec_title}]\n" + sec_body[:2000]
        elif any(k in sec_title for k in ("limitation", "discussion", "failure", "conclusion")):
            if len(sections["limitations"]) < 1800:
                sections["limitations"] += f"\n[Section: {sec_title}]\n" + sec_body[:1200]
    return sections


def fetch_paper_targeted_sections(paper: Paper) -> dict[str, str]:
    """Extracts Method, Experiments, and Limitations slices for arXiv, OpenReview, or PDF papers."""
    arxiv_id = paper.arxiv_id
    if not arxiv_id and paper.url:
        m = re.search(r"(\d{4}\.\d{4,5})", paper.url)
        if m:
            arxiv_id = m.group(1)
    if arxiv_id:
        secs = fetch_arxiv_targeted_sections(arxiv_id)
        if any(secs.values()):
            return secs

    # Fallback for OpenReview or direct PDF URLs via lightweight pymupdf4llm extraction
    pdf_url = paper.pdf_url or ""
    if not pdf_url and paper.url and "openreview.net" in paper.url.lower():
        or_match = re.search(r"id=([a-zA-Z0-9_\-]+)", paper.url)
        if or_match:
            pdf_url = f"https://openreview.net/pdf?id={or_match.group(1)}"

    if pdf_url:
        try:
            import tempfile
            import os
            import pymupdf4llm

            headers = {"User-Agent": "Mozilla/5.0 (compatible; PaperDaily/1.0)"}
            resp = requests.get(pdf_url, headers=headers, timeout=20)
            if resp.status_code == 200 and len(resp.content) > 1000:
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(resp.content)
                    tf_path = tf.name
                try:
                    md_text = pymupdf4llm.to_markdown(tf_path, write_images=False)
                    secs = _extract_markdown_sections(md_text)
                    if any(secs.values()):
                        return secs
                finally:
                    if os.path.exists(tf_path):
                        os.remove(tf_path)
        except Exception as exc:
            logger.debug(f"PDF targeted section extraction skipped for {pdf_url}: {exc}")

    return {}


def _extract_eprint_tex_sections(tar_bytes: bytes) -> dict[str, str]:
    """Extracts method/experiment sections directly from in-memory TeX files."""
    sections = {"method": "", "experiments": "", "limitations": ""}
    try:
        bio = io.BytesIO(tar_bytes)
        with tarfile.open(fileobj=bio) as tar:
            tex_names = [n for n in tar.getnames() if n.endswith(".tex")]
            for name in tex_names:
                f = tar.extractfile(name)
                if not f:
                    continue
                content = f.read().decode("utf-8", errors="ignore")
                # Remove comments
                content = re.sub(r'%.*\n', '\n', content)
                # Split by \section{...}
                chunks = re.split(r'\\section\*?\{([^}]+)\}', content)
                for i in range(1, len(chunks), 2):
                    sec_title = chunks[i].strip().lower()
                    sec_body = chunks[i + 1] if i + 1 < len(chunks) else ""
                    clean_body = re.sub(r'\\[a-zA-Z]+(\[[^\]]*\])?(\{([^}]*)\})?', r'\3', sec_body)
                    clean_body = re.sub(r'\s+', ' ', clean_body).strip()
                    if not clean_body:
                        continue

                    if any(k in sec_title for k in ("method", "approach", "architecture", "framework", "model")):
                        if len(sections["method"]) < 4000:
                            sections["method"] += f"\n[Section: {sec_title}]\n" + clean_body[:2000]
                    elif any(k in sec_title for k in ("experiment", "evaluation", "result", "benchmark")):
                        if len(sections["experiments"]) < 4000:
                            sections["experiments"] += f"\n[Section: {sec_title}]\n" + clean_body[:2000]
                    elif any(k in sec_title for k in ("limitation", "discussion", "conclusion")):
                        if len(sections["limitations"]) < 1800:
                            sections["limitations"] += f"\n[Section: {sec_title}]\n" + clean_body[:1200]
    except Exception as exc:
        logger.debug(f"Failed to untar e-print: {exc}")

    return sections


def format_sections_content(sections: dict[str, str]) -> str:
    """Formats extracted slices for the LLM prompt or returns 'NONE (Abstract Only)'."""
    if not sections or not any(v.strip() for v in sections.values()):
        return "NONE (Abstract Only)"

    parts = []
    if sections.get("method"):
        parts.append(f"[Method 章节文本与公式]\n{sections['method'].strip()[:4000]}")
    if sections.get("experiments"):
        parts.append(f"[Experiments 主表格与结论段]\n{sections['experiments'].strip()[:4000]}")
    if sections.get("limitations"):
        parts.append(f"[Limitations/Conclusion]\n{sections['limitations'].strip()[:1800]}")

    return "\n\n".join(parts) if parts else "NONE (Abstract Only)"


_GRADE_TO_RUBRIC = {"High": 5, "Medium": 3, "Low": 2, "Unknown": 3}


def _clamp_1_5(val: Any, default: int = 3) -> int:
    try:
        return max(1, min(5, int(round(float(val)))))
    except (TypeError, ValueError):
        return default


def normalize_rubric_scores(
    raw_rubric: Any,
    grades: Optional[dict] = None,
    has_code: bool = False,
    has_sections: bool = False,
) -> dict[str, int]:
    """Normalizes 4D 1-5 rubric scores (delta, rigor, actionability, reproducibility) with deterministic fallbacks."""
    grades = grades if isinstance(grades, dict) else {}
    r_dict = raw_rubric if isinstance(raw_rubric, dict) else {}

    g_support = _GRADE_TO_RUBRIC.get((grades.get("claim_support") or {}).get("grade", "Unknown"), 3)
    g_reuse = _GRADE_TO_RUBRIC.get((grades.get("method_reusability") or {}).get("grade", "Unknown"), 3)
    g_fair = _GRADE_TO_RUBRIC.get((grades.get("baseline_fairness") or {}).get("grade", "Unknown"), 3)

    delta = _clamp_1_5(r_dict.get("delta"), default=max(2, round((g_support + g_reuse) / 2)))
    rigor = _clamp_1_5(r_dict.get("rigor"), default=round((g_support + g_fair) / 2))
    actionability = _clamp_1_5(r_dict.get("actionability"), default=g_reuse)
    default_repro = 4 if has_code else (3 if has_sections else 2)
    reproducibility = _clamp_1_5(r_dict.get("reproducibility"), default=default_repro)

    if has_code and reproducibility < 4:
        reproducibility = min(5, reproducibility + 1)
    elif not has_code and not has_sections and reproducibility > 3:
        reproducibility = 3

    return {
        "delta": delta,
        "rigor": rigor,
        "actionability": actionability,
        "reproducibility": reproducibility,
    }


def compute_review_confidence(
    grades: dict,
    rubric_scores: Optional[dict[str, int]] = None,
    has_code: bool = False,
) -> tuple[int, str]:
    """Computes deterministic review confidence score and qualitative badge without icons."""
    if not isinstance(grades, dict):
        grades = {}

    s_support = GRADE_WEIGHTS.get(grades.get("claim_support", {}).get("grade", "Unknown"), 0)
    s_reuse = GRADE_WEIGHTS.get(grades.get("method_reusability", {}).get("grade", "Unknown"), 0)
    s_fair = GRADE_WEIGHTS.get(grades.get("baseline_fairness", {}).get("grade", "Unknown"), 0)

    # Base deterministic grade score: Reusability (x2), Support (x1.5), Fairness (x1)
    total_score = int(round(s_reuse * 2 + s_support * 1.5 + s_fair * 1))
    if has_code:
        total_score += 1

    if rubric_scores:
        rubric_weighted = (
            0.30 * rubric_scores.get("delta", 3)
            + 0.30 * rubric_scores.get("rigor", 3)
            + 0.25 * rubric_scores.get("actionability", 3)
            + 0.15 * rubric_scores.get("reproducibility", 3)
        )
        # Blend rubric score (2..10 scale) with qualitative grade score
        total_score = int(round(0.5 * total_score + 0.5 * (rubric_weighted * 2.0)))

    low_claim = grades.get("claim_support", {}).get("grade") == "Low"
    low_fair = grades.get("baseline_fairness", {}).get("grade") == "Low"
    low_rigor = bool(rubric_scores and rubric_scores.get("rigor", 3) <= 2)

    if low_claim or low_fair or low_rigor:
        badge = "[证据存疑/基线较弱]"
    elif total_score >= 7:
        badge = "[强烈推荐复用] (高置信度)"
    elif total_score >= 4:
        badge = "[值得参考]"
    else:
        badge = "[仅作了解]"

    return total_score, badge


def compute_composite_paper_score(paper: Paper) -> float:
    """Computes a calibrated 0.0-10.0 composite score combining 4D rubric, recall taste, QA fit, and external signals."""
    rubric = getattr(paper, "rubric_scores", None) or {}
    if rubric:
        rubric_10 = (
            0.30 * rubric.get("delta", 3)
            + 0.30 * rubric.get("rigor", 3)
            + 0.25 * rubric.get("actionability", 3)
            + 0.15 * rubric.get("reproducibility", 3)
        ) * 2.0
    else:
        rubric_10 = float(getattr(paper, "review_score", None) or 5.0)

    recall_raw = float(paper.score or 5.0)
    recall_10 = max(0.0, min(10.0, recall_raw))
    qa_max = float(max(paper.qa_scores.values())) if getattr(paper, "qa_scores", None) else recall_10

    # Weighted blend: 50% 4D LLM Rubric + 25% Recall Taste + 25% Question Fit
    composite = 0.50 * rubric_10 + 0.25 * recall_10 + 0.25 * qa_max

    if getattr(paper, "code_url", None):
        composite += 0.35
    hf_up = getattr(paper, "hf_upvotes", None)
    if hf_up and hf_up > 0:
        import math
        composite += min(0.65, 0.18 * math.log1p(hf_up))

    if getattr(paper, "review_badge", "") == "[证据存疑/基线较弱]" or rubric.get("rigor", 3) <= 2:
        composite -= 1.6

    paper.composite_score = round(max(0.0, min(10.0, composite)), 2)
    return paper.composite_score


def rerank_by_composite_score(papers: list[Paper], deep_read_quota: int = 3) -> list[Paper]:
    """Re-ranks candidate papers using calibrated composite_score and updates deep_read / quick_radar tiers."""
    if not papers:
        return []

    for p in papers:
        if getattr(p, "composite_score", None) is None:
            compute_composite_paper_score(p)

    ordered = sorted(
        papers,
        key=lambda x: (
            float(x.composite_score if x.composite_score is not None else (x.score or 0.0)),
            float(x.score or 0.0),
        ),
        reverse=True,
    )

    deep_cnt = 0
    for p in ordered:
        rubric = getattr(p, "rubric_scores", None) or {}
        rigor = rubric.get("rigor", getattr(p, "evidence_rigor", None) or 3)
        weak_evidence = getattr(p, "review_badge", "") == "[证据存疑/基线较弱]" or rigor <= 2
        if not weak_evidence and deep_cnt < deep_read_quota:
            p.recommendation_tier = "deep_read"
            deep_cnt += 1
        else:
            p.recommendation_tier = "quick_radar"

    if ordered and deep_cnt == 0:
        ordered[0].recommendation_tier = "deep_read"

    return ordered


CRITICAL_PAPER_DIGEST_SYSTEM_PROMPT = """# Role
你是一位顶尖的计算机科学审稿人（Journal-Club 级别）与科研架构师。你的任务是对候选论文进行高密度信息浓缩与证据级批判，彻底摒弃空洞的“公关稿式”总结（严禁复述研究背景和泛泛而谈的套话）。

# Core Execution Rules (严格执行)
1. **反吹嘘核验 (Anti-Hype Verification)**：
   - 对比 Abstract 中的声称（Claim）与 Extracted Sections 中的实验表格/限制条件。
   - 如果作者在 Abstract 声称“大幅超越/SOTA”，但正文中仅在特定小数据集有效、或带来了巨大的算力/延迟代价、或对比的基线已经过时，必须在 `inline_annotations` 的 `critique` 中一针见血地指出具体证据。
2. **禁止脑补与待查标记 (No Hallucination & Full-Text Check)**：
   - 若 `Extracted Sections` 为 "NONE (Abstract Only)"，或正文中未交代清楚关键实现细节/消融实验，绝对禁止猜测。必须在 `action_or_check` 字段中以 `[需查正文: 具体去查哪张表/哪个超参/哪个消融实验]` 的格式明确标出。
3. **高密度机制还原 (Mechanism & Formula)**：
   - 必须用单行箭头流（`输入 -> 处理模块A (做什么) -> 处理模块B (做什么) -> 输出`）描述方法全貌。
   - 若提供了正文，提取最核心的 1 个数学公式（LaTeX 格式），并用一句话解释公式中关键符号的物理意义；若仅有 Abstract 则填 'N/A (需查正文)'。
4. **定性分档与四维量化评估 (Qualitative & 4D Rubric Grading)**：
   - 对以下三个定性维度给出 `High` / `Medium` / `Low` 的档位及一句话证据：
     * `claim_support`（实验数据对核心声称的支撑度）
     * `method_reusability`（方法对【用户的核心研究问题】的直接可迁移/可复用度）
     * `baseline_fairness`（实验对比基线的公平性与时效性，是否漏掉关键对比；仅看 Abstract 时填 `Unknown`）
   - 同时在 `rubric_scores` 中给出 4 个正交维度的 1-5 整数评分（1=极差/存疑，3=中规中矩，5=顶尖典范）：
     * `delta`（1-5：方法核心创新增量，简单 A+B 拼接或套壳不超过 2 分）
     * `rigor`（1-5：实验消融完备度、基线强弱与算力开销透明度）
     * `actionability`（1-5：对用户核心追踪问题与现有知识库的直接迁移启发价值）
     * `reproducibility`（1-5：开源代码/项目链接完备度与算法复现清晰度）
5. **优先级覆盖**：若用户控制台自定义阅读规则中有特殊格式或关注点要求，在满足上述 JSON 结构的前提下优先遵循用户规则。
6. **无表情符号 (Strictly No Emojis/Icons)**：输出内容纯文字排版，严禁使用任何 emoji 表情符号。

# Output Schema (严格输出纯 JSON，不要包含 Markdown 代码块包裹以外的任何解释文字)
{
  "delta": "一句话说明：相比已知基线（优先生效已知基线列表中的相关工作），本文最核心的改动变量是什么？（限 50 字内）",
  "mechanism": {
    "pipeline": "输入 X -> 模块 A (做什么) -> 模块 B (做什么) -> 输出 Y",
    "core_formula": "核心公式的 LaTeX 字符串（若仅有 Abstract 则填 'N/A (需查正文)'）",
    "symbol_dict": "公式中核心变量符号的极简释义"
  },
  "evidence_and_cost": {
    "metrics": "在什么具体 Benchmark 上，核心指标相比哪个 Baseline 提升了多少具体数值（若仅有 Abstract 且无数字，填 'Abstract未给出具体数值'）",
    "cost_and_limits": "训练/推理代价（显存、延迟、额外数据量）及边界失效条件"
  },
  "action_or_check": "【对关注问题的启发/可复用技巧】 + 【[需查正文: ...] 标记的具体待核验项】",
  "qualitative_grades": {
    "claim_support": {"grade": "High | Medium | Low", "reason": "一句话证据"},
    "method_reusability": {"grade": "High | Medium | Low", "reason": "一句话证据"},
    "baseline_fairness": {"grade": "High | Medium | Low | Unknown", "reason": "一句话证据"}
  },
  "rubric_scores": {
    "delta": 4,
    "rigor": 4,
    "actionability": 4,
    "reproducibility": 3
  },
  "inline_annotations": [
    {
      "exact_quote": "必须一字不差地摘自 Abstract 原文的句子或短语",
      "type": "baseline | claim | critique",
      "comment": "原位批注内容：若为 baseline 则说明关联基线；若为 claim 则标注验证情况；若为 critique 则指出局限或水分"
    }
  ]
}"""


def run_critical_paper_digest(
    router: LLMRouter,
    paper: Paper,
    questions: list[str],
    library_baselines: list[str],
    user_custom_rules: list[str] | str = "",
    user_note_template: list[str] | str = "",
    is_tier1: bool = True,
) -> dict[str, Any]:
    """Runs the Critical-Paper-Digest review skill on a paper and populates paper attributes."""
    if not router.available or not paper.abstract:
        return {}

    # 1. Prepare slices (supports arXiv HTML/ar5iv/TeX + OpenReview/PDF fallback)
    sections_content = "NONE (Abstract Only)"
    has_sections = False
    if is_tier1:
        sections = fetch_paper_targeted_sections(paper)
        sections_content = format_sections_content(sections)
        has_sections = sections_content != "NONE (Abstract Only)"
        if has_sections and (not getattr(paper, "code_url", None) or not getattr(paper, "project_url", None)):
            from ..protocol import extract_paper_artifacts
            sec_artifacts = extract_paper_artifacts(sections_content)
            if not getattr(paper, "code_url", None) and sec_artifacts.get("code_url"):
                paper.code_url = sec_artifacts["code_url"]
            if not getattr(paper, "project_url", None) and sec_artifacts.get("project_url"):
                paper.project_url = sec_artifacts["project_url"]

    # 2. Format inputs
    q_str = "\n".join(f"- {i}. {q}" for i, q in enumerate(questions, 1)) if questions else "无特定关注问题"
    base_str = ", ".join(library_baselines[:25]) if library_baselines else "无（知识库暂空）"
    if isinstance(user_custom_rules, list):
        rule_str = "\n".join(f"- {r}" for r in user_custom_rules) if user_custom_rules else "无额外自定义规则，遵循默认高密度审阅规范。"
    else:
        rule_str = str(user_custom_rules).strip() or "无额外自定义规则，遵循默认高密度审阅规范。"

    if isinstance(user_note_template, list) and user_note_template:
        tpl_str = "\n".join(f"- {t}" for t in user_note_template)
        rule_str += f"\n\n[用户自定义总结模板要求]:\n{tpl_str}"
    elif isinstance(user_note_template, str) and user_note_template.strip():
        rule_str += f"\n\n[用户自定义总结模板要求]:\n{user_note_template.strip()}"

    artifact_hint = (
        f"Code URL: {getattr(paper, 'code_url', None) or 'None detected'} | "
        f"Project URL: {getattr(paper, 'project_url', None) or 'None detected'} | "
        f"HF Upvotes: {getattr(paper, 'hf_upvotes', None) or 'N/A'}"
    )
    user_prompt = (
        f"# Context Inputs\n"
        f"1. 用户的核心研究问题 (Target Questions):\n{q_str}\n\n"
        f"2. 用户知识库中的已知基线/概念 (Known Baselines & Concepts):\n{base_str}\n\n"
        f"3. 用户控制台自定义阅读规则 (User Custom Rules):\n{rule_str}\n\n"
        f"4. 论文元数据与正文切片 (Paper Content):\n"
        f"- Title: {paper.title}\n"
        f"- Artifacts & Community Signals: {artifact_hint}\n"
        f"- Abstract:\n{paper.abstract.strip()}\n\n"
        f"- Extracted Sections (Method / Experiments / Limitations):\n"
        f"<untrusted_source>\n{sections_content}\n</untrusted_source>\n\n"
        f"Output pure JSON according to the Output Schema."
    )

    try:
        raw = router.chat(
            [
                {"role": "system", "content": CRITICAL_PAPER_DIGEST_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=3000,
            temperature=0.1,
            timeout=90,
        )
        data = extract_json(raw, {})
        if not isinstance(data, dict):
            return {}

        # 3. Post-processing & deterministic 4D rubric + composite scoring
        grades = data.get("qualitative_grades") or {}
        has_code = bool(getattr(paper, "code_url", None))
        rubric = normalize_rubric_scores(
            data.get("rubric_scores"),
            grades=grades,
            has_code=has_code,
            has_sections=has_sections,
        )
        data["rubric_scores"] = rubric
        paper.rubric_scores = rubric
        paper.evidence_rigor = rubric["rigor"]

        score, badge = compute_review_confidence(grades, rubric_scores=rubric, has_code=has_code)
        paper.review_score = score
        paper.review_badge = badge
        paper.critical_digest = data
        compute_composite_paper_score(paper)

        # Map TLDR fields for legacy consumers
        delta = data.get("delta", "").strip()
        pipeline = (data.get("mechanism") or {}).get("pipeline", "").strip()
        if delta:
            paper.tldr_zh = delta
            paper.tldr = delta
        if pipeline:
            paper.tldr_en = pipeline

        # Map inline annotations to standard protocol structure
        raw_anns = data.get("inline_annotations") or []
        valid_anns = []
        for ann in raw_anns:
            quote_text = ann.get("exact_quote") or ann.get("quote") or ""
            if not quote_text or quote_text.strip() not in paper.abstract:
                # Try case-insensitive matching
                m = re.search(re.escape(quote_text.strip()), paper.abstract, re.IGNORECASE)
                if m:
                    quote_text = m.group(0)
                else:
                    continue
            valid_anns.append({
                "source": "S1",
                "quote": quote_text.strip(),
                "type": ann.get("type", "claim"),
                "comment": ann.get("comment", "").strip(),
            })
        if valid_anns:
            paper.inline_annotations = valid_anns
            paper.annotation_sections = [{"id": "S1", "title": "摘要", "text": paper.abstract.strip()}]

        return data
    except Exception as exc:
        logger.warning(f"Critical-Paper-Digest failed for '{paper.title}': {exc}")
        return {}


def format_rubric_summary_line(paper: Paper) -> str:
    """Formats a compact, single-line 4D rubric and external signal summary string."""
    rubric = getattr(paper, "rubric_scores", None) or (getattr(paper, "critical_digest", None) or {}).get("rubric_scores")
    parts: list[str] = []
    if getattr(paper, "composite_score", None) is not None:
        parts.append(f"综合 {paper.composite_score:.1f}/10")
    if isinstance(rubric, dict) and rubric:
        parts.append(
            f"创新:{rubric.get('delta', '-')} "
            f"扎实:{rubric.get('rigor', '-')} "
            f"启发:{rubric.get('actionability', '-')} "
            f"复现:{rubric.get('reproducibility', '-')}"
        )
    if getattr(paper, "hf_upvotes", None):
        parts.append(f"HF热度:{paper.hf_upvotes}")
    if getattr(paper, "code_url", None):
        parts.append("开源代码:已附")
    return " | ".join(parts)


def format_digest_feishu_elements(
    paper: Paper,
    corpus: Optional[list[CorpusPaper]] = None,
    client: Any = None,
) -> list[dict[str, Any]]:
    """Renders Feishu Docx elements for Critical-Paper-Digest without any emoji/icons."""
    elements: list[dict[str, Any]] = []
    digest = paper.critical_digest or {}

    grades = digest.get("qualitative_grades") or {}
    r_grade = grades.get("method_reusability", {}).get("grade", "N/A")
    s_grade = grades.get("claim_support", {}).get("grade", "N/A")
    f_grade = grades.get("baseline_fairness", {}).get("grade", "N/A")

    badge = paper.review_badge or "[仅作了解]"
    rubric_line = format_rubric_summary_line(paper)
    extra_meta = f" | {rubric_line}" if rubric_line else ""

    # 1. 审稿评级
    elements.append({"text_run": {"content": "[审稿评级]：", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"{badge} ", "text_element_style": {"bold": True, "text_color": 1}}})
    elements.append({"text_run": {"content": f"(复用度: {r_grade} | 证据支撑: {s_grade} | 基线公平: {f_grade}{extra_meta})\n"}})

    # 1b. 开源代码与项目主页链接（若存在）
    if getattr(paper, "code_url", None) or getattr(paper, "project_url", None):
        elements.append({"text_run": {"content": "• [开源与复现]：", "text_element_style": {"bold": True}}})
        if getattr(paper, "code_url", None):
            elements.append({"text_run": {"content": f"代码仓库 ({paper.code_url}) "}})
        if getattr(paper, "project_url", None):
            elements.append({"text_run": {"content": f"项目主页 ({paper.project_url})"}})
        elements.append({"text_run": {"content": "\n"}})

    # 2. 核心增量 (Delta)
    delta = digest.get("delta") or paper.tldr_zh or "暂无核心增量记录"
    elements.append({"text_run": {"content": "• [核心增量] (Delta)：", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"{delta}\n"}})

    # 3. 方法链路与公式 (Mechanism)
    mech = digest.get("mechanism") or {}
    pipeline = mech.get("pipeline") or "N/A"
    formula = mech.get("core_formula") or "N/A"
    symbols = mech.get("symbol_dict") or "N/A"
    elements.append({"text_run": {"content": "• [方法链路与公式] (Mechanism)：\n", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"  - 链路：{pipeline}\n"}})
    elements.append({"text_run": {"content": f"  - 核心公式：{formula}\n"}})
    elements.append({"text_run": {"content": f"  - 符号释义：{symbols}\n"}})

    # 4. 实验真相与代价 (Truth & Cost)
    ev = digest.get("evidence_and_cost") or {}
    metrics = ev.get("metrics") or "N/A"
    cost = ev.get("cost_and_limits") or "N/A"
    elements.append({"text_run": {"content": "• [实验真相与代价] (Truth & Cost)：\n", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"  - 真实提升：{metrics}\n"}})
    elements.append({"text_run": {"content": f"  - 代价与边界：{cost}\n"}})

    # 5. 启发与待查 (Action / Check)
    action = digest.get("action_or_check") or "N/A"
    elements.append({"text_run": {"content": "• [启发与待查] (Action / Check)：\n", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"  {action}\n\n"}})

    return elements


def format_digest_html(paper: Paper) -> str:
    """Renders HTML card markup for Critical-Paper-Digest without any emoji/icons."""
    digest = paper.critical_digest or {}
    grades = digest.get("qualitative_grades") or {}
    r_grade = grades.get("method_reusability", {}).get("grade", "N/A")
    s_grade = grades.get("claim_support", {}).get("grade", "N/A")
    f_grade = grades.get("baseline_fairness", {}).get("grade", "N/A")
    badge = paper.review_badge or "[仅作了解]"
    rubric_line = format_rubric_summary_line(paper)

    delta = digest.get("delta") or paper.tldr_zh or "暂无核心增量记录"
    mech = digest.get("mechanism") or {}
    ev = digest.get("evidence_and_cost") or {}
    action = digest.get("action_or_check") or "N/A"

    import html
    e = html.escape

    rubric_html = (
        f'<div style="margin-bottom:6px;font-size:12.5px;color:#1e3a8a;background:#eff6ff;padding:4px 8px;border-radius:4px;">'
        f'<strong>[四维量化评分]</strong>：{e(rubric_line)}</div>'
        if rubric_line
        else ""
    )

    artifact_links: list[str] = []
    if getattr(paper, "code_url", None):
        artifact_links.append(f'<a href="{e(paper.code_url, quote=True)}">开源代码仓库</a>')
    if getattr(paper, "project_url", None):
        artifact_links.append(f'<a href="{e(paper.project_url, quote=True)}">项目主页</a>')
    artifact_html = (
        f'<div style="margin-bottom:4px;"><strong>• [开源与复现]</strong>：{" | ".join(artifact_links)}</div>'
        if artifact_links
        else ""
    )

    return f"""<div style="background:#f9f9fb;border-left:3px solid #0052cc;padding:10px 14px;margin:8px 0;border-radius:4px;font-size:13.5px;line-height:1.65;color:#222;">
  <div style="margin-bottom:6px;"><strong>[审稿评级]</strong>：<span style="font-weight:700;color:#0052cc;">{e(badge)}</span> <span style="color:#666;font-size:12px;">(复用度: {e(r_grade)} | 证据支撑: {e(s_grade)} | 基线公平: {e(f_grade)})</span></div>
  {rubric_html}
  {artifact_html}
  <div style="margin-bottom:4px;"><strong>• [核心增量] (Delta)</strong>：{e(delta)}</div>
  <div style="margin-bottom:4px;">
    <strong>• [方法链路与公式] (Mechanism)</strong>：
    <div style="padding-left:14px;color:#333;">
      - 链路：<code>{e(mech.get('pipeline', 'N/A'))}</code><br/>
      - 核心公式：<code>{e(mech.get('core_formula', 'N/A'))}</code><br/>
      - 符号释义：{e(mech.get('symbol_dict', 'N/A'))}
    </div>
  </div>
  <div style="margin-bottom:4px;">
    <strong>• [实验真相与代价] (Truth & Cost)</strong>：
    <div style="padding-left:14px;color:#333;">
      - 真实提升：{e(ev.get('metrics', 'N/A'))}<br/>
      - 代价与边界：{e(ev.get('cost_and_limits', 'N/A'))}
    </div>
  </div>
  <div>
    <strong>• [启发与待查] (Action / Check)</strong>：
    <div style="padding-left:14px;color:#006621;font-weight:500;">{e(action)}</div>
  </div>
</div>"""
