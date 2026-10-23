"""Deep-research loop: query planning, seed chasing, per-question synthesis, next-round questions."""

import json
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from .llm import LLMRouter
from .protocol import Paper


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
    """Turns tracked tags and questions into this run's search plan."""
    if not router.available or not (tags or questions):
        return {"s2_queries": [], "arxiv_categories": []}

    prompt = (
        "You plan literature search for a research assistant.\n"
        f"Tags: {', '.join(tags) or 'none'}\n"
        f"Questions:\n" + "\n".join(f"- {q}" for q in questions) + "\n"
        f"Already seen examples: {'; '.join((known_titles or [])[:10]) or 'none'}\n\n"
        "Produce 4-6 specific English search queries that would surface papers answering "
        "these questions, and 2-4 arXiv categories (e.g. cs.AI, cs.CL, cs.LG).\n"
        "Return ONLY JSON: {\"s2_queries\": [...], \"arxiv_categories\": [...]}"
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1200), {})
    return {
        "s2_queries": [str(q) for q in data.get("s2_queries", []) if str(q).strip()][:6],
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
    """Writes one evidence brief per tracked question, with citations and gaps."""
    if not router.available or not questions or not papers:
        return []

    briefs: list[dict] = []
    digest = _paper_digest(papers, 25)
    for question in questions[:5]:
        prompt = (
            f"Research question: {question}\n\nToday's candidate papers:\n{digest}\n\n"
            "Write a short Chinese brief (120-200 字) on what today's papers contribute to this "
            "question: the main findings, which papers support them (cite titles), and what "
            "remains unanswered. If nothing is relevant, say so plainly.\n"
            'Return ONLY JSON: {"summary": "...", "evidence": [{"title": "...", "url": "..."}], "gap": "..."}'
        )
        data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1500), {})
        summary = str(data.get("summary", "")).strip()
        if not summary:
            continue
        evidence = [
            {"title": str(e.get("title", "")), "url": str(e.get("url", ""))}
            for e in data.get("evidence", [])
            if isinstance(e, dict) and e.get("title")
        ]
        briefs.append(
            {
                "question": question,
                "summary": summary,
                "evidence": evidence,
                "gap": str(data.get("gap", "")).strip(),
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
    """Downweights questions whose evidence has gone stale so others get a turn."""
    return {q: (0.6 if state.saturated(q) else 1.0) for q in questions}


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
    """Tracks per-question evidence so saturated directions can pivot."""

    def __init__(self, path: str = "data/research_state.json"):
        self.path = Path(path)
        self.data: dict[str, Any] = {"questions": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning(f"Could not read research state at {self.path}; starting fresh")

    def record(self, briefs: list[dict]) -> None:
        today = date.today().isoformat()
        for brief in briefs:
            entry = self.data.setdefault("questions", {}).setdefault(
                brief["question"], {"evidence_days": [], "last_count": 0, "gap": ""}
            )
            count = len(brief.get("evidence", []))
            if count and (not entry["evidence_days"] or entry["evidence_days"][-1] != today):
                entry["evidence_days"].append(today)
            entry["last_count"] = count
            entry["gap"] = brief.get("gap", "")
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
