"""Telegram Bot delivery channel for Paper Daily.

Formats deep-read digests, quick-radar papers, tracked-question evidence briefs,
and open-source trends into clean Telegram HTML messages (auto-chunked under 4096 chars).
"""

from __future__ import annotations

from datetime import datetime
import html
from typing import Any

import requests
from loguru import logger

from ..protocol import Paper, TrendingItem

TELEGRAM_MAX_LEN = 4000


def _esc(text: Any) -> str:
    return html.escape(str(text or "").strip())


def format_telegram_messages(
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    max_len: int = TELEGRAM_MAX_LEN,
) -> list[str]:
    """Formats the daily report into one or more Telegram HTML message chunks."""
    today = datetime.now().strftime("%Y-%m-%d")
    deep_read = [p for p in papers if getattr(p, "recommendation_tier", "deep_read") == "deep_read"]
    quick_radar = [p for p in papers if getattr(p, "recommendation_tier", None) == "quick_radar"]

    blocks: list[str] = []

    # 1. Header
    header = (
        f"<b>Paper Daily | {today}</b>\n"
        f"精读必看: {len(deep_read)} 篇 | 速览雷达: {len(quick_radar)} 篇"
    )
    blocks.append(header)

    # 2. Question Tracking Briefs
    if question_briefs:
        q_lines = ["<b>[问题追踪简报]</b>"]
        for idx, qb in enumerate(question_briefs[:5], 1):
            q_text = _esc(qb.get("question", ""))
            ans = _esc(qb.get("answer") or qb.get("takeaway") or "")
            gap = _esc(qb.get("gap") or "")
            line = f"{idx}. <b>{q_text}</b>"
            if ans:
                line += f"\n   • 进展: {ans}"
            if gap:
                line += f"\n   • 盲区: {gap}"
            q_lines.append(line)
        blocks.append("\n".join(q_lines))

    # 3. Deep Read Papers
    if deep_read:
        blocks.append("<b>[精读必看]</b>")
        for idx, p in enumerate(deep_read, 1):
            title = _esc(p.title_with_venue())
            url = (p.url or "").strip()
            title_link = f'<a href="{html.escape(url, quote=True)}">{title}</a>' if url else f"<b>{title}</b>"
            score_str = f"{p.score:.1f}" if p.score is not None else "N/A"
            digest = p.critical_digest or {}
            badge = _esc(p.review_badge or "[值得参考]")
            delta = _esc(digest.get("delta") or p.tldr_zh or p.tldr or (p.abstract or "")[:160])
            mech = digest.get("mechanism") or {}
            pipeline = _esc(mech.get("pipeline") or "")
            formula = _esc(mech.get("core_formula") or "")
            ev = digest.get("evidence_and_cost") or {}
            metrics = _esc(ev.get("metrics") or "")
            cost = _esc(ev.get("cost_and_limits") or "")
            action = _esc(digest.get("action_or_check") or "")

            lines = [
                f"<b>{idx}. {title_link}</b>",
                f"评分: <code>{score_str}</code> | 评级: <b>{badge}</b>",
                f"• <b>核心增量</b>: {delta}",
            ]
            if pipeline and pipeline != "N/A":
                lines.append(f"• <b>方法链路</b>: <code>{pipeline}</code>")
            if formula and formula not in ("N/A", "N/A (需查正文)"):
                lines.append(f"• <b>关键公式</b>: <code>{formula}</code>")
            if metrics and metrics != "N/A":
                lines.append(f"• <b>实验核查</b>: {metrics}")
            if cost and cost != "N/A":
                lines.append(f"• <b>算力开销</b>: {cost}")
            if action and action != "N/A":
                lines.append(f"• <b>启发与待查</b>: {action}")
            blocks.append("\n".join(lines))

    # 4. Quick Radar Papers
    if quick_radar:
        q_lines = ["<b>[速览雷达]</b>"]
        for idx, p in enumerate(quick_radar, 1):
            title = _esc(p.title_with_venue())
            url = (p.url or "").strip()
            title_link = f'<a href="{html.escape(url, quote=True)}">{title}</a>' if url else title
            score_str = f"{p.score:.1f}" if p.score is not None else "N/A"
            tldr = _esc(p.tldr_zh or p.tldr or (p.abstract or "")[:120])
            q_lines.append(f"{idx}. {title_link} (<code>{score_str}</code>)\n   {tldr}")
        blocks.append("\n".join(q_lines))

    # 5. Trending Items
    if trending_items:
        t_lines = ["<b>[开源与前沿动态]</b>"]
        for idx, item in enumerate(trending_items[:4], 1):
            t_title = _esc(item.title)
            t_url = (item.url or "").strip()
            link = f'<a href="{html.escape(t_url, quote=True)}">{t_title}</a>' if t_url else t_title
            summary = _esc(item.summary_zh or item.description or "")
            t_lines.append(f"{idx}. {link}\n   {summary}")
        blocks.append("\n".join(t_lines))

    # Chunk blocks into messages <= max_len
    messages: list[str] = []
    current = ""
    for blk in blocks:
        if len(blk) > max_len:
            blk = blk[: max_len - 20] + "..."
        candidate = f"{current}\n\n{blk}" if current else blk
        if len(candidate) <= max_len:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = blk
    if current:
        messages.append(current)

    return messages


