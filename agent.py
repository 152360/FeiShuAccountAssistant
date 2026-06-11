"""
AI 模型模块
- 使用 LangChain + 硅基流动 API 进行消息解析
- 支持自动重试 & 正则降级
"""

import os
from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from pydantic import BaseModel, Field

from glob_config import (
    SILICON_API_KEY,
    MODEL_NAME,
    SYSTEM_PROMPT,
    AI_MAX_RETRIES,
    AI_BASE_DELAY,
    FALLBACK_TO_REGEX,
)
from logger_config import get_logger
from utils import retry_with_backoff

logger = get_logger(__name__)

# ── 结构化输出模型 ────────────────────────────────────────
class BillInfo(BaseModel):
    amount: float = Field(description="消费金额（元）")
    account: str = Field(
        default="微信",
        description="支付账户，只能是：微信、支付宝、现金，默认是微信",
    )
    category: str = Field(
        description="消费分类，只能是：餐饮、交通、购物、娱乐、医疗、生活、学习",
    )
    note: str = Field(description="消费描述")


# ── 初始化模型 ────────────────────────────────────────────
_api_key = SILICON_API_KEY

if not _api_key:
    logger.warning(
        "环境变量 SILICON_API_KEY 未设置！AI 解析将不可用，"
        "会自动降级到正则匹配"
    )

_model = None
_agent = None


def _ensure_model():
    """延迟初始化模型（避免导入时就报错）"""
    global _model, _agent
    if _agent is not None:
        return
    if not _api_key:
        raise RuntimeError("SILICON_API_KEY 未设置，无法初始化 AI 模型")

    logger.info("正在初始化 AI 模型: %s", MODEL_NAME)
    try:
        _model = init_chat_model(
            model=MODEL_NAME,
            model_provider="openai",
            base_url="https://api.siliconflow.cn/v1",
            api_key=_api_key,
            temperature=0.7,
        )
        _agent = create_agent(
            model=_model,
            system_prompt=SYSTEM_PROMPT,
            response_format=BillInfo,
        )
        logger.info("AI 模型初始化完成")
    except Exception as e:
        logger.error("AI 模型初始化失败: %s", e)
        raise


def get_agent():
    """获取 agent 实例（延迟初始化）"""
    _ensure_model()
    return _agent


# ── AI 解析（带重试）───────────────────────────────────────
@retry_with_backoff(
    max_retries=AI_MAX_RETRIES,
    base_delay=AI_BASE_DELAY,
    non_retryable_exceptions=(ValueError, TypeError, RuntimeError),
)
def _call_ai(llm, message: str) -> dict:
    """调用 AI 模型解析消息（内部函数，带重试装饰器）"""
    res = llm.invoke({"messages": [{"role": "user", "content": message}]})
    logger.debug("AI 原始返回: %s", res)
    bill = res["structured_response"]
    return {
        "amount": bill.amount,
        "account": bill.account,
        "category": bill.category,
        "note": bill.note,
        "success": True,
        "error_msg": "",
    }


def parse_with_ai(llm, message: str) -> dict[str, Any]:
    """
    使用 AI 模型解析用户消息，自动降级到正则匹配
    """
    try:
        return _call_ai(llm, message)
    except Exception as e:
        logger.warning("AI 解析失败（已重试 %d 次）: %s", AI_MAX_RETRIES, e)

        if FALLBACK_TO_REGEX:
            logger.info("降级到正则匹配解析: %s", message)
            return _fallback_regex_parse(message)
        else:
            return {
                "success": False,
                "error_msg": f"AI解析失败且未启用降级: {e}",
            }


# ── 正则降级解析 ──────────────────────────────────────────
def _fallback_regex_parse(text: str) -> dict[str, Any]:
    """
    正则匹配降级方案（与 handler.parse_message 等价）
    支持格式: "28 午餐" / "记账 28 午餐" / "28.5 打车"
    """
    import re
    from glob_config import DEFAULT_CATEGORY, DEFAULT_ACCOUNT

    cleaned = re.sub(r"^记账\s*", "", text.strip())
    match = re.match(r"(\d+(?:\.\d+)?)\s+(.+)", cleaned)
    if not match:
        return {
            "success": False,
            "error_msg": "请按格式发送：金额 描述（例如：28 午餐）",
        }
    try:
        amount = float(match.group(1))
        note = match.group(2).strip()
        if amount <= 0:
            return {"success": False, "error_msg": "金额必须大于0"}
        if not note:
            return {"success": False, "error_msg": "描述不能为空"}
        logger.info("正则降级解析成功: amount=%s, note=%s", amount, note)
        return {
            "amount": amount,
            "account": DEFAULT_ACCOUNT,
            "category": DEFAULT_CATEGORY,
            "note": note,
            "success": True,
            "error_msg": "",
        }
    except ValueError:
        return {"success": False, "error_msg": "金额格式错误"}


# ── 测试入口 ──────────────────────────────────────────────
if __name__ == "__main__":
    from logger_config import setup_logging
    setup_logging()

    user_message = "28 午餐"
    result = parse_with_ai(get_agent(), user_message)
    logger.info("解析结果: %s", result)
