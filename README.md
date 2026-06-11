# 飞书记账机器人

基于飞书开放平台的 AI 智能记账助手。通过飞书机器人接收用户消息，使用 AI 大模型自动解析消费金额、分类、账户和描述，写入飞书多维表格，并实时回复记账结果。全程使用 WebSocket 长连接，无需公网地址。

## 功能特性

- **AI 智能解析** — 使用大语言模型从自然语言中提取金额、分类、账户、备注
- **自动降级** — AI 服务不可用时自动回退到正则匹配，保证核心功能不中断
- **异步处理** — 收到消息立即回复确认，后台异步处理，避免飞书 3 秒超时
- **自动重试** — API 调用失败时指数退避重试，提高成功率
- **日志管理** — 双通道日志（控制台 + 轮转文件），错误日志独立存储
- **优雅关闭** — 支持 SIGTERM/SIGINT 信号，等待任务完成后安全退出
- **无需公网** — 使用飞书 WebSocket 长连接接收事件，适合云服务器部署

## 项目结构

```
FeiShuAccountAssistant/
├── main.py              # 主入口：长连接管理、消息路由、异步调度
├── agent.py             # AI 模型：LangChain 封装、结构化解析、正则降级
├── handler.py           # 表格操作：飞书多维表格读写（带重试）
├── glob_config.py       # 全局配置：凭证、模型参数、重试策略
├── logger_config.py     # 日志系统：控制台 + 轮转文件 + 错误分离
├── utils.py             # 工具函数：指数退避重试装饰器
├── requirements.txt     # 依赖清单
└── logs/                # 日志输出目录（自动创建，已 gitignore）
    ├── app.log
    ├── app.log.1
    └── error.log
```

## 环境要求

- Python 3.10+
- 飞书开发者账号（需创建企业自建应用）
- 硅基流动 API Key（用于 AI 模型推理）

## 环境搭建

### Windows

