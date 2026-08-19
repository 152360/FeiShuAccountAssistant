# 敏感配置优先从环境变量读取（systemd 部署时用 Environment 注入），
# 未设置时回退到下面的默认值，便于本地开发。
import os

# —— 硅基流动apikey配置 ——————————————
BASE_URL = "https://api.siliconflow.cn/v1"
SILICON_API_KEY = os.getenv("SILICON_API_KEY", "")

# ── 飞书应用凭证（从飞书开发者后台获取）────────────────
APP_ID = os.getenv("APP_ID", "")
APP_SECRET = os.getenv("APP_SECRET", "")

# ── 飞书多维表格信息（从表格 URL 中获取）────────────────
APP_TOKEN = os.getenv("APP_TOKEN", "")
TABLE_ID = os.getenv("TABLE_ID", "")
# —— 飞书多维表格的结构   ————————
TABLE_FIELD_NOTE = "备注"
TABLE_FIELD_CATEGORY = "分类"
TABLE_FIELD_TIME = "消费时间"
TABLE_FIELD_AMOUNT = "金额"

# ── 默认值 ─────────────────────────────────────────────
DEFAULT_CATEGORY = "餐饮"            # 当无法智能分类时使用的默认分类
DEFAULT_ACCOUNT = "微信"             # 默认支付账户

# ── AI 模型配置 ─────────────────────────────────────────
MODEL_NAME = "nex-agi/Nex-N2-Pro"
SYSTEM_PROMPT = """
你是飞书记账助手，帮用户记账和查账。你通过工具完成实际操作，并用自然语言回复用户。

## 工具（具体参数见各工具注释）
- add_account_record：新增一条记账记录。
- get_past_datetime：获取当前或过去某天的日期时间，用于确定查账时间范围。
- get_account_records：查询指定时间范围内的账单记录。

## 使用时机
- 用户描述一笔消费（如"28 午餐"、"打车花了35.5，支付宝"）→ 提取金额、分类、账户、描述，调用 add_account_record 记账。
- 用户要求查账（如"查一下最近的账单"、"这个月花了多少"）→ 先调用 get_past_datetime 确定时间范围，再调用 get_account_records 查询并汇总。
- 涉及"今天 / 昨天 / 最近X天"等相对时间时必须调用 get_past_datetime，严禁编造日期。

## 回复
- 始终用简洁友好的自然语言回复，禁止输出 JSON 或代码块。
- 一切以工具实际返回为准，不要编造结果。
- 消息既不是记账也不是查账时，礼貌说明你能做什么。
"""

# ── 重试配置 ─────────────────────────────────────────────
# 飞书 API 调用（agent 调用刻意不重试，避免工具副作用导致重复记账）
API_MAX_RETRIES = 2          # 飞书 API 最多重试次数
API_BASE_DELAY = 0.5         # 重试基础延迟（秒）
# 异步处理
ASYNC_MAX_WORKERS = 5        # 线程池最大并发数

# ── 降级策略 ─────────────────────────────────────────────
# AI 解析失败时是否回退到正则匹配
FALLBACK_TO_REGEX = True