"""
上下文压缩 —— 对话历史的三级摘要压缩（Memory / Context Compression）

本模块承担"自定义上下文管理"方案中的**压缩**职责：把一轮对话的原始消息压缩
成三级摘要字符串，交给 ContextManager 持久化到 SQLite，供下一轮对话注入模型
上下文。存储层见 core/context_manager.py。

（背景：早期方案使用 LangGraph 检查点 + AgentMiddleware 在 after_model 中自动
压缩，但实测发现 agent.invoke 的返回值是检查点执行之后的结果——最终 AI 回复
已被中间件裁剪，导致取不到最终回复。因此改为在 run_agent 中显式编排：先加载
摘要，再注入输入，拿到完整回复后再压缩并写回，彻底摆脱检查点。）

三级摘要逐级折叠，历史越久粒度越粗，模型始终只保留最近一轮的细节：

    一级 历史摘要（历史摘要：）
         最近一轮"用户输入 + 记账结果"折叠为一条摘要，只留消费事实。

    二级 周摘要（一周消费详情：）
         距今 >= 7 天的历史摘要按分类聚合成 {"总消费": X, "分类": 金额}。

    三级 数周摘要（N周消费详情：）
         累积 >= 2 条周摘要时，各周按分类合并为一条 N 周摘要。
"""

import json
import re
from datetime import datetime

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from config.logger_config import get_logger
from core.context_manager import ContextManager

logger = get_logger(__name__)

# ── 摘要前缀（模型据此识别各级摘要）─────────────────────────
HISTORY_SUMMARY_PREFIX = "历史摘要："          # 一级：历史摘要
WEEK_SUMMARY_PREFIX = "一周消费详情："          # 二级：单周摘要
# 三级："N周消费详情："，N 为被合并的周数（见 _merge_weeks）

# ── 压缩阈值 ───────────────────────────────────────────────
WEEK_PROMOTE_DAYS = 7       # 历史摘要距今超过该天数时升为周摘要
WEEKS_TO_MERGE = 2          # 周摘要达到该数量时合并为"数周摘要"

# 只把记账工具的结果写进摘要；查账工具返回的表格太大，一律丢弃
RECORD_TOOL_NAME = "add_account_record"

# 历史摘要中"时间"字段的格式
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class HistoryCompressor:
    """
    三级摘要压缩器：把一轮对话压缩成摘要，经 ContextManager 持久化。

    用法（在 run_agent 中显式编排，取代检查点自动压缩）：

        1. load_summaries()              —— 读取已存摘要，包装成 AIMessage 注入上下文；
        2. agent.invoke(...)             —— 携带"摘要 + 用户消息"走正常 Agent 流程；
        3. compress_and_store(messages)  —— 对整轮消息做三级压缩，写回存储。
    """

    def __init__(self, manager: ContextManager):
        """绑定摘要存储层。"""
        self.manager = manager

    # ── 读取：加载历史摘要注入模型上下文 ─────────────────────
    def load_summaries(self) -> list[AIMessage]:
        """把已存储的摘要字符串包装成 AIMessage 列表（按时间从旧到新）。"""
        return [
            AIMessage(content=content)
            for content in self.manager.get_summaries()
        ]

    # ── 写入：对一轮对话做三级压缩并落库 ─────────────────────
    def compress_and_store(self, messages: list) -> None:
        """
        对一轮完整对话消息做三级压缩，把结果写回存储。

        :param messages: agent.invoke 返回的完整消息链（含本轮注入的旧摘要、
                         用户消息、工具调用、工具返回、最终 AI 回复）。

        仅当本轮已产出最终回复（最后一条为不含工具调用的 AI 消息）时才压缩，
        否则模型仍在调用工具、对话尚未结束，直接跳过。
        """
        if not messages:
            return

        last_msg = messages[-1]
        if not (isinstance(last_msg, AIMessage) and not last_msg.tool_calls):
            return

        # ── 1. 按类型拆分消息 ──
        # 系统提示词始终不参与压缩；其余消息分成各级摘要与"其它消息"。
        non_system = [m for m in messages if not isinstance(m, SystemMessage)]
        summary_msgs = _filter_by_prefix(non_system, HISTORY_SUMMARY_PREFIX)
        week_msgs = _filter_by_prefix(non_system, WEEK_SUMMARY_PREFIX)
        other_msgs = [
            m for m in non_system
            if m not in summary_msgs and m not in week_msgs
        ]

        # ── 2. 三级压缩：周摘要 → 数周摘要 ──
        #    周摘要达到 WEEKS_TO_MERGE 条时合并为一条；不足则原样保留。
        weeks = _merge_weeks(week_msgs) or [m.content for m in week_msgs]

        # ── 3. 二级压缩：历史摘要 → 周摘要 ──
        #    距今 >= WEEK_PROMOTE_DAYS 天的历史摘要折叠为周摘要；
        #    没有够老的摘要则原样保留，继续积累。
        summaries = (
            _promote_old_summaries(summary_msgs)
            or [m.content for m in summary_msgs]
        )

        # ── 4. 一级压缩：其它消息 → 历史摘要 ──
        #    本轮没有成功记账（纯查账 / 闲聊）时不生成历史摘要，避免记忆噪音。
        history = _build_history_summary(other_msgs) or []

        # ── 5. 写回存储（保持顺序：数周 → 周 → 历史摘要）──
        new_messages = weeks + summaries + history
        logger.debug("上下文压缩后待存储: %s", new_messages)
        self.manager.clear()
        self.manager.add_summaries(new_messages)


