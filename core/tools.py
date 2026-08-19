import json
from datetime import datetime, timedelta, timezone

from langchain_core.tools import tool
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *

from config.logger_config import get_logger
from core.client import get_feishu_client
from config.glob_config import (
    TABLE_FIELD_NOTE,
    TABLE_FIELD_CATEGORY,
    TABLE_FIELD_TIME,
    TABLE_FIELD_AMOUNT,
    DEFAULT_CATEGORY,
    DEFAULT_ACCOUNT,
    APP_TOKEN,
    TABLE_ID,
)

_logger = get_logger(__name__)

@tool
def get_past_datetime(days_ago: int = 0) -> str:
    """
    获取当前时间或过去某天的日期时间字符串。当用户提及'今天'、'现在'、'昨天'或'X天前'时必须调用此工具，严禁自行编造。

    Args:
        days_ago: 自然数，距离今天的天数。0表示今天，1表示昨天，3表示3天前。默认值为0。

    Returns:
        格式为 "YYYY-MM-DD HH:MM:SS" 的字符串，可直接用于 SQLite 查询。

    Raises:
        ValueError: 当 days_ago 不是自然数时抛出。
    """
    if not isinstance(days_ago, int) or days_ago < 0:
        raise ValueError("days_ago 必须是一个自然数（>=0）")

    past_time = datetime.now() - timedelta(days=days_ago)
    return past_time.strftime("%Y-%m-%d %H:%M:%S")


@tool
def add_account_record(
    amount: float,
    note: str,
    category: str = DEFAULT_CATEGORY,
    account: str = DEFAULT_ACCOUNT,
) -> str:
    """
    向多维表格添加一条记账记录
    Args:
        amount: 金额，浮点数，必填。
        note: 备注，记账记录的描述（如沙县、肯德基等），必填。
        category: 消费分类，只能是：餐饮、交通、购物、娱乐、医疗、生活、学习，默认餐饮，可不填。
        account: 支付账户，只能是：微信、支付宝、现金，默认是微信，可不填。
    Returns:
        如果记账成功则返回记账日志信息，失败则返回——记账失败。
    """

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

    _logger.info("写入表格: amount=%s, category=%s, account=%s, note=%s",
                amount, category, account, note)

    try:
        client = get_feishu_client()
        response = client.bitable.v1.app_table_record.create(request)
        if response.success():
            _logger.info("写入表格成功")
            return f"记账成功!写入表格: amount={amount}, category={category}, account={account}, note={note}"
        else:
            error_msg = f"code={response.code}, msg={response.msg}"
            _logger.error("写入表格失败: %s", error_msg)
            raise RuntimeError(f"飞书 API 返回错误: {error_msg}")
    except (ValueError, TypeError):
        return "记账失败"
    except Exception as e:
        _logger.error("写入表格异常: %s", e)
        return "记账失败"


@tool
def get_account_records(start_time_str: str, end_time_str: str, page_size: int = 20):
    """
    获取飞书中提交的记账信息的方法。当用户提及'查账'、'账单记录'或明确表示要进行查账操作时，调用此工具。

    Args:
        start_time_str: 起始时间，格式：yyyy-mm-dd HH:MM:SS
        end_time_str: 结束时间，格式：yyyy-mm-dd HH:MM:SS
        page_size: 一页的大小，默认20，可不填。

    Returns:
        如果查询成功，返回关于记账信息的markdown表格，示例：
            总共 92 条记录，前 20 条记录如下：
            | 事件 | 分类 | 消费时间 | 金额 |
            | 晚餐沙县小吃 | 餐饮 | 2026-06-10 19:06:13 | 14 |
            | 早餐 | 餐饮 | 2026-06-11 13:55:20 | 7.5 |
            | 午餐吃面 | 餐饮 | 2026-06-11 13:56:48 | 17 |
            ……
        如果查询失败，则返回：获取记录信息失败

    """
    _logger.info(f"开始时间：{start_time_str}，结束时间：{end_time_str}")
    # 构造请求对象
    filter_str = f"AND(CurrentValue.[消费时间] >= TODATE(\"{start_time_str}\"), CurrentValue.[消费时间] <= TODATE(\"{end_time_str}\"))"
    request: ListAppTableRecordRequest = ListAppTableRecordRequest.builder() \
        .app_token(APP_TOKEN) \
        .table_id(TABLE_ID) \
        .filter(filter_str) \
        .field_names("[\"分类\", \"消费时间\", \"金额\", \"备注\"]") \
        .page_size(page_size) \
        .build()

    # 发起请求
    client = get_feishu_client()
    response: ListAppTableRecordResponse = client.bitable.v1.app_table_record.list(request)

    # 处理失败返回
    if not response.success():
        _logger.error(
            f"client.bitable.v1.app_table_record.list failed, code: {response.code}, msg: {response.msg}, log_id: {response.get_log_id()}, resp: \n{json.dumps(json.loads(response.raw.content), indent=4, ensure_ascii=False)}")
        return "获取记录信息失败"

    # 处理业务结果
    records_dict = json.loads(lark.JSON.marshal(response.data, indent=4))
    records_str = f"总共 {records_dict["total"]} 条记录"
    records_str += f"，前 {page_size} 条记录如下：\n" if records_dict["has_more"] == True else "\n"
    records_str += "| 事件 | 分类 | 消费时间 | 金额 |\n"
    for item in records_dict["items"]:
        time_obj = datetime.fromtimestamp(item["fields"][TABLE_FIELD_TIME] / 1000, tz=timezone(timedelta(hours=8)))
        time_str = time_obj.strftime("%Y-%m-%d %H:%M:%S")
        records_str += f"| {item["fields"][TABLE_FIELD_NOTE]} | {item["fields"][TABLE_FIELD_CATEGORY]} | {time_str} | {item["fields"][TABLE_FIELD_AMOUNT]} |\n"

    _logger.info(records_str)
    return records_str


def _get_timestamp(time_str: str) -> int:
    # 1. 将字符串解析为 datetime 对象
    dt = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
    # 2. 转换为秒级时间戳（浮点数）
    timestamp_sec = dt.timestamp()
    # 3. 转换为毫秒级（飞书 API 要求，并且必须是整数）
    return int(timestamp_sec * 1000)