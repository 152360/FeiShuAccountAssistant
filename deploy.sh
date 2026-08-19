#!/usr/bin/env bash
# =============================================================================
# 飞书记账助手一键部署脚本
# -----------------------------------------------------------------------------
# 支持系统：Debian/Ubuntu、RHEL/CentOS/Alibaba Cloud Linux
#
# 用法：
#   sudo bash deploy.sh        # 首次部署
#   sudo bash deploy.sh        # 再次运行 = 更新代码 + 重启服务
#
# 可通过环境变量覆盖的配置：
#   REPO_URL      git 仓库地址（默认 https://github.com/152360/FeiShuAccountAssistant）
#   BRANCH        分支（默认 main）
#   INSTALL_DIR   安装目录（默认 /opt/feishu-account-assistant）
#   APP_USER      服务运行用户（默认 feishubot）
#   PIP_INDEX_URL pip 镜像源，国内可设为 https://mirrors.aliyun.com/pypi/simple/
#   敏感配置      SILICON_API_KEY / APP_ID / APP_SECRET / APP_TOKEN / TABLE_ID
#                 已在环境中设置、或 /opt/feishu-account-assistant/.env 已存在时不会重复询问
# =============================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/152360/FeiShuAccountAssistant}"
BRANCH="${BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/feishu-account-assistant}"
APP_USER="${APP_USER:-feishubot}"
PIP_INDEX_URL="${PIP_INDEX_URL:-}"
SERVICE_NAME="feishu-account-assistant"
ENV_FILE="$INSTALL_DIR/.env"

GREEN='\033[1;32m'; YELLOW='\033[1;33m'; RED='\033[1;31m'; NC='\033[0m'
log()  { printf "${GREEN}[deploy]${NC} %s\n" "$*"; }
warn() { printf "${YELLOW}[deploy]${NC} %s\n" "$*"; }
die()  { printf "${RED}[deploy]${NC} %s\n" "$*" >&2; exit 1; }

# ── 0. 前置检查 ──────────────────────────────────────────
[ "$(id -u)" -eq 0 ] || die "请使用 root 或 sudo 运行：sudo bash deploy.sh"

# ── 1. 安装系统依赖，并选出一个 Python 3.10+ ─────────────
PYTHON_BIN=""
install_pkg() { # 参数为包名列表，交给检测到的包管理器安装
    if command -v apt-get >/dev/null 2>&1; then
        apt-get install -y "$@"
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y "$@"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y "$@"
    else
        die "未检测到 apt/dnf/yum，请手动安装 Python 3.10+ 与 git"
    fi
}

if command -v apt-get >/dev/null 2>&1; then
    log "检测到 apt（Debian/Ubuntu），更新并安装依赖..."
    apt-get update -y
    install_pkg git python3 python3-venv python3-pip
elif command -v dnf >/dev/null 2>&1; then
    log "检测到 dnf（RHEL/Alibaba Cloud Linux），更新并安装依赖..."
    dnf makecache -y || true
    # Alibaba Cloud Linux 基础源自带 python3.11，优先使用
    if dnf install -y git python3.11 python3.11-pip >/dev/null 2>&1; then
        PYTHON_BIN="python3.11"
    else
        install_pkg git python3 python3-pip
    fi
else
    log "检测到 yum（CentOS/RHEL），更新并安装依赖..."
    if yum install -y git python3.11 python3.11-pip >/dev/null 2>&1; then
        PYTHON_BIN="python3.11"
    else
        install_pkg git python3 python3-pip
    fi
fi

# 在已安装的解释器中挑一个版本 >= 3.10 的
pick_python() {
    for c in python3.12 python3.11 python3.10 "$PYTHON_BIN" python3; do
        [ -n "$c" ] || continue
        if command -v "$c" >/dev/null 2>&1 \
            && "$c" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
            PYTHON_BIN="$c"
            return 0
        fi
    done
    return 1
}
pick_python || die "需要 Python 3.10+（可通过 Python 官方源码编译，或安装较新发行版）"
log "使用 Python: $PYTHON_BIN"

# ── 2. 创建专用运行用户 ──────────────────────────────────
if id "$APP_USER" >/dev/null 2>&1; then
    log "用户 $APP_USER 已存在"
else
    useradd --system --no-create-home --shell /usr/sbin/nologin "$APP_USER"
    log "已创建系统用户 $APP_USER（无登录权限）"
fi

# ── 3. 拉取 / 更新代码 ───────────────────────────────────
git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
if [ -d "$INSTALL_DIR/.git" ]; then
    log "检测到已有仓库，拉取最新代码（分支 $BRANCH）..."
    cd "$INSTALL_DIR"
    git fetch --depth 1 origin "$BRANCH"
    git checkout -q "$BRANCH" 2>/dev/null || git checkout -q -b "$BRANCH" "origin/$BRANCH" 2>/dev/null || true
    git pull --ff-only origin "$BRANCH" \
        || die "git 更新失败：$INSTALL_DIR 存在本地未提交改动。请先处理：cd $INSTALL_DIR && git status"
