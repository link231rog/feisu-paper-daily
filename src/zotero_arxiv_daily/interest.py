from datetime import datetime
from typing import Any
from loguru import logger
from omegaconf import DictConfig, ListConfig

from .protocol import CorpusPaper


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


def get_interest_corpus(config: DictConfig) -> list[CorpusPaper]:
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
            from .feishu import FeishuClient
            client = FeishuClient(feishu_config)
            notes_corpus = client.fetch_reading_notes()
            logger.info(f"Loaded {len(notes_corpus)} papers from Feishu reading notes")
            corpus.extend(notes_corpus)
            tag_members = client.reading_note_tags
        except Exception as exc:
            logger.warning(f"Could not load Feishu reading notes: {exc}")

    # 3. Feishu console: tracked tags and questions
    console_cfg = config.get("console")
    if console_cfg and console_cfg.get("enabled", True):
        settings = {
            "tags": [str(t) for t in (console_cfg.get("tags") or [])],
            "questions": [str(q) for q in (console_cfg.get("questions") or [])],
        }
        if console_cfg.get("node_token") and feishu_config and not feishu_config.get("dry_run", False):
            try:
                from .feishu import FeishuClient
                client = FeishuClient(feishu_config)
                remote = client.fetch_console_settings(str(console_cfg.node_token))
                settings["tags"] = remote["tags"] or settings["tags"]
                settings["questions"] = remote["questions"] or settings["questions"]
            except Exception as exc:
                logger.warning(f"Could not read Feishu console: {exc}")

        console_corpus = build_corpus_from_console(settings["tags"], settings["questions"], tag_members)
        if console_corpus:
            logger.info(
                f"Loaded {len(settings['tags'])} console tags and {len(settings['questions'])} tracked questions"
            )
            corpus.extend(console_corpus)

    if not corpus:
        logger.warning("No research topics or notes found in configuration.")

    return corpus

