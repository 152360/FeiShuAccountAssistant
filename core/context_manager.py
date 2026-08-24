"""
上下文存储 —— 摘要的 SQLite 持久化（Memory Storage）

在"自定义上下文管理"方案中负责摘要的**存储与读取**：压缩后的摘要以纯文本
存进本地 SQLite（agent_context.db），跨进程 / 重启后仍可恢复，供下一轮对话
注入模型上下文。压缩逻辑见 core/context_compressor.py。

表结构 context_summaries(id, content, created_at)：
    id          自增主键，即写入顺序
    content     摘要内容（历史摘要：/ 一周消费详情：/ N周消费详情：）
    created_at  写入时间（冗余字段，便于排查）
"""

import sqlite3
from typing import List


class ContextManager:
    """摘要存储层：基于 SQLite 的追加式摘要仓库。"""

    def __init__(self, db_path: str = "agent_context.db"):
        """
        :param db_path: SQLite 文件路径。测试可传 ":memory:" 使用内存库。
        """
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()

    def _init_db(self) -> None:
        """建表（幂等）。"""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS context_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    def get_summaries(self) -> List[str]:
        """获取所有摘要内容（按写入顺序从旧到新）。"""
        cursor = self.conn.execute(
            "SELECT content FROM context_summaries ORDER BY id"
        )
        return [row[0] for row in cursor.fetchall()]

    def add_summary(self, content: str) -> None:
        """添加一条新摘要。"""
        self.conn.execute(
            "INSERT INTO context_summaries (content) VALUES (?)", (content,)
        )
        self.conn.commit()

    def add_summaries(self, contents: List[str]) -> None:
        """批量添加多条新摘要（保持列表顺序）。"""
        if not contents:
            return
        self.conn.executemany(
            "INSERT INTO context_summaries (content) VALUES (?)",
            [(content,) for content in contents],
        )
        self.conn.commit()

    def clear(self) -> None:
        """清空所有摘要（压缩写回前调用，实现整库替换）。"""
        self.conn.execute("DELETE FROM context_summaries")
        self.conn.commit()

    def close(self) -> None:
        """关闭数据库连接。"""
        self.conn.close()
