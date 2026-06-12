"""实时行情服务

订阅 QMT 全推行情，合成 K 线并通过 WebSocket 发布。
非交易时间自动停止订阅以节省资源。
"""

import datetime
import threading
from collections import defaultdict
from typing import Callable

from loguru import logger

from qmt_gateway.config import config
from qmt_gateway.core import require_xtdata


class QuoteService:
    """实时行情服务

    订阅 QMT 全推行情，合成 1分钟、30分钟和日线 K 线。
    1. 通过 subscribe_whole_quote 订阅个股行情
    2. 通过 subscribe_whole_quote 单独订阅指数行情（指数不能通过市场代码订阅）
    3. 非交易时间自动停止订阅
    """

    # 主要指数代码列表
    INDEX_CODES = [
        "000001.SH",  # 上证指数
        "399001.SZ",  # 深成指
        "000300.SH",  # 沪深300
        "000905.SH",  # 中证500
        "000852.SH",  # 中证1000
        "000688.SH",  # 科创50
    ]

    # 交易时间配置
    TRADE_START_AM = datetime.time(9, 15)   # 上午开盘前 15 分钟开始
    TRADE_END_AM = datetime.time(11, 45)    # 上午收盘后 15 分钟停止
    TRADE_START_PM = datetime.time(12, 45)  # 下午开盘前 15 分钟开始
    TRADE_END_PM = datetime.time(15, 15)    # 下午收盘后 15 分钟停止

    def __init__(self):
        self._xtdata = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._callbacks: list[Callable] = []
        self._bars_1m: dict[str, dict] = defaultdict(dict)
        self._bars_30m: dict[str, dict] = defaultdict(dict)
        self._bars_1d: dict[str, dict] = defaultdict(dict)
        self._subscribed = False  # 是否已订阅
        self._stock_subscription_seq: int | None = None
        self._index_subscription_seq: int | None = None

    def _is_trade_time(self) -> bool:
        """检查当前是否为交易时间（包含前后缓冲时间）"""
        now = datetime.datetime.now().time()
        weekday = datetime.datetime.now().weekday()

        # 周末不交易
        if weekday >= 5:  # 5=周六, 6=周日
            return False

        # 上午时段
        if self.TRADE_START_AM <= now <= self.TRADE_END_AM:
            return True

        # 下午时段
        if self.TRADE_START_PM <= now <= self.TRADE_END_PM:
            return True

        return False

    def _get_xtdata(self):
        """获取 xtdata 模块"""
        if self._xtdata is None:
            self._xtdata = require_xtdata(
                xtquant_path=str(config.xtquant_path) if config.xtquant_path else None,
                qmt_path=str(config.qmt_path) if config.qmt_path else None,
            )
        return self._xtdata

    def start(self) -> None:
        """启动行情服务"""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("实时行情服务已启动")

    def stop(self) -> None:
        """停止行情服务"""
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("实时行情服务已停止")

    def _run(self) -> None:
        """运行行情订阅循环（带交易时间检查）"""
        try:
            xtdata = self._get_xtdata()

            while self._running:
                is_trade_time = self._is_trade_time()

                if is_trade_time and not self._subscribed:
                    # 交易时间开始，订阅行情
                    self._subscribe(xtdata)
                elif not is_trade_time and self._subscribed:
                    # 交易时间结束，取消订阅
                    self._unsubscribe(xtdata)

                # 每分钟检查一次
                self._stop_event.wait(60)

        except Exception as e:
            logger.error(f"行情服务运行错误: {e}")
            self._running = False

    def _subscribe(self, xtdata) -> None:
        """订阅行情"""
        try:
            # 1. 订阅个股行情（通过市场代码）
            code_list = ["SH", "SZ", "BJ"]
            # region debug-point quote-subscribe
            stock_result = xtdata.subscribe_whole_quote(code_list, self._on_tick)
            self._stock_subscription_seq = int(stock_result)
            logger.debug(
                "debug quote subscribe stocks: result={}, available_unsubscribe={}",
                stock_result,
                [name for name in dir(xtdata) if "unsubscribe" in name.lower()],
            )
            # endregion debug-point quote-subscribe
            logger.info(f"已订阅个股行情，市场: {code_list}")

            # 2. 单独订阅指数行情（指数不能通过市场代码订阅，必须单独订阅）
            # region debug-point quote-subscribe-index
            index_result = xtdata.subscribe_whole_quote(self.INDEX_CODES, self._on_tick)
            self._index_subscription_seq = int(index_result)
            logger.debug("debug quote subscribe indices: result={}", index_result)
            # endregion debug-point quote-subscribe-index
            logger.info(f"已订阅指数行情: {self.INDEX_CODES}")

            self._subscribed = True
        except Exception as e:
            logger.error(f"订阅行情失败: {e}")

    def _unsubscribe(self, xtdata) -> None:
        """取消订阅行情"""
        try:
            # region debug-point quote-unsubscribe
            logger.debug(
                "debug quote unsubscribe: available_unsubscribe={}",
                [name for name in dir(xtdata) if "unsubscribe" in name.lower()],
            )
            # endregion debug-point quote-unsubscribe
            # 1. 取消订阅个股行情
            code_list = ["SH", "SZ", "BJ"]
            if self._stock_subscription_seq is not None:
                xtdata.unsubscribe_quote(self._stock_subscription_seq)
                logger.info(
                    f"已取消订阅个股行情，市场: {code_list}, seq={self._stock_subscription_seq}"
                )

            # 2. 取消订阅指数行情
            if self._index_subscription_seq is not None:
                xtdata.unsubscribe_quote(self._index_subscription_seq)
                logger.info(
                    f"已取消订阅指数行情: {self.INDEX_CODES}, seq={self._index_subscription_seq}"
                )

            self._stock_subscription_seq = None
            self._index_subscription_seq = None
            self._subscribed = False
        except Exception as e:
            logger.error(f"取消订阅行情失败: {e}")

    def _on_tick(self, data: dict) -> None:
        """处理 tick 数据

        Args:
            data: tick 数据字典
        """
        # 非交易时间不处理数据
        if not self._is_trade_time():
            return

        try:
            symbol = data.get("code")
            if not symbol:
                return

            # 取一次 now，三个 K 线级别共享；同时也用于回调载荷。
            # 避免每个 _update_bar / 回调都再 datetime.now() —— 全市场 tick 时
            # 这能省下 ~15000 次系统调用 / 3 秒。
            now = datetime.datetime.now()
            timestamp_iso = now.isoformat()

            # 更新 1分钟 K 线
            bar_1m = self._update_bar(
                self._bars_1m[symbol],
                data,
                now,
                interval=60,
            )

            # 更新 30分钟 K 线
            bar_30m = self._update_bar(
                self._bars_30m[symbol],
                data,
                now,
                interval=1800,
            )

            # 更新日线 K 线
            bar_1d = self._update_bar(
                self._bars_1d[symbol],
                data,
                now,
                interval=86400,
            )

            # 构造回调载荷：直接复用 timestamp_iso，不再重复格式化。
            payload = {
                "symbol": symbol,
                "timestamp": timestamp_iso,
                "1m": bar_1m,
                "30m": bar_30m,
                "1d": bar_1d,
            }

            # 触发回调
            for callback in self._callbacks:
                try:
                    callback(payload)
                except Exception as e:
                    logger.error(f"行情回调错误: {e}")

        except Exception as e:
            logger.error(f"处理 tick 数据错误: {e}")

    def _update_bar(
        self,
        bar_cache: dict,
        tick: dict,
        now: datetime.datetime,
        interval: int,
    ) -> dict:
        """更新 K 线数据

        Args:
            bar_cache: K 线缓存
            tick: tick 数据
            now: 当前时间
            interval: 时间间隔（秒）

        Returns:
            更新后的 K 线数据
        """
        price = tick.get("lastPrice", 0)
        # K 线合成（含 volume / amount 的末 tick 锁定、ref_volume 状态机、跨 bar 行为）见
        # docs/quote-bar-synthesis.md。
        raw_volume = tick.get("volume")
        raw_amount = tick.get("amount")
        new_volume = raw_volume if raw_volume is not None else 0
        new_amount = raw_amount if raw_amount is not None else 0
        has_volume = raw_volume is not None and raw_volume > 0
        has_amount = raw_amount is not None and raw_amount > 0

        # 计算当前 K 线的时间戳
        if interval == 86400:  # 日线
            bar_time = now.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            timestamp = int(now.timestamp())
            bar_timestamp = (timestamp // interval) * interval
            bar_time = datetime.datetime.fromtimestamp(bar_timestamp)

        bar_key = bar_time.isoformat()

        if bar_key not in bar_cache:
            # 新 K 线
            bar_cache.clear()
            # ref_volume / ref_amount：上一根 bar 区间内最后一个 tick.volume / .amount。
            # 首根 bar 初始化为 0（视作"开盘前"）。
            bar_cache[bar_key] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0,
                "amount": 0.0,
                "time": bar_time.isoformat(),
                "ref_volume": 0,
                "ref_amount": 0.0,
            }
        else:
            # 更新现有 K 线
            bar = bar_cache[bar_key]
            bar["high"] = max(bar["high"], price)
            bar["low"] = min(bar["low"], price)
            bar["close"] = price

        # 1d 走覆盖；日内级别走 ref 减法。详细见 docs/quote-bar-synthesis.md。
        if interval == 86400:
            if has_volume:
                bar_cache[bar_key]["volume"] = new_volume
            if has_amount:
                bar_cache[bar_key]["amount"] = new_amount
        else:
            if has_volume:
                bar_cache[bar_key]["volume"] = max(
                    0, new_volume - bar_cache[bar_key]["ref_volume"]
                )
            if has_amount:
                bar_cache[bar_key]["amount"] = max(
                    0.0, new_amount - bar_cache[bar_key]["ref_amount"]
                )

        # 末 tick 锁定：无论是否跨 bar，都把"本 tick.volume"作为新的 ref_volume，
        # 这样下一根 bar 进来的第一个 tick 就能立刻算出正确的 delta。
        # 缺字段（None / 0）时不更新 ref，避免把坏值灌进基线。
        if interval != 86400:
            if has_volume:
                bar_cache[bar_key]["ref_volume"] = new_volume
            if has_amount:
                bar_cache[bar_key]["ref_amount"] = new_amount

        return bar_cache[bar_key]

    def subscribe(self, callback: Callable) -> None:
        """订阅行情数据

        Args:
            callback: 回调函数，接收行情数据字典
        """
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable) -> None:
        """取消订阅"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def is_running(self) -> bool:
        """检查服务是否运行中"""
        return self._running

    def get_latest_price(self, symbol: str) -> float:
        """获取最新价。

        Args:
            symbol: 证券代码

        Returns:
            最新价。无可用数据时返回 0
        """
        bars = self._bars_1m.get(symbol, {})
        if not bars:
            return 0
        latest_bar = max(
            bars.values(),
            key=lambda item: str(item.get("time", "")),
            default=None,
        )
        if not latest_bar:
            return 0
        try:
            return float(latest_bar.get("close", 0) or 0)
        except (TypeError, ValueError):
            return 0


# 全局服务实例
quote_service = QuoteService()
