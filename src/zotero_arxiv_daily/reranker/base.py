from abc import ABC, abstractmethod
from datetime import date
from omegaconf import DictConfig
from ..protocol import Paper, CorpusPaper
import numpy as np
from typing import Any, Type
class BaseReranker(ABC):
    def __init__(self, config:DictConfig):
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
    ) -> list[Paper]:
        if not candidates or not corpus:
            return candidates

        corpus = sorted(corpus, key=lambda x: x.added_date, reverse=True)
        time_decay_weight = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
        time_decay_weight: np.ndarray = time_decay_weight / time_decay_weight.sum()
        sim = self.get_similarity_score([c.abstract for c in candidates], [c.abstract for c in corpus])
        assert sim.shape == (len(candidates), len(corpus))
        sim_scores = (sim * time_decay_weight).sum(axis=1) * 10  # [n_candidate]

        recency_boost = float(self._setting("recency_boost", 0.5))
        venue_boost = float(self._setting("venue_boost", 0.5))
        citation_boost_max = float(self._setting("citation_boost_max", 1.0))
        institution_boost = float(self._setting("institution_boost", 1.5))
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

        for idx, c in enumerate(candidates):
            score = float(sim_scores[idx])

            # 1. Recency Boost
            pub_year = c.published_year
            if pub_year in recency_years:
                score += recency_boost

            # 2. Top Venue Boost (e.g. EMNLP 2026, ACL, NeurIPS, ICLR, ICML)
            venue_lower = (c.venue or "").lower()
            if any(v in venue_lower for v in top_venues):
                score += venue_boost

            # 3. Classic Baseline / High Citation Boost
            # Enables foundational works with strong citation impact to rank strongly
            if c.citation_count and c.citation_count > 0:
                citation_boost = min(citation_boost_max, float(np.log1p(c.citation_count) * 0.4))
                score += citation_boost

            # 4. Priority Institution Boost (e.g. Anthropic, OpenAI, Google)
            c_text = " ".join((c.affiliations or []) + (c.authors or [])).lower()
            if not c_text and c.abstract:
                c_text = c.abstract[:400].lower()
            if any(inst in c_text for inst in all_priority_insts):
                score += institution_boost
                c.is_priority_institution = True

            c.score = round(score, 2)

        candidates = sorted(candidates, key=lambda x: (x.score or 0.0), reverse=True)
        return candidates

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
