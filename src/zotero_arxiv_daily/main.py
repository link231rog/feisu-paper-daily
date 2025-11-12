import arxiv
import os
import sys
from pyzotero import zotero
from recommender import rerank_paper
from construct_email import render_email, send_email
from tqdm import tqdm
from loguru import logger
from gitignore_parser import parse_gitignore
from tempfile import mkstemp
from paper import ArxivPaper
from llm import set_global_llm
import feedparser
from omegaconf import DictConfig
import hydra
os.environ["TOKENIZERS_PARALLELISM"] = "false"

def get_zotero_corpus(id:str,key:str) -> list[dict]:
    zot = zotero.Zotero(id, 'user', key)
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
    return corpus

def filter_corpus(corpus:list[dict], pattern:str) -> list[dict]:
    _,filename = mkstemp()
    with open(filename,'w') as file:
        file.write(pattern)
    matcher = parse_gitignore(filename,base_dir='./')
    new_corpus = []
    for c in corpus:
        match_results = [matcher(p) for p in c['paths']]
        if not any(match_results):
            new_corpus.append(c)
    os.remove(filename)
    return new_corpus


def get_arxiv_paper(query:str, debug:bool=False) -> list[ArxivPaper]:
    client = arxiv.Client(num_retries=10,delay_seconds=10)
    feed = feedparser.parse(f"https://rss.arxiv.org/atom/{query}")
    if 'Feed error for query' in feed.feed.title:
        raise Exception(f"Invalid ARXIV_QUERY: {query}.")
    if not debug:
        papers = []
        all_paper_ids = [i.id.removeprefix("oai:arXiv.org:") for i in feed.entries if i.arxiv_announce_type == 'new']
        bar = tqdm(total=len(all_paper_ids),desc="Retrieving Arxiv papers")
        for i in range(0,len(all_paper_ids),50):
            search = arxiv.Search(id_list=all_paper_ids[i:i+50])
            batch = [ArxivPaper(p) for p in client.results(search)]
            bar.update(len(batch))
            papers.extend(batch)
        bar.close()

    else:
        logger.debug("Retrieve 5 arxiv papers regardless of the date.")
        search = arxiv.Search(query='cat:cs.AI', sort_by=arxiv.SortCriterion.SubmittedDate)
        papers = []
        for i in client.results(search):
            papers.append(ArxivPaper(i))
            if len(papers) == 5:
                break

    return papers

@hydra.main(version_base=None, config_path="config", config_name="default")
def main(config:DictConfig):
    assert (
        not config.llm.use_api or config.llm.api.key is not None
    )  # If use_llm_api is True, openai_api_key must be provided
    if config.executor.debug:
        logger.remove()
        logger.add(sys.stdout, level="DEBUG")
        logger.debug("Debug mode is on.")
    else:
        logger.remove()
        logger.add(sys.stdout, level="INFO")

    logger.info("Retrieving Zotero corpus...")
    corpus = get_zotero_corpus(config.zotero.user_id, config.zotero.api_key)
    logger.info(f"Retrieved {len(corpus)} papers from Zotero.")
    if config.zotero.ignore_collection:
        logger.info(f"Ignoring papers in:\n {config.zotero.ignore_collection}...")
        corpus = filter_corpus(corpus, config.zotero.ignore_collection)
        logger.info(f"Remaining {len(corpus)} papers after filtering.")
    logger.info("Retrieving Arxiv papers...")
    papers = get_arxiv_paper(config.arxiv.query, config.executor.debug)
    if len(papers) == 0:
        logger.info("No new papers found. Yesterday maybe a holiday and no one submit their work :). If this is not the case, please check the ARXIV_QUERY.")
        if not config.executor.send_empty:
          exit(0)
    else:
        logger.info("Reranking papers...")
        papers = rerank_paper(papers, corpus)
        if config.executor.max_paper_num != -1:
            papers = papers[:config.executor.max_paper_num]
        if config.llm.use_api:
            logger.info("Using OpenAI API as global LLM.")
            set_global_llm(api_key=config.llm.api.key, base_url=config.llm.api.base_url, model=config.llm.name, lang=config.llm.generation_kwargs.language)
        else:
            logger.info("Using Local LLM as global LLM.")
            set_global_llm(lang=config.llm.generation_kwargs.language)

    html = render_email(papers)
    logger.info("Sending email...")
    send_email(config.email.sender, config.email.receiver, config.email.sender_password, config.email.smtp_server, config.email.smtp_port, html)
    logger.success("Email sent successfully! If you don't receive the email, please check the configuration and the junk box.")


if __name__ == '__main__':
    main()