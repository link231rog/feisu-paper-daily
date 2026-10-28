"""Deep-research query planning, multi-hop seed selection, judge ranking, and evidence synthesis."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Any, Optional

from loguru import logger

from ..protocol import Paper
from .textutil import UNTRUSTED_NOTICE, extract_json


class ResearchState:
    """Persists cumulative evidence for tracked research questions across daily runs."""

    def __init__(self, path: str = "data/research_state.json", **_: Any):
        self.path = path
        self.questions: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.questions = data.get("questions", data)
        except Exception as exc:
            logger.warning(f"Failed to load research state from {self.path}: {exc}")

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated_at": datetime.now().isoformat(),
                        "questions": self.questions,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as exc:
            logger.warning(f"Failed to save research state to {self.path}: {exc}")

    def gap(self, question: str) -> str:
        return str((self.questions.get(question) or {}).get("gap") or "")

    def record(self, briefs: list[dict[str, Any]], saturation_days: int = 10) -> None:
        self.update(briefs, saturation_days=saturation_days)

    def update(self, briefs: list[dict[str, Any]], saturation_days: int = 10) -> None:
        today = datetime.now().strftime("%Y-%m-%d")
        for brief in briefs or []:
            q = (brief.get("question") or "").strip()
            if not q:
                continue
            entry = self.questions.setdefault(
                q,
                {
                    "evidence_days": 0,
                    "last_evidence_date": "",
                    "summary": "",
                    "gap": "",
                    "supporting": [],
                    "counter": [],
                    "saturated": False,
                },
            )
            new_ev = brief.get("evidence") or brief.get("supporting_evidence") or []
            new_counter = brief.get("counter_evidence") or []
            if new_ev or new_counter:
                if entry.get("last_evidence_date") != today:
                    entry["evidence_days"] = int(entry.get("evidence_days", 0)) + 1
                    entry["last_evidence_date"] = today

                seen_sup = {e.get("url") or e.get("title") for e in entry.get("supporting", []) if isinstance(e, dict)}
                for item in new_ev:
                    if isinstance(item, dict):
                        key = item.get("url") or item.get("title")
                        if key and key not in seen_sup:
                            entry.setdefault("supporting", []).append(item)
                            seen_sup.add(key)
                entry["supporting"] = entry.get("supporting", [])[-12:]

                seen_cnt = {e.get("url") or e.get("title") for e in entry.get("counter", []) if isinstance(e, dict)}
                for item in new_counter:
                    if isinstance(item, dict):
                        key = item.get("url") or item.get("title")
                        if key and key not in seen_cnt:
                            entry.setdefault("counter", []).append(item)
                            seen_cnt.add(key)
                entry["counter"] = entry.get("counter", [])[-8:]

            if brief.get("summary"):
                entry["summary"] = brief["summary"]
            if brief.get("gap"):
                entry["gap"] = brief["gap"]

            if entry.get("evidence_days", 0) >= saturation_days and not brief.get("gap"):
                entry["saturated"] = True

            brief["evidence_days"] = entry.get("evidence_days", 0)
            brief["supporting_count"] = len(entry.get("supporting", []))
            brief["counter_count"] = len(entry.get("counter", []))
        self.save()


def question_weights(state: Optional[ResearchState], questions: list[str]) -> dict[str, float]:
    """Computes priority weights per tracked question based on open gaps and saturation."""
    weights: dict[str, float] = {}
    for q in questions or []:
        if not state:
            weights[q] = 1.0
            continue
        entry = state.questions.get(q) or {}
        if entry.get("saturated"):
            weights[q] = 0.5
        elif entry.get("counter"):
            weights[q] = 1.25
        elif entry.get("gap"):
            weights[q] = 1.15
        else:
            weights[q] = 1.0
    return weights


def plan_queries(
    router: Any,
    tags: list[str] | str,
    questions: list[str] | str | None = None,
    recent_titles: Optional[list[str]] = None,
    state: Optional[ResearchState] = None,
    max_queries: int = 8,
) -> dict[str, list[str]]:
    """Expands user tags and open research questions into affirmative & adversarial search queries."""
    tag_list = [tags] if isinstance(tags, str) else list(tags or [])
    q_list = [questions] if isinstance(questions, str) else list(questions or [])
    fallback = [t.strip() for t in tag_list if t and str(t).strip()]

    if not getattr(router, "available", False) or (not tag_list and not q_list):
        return {
            "s2_queries": fallback[:max_queries],
            "affirmative_s2": fallback[:max_queries],
            "adversarial_s2": [],
            "arxiv_categories": [],
        }

    prior_gaps = []
    for q in q_list:
        gap = state.gap(q) if state else ""
        prior_gaps.append(f"{q} (待解决缺口: {gap})" if gap else str(q))

    recent_str = "\n".join(f"- {t}" for t in (recent_titles or [])[:8])
    prompt = (
        "Generate concise English academic search queries (2-6 words each) to retrieve papers "
        "for the user's research tags and open questions.\n"
        f"Tags: {', '.join(fallback)}\n"
        f"Questions:\n- " + "\n- ".join(prior_gaps or ["None"]) + "\n"
        + (f"Recent library papers:\n{recent_str}\n" if recent_str else "")
        + "\nReturn ONLY JSON:\n"
        '{"affirmative_s2": ["query 1", "query 2"], "adversarial_s2": ["counter/limitation query"], "arxiv_categories": ["cs.AI", "cs.CL"]}'
    )
    try:
        if hasattr(router, "chat"):
            raw = router.chat([{"role": "user", "content": prompt}], max_tokens=500)
        else:
            raw = router.complete(
                task="query_plan",
                prompt=prompt,
                system_prompt="You are a scholarly search planner. Output valid JSON only.",
                temperature=0.2,
                max_tokens=500,
                response_json=True,
            )
        parsed = extract_json(raw, {})
        if not isinstance(parsed, dict):
            parsed = {}
        aff = [str(q).strip() for q in (parsed.get("affirmative_s2") or parsed.get("queries") or []) if str(q).strip()]
        adv = [str(q).strip() for q in (parsed.get("adversarial_s2") or []) if str(q).strip()]
        cats = [str(c).strip() for c in (parsed.get("arxiv_categories") or []) if str(c).strip()]
        s2_queries = list(dict.fromkeys(aff + adv + fallback))[:max_queries]
        return {
            "s2_queries": s2_queries,
            "affirmative_s2": aff or fallback[:max_queries],
            "adversarial_s2": adv,
            "arxiv_categories": cats,
        }
    except Exception as exc:
        logger.warning(f"Query planning failed, falling back to tags: {exc}")
        return {
            "s2_queries": fallback[:max_queries],
            "affirmative_s2": fallback[:max_queries],
            "adversarial_s2": [],
            "arxiv_categories": [],
        }


def pick_seeds(
    router: Any,
    papers: list[Paper],
    max_seeds: int = 4,
    questions: Optional[list[str]] = None,
) -> list[Paper]:
    """Selects top seed papers for citation chasing."""
    if not papers or max_seeds <= 0:
        return []
    if not getattr(router, "available", False) or len(papers) <= max_seeds:
        return papers[:max_seeds]

    items = "\n".join(
        f"{i}. {p.title} — {(p.abstract or '')[:220]}"
        for i, p in enumerate(papers[:20], 1)
    )
    q_block = "\n".join(f"- {q}" for q in (questions or []))
    prompt = (
        f"Select up to {max_seeds} seed papers most likely to cite or be cited by core work on these questions:\n"
        f"{q_block or 'General research taste'}\n\n"
        f"{UNTRUSTED_NOTICE}\n"
        f"Candidates:\n{items}\n\n"
        'Return ONLY JSON: {"seeds": [1, 3]}'
    )
    try:
        raw = (
            router.chat([{"role": "user", "content": prompt}], max_tokens=200)
            if hasattr(router, "chat")
            else router.complete(task="pick_seeds", prompt=prompt, max_tokens=200, response_json=True)
        )
        parsed = extract_json(raw, {})
        indices = parsed.get("seeds") if isinstance(parsed, dict) else parsed
        if isinstance(indices, list):
            chosen = []
            for idx in indices:
                try:
                    k = int(idx) - 1
                    if 0 <= k < len(papers) and papers[k] not in chosen:
                        chosen.append(papers[k])
                except (TypeError, ValueError):
                    continue
            if chosen:
                return chosen[:max_seeds]
    except Exception as exc:
        logger.debug(f"pick_seeds fallback to head: {exc}")
    return papers[:max_seeds]


def judge_ranking(
    router: Any,
    questions: list[str],
    papers: list[Paper],
) -> list[int]:
    """Runs an LLM listwise judge over candidate papers and populates judge_reason."""
    if not papers:
        return []
    if not getattr(router, "available", False):
        return list(range(len(papers)))

    q_block = "\n".join(f"- {q}" for q in questions)
    items = "\n".join(
        f"{i}. {p.title}\n   Abstract: {(p.abstract or '')[:300]}"
        for i, p in enumerate(papers, 1)
    )
    prompt = (
        "Rank the following candidate papers by concrete empirical/methodological contribution to the tracked questions.\n"
        f"Questions:\n{q_block}\n\n"
        f"{UNTRUSTED_NOTICE}\n"
        f"Candidates:\n{items}\n\n"
        'Return ONLY JSON: {"ranking": [{"id": 1, "reason": "一句话中文入选理由"}]}'
    )
    try:
        raw = (
            router.chat([{"role": "user", "content": prompt}], max_tokens=1000)
            if hasattr(router, "chat")
            else router.complete(task="judge_ranking", prompt=prompt, max_tokens=1000, response_json=True)
        )
        parsed = extract_json(raw, {})
        entries = parsed.get("ranking") if isinstance(parsed, dict) else parsed
        order: list[int] = []
        if isinstance(entries, list):
            for entry in entries:
                if isinstance(entry, dict):
                    try:
                        idx = int(entry.get("id", 0)) - 1
                    except (TypeError, ValueError):
                        continue
                    if 0 <= idx < len(papers) and idx not in order:
                        order.append(idx)
                        reason = str(entry.get("reason") or "").strip()
                        if reason:
                            papers[idx].judge_reason = reason
                elif isinstance(entry, int):
                    idx = entry - 1
                    if 0 <= idx < len(papers) and idx not in order:
                        order.append(idx)
        if order:
            for i in range(len(papers)):
                if i not in order:
                    order.append(i)
            return order
    except Exception as exc:
        logger.warning(f"Judge ranking failed: {exc}")
    return list(range(len(papers)))


def synthesize_questions(
    router: Any,
    questions: list[str],
    papers: list[Paper],
    state: Optional[ResearchState] = None,
    max_questions: int = 8,
) -> list[dict[str, Any]]:
    """Synthesizes daily progress briefs (supporting & counter evidence) for tracked questions."""
    if not questions or not papers:
        return []

    target_qs = questions[:max_questions]
    grouped: dict[str, list[dict[str, Any]]] = {q: [] for q in target_qs}
    counter_grouped: dict[str, list[dict[str, Any]]] = {q: [] for q in target_qs}

    for p in papers:
        for m in p.qa_matches or []:
            q = (m.get("question") or "").strip()
            ans = (m.get("answer") or "").strip()
            stance = (m.get("stance") or "supports").lower()
            if q in grouped and ans:
                ev_item = {
                    "title": p.title,
                    "url": p.url or "",
                    "finding": ans,
                }
                if stance in ("against", "counter", "contradict", "challenge", "limitation") or any(
                    kw in ans for kw in ["反例", "相反", "局限", "质疑", "证伪", "并非", "退化", "失效"]
                ):
                    counter_grouped[q].append(ev_item)
                else:
                    grouped[q].append(ev_item)

    matched_q = {q: ev for q, ev in grouped.items() if ev or counter_grouped.get(q)}
    if not matched_q:
        return []

    if not getattr(router, "available", False):
        return [
            {
                "question": q,
                "summary": "；".join(f"《{e['title']}》：{e['finding']}" for e in ev[:3]),
                "gap": "",
                "evidence": ev[:4],
                "counter_evidence": counter_grouped.get(q, [])[:3],
            }
            for q, ev in matched_q.items()
        ]

    payload = [
        {
            "question": q,
            "prior_summary": (state.questions.get(q) or {}).get("summary", "") if state else "",
            "prior_gap": (state.questions.get(q) or {}).get("gap", "") if state else "",
            "today_supporting": ev[:5],
            "today_counter": counter_grouped.get(q, [])[:3],
        }
        for q, ev in matched_q.items()
    ]
    prompt = (
        "Synthesize today's academic evidence (supporting and counter/limitation findings) "
        "into concise Chinese research progress briefs.\n"
        f"Input:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return ONLY JSON:\n"
        '{"briefs": [{"question": "original question", "summary": "2-4 sentences in Chinese", "gap": "remaining open bottleneck in 1 sentence"}]}'
    )
    try:
        raw = (
            router.chat([{"role": "user", "content": prompt}], max_tokens=1200)
            if hasattr(router, "chat")
            else router.complete(task="question_synthesis", prompt=prompt, max_tokens=1200, response_json=True)
        )
        parsed = extract_json(raw, {})
        raw_briefs = parsed.get("briefs") if isinstance(parsed, dict) else parsed
        briefs: list[dict[str, Any]] = []
        for item in raw_briefs or []:
            if not isinstance(item, dict):
                continue
            q = (item.get("question") or "").strip()
            if q in matched_q:
                briefs.append(
                    {
                        "question": q,
                        "summary": (item.get("summary") or "").strip(),
                        "gap": (item.get("gap") or "").strip(),
                        "evidence": matched_q[q][:4],
                        "counter_evidence": counter_grouped.get(q, [])[:3],
                    }
                )
        if briefs:
            return briefs
    except Exception as exc:
        logger.warning(f"Question synthesis failed: {exc}")

    return [
        {
            "question": q,
            "summary": "；".join(f"《{e['title']}》：{e['finding']}" for e in ev[:3]),
            "gap": "",
            "evidence": ev[:4],
            "counter_evidence": counter_grouped.get(q, [])[:3],
        }
        for q, ev in matched_q.items()
    ]


def suggest_next_questions(
    router: Any,
    questions: list[str],
    briefs: list[dict[str, Any]],
    accepted_titles: list[str],
    state: Optional[ResearchState] = None,
) -> list[str]:
    """Proposes up to 2 concrete follow-up research questions based on unresolved gaps."""
    if not briefs or not getattr(router, "available", False):
        return []
    gaps = [f"{b.get('question')}: {b.get('gap')}" for b in briefs if b.get("gap")]
    if not gaps:
        return []
    prompt = (
        "Based on the unresolved research gaps identified today, propose up to 2 concrete, "
        "verifiable follow-up research questions in Chinese.\n"
        f"Existing questions: {', '.join(questions)}\n"
        f"Today's unresolved gaps:\n- " + "\n- ".join(gaps) + "\n"
        f"Today's accepted papers: {', '.join(accepted_titles[:6])}\n\n"
        'Return ONLY JSON: {"questions": ["问题1", "问题2"]}'
    )
    try:
        raw = (
            router.chat([{"role": "user", "content": prompt}], max_tokens=400)
            if hasattr(router, "chat")
            else router.complete(task="next_questions", prompt=prompt, max_tokens=400, response_json=True)
        )
        parsed = extract_json(raw, {})
        items = parsed.get("questions") if isinstance(parsed, dict) else parsed
        if isinstance(items, list):
            return [str(q).strip() for q in items if str(q).strip() and str(q).strip() not in questions][:2]
    except Exception as exc:
        logger.debug(f"suggest_next_questions failed: {exc}")
    return []


def synthesize_question_briefs(
    router: Any,
    questions: list[str],
    papers: list[Paper],
    state: Optional[ResearchState] = None,
    saturation_days: int = 10,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Synthesizes briefs and follow-up questions in one call."""
    briefs = synthesize_questions(router, questions, papers, state=state)
    if state:
        state.update(briefs, saturation_days=saturation_days)
    accepted = [p.title for p in papers if p.qa_matches]
    suggested = suggest_next_questions(router, questions, briefs, accepted, state=state)
    return briefs, suggested
