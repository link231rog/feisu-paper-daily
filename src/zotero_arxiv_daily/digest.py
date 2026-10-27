"""Critical-Paper-Digest: Default high-density journal-club review protocol and section extraction.

Extracts targeted paper slices (Method, Experiments, Limitations) from arXiv HTML/ar5iv/e-print,
invokes the default Critical-Paper-Digest review prompt with anti-hype verification,
and deterministically computes qualitative review confidence scores without decorative icons.
"""

import io
import re
import tarfile
from typing import Any, Optional
from urllib.parse import quote

import requests
from loguru import logger

from .llm import LLMRouter
from .protocol import CorpusPaper, Paper
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
    """Parses Method, Experiments, and Limitations from LaTeXML HTML."""
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

    return sections


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


def compute_review_confidence(grades: dict) -> tuple[int, str]:
    """Computes deterministic review confidence score and qualitative badge without icons."""
    if not isinstance(grades, dict):
        return 0, "[仅作了解]"

    s_support = GRADE_WEIGHTS.get(grades.get("claim_support", {}).get("grade", "Unknown"), 0)
    s_reuse = GRADE_WEIGHTS.get(grades.get("method_reusability", {}).get("grade", "Unknown"), 0)
    s_fair = GRADE_WEIGHTS.get(grades.get("baseline_fairness", {}).get("grade", "Unknown"), 0)

    # Weights: Reusability (x2), Support (x1.5), Fairness (x1)
    total_score = int(s_reuse * 2 + s_support * 1.5 + s_fair * 1)

    # Automatic anti-hype warning badge
    if grades.get("claim_support", {}).get("grade") == "Low" or grades.get("baseline_fairness", {}).get("grade") == "Low":
        badge = "[证据存疑/基线较弱]"
    elif total_score >= 6:
        badge = "[强烈推荐复用] (高置信度)"
    elif total_score >= 3:
        badge = "[值得参考]"
    else:
        badge = "[仅作了解]"

    return total_score, badge


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
4. **定性分档评估 (Qualitative Grading - 供系统确定性算分)**：
   - 不要给数字总分。仅对以下三个维度给出 `High` / `Medium` / `Low` 的定性档位及一句话证据：
     * `claim_support`（实验数据对核心声称的支撑度）
     * `method_reusability`（方法对【用户的核心研究问题】的直接可迁移/可复用度）
     * `baseline_fairness`（实验对比基线的公平性与时效性，是否漏掉关键对比；仅看 Abstract 时填 `Unknown`）
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
    is_tier1: bool = True,
) -> dict[str, Any]:
    """Runs the Critical-Paper-Digest review skill on a paper and populates paper attributes."""
    if not router.available or not paper.abstract:
        return {}

    # 1. Prepare slices
    sections_content = "NONE (Abstract Only)"
    if is_tier1 and paper.arxiv_id:
        sections = fetch_arxiv_targeted_sections(paper.arxiv_id)
        sections_content = format_sections_content(sections)

    # 2. Format inputs
    q_str = "\n".join(f"- {i}. {q}" for i, q in enumerate(questions, 1)) if questions else "无特定关注问题"
    base_str = ", ".join(library_baselines[:25]) if library_baselines else "无（知识库暂空）"
    if isinstance(user_custom_rules, list):
        rule_str = "\n".join(f"- {r}" for r in user_custom_rules) if user_custom_rules else "无额外自定义规则，遵循默认高密度审阅规范。"
    else:
        rule_str = str(user_custom_rules).strip() or "无额外自定义规则，遵循默认高密度审阅规范。"

    user_prompt = (
        f"# Context Inputs\n"
        f"1. 用户的核心研究问题 (Target Questions):\n{q_str}\n\n"
        f"2. 用户知识库中的已知基线/概念 (Known Baselines & Concepts):\n{base_str}\n\n"
        f"3. 用户控制台自定义阅读规则 (User Custom Rules):\n{rule_str}\n\n"
        f"4. 论文元数据与正文切片 (Paper Content):\n"
        f"- Title: {paper.title}\n"
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

        # 3. Post-processing & deterministic scoring
        grades = data.get("qualitative_grades") or {}
        score, badge = compute_review_confidence(grades)
        paper.review_score = score
        paper.review_badge = badge
        paper.critical_digest = data

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

    # 1. 审稿评级
    elements.append({"text_run": {"content": "[审稿评级]：", "text_element_style": {"bold": True}}})
    elements.append({"text_run": {"content": f"{badge} ", "text_element_style": {"bold": True, "text_color": 1}}})
    elements.append({"text_run": {"content": f"(复用度: {r_grade} | 证据支撑: {s_grade} | 基线公平: {f_grade})\n"}})

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

    delta = digest.get("delta") or paper.tldr_zh or "暂无核心增量记录"
    mech = digest.get("mechanism") or {}
    ev = digest.get("evidence_and_cost") or {}
    action = digest.get("action_or_check") or "N/A"

    import html
    e = html.escape

    return f"""<div style="background:#f9f9fb;border-left:3px solid #0052cc;padding:10px 14px;margin:8px 0;border-radius:4px;font-size:13.5px;line-height:1.65;color:#222;">
  <div style="margin-bottom:6px;"><strong>[审稿评级]</strong>：<span style="font-weight:700;color:#0052cc;">{e(badge)}</span> <span style="color:#666;font-size:12px;">(复用度: {e(r_grade)} | 证据支撑: {e(s_grade)} | 基线公平: {e(f_grade)})</span></div>
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