1. 访问 [Python 官网](https://www.python.org/downloads/) 下载安装包
2. 运行安装程序，勾选 **「Add Python to PATH」**，选择「Customize installation」按需调整组件
3. 安装完成后打开终端验证：
   ```bash
   python --version
   pip --version
   ```

### macOS

```bash
# 安装 Homebrew（如已安装可跳过）
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# 安装 Python
brew install python

# 验证
python3 --version
```

### Linux (Debian/Ubuntu)

```bash
sudo apt update
sudo apt install python3 python3-pip

# 验证
python3 --version
pip3 --version
```

### 安装项目依赖

```bash
cd FeiShuAccountAssistant
pip install -r requirements.txt
```

### 设置环境变量

```bash
# Linux / macOS
export SILICON_API_KEY="sk-your-api-key"

# Windows (cmd)
set SILICON_API_KEY=sk-your-api-key

# Windows (PowerShell)
$env:SILICON_API_KEY="sk-your-api-key"
```

可选配置：

```bash
export LOG_LEVEL=DEBUG    # 日志级别，默认 INFO（可选：DEBUG / WARNING / ERROR）
```

## 飞书配置

### 1. 创建企业自建应用

1. 登录 [飞书开发者后台](https://open.feishu.cn/app)
2. 创建「企业自建应用」，获取 **App ID** 和 **App Secret**

### 2. 开启权限

在应用「权限管理」中添加以下权限：

| 权限 | 用途 |
|------|------|
| `im:message:readonly` | 接收用户消息 |
| `im:message:reply` | 回复用户消息 |
| `bitable:app` | 读写多维表格 |

### 3. 创建多维表格

1. 在飞书中创建多维表格，包含以下列：**金额**（数字）、**分类**（文本）、**账户**（文本）、**备注**（文本）
2. 从表格 URL 中提取 `app_token` 和 `table_id`
3. 将表格共享给机器人（在表格右上角「…」→「更多」→「添加文档应用」）

### 4. 填写配置

编辑 `glob_config.py`：

```python
APP_ID     = "cli_xxxxxxxxxxxxx"   # 替换为你的 App ID
APP_SECRET = "xxxxxxxxxxxxxxxx"    # 替换为你的 App Secret
APP_TOKEN  = "xxxxxxxxxxxxxxxx"    # 替换为你的表格 app_token
TABLE_ID   = "tblxxxxxxxxxxxx"     # 替换为你的表格 table_id
```

> ⚠️ 当前代码中的凭证为示例值，部署前请务必替换。

## 运行

### 本地开发

```bash
python main.py
```

启动后输出示例：

```
==================================================
飞书记账机器人启动中...
日志目录: logs/
线程池大小: 5
==================================================
飞书 API 客户端初始化完成
AI 模型预热完成
飞书记账机器人已启动，等待消息...
```

### 云服务器部署（推荐 systemd）

创建服务文件 `/etc/systemd/system/feishu-bot.service`：

```ini
[Unit]
Description=飞书记账机器人
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/FeiShuAccountAssistant
Environment="SILICON_API_KEY=sk-your-api-key"
Environment="LOG_LEVEL=INFO"
ExecStart=/usr/bin/python3 /opt/FeiShuAccountAssistant/main.py
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable feishu-bot
sudo systemctl start feishu-bot
sudo systemctl status feishu-bot
```

查看日志：

```bash
# 应用日志
tail -f /opt/FeiShuAccountAssistant/logs/app.log

# 错误日志
tail -f /opt/FeiShuAccountAssistant/logs/error.log

# systemd 日志
journalctl -u feishu-bot -f
```

## 使用示例

在飞书中向机器人发送消息：

| 用户输入 | AI 解析结果 |
|----------|------------|
| `28 午餐` | 金额=28, 分类=餐饮, 账户=微信, 备注=午餐 |
| `打车花了35.5，支付宝` | 金额=35.5, 分类=交通, 账户=支付宝, 备注=打车 |
| `现金买药200，医疗报销` | 金额=200, 分类=医疗, 账户=现金, 备注=买药 |
| `268 超市购物` | 金额=268, 分类=购物, 账户=微信, 备注=超市购物 |

机器人回复示例：

```
✅ 记账成功
💰 28.0元 | 餐饮 | 微信
📝 午餐
```

## 配置参考

`glob_config.py` 中所有可配置项：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `APP_ID` | — | 飞书应用 App ID |
| `APP_SECRET` | — | 飞书应用 App Secret |
| `APP_TOKEN` | — | 多维表格 app_token |
| `TABLE_ID` | — | 多维表格 table_id |
| `DEFAULT_CATEGORY` | 餐饮 | 正则降级时默认分类 |
| `DEFAULT_ACCOUNT` | 微信 | 正则降级时默认账户 |
| `MODEL_NAME` | nex-agi/Nex-N2-Pro | AI 模型名称 |
| `AI_MAX_RETRIES` | 2 | AI 解析最大重试次数 |
| `AI_BASE_DELAY` | 1.0s | AI 重试基础延迟 |
| `API_MAX_RETRIES` | 2 | 飞书 API 最大重试次数 |
| `API_BASE_DELAY` | 0.5s | API 重试基础延迟 |
| `ASYNC_MAX_WORKERS` | 5 | 线程池最大并发数 |
| `FALLBACK_TO_REGEX` | True | AI 失败时是否降级正则 |

## 消息处理流程

```
用户发送消息
     │
     ▼
do_p2_im_message_receive_v1()    ← 飞书 WebSocket 回调
     │
     ├─ 去重检查
     ├─ 类型过滤（仅 text）
     │
     ▼
立即回复 "⏳ 收到，正在记账..."   ← 避免 3s 超时
     │
     ▼
async_process_message()          ← 提交到线程池
     │
     ├─ parse_with_ai()          ← AI 解析（重试 → 降级正则）
     ├─ add_account_record()     ← 写入表格（重试）
     └─ send_reply()             ← 回复最终结果
```

## 技术架构

| 层 | 技术选型 |
|----|---------|
| 消息接入 | 飞书 WebSocket 长连接（lark-oapi SDK） |
| AI 解析 | LangChain + 硅基流动（OpenAI 兼容 API） |
| 结构化输出 | Pydantic 模型 + LangChain response_format |
| 数据存储 | 飞书多维表格（Bitable API） |
| 并发模型 | `concurrent.futures.ThreadPoolExecutor` |
| 重试机制 | 指数退避 + 随机抖动（自研装饰器） |
| 日志 | Python logging + RotatingFileHandler |
| 进程管理 | systemd（推荐）/ 直接运行 |

## License

MIT
