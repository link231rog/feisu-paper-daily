"""Multi-channel delivery adapters (Feishu, WeChat Official Account, Telegram, Audio, Daily Report)."""

from .audio import (
    AudioBundle,
    AudioSegment,
    build_audio_script,
    build_wechat_60s_script,
    clean_text_for_tts,
    concat_mp3_segments,
    generate_daily_audio_bundle,
    synthesize_segments_to_mp3,
)
from .daily_report import (
    DailyReport,
    build_daily_report,
    markdown_to_email_html,
    render_report_markdown,
)
from .feishu import FeishuClient, normalize_reading_status
from .notebooklm import NotebookLMBundle, group_papers_by_topic, run_notebooklm_pipeline
from .telegram import format_telegram_messages, send_telegram_audio, send_telegram_daily_report
from .wechat import (
    build_digest_wechat_article,
    build_single_paper_deep_read_article,
    build_topic_review_article,
    build_wechat_articles,
    convert_links_to_wechat_footnotes,
    create_draft,
    generate_academic_cover,
    markdown_to_wechat_html,
    publish_wechat_drafts,
    upload_wechat_voice_material,
)

__all__ = [
    "AudioBundle",
    "AudioSegment",
    "DailyReport",
    "FeishuClient",
    "NotebookLMBundle",
    "build_audio_script",
    "build_daily_report",
    "build_digest_wechat_article",
    "build_single_paper_deep_read_article",
    "build_topic_review_article",
    "build_wechat_60s_script",
    "build_wechat_articles",
    "clean_text_for_tts",
    "concat_mp3_segments",
    "convert_links_to_wechat_footnotes",
    "create_draft",
    "format_telegram_messages",
    "generate_academic_cover",
    "generate_daily_audio_bundle",
    "group_papers_by_topic",
    "markdown_to_wechat_html",
    "normalize_reading_status",
    "publish_wechat_drafts",
    "run_notebooklm_pipeline",
    "send_telegram_audio",
    "send_telegram_daily_report",
    "synthesize_segments_to_mp3",
    "upload_wechat_voice_material",
]
