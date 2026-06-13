"""集合竞价行情 WebSocket API（issue #81）

09:15 ~ 09:29:59 推送原始撮合快照，**不做 K 线合成**。
设计意图：让"开盘瞬间需要立即产生策略信号"的客户端（打板、跳空策略）
在 09:25 撮合那一帧立刻拿到稳定开盘价，无需等到 09:30 第一个 tick；
同时让需要观察可撤单段撮合趋势的客户端也能拿到原始数据。

参考 xtquant 全推 tick 行为实测（见 wiki "xtquant 全推 Tick 行为"）：

- 09:15 - 09:20（可撤单段，``phase = "auction_a"``）：lastPrice 是
  虚拟撮合价，价格剧烈波动且大量虚假报单；OHLV 仍为 0；status=2。
  **风险段**——简单策略应过滤，撮合大单监控类策略可能仍有用。
- 09:20 - 09:25（不可撤单段，``phase = "auction_b"``）：lastPrice
  是虚拟撮合价（已稳定收敛）；OHLV 仍为 0；status=2。
- 09:25:00 ± 几秒（撮合那一帧 ⭐，``phase = "matching"``）：open /
  high / low / volume 同时首次填入，``open = high = low = lastPrice
  = 撮合成交价``。
- 09:25 - 09:30（静默期，``phase = "matching"``）：OHLV 锁定，仅
  lastPrice 偶有微调；status=3。
- 09:30 起：连续竞价（走 /ws/quotes）。

数据格式（每 tick 一条消息，不聚合）：
```json
{
    "type": "auction",
    "symbol": "000001.SZ",
    "server_time": "2026-06-12T09:23:45.000",
    "phase": "auction_b",
    "price": 12.34,
    "open": 0.0,
    "volume": 0,
    "amount": 0.0,
    "stock_status": 2
}
```

撮合帧（09:25 ± 几秒）特征：``phase == "matching"`` 且 ``open != 0``
且 ``volume > 0``，客户端可据此识别。
"""

import asyncio
import datetime
import json
import threading
from typing import Any

import orjson
from fasthtml.common import *
from loguru import logger

from qmt_gateway.apis.api_keys import require_api_key_or_session
from qmt_gateway.services.quote_service import quote_service


_dumps = orjson.dumps


def _dumps_text(obj: Any) -> str:
    return _dumps(obj).decode("utf-8")


# 集合竞价时段闸门。
#
# 起点 09:15、终点 09:30：诚实转发 xtquant 全推 tick 在集合竞价段（含
# 09:15-09:20 的可撤单段）的所有数据。客户端通过 ``phase`` 字段判断
# 当前在哪个阶段，自行决定是否使用：
#
# - ``auction_a``（09:15-09:20，可撤单段）：价格剧烈波动且大量虚假
#   报单，**风险段**——简单策略可丢弃，撮合大单监控类策略可能仍有用。
# - ``auction_b``（09:20-09:25，不可撤单段）：撮合价稳定收敛。
# - ``matching``（09:25-09:30，含 09:25 撮合那一帧 ⭐）：开盘价权威定价时刻。
#
# >= 09:30 走 /ws/quotes 的 K 线合成路径，本通道不再发布。
AUCTION_START = datetime.time(9, 15, 0)
AUCTION_END = datetime.time(9, 30, 0)


def is_auction_time(server_time: datetime.datetime) -> bool:
    """判断 server_time 是否在集合竞价发布窗口（09:15 ~ 09:29:59）。"""
    t = server_time.time()
    return AUCTION_START <= t < AUCTION_END


def auction_phase(server_time: datetime.datetime) -> str:
    """返回集合竞价子阶段标签，便于客户端识别撮合时刻并按阶段过滤。

    - ``auction_a``: 09:15 ~ 09:19:59（可撤单段；价格剧烈波动 + 虚假报单）
    - ``auction_b``: 09:20 ~ 09:24:59（不可撤单段；撮合价稳定收敛）
    - ``matching``:  09:25 ~ 09:29:59（含 09:25 ± 几秒撮合那一帧 ⭐ + 静默期）
    """
    t = server_time.time()
    if t < datetime.time(9, 20):
        return "auction_a"
    if t < datetime.time(9, 25):
        return "auction_b"
    return "matching"


