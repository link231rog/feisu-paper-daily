"""Deep-research loop: query planning, seed chasing, per-question synthesis, next-round questions."""

from enum import Enum
import json
import random
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

from .llm import LLMRouter
from .protocol import Paper
from .textutil import UNTRUSTED_NOTICE, extract_json, text_similarity


class HypothesisStatus(str, Enum):
    """Lifecycle status of a research question/hypothesis."""
    EXPLORING = "exploring"     # 🌱 探索期：双向搜集初步机制与基线
    CONTESTED = "contested"     # ⚖️ 争议期：同时存在支持与反例证据，优先追踪
    CONVERGED = "converged"     # ✅ 已收敛：证据链充分，降低频率并派生子问题
    FALSIFIED = "falsified"     # ❌ 已证伪：核心假设被反例推翻，归档


_json_block = extract_json


def _paper_digest(papers: list[Paper], limit: int = 30) -> str:
    lines = []
    for idx, paper in enumerate(papers[:limit], 1):
        abstract = (paper.abstract or "").replace("\n", " ")[:300]
        lines.append(f"{idx}. {paper.title} ({paper.url})\n   {abstract}")
    return "\n".join(lines)


def _question_directive(state: "ResearchState | None", question: str) -> str:
    """One planning line per question, steering queries by its state and open gap."""
    if state is None:
        return f"- {question}"
    ctx = state.question_context(question)
    status = ctx["status"]
    if status == HypothesisStatus.CONTESTED.value:
        hint = "contested: prioritize counter-evidence and failure-mode queries"
    elif status == HypothesisStatus.CONVERGED.value:
        hint = "converged: only look for challenges to the consensus"
    elif status == HypothesisStatus.FALSIFIED.value:
        hint = "falsified: only look for evidence that reopens it"
    else:
        hint = "exploring: look for mechanisms, baselines and benchmarks"
    gap = f"; open gap: {ctx['gap']}" if ctx["gap"] else ""
    return f"- {question} [{hint}; {ctx['support']} supporting / {ctx['counter']} counter so far{gap}]"


def plan_queries(
    router: LLMRouter,
    tags: list[str],
    questions: list[str],
    known_titles: list[str] | None = None,
    state: "ResearchState | None" = None,
) -> dict[str, list[str]]:
    """Turns tracked tags and questions into affirmative and adversarial search queries."""
    if not router.available or not (tags or questions):
        return {"s2_queries": [], "arxiv_categories": []}

    directives = "\n".join(_question_directive(state, q) for q in questions)
    prompt = (
        "You plan literature search for an active scientific research assistant.\n"
        f"Tags: {', '.join(tags) or 'none'}\n"
        f"Questions (with their current research state):\n{directives or '- none'}\n"
        f"Already seen examples: {'; '.join((known_titles or [])[:10]) or 'none'}\n\n"
        "Generate a dual search plan. Each query must be a concrete 4-10 word search phrase, "
        "not a restated question, and every question should be served by at least one query "
        "that follows its state hint (target the open gap when one is given):\n"
        "1. affirmative_s2: 3-5 queries targeting mechanisms, architectures, and positive benchmark results.\n"
        "2. adversarial_s2: 2-4 counter-queries targeting failure modes, ablation degradation, scaling limits, or negative results that challenge assumptions.\n"
        "3. arxiv_categories: 2-4 arXiv categories (e.g. cs.AI, cs.CL, cs.LG).\n\n"
        "Return ONLY JSON:\n"
        '{"affirmative_s2": [...], "adversarial_s2": [...], "arxiv_categories": [...]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1400), {})
    if not isinstance(data, dict):
        data = {}
    pos = [str(q) for q in data.get("affirmative_s2", []) if str(q).strip()][:5]
    neg = [str(q) for q in data.get("adversarial_s2", []) if str(q).strip()][:4]
    # Fallback if model returns legacy s2_queries key
    if not pos and not neg and data.get("s2_queries"):
        pos = [str(q) for q in data.get("s2_queries", []) if str(q).strip()][:6]

    combined = pos + neg
    return {
        "s2_queries": combined[:9],
        "affirmative_s2": pos,
        "adversarial_s2": neg,
        "arxiv_categories": [str(c) for c in data.get("arxiv_categories", []) if str(c).strip()][:4],
    }


def pick_seeds(
    router: LLMRouter,
    papers: list[Paper],
    limit: int = 4,
    questions: list[str] | None = None,
) -> list[str]:
    """Chooses papers worth chasing through citations and references for the tracked questions."""
    if not router.available or not papers:
        return []
    q_text = "\n".join(f"- {q}" for q in questions or []) or "none"
    prompt = (
        "Pick the papers most worth following through their citations and references "
        "to answer these ongoing research questions. Prefer papers that introduce or evaluate "
        "a mechanism the questions depend on over merely popular ones.\n"
        f"Questions:\n{q_text}\n\n"
        f"{UNTRUSTED_NOTICE}\n<untrusted_source>\n{_paper_digest(papers, 20)}\n</untrusted_source>\n\n"
        f"Return ONLY a JSON array of up to {limit} numbers from the list above."
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=800), [])
    seeds = []
    for item in data if isinstance(data, list) else []:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= min(len(papers), 20) and papers[idx - 1].url not in seeds:
            seeds.append(papers[idx - 1].url)
    return seeds[:limit]


