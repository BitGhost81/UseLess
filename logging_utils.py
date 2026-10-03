import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "useless.log"
LOGGER_NAME = "useless"


def configure_logging():
    """Configure one persistent rotating log file and return the app logger."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_FILE,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)

    return logger


def read_recent_logs():
    """Return the current log text for the local log viewer."""
    if not LOG_FILE.exists():
        return "No log entries yet."
    try:
        return LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return "Unable to read the log file."
