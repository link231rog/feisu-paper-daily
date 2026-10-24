"""Deep-research loop: query planning, seed chasing, per-question synthesis, next-round questions."""

from enum import Enum
import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from .llm import LLMRouter
from .protocol import Paper


class HypothesisStatus(str, Enum):
    """Lifecycle status of a research question/hypothesis."""
    EXPLORING = "exploring"     # 🌱 探索期：双向搜集初步机制与基线
    CONTESTED = "contested"     # ⚖️ 争议期：同时存在支持与反例证据，优先追踪
    CONVERGED = "converged"     # ✅ 已收敛：证据链充分，降低频率并派生子问题
    FALSIFIED = "falsified"     # ❌ 已证伪：核心假设被反例推翻，归档


def _json_block(raw: str, default: Any) -> Any:
    if not raw:
        return default
    match = re.search(r"(\{.*\}|\[.*\])", raw, flags=re.DOTALL)
    if not match:
        return default
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError:
        return default


def _paper_digest(papers: list[Paper], limit: int = 30) -> str:
    lines = []
    for idx, paper in enumerate(papers[:limit], 1):
        abstract = (paper.abstract or "").replace("\n", " ")[:300]
        lines.append(f"{idx}. {paper.title} ({paper.url})\n   {abstract}")
    return "\n".join(lines)


def plan_queries(
    router: LLMRouter,
    tags: list[str],
    questions: list[str],
    known_titles: list[str] | None = None,
) -> dict[str, list[str]]:
    """Turns tracked tags and questions into affirmative and adversarial search queries."""
    if not router.available or not (tags or questions):
        return {"s2_queries": [], "arxiv_categories": []}

    prompt = (
        "You plan literature search for an active scientific research assistant.\n"
        f"Tags: {', '.join(tags) or 'none'}\n"
        f"Questions:\n" + "\n".join(f"- {q}" for q in questions) + "\n"
        f"Already seen examples: {'; '.join((known_titles or [])[:10]) or 'none'}\n\n"
        "Generate a dual search plan:\n"
        "1. affirmative_s2: 3-4 queries targeting mechanisms, architectures, and positive SOTA benchmark results.\n"
        "2. adversarial_s2: 2-3 counter-queries targeting failure modes, ablation degradation, scaling limits, or negative results that challenge assumptions.\n"
        "3. arxiv_categories: 2-4 arXiv categories (e.g. cs.AI, cs.CL, cs.LG).\n\n"
        "Return ONLY JSON:\n"
        '{"affirmative_s2": [...], "adversarial_s2": [...], "arxiv_categories": [...]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1400), {})
    pos = [str(q) for q in data.get("affirmative_s2", []) if str(q).strip()][:4]
    neg = [str(q) for q in data.get("adversarial_s2", []) if str(q).strip()][:3]
    # Fallback if model returns legacy s2_queries key
    if not pos and not neg and data.get("s2_queries"):
        pos = [str(q) for q in data.get("s2_queries", []) if str(q).strip()][:6]

    combined = pos + neg
    return {
        "s2_queries": combined[:7],
        "affirmative_s2": pos,
        "adversarial_s2": neg,
        "arxiv_categories": [str(c) for c in data.get("arxiv_categories", []) if str(c).strip()][:4],
    }


def pick_seeds(router: LLMRouter, papers: list[Paper], limit: int = 4) -> list[str]:
    """Chooses papers worth chasing through citations and references."""
    if not router.available or not papers:
        return []
    prompt = (
        "Pick the papers most worth following through their citations and references "
        "to answer ongoing research questions.\n\n"
        f"{_paper_digest(papers, 20)}\n\n"
        f"Return ONLY a JSON array of up to {limit} numbers from the list above."
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=800), [])
    seeds = []
    for item in data if isinstance(data, list) else []:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= min(len(papers), 20):
            seeds.append(papers[idx - 1].url)
    return seeds[:limit]


