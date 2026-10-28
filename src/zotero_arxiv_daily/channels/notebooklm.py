"""Google NotebookLM topic-based library ingestion and native dual-host podcast generation.

Uses unofficial Python API (teng-lin/notebooklm-py) to:
1. Ingest filtered daily papers into dedicated Topic Notebooks:
   - "persistent" mode: long-term topic notebook with auto-volume split when reaching quota cap (e.g. 45 sources).
   - "daily" mode: daily-scoped topic notebook (YYYY-MM-DD [Topic] Name).
2. Generate Google official dual-host Audio Overview podcasts (deep-dive, brief, critique, debate)
   and download local audio artifacts.
3. Serve as an independent dual-track audio engine alongside Edge-TTS.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
import datetime
import json
import os
from pathlib import Path
import re
from typing import Any

from loguru import logger
from omegaconf import DictConfig

from ..protocol import Paper
from .audio import AudioBundle


@dataclass
class NotebookLMBundle:
    """Artifact bundle produced by NotebookLM topic pipeline."""

    notebook_id: str
    topic: str
    title: str
    audio_path: Path | None = None
    duration_seconds: int = 0
    sources_count: int = 0
    volume: int = 1
    engine: str = "notebooklm"


def _sanitize_filename(name: str) -> str:
    """Sanitize string for safe filenames."""
    s = re.sub(r'[\\/*?:"<>|]', "", name)
    s = re.sub(r"\s+", "_", s).strip("._")
    return s[:64] or "topic"


def _resolve_auth_json() -> str | None:
    """Resolves NotebookLM Playwright storage state JSON from environment or local storage."""
    # 1. Direct env variable: NOTEBOOKLM_AUTH_JSON
    raw_json = os.environ.get("NOTEBOOKLM_AUTH_JSON", "").strip()
    if raw_json:
        try:
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict) and "cookies" in parsed:
                return raw_json
        except Exception:
            pass

    # 2. Raw cookie map / string env variable: NOTEBOOKLM_COOKIES
    raw_cookies = os.environ.get("NOTEBOOKLM_COOKIES", "").strip()
    if raw_cookies:
        try:
            parsed = json.loads(raw_cookies)
            if isinstance(parsed, list):
                return json.dumps({"cookies": parsed, "origins": []})
            if isinstance(parsed, dict):
                cookie_list = [
                    {"name": k, "value": str(v), "domain": ".google.com", "path": "/"}
                    for k, v in parsed.items()
                ]
                return json.dumps({"cookies": cookie_list, "origins": []})
        except Exception:
            # Parse header string: "name=val; name2=val2"
            pairs = [p.strip().split("=", 1) for p in raw_cookies.split(";") if "=" in p]
            if pairs:
                cookie_list = [
                    {"name": k.strip(), "value": v.strip(), "domain": ".google.com", "path": "/"}
                    for k, v in pairs
                ]
                return json.dumps({"cookies": cookie_list, "origins": []})

    # 3. Local developer default file: ~/.notebooklm/profiles/default/storage_state.json
    local_path = Path.home() / ".notebooklm" / "profiles" / "default" / "storage_state.json"
    if local_path.is_file():
        try:
            return local_path.read_text(encoding="utf-8")
        except Exception:
            pass

    return None


def group_papers_by_topic(
    papers: list[Paper],
    configured_topics: list[str] | None = None,
    fallback_topic: str = "前沿前瞻",
) -> dict[str, list[Paper]]:
    """Groups papers by primary topic matching anchor title, tags, or configured topics."""
    topic_map: dict[str, list[Paper]] = defaultdict(list)
    for p in papers:
        matched: str | None = None
        # 1. Matched anchor title
        if p.matched_anchor_title and len(p.matched_anchor_title.strip()) > 1:
            matched = p.matched_anchor_title.strip()
        # 2. Match against configured topics list
        elif configured_topics:
            combined = f"{p.title} {p.abstract}".lower()
            for top in configured_topics:
                if top and top.lower() in combined:
                    matched = top.strip()
                    break
        # 3. First tag
        if not matched and p.tags:
            for t in p.tags:
                if t and len(t.strip()) > 1:
                    matched = t.strip()
                    break
        if not matched:
            matched = fallback_topic
        topic_map[matched].append(p)

    # Sort topics by paper count descending
    return dict(sorted(topic_map.items(), key=lambda item: len(item[1]), reverse=True))


async def _async_process_topic_notebooklm(
    topic_name: str,
    papers: list[Paper],
    cfg: DictConfig | dict[str, Any],
) -> NotebookLMBundle | None:
    """Async worker handling topic notebook selection, paper ingestion, and optional audio generation."""
    try:
        from notebooklm import AudioFormat, AudioLength, NotebookLMClient
    except ImportError:
        logger.warning("notebooklm-py is not installed. Run 'uv add notebooklm-py' to enable.")
        return None

    auth_json = _resolve_auth_json()
    if not auth_json:
        logger.info(
            "NotebookLM credentials not found. For local usage, run 'notebooklm login' or 'notebooklm login --browser-cookies chrome'. "
            "For GitHub Actions, configure 'NOTEBOOKLM_AUTH_JSON' in repository secrets."
        )
        return None

    # Ensure environment has the JSON for notebooklm-py internal loaders
    os.environ["NOTEBOOKLM_AUTH_JSON"] = auth_json

    nblm_cfg = cfg.get("notebooklm") if hasattr(cfg, "get") else {}
    if not nblm_cfg and isinstance(cfg, dict):
        nblm_cfg = cfg.get("notebooklm") or {}

    notebook_mode = str(nblm_cfg.get("notebook_mode", "persistent")).strip().lower()
    max_sources = int(nblm_cfg.get("max_sources_per_notebook", 45))
    should_gen_audio = str(nblm_cfg.get("generate_audio", True)).strip().lower() in ("true", "1", "yes")
    audio_format_str = str(nblm_cfg.get("audio_format", "deep_dive")).strip().lower()
    audio_length_str = str(nblm_cfg.get("audio_length", "default")).strip().lower()
    audio_lang = str(nblm_cfg.get("audio_language", "zh")).strip()
    output_dir = Path(nblm_cfg.get("output_dir", "data/audio/notebooklm"))
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")

    async with NotebookLMClient.from_storage() as client:
        # 1. Resolve or create topic notebook
        target_notebook_id: str | None = None
        target_notebook_title: str = ""
        current_volume = 1

        if notebook_mode == "daily":
            daily_title = f"{today_str} [Topic] {topic_name}"
            target_notebook_title = daily_title
            # Check existing daily notebooks
            existing_nbs = await client.notebooks.list()
            for nb in existing_nbs:
                if nb.title.strip() == daily_title:
                    target_notebook_id = nb.id
                    break
            if not target_notebook_id:
                new_nb = await client.notebooks.create(daily_title)
                target_notebook_id = new_nb.id
                logger.info(f"Created daily NotebookLM topic notebook: '{daily_title}' (id={target_notebook_id})")
        else:
            # Persistent mode with auto-volume split
            base_title = f"[Topic] {topic_name}"
            existing_nbs = await client.notebooks.list()
            matched_vols: list[tuple[int, Any]] = []
            for nb in existing_nbs:
                t = nb.title.strip()
                if t == base_title:
                    matched_vols.append((1, nb))
                elif t.startswith(f"{base_title} Vol."):
                    m = re.search(r"Vol\.(\d+)", t)
                    vol_num = int(m.group(1)) if m else 1
                    matched_vols.append((vol_num, nb))

            matched_vols.sort(key=lambda x: x[0])
            if matched_vols:
                latest_vol_num, latest_nb = matched_vols[-1]
                sources_cnt = getattr(latest_nb, "sources_count", 0)
                if sources_cnt < max_sources:
                    target_notebook_id = latest_nb.id
                    target_notebook_title = latest_nb.title
                    current_volume = latest_vol_num
                else:
                    # Current volume reached capacity; create next volume
                    current_volume = latest_vol_num + 1
                    new_title = f"{base_title} Vol.{current_volume}"
                    new_nb = await client.notebooks.create(new_title)
                    target_notebook_id = new_nb.id
                    target_notebook_title = new_title
                    logger.info(
                        f"NotebookLM topic '{topic_name}' reached {sources_cnt} sources (cap: {max_sources}). "
                        f"Created volume {current_volume}: '{new_title}'"
                    )
            else:
                new_nb = await client.notebooks.create(base_title)
                target_notebook_id = new_nb.id
                target_notebook_title = base_title
                current_volume = 1
                logger.info(f"Created persistent NotebookLM topic notebook: '{base_title}' (id={target_notebook_id})")

        if not target_notebook_id:
            return None

        # 2. Ingest papers into the notebook
        ingested_count = 0
        existing_source_titles: set[str] = set()
        try:
            curr_sources = await client.sources.list(target_notebook_id)
            existing_source_titles = {s.title.strip().lower() for s in curr_sources if getattr(s, "title", None)}
        except Exception:
            pass

        for p in papers:
            p_title = (p.title or "").strip()
            if p_title.lower() in existing_source_titles:
                continue

            paper_url = p.url or (f"https://arxiv.org/abs/{p.arxiv_id}" if getattr(p, "arxiv_id", None) else "")
            added = False
            if paper_url and paper_url.startswith("http"):
                try:
                    await client.sources.add_url(target_notebook_id, paper_url, title=p_title, wait=True, wait_timeout=60.0)
                    added = True
                    ingested_count += 1
                except Exception as add_err:
                    logger.debug(f"NotebookLM add_url failed for '{p_title}' ({add_err}); falling back to text.")

            if not added:
                try:
                    text_content = (
                        f"Title: {p_title}\n"
                        f"Authors: {', '.join(p.authors or [])}\n"
                        f"URL: {paper_url}\n\n"
                        f"Abstract:\n{p.abstract or ''}\n\n"
                        f"Key Insights & Innovations:\n{p.tldr_zh or p.tldr or ''}\n"
                    )
                    await client.sources.add_text(target_notebook_id, text_content, title=p_title)
                    ingested_count += 1
                except Exception as txt_err:
                    logger.warning(f"Failed to add paper '{p_title}' to NotebookLM: {txt_err}")

        logger.info(f"Ingested {ingested_count} papers into NotebookLM notebook '{target_notebook_title}'")

        # 3. Optional Google Native Dual-Host Audio Overview Generation
        audio_file_path: Path | None = None
        duration_est = 0
        if should_gen_audio and (ingested_count > 0 or existing_source_titles):
            try:
                fmt_map = {
                    "deep_dive": AudioFormat.DEEP_DIVE,
                    "brief": AudioFormat.BRIEF,
                    "critique": AudioFormat.CRITIQUE,
                    "debate": AudioFormat.DEBATE,
                }
                len_map = {
                    "short": AudioLength.SHORT,
                    "default": AudioLength.DEFAULT,
                    "long": AudioLength.LONG,
                }
                afmt = fmt_map.get(audio_format_str, AudioFormat.DEEP_DIVE)
                alen = len_map.get(audio_length_str, AudioLength.DEFAULT)
                instructions = (
                    f"请深入讨论本专题【{topic_name}】的核心技术演进、关键论文的机制创新（Delta）与实验评估对比。"
                    f"语言风格生动自然，双人对谈要突出不同方法之间的优劣权衡、技术洞察与实际工程落地启示。"
                )

                logger.info(f"Requesting NotebookLM official dual-host audio generation for '{topic_name}'...")
                gen_status = await client.artifacts.generate_audio(
                    target_notebook_id,
                    language=audio_lang,
                    audio_format=afmt,
                    audio_length=alen,
                    instructions=instructions,
                )

                if gen_status and getattr(gen_status, "task_id", None):
                    logger.info(f"Waiting for NotebookLM audio generation task {gen_status.task_id} (timeout: 360s)...")
                    done_status = await client.artifacts.wait_for_completion(
                        target_notebook_id,
                        gen_status.task_id,
                        timeout=360.0,
                    )
                    clean_name = _sanitize_filename(topic_name)
                    audio_file_path = output_dir / f"notebooklm_{clean_name}_{today_str}.mp3"
                    await client.artifacts.download_audio(target_notebook_id, str(audio_file_path))
                    logger.info(f"Downloaded NotebookLM audio overview to: {audio_file_path}")
                    duration_est = 600 if alen == AudioLength.DEFAULT else (300 if alen == AudioLength.SHORT else 900)
            except Exception as audio_err:
                logger.warning(f"NotebookLM audio generation failed or timed out: {audio_err}")

        return NotebookLMBundle(
            notebook_id=target_notebook_id,
            topic=topic_name,
            title=f"NotebookLM 深度播客 | {topic_name}",
            audio_path=audio_file_path,
            duration_seconds=duration_est,
            sources_count=len(existing_source_titles) + ingested_count,
            volume=current_volume,
        )


def run_notebooklm_pipeline(
    papers: list[Paper],
    config: DictConfig | dict[str, Any],
) -> list[AudioBundle]:
    """Synchronous pipeline entrypoint to ingest papers by topic and produce independent NotebookLM AudioBundles."""
    nblm_cfg = config.get("notebooklm") if hasattr(config, "get") else {}
    if not nblm_cfg and isinstance(config, dict):
        nblm_cfg = config.get("notebooklm") or {}

    enabled = str(nblm_cfg.get("enabled", False)).strip().lower() in ("true", "1", "yes")
    if not enabled and os.environ.get("NOTEBOOKLM_ENABLED", "").strip().lower() not in ("true", "1", "yes"):
        return []

    if not papers:
        return []

    configured_topics: list[str] = []
    if hasattr(config, "topics") and config.topics:
        configured_topics = [str(t) for t in config.topics if str(t).strip()]
    elif isinstance(config, dict) and config.get("topics"):
        configured_topics = [str(t) for t in config["topics"] if str(t).strip()]

    grouped = group_papers_by_topic(papers, configured_topics=configured_topics)
    if not grouped:
        return []

    max_topics = int(nblm_cfg.get("max_topics", 1))
    target_topics = list(grouped.items())[:max_topics]

    bundles: list[AudioBundle] = []

    def _run_async(coro: Any) -> Any:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(1) as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return asyncio.run(coro)

    for topic_name, topic_papers in target_topics:
        logger.info(f"Processing NotebookLM pipeline for topic '{topic_name}' ({len(topic_papers)} papers)...")
        try:
            res: NotebookLMBundle | None = _run_async(
                _async_process_topic_notebooklm(topic_name, topic_papers, config)
            )
            if res and res.audio_path and res.audio_path.is_file():
                bundle = AudioBundle(
                    mp3_path=res.audio_path,
                    script_path=res.audio_path.with_suffix(".txt"),
                    wechat_mp3_path=None,  # NotebookLM deep dive is reserved for full channels, not WeChat 60s
                    mode="notebooklm",
                    engine="notebooklm",
                    duration_seconds=res.duration_seconds,
                    title=res.title,
                )
                bundles.append(bundle)
        except Exception as exc:
            logger.warning(f"Failed processing NotebookLM topic '{topic_name}': {exc}")

    return bundles
