from abc import ABC, abstractmethod
from omegaconf import DictConfig
from zotero_arxiv_daily.protocol import Paper, RawPaperItem
from concurrent.futures import ThreadPoolExecutor

class BaseRetriever(ABC):
    def __init__(self, config:DictConfig):
        self.config = config
        self.exec_pool = ThreadPoolExecutor(max_workers=config.executor.max_workers)

    @abstractmethod
    def _retrieve_raw_papers(self) -> list[RawPaperItem]:
        pass

    @abstractmethod
    def convert_to_paper(self, raw_paper:RawPaperItem) -> Paper:
        pass

    def retrieve_papers(self) -> list[Paper]:
        raw_papers = self._retrieve_raw_papers()
        with self.exec_pool:
            papers = list(self.exec_pool.map(self.convert_to_paper, raw_papers))
        return papers

registered_retrievers = {}

def register_retriever(name:str):
    def decorator(cls):
        registered_retrievers[name] = cls
        return cls
    return decorator