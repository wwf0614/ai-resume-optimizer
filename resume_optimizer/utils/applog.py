# -*- coding: utf-8 -*-
"""结构化应用日志：JSON Lines 滚动文件 + 内存环形缓冲（供日志页实时查看）。"""
import json
import logging
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

_RECENT: list = []
_MAX_RECENT = 500


class _JsonFormatter(logging.Formatter):
    def format(self, record):
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            payload = {"message": record.getMessage()}
        payload.setdefault("level", record.levelname)
        payload.setdefault("ts", time.strftime("%Y-%m-%d %H:%M:%S"))
        return json.dumps(payload, ensure_ascii=False)


_logger = logging.getLogger("resume_app")
if not _logger.handlers:
    _handler = RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    _handler.setFormatter(_JsonFormatter())
    _logger.addHandler(_handler)
    _logger.setLevel(logging.INFO)


def log(event: str, **fields):
    """写入一条结构化日志，同时保留在内存环形缓冲。"""
    fields["event"] = event
    _RECENT.append(fields)
    if len(_RECENT) > _MAX_RECENT:
        del _RECENT[: len(_RECENT) - _MAX_RECENT]
    try:
        _logger.info(json.dumps(fields, ensure_ascii=False))
    except Exception:  # noqa: BLE001 日志失败不影响业务
        pass


def recent(limit: int = 200) -> list:
    return list(_RECENT[-limit:])
