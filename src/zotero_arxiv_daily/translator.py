"""Academic paper translation module with LaTeX formula preservation and bilingual layout."""

import os
import re
import time
from typing import Any, Optional, Union
from loguru import logger
from omegaconf import DictConfig
from openai import OpenAI


class AcademicTranslator:
    """Translates academic paper text into Chinese while strictly preserving LaTeX formulas and structure."""

    def __init__(self, config: Optional[Union[DictConfig, dict[str, Any]]] = None):
        cfg = config or {}
        if isinstance(cfg, DictConfig):
            cfg = dict(cfg)

        self.enabled = bool(cfg.get("enabled", True))
        self.api_base = cfg.get("api_base") or os.getenv("TRANSLATION_API_BASE", "https://integrate.api.nvidia.com/v1")
        self.api_key = cfg.get("api_key") or os.getenv("TRANSLATION_API_KEY", "")
        self.backup_api_key = cfg.get("backup_api_key") or os.getenv("TRANSLATION_BACKUP_API_KEY", "")
        self.model = cfg.get("model") or os.getenv("TRANSLATION_MODEL", "z-ai/glm-5.3-flash")
        self.layout = cfg.get("layout") or os.getenv("TRANSLATION_LAYOUT", "quote")
        self.batch_size = int(cfg.get("batch_size") or os.getenv("TRANSLATION_BATCH_SIZE", 3))

        self.current_key = self.api_key
        self._init_client()

    def _init_client(self) -> None:
        if self.current_key:
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

    def translate_batch(self, paragraphs: list[str]) -> list[str]:
        """Translates a batch of English paragraphs into academic Chinese using GLM-5.3."""
        if not paragraphs or not self.client:
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
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    max_tokens=4096,
                    temperature=0.1,
                    timeout=180,
                )
                raw_out = resp.choices[0].message.content or ""
                translations = self._parse_batch_response(raw_out, len(paragraphs))
                if any(t for t in translations):
                    return translations
            except Exception as exc:
                logger.warning(f"Translation batch attempt {attempt + 1} failed: {exc}")
                if "403" in str(exc) or "429" in str(exc):
                    if self._switch_to_backup_key():
                        continue
                time.sleep(2)

        # Fallback: translate one by one
        logger.info("Falling back to single-paragraph translation...")
        results = []
        for p in paragraphs:
            results.append(self.translate_single(p))
        return results

    def translate_single(self, text: str) -> str:
        """Translates a single English paragraph into Chinese."""
        if not text.strip() or not self.client:
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
                resp = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": text},
                    ],
                    max_tokens=4096,
                    temperature=0.1,
                    timeout=120,
                )
                raw = (resp.choices[0].message.content or "").strip()
                raw = re.sub(r"^\*{0,2}译文[：:]\*{0,2}\s*", "", raw)
                if "\n\n**术语说明" in raw or "\n\n术语说明" in raw:
                    raw = re.split(r"\n\n\*{0,2}术语说明", raw)[0].strip()
                return raw
            except Exception as exc:
                logger.warning(f"Single translation failed: {exc}")
                if "403" in str(exc) or "429" in str(exc):
                    if self._switch_to_backup_key():
                        continue
                time.sleep(2)
        return ""

    def _parse_batch_response(self, raw_text: str, expected_count: int) -> list[str]:
        """Parses [P1], [P2], ... tags from model output."""
        translations = [""] * expected_count
        parts = re.split(r"\[P(\d+)\]", raw_text)
        if len(parts) > 1:
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
        """Transforms paper full text into bilingual English + Chinese layout."""
        if not self.enabled or not markdown_text or not self.client:
            return markdown_text

        blocks = self.split_into_semantic_blocks(markdown_text)
        text_indices = [i for i, (content, btype) in enumerate(blocks) if btype == "text" and len(content.strip()) > 20]

        logger.info(f"Translating {len(text_indices)} text paragraphs into bilingual layout (model: {self.model})...")

        batch_size = max(1, self.batch_size)
        translated_map: dict[int, str] = {}

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
