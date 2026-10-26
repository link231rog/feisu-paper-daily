"""Shared LLM access with key rotation across the free API pool."""

import random
import threading
import time
from typing import Any

from loguru import logger
from openai import OpenAI

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_MAX_CONCURRENCY = 8
_MAX_RATE_LIMIT_RETRIES = 6
_RATE_LIMIT_BACKOFF_CAP = 12.0

_RATE_LIMIT_MARKERS = ("429", "concurrency limit", "rate limit", "too many requests")


def _is_rate_limit(detail: str) -> bool:
    low = detail.lower()
    return any(marker in low for marker in _RATE_LIMIT_MARKERS)


def _as_list(value: Any) -> list[str]:
    if not value or str(value).strip().lower() in ("none", "null", ""):
        return []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    else:
        items = [str(part).strip() for part in value if str(part).strip()]
    return [i for i in items if i and i.lower() not in ("none", "null")]


class LLMRouter:
    """Rotates through API keys so one exhausted key does not stop the run."""

    def __init__(
        self,
        keys: list[str],
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        models: list[str] | None = None,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    ):
        self.keys = [k for k in keys if k]
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self.models = [m for m in (models or [self.model]) if m]
        self._index = 0
        self._lock = threading.Lock()
        self._sem = threading.BoundedSemaphore(max(1, int(max_concurrency)))
        self._clients: dict[str, OpenAI] = {}
        # Circuit breaker: a dead endpoint must not make every later call wait for its timeout
        self._failures = 0
        self._dead = False

    @classmethod
    def from_config(cls, config: Any) -> "LLMRouter":
        llm_cfg = config.get("llm") or {}
        api_cfg = llm_cfg.get("api") or {}
        keys = _as_list(api_cfg.get("keys")) or _as_list(api_cfg.get("key"))
        trans_cfg = config.get("translation") or {}
        for extra in (trans_cfg.get("api_key"), trans_cfg.get("backup_api_key")):
            if extra and str(extra) not in keys:
                keys.append(str(extra))

        primary_model = str((llm_cfg.get("generation_kwargs") or {}).get("model") or trans_cfg.get("model") or DEFAULT_MODEL)
        backup_model = str(llm_cfg.get("backup_model") or trans_cfg.get("backup_model") or "")
        models = [primary_model]
        if backup_model and backup_model not in models:
            models.append(backup_model)

        return cls(
            keys,
            base_url=str(api_cfg.get("base_url") or trans_cfg.get("api_base") or DEFAULT_BASE_URL),
            model=primary_model,
            models=models,
            max_concurrency=int(api_cfg.get("max_concurrency") or DEFAULT_MAX_CONCURRENCY),
        )

    @property
    def available(self) -> bool:
        return bool(self.keys) and not self._dead

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= max(3, len(self.keys) * 2) and not self._dead:
            self._dead = True
            logger.error(
                "LLM endpoint failed repeatedly; skipping remaining LLM work for this run "
                "(set a reachable OPENAI_API_BASE or run again when the provider recovers)"
            )

    def _client(self, key: str) -> OpenAI:
        if key not in self._clients:
            self._clients[key] = OpenAI(api_key=key, base_url=self.base_url)
        return self._clients[key]

    def chat(
        self,
        messages: list[dict[str, str]],
        max_tokens: int = 800,
        temperature: float = 0.1,
        timeout: float = 60,
    ) -> str:
        """Returns the reply text, or an empty string when every key fails."""
        if not self.keys or self._dead:
            return ""

        attempts = 0
        rate_limit_hits = 0
        while attempts < max(len(self.keys), 1):
            with self._lock:
                if not self.keys:
                    break
                key = self.keys[self._index % len(self.keys)]
            attempts += 1
            for boost in (1, 2):
                try:
                    # Allocate enough tokens so reasoning models don't exhaust budget before outputting content
                    call_max_tokens = max(max_tokens, 3000) * boost
                    extra_body = {}
                    if self.models and len(self.models) > 1:
                        extra_body["models"] = self.models

                    call_kwargs: dict[str, Any] = {
                        "model": self.model,
                        "messages": messages,
                        "max_tokens": call_max_tokens,
                        "temperature": temperature,
                        "timeout": max(timeout, 90),
                    }
                    if extra_body:
                        call_kwargs["extra_body"] = extra_body

                    # The provider rejects bursts over its per-key concurrency cap,
                    # so in-flight calls are gated here rather than by thread count.
                    with self._sem:
                        resp = self._client(key).chat.completions.create(**call_kwargs)
                except Exception as exc:
                    detail = str(exc)
                    if _is_rate_limit(detail) and rate_limit_hits < _MAX_RATE_LIMIT_RETRIES:
                        # Transient overload: back off and retry without blaming the endpoint.
                        rate_limit_hits += 1
                        attempts -= 1
                        delay = min(_RATE_LIMIT_BACKOFF_CAP, 0.6 * (2 ** rate_limit_hits))
                        time.sleep(delay + random.uniform(0, 0.4))
                        logger.debug(f"LLM concurrency limit hit; backing off {delay:.1f}s then retrying")
                        continue
                    logger.warning(f"LLM call failed with a pooled key: {exc}")
                    self._record_failure()
                    with self._lock:
                        if "401" in detail or "403" in detail:
                            if key in self.keys:
                                self.keys.remove(key)
                            self._index = 0
                        else:
                            self._index += 1
                    break

                self._failures = 0
                choice = resp.choices[0]
                text = (choice.message.content or "").strip()
                if text:
                    with self._lock:
                        self._index = (self._index + 1) % max(len(self.keys), 1)
                    return text
                # Reasoning models spend the budget before writing the answer
                if choice.finish_reason != "length":
                    break
            if not self.keys:
                break
        return ""