def _evidence_digest(papers: list[Paper], question: str, limit: int = 25) -> str:
    """Candidate listing for one question, including answers and annotations already produced."""
    lines = []
    for idx, paper in enumerate(papers[:limit], 1):
        abstract = (paper.abstract or "").replace("\n", " ")[:600]
        lines.append(f"{idx}. {paper.title} ({paper.url})\n   Abstract: {abstract}")
        score = (paper.qa_scores or {}).get(question)
        if score is not None:
            lines.append(f"   Earlier relevance score for this question: {score}/10")
        for match in paper.qa_matches or []:
            if match.get("question") == question:
                quote = f' (quote: "{match["evidence_quote"]}")' if match.get("evidence_quote") else ""
                stance = f" [{match['stance']}]" if match.get("stance") in {"supports", "against"} else ""
                lines.append(f"   Answer found{stance}: {match.get('answer', '')}{quote}")
        for ann in paper.inline_annotations or []:
            if ann.get("type") == "counter" or (ann.get("type") == "claim" and ann.get("question") == question):
                lines.append(
                    f"   Source-anchored {ann['type']}: \"{ann.get('quote', '')}\" -> {ann.get('comment', '')}"
                )
    return "\n".join(lines)


def synthesize_questions(
    router: LLMRouter,
    questions: list[str],
    papers: list[Paper],
    state: "ResearchState | None" = None,
    max_questions: int = 8,
) -> list[dict]:
    """Writes one evidence brief per tracked question, identifying both supporting and counter evidence."""
    if not router.available or not questions or not papers:
        return []

    if len(questions) > max_questions:
        logger.warning(
            f"{len(questions)} tracked questions but only the first {max_questions} get a brief "
            "(raise research.max_brief_questions to cover more)"
        )

    briefs: list[dict] = []
    for question in questions[:max_questions]:
        previous = ""
        if state is not None:
            ctx = state.question_context(question)
            if ctx["summary"]:
                previous = (
                    f"Previous conclusion ({ctx['status']}, {ctx['support']} supporting / {ctx['counter']} counter so far): "
                    f"{ctx['summary']}\nPreviously open gap: {ctx['gap'] or 'none'}\n\n"
                )
        prompt = (
            f"Research question: {question}\n\n{previous}"
            f"{UNTRUSTED_NOTICE}\nToday's candidate papers:\n<untrusted_source>\n"
            f"{_evidence_digest(papers, question)}\n</untrusted_source>\n\n"
            "Write a concise Chinese brief (120-220 字) analyzing today's evidence for this question"
            + (", stating explicitly what changed relative to the previous conclusion" if previous else "")
            + ":\n"
            "1. summary: Core progress and whether evidence is affirmative, disputed, or negative.\n"
            "2. evidence: Candidate indices whose abstracts or listed quotes explicitly support an answer.\n"
            "3. counter_evidence: Candidate indices that explicitly report a result against the hypothesis; an ordinary limitation does not qualify.\n"
            "4. gap: What remains unanswered or debated, phrased as a searchable sub-problem.\n"
            "5. status: Daily assessment only: 'exploring' (preliminary), 'contested' (direct support and direct counter-evidence), 'converged' (rare: several independent explicit answers and no material gap), 'falsified' (direct refutation, not merely missing evidence).\n"
            "Use only the candidate text above. Do not invent citations, evidence, agreement between papers, or results. Empty evidence arrays are valid.\n\n"
            'Return ONLY JSON: {"summary": "...", "evidence": [{"index": 1}], "counter_evidence": [{"index": 2}], "gap": "...", "status": "..."}'
        )
        data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1600), {})
        if not isinstance(data, dict):
            continue
        summary = str(data.get("summary", "")).strip()
        if not summary:
            continue

        def cited_papers(items: Any) -> list[dict]:
            cited = []
            seen = set()
            for item in items if isinstance(items, list) else []:
                try:
                    index = int(item.get("index", 0)) if isinstance(item, dict) else int(item)
                except (TypeError, ValueError):
                    continue
                if not 1 <= index <= min(len(papers), 25) or index in seen:
                    continue
                seen.add(index)
                paper = papers[index - 1]
                cited.append({"title": paper.title, "url": paper.url})
            return cited

        evidence = cited_papers(data.get("evidence"))
        counter = cited_papers(data.get("counter_evidence"))
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
    state: "ResearchState | None" = None,
    similarity_threshold: float = 0.6,
) -> list[str]:
    """Proposes refined sub-questions for the next round; a human approves them."""
    if not router.available or not questions:
        return []

    lines = []
    for b in briefs:
        status = state.get_status(b["question"]).value if state is not None else b.get("status", "exploring")
        lines.append(
            f"- {b['question']} [{status}]: {b['summary']} | open gap: {b.get('gap') or 'none'}"
        )
    brief_text = "\n".join(lines) or "no briefs today"
    prompt = (
        "You refine a research agenda by turning today's open gaps into sharper questions.\n"
        "Current questions (never repeat or paraphrase these):\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"
        f"Today's briefs (status in brackets):\n{brief_text}\n\n"
        f"Papers the reader accepted today: {', '.join((accepted_titles or [])[:10]) or 'none'}\n\n"
        "Propose 2-4 follow-up questions. Rules:\n"
        "- Prefer turning a stated open gap or a contested/exploring question into a narrower, testable sub-question.\n"
        "- For converged or falsified questions, propose at most one question that probes a boundary condition or a "
        "setting where the conclusion might break; never ask for more of the same evidence.\n"
        "- Each must be answerable by a literature search and name a concrete method, setting, metric or failure mode.\n"
        "- Write each in the same language as the current questions, as one sentence.\n"
        'Return ONLY JSON: {"questions": ["..."]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=1000), {})
    proposed: list[str] = []
    for item in data.get("questions", []) if isinstance(data, dict) and isinstance(data.get("questions"), list) else []:
        text = str(item).strip()
        if not text:
            continue
        # Drop paraphrases of existing questions and of earlier proposals
        if any(text_similarity(text, other) >= similarity_threshold for other in [*questions, *proposed]):
            continue
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
    """Comparatively ranks candidates in one call; returns 0-based indices best first.

    Candidates are shown in a shuffled order so the judge cannot simply echo the fused order,
    and each carries the evidence already extracted for it. Papers the judge omits keep their
    original relative order after the ranked ones; explicitly dropped papers are removed.
    """
    if not router.available or len(papers) < 2:
        return list(range(len(papers)))

    # Shuffled presentation; shown[k] is the index into `papers` of the paper displayed as k+1
    shown = list(range(len(papers)))
    random.Random(len(papers) * 7919 + len(questions)).shuffle(shown)

    def entry(position: int, paper: Paper) -> str:
        lines = [f"{position}. {paper.title}", f"   {(paper.abstract or '').replace(chr(10), ' ')[:700]}"]
        if paper.qa_scores:
            best = max(paper.qa_scores.items(), key=lambda kv: kv[1])
            lines.append(f"   Earlier per-paper scoring: best question fit {best[1]}/10")
        for match in (paper.qa_matches or [])[:2]:
            tag = " (reports a result against the hypothesis)" if match.get("stance") == "against" else ""
            lines.append(f"   Extracted answer{tag}: {match.get('answer', '')}")
        return "\n".join(lines)

    listing = "\n".join(entry(pos, papers[i]) for pos, i in enumerate(shown, 1))
    prompt = (
        "You are ranking today's candidate papers for a researcher. Judge how much each "
        "paper would actually advance their tracked questions, not how popular it is. "
        "The list order carries no information.\n\n"
        "Tracked questions:\n" + "\n".join(f"- {q}" for q in questions) + "\n\n"
        f"{UNTRUSTED_NOTICE}\nCandidates:\n<untrusted_source>\n{listing}\n</untrusted_source>\n\n"
        "Use only the supplied evidence, not reputation or prior knowledge. Rank by direct, question-specific evidence: "
        "explicit mechanism/result/benchmark > partial evidence > topic overlap. Do not infer missing experiments.\n"
        "Keep genuinely useful papers. Return dropped only for a paper with no question-specific evidence or an exact duplicate of a stronger candidate; "
        "do not drop merely because it is a baseline, negative result or opposing view. "
        "Papers that report a result against a tracked hypothesis are especially valuable.\n"
        "Give a concise Chinese reason tied to the abstract; do not invent novelty or results.\n"
        'Return ONLY JSON: {"ranking": [{"index": 3, "reason": "一句话中文理由"}], "dropped": [7]}'
    )
    data = _json_block(router.chat([{"role": "user", "content": prompt}], max_tokens=2500), {})
    if not isinstance(data, dict):
        return list(range(len(papers)))

    def real_index(displayed: Any) -> int | None:
        try:
            pos = int(displayed)
        except (TypeError, ValueError):
            return None
        return shown[pos - 1] if 1 <= pos <= len(papers) else None

    dropped = set()
    for item in data.get("dropped", []) if isinstance(data.get("dropped"), list) else []:
        mapped = real_index(item)
        if mapped is not None:
            dropped.add(mapped)

    order: list[int] = []
    for item in data.get("ranking", []) if isinstance(data.get("ranking"), list) else []:
        mapped = real_index(item.get("index")) if isinstance(item, dict) else None
        if mapped is not None and mapped not in order and mapped not in dropped:
            order.append(mapped)
            papers[mapped].judge_reason = str(item.get("reason", "")).strip() or None
    order.extend(i for i in range(len(papers)) if i not in order and i not in dropped)
    return order


def _absorb(bucket: dict[str, dict], items: Any, today: str) -> None:
    """Adds newly cited papers to a cumulative evidence bucket; keys dedupe by URL or title."""
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "")).strip()
        url = str(item.get("url", "")).strip()
        key = url or title
        if key and key not in bucket:
            bucket[key] = {"title": title, "url": url, "first_seen": today}


