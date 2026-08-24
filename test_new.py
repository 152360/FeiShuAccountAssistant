"""HistoryCompressor（自定义上下文管理）的三级压缩单元测试。"""
import unittest
import json
from datetime import datetime, timedelta

from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

from core.context_manager import ContextManager
from core.context_compressor import HistoryCompressor


class TestHistoryCompressor(unittest.TestCase):

    def setUp(self):
        # 每个用例用独立的 SQLite 内存库，互不影响
        self.manager = ContextManager(db_path=":memory:")
        self.compressor = HistoryCompressor(self.manager)

    def test_combine_two_weeks(self):
        """两条周摘要应合并为一条 N 周消费详情，且丢弃其它消息。"""
        week1 = AIMessage(content='一周消费详情：{"总消费": 150.0, "餐饮": 100.0, "交通": 50.0}')
        week2 = AIMessage(content='一周消费详情：{"总消费": 80.0, "餐饮": 30.0, "娱乐": 50.0}')
        final_ai = AIMessage(content="记账成功", tool_calls=[])

        self.compressor.compress_and_store([week1, week2, final_ai])

        stored = self.manager.get_summaries()
        self.assertEqual(len(stored), 1)
        merged = stored[0]
        self.assertTrue(merged.startswith("2周消费详情："))
        data = json.loads(merged.split("：", 1)[1])
        self.assertEqual(data["总消费"], 230.0)
        self.assertEqual(data["餐饮"], 130.0)
        self.assertEqual(data["交通"], 50.0)
        self.assertEqual(data["娱乐"], 50.0)

    def test_no_combine_less_than_two_weeks(self):
        """周摘要不足两条时原样保留；本轮无记账不生成历史摘要。"""
        week1 = AIMessage(content='一周消费详情：{"总消费": 150.0, "餐饮": 100.0}')
        final_ai = AIMessage(content="记账成功", tool_calls=[])

        self.compressor.compress_and_store([week1, final_ai])

        stored = self.manager.get_summaries()
        self.assertEqual(len(stored), 1)
        self.assertTrue(stored[0].startswith("一周消费详情："))

    def test_full_scenario_with_summary_and_weeks(self):
        """旧摘要升级为周摘要 + 两条周摘要合并 + 本轮记账生成新历史摘要。"""
        # 两条旧周详情
        week1 = AIMessage(content='一周消费详情：{"总消费": 100, "餐饮": 100}')
        week2 = AIMessage(content='一周消费详情：{"总消费": 200, "交通": 200}')

        # 一条 10 天前的旧摘要，确保触发周详情生成
        ten_days_ago = datetime.now() - timedelta(days=10)
        old_summary_content = (
            f"历史摘要：时间：{ten_days_ago.strftime('%Y-%m-%d %H:%M:%S')}；"
            f"记账：写入表格: amount=50.0, category=娱乐, account=微信, note=电影"
        )
        old_summary = AIMessage(content=old_summary_content)

        # 本轮一笔记账
        human = HumanMessage(content="午餐30元")
        ai_tool = AIMessage(
            content="",
            tool_calls=[{"id": "call1", "name": "add_account_record",
                         "args": {"amount": 30, "category": "餐饮"}}],
        )
        tool = ToolMessage(content="写入表格: amount=30.0, category=餐饮", tool_call_id="call1")
        final = AIMessage(content="记账成功", tool_calls=[])

        self.compressor.compress_and_store(
            [week1, week2, old_summary, human, ai_tool, tool, final]
        )

        stored = self.manager.get_summaries()
        # 预期 3 条：合并周详情（2周）、新周详情（来自旧摘要）、新历史摘要
        self.assertEqual(len(stored), 3)

        merged = [s for s in stored if s.startswith("2周消费详情：")]
        new_week = [s for s in stored if s.startswith("一周消费详情：")]
        new_summary = [s for s in stored if s.startswith("历史摘要：")]

        self.assertEqual(len(merged), 1)
        self.assertEqual(len(new_week), 1)
        self.assertEqual(len(new_summary), 1)

        # 验证合并内容
        data = json.loads(merged[0].split("：", 1)[1])
        self.assertEqual(data["总消费"], 300)
        self.assertEqual(data["餐饮"], 100)
        self.assertEqual(data["交通"], 200)

        # 验证新周详情内容（来自旧摘要的娱乐50）
        new_week_data = json.loads(new_week[0].split("：", 1)[1])
        self.assertEqual(new_week_data["总消费"], 50)
        self.assertEqual(new_week_data["娱乐"], 50)

        # 验证新摘要包含最新记账
        self.assertIn("用户消息：午餐30元", new_summary[0])

    def test_query_only_turn_keeps_no_history_summary(self):
        """纯查账轮次（无记账工具调用）不应产生历史摘要。"""
        human = HumanMessage(content="查一下最近7天的账单")
        ai_tool = AIMessage(
            content="",
            tool_calls=[{"id": "call2", "name": "get_account_records",
                         "args": {"start_time_str": "x", "end_time_str": "y"}}],
        )
        tool = ToolMessage(content="| 金额 | 分类 |", tool_call_id="call2")
        final = AIMessage(content="这是你的账单", tool_calls=[])

        self.compressor.compress_and_store([human, ai_tool, tool, final])

        # 没有记账 → 不生成历史摘要
        self.assertEqual(self.manager.get_summaries(), [])


if __name__ == "__main__":
    unittest.main()
