from loguru import logger
from pyzotero import zotero
from omegaconf import DictConfig
from .utils import glob_match
import random

class Executor:
    def __init__(self, config:DictConfig):
        self.config = config

    def fetch_zotero_corpus(self) -> list[dict]:
        logger.info("Fetching zotero corpus")
        zot = zotero.Zotero(self.config.zotero.id, 'user', self.config.zotero.api_key)
        collections = zot.everything(zot.collections())
        collections = {c['key']:c for c in collections}
        corpus = zot.everything(zot.items(itemType='conferencePaper || journalArticle || preprint'))
        corpus = [c for c in corpus if c['data']['abstractNote'] != '']
        def get_collection_path(col_key:str) -> str:
            if p := collections[col_key]['data']['parentCollection']:
                return get_collection_path(p) + '/' + collections[col_key]['data']['name']
            else:
                return collections[col_key]['data']['name']
        for c in corpus:
            paths = [get_collection_path(col) for col in c['data']['collections']]
            c['paths'] = paths
        logger.info(f"Fetched {len(corpus)} zotero papers")
        return corpus
    
    def filter_corpus(self, corpus:list[dict]) -> list[dict]:
        if not self.config.zotero.include_path:
            return corpus
        new_corpus = []
        logger.info(f"Selecting zotero papers matching include_path: {self.config.zotero.include_path}")
        for c in corpus:
            match_results = [glob_match(p, self.config.zotero.include_path) for p in c['paths']]
            if any(match_results):
                new_corpus.append(c)
        samples = random.sample(new_corpus, min(5, len(new_corpus)))
        samples = '\n'.join([c['data']['title'] + ' - ' + '\n'.join(c['paths']) for c in samples])
        logger.info(f"Selected {len(new_corpus)} zotero papers:\n{samples}")
        return new_corpus

    
    def run(self):
        corpus = self.fetch_zotero_corpus()
        corpus = self.filter_corpus(corpus)
        return corpus