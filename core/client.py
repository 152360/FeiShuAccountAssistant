import sys
import traceback

import lark_oapi as lark

from utils import get_logger
from config import glob_config

_logger = get_logger(__name__)

_client: lark.Client | None = None

def get_feishu_client() -> lark.Client:
    global _client
    # 初始化 API 客户端
    if _client is not None:
        return _client
    try:
        _client = lark.Client.builder() \
            .app_id(glob_config.APP_ID) \
            .app_secret(glob_config.APP_SECRET) \
            .build()
        _logger.info("飞书 API 客户端初始化完成")
        return _client
    except Exception:
        _logger.critical("飞书 API 客户端初始化失败:\n%s", traceback.format_exc())
        sys.exit(1)