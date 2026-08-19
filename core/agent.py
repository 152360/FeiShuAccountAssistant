"""
AI 模型模块
- 使用 LangChain + 硅基流动 API 构建记账 agent
- agent 通过工具调用完成记账 / 查账，输出自由文本
- AI 失败时自动降级到正则记账
"""

from typing import Any

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.messages import AIMessage

from config.glob_config import (
    SILICON_API_KEY,
    MODEL_NAME,
    SYSTEM_PROMPT,
    FALLBACK_TO_REGEX,
    BASE_URL,
)
from config.logger_config import get_logger
from core.tools import (
    get_past_datetime,
    get_account_records,
    add_account_record,
)
from utils import safe_str

logger = get_logger(__name__)


# ── 初始化模型 ────────────────────────────────────────────
_api_key = SILICON_API_KEY

if not _api_key:
    logger.warning(
        "环境变量 SILICON_API_KEY 未设置！AI 解析将不可用，"
        "会自动降级到正则匹配"
    )

_model = None
_agent = None
_tools = [get_past_datetime, get_account_records, add_account_record]


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
            base_url=BASE_URL,
            api_key=_api_key,
            temperature=0.7,
        )
        _agent = create_agent(
            model=_model,
            system_prompt=SYSTEM_PROMPT,
            tools=_tools,
        )
        logger.info("AI 模型初始化完成")
    except Exception as e:
        logger.error("AI 模型初始化失败: %s", e)
        raise


def get_agent():
    """获取 agent 实例（延迟初始化）"""
    _ensure_model()
    return _agent


# ── Agent 调用（自由文本输出）─────────────────────────────
def run_agent(agent, message: str) -> dict[str, Any]:
    """
    让 agent 完整处理一条用户消息，返回其自然语言回复。

    agent 会自主调用工具完成记账 / 查账；AI 处理失败时自动降级到正则记账。
    注意：这里刻意不做整体重试 —— agent 的工具调用可能已经产生副作用（写入
    表格），重试会导致重复记账，因此宁可降级到正则，也不重复写账。

    Returns:
        {"success": bool, "reply": str, "error_msg": str}
    """
    try:
        res = agent.invoke({"messages": [{"role": "user", "content": message}]})
        logger.debug("AI 原始返回: %s", safe_str(res))

        final_answer = _extract_final_answer(res)
        if final_answer:
            logger.info("AI 回复: %s", final_answer)
            return {
                "success": True,
                "error_msg": "",
                "reply": final_answer,
            }

        logger.error("AI 未返回有效回复: %s", safe_str(res))
        return {
            "success": False,
            "error_msg": "AI 未返回有效回复",
            "reply": "❌ AI 未返回有效回复，请稍后重试",
        }
    except Exception as e:
        logger.warning("AI 处理失败: %s", e)

        if FALLBACK_TO_REGEX:
            logger.info("降级到正则匹配记账: %s", message)
            return _fallback_regex_reply(message)
        else:
            return {
                "success": False,
                "error_msg": f"AI 处理失败且未启用降级: {e}",
                "reply": f"❌ AI 处理失败: {e}",
            }


def _extract_final_answer(result: dict) -> str:
    """
    从 agent 返回的消息列表中提取最终的自然语言回复。

    create_agent 的返回值包含完整消息链：用户消息、带工具调用的 AI 中间消息、
    工具返回消息、最终的 AI 消息。最后一条有正文且不含工具调用的 AI 消息即为
    最终回复。
    """
    messages = result.get("messages", [])
    for msg in reversed(messages):
        if not isinstance(msg, AIMessage):
            continue
        # 跳过“仅发起工具调用”的中间消息
        if getattr(msg, "tool_calls", None):
            continue
        content = msg.content
        if isinstance(content, str):
            text = content.strip()
            if text:
                return text
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = str(block.get("text") or "").strip()
                    if text:
                        parts.append(text)
            if parts:
                return "".join(parts).strip()
    return ""


# ── 正则降级记账 ──────────────────────────────────────────
def _fallback_regex_reply(text: str) -> dict[str, Any]:
    """
    正则降级方案：解析 "28 午餐" / "28.5 打车" 格式并直接记账。
    """
    parsed = _fallback_regex_parse(text)
    if not parsed["success"]:
        return {
            "success": False,
            "error_msg": parsed["error_msg"],
            "reply": f"❌ {parsed['error_msg']}",
        }

    try:
        tool_msg = add_account_record.invoke({
            "amount": parsed["amount"],
            "note": parsed["note"],
            "category": parsed["category"],
            "account": parsed["account"],
        })
        logger.info("正则降级记账成功: %s", tool_msg)
        return {
            "success": True,
            "error_msg": "",
            "reply": (
                f"✅ 记账成功\n"
                f"💰 {parsed['amount']}元 | {parsed['category']} | {parsed['account']}\n"
                f"📝 {parsed['note']}"
            ),
        }
    except Exception as e:
        logger.error("正则降级记账失败: %s", e)
        return {
            "success": False,
            "error_msg": f"记账失败: {e}",
            "reply": f"❌ 记账失败: {e}",
        }


def _fallback_regex_parse(text: str) -> dict[str, Any]:
    """
    正则匹配降级方案（与 handler.parse_message 等价）
    支持格式: "28 午餐" / "记账 28 午餐" / "28.5 打车"
    """
    import re
    from config.glob_config import DEFAULT_CATEGORY, DEFAULT_ACCOUNT

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
    from config.logger_config import setup_logging
    setup_logging()

    user_message = "28 午餐"
    result = run_agent(get_agent(), user_message)
    logger.info("处理结果: %s", result)
