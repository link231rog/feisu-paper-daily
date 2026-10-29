"""Pipeline DAG architecture and fallback chain abstractions."""

from .backends.agent_reach import AgentReachCLI
from .backends.fulltext_backends import (
    AgentReachReadBackend,
    ArxivHtmlBackend,
    PyMuPDFBackend,
    TrafilaturaBackend,
    create_default_fulltext_chain,
)
from .base import Backend, BackendResult, FallbackChain, PipelineContext, PipelineStage
from .engine import PipelineEngine

__all__ = [
    "AgentReachCLI",
    "AgentReachReadBackend",
    "ArxivHtmlBackend",
    "Backend",
    "BackendResult",
    "FallbackChain",
    "PipelineContext",
    "PipelineEngine",
    "PipelineStage",
    "PyMuPDFBackend",
    "TrafilaturaBackend",
    "create_default_fulltext_chain",
]
