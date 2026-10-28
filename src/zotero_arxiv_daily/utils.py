import datetime
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, parseaddr
import glob
import re
import smtplib
from typing import Any
import unicodedata

from loguru import logger
from omegaconf import DictConfig


def clean_paper_markdown(text: str) -> str:
    """Cleans up academic paper markdown extracted from PDF / HTML."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = re.sub(r"\[\[(.*?)\]\]\(#.*?\)", r"[\1]", text)
    text = re.sub(r"\[\[(.*?)\]\]", r"[\1]", text)
    text = re.sub(
        r"\[\s*(\d+(?:\s*,\s*\d+|\s*[-–]\s*\d+)*)\s*\]",
        lambda m: "[" + re.sub(r"\s*[-–]\s*", "–", re.sub(r"\s*,\s*", ", ", m.group(1).strip())) + "]",
        text,
    )
    text = re.sub(r"([a-zA-Z0-9])\s*\n\s*(\[\d+\])", r"\1 \2", text)
    return text


def extract_markdown_from_pdf(file_path: str) -> str:
    import pymupdf
    import pymupdf.layout
    import pymupdf4llm

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.layout.activate()
    raw_md = pymupdf4llm.to_markdown(file_path, use_ocr=False, header=False, footer=False, ignore_code=True)
    return clean_paper_markdown(raw_md)


def glob_match(path: str, pattern: str) -> bool:
    re_pattern = glob.translate(pattern, recursive=True)
    return re.match(re_pattern, path) is not None


def send_email(
    config: DictConfig,
    html: str,
    subject: str | None = None,
    attachments: list[str | Any] | None = None,
) -> None:
    from email import encoders
    from email.mime.base import MIMEBase
    from email.mime.multipart import MIMEMultipart
    import mimetypes
    from pathlib import Path

    sender = str(config.email.sender).strip() if config.email.sender else ""
    receivers = [addr.strip() for addr in str(config.email.receiver).split(",") if addr.strip()]
    password = str(config.email.sender_password).strip() if config.email.sender_password else ""
    smtp_server = str(config.email.smtp_server).strip() if config.email.smtp_server else "smtp.qq.com"
    smtp_port = int(config.email.smtp_port)
    if not receivers:
        raise ValueError("email.receiver must contain at least one address")

    def _format_addr(s: str) -> str:
        name, addr = parseaddr(s)
        return formataddr((Header(name, "utf-8").encode(), addr))

    valid_files = [Path(p) for p in (attachments or []) if p and Path(p).is_file()]
    if valid_files:
        msg: Any = MIMEMultipart("mixed")
        msg.attach(MIMEText(html, "html", "utf-8"))
        for file_path in valid_files:
            mime_type, _ = mimetypes.guess_type(file_path.name)
            if mime_type and "/" in mime_type:
                maintype, subtype = mime_type.split("/", 1)
            elif file_path.suffix.lower() == ".mp3":
                maintype, subtype = "audio", "mpeg"
            elif file_path.suffix.lower() == ".m4a":
                maintype, subtype = "audio", "mp4"
            else:
                maintype, subtype = "application", "octet-stream"
            part = MIMEBase(maintype, subtype)
            part.set_payload(file_path.read_bytes())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                "attachment",
                filename=("utf-8", "", file_path.name),
            )
            msg.attach(part)
    else:
        msg = MIMEText(html, "html", "utf-8")

    msg["From"] = _format_addr(f"Feishu Paper Daily <{sender}>")
    msg["To"] = ", ".join(receivers)
    today = datetime.datetime.now().strftime("%Y/%m/%d")
    msg["Subject"] = Header(subject or f"Daily arXiv {today}", "utf-8").encode()

    if smtp_port == 465:
        server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=30)
    else:
        server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
        server.starttls()
    try:
        server.login(sender, password)
        server.sendmail(sender, receivers, msg.as_string())
    finally:
        server.quit()


def translate_to_chinese(text: str, timeout: float = 8.0) -> str:
    """Translates text to Chinese using free translation endpoints (Google Chrome Extension & MyMemory)."""
    if not text or not text.strip():
        return ""

    if re.search(r"[\u4e00-\u9fff]", text):
        return text.strip()

    clean_text = text.strip()

    try:
        import requests

        url = "https://clients5.google.com/translate_a/t"
        params = {
            "client": "dict-chrome-ex",
            "sl": "auto",
            "tl": "zh-CN",
            "q": clean_text[:4000],
        }
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, params=params, headers=headers, timeout=timeout)
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                first_item = data[0]
                if isinstance(first_item, list) and len(first_item) > 0 and isinstance(first_item[0], str):
                    res = first_item[0].strip()
                    if res:
                        return res
                elif isinstance(first_item, str):
                    return first_item.strip()
    except Exception as exc:
        logger.debug(f"Google Chrome translation fallback: {exc}")

    try:
        import requests

        url = "https://api.mymemory.translated.net/get"
        params = {"q": clean_text[:1000], "langpair": "en|zh-CN"}
        resp = requests.get(url, params=params, timeout=timeout)
        if resp.status_code == 200:
            res = resp.json().get("responseData", {}).get("translatedText")
            if res and isinstance(res, str) and res.strip():
                return res.strip()
    except Exception as exc:
        logger.debug(f"MyMemory translation fallback: {exc}")

    return clean_text