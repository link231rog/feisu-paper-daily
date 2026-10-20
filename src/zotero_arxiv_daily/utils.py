import tarfile
import re
import glob
import math
import smtplib
import unicodedata
from collections import Counter
from email.header import Header
from email.mime.text import MIMEText
from email.utils import parseaddr, formataddr
from loguru import logger
import datetime
from omegaconf import DictConfig
import pymupdf
import pymupdf.layout
pymupdf.TOOLS.mupdf_display_errors(False)
pymupdf.layout.activate()

import pymupdf4llm  # noqa: E402

_TOKEN_RE = re.compile(r'[a-zA-Z0-9]+')

def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def _bm25_pick(query: str, candidates: dict[str, str], k1: float = 1.5, b: float = 0.75) -> str:
    """Return the candidate key whose content best matches *query* by BM25."""
    query_tokens = _tokenize(query)
    if not query_tokens:
        return next(iter(candidates))

    doc_tokens = {name: _tokenize(content) for name, content in candidates.items()}
    N = len(doc_tokens)
    avgdl = sum(len(t) for t in doc_tokens.values()) / max(N, 1)

    df: Counter[str] = Counter()
    for tokens in doc_tokens.values():
        df.update(set(tokens))

    best_name, best_score = None, -1.0
    for name, tokens in doc_tokens.items():
        tf = Counter(tokens)
        dl = len(tokens)
        score = 0.0
        for q in query_tokens:
            n_q = df.get(q, 0)
            idf = math.log((N - n_q + 0.5) / (n_q + 0.5) + 1)
            f_q = tf.get(q, 0)
            score += idf * (f_q * (k1 + 1)) / (f_q + k1 * (1 - b + b * dl / max(avgdl, 1)))
        if score > best_score:
            best_score = score
            best_name = name
    return best_name


def extract_tex_code_from_tar(file_path:str, paper_id:str, paper_title:str | None = None) -> dict[str,str]:
    try:
        tar = tarfile.open(file_path)
    except tarfile.ReadError:
        logger.debug(f"Failed to find main tex file of {paper_id}: Not a tar file.")
        return None
 
    tex_files = [f for f in tar.getnames() if f.endswith('.tex')]
    if len(tex_files) == 0:
        logger.debug(f"Failed to find main tex file of {paper_id}: No tex file.")
        tar.close()
        return None
    
    bbl_file = [f for f in tar.getnames() if f.endswith('.bbl')]
    match len(bbl_file) :
        case 0:
            if len(tex_files) > 1:
                logger.debug(f"Cannot find main tex file of {paper_id} from bbl: There are multiple tex files while no bbl file.")
                main_tex = None
            else:
                main_tex = tex_files[0]
        case 1:
            main_name = bbl_file[0].replace('.bbl','')
            main_tex = f"{main_name}.tex"
            if main_tex not in tex_files:
                logger.debug(f"Cannot find main tex file of {paper_id} from bbl: The bbl file does not match any tex file.")
                main_tex = None
        case _:
            logger.debug(f"Cannot find main tex file of {paper_id} from bbl: There are multiple bbl files.")
            main_tex = None

    if main_tex is None:
        logger.debug(f"Trying to choose tex file containing the document block as main tex file of {paper_id}")

    file_contents = {}
    doc_block_candidates: list[str] = []
    for t in tex_files:
        f = tar.extractfile(t)
        content = f.read().decode('utf-8',errors='ignore')
        content = re.sub(r'%.*\n', '\n', content)
        content = re.sub(r'\\begin{comment}.*?\\end{comment}', '', content, flags=re.DOTALL)
        content = re.sub(r'\\iffalse.*?\\fi', '', content, flags=re.DOTALL)
        content = re.sub(r'\n+', '\n', content)
        content = re.sub(r'\\\\', '', content)
        content = re.sub(r'[ \t\r\f]{3,}', ' ', content)
        if main_tex is None and re.search(r'\\begin\{document\}', content) and not any(w in t for w in ['example', 'sample', 'template']):
            doc_block_candidates.append(t)
        file_contents[t] = content

    if main_tex is None:
        if len(doc_block_candidates) == 1:
            main_tex = doc_block_candidates[0]
            logger.debug(f"Choose {main_tex} as main tex file of {paper_id}")
        elif len(doc_block_candidates) > 1:
            if paper_title:
                main_tex = _bm25_pick(paper_title, {c: file_contents[c] for c in doc_block_candidates})
                logger.debug(f"Multiple document blocks found in {paper_id}; BM25 selected {main_tex} from {doc_block_candidates}")
            else:
                main_tex = doc_block_candidates[0]
                logger.debug(f"Multiple document blocks found in {paper_id}; no title provided, using first candidate {main_tex}")

    if main_tex is not None:
        main_source:str = file_contents[main_tex]
        #find and replace all included sub-files
        include_files = re.findall(r'\\input\{(.+?)\}', main_source) + re.findall(r'\\include\{(.+?)\}', main_source)
        for f in include_files:
            if not f.endswith('.tex'):
                file_name = f + '.tex'
            else:
                file_name = f
            main_source = main_source.replace(f'\\input{{{f}}}', file_contents.get(file_name, ''))
        file_contents["all"] = main_source
    else:
        logger.debug(f"Failed to find main tex file of {paper_id}: No tex file containing the document block.")
        file_contents["all"] = None
        
    tar.close()
    return file_contents