else
    [ -e "$INSTALL_DIR" ] && [ -n "$(ls -A "$INSTALL_DIR" 2>/dev/null)" ] \
        && die "目录 $INSTALL_DIR 非空且不是 git 仓库，请处理后再试"
    log "克隆仓库 $REPO_URL（分支 $BRANCH）→ $INSTALL_DIR ..."
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$INSTALL_DIR"
fi

# ── 4. 创建虚拟环境并安装依赖 ────────────────────────────
if [ ! -x "$INSTALL_DIR/venv/bin/python" ]; then
    log "创建虚拟环境 ..."
    "$PYTHON_BIN" -m venv "$INSTALL_DIR/venv"
fi

PIP_ARGS=()
[ -n "$PIP_INDEX_URL" ] && PIP_ARGS=(-i "$PIP_INDEX_URL")
log "安装依赖（pip 镜像：${PIP_INDEX_URL:-官方源}）..."
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip "${PIP_ARGS[@]}" >/dev/null
"$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt" "${PIP_ARGS[@]}"

# 代码、虚拟环境、日志目录都归属运行用户
chown -R "$APP_USER:$APP_USER" "$INSTALL_DIR"

# ── 5. 生成敏感配置 .env（已存在则保留）──────────────────
cfg_default() { # 从 glob_config.py 中提取某项的回退默认值
    sed -n "s/^$1 * *= *['\"]\([^'\"]*\)['\"].*/\1/p" "$INSTALL_DIR/config/glob_config.py" | head -1
}
ask_value() { # 交互式询问，直接回车则使用默认值
    local name="$1" default="$2" v
    printf "  %-16s [%s]: " "$name" "$default"
    read -r v
    [ -n "$v" ] && echo "$v" || echo "$default"
}

if [ -f "$ENV_FILE" ]; then
    log "已存在 $ENV_FILE，保留现有配置（如需修改请直接编辑该文件）"
else
    log "生成 $ENV_FILE（直接回车使用括号内默认值）..."
    SILICON_API_KEY="${SILICON_API_KEY:-$(cfg_default SILICON_API_KEY)}"
    APP_ID="${APP_ID:-$(cfg_default APP_ID)}"
    APP_SECRET="${APP_SECRET:-$(cfg_default APP_SECRET)}"
    APP_TOKEN="${APP_TOKEN:-$(cfg_default APP_TOKEN)}"
    TABLE_ID="${TABLE_ID:-$(cfg_default TABLE_ID)}"

    SILICON_API_KEY="$(ask_value "SILICON_API_KEY" "$SILICON_API_KEY")"
    APP_ID="$(ask_value "APP_ID" "$APP_ID")"
    APP_SECRET="$(ask_value "APP_SECRET" "$APP_SECRET")"
    APP_TOKEN="$(ask_value "APP_TOKEN" "$APP_TOKEN")"
    TABLE_ID="$(ask_value "TABLE_ID" "$TABLE_ID")"

    cat > "$ENV_FILE" <<EOF
SILICON_API_KEY=$SILICON_API_KEY
APP_ID=$APP_ID
APP_SECRET=$APP_SECRET
APP_TOKEN=$APP_TOKEN
TABLE_ID=$TABLE_ID
LOG_LEVEL=${LOG_LEVEL:-INFO}
EOF
    chown "$APP_USER:$APP_USER" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    log ".env 已生成（权限 600，仅 $APP_USER 可读）"
fi

# ── 6. 安装并启动 systemd 服务 ───────────────────────────
if [ -f "$INSTALL_DIR/deploy/$SERVICE_NAME.service" ]; then
    log "安装 systemd 服务 $SERVICE_NAME ..."
    cp "$INSTALL_DIR/deploy/$SERVICE_NAME.service" "/etc/systemd/system/$SERVICE_NAME.service"
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME"
    systemctl restart "$SERVICE_NAME" \
        || die "服务启动失败，请查看日志：journalctl -u $SERVICE_NAME -n 50 --no-pager"
else
    warn "未找到 $INSTALL_DIR/deploy/$SERVICE_NAME.service，跳过服务安装（代码已就绪）"
fi

# ── 7. 结果输出 ──────────────────────────────────────────
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
    log "✅ 部署成功，服务运行中！"
else
    warn "服务未在运行，请检查：journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi
echo "----------------------------------------------------------------------"
echo "  实时日志   : journalctl -u $SERVICE_NAME -f"
echo "  服务管理   : sudo systemctl restart|stop|status $SERVICE_NAME"
echo "  更新部署   : sudo bash $0"
echo "----------------------------------------------------------------------"