def send_telegram_audio(
    telegram_cfg: Any,
    audio_path: str | Any,
    title: str | None = None,
    caption: str | None = None,
    performer: str = "Paper Daily",
    duration: int | None = None,
) -> int | None:
    """Upload and send an MP3 audio file to a Telegram chat using the native Bot sendAudio API."""
    from pathlib import Path

    path = Path(audio_path)
    if not path.is_file():
        raise ValueError(f"Telegram audio file not found: {path}")

    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    chat_id = str(telegram_cfg.get("chat_id") or "").strip()
    thread_id = telegram_cfg.get("message_thread_id")
    api_base = str(telegram_cfg.get("api_base") or "https://api.telegram.org").rstrip("/")

    if not bot_token or not chat_id:
        raise ValueError("Telegram bot_token and chat_id are required")

    endpoint = f"{api_base}/bot{bot_token}/sendAudio"
    today = datetime.now().strftime("%Y-%m-%d")
    data: dict[str, Any] = {
        "chat_id": chat_id,
        "title": (title or f"Paper Daily 语音播客 | {today}")[:64],
        "performer": performer,
        "caption": (caption or f"Paper Daily | {today} 每日精选论文语音导读")[:1024],
    }
    if duration and duration > 0:
        data["duration"] = int(duration)
    if thread_id:
        data["message_thread_id"] = int(thread_id)

    with path.open("rb") as f_audio:
        resp = requests.post(
            endpoint,
            data=data,
            files={"audio": (path.name, f_audio, "audio/mpeg")},
            timeout=60,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Telegram sendAudio failed ({resp.status_code}): {resp.text[:200]}")
    res_json = resp.json()
    mid = (res_json.get("result") or {}).get("message_id")
    logger.info(f"Sent Telegram MP3 audio '{path.name}' to chat {chat_id} (message_id={mid})")
    return int(mid) if mid is not None else None


def send_telegram_daily_report(
    telegram_cfg: Any,
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    audio_path: str | Any | None = None,
    audio_title: str | None = None,
    audio_duration: int | None = None,
) -> list[int]:
    """Sends the formatted daily report (and optional MP3 podcast) to a Telegram chat via Bot API."""
    bot_token = str(telegram_cfg.get("bot_token") or "").strip()
    chat_id = str(telegram_cfg.get("chat_id") or "").strip()
    thread_id = telegram_cfg.get("message_thread_id")
    api_base = str(telegram_cfg.get("api_base") or "https://api.telegram.org").rstrip("/")

    if not bot_token or not chat_id:
        raise ValueError("Telegram bot_token and chat_id are required")

    messages = format_telegram_messages(papers, question_briefs=question_briefs, trending_items=trending_items)
    message_ids: list[int] = []
    endpoint = f"{api_base}/bot{bot_token}/sendMessage"

    if audio_path:
        try:
            audio_mid = send_telegram_audio(
                telegram_cfg,
                audio_path=audio_path,
                title=audio_title,
                duration=audio_duration,
            )
            if audio_mid is not None:
                message_ids.append(audio_mid)
        except Exception as exc:
            logger.warning(f"Failed to send Telegram audio attachment: {exc}")

    for chunk in messages:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": chunk,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if thread_id:
            payload["message_thread_id"] = int(thread_id)
        resp = requests.post(endpoint, json=payload, timeout=20)
        if resp.status_code != 200:
            raise RuntimeError(f"Telegram sendMessage failed ({resp.status_code}): {resp.text[:200]}")
        data = resp.json()
        mid = (data.get("result") or {}).get("message_id")
        if mid is not None:
            message_ids.append(int(mid))

    logger.info(f"Sent {len(message_ids)} Telegram message chunk(s) to chat {chat_id}")
    return message_ids
