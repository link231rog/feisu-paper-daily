from llama_cpp import Llama
from openai import OpenAI
from openai.resources.chat.completions import Completions
from omegaconf import DictConfig
from functools import wraps

class LLM:
    def __init__(self, config:DictConfig):
        self.config = config.llm
        self.model = self.config.model
        self.default_generation_kwargs = self.config.generation_kwargs
        self.max_retries = self.config.max_retries
        self.timeout = self.config.timeout
        if self.config.use_api:
            self.llm = OpenAI(api_key=self.config.api.key, base_url=self.config.api.base_url)
        else:
            self.llm = Llama.from_pretrained(
                repo_id=self.model,
                filename=self.config.filename,
                n_ctx=8192,
                n_threads=4,
                verbose=False,
            )
        
    
    @wraps(Completions.create)
    def create_chat_completion(self, *args, **kwargs):
        if isinstance(self.llm, OpenAI):
            return self.llm.chat.completions.create(*args, **kwargs)
        else:
            return self.llm.create_chat_completion_openai_v1(*args, **kwargs)