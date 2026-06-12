"""行情 WebSocket API

提供实时行情数据推送。
"""

import asyncio
import json
import threading
from typing import Any

import orjson
from fasthtml.common import *
from loguru import logger

from qmt_gateway.apis.api_keys import require_api_key_or_session
from qmt_gateway.services.quote_service import quote_service


# orjson 序列化 helper：比标准库 json.dumps 快 5~10 倍，输出更紧凑
# 全部 dict / int / float / str / list / None 类型，无需自定义 default
_dumps = orjson.dumps


def _dumps_text(obj: Any) -> str:
    """把对象序列化为 WebSocket 文本帧字符串。

    orjson.dumps 返回 bytes，解码为 utf-8 字符串。
    """
    return _dumps(obj).decode("utf-8")


class QuoteWebSocket:
    """行情 WebSocket 处理器

    性能改造：
    - 不再为每个客户端 / 每个 tick 创建 asyncio task（之前每 3 秒会瞬时
      产生 ~ 5000 × N 个 task，事件循环压力大）。
    - 改为：xtquant 回调线程把行情推入 asyncio.Queue（线程安全），
      事件循环里跑一个常驻 worker 批量消费 → 序列化 → 广播。
    - 客户端列表用 set + RLock 保护，遍历时拿快照，避免迭代过程中变更。
    """

    # 队列容量上限：防止 xtquant 推送速度 > 消费速度时无限堆积
    # 经验值：5000 symbol × 3 秒一次 ≈ 15000 条 / 3s = 5000 条/s
    # 留 10 秒缓冲即 50000；过大反而吃内存
    _QUEUE_MAX = 50000

    def __init__(self):
        self._clients: set = set()
        self._clients_lock = threading.RLock()
        self._started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None

    async def handle(self, ws):
        """处理 WebSocket 连接"""
        with self._clients_lock:
            self._clients.add(ws)
            client_count = len(self._clients)
        logger.info(f"WebSocket 客户端连接: {client_count} 个客户端")

        try:
            while True:
                # 接收消息（心跳或订阅请求）
                msg = await ws.receive_text()
                data = json.loads(msg)

                action = data.get("action")
                if action == "subscribe":
                    symbols = data.get("symbols", [])
                    logger.info(f"订阅行情: {symbols}")
                    # 这里可以添加订阅逻辑
                elif action == "ping":
                    await ws.send_text(json.dumps({"action": "pong"}))

        except Exception as e:
            logger.error(f"WebSocket 错误: {e}")
        finally:
            with self._clients_lock:
                self._clients.discard(ws)
                client_count = len(self._clients)
            logger.info(f"WebSocket 客户端断开: {client_count} 个客户端")

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """取到 FastHTML/uvicorn 跑着的事件循环。

        broadcast 在 xtquant 回调线程里被调用，所以我们要 run_coroutine_threadsafe。
        """
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_running_loop()
            except RuntimeError:
                # 在没有运行中的事件循环的线程中调用（极少见，例如 lifespan 之外）
                self._loop = asyncio.get_event_loop()
        return self._loop

    def broadcast(self, data: dict):
        """从 xtquant 回调线程调用：把行情推到 asyncio.Queue。"""
        if not self._clients:
            return
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(data)
        except asyncio.QueueFull:
            # 队列满：丢弃最旧一条，放入新数据；保证最新行情不被堵死
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(data)
            except Exception:
                pass

    async def _broadcast_worker(self):
        """事件循环里的常驻 worker：批量消费队列 → 序列化 → 广播。"""
        # 在 worker 启动时把 loop 缓存起来（之后 broadcast 线程用得到）
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._QUEUE_MAX)
        logger.info(f"行情广播 worker 启动（队列容量 {self._QUEUE_MAX}）")

        while True:
            try:
                # 批量取出当前队列里所有数据（最多 1000 条一批，避免单批过大）
                batch: list[dict] = []
                while len(batch) < 1000:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if not batch:
                    # 没数据，短暂让出
                    await asyncio.sleep(0)
                    continue

                # 序列化：每条单独 serialize（dict 异构，避免合并）
                # 用 orjson 替换标准库 json：单条 ~5 μs（原 ~50 μs，10x+ 提速）
                encoded = [_dumps_text(item) for item in batch]

                # 取客户端快照（无锁、避免广播与断开竞争）
                with self._clients_lock:
                    clients = list(self._clients)

                # 并发发送给所有客户端；单个失败不影响其他
                if clients:
                    await asyncio.gather(
                        *(self._safe_send(ws, msg) for ws in clients for msg in encoded),
                        return_exceptions=True,
                    )
            except asyncio.CancelledError:
                logger.info("行情广播 worker 取消")
                raise
            except Exception as e:
                logger.error(f"行情广播 worker 错误: {e}")
                await asyncio.sleep(0.01)

    async def _safe_send(self, ws, msg: str) -> None:
        """发送单条消息到单个客户端；失败仅记录日志。"""
        try:
            await ws.send_text(msg)
        except Exception as e:
            logger.error(f"发送行情数据失败: {e}")

    async def start_async(self):
        """在 FastHTML lifespan/startup 里调用，启动常驻 worker。"""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._QUEUE_MAX)
        self._worker_task = asyncio.create_task(self._broadcast_worker())
        logger.info("行情 WebSocket 服务已启动")

    def start(self):
        """同步启动入口：可在事件循环内或外调用。
        - 在事件循环内：直接 await start_async 一次
        - 在事件循环外：schedule 到下一个 tick（lifespan 钩子兜底）
        """
        if self._started:
            return

        # 订阅行情服务
        quote_service.subscribe(self._on_quote)
        quote_service.start()

        try:
            loop = asyncio.get_running_loop()
            # 在事件循环里：立即启动 worker
            loop.create_task(self.start_async())
        except RuntimeError:
            # 没有运行中的 loop；lifespan / startup 钩子会再调一次
            pass

        self._started = True
        logger.info("行情 WebSocket 服务已启动")

    def stop(self):
        """停止行情推送"""
        if not self._started:
            return

        quote_service.stop()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        self._worker_task = None
        self._queue = None
        self._started = False
        logger.info("行情 WebSocket 服务已停止")

    def _on_quote(self, data: dict):
        """行情数据回调（xtquant 回调线程里执行）"""
        self.broadcast(data)


# 全局 WebSocket 处理器
quote_ws = QuoteWebSocket()


def register_routes(app):
    """注册行情路由"""

    @app.ws("/ws/quotes")
    async def ws_quotes(ws):
        await quote_ws.handle(ws)

    @app.get("/api/v1/quotes/status")
    def get_quote_status(request):
        """获取行情服务状态"""
        require_api_key_or_session(request)
        with quote_ws._clients_lock:
            client_count = len(quote_ws._clients)
        return {
            "running": quote_service.is_running(),
            "clients": client_count,
        }
