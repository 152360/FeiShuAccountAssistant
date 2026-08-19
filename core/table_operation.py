"""
飞书多维表格操作模块
- 写入记账记录
- （原 parse_message 已迁移至 agent.py 作为降级方案）
"""

from lark_oapi import Client
from lark_oapi.api.bitable.v1 import CreateAppTableRecordRequest, AppTableRecord

from config.glob_config import (
    APP_TOKEN,
    TABLE_ID,
    DEFAULT_CATEGORY,
    DEFAULT_ACCOUNT,
    API_MAX_RETRIES,
    API_BASE_DELAY,
)
from config.logger_config import get_logger
from utils import retry_with_backoff

logger = get_logger(__name__)


@retry_with_backoff(
    max_retries=API_MAX_RETRIES,
    base_delay=API_BASE_DELAY,
    non_retryable_exceptions=(ValueError, TypeError),
)
def add_account_record(
    client: Client,
    amount: float,
    note: str,
    category: str | None = None,
    account: str | None = None,
) -> tuple[bool, str]:
    """
    向多维表格添加一条记账记录（带自动重试）

    :param client:   飞书 API 客户端
    :param amount:   金额
    :param note:     备注（消费描述）
    :param category: 分类（若为 None 则使用默认分类）
    :param account:  账户（若为 None 则使用默认账户）
    :return: (success: bool, message: str)
    """
    if category is None:
        category = DEFAULT_CATEGORY
    if account is None:
        account = DEFAULT_ACCOUNT

    fields = {
        "金额": amount,
        "分类": category,
        "账户": account,
        "备注": note,
    }

    request = (
        CreateAppTableRecordRequest.builder()
        .app_token(APP_TOKEN)
        .table_id(TABLE_ID)
        .request_body(AppTableRecord.builder().fields(fields).build())
        .build()
    )

    logger.info("写入表格: amount=%s, category=%s, account=%s, note=%s",
                amount, category, account, note)

    try:
        response = client.bitable.v1.app_table_record.create(request)
        if response.success():
            logger.info("写入表格成功")
            return True, "记账成功"
        else:
            error_msg = f"code={response.code}, msg={response.msg}"
            logger.error("写入表格失败: %s", error_msg)
            raise RuntimeError(f"飞书 API 返回错误: {error_msg}")
    except (ValueError, TypeError):
        # 参数错误，不应重试
        raise
    except Exception as e:
        logger.error("写入表格异常: %s", e)
        raise  # 由 retry 装饰器处理重试
