from .base import BaseReranker, register_reranker
import hashlib
import logging
import pickle
import time
import warnings
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Model load + corpus re-encode dominated the run time (~10 min for two rerank calls),
# so both are cached: the encoder in-process, embeddings on disk across runs.
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
        logging.getLogger(__name__).debug(f"Ignoring unreadable embedding cache: {exc}")


def _save_cache() -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Keep the newest entries only; the file is rewritten in full each time.
        items = list(_EMBED_CACHE.items())[-_CACHE_MAX:]
        with _CACHE_PATH.open("wb") as f:
            pickle.dump(dict(items), f)
    except Exception as exc:
        logging.getLogger(__name__).debug(f"Could not persist embedding cache: {exc}")


@register_reranker("local")
class LocalReranker(BaseReranker):
    def _encoder(self):
        model_name = self.config.reranker.local.model
        if model_name not in _MODEL_CACHE:
            from sentence_transformers import SentenceTransformer

            encoder = SentenceTransformer(model_name, trust_remote_code=True)
            # jina-v5 pads to a very long context by default, which made CPU encoding
            # ~100x slower than needed for abstracts. 512 tokens covers every abstract.
            max_seq = int(self.config.reranker.local.get("max_seq_length", 512) or 512)
            try:
                encoder.max_seq_length = max_seq
            except Exception:
                pass
            _MODEL_CACHE[model_name] = encoder
        return _MODEL_CACHE[model_name]

    def _encode(self, encoder, texts: list[str], encode_kwargs: dict) -> np.ndarray:
        model_name = self.config.reranker.local.model
        # jina-v5 pads to its full context window, and an 8k-token batch needs a ~9 GiB
        # attention buffer, which made a CI run encode 96 texts in 453s. 2000 chars is
        # still well past every abstract, and keeps the work bounded.
        max_chars = int(self.config.reranker.local.get("max_chars", 2000) or 2000)
        texts = [(t or "")[:max_chars] for t in texts]
        key = _cache_key(model_name, texts)
        cached = _EMBED_CACHE.get(key)
        if cached is not None:
            logger.debug(f"Embedding cache hit for {len(texts)} texts")
            return cached
        started = time.time()
        features = encoder.encode(
            texts,
            **encode_kwargs,
            batch_size=int(self.config.reranker.local.get("batch_size", 32) or 32),
            show_progress_bar=False,
        )
        features = np.asarray(features)
        _EMBED_CACHE[key] = features
        _save_cache()
        logger.info(f"Encoded {len(texts)} texts in {time.time() - started:.1f}s (cache miss)")
        return features

    def get_similarity_score(self, s1: list[str], s2: list[str]) -> np.ndarray:
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
        if self.config.reranker.local.encode_kwargs:
            encode_kwargs = dict(self.config.reranker.local.encode_kwargs)
        else:
            encode_kwargs = {}
        s1_feature = self._encode(encoder, s1, encode_kwargs)
        s2_feature = self._encode(encoder, s2, encode_kwargs)
        sim = encoder.similarity(s1_feature, s2_feature)
        return sim.numpy() if hasattr(sim, "numpy") else np.asarray(sim)