# ═══════════════════════════════════════════════════════════
# 一级压缩：历史摘要
# ═══════════════════════════════════════════════════════════
def _build_history_summary(other_msgs: list) -> list[str] | None:
    """
    把"用户输入 + 记账结果"折叠成一条历史摘要（一级压缩）。

    - 用户消息       → "用户消息：{内容}；"
    - 记账工具的结果 → "时间：{now}；记账：{工具返回}"（仅 add_account_record）
    - 查账等其它工具的结果、机器人的最终回复 → 丢弃

    摘要中的"时间"统一取当前时间：7 天后该摘要即满足升级为周摘要的条件，
    实现"多久前的消费算历史"这一时间锚点。

    本轮没有成功记账时返回 None（纯查账 / 闲聊不生成历史摘要）。
    """
    content = HISTORY_SUMMARY_PREFIX
    tool_name_by_id: dict[str, str] = {}   # tool_call_id -> 工具名
    had_record = False                       # 本轮是否成功记账

    for msg in other_msgs:
        if isinstance(msg, HumanMessage):
            content += f"用户消息：{msg.content}；"
        elif isinstance(msg, AIMessage) and msg.tool_calls:
            # 记录工具调用 id，后续据此把 ToolMessage 关联到工具名
            for call in msg.tool_calls:
                tool_name_by_id[call["id"]] = call["name"]
        elif isinstance(msg, ToolMessage):
            tool_name = tool_name_by_id.get(msg.tool_call_id)
            if tool_name != RECORD_TOOL_NAME:
                continue  # 非记账工具的结果不进摘要，避免塞入查账大表格
            had_record = True
            now_time = datetime.now().strftime(TIME_FORMAT)
            content += f"时间：{now_time}；记账：{msg.content}"

    return [content] if had_record else None


# ═══════════════════════════════════════════════════════════
# 二级压缩：历史摘要 → 周摘要
# ═══════════════════════════════════════════════════════════
def _promote_old_summaries(summary_msgs: list[AIMessage]) -> list[str] | None:
    """
    把距今 >= WEEK_PROMOTE_DAYS 天的历史摘要升级为周摘要（二级压缩）。

    从最旧的摘要开始扫描，找到第一条"够老"的摘要，将其及其之后的所有摘要
    聚合成一条"一周消费详情"；没有够老的摘要则返回 None（交给调用方原样保留）。

    返回新生成的周摘要列表，或 None。
    """
    for i, msg in enumerate(summary_msgs):
        content = msg.content if isinstance(msg.content, str) else ""
        fields = _parse_summary_fields(content)
        try:
            old_dt = (
                datetime.strptime(fields["time"], TIME_FORMAT)
                if fields.get("time") else None
            )
        except (TypeError, ValueError):
            old_dt = None
        if old_dt is None:
            continue  # 时间缺失 / 非法，无法判断新旧，跳过

        if _days_since(old_dt) >= WEEK_PROMOTE_DAYS:
            return [_aggregate_week_details(i, summary_msgs)]

    return None


