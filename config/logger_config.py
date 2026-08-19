"""
日志管理模块
- 控制台输出 + 文件轮转（按大小）
- 普通日志 & 错误日志分离
- 支持通过环境变量 LOG_LEVEL 控制级别
"""

import logging
import logging.handlers
import os
from pathlib import Path

# ── 可配置项 ──────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = "app.log"
ERROR_FILE = "error.log"
MAX_BYTES = 10 * 1024 * 1024   # 10 MB 单文件上限
BACKUP_COUNT = 7               # 保留最近 7 个轮转文件
LOG_FORMAT = (
    "[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
# ──────────────────────────────────────────────────────────

_initialized = False
_loggers: dict[str, logging.Logger] = {}


def setup_logging() -> None:
    """初始化日志系统（幂等 — 多次调用只生效一次）"""
    global _initialized
    if _initialized:
        return

    LOG_DIR.mkdir(parents=True, exist_ok=True)

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    # 清除已有的 handler（避免重复添加）
    root.handlers.clear()

    fmt = logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT)

    # ── 控制台 handler ──
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # ── 全量日志文件（按大小轮转）──
    app_file = logging.handlers.RotatingFileHandler(
        LOG_DIR / LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    app_file.setLevel(level)
    app_file.setFormatter(fmt)
    root.addHandler(app_file)

    # ── 错误日志单独文件 ──
    err_file = logging.handlers.RotatingFileHandler(
        LOG_DIR / ERROR_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    err_file.setLevel(logging.ERROR)
    err_file.setFormatter(fmt)
    root.addHandler(err_file)

    _initialized = True

    logging.getLogger(__name__).info(
        "日志系统初始化完成 | 级别=%s | 目录=%s", level_name, LOG_DIR
    )


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger，自动附加模块名"""
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


# 模块导入时自动初始化
setup_logging()
