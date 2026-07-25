"""
结构化日志模块。
格式：[时间] [级别] [模块名] 消息
"""

import sys
import time
from config import LOG_LEVEL

# Windows GBK 终端打不出 emoji，强制 UTF-8
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

LEVEL_RANK = {"DEBUG": 0, "INFO": 1, "WARNING": 2, "ERROR": 3, "SILENT": 99}
CURRENT_LEVEL = LEVEL_RANK.get(LOG_LEVEL, 1)


def _log(level: str, module: str, msg: str):
    if LEVEL_RANK.get(level, 1) < CURRENT_LEVEL:
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    print(f"[{ts}] [{level:<7}] [{module}] {msg}")


def debug(module: str, msg: str):
    _log("DEBUG", module, msg)


def info(module: str, msg: str):
    _log("INFO", module, msg)


def warning(module: str, msg: str):
    _log("WARNING", module, msg)


def error(module: str, msg: str):
    _log("ERROR", module, msg)