def _aggregate_week_details(start: int, messages: list[AIMessage]) -> str:
    """
    把 messages[start:] 内的历史摘要按分类聚合成一条周摘要。

    返回格式："一周消费详情：{"总消费": X, "分类": Y, ...}"
    """
    details: dict = {"总消费": 0.0}
    for msg in messages[start:]:
        content = msg.content if isinstance(msg.content, str) else ""
        if not content.startswith(HISTORY_SUMMARY_PREFIX):
            continue
        fields = _parse_summary_fields(content)
        try:
            amount = float(fields.get("amount", ""))
        except (TypeError, ValueError):
            continue  # 无金额（记账失败或纯查询摘要），无法聚合，跳过
        category = fields.get("category")
        if not category:
            continue
        details[category] = details.get(category, 0.0) + amount
        details["总消费"] += amount

    return WEEK_SUMMARY_PREFIX + json.dumps(details, ensure_ascii=False)


# ═══════════════════════════════════════════════════════════
# 三级压缩：周摘要 → 数周摘要
# ═══════════════════════════════════════════════════════════
def _merge_weeks(week_msgs: list[AIMessage]) -> list[str] | None:
    """
    把 >= WEEKS_TO_MERGE 条周摘要按分类合并为一条"N 周消费详情"。

    周摘要不足 WEEKS_TO_MERGE 条时返回 None（交给调用方原样保留）。

    返回合并后的单元素列表，或 None。
    """
    if len(week_msgs) < WEEKS_TO_MERGE:
        return None

    merged: dict = {"总消费": 0.0}
    for msg in week_msgs:
        content = msg.content if isinstance(msg.content, str) else ""
        try:
            # 去掉"一周消费详情："前缀后即为 JSON
            week_data = json.loads(content[len(WEEK_SUMMARY_PREFIX):])
        except ValueError:
            continue  # 摘要格式异常，跳过该条
        for key, value in week_data.items():
            if key == "总消费":
                merged[key] += value
            else:
                merged[key] = merged.get(key, 0.0) + value

    return [f"{len(week_msgs)}周消费详情：" + json.dumps(merged, ensure_ascii=False)]


# ═══════════════════════════════════════════════════════════
# 通用辅助函数
# ═══════════════════════════════════════════════════════════
def _filter_by_prefix(messages: list, prefix: str) -> list[AIMessage]:
    """筛选出 content 以指定前缀开头的 AI 消息（即某一级摘要）。"""
    return [
        m for m in messages
        if isinstance(m, AIMessage)
        and isinstance(m.content, str)
        and m.content.startswith(prefix)
    ]


def _parse_summary_fields(text: str) -> dict[str, str | None]:
    """
    从历史摘要中解析出时间、金额、分类。

    示例：
        历史摘要：时间：2026-08-20 12:00:00；记账：写入表格: amount=50.0, category=娱乐, ...
    返回：
        {"time": "2026-08-20 12:00:00", "amount": "50.0", "category": "娱乐"}
    """
    fields: dict[str, str | None] = {}

    # 时间：取"时间："之后、下一个分号之前的字符
    time_match = re.search(r"时间：([^；]+)", text)
    fields["time"] = time_match.group(1).strip() if time_match else None

    # 金额与分类：从"写入表格:"之后解析逗号分隔的键值对
    table_match = re.search(r"写入表格:\s*(.+)", text)
    if table_match:
        for item in table_match.group(1).split(","):
            item = item.strip()
            if item.startswith("amount="):
                fields["amount"] = item.split("=", 1)[1]
            elif item.startswith("category="):
                fields["category"] = item.split("=", 1)[1]

    return fields


def _days_since(dt: datetime) -> int:
    """返回该日期距今的天数（只比较日期部分，忽略时间）。"""
    return (datetime.now().date() - dt.date()).days