class ResearchState:
    """Tracks per-question evidence and hypothesis state machine across daily runs."""

    def __init__(
        self,
        path: str = "data/research_state.json",
        converge_min_support: int = 6,
        falsify_min_counter: int = 3,
    ):
        self.path = Path(path)
        self.converge_min_support = max(1, int(converge_min_support))
        self.falsify_min_counter = max(1, int(falsify_min_counter))
        self.data: dict[str, Any] = {"questions": {}}
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                logger.warning(f"Could not read research state at {self.path}; starting fresh")
        today = date.today().isoformat()
        for entry in self.data.get("questions", {}).values():
            if isinstance(entry, dict):
                self._migrate(entry, today)

    @staticmethod
    def _migrate(entry: dict, today: str) -> None:
        """Upgrades per-day title lists to the cumulative evidence dicts without losing entries."""
        if "supporting" in entry and "counter" in entry:
            return
        first_seen = (entry.get("evidence_days") or [today])[-1]

        def convert(titles: Any, bucket: dict[str, dict]) -> None:
            for title in titles if isinstance(titles, list) else []:
                title = str(title)
                bucket.setdefault(title, {"title": title, "url": "", "first_seen": first_seen})

        supporting = entry.setdefault("supporting", {})
        counter = entry.setdefault("counter", {})
        convert(entry.pop("supporting_titles", []), supporting)
        convert(entry.pop("counter_titles", []), counter)
        entry["supporting_count"] = len(supporting)
        entry["counter_count"] = len(counter)

    def get_status(self, question: str) -> HypothesisStatus:
        raw = (self.data.get("questions", {}).get(question, {}).get("status") or "").lower()
        for s in HypothesisStatus:
            if s.value == raw:
                return s
        return HypothesisStatus.EXPLORING

    def record(self, briefs: list[dict], today: str | None = None) -> None:
        today = today or date.today().isoformat()
        for brief in briefs:
            entry = self.data.setdefault("questions", {}).setdefault(
                brief["question"], {
                    "evidence_days": [],
                    "last_count": 0,
                    "gap": "",
                    "status": HypothesisStatus.EXPLORING.value,
                    "supporting_count": 0,
                    "counter_count": 0,
                    "supporting": {},
                    "counter": {},
                }
            )
            self._migrate(entry, today)
            evidence = brief.get("evidence", [])
            counter = brief.get("counter_evidence", [])
            # Accumulate across days by URL/title; rerunning a report stays idempotent.
            _absorb(entry["supporting"], evidence, today)
            _absorb(entry["counter"], counter, today)
            if evidence and (not entry["evidence_days"] or entry["evidence_days"][-1] != today):
                entry["evidence_days"].append(today)
            entry["last_count"] = len(evidence)
            entry["supporting_count"] = len(entry["supporting"])
            entry["counter_count"] = len(entry["counter"])
            entry["gap"] = str(brief.get("gap", "") or "").strip()
            entry["summary"] = str(brief.get("summary", "") or "").strip()
            entry["llm_status"] = str(brief.get("status", "") or "").strip().lower()

            support = entry["supporting_count"]
            counter_count = entry["counter_count"]
            support_dates = {str(v.get("first_seen")) for v in entry["supporting"].values()}
            counter_dates = {str(v.get("first_seen")) for v in entry["counter"].values()}

            # Rule-driven state; the model's per-run status is only a suggestion.
            # Strongest conclusions are checked first, otherwise one counter-example
            # would pin every question to "contested" and the other states could not be reached.
            if (
                counter_count >= self.falsify_min_counter
                and len(counter_dates) >= 2
                and counter_count > support
            ):
                entry["status"] = HypothesisStatus.FALSIFIED.value
            elif (
                support >= self.converge_min_support
                and counter_count * 2 < support
                and not entry["gap"]
                and len(support_dates) >= 2
            ):
                entry["status"] = HypothesisStatus.CONVERGED.value
            elif support and counter_count:
                entry["status"] = HypothesisStatus.CONTESTED.value
            else:
                entry["status"] = entry.get("status", HypothesisStatus.EXPLORING.value)

            entry["updated"] = datetime.now().isoformat(timespec="seconds")
        self.save()

    def question_context(self, question: str) -> dict[str, Any]:
        """Compact view of a question's tracked state, for prompts."""
        entry = self.data.get("questions", {}).get(question) or {}
        return {
            "status": self.get_status(question).value,
            "support": int(entry.get("supporting_count", 0) or 0),
            "counter": int(entry.get("counter_count", 0) or 0),
            "gap": str(entry.get("gap", "") or ""),
            "summary": str(entry.get("summary", "") or ""),
        }

    def saturated(self, question: str, days: int = 7) -> bool:
        entry = self.data.get("questions", {}).get(question)
        if not entry or not entry.get("evidence_days"):
            return False
        last = date.fromisoformat(entry["evidence_days"][-1])
        return (date.today() - last) >= timedelta(days=days)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
