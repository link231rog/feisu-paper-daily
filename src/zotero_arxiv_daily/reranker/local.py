from .base import BaseReranker, register_reranker
import numpy as np
@register_reranker("local")
class LocalReranker(BaseReranker):
    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(self.config.reranker.local.model)
        s1_feature = encoder.encode(s1)
        s2_feature = encoder.encode(s2)
        sim = encoder.similarity(s1_feature, s2_feature)
        return sim.numpy()