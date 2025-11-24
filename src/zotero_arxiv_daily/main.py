import os
import logging
import sys
from omegaconf import DictConfig
import hydra
from loguru import logger
from zotero_arxiv_daily.executor import Executor
os.environ["TOKENIZERS_PARALLELISM"] = "false"


@hydra.main(version_base=None, config_path="../../config", config_name="default")
def main(config:DictConfig):
    # Configure loguru log level based on config
    log_level = "DEBUG" if config.executor.debug else "INFO"
    logger.remove()  # Remove default handler
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )
    
    # Intercept standard logging (including httpx) and route through loguru
    # Only show WARNING and above for httpx to reduce noise
    class InterceptHandler(logging.Handler):
        def emit(self, record):
            # Filter httpx INFO logs
            if record.name == "httpx" and record.levelno < logging.WARNING:
                return

            # Get corresponding Loguru level if it exists
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # Find caller from where the logged message originated
            frame, depth = sys._getframe(), 6
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    # Remove all existing handlers and add our interceptor
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    
    executor = Executor(config)
    executor.run()

if __name__ == '__main__':
    main()