def synthesize_questions(router: LLMRouter, questions: list[str], papers: list[Paper]) -> list[dict]:
    """Writes one evidence brief per tracked question, identifying both supporting and counter evidence."""
    if not router.available or not questions or not papers:
        return []

    briefs: list[dict] = []
    digest = _paper_digest(papers, 25)
    for question in questions[:5]:
        prompt = (
            f"Research question: {question}\n\nToday's candidate papers:\n{digest}\n\n"
            "Write a concise Chinese brief (120-220 字) analyzing today's evidence for this question:\n"
            "1. summary: Core progress and whether evidence is affirmative, disputed, or negative.\n"
            "2. evidence: Supporting papers (title, url).\n"
            "3. counter_evidence: Papers showing failure modes, limitations, or counter-results (title, url).\n"
            "4. gap: What remains unanswered or debated.\n"
            "5. status: One of 'exploring' (preliminary), 'contested' (debated/opposing views), 'converged' (strongly answered), 'falsified' (refuted).\n\n"
            'Return ONLY JSON: {"summary": "...", "evidence": [{"title": "...", "url": "..."}], "counter_evidence": [{"title": "...", "url": "..."}], "gap": "...", "status": "..."}'
        )
        data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1600), {})
        summary = str(data.get("summary", "")).strip()
        if not summary:
            continue
        evidence = [
            {"title": str(e.get("title", "")), "url": str(e.get("url", ""))}
            for e in data.get("evidence", [])
            if isinstance(e, dict) and e.get("title")
        ]
        counter = [
            {"title": str(c.get("title", "")), "url": str(c.get("url", ""))}
            for c in data.get("counter_evidence", [])
            if isinstance(c, dict) and c.get("title")
        ]
        briefs.append(
            {
                "question": question,
                "summary": summary,
                "evidence": evidence,
                "counter_evidence": counter,
                "gap": str(data.get("gap", "")).strip(),
                "status": str(data.get("status", "exploring")).strip().lower(),
            }
        )
    return briefs


