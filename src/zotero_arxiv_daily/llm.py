"""Shared LLM access with key rotation across the free API pool."""

import threading
from typing import Any

from loguru import logger
from openai import OpenAI

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "z-ai/glm-5.3-flash"


def _as_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return [str(part).strip() for part in value if str(part).strip()]


class LLMRouter:
    """Rotates through API keys so one exhausted key does not stop the run."""

    def __init__(self, keys: list[str], base_url: str = DEFAULT_BASE_URL, model: str = DEFAULT_MODEL):
        self.keys = [k for k in keys if k]
        self.base_url = base_url or DEFAULT_BASE_URL
        self.model = model or DEFAULT_MODEL
        self._index = 0
        self._lock = threading.Lock()
        self._clients: dict[str, OpenAI] = {}

    @classmethod
    def from_config(cls, config: Any) -> "LLMRouter":
        llm_cfg = config.get("llm") or {}
        api_cfg = llm_cfg.get("api") or {}
        keys = _as_list(api_cfg.get("keys")) or _as_list(api_cfg.get("key"))
        trans_cfg = config.get("translation") or {}
        for extra in (trans_cfg.get("api_key"), trans_cfg.get("backup_api_key")):
            if extra and str(extra) not in keys:
                keys.append(str(extra))
        return cls(
            keys,
            base_url=str(api_cfg.get("base_url") or trans_cfg.get("api_base") or DEFAULT_BASE_URL),
            model=str((llm_cfg.get("generation_kwargs") or {}).get("model") or trans_cfg.get("model") or DEFAULT_MODEL),
        )

    @property
    def available(self) -> bool:
        return bool(self.keys)

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
        if not self.keys:
            return ""

        attempts = 0
        while attempts < max(len(self.keys), 1):
            with self._lock:
                if not self.keys:
                    break
                key = self.keys[self._index % len(self.keys)]
            attempts += 1
            for boost in (1, 2):
                try:
                    resp = self._client(key).chat.completions.create(
                        model=self.model,
                        messages=messages,
                        max_tokens=max_tokens * boost,
                        temperature=temperature,
                        timeout=timeout,
                    )
                except Exception as exc:
                    logger.warning(f"LLM call failed with a pooled key: {exc}")
                    with self._lock:
                        if "401" in str(exc) or "403" in str(exc):
                            if key in self.keys:
                                self.keys.remove(key)
                            self._index = 0
                        else:
                            self._index += 1
                    break

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
