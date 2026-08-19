# 飞书记账机器人

基于飞书开放平台的 AI 智能记账助手。通过飞书机器人接收用户消息，由 AI Agent 自主调用工具完成记账、查账，写入飞书多维表格，并实时回复结果。全程使用 WebSocket 长连接，无需公网地址。

## 功能特性

- **Agent 工具调用** — 使用 LangChain `create_agent` 构建 agent，自主调用记账/查账/取时间工具
- **自由文本回复** — agent 以自然语言回复用户，记账、查账结果一目了然
- **自动降级** — AI 服务不可用时自动回退到正则记账，保证核心功能不中断
- **异步处理** — 收到消息立即回复确认，后台异步处理，避免飞书 3 秒超时
- **日志管理** — 双通道日志（控制台 + 轮转文件），错误日志独立存储
- **优雅关闭** — 支持 SIGTERM/SIGINT 信号，等待任务完成后安全退出
- **无需公网** — 使用飞书 WebSocket 长连接接收事件，适合云服务器部署

## 项目结构

```
FeiShuAccountAssistant/
├── main.py                  # 主入口：长连接管理、消息路由、异步调度
├── core/
│   ├── agent.py             # AI Agent：LangChain 封装、自由文本输出、正则降级
│   ├── tools.py             # 工具定义：记账 / 查账 / 取时间（@tool）
│   ├── client.py            # 飞书 API 客户端（单例）
│   └── table_operation.py   # 表格操作：飞书多维表格写入（带重试）
├── config/
│   ├── glob_config.py       # 全局配置：凭证、系统提示词、重试策略
│   └── logger_config.py     # 日志系统：控制台 + 轮转文件 + 错误分离
├── utils.py                 # 工具函数：指数退避重试装饰器
├── requirements.txt         # 依赖清单
├── deploy.sh                # Linux 一键部署脚本（systemd 封装）
├── deploy/
│   └── feishu-account-assistant.service   # systemd 服务单元文件
└── config/logs/             # 日志输出目录（自动创建，已 gitignore）
    ├── app.log
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

敏感配置优先从环境变量读取，未设置时回退到 `config/glob_config.py` 中填写的默认值（便于本地开发）：

| 环境变量 | 说明 |
|----------|------|
| `SILICON_API_KEY` | 硅基流动 API Key（AI 模型推理） |
| `APP_ID` | 飞书应用 App ID |
| `APP_SECRET` | 飞书应用 App Secret |
| `APP_TOKEN` | 多维表格 app_token |
| `TABLE_ID` | 多维表格 table_id |
| `LOG_LEVEL` | 日志级别，默认 INFO（DEBUG / WARNING / ERROR） |

```bash
# Linux / macOS
export SILICON_API_KEY="sk-your-api-key"

# Windows (cmd)
set SILICON_API_KEY=sk-your-api-key

# Windows (PowerShell)
$env:SILICON_API_KEY="sk-your-api-key"
```

> 提示：本地开发可以直接把凭证写进 `glob_config.py`；部署到服务器时建议通过 `.env` / systemd `Environment=` 注入，避免凭证入库。

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

### 云服务器部署（推荐 systemd + 一键脚本）

项目内置 [deploy.sh](deploy.sh) 和 [deploy/feishu-account-assistant.service](deploy/feishu-account-assistant.service)，一条命令即可完成：装依赖 → 拉代码 → 建虚拟环境 → 生成配置 → 安装并启动 systemd 服务。

**1. 一键部署**

```bash
# 在服务器上执行（支持 Debian/Ubuntu、RHEL/CentOS/Alibaba Cloud Linux）
sudo bash -c "$(curl -fsSL https://raw.githubusercontent.com/152360/FeiShuAccountAssistant/main/deploy.sh)"
```

或将仓库克隆到服务器后本地执行：

```bash
git clone https://github.com/152360/FeiShuAccountAssistant
cd FeiShuAccountAssistant
sudo bash deploy.sh
```

脚本会交互式提示填写 `SILICON_API_KEY / APP_ID / APP_SECRET / APP_TOKEN / TABLE_ID`（直接回车使用 `glob_config.py` 中的默认值），生成 `/opt/feishu-account-assistant/.env`（权限 600）并创建专用运行用户 `feishubot`。

**2. 服务管理**

```bash
sudo systemctl status feishu-account-assistant   # 查看状态
sudo systemctl restart feishu-account-assistant  # 重启
sudo systemctl stop feishu-account-assistant     # 停止
sudo systemctl enable feishu-account-assistant   # 开机自启（部署时已默认开启）
```

**3. 查看日志**

```bash
journalctl -u feishu-account-assistant -f                     # systemd 实时日志
tail -f /opt/feishu-account-assistant/config/logs/app.log     # 应用日志
tail -f /opt/feishu-account-assistant/config/logs/error.log   # 错误日志
```

**4. 更新 / 升级**

```bash
# 提交并推送代码后，再次运行同一脚本即可拉取最新代码并重启服务
sudo bash deploy.sh
```

**5. 手动部署（不用脚本时）**

```bash
# 以 root 执行
INSTALL_DIR=/opt/feishu-account-assistant
git clone -b main https://github.com/152360/FeiShuAccountAssistant $INSTALL_DIR
cd $INSTALL_DIR
python3.11 -m venv venv && venv/bin/pip install -r requirements.txt

