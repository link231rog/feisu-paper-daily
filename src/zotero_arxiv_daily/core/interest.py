from datetime import datetime
from typing import Any
from loguru import logger
from omegaconf import DictConfig, ListConfig

from ..protocol import CorpusPaper


def build_corpus_from_topics(topics: list[dict[str, Any]] | ListConfig | None) -> list[CorpusPaper]:
    """Constructs CorpusPaper list from configured research topics."""
    if not topics:
        return []

    corpus: list[CorpusPaper] = []
    for idx, item in enumerate(topics):
        if isinstance(item, str):
            name = f"Topic {idx + 1}"
            abstract = item.strip()
            keywords = []
        elif isinstance(item, dict) or hasattr(item, "get"):
            name = item.get("name", f"Topic {idx + 1}")
            desc = item.get("description", "")
            raw_keywords = item.get("keywords") or []
            if isinstance(raw_keywords, (list, ListConfig)):
                keywords_str = ", ".join(str(k) for k in raw_keywords)
            else:
                keywords_str = str(raw_keywords)
            
            parts = []
            if desc:
                parts.append(str(desc).strip())
            if keywords_str:
                parts.append(f"Keywords: {keywords_str}")
            abstract = "\n".join(parts) if parts else name
        else:
            continue

        corpus.append(
            CorpusPaper(
                title=name,
                abstract=abstract,
                added_date=datetime.now(),
                paths=[f"topics/{name}"],
            )
        )
    return corpus


def build_corpus_from_console(
    tags: list[str] | None,
    questions: list[str] | None,
    tag_members: dict[str, list[str]] | None = None,
) -> list[CorpusPaper]:
    """Turns console tags and tracked questions into reranking anchors."""
    corpus: list[CorpusPaper] = []
    tag_members = tag_members or {}

    for tag in tags or []:
        members = tag_members.get(tag, [])
        abstract = f"Research tag: {tag}"
        if members:
            abstract += "\nRelated papers: " + "; ".join(members[:10])
        corpus.append(
            CorpusPaper(
                title=f"Tag: {tag}",
                abstract=abstract,
                added_date=datetime.now(),
                paths=[f"console/tags/{tag}"],
            )
        )

    for idx, question in enumerate(questions or [], 1):
        corpus.append(
            CorpusPaper(
                title=f"Question {idx}",
                abstract=str(question).strip(),
                added_date=datetime.now(),
                paths=[f"console/questions/{idx}"],
            )
        )
    return corpus


def taste_corpus(corpus: list[CorpusPaper]) -> list[CorpusPaper]:
    """Drops console tags/questions so they cannot dominate the library taste score."""
    taste = [
        c for c in corpus
        if not any(str(path).startswith("console/") for path in (c.paths or []))
    ]
    if not taste and corpus:
        logger.warning("Interest corpus is only console tags/questions; falling back for reranking")
        return corpus
    return taste


def get_interest_corpus(
    config: DictConfig,
    console_settings: dict[str, list[str]] | None = None,
) -> list[CorpusPaper]:
    """Retrieves interest corpus from configured topics, reading notes, or Zotero fallback."""
    corpus: list[CorpusPaper] = []

    # 1. Primary: configured research topics
    topics = config.get("topics")
    if topics:
        topic_corpus = build_corpus_from_topics(topics)
        logger.info(f"Loaded {len(topic_corpus)} interest profiles from configured research topics")
        corpus.extend(topic_corpus)

    # 2. Feishu reading notes (for Step 3)
    feishu_config = config.get("feishu")
    tag_members: dict[str, list[str]] = {}
    if (
        feishu_config
        and (feishu_config.get("notes_folder_token") or feishu_config.get("notes_parent_node_token"))
        and not feishu_config.get("dry_run", False)
    ):
        try:
            from ..channels.feishu import FeishuClient
            client = FeishuClient(feishu_config)
            notes_corpus = client.fetch_reading_notes()
            logger.info(f"Loaded {len(notes_corpus)} papers from Feishu reading notes")
            corpus.extend(notes_corpus)
            tag_members = client.reading_note_tags
        except Exception as exc:
            logger.warning(f"Could not load Feishu reading notes: {exc}")

    # 3. Console: tracked tags and questions, from whichever provider the user configured
    console_cfg = config.get("console")
    if console_cfg and str(console_cfg.get("enabled", True)).lower() not in ("false", "0", "no"):
        if console_settings is None:
            from ..library.console import load_console_settings

            console_settings = load_console_settings(config)

        console_corpus = build_corpus_from_console(
            console_settings.get("tags"), console_settings.get("questions"), tag_members
        )
        if console_corpus:
            logger.info(
                f"Loaded {len(console_settings.get('tags', []))} console tags and "
                f"{len(console_settings.get('questions', []))} tracked questions"
            )
            corpus.extend(console_corpus)

    if not corpus:
        logger.warning("No research topics or notes found in configuration.")

    return corpus

