import logging
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "useless.log"
LOGGER_NAME = "useless"
_MAX_ARCHIVED_SESSIONS = 10
_configured = False


def _archive_previous_session():
    if not LOG_FILE.exists():
        return

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S_%f")
    archive_path = LOG_DIR / f"useless_{timestamp}.log"
    LOG_FILE.replace(archive_path)

    archives = sorted(
        LOG_DIR.glob("useless_*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old_archive in archives[_MAX_ARCHIVED_SESSIONS:]:
        try:
            old_archive.unlink()
        except OSError:
            logging.getLogger(LOGGER_NAME).exception(
                "Unable to delete old archived session log: %s", old_archive
            )


def configure_logging():
    """Start a fresh current-session log with bounded archived history."""
    global _configured
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if _configured:
        return logger

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for old_handler in list(logger.handlers):
        old_handler.close()
        logger.removeHandler(old_handler)
    _archive_previous_session()

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
    _configured = True

    timestamp = datetime.now().isoformat(timespec="seconds")
    logger.info(
        "============================================================\n"
        "USELESS SESSION START\n%s\n"
        "============================================================",
        timestamp,
    )
    return logger


def mark_session_end():
    logger = logging.getLogger(LOGGER_NAME)
    timestamp = datetime.now().isoformat(timespec="seconds")
    logger.info(
        "============================================================\n"
        "USELESS SESSION END\n%s\n"
        "============================================================",
        timestamp,
    )


def read_recent_logs():
    """Return the current log text for the local log viewer."""
    if not LOG_FILE.exists():
        return "No log entries yet."
    try:
        return LOG_FILE.read_text(encoding="utf-8")
    except OSError:
        return "Unable to read the log file."
