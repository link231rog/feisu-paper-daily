from .base import BaseReranker, register_reranker
import hashlib
import logging
import pickle
import time
import warnings
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Model load + corpus re-encode dominated the run time: a 2000-char capped encode of
# 89 texts still took 374s on a 4-vCPU CI runner (Apple matrix units make it ~40x faster
# locally), so the default similarity is TF-IDF and embeddings are opt-in.
_MODEL_CACHE: dict[str, object] = {}
_EMBED_CACHE: dict[str, np.ndarray] = {}
_CACHE_PATH = Path("data/embed_cache.pkl")
_CACHE_MAX = 64


def _cache_key(model: str, texts: list[str]) -> str:
    h = hashlib.sha1(model.encode("utf-8"))
    for t in texts:
        h.update(b"\x00")
        h.update((t or "").encode("utf-8", "replace"))
    return h.hexdigest()


def _load_cache() -> None:
    if _EMBED_CACHE or not _CACHE_PATH.exists():
        return
    try:
        with _CACHE_PATH.open("rb") as f:
            data = pickle.load(f)
        if isinstance(data, dict):
            _EMBED_CACHE.update({k: v for k, v in data.items() if isinstance(v, np.ndarray)})
    except Exception as exc:
        logger.debug(f"Ignoring unreadable embedding cache: {exc}")


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        items = list(_EMBED_CACHE.items())[-_CACHE_MAX:]
        with _CACHE_PATH.open("wb") as f:
            pickle.dump(dict(items), f)
    except Exception as exc:
        logger.debug(f"Could not persist embedding cache: {exc}")


@register_reranker("local")
class LocalReranker(BaseReranker):
    def _method(self) -> str:
        return str(self.config.reranker.local.get("method", "tfidf") or "tfidf").lower()

    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
        if not s1 or not s2:
            return np.zeros((len(s1), len(s2)))
        if self._method() == "embedding":
            return self._embedding_similarity(s1, s2)
        return self._tfidf_similarity(s1, s2)

    @staticmethod
    def _tfidf_similarity(s1: list[str], s2: list[str]) -> np.ndarray:
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [(t or "").strip() for t in list(s1) + list(s2)]
        if not any(texts):
            return np.zeros((len(s1), len(s2)))
        try:
            vectorizer = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)
            matrix = vectorizer.fit_transform(texts)
        except ValueError:  # empty vocabulary
            return np.zeros((len(s1), len(s2)))
        return (matrix[: len(s1)] @ matrix[len(s1) :].T).toarray()

    def _encoder(self):
        model_name = self.config.reranker.local.model
        if model_name not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer

            encoder = SentenceTransformer(model_name, trust_remote_code=True)
            try:
                encoder.max_seq_length = int(self.config.reranker.local.get("max_seq_length", 512) or 512)
            except Exception:
                pass
            _MODEL_CACHE[model_name] = encoder
        return _MODEL_CACHE[model_name]

    def _encode(self, encoder, texts: list[str], encode_kwargs: dict) -> np.ndarray:
        model_name = self.config.reranker.local.model
        max_chars = int(self.config.reranker.local.get("max_chars", 2000) or 2000)
        texts = [(t or "")[:max_chars] for t in texts]
        key = _cache_key(model_name, texts)
        cached = _EMBED_CACHE.get(key)
        if cached is not None:
            logger.debug(f"Embedding cache hit for {len(texts)} texts")
            return cached
        started = time.time()
        features = np.asarray(
            encoder.encode(
                texts,
                **encode_kwargs,
                batch_size=int(self.config.reranker.local.get("batch_size", 32) or 32),
                show_progress_bar=False,
            )
        )
        _EMBED_CACHE[key] = features
        _save_cache()
        logger.info(f"Encoded {len(texts)} texts in {time.time() - started:.1f}s (cache miss)")
        return features

    def _embedding_similarity(self, s1: list[str], s2: list[str]) -> np.ndarray:
        if not self.config.executor.debug:
            from transformers.utils import logging as transformers_logging
            from huggingface_hub.utils import logging as hf_logging

            transformers_logging.set_verbosity_error()
            hf_logging.set_verbosity_error()
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            logging.getLogger("sentence_transformers.SentenceTransformer").setLevel(logging.ERROR)
            logging.getLogger("transformers").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
            logging.getLogger("huggingface_hub.utils._http").setLevel(logging.ERROR)
            warnings.filterwarnings("ignore", category=FutureWarning)

        _load_cache()
        encoder = self._encoder()
        encode_kwargs = dict(self.config.reranker.local.encode_kwargs or {})
        s1_feature = self._encode(encoder, s1, encode_kwargs)
        s2_feature = self._encode(encoder, s2, encode_kwargs)
        sim = encoder.similarity(s1_feature, s2_feature)
        return sim.numpy() if hasattr(sim, "numpy") else np.asarray(sim)
