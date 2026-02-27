from .base import BaseReranker, register_reranker
import numpy as np
@register_reranker("local")
class LocalReranker(BaseReranker):
    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        from sentence_transformers import SentenceTransformer
        encoder = SentenceTransformer(self.config.reranker.local.model, trust_remote_code=True)
        if self.config.reranker.local.encode_kwargs:
            encode_kwargs = self.config.reranker.local.encode_kwargs
        else:
            encode_kwargs = {}
        s1_feature = encoder.encode(s1,**encode_kwargs)
        s2_feature = encoder.encode(s2,**encode_kwargs)
        sim = encoder.similarity(s1_feature, s2_feature)
        return sim.numpy()