import os

from loguru import logger

# Configure loguru to write to logs/nakama_kun.log
log_dir = "logs"
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "nakama_kun.log")

# Setup logger configuration
logger.add(
    log_file,
    rotation="10 MB",
    retention="1 month",
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
)

logger.info("nakama_kun AI Integration Layer initialized.")
