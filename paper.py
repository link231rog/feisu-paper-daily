from typing import Optional
from functools import cached_property
from tempfile import TemporaryDirectory
import arxiv
import tarfile
import re
from llm import get_llm
import requests
from requests.adapters import HTTPAdapter, Retry
from loguru import logger
import tiktoken



class ArxivPaper:
    def __init__(self,paper:arxiv.Result):
        self._paper = paper
        self.score = None
    
    @property
    def title(self) -> str:
        return self._paper.title
    
    @property
    def summary(self) -> str:
        return self._paper.summary
    
    @property
    def authors(self) -> list[str]:
        return self._paper.authors
    
    @cached_property
    def arxiv_id(self) -> str:
        return re.sub(r'v\d+$', '', self._paper.get_short_id())
    
    @property
    def pdf_url(self) -> str:
        return self._paper.pdf_url
    
    @cached_property
    def code_url(self) -> Optional[str]:
        s = requests.Session()
        retries = Retry(total=5, backoff_factor=0.1)
        s.mount('https://', HTTPAdapter(max_retries=retries))
        try:
            paper_list = s.get(f'https://paperswithcode.com/api/v1/papers/?arxiv_id={self.arxiv_id}').json()
        except Exception as e:
            logger.debug(f'Error when searching {self.arxiv_id}: {e}')
            return None

        if paper_list.get('count',0) == 0:
            return None
        paper_id = paper_list['results'][0]['id']

        try:
            repo_list = s.get(f'https://paperswithcode.com/api/v1/papers/{paper_id}/repositories/').json()
        except Exception as e:
            logger.debug(f'Error when searching {self.arxiv_id}: {e}')
            return None
        if repo_list.get('count',0) == 0:
            return None
        return repo_list['results'][0]['url']
    
    @cached_property
    def tex(self) -> dict[str,str]:
        with TemporaryDirectory() as tmpdirname:
            file = self._paper.download_source(dirpath=tmpdirname)
            with tarfile.open(file) as tar:
                tex_files = [f for f in tar.getnames() if f.endswith('.tex')]
                if len(tex_files) == 0:
                    logger.debug(f"Failed to find main tex file of {self.arxiv_id}: No tex file.")
                    return None
                
                bbl_file = [f for f in tar.getnames() if f.endswith('.bbl')]
                match len(bbl_file) :
                    case 0:
                        if len(tex_files) > 1:
                            logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: There are multiple tex files while no bbl file.")
                            main_tex = None
                        else:
                            main_tex = tex_files[0]
                    case 1:
                        main_name = bbl_file[0].replace('.bbl','')
                        main_tex = f"{main_name}.tex"
                        if main_tex not in tex_files:
                            logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: The bbl file does not match any tex file.")
                            main_tex = None
                    case _:
                        logger.debug(f"Cannot find main tex file of {self.arxiv_id} from bbl: There are multiple bbl files.")
                        main_tex = None

                if main_tex is None:
                    logger.debug(f"Trying to choose tex file containing the document block as main tex file of {self.arxiv_id}")
                #read all tex files
                file_contents = {}
                for t in tex_files:
                    f = tar.extractfile(t)
                    content = f.read().decode('utf-8')
                    #remove comments
                    content = re.sub(r'%.*\n', '\n', content)
                    content = re.sub(r'\\begin{comment}.*?\\end{comment}', '', content, flags=re.DOTALL)
                    content = re.sub(r'\\iffalse.*?\\fi', '', content, flags=re.DOTALL)
                    #remove redundant \n
                    content = re.sub(r'\n+', '\n', content)
                    if main_tex is None and re.search(r'\\begin\{document\}', content):
                        main_tex = t
                        logger.debug(f"Choose {t} as main tex file of {self.arxiv_id}")
                    file_contents[t] = content
                
                if main_tex is not None:
                    main_source:str = file_contents[main_tex]
                    #find and replace all included sub-files
                    include_files = re.findall(r'\\input\{(.+?)\}', main_source) + re.findall(r'\\include\{(.+?)\}', main_source)
                    for f in include_files:
                        if not f.endswith('.tex'):
                            f += '.tex'
                        main_source = main_source.replace(f, file_contents.get(f, ''))
                    file_contents["all"] = main_source
                else:
                    logger.debug(f"Failed to find main tex file of {self.arxiv_id}: No tex file containing the document block.")
                    file_contents["all"] = None
        return file_contents
    
    @cached_property
    def tldr(self) -> str:
        introduction = ""
        conclusion = ""
        if self.tex is not None:
            content = self.tex.get("all")
            if content is None:
                content = "\n".join(self.tex.values())
            #remove cite
            content = re.sub(r'~?\\cite.?\{.*?\}', '', content)
            #remove figure
            content = re.sub(r'\\begin\{figure\}.*?\\end\{figure\}', '', content, flags=re.DOTALL)
            #remove table
            content = re.sub(r'\\begin\{table\}.*?\\end\{table\}', '', content, flags=re.DOTALL)
            #find introduction and conclusion
            # end word can be \section or \end{document} or \bibliography or \appendix
            match = re.search(r'\\section\{Introduction\}.*?(\\section|\\end\{document\}|\\bibliography|\\appendix|$)', content, flags=re.DOTALL)
            if match:
                introduction = match.group(0)
            match = re.search(r'\\section\{Conclusion\}.*?(\\section|\\end\{document\}|\\bibliography|\\appendix|$)', content, flags=re.DOTALL)
            if match:
                conclusion = match.group(0)
        prompt = """Given the title, abstract, introduction and the conclusion (if any) of a paper in latex format, generate a one-sentence TLDR summary:
        
        \\title{__TITLE__}
        \\begin{abstract}__ABSTRACT__\\end{abstract}
        __INTRODUCTION__
        __CONCLUSION__
        """
        prompt = prompt.replace('__TITLE__', self.title)
        prompt = prompt.replace('__ABSTRACT__', self.summary)
        prompt = prompt.replace('__INTRODUCTION__', introduction)
        prompt = prompt.replace('__CONCLUSION__', conclusion)

        # use gpt-4o tokenizer for estimation
        enc = tiktoken.encoding_for_model("gpt-4o")
        prompt_tokens = enc.encode(prompt)
        prompt_tokens = prompt_tokens[:4000]  # truncate to 4000 tokens
        prompt = enc.decode(prompt_tokens)
        llm = get_llm()
        tldr = llm.generate(
            messages=[
                {
                    "role": "system",
                    "content": "You are an assistant who perfectly summarizes scientific paper, and gives the core idea of the paper to the user.",
                },
                {"role": "user", "content": prompt},
            ]
        )
        return tldr



                
                