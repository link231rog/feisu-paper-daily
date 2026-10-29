"""Pipeline base abstractions, DAG stage interfaces, and Agent-Reach style FallbackChains."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
import time
from typing import Any, Generic, Optional, TypeVar

from loguru import logger

from ..protocol import CorpusPaper, Paper, TrendingItem
from ..channels.audio import AudioBundle

T = TypeVar("T")


@dataclass
class BackendResult(Generic[T]):
    """Result wrapper for a single backend or fallback chain execution."""

    ok: bool
    data: Optional[T] = None
    backend_name: str = ""
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


class Backend(ABC, Generic[T]):
    """Abstract single backend within an ordered fallback chain."""

    name: str = "base"

    def is_available(self) -> bool:
        """Check if environment prerequisites (e.g. tools, keys) are satisfied."""
        return True

    @abstractmethod
    def execute(self, *args: Any, **kwargs: Any) -> Optional[T]:
        """Execute backend action. Return None or raise to trigger fallback."""
        ...


class FallbackChain(Generic[T]):
    """Ordered fallback chain inspired by Agent-Reach's backends mechanism.

    Tries backends in priority order. If a backend fails or returns None/empty,
    it records telemetry and gracefully falls back to the next backend in line.
    """

    def __init__(self, backends: list[Backend[T]], name: str = "fallback_chain"):
        self.backends = backends
        self.name = name

    def execute(self, *args: Any, **kwargs: Any) -> BackendResult[T]:
        start_time = time.time()
        errors: list[str] = []

        for b in self.backends:
            if not b.is_available():
                logger.debug(f"[{self.name}] Backend '{b.name}' is unavailable; skipping.")
                continue

            b_t0 = time.time()
            try:
                res = b.execute(*args, **kwargs)
                if res is not None:
                    b_elapsed = time.time() - b_t0
                    logger.debug(f"[{self.name}] Backend '{b.name}' succeeded in {b_elapsed:.2f}s")
                    return BackendResult(
                        ok=True,
                        data=res,
                        backend_name=b.name,
                        elapsed_seconds=time.time() - start_time,
                    )
                errors.append(f"{b.name}: returned None")
            except Exception as exc:
                b_elapsed = time.time() - b_t0
                logger.debug(f"[{self.name}] Backend '{b.name}' failed after {b_elapsed:.2f}s: {exc}")
                errors.append(f"{b.name}: {exc}")

        total_elapsed = time.time() - start_time
        err_msg = " | ".join(errors) or "All backends unavailable or returned empty"
        logger.debug(f"[{self.name}] Fallback chain exhausted ({err_msg}) in {total_elapsed:.2f}s")
        return BackendResult(
            ok=False,
            data=None,
            backend_name="none",
            error=err_msg,
            elapsed_seconds=total_elapsed,
        )


@dataclass
class PipelineContext:
    """Universal state carried across pipeline stages."""

    config: Any
    today_str: str = field(default_factory=lambda: datetime.now().date().isoformat())
    force_today: bool = False

    # Corpus & User Configuration
    corpus: list[CorpusPaper] = field(default_factory=list)
    console_settings: dict[str, Any] = field(default_factory=dict)
    tracked_questions: list[str] = field(default_factory=list)

    # Retrieval & Quality Filter
    all_papers: list[Paper] = field(default_factory=list)
    deduped_papers: list[Paper] = field(default_factory=list)
    new_papers: list[Paper] = field(default_factory=list)
    quality_papers: list[Paper] = field(default_factory=list)

    # Reranking & Selection
    ranked_papers: list[Paper] = field(default_factory=list)
    reranked_papers: list[Paper] = field(default_factory=list)
    deep_read_papers: list[Paper] = field(default_factory=list)
    quick_radar_papers: list[Paper] = field(default_factory=list)
    funnel: dict[str, int] = field(default_factory=dict)

    # External Enrichment (Agent-Reach / Hugging Face / Baselines / Synthesis)
    enrichments: dict[str, dict[str, Any]] = field(default_factory=dict)
    question_briefs: list[dict[str, Any]] = field(default_factory=list)
    suggested_questions: list[str] = field(default_factory=list)

    # Trending Items
    trending_items: list[TrendingItem] = field(default_factory=list)

    # Generated Audio
    audio_bundle: Optional[AudioBundle] = None
    notebooklm_bundles: list[AudioBundle] = field(default_factory=list)

    # Delivery & Ingestion State
    attempted_channels: int = 0
    delivered_channels: list[str] = field(default_factory=list)
    delivery_results: dict[str, Any] = field(default_factory=dict)
    is_delivered: bool = False
    ingested_papers: list[str] = field(default_factory=list)

    # Stage Telemetry & Metadata
    stage_durations: dict[str, float] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)


class PipelineStage(ABC):
    """Abstract stage in the literature pipeline DAG."""

    name: str = "base_stage"

    def is_enabled(self, context: PipelineContext) -> bool:
        """Determines whether this stage should execute based on context."""
        return True

    @abstractmethod
    def run(self, context: PipelineContext) -> None:
        """Executes stage logic, mutating the context."""
        ...
