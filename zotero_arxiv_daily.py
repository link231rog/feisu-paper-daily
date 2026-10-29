"""Backward-compatibility shim redirecting zotero_arxiv_daily -> paper_daily."""

from __future__ import annotations

import sys
import paper_daily

# Alias in sys.modules so submodule imports also resolve
sys.modules["zotero_arxiv_daily"] = paper_daily

# Re-export all public attributes
for _attr in dir(paper_daily):
    if not _attr.startswith("__"):
        globals()[_attr] = getattr(paper_daily, _attr)
