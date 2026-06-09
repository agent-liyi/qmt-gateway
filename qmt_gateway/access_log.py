"""Uvicorn access log configuration."""

import logging
from pathlib import Path


_ACCESS_FILE_HANDLER_NAME = "qmt-gateway-access-file"


def configure_access_log(log_dir: str | Path) -> Path:
    """Route uvicorn access logs to access.log and quiet console output."""
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False

    for handler in access_logger.handlers:
        if getattr(handler, "name", "") != _ACCESS_FILE_HANDLER_NAME:
            handler.setLevel(logging.WARNING)

    path = Path(log_dir).expanduser() / "access.log"
    path.parent.mkdir(parents=True, exist_ok=True)

    for handler in access_logger.handlers:
        if getattr(handler, "name", "") == _ACCESS_FILE_HANDLER_NAME:
            if Path(getattr(handler, "baseFilename", "")) == path:
                return path
            access_logger.removeHandler(handler)
            handler.close()

    file_handler = logging.FileHandler(path, encoding="utf-8")
    file_handler.name = _ACCESS_FILE_HANDLER_NAME
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
    access_logger.addHandler(file_handler)
    return path