def suggest_next_questions(
    router: LLMRouter,
    questions: list[str],
    briefs: list[dict],
    accepted_titles: list[str] | None = None,
) -> list[str]:
    """Proposes refined sub-questions for the next round; a human approves them."""
    if not router.available or not questions:
        return []

    brief_text = "\n".join(
        f"- {b['question']}: {b['summary']} (gap: {b.get('gap', '')})" for b in briefs
    ) or "no briefs today"
    prompt = (
        "You refine a research agenda.\n"
        f"Current questions:\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"
        f"Today's briefs:\n{brief_text}\n\n"
        f"Papers the reader accepted today: {', '.join((accepted_titles or [])[:10]) or 'none'}\n\n"
        "Propose 2-4 sharper follow-up questions that would move the research forward. "
        "Each must be answerable by literature search and must not repeat an existing question.\n"
        'Return ONLY JSON: {"questions": ["..."]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1000), {})
    existing = {q.strip().lower() for q in questions}
    proposed = []
    for item in data.get("questions", []) if isinstance(data, dict) else []:
        text = str(item).strip()
        if text and text.lower() not in existing:
            proposed.append(text)
    return proposed[:4]


def question_weights(state: "ResearchState", questions: list[str]) -> dict[str, float]:
    """Weights questions dynamically based on their hypothesis status and saturation."""
    weights = {}
    for q in questions:
        status = state.get_status(q)
        if status == HypothesisStatus.CONTESTED:
            weights[q] = 1.35  # prioritize unresolved debate
        elif status == HypothesisStatus.CONVERGED:
            weights[q] = 0.35  # lower frequency for resolved problems
        elif status == HypothesisStatus.FALSIFIED:
            weights[q] = 0.1   # minimal for abandoned hypotheses
        elif state.saturated(q):
            weights[q] = 0.6   # decay stale exploring questions
        else:
            weights[q] = 1.0
    return weights


def judge_ranking(router: LLMRouter, questions: list[str], papers: list[Paper]) -> list[int]:
    """Comparatively ranks candidates in one call; returns 0-based indices best first."""
    if not router.available or len(papers) < 2:
        return list(range(len(papers)))

    listing = "\n".join(
        f"{idx}. {p.title}\n   {(p.abstract or '').replace(chr(10), ' ')[:400]}"
        for idx, p in enumerate(papers, 1)
    )
    prompt = (
        "You are ranking today's candidate papers for a researcher. Judge how much each "
        "paper would actually advance their tracked questions, not how popular it is.\n\n"
        f"Tracked questions:\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"
        f"Candidates:\n{listing}\n\n"
        "Order them best first. Prefer concrete mechanisms, results or benchmarks that "
        "answer a question over papers that merely mention the topic. Drop papers that "
        "add nothing new to an already-covered point.\n"
        'Return ONLY JSON: {"ranking": [{"index": 3, "reason": "一句话中文理由"}], "dropped": [7]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=2500), {})
    if not isinstance(data, dict):
        return list(range(len(papers)))

    dropped = {int(i) for i in data.get("dropped", []) if str(i).isdigit()}
    order: list[int] = []
    for item in data.get("ranking", []):
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError, AttributeError):
            continue
        if 1 <= idx <= len(papers) and (idx - 1) not in order:
            order.append(idx - 1)
            papers[idx - 1].judge_reason = str(item.get("reason", "")).strip() or None
    # Anything the judge omitted keeps its fused order behind the ranked block
    order.extend(i for i in range(len(papers)) if i not in order and i not in dropped)
    order.extend(i for i in range(len(papers)) if i in dropped and i not in order)
    return order


class ResearchState:
    """Tracks per-question evidence and hypothesis state machine across daily runs."""

    def __init__(self, path: str = "data/research_state.json"):
        self.path = Path(path)
        self.data: dict[str, Any] = {"questions": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning(f"Could not read research state at {self.path}; starting fresh")

    def get_status(self, question: str) -> HypothesisStatus:
        raw = (self.data.get("questions", {}).get(question, {}).get("status") or "").lower()
        for s in HypothesisStatus:
            if s.value == raw:
                return s
        return HypothesisStatus.EXPLORING

    def record(self, briefs: list[dict]) -> None:
        today = date.today().isoformat()
        for brief in briefs:
            entry = self.data.setdefault("questions", {}).setdefault(
                brief["question"], {
                    "evidence_days": [],
                    "last_count": 0,
                    "gap": "",
                    "status": HypothesisStatus.EXPLORING.value,
                    "supporting_count": 0,
                    "counter_count": 0,
                }
            )
            count = len(brief.get("evidence", []))
            counter_count = len(brief.get("counter_evidence", []))
            if count and (not entry["evidence_days"] or entry["evidence_days"][-1] != today):
                entry["evidence_days"].append(today)
            entry["last_count"] = count
            entry["supporting_count"] = entry.get("supporting_count", 0) + count
            entry["counter_count"] = entry.get("counter_count", 0) + counter_count
            entry["gap"] = brief.get("gap", "")

            # Dynamic Hypothesis Status Transition
            suggested_status = brief.get("status")
            if suggested_status in [s.value for s in HypothesisStatus]:
                entry["status"] = suggested_status
            elif entry["counter_count"] > 0 and entry["supporting_count"] > 0:
                entry["status"] = HypothesisStatus.CONTESTED.value
            elif entry["supporting_count"] >= 6 and not entry.get("gap"):
                entry["status"] = HypothesisStatus.CONVERGED.value
            else:
                entry["status"] = entry.get("status", HypothesisStatus.EXPLORING.value)

            entry["updated"] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def saturated(self, question: str, days: int = 7) -> bool:
        entry = self.data.get("questions", {}).get(question)
        if not entry or not entry.get("evidence_days"):
            return False
        last = date.fromisoformat(entry["evidence_days"][-1])
        return (date.today() - last) >= timedelta(days=days)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
