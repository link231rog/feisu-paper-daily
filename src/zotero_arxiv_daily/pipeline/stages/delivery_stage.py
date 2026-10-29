"""Delivery stage: multi-channel distribution across Feishu, Email, Telegram, WeChat, and Audio."""

from __future__ import annotations

from typing import Any

from loguru import logger

from ...channels.audio import generate_daily_audio_bundle
from ...channels.daily_report import build_daily_report
from ...channels.notebooklm import run_notebooklm_pipeline
from ...channels.telegram import send_telegram_daily_report
from ...utils import send_email
from ..base import PipelineContext, PipelineStage


def _as_bool(val: Any) -> bool:
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("true", "1", "yes")


class DeliveryStage(PipelineStage):
    """Orchestrates delivery across Feishu Wiki, SMTP Email, Telegram Bot, WeChat, and Audio."""

    name = "delivery"

    def __init__(self, executor: Any):
        self.executor = executor

    def run(self, context: PipelineContext) -> None:
        if not context.reranked_papers and not context.trending_items and not context.config.executor.send_empty:
            logger.info("Neither new papers nor new trending items found. Skipping delivery.")
            return

        today_str = context.today_str
        force_today = context.force_today
        delivered = False
        attempted_channels = 0

        # 1. Edge-TTS Audio Generation
        audio_bundle = None
        audio_cfg = context.config.get("audio") or {}
        if _as_bool(audio_cfg.get("enabled", False)) and (context.reranked_papers or context.trending_items):
            try:
                audio_bundle = generate_daily_audio_bundle(
                    context.reranked_papers,
                    context.config,
                    question_briefs=context.question_briefs,
                    trending_items=context.trending_items,
                    router=self.executor.router,
                )
                context.audio_bundle = audio_bundle
            except Exception as exc:
                logger.warning(f"Optional Edge-TTS audio bundle generation failed: {exc}")

        # 2. Google NotebookLM Topic Ingestion & Podcast Generation
        notebooklm_bundles = []
        notebooklm_cfg = context.config.get("notebooklm") or {}
        if _as_bool(notebooklm_cfg.get("enabled", False)) and context.reranked_papers:
            try:
                notebooklm_bundles = run_notebooklm_pipeline(
                    context.reranked_papers,
                    context.config,
                )
                context.notebooklm_bundles = notebooklm_bundles
            except Exception as exc:
                logger.warning(f"Optional NotebookLM topic pipeline failed: {exc}")

        # Resolve multi-audio attachment paths
        feishu_audio_paths: list[str] = []
        if audio_bundle and _as_bool(audio_cfg.get("attach_feishu", True)):
            feishu_audio_paths.append(str(audio_bundle.mp3_path))
        if _as_bool(notebooklm_cfg.get("attach_feishu", True)):
            for nb_b in notebooklm_bundles:
                if nb_b.mp3_path and nb_b.mp3_path.is_file():
                    feishu_audio_paths.append(str(nb_b.mp3_path))

        email_attachments: list[str] = []
        if audio_bundle and _as_bool(audio_cfg.get("attach_email", True)):
            email_attachments.append(str(audio_bundle.mp3_path))
        if _as_bool(notebooklm_cfg.get("attach_email", True)):
            for nb_b in notebooklm_bundles:
                if nb_b.mp3_path and nb_b.mp3_path.is_file():
                    email_attachments.append(str(nb_b.mp3_path))

        wechat_voice_path = (
            str(audio_bundle.wechat_mp3_path)
            if audio_bundle and audio_bundle.wechat_mp3_path and _as_bool(audio_cfg.get("upload_wechat_voice", True))
            else None
        )

        telegram_audio_items: list[Any] = []
        if audio_bundle and _as_bool(audio_cfg.get("attach_telegram", True)):
            telegram_audio_items.append(audio_bundle)
        if _as_bool(notebooklm_cfg.get("attach_telegram", True)):
            for nb_b in notebooklm_bundles:
                if nb_b.mp3_path and nb_b.mp3_path.is_file():
                    telegram_audio_items.append(nb_b)

        # 3. Feishu Delivery
        feishu_cfg = context.config.get("feishu")
        is_feishu_dry_run = _as_bool(feishu_cfg.get("dry_run", False)) if feishu_cfg else False
        if feishu_cfg and feishu_cfg.get("app_id") and not is_feishu_dry_run:
            attempted_channels += 1
            try:
                from ...channels.feishu import FeishuClient

                client = FeishuClient(feishu_cfg)
                doc_url = client.create_or_update_daily_report(
                    context.reranked_papers,
                    trending_items=context.trending_items,
                    question_briefs=context.question_briefs,
                    corpus=context.corpus,
                    audio_path=feishu_audio_paths if feishu_audio_paths else None,
                )
                logger.info(f"Feishu daily report updated successfully: {doc_url}")
                self.executor.paper_store.mark_channel_delivered("feishu", today_str)
                context.delivered_channels.append("feishu")
                context.delivery_results["feishu"] = doc_url
                delivered = True
            except Exception as exc:
                logger.error(f"Failed to publish Feishu daily report: {exc}")
                context.errors.append({"channel": "feishu", "error": str(exc)})

        # 4. Email Delivery
        email_cfg = context.config.get("email")
        email_enabled = _as_bool(email_cfg.get("enabled", True)) if email_cfg else False
        sender_val = str(email_cfg.get("sender") or "").strip() if email_cfg else ""
        receiver_val = str(email_cfg.get("receiver") or "").strip() if email_cfg else ""
        pwd_val = str(email_cfg.get("sender_password") or "").strip() if email_cfg else ""
        if email_cfg and email_enabled and sender_val and receiver_val and pwd_val and sender_val != "???":
            attempted_channels += 1
            try:
                if self.executor.paper_store.is_channel_delivered("email", today_str) and not force_today and not context.reranked_papers:
                    logger.info(f"Daily report email already sent today ({today_str}); skipping.")
                    delivered = True
                else:
                    report = build_daily_report(context.reranked_papers, context.question_briefs, trending_items=context.trending_items)
                    logger.info(f"Sending daily report email to {receiver_val} via {email_cfg.get('smtp_server', 'smtp.qq.com')}...")
                    send_email(context.config, report.html, report.title, attachments=email_attachments)
                    logger.info(f"Daily report email sent successfully to {receiver_val}")
                    self.executor.paper_store.mark_channel_delivered("email", today_str)
                    context.delivered_channels.append("email")
                    delivered = True
            except Exception as exc:
                logger.error(f"Failed to send email daily report: {exc}")
                context.errors.append({"channel": "email", "error": str(exc)})

        # 5. WeChat Delivery
        wechat_cfg = context.config.get("wechat")
        wechat_enabled = _as_bool(wechat_cfg.get("enabled", False)) if wechat_cfg else False
        if wechat_cfg and wechat_enabled and wechat_cfg.get("app_id") and wechat_cfg.get("app_secret"):
            attempted_channels += 1
            try:
                if self.executor.paper_store.is_channel_delivered("wechat", today_str) and not force_today and not context.reranked_papers:
                    logger.info(f"WeChat daily report draft already created today ({today_str}); skipping.")
                    delivered = True
                else:
                    from ...channels.wechat import publish_wechat_drafts

                    media_id = publish_wechat_drafts(
                        wechat_cfg,
                        context.reranked_papers,
                        question_briefs=context.question_briefs,
                        trending_items=context.trending_items,
                        router=self.executor.router,
                        voice_mp3_path=wechat_voice_path,
                    )
                    logger.info(f"WeChat daily report draft(s) created successfully (media_id={media_id})")
                    self.executor.paper_store.mark_channel_delivered("wechat", today_str)
                    context.delivered_channels.append("wechat")
                    context.delivery_results["wechat"] = media_id
                    delivered = True
            except Exception as exc:
                logger.error(f"Failed to create WeChat daily report draft: {exc}")
                context.errors.append({"channel": "wechat", "error": str(exc)})

        # 6. Telegram Delivery
        telegram_cfg = context.config.get("telegram")
        telegram_enabled = _as_bool(telegram_cfg.get("enabled", False)) if telegram_cfg else False
        if telegram_cfg and telegram_enabled and telegram_cfg.get("bot_token") and telegram_cfg.get("chat_id"):
            attempted_channels += 1
            try:
                if self.executor.paper_store.is_channel_delivered("telegram", today_str) and not force_today and not context.reranked_papers:
                    logger.info(f"Telegram daily report already sent today ({today_str}); skipping.")
                    delivered = True
                else:
                    send_telegram_daily_report(
                        telegram_cfg,
                        context.reranked_papers,
                        question_briefs=context.question_briefs,
                        trending_items=context.trending_items,
                        audio_path=telegram_audio_items if telegram_audio_items else None,
                        audio_title=audio_bundle.title if audio_bundle else None,
                        audio_duration=audio_bundle.duration_seconds if audio_bundle else None,
                    )
                    logger.info("Telegram daily report sent successfully")
                    self.executor.paper_store.mark_channel_delivered("telegram", today_str)
                    context.delivered_channels.append("telegram")
                    delivered = True
            except Exception as exc:
                logger.error(f"Failed to send Telegram daily report: {exc}")
                context.errors.append({"channel": "telegram", "error": str(exc)})

        context.attempted_channels = attempted_channels
        context.is_delivered = delivered

        if attempted_channels and not delivered:
            raise RuntimeError(
                f"Configured delivery channels ({attempted_channels}) all failed today. "
                "Failing run so scheduled workflow detects the error."
            )

        # Mark as pushed only after a channel actually delivered (or in local dry-run)
        if delivered or is_feishu_dry_run:
            if not context.config.get("executor", {}).get("debug", False):
                if context.reranked_papers:
                    self.executor.paper_store.mark_pushed(context.reranked_papers)
                    logger.info(f"Marked {len(context.reranked_papers)} papers as pushed in paper_store")
                if context.trending_items:
                    self.executor.paper_store.mark_pushed(context.trending_items)
                    logger.info(f"Marked {len(context.trending_items)} trending items as pushed in paper_store")