class AuctionWebSocket:
    """集合竞价 WebSocket 处理器。

    架构对标 QuoteWebSocket：
    - set + RLock 管理客户端
    - asyncio.Queue + 单 worker 广播
    - orjson 序列化
    - 推送频率与 xtquant tick 同步（每 ~3 秒一条；集合竞价段每标的约 30~100 条）
    """

    _QUEUE_MAX = 50000

    def __init__(self):
        self._clients: set = set()
        self._clients_lock = threading.RLock()
        self._started = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queue: asyncio.Queue | None = None
        self._worker_task: asyncio.Task | None = None

    async def handle(self, ws):
        """处理 WebSocket 连接。"""
        with self._clients_lock:
            self._clients.add(ws)
            client_count = len(self._clients)
        logger.info(f"集合竞价 WebSocket 客户端连接: {client_count} 个客户端")

        try:
            while True:
                msg = await ws.receive_text()
                data = json.loads(msg)

                action = data.get("action")
                if action == "ping":
                    await ws.send_text(json.dumps({"action": "pong"}))
                # 其它 action 暂只记日志（未来可加按 symbol 过滤）
        except Exception as e:
            logger.error(f"集合竞价 WebSocket 错误: {e}")
        finally:
            with self._clients_lock:
                self._clients.discard(ws)
                client_count = len(self._clients)
            logger.info(f"集合竞价 WebSocket 客户端断开: {client_count} 个客户端")

    def broadcast(self, payload: dict) -> None:
        """从 xtquant 回调线程调用：把集合竞价快照推到 asyncio.Queue。"""
        if not self._clients:
            return
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            # 队列满：丢弃最旧一条，放入新数据；保证最新行情不被堵死
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            try:
                self._queue.put_nowait(payload)
            except Exception:
                pass

    async def _broadcast_worker(self):
        """事件循环里的常驻 worker：批量消费队列 → 序列化 → 广播。"""
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._QUEUE_MAX)
        logger.info(f"集合竞价广播 worker 启动（队列容量 {self._QUEUE_MAX}）")

        while True:
            try:
                batch: list[dict] = []
                while len(batch) < 1000:
                    try:
                        batch.append(self._queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break

                if not batch:
                    await asyncio.sleep(0)
                    continue

                encoded = [_dumps_text(item) for item in batch]

                with self._clients_lock:
                    clients = list(self._clients)

                if clients:
                    await asyncio.gather(
                        *(self._safe_send(ws, msg) for ws in clients for msg in encoded),
                        return_exceptions=True,
                    )
            except asyncio.CancelledError:
                logger.info("集合竞价广播 worker 取消")
                raise
            except Exception as e:
                logger.error(f"集合竞价广播 worker 错误: {e}")
                await asyncio.sleep(0.01)

    async def _safe_send(self, ws, msg: str) -> None:
        try:
            await ws.send_text(msg)
        except Exception as e:
            logger.error(f"发送集合竞价数据失败: {e}")

    async def start_async(self):
        """在 FastHTML lifespan/startup 里调用，启动常驻 worker。"""
        if self._worker_task is not None and not self._worker_task.done():
            return
        self._loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue(maxsize=self._QUEUE_MAX)
        self._worker_task = asyncio.create_task(self._broadcast_worker())
        self._started = True
        logger.info("集合竞价 WebSocket 服务已启动")

    def stop(self):
        if not self._started:
            return
        # 解订阅 quote_service 的 tick 回调
        quote_service.unsubscribe_tick(self._on_tick)
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
        self._worker_task = None
        self._queue = None
        self._started = False
        logger.info("集合竞价 WebSocket 服务已停止")

    def start(self):
        """订阅 quote_service 的原始 tick 回调（同步入口）。

        worker 由 start_async 在事件循环里启动；这里只做回调注册。
        """
        quote_service.subscribe_tick(self._on_tick)

    def _on_tick(
        self,
        symbol: str,
        server_time: datetime.datetime,
        tick: dict,
    ) -> None:
        """quote_service 触发的原始 tick 回调（xtquant 回调线程）。

        只在集合竞价时段（09:15 ~ 09:29:59，按 server_time 判定）转发；
        其它时段直接丢弃。
        """
        if not is_auction_time(server_time):
            return
        if not self._clients:
            return

        # 提取关键字段，构造紧凑的 auction 消息（不含五档报价等冗余字段）
        payload = {
            "type": "auction",
            "symbol": symbol,
            "server_time": server_time.isoformat(timespec="milliseconds"),
            "phase": auction_phase(server_time),
            "price": tick.get("lastPrice", 0.0) or 0.0,
            "open": tick.get("open", 0.0) or 0.0,
            "high": tick.get("high", 0.0) or 0.0,
            "low": tick.get("low", 0.0) or 0.0,
            "volume": tick.get("volume", 0) or 0,
            "amount": tick.get("amount", 0.0) or 0.0,
            "stock_status": tick.get("stockStatus", 0) or 0,
            "last_close": tick.get("lastClose", 0.0) or 0.0,
        }
        self.broadcast(payload)


# 全局 WebSocket 处理器
auction_ws = AuctionWebSocket()


def register_routes(app):
    """注册集合竞价路由。"""

    @app.ws("/ws/auction")
    async def ws_auction(ws):
        await auction_ws.handle(ws)

    @app.get("/api/v1/auction/status")
    def get_auction_status(request):
        """获取集合竞价服务状态。"""
        require_api_key_or_session(request)
        with auction_ws._clients_lock:
            client_count = len(auction_ws._clients)
        return {
            "running": auction_ws._started,
            "clients": client_count,
        }
