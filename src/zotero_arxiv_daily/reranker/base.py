from abc import ABC, abstractmethod
from omegaconf import DictConfig
from ..protocol import Paper, CorpusPaper
import numpy as np
from typing import Type
class BaseReranker(ABC):
    def __init__(self, config:DictConfig):
        self.config = config

    def rerank(self, candidates: list[Paper], corpus: list[CorpusPaper]) -> list[Paper]:
        if not candidates or not corpus:
            return candidates

        corpus = sorted(corpus, key=lambda x: x.added_date, reverse=True)
        time_decay_weight = 1 / (1 + np.log10(np.arange(len(corpus)) + 1))
        time_decay_weight: np.ndarray = time_decay_weight / time_decay_weight.sum()
        sim = self.get_similarity_score([c.abstract for c in candidates], [c.abstract for c in corpus])
        assert sim.shape == (len(candidates), len(corpus))
        sim_scores = (sim * time_decay_weight).sum(axis=1) * 10  # [n_candidate]

        top_venues = ("emnlp", "acl", "neurips", "iclr", "icml", "kdd", "aaai", "sigir", "cvpr", "iccv")

        for idx, c in enumerate(candidates):
            score = float(sim_scores[idx])

            # 1. Recency Boost (2025-2026 preference)
            pub_year = c.published_year
            if pub_year in (2025, 2026):
                score += 1.5

            # 2. Top Venue Boost (e.g. EMNLP 2026, ACL, NeurIPS, ICLR, ICML)
            venue_lower = (c.venue or "").lower()
            if any(v in venue_lower for v in top_venues):
                score += 1.5

            # 3. Classic Baseline / High Citation Boost
            # Enables foundational works with strong citation impact to rank strongly
            if c.citation_count and c.citation_count > 0:
                citation_boost = min(2.5, float(np.log1p(c.citation_count) * 0.4))
                score += citation_boost

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