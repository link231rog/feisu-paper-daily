"""Literature library bidirectional bridge and console configuration parser."""

from .bridge import *  # noqa: F401,F403
from .bridge import _block_text, _comment_signature, _enabled_providers, _load_cache, _save_cache, main  # noqa: F401
from .console import (  # noqa: F401
    _apply_dispatch_payload,
    append_suggested_questions_to_console,
    feishu_blocks_to_text,
    load_console_settings,
    parse_console_text,
)
from .finder import (  # noqa: F401
    find_papers,
    format_found_papers_markdown,
    generate_poster_for_paper_direct,
    ingest_paper_direct,
    normalize_paper_url,
    search_and_rank_papers,
    search_arxiv,
    search_dblp,
    search_semantic_scholar,
)
