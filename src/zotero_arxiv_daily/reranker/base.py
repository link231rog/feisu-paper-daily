"""Base reranker with multi-peak anchor matching, Rocchio negative feedback, and MMR diversity.

Open-source references and algorithmic citations:
- TideDra/zotero-arxiv-daily (https://github.com/TideDra/zotero-arxiv-daily): Time-decayed Zotero corpus scoring baseline
- AutoLLM/ArxivDigest (https://github.com/AutoLLM/ArxivDigest) & dw-dengwei/daily-arXiv-ai-enhanced (https://github.com/dw-dengwei/daily-arXiv-ai-enhanced): Max-TopK multi-peak anchor similarity matching
- karpathy/arxiv-sanity-preserver (https://github.com/karpathy/arxiv-sanity-preserver) & Disham220/arxiv_sanity_x (https://github.com/Disham220/arxiv_sanity_x): Rocchio negative prototype feedback & Maximal Marginal Relevance (MMR) diversity selection
"""

from abc import ABC, abstractmethod
from datetime import date
from omegaconf import DictConfig
from ..protocol import Paper, CorpusPaper
import numpy as np
from typing import Any, Type


class BaseReranker(ABC):
    def __init__(self, config: DictConfig):
        self.config = config

    def _setting(self, key: str, default: Any) -> Any:
        """Reads a reranker setting even when the config section or key is absent."""
        cfg = self.config.get("reranker") if self.config is not None else None
        if cfg is None:
            return default
        value = cfg.get(key, default)
        return default if value is None else value

    def rerank(
        self,
        candidates: list[Paper],
        corpus: list[CorpusPaper],
        priority_institutions: list[str] | None = None,
        topic_anchors: list[str] | None = None,
        negative_texts: list[str] | None = None,
    ) -> list[Paper]:
        if not candidates or not corpus:
            return candidates

        corpus = sorted(corpus, key=lambda x: x.added_date, reverse=True)
        time_decay_weight = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
        time_decay_weight: np.ndarray = time_decay_weight / time_decay_weight.sum()

        cand_texts = [f"{c.title or ''}. {c.abstract or ''}".strip(". ") for c in candidates]
        corpus_texts = [f"{cp.title or ''}. {cp.abstract or ''}".strip(". ") for cp in corpus]
        sim = self.get_similarity_score(cand_texts, corpus_texts)
        assert sim.shape == (len(candidates), len(corpus))

        # 1. Max-TopK Multi-Peak Similarity (prevents multi-topic interest dilution)
        alpha = float(self._setting("max_sim_alpha", 0.45))
        top_k = max(1, min(int(self._setting("top_k_anchors", 5)), len(corpus)))
        max_sim = sim.max(axis=1)
        best_anchor_idx = sim.argmax(axis=1)
        topk_mean = np.sort(sim, axis=1)[:, -top_k:].mean(axis=1)
        decay_mean = (sim * time_decay_weight).sum(axis=1)
        blended_mean = 0.5 * topk_mean + 0.5 * decay_mean
        sim_scores = (alpha * max_sim + (1.0 - alpha) * blended_mean) * 10.0  # [n_candidate]

        # 2. Rocchio Negative Prototype Repulsion (penalizes semantic similarity to discarded papers / negative cues)
        neg_penalties = np.zeros(len(candidates), dtype=float)
        clean_neg = [t.strip() for t in (negative_texts or []) if t and t.strip()]
        rocchio_beta = float(self._setting("rocchio_beta", 0.35))
        neg_threshold = float(self._setting("rocchio_neg_threshold", 0.18))
        if clean_neg and rocchio_beta > 0:
            try:
                neg_sim = self.get_similarity_score(cand_texts, clean_neg)
                if neg_sim.shape == (len(candidates), len(clean_neg)):
                    max_neg = neg_sim.max(axis=1)
                    neg_penalties = np.where(max_neg >= neg_threshold, rocchio_beta * max_neg * 10.0, 0.0)
            except Exception:
                pass

        recency_boost = float(self._setting("recency_boost", 0.5))
        venue_boost = float(self._setting("venue_boost", 0.5))
        citation_boost_max = float(self._setting("citation_boost_max", 1.0))
        institution_boost = float(self._setting("institution_boost", 1.5))
        code_boost = float(self._setting("code_boost", 0.4))
        hf_boost_max = float(self._setting("hf_boost_max", 0.8))
        recency_years = self._setting("recency_years", None)
        if recency_years:
            recency_years = {int(y) for y in recency_years}
        else:
            current_year = date.today().year
            recency_years = {current_year, current_year - 1}
        top_venues = self._setting("top_venues", None) or (
            "emnlp", "acl", "neurips", "iclr", "icml", "kdd", "aaai", "sigir", "cvpr", "iccv"
        )

        # Priority institutions: combining config with console-defined institutions
        config_insts = self._setting("priority_institutions", ["anthropic", "openai", "google", "deepmind"])
        all_priority_insts = set(i.lower().strip() for i in (config_insts or []))
        if priority_institutions:
            all_priority_insts.update(i.lower().strip() for i in priority_institutions if i.strip())

        default_anchors = [
            "agent", "memory", "decision", "planning", "reasoning", "reinforcement learning",
            "rl", "multi-agent", "llm", "language model", "world model", "policy", "self-improv",
            "knowledge graph", "harness", "benchmark", "eval", "reward", "tool use"
        ]
        anchors = [a.lower().strip() for a in (topic_anchors or default_anchors) if a.strip()]

        for idx, c in enumerate(candidates):
            base_sim = float(sim_scores[idx])
            score = base_sim - float(neg_penalties[idx])
            c.matched_anchor_title = corpus[int(best_anchor_idx[idx])].title

            # 1. Recency Boost
            pub_year = c.published_year
            if pub_year in recency_years:
                score += recency_boost

            # 2. Top Venue Boost (e.g. EMNLP 2026, ACL, NeurIPS, ICLR, ICML)
            venue_lower = (c.venue or "").lower()
            if any(v in venue_lower for v in top_venues):
                score += venue_boost

            # 3. Classic Baseline / High Citation Boost
            if c.citation_count and c.citation_count > 0:
                citation_boost = min(citation_boost_max, float(np.log1p(c.citation_count) * 0.4))
                score += citation_boost

            # 4. Open-Source Code & Reproducibility Boost
            if getattr(c, "code_url", None):
                score += code_boost

            # 5. HuggingFace Daily Papers Cold-Start Community Velocity Boost
            hf_up = getattr(c, "hf_upvotes", None)
            if hf_up and hf_up > 0:
                score += min(hf_boost_max, float(np.log1p(hf_up) * 0.22))

            # 6. Priority Institution × Topic Anchor Gate
            c_text = " ".join((c.affiliations or []) + (c.authors or [])).lower()
            if not c_text and c.abstract:
                c_text = c.abstract[:400].lower()
            if any(inst in c_text for inst in all_priority_insts):
                c.is_priority_institution = True
                full_content = f"{c.title or ''} {c.abstract or ''}".lower()
                anchor_matched = any(a in full_content for a in anchors)
                if anchor_matched or base_sim >= 2.5:
                    score += institution_boost
                else:
                    score += round(institution_boost * 0.2, 2)

            c.score = round(score, 2)

        candidates = sorted(candidates, key=lambda x: (x.score or 0.0), reverse=True)
        return candidates

    def mmr_select(
        self,
        candidates: list[Paper],
        k: int,
        lambda_param: float | None = None,
        relevance_scores: dict[int, float] | None = None,
    ) -> list[Paper]:
        """Selects top-k papers using Maximal Marginal Relevance (MMR) to prevent sub-topic flooding."""
        if not candidates or k <= 0:
            return []
        if len(candidates) <= k:
            return list(candidates)

        lam = float(lambda_param if lambda_param is not None else self._setting("mmr_lambda", 0.75))
        if lam >= 0.999:
            return list(candidates[:k])

        pool = list(candidates[: max(k * 4, 40)])
        raw_rel = np.array(
            [
                float(relevance_scores[id(p)])
                if (relevance_scores and id(p) in relevance_scores)
                else float(p.score or 0.0)
                for p in pool
            ],
            dtype=float,
        )
        r_min, r_max = float(raw_rel.min()), float(raw_rel.max())
        if r_max > r_min:
            if r_min >= 0 and r_max > 0:
                rel_norm = raw_rel / r_max
            else:
                span = r_max - r_min
                rel_norm = 0.2 + 0.8 * ((raw_rel - r_min) / span)
        else:
            rel_norm = np.ones_like(raw_rel)

        texts = [f"{p.title or ''}. {p.abstract or ''}".strip(". ") for p in pool]
        try:
            pair_sim = self.get_similarity_score(texts, texts)
            if pair_sim.shape != (len(pool), len(pool)):
                return list(candidates[:k])
        except Exception:
            return list(candidates[:k])

        selected_indices: list[int] = [int(np.argmax(rel_norm))]
        remaining = set(range(len(pool))) - set(selected_indices)

        while len(selected_indices) < min(k, len(pool)) and remaining:
            best_idx = -1
            best_mmr = -1e9
            for idx in remaining:
                max_sim_to_selected = float(max(pair_sim[idx, s_idx] for s_idx in selected_indices))
                mmr_val = lam * float(rel_norm[idx]) - (1.0 - lam) * max_sim_to_selected
                if mmr_val > best_mmr:
                    best_mmr = mmr_val
                    best_idx = idx
            if best_idx < 0:
                break
            selected_indices.append(best_idx)
            remaining.remove(best_idx)

        selected_papers = [pool[i] for i in selected_indices]
        picked_ids = {id(p) for p in selected_papers}
        for p in candidates:
            if len(selected_papers) >= len(candidates):
                break
            if id(p) not in picked_ids:
                selected_papers.append(p)
        return selected_papers[:k]

    @abstractmethod
    def get_similarity_score(self, s1:list[str], s2:list[str]) -> np.ndarray:
        raise NotImplementedError

registered_rerankers = {}

def register_reranker(name:str):
    def decorator(cls):
        registered_rerankers[name] = cls
        return cls
    return decorator

def get_reranker_cls(name:str) -> Type[BaseReranker]:
    if name not in registered_rerankers:
        raise ValueError(f"Reranker {name} not found")
    return registered_rerankers[name]