def clean_paper_markdown(text: str) -> str:
    """Cleans up academic paper markdown extracted from PDF / HTML."""
    if not text:
        return ""
    # Unicode normalize NFKD (fixes ligatures like fi, fl, ff)
    text = unicodedata.normalize("NFKD", text)
    # Fix HTML pseudo-anchor citations [[1]](#bib.bib1) -> [1]
    text = re.sub(r"\[\[(.*?)\]\]\(#.*?\)", r"[\1]", text)
    # Fix multiple separated brackets like [[1], [2]] -> [1, 2]
    text = re.sub(r"\[\[(.*?)\]\]", r"[\1]", text)
    # Fix broken spaced bracket citations e.g. [ 1 , 2 ] -> [1, 2], [ 12 - 15 ] -> [12–15]
    text = re.sub(
        r"\[\s*(\d+(?:\s*,\s*\d+|\s*[-–]\s*\d+)*)\s*\]",
        lambda m: "[" + re.sub(r"\s*[-–]\s*", "–", re.sub(r"\s*,\s*", ", ", m.group(1).strip())) + "]",
        text,
    )
    # Fix mid-sentence line breaks right before citation brackets e.g. "word\n[1]" -> "word [1]"
    text = re.sub(r"([a-zA-Z0-9])\s*\n\s*(\[\d+\])", r"\1 \2", text)
    return text


def extract_markdown_from_pdf(file_path: str) -> str:
    raw_md = pymupdf4llm.to_markdown(file_path, use_ocr=False, header=False, footer=False, ignore_code=True)
    return clean_paper_markdown(raw_md)

def glob_match(path:str, pattern:str) -> bool:
    re_pattern = glob.translate(pattern,recursive=True)
    return re.match(re_pattern, path) is not None

def send_email(config:DictConfig, html:str):
    sender = config.email.sender
    receiver = config.email.receiver
    password = config.email.sender_password
    smtp_server = config.email.smtp_server
    smtp_port = config.email.smtp_port
    def _format_addr(s):
        name, addr = parseaddr(s)
        return formataddr((Header(name, 'utf-8').encode(), addr))

    msg = MIMEText(html, 'html', 'utf-8')
    msg['From'] = _format_addr('Github Action <%s>' % sender)
    msg['To'] = _format_addr('You <%s>' % receiver)
    today = datetime.datetime.now().strftime('%Y/%m/%d')
    msg['Subject'] = Header(f'Daily arXiv {today}', 'utf-8').encode()

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
    except Exception as e:
        logger.debug(f"Failed to use TLS. {e}\nTry to use SSL.")
        try:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        except Exception as e:
            logger.debug(f"Failed to use SSL. {e}\nTry to use plain text.")
            server = smtplib.SMTP(smtp_server, smtp_port)

    server.login(sender, password)
    server.sendmail(sender, [receiver], msg.as_string())
    server.quit()


def translate_to_chinese(text: str, timeout: float = 8.0) -> str:
    """Translates text to Chinese using free translation endpoints (Google Chrome Extension & MyMemory).
    
    Zero configuration, no API keys needed.
    """
    if not text or not text.strip():
        return ""

    # Already contains Chinese characters
    if re.search(r"[\u4e00-\u9fff]", text):
        return text.strip()

    clean_text = text.strip()

    # 1. Primary: Google Chrome translation endpoint (fast, high limit)
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

    # 2. Secondary fallback: MyMemory Translation API
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