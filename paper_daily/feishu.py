"""Backward-compatible re-export for paper_daily.feishu."""

from .channels.feishu import *  # noqa: F401,F403
from .channels.feishu import _build_annotation_workspace_markdown, _split_markdown_chunks  # noqa: F401
