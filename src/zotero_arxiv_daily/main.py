import os
import sys
import logging
from omegaconf import DictConfig
import hydra
from loguru import logger
import dotenv
from zotero_arxiv_daily.executor import Executor
os.environ["TOKENIZERS_PARALLELISM"] = "false"
if "HF_ENDPOINT" not in os.environ and "GITHUB_ACTIONS" not in os.environ:
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
dotenv.load_dotenv()

@hydra.main(version_base=None, config_path="../../config", config_name="default")
def _hydra_main(config:DictConfig):
    # Configure loguru log level based on config
    log_level = "DEBUG" if config.executor.debug else "INFO"
    logger.remove()  # Remove default handler
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    for logger_name in logging.root.manager.loggerDict:
        if "zotero_arxiv_daily" in logger_name:
            continue
        logging.getLogger(logger_name).setLevel(logging.WARNING)

    if config.executor.debug:
        logger.info("Debug mode is enabled")
    
    executor = Executor(config)
    executor.run()


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("init", "--init"):
        from zotero_arxiv_daily.init_wizard import handle_init_cli

        handle_init_cli(sys.argv[2:])
        return
    _hydra_main()


if __name__ == '__main__':
    main()