"""Academic paper translation module with LaTeX formula preservation and bilingual layout."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import time
from typing import Any, Optional, Union
from loguru import logger
from omegaconf import DictConfig
import requests

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None  # type: ignore[assignment,misc]


def protect_latex_and_tokens(text: str) -> tuple[str, dict[str, str]]:
    """Protects LaTeX formulas and code spans from translation via unique placeholders."""
    placeholders: dict[str, str] = {}

    # 1. Display math: $$...$$
    def _repl_disp(m: re.Match) -> str:
        key = f"__XDISPMATH{len(placeholders)}X__"
        placeholders[key] = m.group(0)
        return key

    text = re.sub(r"\$\$[\s\S]*?\$\$", _repl_disp, text)

    # 2. Inline math: $...$
    def _repl_inl(m: re.Match) -> str:
        key = f"__XINLMATH{len(placeholders)}X__"
        placeholders[key] = m.group(0)
        return key

    text = re.sub(r"\$[^$\n]+?\$", _repl_inl, text)

    # 3. Inline code spans: `...`
    def _repl_code(m: re.Match) -> str:
        key = f"__XCODESPAN{len(placeholders)}X__"
        placeholders[key] = m.group(0)
        return key

    text = re.sub(r"`[^`\n]+?`", _repl_code, text)

    return text, placeholders


def restore_latex_and_tokens(translated_text: str, placeholders: dict[str, str]) -> str:
    """Restores protected LaTeX formulas and code spans into the translated text."""
    res = translated_text
    for key, original in placeholders.items():
        if key in res:
            res = res.replace(key, original)
        else:
            loose_pattern = re.escape(key).replace("_", r"\s*_\s*")
            res = re.sub(loose_pattern, lambda m, orig=original: orig, res, flags=re.IGNORECASE)
    return res.strip()


class AcademicTranslator:
    """Translates academic paper text into Chinese while strictly preserving LaTeX formulas and structure."""

    def __init__(self, config: Optional[Union[DictConfig, dict[str, Any]]] = None):
        cfg = config or {}
        if isinstance(cfg, DictConfig):
            cfg = dict(cfg)

        self.enabled = bool(cfg.get("enabled", True))
        self.engine = str(cfg.get("engine") or os.getenv("TRANSLATION_ENGINE", "web")).strip().lower()
        self.concurrency = int(cfg.get("concurrency") or os.getenv("TRANSLATION_CONCURRENCY", 5))

        # LLM mode parameters
        self.api_base = cfg.get("api_base") or os.getenv("TRANSLATION_API_BASE", "https://integrate.api.nvidia.com/v1")
        self.api_key = cfg.get("api_key") or os.getenv("TRANSLATION_API_KEY", "")
        self.backup_api_key = cfg.get("backup_api_key") or os.getenv("TRANSLATION_BACKUP_API_KEY", "")
        self.model = cfg.get("model") or os.getenv("TRANSLATION_MODEL", "z-ai/glm-5.3-flash")
        self.backup_model = cfg.get("backup_model") or os.getenv("TRANSLATION_BACKUP_MODEL", "")
        self.models = [self.model]
        if self.backup_model and self.backup_model != self.model:
            self.models.append(self.backup_model)
        self.layout = cfg.get("layout") or os.getenv("TRANSLATION_LAYOUT", "quote")
        self.batch_size = int(cfg.get("batch_size") or os.getenv("TRANSLATION_BATCH_SIZE", 3))

        self.current_key = self.api_key
        self._init_client()
        self._failures = 0
        self._disabled = False

        # Web translation session and token caches
        self._http_session = requests.Session()
        self._http_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
        }
        self._bing_session_time = 0.0
        self._bing_tk: dict[str, str] | None = None
        self._bing_ig_iid: dict[str, str] | None = None
        self._proxy = self._resolve_proxy()

    def _resolve_proxy(self) -> dict[str, str] | None:
        """Auto-discovers proxy for Google web translate fallback when running locally."""
        env_proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or os.getenv("ALL_PROXY")
        if env_proxy:
            return {"http": env_proxy, "https": env_proxy}
        # Check standard local proxy ports (7897, 7890)
        for port in (7897, 7890):
            try:
                import socket
                with socket.create_connection(("127.0.0.1", port), timeout=0.15):
                    return {"http": f"http://127.0.0.1:{port}", "https": f"http://127.0.0.1:{port}"}
            except Exception:
                continue
        return None

    def _init_client(self) -> None:
        if self.current_key and OpenAI is not None:
            self.client = OpenAI(base_url=self.api_base, api_key=self.current_key)
        else:
            self.client = None

    def _switch_to_backup_key(self) -> bool:
        if self.backup_api_key and self.current_key != self.backup_api_key:
            logger.warning("Switching translator to backup API key...")
            self.current_key = self.backup_api_key
            self._init_client()
            return True
        return False

    def _record_failure(self) -> None:
        self._failures += 1
        if self._failures >= 3 and not self._disabled:
            self._disabled = True
            logger.error("Translation endpoint keeps failing; keeping source text for the rest of this run")

    @staticmethod
    def _is_rate_limit(exc: Exception) -> bool:
        low = str(exc).lower()
        return any(m in low for m in ("429", "concurrency limit", "rate limit", "too many requests"))

    def _translate_bing(self, text: str) -> Optional[str]:
        """Translates via Bing Web (cn.bing.com or bing.com) with token reuse."""
        try:
            now = time.time()
            if now - self._bing_session_time > 1200 or not self._bing_tk or not self._bing_ig_iid:
                r = self._http_session.get("https://cn.bing.com/Translator", headers=self._http_headers, timeout=5)
                html = r.text
                ig = re.search(r'IG:"([^"]+)"', html)
                iid = re.search(r'data-iid=\"([^\"]+)\"', html)
                helper = re.search(r'params_AbusePreventionHelper\s*=\s*\[([^\]]+)\]', html)
                if ig and iid and helper:
                    items = [x.strip().strip('"') for x in helper.group(1).split(",")]
                    self._bing_tk = {"key": items[0], "token": items[1]}
                    self._bing_ig_iid = {"ig": ig.group(1), "iid": iid.group(1)}
                    self._bing_session_time = now

            if not self._bing_tk or not self._bing_ig_iid:
                return None

            url = f"https://cn.bing.com/ttranslatev3?isVertical=1&&IG={self._bing_ig_iid['ig']}&IID={self._bing_ig_iid['iid']}"
            data = {
                "text": text,
                "fromLang": "en",
                "to": "zh-Hans",
                "key": self._bing_tk["key"],
                "token": self._bing_tk["token"],
            }
            resp = self._http_session.post(url, data=data, headers=self._http_headers, timeout=6)
            if resp.status_code == 200:
                body = resp.json()
                if body and isinstance(body, list) and "translations" in body[0]:
                    return body[0]["translations"][0]["text"]
        except Exception as exc:
            logger.debug(f"Bing web translation transient error: {exc}")
        return None

    def _translate_google(self, text: str) -> Optional[str]:
        """Translates via Google Web API (works globally and in GitHub Actions)."""
        url = "https://translate.google.com/translate_a/single"
        params = {
            "client": "dict-chrome-ex",
            "sl": "auto",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        }
        try:
            req_kwargs: dict[str, Any] = {"params": params, "headers": self._http_headers, "timeout": 6}
            if self._proxy:
                req_kwargs["proxies"] = self._proxy
            resp = self._http_session.get(url, **req_kwargs)
            if resp.status_code == 200:
                data = resp.json()
                return "".join([item[0] for item in data[0] if item and item[0]])
        except Exception as exc:
            logger.debug(f"Google web translation transient error: {exc}")
        return None

    def translate_paragraph(self, text: str) -> str:
        """Translates a single paragraph with formula protection and engine fallback."""
        if not text or not text.strip():
            return ""

        protected_text, placeholders = protect_latex_and_tokens(text)

        translated: Optional[str] = None
        if self.engine in ("web", "auto"):
            translated = self._translate_bing(protected_text)
            if not translated:
                translated = self._translate_google(protected_text)
        elif self.engine == "bing":
            translated = self._translate_bing(protected_text)
        elif self.engine == "google":
            translated = self._translate_google(protected_text)
        elif self.engine == "llm":
            return self.translate_single(text)

        if not translated:
            if self.client and not self._disabled:
                return self.translate_single(text)
            return text

        return restore_latex_and_tokens(translated, placeholders)

    def translate_batch(self, paragraphs: list[str]) -> list[str]:
        """Translates a batch of English paragraphs using LLM (legacy mode)."""
        if not paragraphs or not self.client or self._disabled:
            return [""] * len(paragraphs)

        batch_prompts = []
        for idx, p in enumerate(paragraphs, 1):
            batch_prompts.append(f"[P{idx}] {p}")
        user_content = "\n\n".join(batch_prompts)

        system_prompt = (
            "You are an expert academic translator specializing in computer science and AI. "
            "Translate each numbered paragraph into formal, publication-ready Chinese. "
            "CRITICAL RULES:\n"
            "1. Strictly PRESERVE paragraph tags [P1], [P2], etc., matching each translated paragraph.\n"
            "2. Strictly PRESERVE all LaTeX formulas (like $...$, $$...$$) and mathematical variables untouched.\n"
            "3. Strictly PRESERVE all citations [(...)] and footnotes [注: ...] untouched.\n"
            "4. Output ONLY the translated paragraphs matching the tags. No notes, no conversational remarks."
        )

        for attempt in range(2):
            try:
                extra_body = {}
                if len(self.models) > 1:
                    extra_body["models"] = self.models
                create_kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 4096,
                    "temperature": 0.1,
                    "timeout": 90,
                }
                if extra_body:
                    create_kwargs["extra_body"] = extra_body

                resp = self.client.chat.completions.create(**create_kwargs)
                self._failures = 0
                raw_out = resp.choices[0].message.content or ""
                translations = self._parse_batch_response(raw_out, len(paragraphs))
                if any(t for t in translations):
                    return translations
            except Exception as exc:
                logger.warning(f"Translation batch attempt {attempt + 1} failed: {exc}")
                if self._is_rate_limit(exc):
                    time.sleep(2 + attempt * 3)
                    continue
                self._record_failure()
                if "403" in str(exc) and self._switch_to_backup_key():
                    continue
                time.sleep(2)

        # Fallback: translate one by one
        logger.info("Falling back to single-paragraph translation...")
        return [self.translate_single(p) for p in paragraphs]

    def translate_single(self, text: str) -> str:
        """Translates a single English paragraph into Chinese using LLM."""
        if not text.strip() or not self.client or self._disabled:
            return ""

        system_prompt = (
            "You are an expert academic translator in computer science and AI. "
            "Translate the given English text into formal, publication-ready Chinese. "
            "CRITICAL RULES:\n"
            "1. Strictly PRESERVE all LaTeX formulas (e.g. $...$, $$...$$) and mathematical variables untouched.\n"
            "2. Strictly PRESERVE all citations [(...)] and footnotes [注: ...] untouched.\n"
            "3. Output ONLY the translated Chinese text with no notes, no commentary, no markdown prefixes like '译文：'."
        )

        for attempt in range(2):
            try:
                extra_body = {}
                if len(self.models) > 1:
                    extra_body["models"] = self.models
                create_kwargs: dict[str, Any] = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    "max_tokens": 1500,
                    "temperature": 0.1,
                    "timeout": 60,
                }
                if extra_body:
                    create_kwargs["extra_body"] = extra_body

                resp = self.client.chat.completions.create(**create_kwargs)
                self._failures = 0
                out = (resp.choices[0].message.content or "").strip()
                out = re.sub(r"^\*{0,2}译文[：:]\*{0,2}\s*", "", out)
                return out
            except Exception as exc:
                logger.warning(f"Translation single attempt {attempt + 1} failed: {exc}")
                if self._is_rate_limit(exc):
                    time.sleep(2 + attempt * 3)
                    continue
                self._record_failure()
                if "403" in str(exc) and self._switch_to_backup_key():
                    continue
                time.sleep(1)
        return ""

    def _parse_batch_response(self, raw_output: str, expected_count: int) -> list[str]:
        translations = [""] * expected_count
        parts = re.split(r"\[P(\d+)\]", raw_output)
        if len(parts) >= 3:
            for i in range(1, len(parts), 2):
                idx = int(parts[i]) - 1
                val = parts[i + 1].strip()
                val = re.sub(r"^\*{0,2}译文[：:]\*{0,2}\s*", "", val)
                if "\n\n**术语说明" in val or "\n\n术语说明" in val:
                    val = re.split(r"\n\n\*{0,2}术语说明", val)[0].strip()
                if 0 <= idx < expected_count:
                    translations[idx] = val
        return translations

    def make_bilingual_markdown(self, markdown_text: str) -> str:
        """Transforms paper full text into bilingual English + Chinese layout with fast concurrency and deadline guard."""
        if not self.enabled or not markdown_text:
            return markdown_text

        blocks = self.split_into_semantic_blocks(markdown_text)
        text_indices = [
            i for i, (content, btype) in enumerate(blocks)
            if btype == "text" and len(content.strip()) > 20
        ]

        if not text_indices:
            return markdown_text

        logger.info(
            f"Translating {len(text_indices)} text paragraphs into bilingual layout "
            f"(engine: {self.engine}, concurrency: {self.concurrency})..."
        )

        translated_map: dict[int, str] = {}

        if self.engine in ("web", "auto", "bing", "google"):
            # Multi-threaded web translation with overall deadline guard
            def _worker(idx: int) -> tuple[int, str]:
                content = blocks[idx][0]
                return idx, self.translate_paragraph(content)

            max_workers = min(6, max(2, self.concurrency))
            deadline = time.time() + 120.0  # Max 2 minutes for the entire full text

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = {pool.submit(_worker, idx): idx for idx in text_indices}
                completed_count = 0
                for f in as_completed(futures):
                    if time.time() > deadline:
                        logger.warning("Translation reached overall deadline (120s); finishing with partial translations.")
                        break
                    try:
                        idx, res = f.result(timeout=10.0)
                        if res and res != blocks[idx][0]:
                            translated_map[idx] = res
                            completed_count += 1
                    except Exception as err:
                        logger.debug(f"Paragraph translation worker error: {err}")

            logger.info(f"Finished bilingual translation: {completed_count}/{len(text_indices)} paragraphs translated.")
        else:
            # Legacy LLM batch translation
            batch_size = max(1, self.batch_size)
            for b_idx in range(0, len(text_indices), batch_size):
                chunk_indices = text_indices[b_idx : b_idx + batch_size]
                chunk_texts = [blocks[idx][0] for idx in chunk_indices]
                chunk_translations = self.translate_batch(chunk_texts)
                for idx, trans in zip(chunk_indices, chunk_translations):
                    translated_map[idx] = trans
                logger.info(f"Translated batch {b_idx // batch_size + 1}/{(len(text_indices) + batch_size - 1) // batch_size}")

        out_blocks = []
        for i, (content, btype) in enumerate(blocks):
            if btype == "text" and i in translated_map and translated_map[i]:
                ch_text = translated_map[i]
                if self.layout == "quote":
                    quote_lines = [f"> {line}" for line in ch_text.splitlines() if line.strip()]
                    ch_block = "\n".join(quote_lines)
                    out_blocks.append(f"{content}\n\n{ch_block}")
                else:
                    out_blocks.append(f"{content}\n\n{ch_text}")
            else:
                out_blocks.append(content)

        return "\n\n".join(out_blocks)

    @staticmethod
    def split_into_semantic_blocks(md_text: str) -> list[tuple[str, str]]:
        """Splits markdown into headings, code, math, tables, images, and text."""
        lines = md_text.splitlines()
        blocks = []
        curr: list[str] = []
        in_code = False
        code_lines: list[str] = []
        in_math = False
        math_lines: list[str] = []
        in_table = False
        table_lines: list[str] = []

        for line in lines:
            s = line.strip()

            # 1. Code blocks ```
            if s.startswith("```"):
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                if in_table:
                    blocks.append(("\n".join(table_lines), "table"))
                    table_lines = []
                    in_table = False
                in_code = not in_code
                code_lines.append(line)
                if not in_code:
                    blocks.append(("\n".join(code_lines), "code"))
                    code_lines = []
                continue
            if in_code:
                code_lines.append(line)
                continue

            # 2. Block equations $$ ... $$
            if s.startswith("$$"):
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                if in_table:
                    blocks.append(("\n".join(table_lines), "table"))
                    table_lines = []
                    in_table = False
                if len(s) > 2 and s.endswith("$$") and s != "$$":
                    blocks.append((line, "math"))
                    continue
                in_math = not in_math
                math_lines.append(line)
                if not in_math:
                    blocks.append(("\n".join(math_lines), "math"))
                    math_lines = []
                continue
            if in_math:
                math_lines.append(line)
                continue

            # 3. Tables | ... |
            if s.startswith("|") and s.endswith("|"):
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                in_table = True
                table_lines.append(line)
                continue
            elif in_table:
                blocks.append(("\n".join(table_lines), "table"))
                table_lines = []
                in_table = False

            # 4. Headings
            if s.startswith("#"):
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                blocks.append((line, "heading"))
                continue

            # 5. Images
            if s.startswith("![") and "](" in s:
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                blocks.append((line, "image"))
                continue

            # 6. Blank line paragraph boundary
            if not s:
                if curr:
                    blocks.append(("\n".join(curr), "text"))
                    curr = []
                continue

            curr.append(line)

        if in_table and table_lines:
            blocks.append(("\n".join(table_lines), "table"))
        if curr:
            blocks.append(("\n".join(curr), "text"))
        return blocks
