import logging
from pathlib import Path

import verticals.log as log_module


def test_get_logger_falls_back_when_file_handler_cannot_open(monkeypatch):
    monkeypatch.setattr(log_module, "LOGS_DIR", Path("C:/tmp/verticals-test-logs"))
    monkeypatch.setattr(log_module, "_logger", None)

    class ExplodingFileHandler(logging.FileHandler):
        def __init__(self, *args, **kwargs):
            raise PermissionError("no file access")

    monkeypatch.setattr(log_module.logging, "FileHandler", ExplodingFileHandler)

    logger = log_module.get_logger()

    assert logger.name == "pipeline"
    assert any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers)
