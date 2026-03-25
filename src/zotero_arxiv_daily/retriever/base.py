from abc import ABC, abstractmethod
from omegaconf import DictConfig
from ..protocol import Paper, RawPaperItem
from tqdm import tqdm
from typing import Type
from loguru import logger


def _describe_raw_paper(raw_paper: RawPaperItem) -> str:
    title = getattr(raw_paper, "title", None)
    if title:
        return str(title)
    if isinstance(raw_paper, dict):
        for key in ("title", "entry_id", "id", "doi"):
            value = raw_paper.get(key)
            if value:
                return str(value)
    return repr(raw_paper)


def _convert_to_paper_safe(retriever: "BaseRetriever", raw_paper: RawPaperItem) -> Paper | None:
    try:
        return retriever.convert_to_paper(raw_paper)
    except Exception as exc:
        logger.warning(
            f"Skipping paper {_describe_raw_paper(raw_paper)}: {type(exc).__name__}: {exc}"
        )
        return None


class BaseRetriever(ABC):
    name: str
    def __init__(self, config:DictConfig):
        self.config = config
        self.retriever_config = getattr(config.source,self.name)

    @abstractmethod
    def _retrieve_raw_papers(self) -> list[RawPaperItem]:
        pass

    @abstractmethod
    def convert_to_paper(self, raw_paper:RawPaperItem) -> Paper | None:
        pass

    def retrieve_papers(self) -> list[Paper]:
        raw_papers = self._retrieve_raw_papers()
        logger.info("Processing papers...")
        papers = []
        for raw_paper in tqdm(raw_papers, total=len(raw_papers), desc="Converting papers"):
            paper = _convert_to_paper_safe(self, raw_paper)
            if paper is not None:
                papers.append(paper)
        return papers

registered_retrievers = {}

def register_retriever(name:str):
    def decorator(cls):
        registered_retrievers[name] = cls
        cls.name = name
        return cls
    return decorator

def get_retriever_cls(name:str) -> Type[BaseRetriever]:
    if name not in registered_retrievers:
        raise ValueError(f"Retriever {name} not found")
    return registered_retrievers[name]
