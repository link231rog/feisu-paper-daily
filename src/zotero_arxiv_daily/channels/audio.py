"""Optional MP3 Audio & Podcast generator for Paper Daily.

Integrates open-source patterns from:
- rany2/edge-tts (Zero-config Microsoft Edge Neural TTS with multi-speaker Chinese/English voices)
- souzatharsis/podcastfy & Azzedde/paper_to_podcast (NotebookLM-style two-host academic dialogue & briefing scripts)
- travisvn/openai-edge-tts & OpenAI /v1/audio/speech (OpenAI-compatible TTS endpoint support)
- Pure-Python MPEG Audio Layer III frame concatenation (no host ffmpeg dependency required)
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
from datetime import date
import json
from pathlib import Path
import re
from typing import Any

from loguru import logger
import requests

from ..core.digest import format_rubric_summary_line
from ..core.textutil import extract_json
from ..protocol import Paper, TrendingItem

DEFAULT_HOST_VOICE_EDGE = "zh-CN-XiaoxiaoNeural"
DEFAULT_GUEST_VOICE_EDGE = "zh-CN-YunxiNeural"
DEFAULT_HOST_VOICE_OPENAI = "nova"
DEFAULT_GUEST_VOICE_OPENAI = "onyx"

# Standard MPEG-1 Audio Layer III frame constants (128 kbps, 44100 Hz, Joint Stereo)
# Header: 0xFF 0xFB 0x90 0x64 -> frame length = int(144 * 128000 / 44100) = 417 bytes (~26.12 ms/frame)
_MP3_FRAME_HEADER = b"\xff\xfb\x90\x64"
_MP3_FRAME_SIZE = 417
_MP3_FRAME_DURATION_MS = 26.122


@dataclass
class AudioSegment:
    """Single spoken turn in a podcast dialogue or solo academic briefing."""

    speaker: str  # "host" | "expert"
    voice: str
    text: str


@dataclass
class AudioBundle:
    """Generated MP3 audio artifacts and metadata for multi-channel delivery."""

    mp3_path: Path
    script_path: Path
    wechat_mp3_path: Path | None = None
    mode: str = "dialogue"
    engine: str = "edge-tts"
    duration_seconds: int = 0
    title: str = ""
    segments: list[AudioSegment] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mp3_path": str(self.mp3_path),
            "script_path": str(self.script_path),
            "wechat_mp3_path": str(self.wechat_mp3_path) if self.wechat_mp3_path else None,
            "mode": self.mode,
            "engine": self.engine,
            "duration_seconds": self.duration_seconds,
            "title": self.title,
            "segments": [asdict(s) for s in self.segments],
        }


def clean_text_for_tts(text: str) -> str:
    """Sanitize academic markdown, LaTeX equations, and URLs into natural spoken text."""
    if not text:
        return ""
    s = str(text)
    # 1. Strip display and inline LaTeX formulas
    s = re.sub(r"\$\$[\s\S]*?\$\$", "，相关公式详见原文，", s)
    s = re.sub(r"\$[^$\n]+\$", " ", s)
    s = re.sub(r"\\[a-zA-Z]+\{([^}]*)\}", r"\1", s)
    s = re.sub(r"\\[a-zA-Z]+", " ", s)
    # 2. Convert markdown links [label](url) -> label, and strip raw URLs
    s = re.sub(r"\[([^\]]+)\]\(https?://[^)\s]+\)", r"\1", s)
    s = re.sub(r"https?://\S+", "", s)
    # 3. Replace symbolic arrows and brackets with spoken equivalents
    s = s.replace("->", "，再到").replace("→", "，再到")
    s = re.sub(r"\[(?:精读必看|速览雷达|强烈推荐复用|值得参考|证据存疑/基线较弱|证据存疑)\]", "", s)
    s = re.sub(r"[`*_#~>|]", " ", s)
    # 4. Normalize whitespace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def estimate_speech_duration_seconds(segments: list[AudioSegment]) -> int:
    """Estimate spoken audio duration in seconds (~4.2 Chinese chars or ~2.8 English words per second)."""
    total_chars = sum(len(seg.text) for seg in segments)
    if total_chars <= 0:
        return 0
    return max(5, int(round(total_chars / 4.2)))


def _strip_id3v2_tag(mp3_bytes: bytes) -> bytes:
    """Strip leading ID3v2 metadata tag from an MP3 byte buffer if present."""
    if len(mp3_bytes) >= 10 and mp3_bytes[:3] == b"ID3":
        # Synchsafe 28-bit integer in bytes 6..9
        size_bytes = mp3_bytes[6:10]
        tag_size = (
            ((size_bytes[0] & 0x7F) << 21)
            | ((size_bytes[1] & 0x7F) << 14)
            | ((size_bytes[2] & 0x7F) << 7)
            | (size_bytes[3] & 0x7F)
        )
        total_header = 10 + tag_size
        if total_header < len(mp3_bytes):
            return mp3_bytes[total_header:]
    return mp3_bytes


def generate_mpeg1_layer3_silence(duration_ms: int = 320) -> bytes:
    """Generate valid MPEG-1 Audio Layer III silent frames without external tools."""
    num_frames = max(1, int(round(duration_ms / _MP3_FRAME_DURATION_MS)))
    payload = b"\x00" * (_MP3_FRAME_SIZE - len(_MP3_FRAME_HEADER))
    frame = _MP3_FRAME_HEADER + payload
    return frame * num_frames


def concat_mp3_segments(mp3_chunks: list[bytes], pause_ms: int = 320) -> bytes:
    """Concatenate multiple MP3 audio segments cleanly with silent inter-turn pauses."""
    valid_chunks = [c for c in mp3_chunks if c]
    if not valid_chunks:
        return generate_mpeg1_layer3_silence(1000)

    pause_bytes = generate_mpeg1_layer3_silence(pause_ms) if pause_ms > 0 else b""
    output = bytearray()
    for idx, chunk in enumerate(valid_chunks):
        cleaned = chunk if idx == 0 else _strip_id3v2_tag(chunk)
        output.extend(cleaned)
        if idx < len(valid_chunks) - 1 and pause_bytes:
            output.extend(pause_bytes)
    return bytes(output)


def _resolve_voices(audio_cfg: dict[str, Any] | None = None) -> tuple[str, str, str]:
    """Return (engine, host_voice, guest_voice) based on configuration."""
    cfg = audio_cfg or {}
    engine = str(cfg.get("engine") or "edge-tts").strip().lower()
    if engine == "openai":
        host_voice = str(cfg.get("openai_host_voice") or DEFAULT_HOST_VOICE_OPENAI).strip()
        guest_voice = str(cfg.get("openai_guest_voice") or DEFAULT_GUEST_VOICE_OPENAI).strip()
    else:
        engine = "edge-tts"
        host_voice = str(cfg.get("host_voice") or DEFAULT_HOST_VOICE_EDGE).strip()
        guest_voice = str(cfg.get("guest_voice") or DEFAULT_GUEST_VOICE_EDGE).strip()
    return engine, host_voice, guest_voice


def _build_template_dialogue_script(
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    host_voice: str = DEFAULT_HOST_VOICE_EDGE,
    guest_voice: str = DEFAULT_GUEST_VOICE_EDGE,
    max_papers: int = 5,
    report_date: date | None = None,
) -> list[AudioSegment]:
    """Build a NotebookLM-style two-speaker academic podcast script from structured paper digests."""
    today_str = (report_date or date.today()).isoformat()
    selected = papers[: max(1, max_papers)]
    deep_read = [p for p in selected if getattr(p, "recommendation_tier", "deep_read") == "deep_read"] or selected[:3]
    quick_radar = [p for p in selected if getattr(p, "recommendation_tier", None) == "quick_radar"]

    segments: list[AudioSegment] = [
        AudioSegment(
            speaker="host",
            voice=host_voice,
            text=clean_text_for_tts(
                f"欢迎收听今日论文研究播客，今天是 {today_str}。"
                f"我们从多源文献库中精选出 {len(selected)} 篇高价值论文，其中精读必看 {len(deep_read)} 篇。"
                "今天我们重点拆解这些工作的实质增量、实验严谨度以及开源复现价值。"
            ),
        )
    ]

    if question_briefs:
        top_q = question_briefs[0]
        q_text = clean_text_for_tts(str(top_q.get("question") or ""))
        q_ans = clean_text_for_tts(str(top_q.get("summary") or top_q.get("answer") or ""))
        q_gap = clean_text_for_tts(str(top_q.get("gap") or ""))
        if q_text:
            segments.append(
                AudioSegment(
                    speaker="host",
                    voice=host_voice,
                    text=clean_text_for_tts(f"首先来看我们持续追踪的核心科学问题：{q_text}，今天有哪些新的证据进展？"),
                )
            )
            ans_body = f"围绕这个问题，今日文献给出的核心结论是：{q_ans}。" if q_ans else "今日多篇新文献提供了直接实验证据。"
            if q_gap:
                ans_body += f"同时需要留意的盲区是：{q_gap}。"
            segments.append(
                AudioSegment(
                    speaker="expert",
                    voice=guest_voice,
                    text=clean_text_for_tts(ans_body),
                )
            )

    for idx, p in enumerate(deep_read, 1):
        title = clean_text_for_tts(p.title_with_venue())
        digest = getattr(p, "critical_digest", None) or {}
        delta = clean_text_for_tts(str(digest.get("delta") or p.tldr_zh or p.tldr or (p.abstract or "")[:160]))
        mech = digest.get("mechanism") or {}
        pipeline = clean_text_for_tts(str(mech.get("pipeline") or ""))
        ev = digest.get("evidence_and_cost") or {}
        metrics = clean_text_for_tts(str(ev.get("metrics") or ""))
        cost = clean_text_for_tts(str(ev.get("cost_and_limits") or ""))
        action = clean_text_for_tts(str(digest.get("action_or_check") or ""))
        rubric_line = clean_text_for_tts(format_rubric_summary_line(p))

        host_prompt = f"接下来看第 {idx} 篇精读论文：{title}。"
        if getattr(p, "matched_anchor_title", None):
            host_prompt += f"这篇工作与我们文献库中的《{clean_text_for_tts(p.matched_anchor_title)}》高度相关，它做出了什么实质突破？"
        else:
            host_prompt += "它相比现有基线解决了什么痛点？"
        segments.append(AudioSegment(speaker="host", voice=host_voice, text=clean_text_for_tts(host_prompt)))

        expert_reply = f"这篇工作的核心增量在于：{delta}。"
        if pipeline and pipeline != "N/A":
            expert_reply += f"在方法链路上，它通过 {pipeline} 实现。"
        if metrics and metrics != "N/A":
            expert_reply += f"实验表现方面，{metrics}。"
        if cost and cost != "N/A":
            expert_reply += f"不过要注意它的算力代价与边界：{cost}。"
        if rubric_line:
            expert_reply += f"综合四维量化评估，{rubric_line}。"
        if getattr(p, "code_url", None):
            expert_reply += "作者已经同步开源了代码仓库，复现友好度很高。"
        if action and action != "N/A":
            expert_reply += f"建议后续行动：{action}。"
        segments.append(AudioSegment(speaker="expert", voice=guest_voice, text=clean_text_for_tts(expert_reply)))

    if quick_radar:
        radar_titles = "；".join(
            f"《{clean_text_for_tts(p.title)}》，核心点是{clean_text_for_tts(p.tldr_zh or p.tldr or (p.abstract or '')[:80])}"
            for p in quick_radar[:3]
        )
        segments.append(
            AudioSegment(
                speaker="host",
                voice=host_voice,
                text=clean_text_for_tts(
                    f"此外，今日速览雷达还收录了 {len(quick_radar)} 篇候选工作，包括：{radar_titles}。"
                ),
            )
        )

    if trending_items:
        top_trend = trending_items[0]
        segments.append(
            AudioSegment(
                speaker="expert",
                voice=guest_voice,
                text=clean_text_for_tts(
                    f"最后补充一条开源与社区前沿动态：{top_trend.title}，{top_trend.summary_zh or top_trend.description or ''}。"
                ),
            )
        )

    segments.append(
        AudioSegment(
            speaker="host",
            voice=host_voice,
            text="以上就是今日论文研究播客的全部内容，详细公式、图表与原文链接请查看今日完整日报。我们明天见。",
        )
    )
    return segments


def _build_template_briefing_script(
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    host_voice: str = DEFAULT_HOST_VOICE_EDGE,
    max_papers: int = 5,
    report_date: date | None = None,
) -> list[AudioSegment]:
    """Build a high-density solo academic morning briefing script."""
    today_str = (report_date or date.today()).isoformat()
    selected = papers[: max(1, max_papers)]
    segments: list[AudioSegment] = [
        AudioSegment(
            speaker="host",
            voice=host_voice,
            text=clean_text_for_tts(
                f"这里是论文研究日报语音早报，今天是 {today_str}，为您快速串讲今日精选的 {len(selected)} 篇前沿论文。"
            ),
        )
    ]

    if question_briefs:
        q0 = question_briefs[0]
        q_title = clean_text_for_tts(str(q0.get("question") or ""))
        q_ans = clean_text_for_tts(str(q0.get("summary") or q0.get("answer") or ""))
        if q_title and q_ans:
            segments.append(
                AudioSegment(
                    speaker="host",
                    voice=host_voice,
                    text=clean_text_for_tts(f"问题追踪速递：针对「{q_title}」，今日核心进展为：{q_ans}。"),
                )
            )

    for idx, p in enumerate(selected, 1):
        title = clean_text_for_tts(p.title_with_venue())
        digest = getattr(p, "critical_digest", None) or {}
        delta = clean_text_for_tts(str(digest.get("delta") or p.tldr_zh or p.tldr or (p.abstract or "")[:140]))
        ev = digest.get("evidence_and_cost") or {}
        metrics = clean_text_for_tts(str(ev.get("metrics") or ""))
        rubric_line = clean_text_for_tts(format_rubric_summary_line(p))

        item_text = f"第 {idx} 篇，{title}。核心增量：{delta}。"
        if metrics and metrics != "N/A":
            item_text += f"关键实验指标：{metrics}。"
        if rubric_line:
            item_text += f"{rubric_line}。"
        if getattr(p, "code_url", None):
            item_text += "该论文已开源代码。"
        segments.append(AudioSegment(speaker="host", voice=host_voice, text=clean_text_for_tts(item_text)))

    if trending_items:
        t0 = trending_items[0]
        segments.append(
            AudioSegment(
                speaker="host",
                voice=host_voice,
                text=clean_text_for_tts(f"开源社区热点关注：{t0.title}，{t0.summary_zh or t0.description or ''}。"),
            )
        )

    segments.append(
        AudioSegment(
            speaker="host",
            voice=host_voice,
            text="今日学术早报播报完毕，祝您科研顺利。",
        )
    )
    return segments


def build_wechat_60s_script(
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    host_voice: str = DEFAULT_HOST_VOICE_EDGE,
    report_date: date | None = None,
) -> list[AudioSegment]:
    """Build a strict <= 210 Chinese character (~45s, <2MB) voice guide for WeChat Official Account."""
    today_str = (report_date or date.today()).strftime("%m月%d日")
    if not papers:
        text = f"欢迎收听{today_str}论文研究日报一分钟语音导读。今日暂无新增高分命中论文，请查看正文问题追踪与历史回顾。"
        return [AudioSegment(speaker="host", voice=host_voice, text=text)]

    top_papers = papers[:2]
    highlights: list[str] = []
    for idx, p in enumerate(top_papers, 1):
        digest = getattr(p, "critical_digest", None) or {}
        delta = clean_text_for_tts(str(digest.get("delta") or p.tldr_zh or p.tldr or p.title))[:42]
        short_title = clean_text_for_tts(p.title)[:24]
        highlights.append(f"第{idx}篇《{short_title}》聚焦{delta}")

    joined = "；".join(highlights)
    q_part = ""
    if question_briefs and question_briefs[0].get("question"):
        q_short = clean_text_for_tts(str(question_briefs[0]["question"]))[:20]
        q_part = f"并更新了「{q_short}」的跨文献证据。"

    summary = (
        f"{today_str}论文日报语音导读：今日精选{len(papers)}篇文献。"
        f"重点关注：{joined}。{q_part}详细公式与基线对比请下拉阅读正文。"
    )
    return [AudioSegment(speaker="host", voice=host_voice, text=clean_text_for_tts(summary)[:210])]


def build_audio_script(
    papers: list[Paper],
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    mode: str = "dialogue",
    audio_cfg: dict[str, Any] | None = None,
    router: Any = None,
    report_date: date | None = None,
) -> list[AudioSegment]:
    """Build structured audio segments in 'dialogue' (NotebookLM-style), 'briefing', or 'wechat_60s' mode."""
    cfg = audio_cfg or {}
    _, host_voice, guest_voice = _resolve_voices(cfg)
    max_papers = int(cfg.get("max_papers") or 5)
    norm_mode = str(mode or cfg.get("mode") or "dialogue").strip().lower()

    if norm_mode == "wechat_60s":
        return build_wechat_60s_script(
            papers,
            question_briefs=question_briefs,
            host_voice=host_voice,
            report_date=report_date,
        )

    use_llm = str(cfg.get("use_llm_script", True)).strip().lower() in ("true", "1", "yes")
    if use_llm and router is not None and getattr(router, "available", False) and papers:
        try:
            selected = papers[: max(1, max_papers)]
            paper_Contexts = []
            for i, p in enumerate(selected, 1):
                cd = getattr(p, "critical_digest", None) or {}
                paper_Contexts.append(
                    {
                        "index": i,
                        "title": p.title_with_venue(),
                        "delta": cd.get("delta") or p.tldr_zh or p.tldr or (p.abstract or "")[:200],
                        "metrics": (cd.get("evidence_and_cost") or {}).get("metrics") or "",
                        "cost": (cd.get("evidence_and_cost") or {}).get("cost_and_limits") or "",
                        "rubric": format_rubric_summary_line(p),
                        "has_code": bool(getattr(p, "code_url", None)),
                    }
                )
            if norm_mode == "briefing":
                prompt = (
                    "请将以下今日精选学术论文与问题进展改写为单人高密度学术早报播音稿（JSON 格式）。\n"
                    "要求：纯口语化中文，严禁包含 LaTeX 符号、Markdown 标记或 URL 链接，直奔核心增量与实验指标。\n"
                    '输出格式：{"segments": [{"speaker": "host", "text": "..."}]}\n'
                    f"输入数据：{json.dumps({'papers': paper_Contexts, 'briefs': (question_briefs or [])[:2]}, ensure_ascii=False)}"
                )
            else:
                prompt = (
                    "请参考 NotebookLM 双人学术播客风格，将以下今日精选论文改写为「主持人(host)」与「客座学者(expert)」交替对谈的播音稿（JSON 格式）。\n"
                    "要求：主持人负责抛出研究痛点与批判性追问，客座学者负责拆解实质增量（Delta）、实验涨点与算力边界。纯口语化中文，严禁包含 LaTeX 公式或 Markdown 符号。\n"
                    '输出格式：{"segments": [{"speaker": "host", "text": "..."}, {"speaker": "expert", "text": "..."}]}\n'
                    f"输入数据：{json.dumps({'papers': paper_Contexts, 'briefs': (question_briefs or [])[:2]}, ensure_ascii=False)}"
                )
            raw_resp = (
                router.complete(task="audio_script", prompt=prompt, max_tokens=2000)
                if hasattr(router, "complete")
                else router.chat([{"role": "user", "content": prompt}], max_tokens=2000)
            )
            parsed = extract_json(raw_resp, {})
            raw_segs = parsed.get("segments") if isinstance(parsed, dict) else None
            if isinstance(raw_segs, list) and len(raw_segs) >= 2:
                out_segs: list[AudioSegment] = []
                for item in raw_segs:
                    if not isinstance(item, dict):
                        continue
                    spk = "expert" if str(item.get("speaker") or "").lower() in ("expert", "guest") else "host"
                    txt = clean_text_for_tts(str(item.get("text") or ""))
                    if txt:
                        out_segs.append(
                            AudioSegment(
                                speaker=spk,
                                voice=guest_voice if (spk == "expert" and norm_mode != "briefing") else host_voice,
                                text=txt,
                            )
                        )
                if out_segs:
                    return out_segs
        except Exception as exc:
            logger.debug(f"LLM audio script generation fallback to deterministic template: {exc}")

    if norm_mode == "briefing":
        return _build_template_briefing_script(
            papers,
            question_briefs=question_briefs,
            trending_items=trending_items,
            host_voice=host_voice,
            max_papers=max_papers,
            report_date=report_date,
        )
    return _build_template_dialogue_script(
        papers,
        question_briefs=question_briefs,
        trending_items=trending_items,
        host_voice=host_voice,
        guest_voice=guest_voice,
        max_papers=max_papers,
        report_date=report_date,
    )


async def _edge_tts_synthesize_turn(text: str, voice: str, rate: str = "+5%") -> bytes:
    """Synthesize a single turn to MP3 bytes via edge-tts."""
    import edge_tts  # type: ignore[import-not-found]

    communicate = edge_tts.Communicate(text=text, voice=voice, rate=rate)
    audio_Buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio" and chunk.get("data"):
            audio_Buffer.extend(chunk["data"])
    return bytes(audio_Buffer)


def _synthesize_with_edge_tts(segments: list[AudioSegment], rate: str = "+5%") -> list[bytes]:
    """Run edge-tts across all segments in an event loop and return raw MP3 byte chunks."""
    async def _run_all() -> list[bytes]:
        chunks: list[bytes] = []
        for seg in segments:
            if not seg.text.strip():
                continue
            chunk = await _edge_tts_synthesize_turn(seg.text, seg.voice, rate=rate)
            if chunk:
                chunks.append(chunk)
        return chunks

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(lambda: asyncio.run(_run_all())).result(timeout=180)
    return asyncio.run(_run_all())


def _synthesize_with_openai_tts(
    segments: list[AudioSegment],
    audio_cfg: dict[str, Any],
    llm_cfg: dict[str, Any] | None = None,
) -> list[bytes]:
    """Synthesize segments using an OpenAI-compatible /v1/audio/speech endpoint (including openai-edge-tts)."""
    api_key = str(
        audio_cfg.get("openai_api_key")
        or (llm_cfg or {}).get("api", {}).get("key")
        or "sk-edge-tts-free"
    ).strip()
    base_url = str(
        audio_cfg.get("openai_base_url")
        or (llm_cfg or {}).get("api", {}).get("base_url")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = str(audio_cfg.get("openai_model") or "tts-1").strip()
    speed = float(audio_cfg.get("openai_speed") or 1.05)

    endpoint = f"{base_url}/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    chunks: list[bytes] = []
    for seg in segments:
        if not seg.text.strip():
            continue
        payload = {
            "model": model,
            "input": seg.text,
            "voice": seg.voice,
            "response_format": "mp3",
            "speed": speed,
        }
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        if resp.content:
            chunks.append(resp.content)
    return chunks


def synthesize_segments_to_mp3(
    segments: list[AudioSegment],
    output_path: str | Path,
    audio_cfg: dict[str, Any] | None = None,
    llm_cfg: dict[str, Any] | None = None,
) -> Path:
    """Synthesize dialogue or briefing segments into a single concatenated MP3 file."""
    cfg = audio_cfg or {}
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    engine, _, _ = _resolve_voices(cfg)
    rate = str(cfg.get("speech_rate") or "+5%").strip()
    pause_ms = int(cfg.get("turn_pause_ms") or 320)

    mp3_chunks: list[bytes] = []
    if engine == "openai":
        try:
            mp3_chunks = _synthesize_with_openai_tts(segments, cfg, llm_cfg=llm_cfg)
        except Exception as exc:
            logger.warning(f"OpenAI TTS synthesis failed ({exc}); falling back to edge-tts.")
            engine = "edge-tts"

    if engine == "edge-tts" and not mp3_chunks:
        try:
            mp3_chunks = _synthesize_with_edge_tts(segments, rate=rate)
        except Exception as exc:
            logger.warning(f"edge-tts synthesis unavailable or offline ({exc}); writing deterministic MPEG-1 Layer 3 fallback stream.")

    if not mp3_chunks:
        # Offline / sandboxed CI fallback: generate valid MPEG-1 Layer 3 frames proportional to script length
        est_sec = min(15, max(2, estimate_speech_duration_seconds(segments)))
        mp3_chunks = [generate_mpeg1_layer3_silence(est_sec * 1000)]

    combined = concat_mp3_segments(mp3_chunks, pause_ms=pause_ms)
    out.write_bytes(combined)
    return out


def generate_daily_audio_bundle(
    papers: list[Paper],
    config: Any,
    question_briefs: list[dict[str, Any]] | None = None,
    trending_items: list[TrendingItem] | None = None,
    router: Any = None,
    report_date: date | None = None,
) -> AudioBundle:
    """Generate the daily MP3 audio podcast/briefing, script archive, and optional WeChat 60s voice material."""
    report_date = report_date or date.today()
    audio_cfg = dict(config.get("audio") or {}) if hasattr(config, "get") else {}
    llm_cfg = dict(config.get("llm") or {}) if hasattr(config, "get") else {}

    mode = str(audio_cfg.get("mode") or "dialogue").strip().lower()
    engine, _, _ = _resolve_voices(audio_cfg)
    output_dir = Path(str(audio_cfg.get("output_dir") or "data/audio"))
    output_dir.mkdir(parents=True, exist_ok=True)

    stem = f"daily_podcast_{report_date.isoformat()}"
    mp3_path = output_dir / f"{stem}.mp3"
    script_path = output_dir / f"{stem}.script.json"

    segments = build_audio_script(
        papers,
        question_briefs=question_briefs,
        trending_items=trending_items,
        mode=mode,
        audio_cfg=audio_cfg,
        router=router,
        report_date=report_date,
    )
    synthesize_segments_to_mp3(segments, mp3_path, audio_cfg=audio_cfg, llm_cfg=llm_cfg)
    duration_sec = estimate_speech_duration_seconds(segments)

    wechat_mp3_path: Path | None = None
    upload_wechat = str(audio_cfg.get("upload_wechat_voice", True)).strip().lower() in ("true", "1", "yes")
    if upload_wechat:
        wx_segments = build_wechat_60s_script(
            papers,
            question_briefs=question_briefs,
            host_voice=_resolve_voices(audio_cfg)[1],
            report_date=report_date,
        )
        wx_path = output_dir / f"{stem}_wechat60s.mp3"
        synthesize_segments_to_mp3(wx_segments, wx_path, audio_cfg=audio_cfg, llm_cfg=llm_cfg)
        wechat_mp3_path = wx_path

    mode_label = "双人学术播客" if mode == "dialogue" else "学术语音早报"
    title = f"Paper Daily {mode_label} | {report_date.isoformat()}"

    bundle = AudioBundle(
        mp3_path=mp3_path,
        script_path=script_path,
        wechat_mp3_path=wechat_mp3_path,
        mode=mode,
        engine=engine,
        duration_seconds=duration_sec,
        title=title,
        segments=segments,
    )
    script_path.write_text(
        json.dumps(bundle.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        f"Generated daily audio bundle ({mode}, engine={engine}, ~{duration_sec}s): {mp3_path}"
    )
    return bundle
