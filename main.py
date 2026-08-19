"""
飞书记账机器人 - 完整版（云服务器就绪）
功能：接收用户消息，由 AI agent 自主调用工具完成记账/查账，并回复结果
使用长连接接收事件，无需公网地址

消息处理流程：
  1. 收到消息 → 立即回复"正在处理"（避免飞书长连接 3s 超时）
  2. 异步提交到线程池 → agent 调用工具记账/查账 → 回复最终结果（自由文本）
  3. AI 处理失败时自动降级到正则记账
"""

import json
import signal
import sys
import traceback

import lark_oapi as lark
from lark_oapi.api.im.v1 import *
from concurrent.futures import ThreadPoolExecutor

from config.glob_config import APP_ID, APP_SECRET, ASYNC_MAX_WORKERS
from core import get_agent, run_agent, get_feishu_client
from config.logger_config import get_logger
from utils import retry_with_backoff

logger = get_logger(__name__)

# ── 线程池 ────────────────────────────────────────────────
_executor = ThreadPoolExecutor(max_workers=ASYNC_MAX_WORKERS)

# ── 全局状态 ──────────────────────────────────────────────
_client: lark.Client
processed_message_ids: set[str] = set()
_shutdown_requested = False


# ── 消息回复（带重试）─────────────────────────────────────
@retry_with_backoff(
    max_retries=1,
    base_delay=0.5,
    non_retryable_exceptions=(ValueError, TypeError),
)
def send_reply(message_id: str, reply_text: str) -> None:
    """
    回复用户消息（群聊或单聊），失败自动重试 1 次
    """
    content = json.dumps({"text": reply_text})
    request = (
        ReplyMessageRequest.builder()
        .message_id(message_id)
        .request_body(
            ReplyMessageRequestBody.builder()
            .content(content)
            .msg_type("text")
            .build()
        )
        .build()
    )
    response = _client.im.v1.message.reply(request)
    if not response.success():
        error_detail = f"code={response.code}, msg={response.msg}"
        logger.error("回复消息失败: %s", error_detail)
        raise RuntimeError(f"回复消息失败: {error_detail}")
    logger.debug("回复消息成功: id=%s", message_id)


# ── 异步消息处理 ──────────────────────────────────────────
def async_process_message(message_id: str, msg_text: str) -> None:
    """
    异步处理消息：agent 自主调用工具记账/查账 → 回复自由文本结果
    此函数在线程池中执行，不会阻塞飞书长连接
    """
    thread_name = f"[msg={message_id[-8:]}]"
    logger.info("%s 开始异步处理: %s", thread_name, msg_text)

    try:
        # agent 自主调用工具完成记账/查账（AI 失败时自动降级到正则记账）
        agent = get_agent()
        result = run_agent(agent, msg_text)

        if not result.get("success"):
            reply = result.get("reply") or f"❌ {result.get('error_msg')}"
            send_reply(message_id, reply)
            logger.warning("%s 消息处理失败: %s", thread_name, result.get("error_msg"))
            return

        reply = result["reply"]
        logger.info("%s 处理完成: %s", thread_name, reply)
        send_reply(message_id, reply)

    except Exception:
        logger.error(
            "%s 异步处理异常:\n%s",
            thread_name,
            traceback.format_exc(),
        )
        try:
            send_reply(message_id, "❌ 处理失败，请稍后重试或联系管理员")
        except Exception:
            logger.error("%s 连错误回复也发送失败", thread_name)


# ── 事件回调 ──────────────────────────────────────────────
def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    """处理接收到的消息事件（立即回复 + 异步处理）"""
    if _shutdown_requested:
        return

    event = data.event
    message = event.message
    message_id = message.message_id

    # 去重
    if message_id in processed_message_ids:
        logger.debug("跳过重复消息: %s", message_id)
        return
    processed_message_ids.add(message_id)

    # 只处理文本消息
    if message.message_type != "text":
        logger.debug("跳过非文本消息: type=%s", message.message_type)
        return

    try:
        msg_text = json.loads(message.content)["text"]
        logger.info("收到消息: %s", msg_text)

        # 立即回复，避免飞书长连接 3s 超时
        send_reply(message.message_id, "⏳ 收到，正在记账...")

        # 提交到线程池异步处理
        _executor.submit(async_process_message, message.message_id, msg_text)

    except Exception:
        logger.error("消息接收处理异常:\n%s", traceback.format_exc())
        try:
            send_reply(message.message_id, "❌ 内部错误，请联系管理员")
        except Exception:
            pass


# ── 优雅关闭 ──────────────────────────────────────────────
def _shutdown(signum=None, frame=None) -> None:
    """收到 SIGTERM / SIGINT 时优雅关闭"""
    global _shutdown_requested
    if _shutdown_requested:
        return
    _shutdown_requested = True

    sig_name = signal.Signals(signum).name if signum else "手动"
    logger.info("收到 %s 信号，开始优雅关闭...", sig_name)

    print("\n正在关闭...", flush=True)

    _executor.shutdown(wait=True, cancel_futures=True)
    logger.info("线程池已关闭")

    sys.exit(0)


# ── 主入口 ────────────────────────────────────────────────
def main() -> None:
    global _client

    # 注册信号处理
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("=" * 50)
    logger.info("飞书记账机器人启动中...")
    logger.info("日志目录: logs/")
    logger.info("线程池大小: %d", ASYNC_MAX_WORKERS)
    logger.info("=" * 50)

    # 初始化 API 客户端
    _client = get_feishu_client()
    # 预热 AI 模型（可选 — 让第一次解析更快）
    try:
        get_agent()
        logger.info("AI 模型预热完成")
    except Exception as e:
        logger.warning("AI 模型预热失败（将在首次请求时重试）: %s", e)

    # 构建事件处理器
    event_handler = (
        lark.EventDispatcherHandler.builder(APP_ID, APP_SECRET)
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .build()
    )

    # 启动 WebSocket 长连接
    ws_client = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )

    logger.info("飞书记账机器人已启动，等待消息...")
    try:
        ws_client.start()
    except KeyboardInterrupt:
        _shutdown()
    except Exception:
        logger.critical("WebSocket 连接异常退出:\n%s", traceback.format_exc())
        _shutdown()


if __name__ == "__main__":
    main()
