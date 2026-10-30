"""Core review, digest, annotation, baseline, research synthesis, and LLM utilities."""

from .annotator import build_annotated_text_elements, fetch_ar5iv_targeted_sections, locate_spans, resolve_inline_ai_followups
from .baseline import enrich_papers_with_baselines, extract_baselines, match_baselines_with_corpus
from .digest import (
    compute_composite_paper_score,
    compute_review_confidence,
    fetch_arxiv_targeted_sections,
    format_digest_feishu_elements,
    format_digest_html,
    format_rubric_summary_line,
    normalize_rubric_scores,
    rerank_by_composite_score,
    run_critical_paper_digest,
)
from .interest import build_corpus_from_topics, get_interest_corpus, taste_corpus
from .llm import LLMRouter
from .paper_store import PaperStore
from .poster import build_framework_prompt, extract_source_method_figure, generate_diagram_with_gpt_image, generate_paper_poster
from .research import (
    ResearchState,
    judge_ranking,
    pick_seeds,
    plan_queries,
    question_weights,
    suggest_next_questions,
    synthesize_question_briefs,
    synthesize_questions,
)
from .textutil import UNTRUSTED_NOTICE, contains_quote, extract_json
from .translator import AcademicTranslator

__all__ = [
    "AcademicTranslator",
    "LLMRouter",
    "PaperStore",
    "ResearchState",
    "UNTRUSTED_NOTICE",
    "build_annotated_text_elements",
    "build_corpus_from_topics",
    "compute_composite_paper_score",
    "compute_review_confidence",
    "contains_quote",
    "enrich_papers_with_baselines",
    "extract_baselines",
    "extract_json",
    "fetch_ar5iv_targeted_sections",
    "fetch_arxiv_targeted_sections",
    "format_digest_feishu_elements",
    "format_digest_html",
    "format_rubric_summary_line",
    "generate_paper_poster",
    "get_interest_corpus",
    "judge_ranking",
    "locate_spans",
    "match_baselines_with_corpus",
    "normalize_rubric_scores",
    "pick_seeds",
    "plan_queries",
    "question_weights",
    "rerank_by_composite_score",
    "resolve_inline_ai_followups",
    "run_critical_paper_digest",
    "suggest_next_questions",
    "synthesize_question_briefs",
    "synthesize_questions",
    "taste_corpus",
]