# 写入敏感配置
cat > .env <<EOF
SILICON_API_KEY=sk-your-api-key
APP_ID=cli_xxx
APP_SECRET=xxx
APP_TOKEN=xxx
TABLE_ID=tblxxx
LOG_LEVEL=INFO
EOF
chmod 600 .env

# 安装 systemd 服务
cp deploy/feishu-account-assistant.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now feishu-account-assistant
```

> ⚠️ 部署说明：`deploy.sh` 通过 git 拉取已提交的代码，**部署前请先把本地改动 commit 并 push**。`.env` 已被 gitignore，不会进入仓库。

## 使用示例

在飞书中向机器人发送消息：

| 用户输入 | 机器人行为 |
|----------|-----------|
| `28 午餐` | 提取金额/分类/账户 → 调用 `add_account_record` 记账 → 回复结果 |
| `打车花了35.5，支付宝` | 提取金额=35.5, 分类=交通, 账户=支付宝 → 记账 |
| `现金买药200，医疗报销` | 提取金额=200, 分类=医疗, 账户=现金 → 记账 |
| `查一下最近7天的账单` | 调用 `get_past_datetime` + `get_account_records` → 汇总回复 |

机器人记账回复示例（由 agent 自由生成）：

```
✅ 记账成功！
💰 28元 | 餐饮 | 微信
📝 午餐
```

## 配置参考

`config/glob_config.py` 中所有可配置项。标 🔧 的项优先从同名环境变量读取（部署时通过 `.env` 注入），未设置时使用默认值：

| 配置项 | 环境变量 | 默认值 | 说明 |
|--------|----------|--------|------|
| 🔧 `SILICON_API_KEY` | `SILICON_API_KEY` | — | 硅基流动 API Key |
| 🔧 `APP_ID` | `APP_ID` | — | 飞书应用 App ID |
| 🔧 `APP_SECRET` | `APP_SECRET` | — | 飞书应用 App Secret |
| 🔧 `APP_TOKEN` | `APP_TOKEN` | — | 多维表格 app_token |
| 🔧 `TABLE_ID` | `TABLE_ID` | — | 多维表格 table_id |
| `DEFAULT_CATEGORY` | — | 餐饮 | 正则降级时默认分类 |
| `DEFAULT_ACCOUNT` | — | 微信 | 正则降级时默认账户 |
| `MODEL_NAME` | — | nex-agi/Nex-N2-Pro | AI 模型名称 |
| `SYSTEM_PROMPT` | — | — | agent 系统提示词（工具调用行为） |
| `API_MAX_RETRIES` | — | 2 | 飞书 API 最大重试次数 |
| `API_BASE_DELAY` | — | 0.5s | API 重试基础延迟 |
| `ASYNC_MAX_WORKERS` | — | 5 | 线程池最大并发数 |
| `FALLBACK_TO_REGEX` | — | True | AI 失败时是否降级正则 |

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
     └─ run_agent()              ← agent 自主调用工具
         ├─ get_past_datetime()       ← 计算查账时间范围
         ├─ get_account_records()     ← 查账
         ├─ add_account_record()      ← 记账（AI 失败时降级正则记账）
         └─ send_reply()              ← 回复 agent 自由文本结果
```

## 技术架构

| 层 | 技术选型 |
|----|---------|
| 消息接入 | 飞书 WebSocket 长连接（lark-oapi SDK） |
| Agent | LangChain `create_agent` + 硅基流动（OpenAI 兼容 API） |
| 工具调用 | LangChain `@tool` 定义记账 / 查账 / 取时间 |
| 数据存储 | 飞书多维表格（Bitable API） |
| 并发模型 | `concurrent.futures.ThreadPoolExecutor` |
| 重试机制 | 指数退避 + 随机抖动（装饰器，用于飞书 API） |
| 日志 | Python logging + RotatingFileHandler |
| 进程管理 | systemd（推荐）/ 直接运行 |

## License

MIT
