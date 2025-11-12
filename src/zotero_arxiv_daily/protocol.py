from dataclasses import dataclass
from typing import Optional, TypeVar

RawPaperItem = TypeVar('RawPaperItem')

@dataclass
class Paper:
    source: str
    title: str
    authors: list[str]
    abstract: str
    url: str
    pdf_url: Optional[str] = None
    tex: Optional[dict[str,str]] = None
    tldr: Optional[str] = None