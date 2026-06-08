"""交易 API

提供账户资金、持仓、订单查询和交易执行功能。
"""

import datetime
import sqlite3
from decimal import Decimal

from fastcore.xml import to_xml
from fasthtml.common import *
from loguru import logger
from starlette.responses import HTMLResponse, JSONResponse
from qmt_gateway.apis.api_keys import require_api_key_or_session
from qmt_gateway.config import config
from qmt_gateway.db.models import Asset, Position
from qmt_gateway.db.sqlite import db
from qmt_gateway.services.quote_service import quote_service
from qmt_gateway.services.stock_service import stock_service
from qmt_gateway.services.trade_service import trade_service

DEFAULT_PORTFOLIO_ID = "default"


def _render_fragment(fragment) -> HTMLResponse:
    return HTMLResponse(to_xml(fragment))


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _get_value(item, key: str, default=None):
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _json_safe(value):
    """将非 JSON 可序列化的类型转换为原生 Python 类型。

    处理的类型:
    - datetime.datetime / datetime.date → ISO 格式字符串
    - Decimal → float
    - numpy 数值类型 (int64, float64 等) → 原生 int/float
    - bytes → hex 字符串
    - 其他不可序列化类型 → str
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, str)):
        return value
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    # numpy 数值类型: 检查是否有 .item() 方法 (ndarray scalar)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    # 兜底: 转为字符串
    try:
        return str(value)
    except Exception:
        return None


def _json_safe_rows(rows: list[dict]) -> list[dict]:
    """对字典列表中的每个值执行 _json_safe 归一化。"""
    return [{k: _json_safe(v) for k, v in row.items()} for row in rows]


def _format_time(value) -> str:
    """将时间值统一格式化为 HH:MM:SS 字符串。

    处理的类型:
    - datetime.datetime → strftime
    - str (ISO 格式) → 解析后 strftime
    - str (HH:MM:SS) → 原样返回
    - 其他 → str()
    """
    if isinstance(value, datetime.datetime):
        return value.strftime("%H:%M:%S")
    if isinstance(value, str):
        if ":" in value:
            return value
        try:
            return datetime.datetime.fromisoformat(value).strftime("%H:%M:%S")
        except ValueError:
            return value
    if value is None:
        return ""
    return str(value)


def _normalize_side(value) -> str:
    """将 side 值归一化为 'buy' 或 'sell'。

    处理的类型:
    - str ('buy'/'sell') → 原样
    - int (1/2 或 23/24) → 'buy'/'sell'
    - 枚举 → 根据值判断
    """
    if isinstance(value, str):
        return value if value in ("buy", "sell") else "buy"
    if isinstance(value, (int, float)):
        return "buy" if int(value) in (1, 23) else "sell"
    if hasattr(value, "value"):
        return _normalize_side(value.value)
    return "buy"


def _require_local_request(request) -> None:
    client = getattr(request, "client", None)
    host = str(getattr(client, "host", "") or "")
    if host not in {"127.0.0.1", "::1", "localhost", "testclient"}:
        raise HTTPException(status_code=403, detail="仅允许本机访问")


def _fetch_one_dict(sql: str, params: tuple = ()) -> dict | None:
    cursor = db.conn.execute(sql, params)
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [c[0] for c in cursor.description]
    return dict(zip(columns, row, strict=False))


def _fetch_all_dicts(sql: str, params: tuple = ()) -> list[dict]:
    cursor = db.conn.execute(sql, params)
    rows = cursor.fetchall()
    if not rows:
        return []
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row, strict=False)) for row in rows]


def _get_stock_name_map(symbols: list[str]) -> dict[str, str]:
    result = {}
    for symbol in symbols:
        stock = stock_service.get_stock(symbol)
        if stock:
            result[symbol] = stock.name
    if len(result) == len(symbols):
        return result
    if not stock_service.get_all_stocks():
        stock_service.update_stock_list()
    for symbol in symbols:
        if symbol in result:
            continue
        stock = stock_service.get_stock(symbol)
        if stock:
            result[symbol] = stock.name
    return result


def _normalize_order_status(status: str) -> str:
    value = str(status or "").strip().lower()
    aliases = {
        "48": "unreported",
        "49": "pending",
        "50": "reported",
        "51": "canceling",
        "52": "partial_canceling",
        "53": "partial_cancelled",
        "54": "cancelled",
        "55": "partial",
        "56": "filled",
        "57": "rejected",
        "wait_reporting": "pending",
        "reported_cancel": "canceling",
        "partsucc_cancel": "partial_canceling",
        "part_cancel": "partial_cancelled",
        "part_succ": "partial",
        "succeeded": "filled",
        "junk": "rejected",
    }
    return aliases.get(value, value or "unknown")


def _is_order_cancellable(status: str) -> bool:
    normalized = _normalize_order_status(status)
    return normalized in {
        "unreported",
        "pending",
        "reported",
        "partial",
    }


def _get_latest_asset(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> Asset | None:
    row = _fetch_one_dict(
        "select * from assets where portfolio_id = ? order by dt desc limit 1",
        (portfolio_id,),
    )
    if row is None:
        return None
    return Asset.from_dict(row)


def _get_latest_positions(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> list[Position]:
    rows = _fetch_all_dicts(
        """
        select * from positions
        where portfolio_id = ?
          and dt = (
              select dt from positions
              where portfolio_id = ?
              order by dt desc
              limit 1
          )
        """,
        (portfolio_id, portfolio_id),
    )
    return [Position.from_dict(row) for row in rows]


def _snapshot_asset(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> Asset | None:
    # region debug-point asset-snapshot-live
    live = trade_service.get_asset()
    logger.debug("debug asset snapshot live: portfolio_id={}, live={}", portfolio_id, live)
    # endregion debug-point asset-snapshot-live
    if not live:
        return None
    today = datetime.date.today()
    cached_asset = _get_latest_asset(portfolio_id)
    asset = Asset(
        portfolio_id=portfolio_id,
        dt=today,
        principal=_as_float(
            cached_asset.principal if cached_asset is not None else _get_value(live, "total", 0)
        ),
        cash=_as_float(_get_value(live, "cash", 0)),
        frozen_cash=_as_float(_get_value(live, "frozen_cash", 0)),
        market_value=_as_float(_get_value(live, "market_value", 0)),
        total=_as_float(_get_value(live, "total", 0)),
    )
    db["assets"].upsert(asset.to_dict(), pk=Asset.__pk__)
    return asset


def _snapshot_positions(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> None:
    rows = trade_service.get_positions()
    today = datetime.date.today()
    if rows is None:
        return
    try:
        db.execute_write(
            "delete from positions where portfolio_id = ? and dt = ?",
            (portfolio_id, today),
        )
        for row in rows:
            symbol = str(_get_value(row, "symbol", "")).strip()
            if not symbol:
                continue
            shares = _as_float(_get_value(row, "shares", 0))
            if shares <= 0:
                continue
            price = _as_float(_get_value(row, "cost", _get_value(row, "price", 0)))
            position = Position(
                portfolio_id=portfolio_id,
                dt=today,
                asset=symbol,
                shares=shares,
                avail=_as_float(_get_value(row, "avail", 0)),
                price=price,
                profit=_as_float(_get_value(row, "profit", 0)),
                mv=_as_float(_get_value(row, "market_value", 0)),
            )
            db["positions"].upsert(position.to_dict(), pk=Position.__pk__)
    except sqlite3.OperationalError as exc:
        logger.warning(f"持仓快照写入失败，回退到已有缓存数据: {exc}")


def get_latest_asset_data(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> dict:
    # region debug-point asset-cache-read
    asset = _get_latest_asset(portfolio_id)
    logger.debug(
        "debug asset cache read: portfolio_id={}, cached_asset={}",
        portfolio_id,
        asset.to_dict() if asset else None,
    )
    # endregion debug-point asset-cache-read
    live_asset = _snapshot_asset(portfolio_id)
    if live_asset is not None:
        asset = live_asset
    if asset is None:
        return {
            "principal": 0,
            "total": 0,
            "profit": 0,
            "profit_ratio": 0,
            "cash": 0,
            "market_value": 0,
            "frozen_cash": 0,
        }
    profit = asset.total - asset.principal
    profit_ratio = (profit / asset.principal * 100) if asset.principal > 0 else 0
    result = {
        "principal": asset.principal,
        "total": asset.total,
        "profit": profit,
        "profit_ratio": profit_ratio,
        "cash": asset.cash,
        "market_value": asset.market_value,
        "frozen_cash": asset.frozen_cash,
    }
    # region debug-point asset-response
    logger.debug("debug asset response: portfolio_id={}, result={}", portfolio_id, result)
    # endregion debug-point asset-response
    return result


def get_latest_positions_data(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> list[dict]:
    _snapshot_positions(portfolio_id)
    positions = [p for p in _get_latest_positions(portfolio_id) if p.shares > 0]
    total = get_latest_asset_data(portfolio_id).get("total", 0)
    name_map = _get_stock_name_map([p.asset for p in positions])
    data = []
    for p in positions:
        cost_price = _as_float(p.price)
        hold_cost = p.shares * cost_price
        current_price = quote_service.get_latest_price(p.asset)
        if current_price <= 0 and p.shares > 0:
            current_price = _as_float(p.mv) / p.shares
        market_value = p.shares * current_price if current_price > 0 else _as_float(p.mv)
        float_profit = market_value - hold_cost
        profit_ratio = (float_profit / hold_cost * 100) if hold_cost > 0 else 0
        position_ratio = (market_value / total * 100) if total > 0 else 0
        data.append(
            {
                "symbol": p.asset,
                "name": name_map.get(p.asset, p.asset),
                "shares": p.shares,
                "avail": p.avail,
                "price": current_price,
                "cost": cost_price,
                "profit_ratio": profit_ratio,
                "float_profit": float_profit,
                "market_value": market_value,
                "hold_cost": hold_cost,
                "position_ratio": position_ratio,
            }
        )
    return _json_safe_rows(data)


def get_latest_orders_data(status: str = "all") -> list[dict]:
    orders = trade_service.get_orders()
    if not orders:
        data = _fetch_all_dicts(
            """
            select qtoid, foid, asset, side, price, shares, filled, status, tm
            from orders
            where portfolio_id = ?
            order by tm desc
            limit 200
            """,
            (DEFAULT_PORTFOLIO_ID,),
        )
        symbols = [str(_get_value(order, "asset", "")).strip() for order in data]
        name_map = _get_stock_name_map(symbols)
        rows = []
        for order in data:
            symbol = str(_get_value(order, "asset", "")).strip()
            side_value = _as_float(_get_value(order, "side", 1))
            normalized_status = _normalize_order_status(
                _get_value(order, "status", "unknown")
            )
            tm_raw = _get_value(order, "tm", "")
            time_text = ""
            if isinstance(tm_raw, datetime.datetime):
                time_text = tm_raw.strftime("%H:%M:%S")
            elif isinstance(tm_raw, str):
                try:
                    time_text = datetime.datetime.fromisoformat(tm_raw).strftime(
                        "%H:%M:%S"
                    )
                except ValueError:
                    time_text = tm_raw
            rows.append(
                {
                    "time": time_text,
                    "symbol": symbol,
                    "name": name_map.get(symbol, symbol),
                    "side": "buy" if side_value == 1 else "sell",
                    "price": _as_float(_get_value(order, "price", 0)),
                    "shares": _as_float(_get_value(order, "shares", 0)),
                    "filled": _as_float(_get_value(order, "filled", 0)),
                    "status": normalized_status,
                    "qtoid": str(
                        _get_value(order, "foid", "")
                        or _get_value(order, "qtoid", "")
                    ),
                    "can_cancel": _is_order_cancellable(normalized_status),
                }
            )
        if status == "all":
            return _json_safe_rows(rows)
        target = _normalize_order_status(status)
        return _json_safe_rows([row for row in rows if row["status"] == target])

    symbols = [str(_get_value(o, "symbol", "")).strip() for o in orders]
    name_map = _get_stock_name_map(symbols)
    data = []
    for order in orders:
        symbol = str(_get_value(order, "symbol", "")).strip()
        normalized_status = _normalize_order_status(_get_value(order, "status", "unknown"))
        time_raw = _get_value(order, "time", "")
        if isinstance(time_raw, datetime.datetime):
            time_text = time_raw.strftime("%H:%M:%S")
        elif isinstance(time_raw, str):
            time_text = time_raw
        else:
            time_text = str(time_raw) if time_raw else ""
        row = {
            "time": time_text,
            "symbol": symbol,
            "name": _get_value(order, "name", "") or name_map.get(symbol, symbol),
            "side": _get_value(order, "side", "buy"),
            "price": _as_float(_get_value(order, "price", 0)),
            "shares": _as_float(_get_value(order, "shares", 0)),
            "filled": _as_float(_get_value(order, "filled", 0)),
            "status": normalized_status,
            "qtoid": _get_value(order, "qtoid", ""),
            "can_cancel": _is_order_cancellable(normalized_status),
        }
        data.append(row)
    if status == "all":
        return _json_safe_rows(data)
    target = _normalize_order_status(status)
    return _json_safe_rows([row for row in data if row["status"] == target])


def login_required(request):
    """检查用户是否登录"""
    user = request.scope.get("session", {}).get("user")
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def register_routes(app):
    """注册交易路由"""

    @app.on_event("startup")
    async def startup_event():
        """启动时连接交易接口"""
        try:
            if config.qmt_account_id and config.qmt_path:
                success = trade_service.connect(
                    account_id=config.qmt_account_id,
                    qmt_path=str(config.qmt_path),
                )
                if success:
                    logger.info("已连接到 QMT")
                else:
                    logger.warning("已和 QMT 断开")
                    if config.auto_start_qmt:
                        logger.info("auto_start_qmt 已启用，尝试自动启动 QMT")
                        import asyncio
                        await asyncio.to_thread(
                            trade_service.try_auto_start_qmt,
                            qmt_path=str(config.qmt_path),
                            account_id=config.qmt_account_id,
                        )
        except Exception as e:
            logger.error(f"启动时连接交易接口失败: {e}")

    @app.on_event("shutdown")
    async def shutdown_event():
        """关闭时断开交易接口"""
        trade_service.disconnect()

    @app.get("/api/trade/asset")
    def get_asset(request):
        """获取账户资金"""
        require_api_key_or_session(request)
        return get_latest_asset_data()

    @app.get("/api/trade/connection-status")
    def get_connection_status(request):
        """获取交易接口连接状态"""
        require_api_key_or_session(request)
        return trade_service.get_connection_status()

    @app.post("/api/trade/restart-qmt")
    async def restart_qmt(request, password: str = ""):
        """重启 QMT 客户端并自动填入交易密码。

        如果未提供 password，则尝试使用 session 中存储的派生密钥解密已存储的 QMT 密码。
        重置流程在后台线程中执行，整体 30 秒超时，不阻塞事件循环。
        """
        require_api_key_or_session(request)

        # 如果未提供密码，尝试使用存储的加密密码
        if not password:
            try:
                settings = db.get_settings()
                if settings.qmt_password_encrypted:
                    from qmt_gateway.core.crypto_utils import decrypt_password_with_key
                    # 从 session 获取预计算的解密密钥
                    derived_key = request.scope.get("session", {}).get("qmt_decrypt_key")
                    if derived_key:
                        password = decrypt_password_with_key(
                            settings.qmt_password_encrypted, derived_key
                        )
                        logger.info("已使用存储的加密密码自动登录 QMT")
                    else:
                        logger.warning("session 中无 qmt_decrypt_key，无法解密存储的密码")
            except Exception as e:
                logger.warning(f"解密存储的 QMT 密码失败: {e}")

        logger.info("收到 QMT 重启请求")
        result = await trade_service.async_restart_and_login(
            qmt_path=str(trade_service._qmt_path or config.qmt_path or ""),
            account_id=str(trade_service._account_id or config.qmt_account_id or ""),
            qmt_password=password,
            kill_first=True,
        )
        if result.get("success"):
            logger.info("QMT 重启完成并已发起重连")
        else:
            logger.warning("QMT 重启失败: {}", result.get("error", "未知错误"))
        return result

    @app.get("/api/trade/restart-qmt/has-password")
    def has_restart_qmt_password(request):
        """检查当前会话是否可以获取到 QMT 交易密码。"""
        require_api_key_or_session(request)
        try:
            settings = db.get_settings()
            if not settings.qmt_password_encrypted:
                return {"has_password": False, "message": "未存储 QMT 交易密码"}
            derived_key = request.scope.get("session", {}).get("qmt_decrypt_key")
            if not derived_key:
                return {"has_password": False, "message": "会话已过期，请重新登录"}
            from qmt_gateway.core.crypto_utils import decrypt_password_with_key
            password = decrypt_password_with_key(settings.qmt_password_encrypted, derived_key)
            if password:
                return {"has_password": True, "message": "已存储 QMT 交易密码"}
            return {"has_password": False, "message": "密码解密失败"}
        except Exception as e:
            logger.warning(f"检查 QMT 密码可用性失败: {e}")
            return {"has_password": False, "message": str(e)}

    @app.get("/api/trade/restart-qmt/password")
    def get_restart_qmt_password(request, token: str = ""):
        """供交互会话 helper 一次性获取重启密码"""
        _require_local_request(request)
        password = trade_service.consume_restart_password_token(token)
        if not password:
            raise HTTPException(status_code=404, detail="重启密码令牌无效或已过期")
        return {"password": password}

    @app.post("/api/trade/restart-qmt/helper-status")
    def record_restart_qmt_helper_status(request, token: str = "", status: str = ""):
        """记录交互会话 helper 的错误状态"""
        _require_local_request(request)
        trade_service.record_restart_helper_status(token, status)
        if status:
            if str(status).startswith("INFO:"):
                logger.info("QMT helper 状态: {}", status)
            else:
                logger.warning("QMT helper 状态: {}", status)
        return {"success": True}

    @app.get("/api/trade/positions")
    def get_positions(request, view: str = "json"):
        """获取持仓列表

        Args:
            view: 返回格式，json 或 table
        """
        require_api_key_or_session(request)
        positions_data = get_latest_positions_data()

        if view == "table":
            from qmt_gateway.web.pages.trading import PositionTable
            return _render_fragment(PositionTable(positions_data))

        return JSONResponse(_json_safe_rows(positions_data))

    @app.get("/api/trade/orders")
    def get_orders(request, status: str = "all", view: str = "json"):
        """获取订单列表

        Args:
            status: 订单状态过滤
            view: 返回格式，json 或 table
        """
        require_api_key_or_session(request)
        orders_data = get_latest_orders_data(status)

        if view == "table":
            from qmt_gateway.web.pages.trading import OrdersTable
            return _render_fragment(OrdersTable(orders_data))

        return JSONResponse(_json_safe_rows(orders_data))

    @app.get("/api/trade/trades")
    def get_trades(request):
        """获取成交列表"""
        require_api_key_or_session(request)
        trades = trade_service.get_trades()
        rows = [
            {
                "tid": _get_value(t, "tid", ""),
                "qtoid": _get_value(t, "qtoid", ""),
                "time": _format_time(_get_value(t, "time", "")),
                "symbol": _get_value(t, "symbol", ""),
                "name": _get_value(t, "name", ""),
                "side": _normalize_side(_get_value(t, "side", "buy")),
                "price": _as_float(_get_value(t, "price", 0)),
                "shares": _as_float(_get_value(t, "shares", 0)),
                "amount": _as_float(_get_value(t, "amount", 0)),
            }
            for t in trades
        ]
        return JSONResponse(_json_safe_rows(rows))

    @app.post("/api/trade/buy")
    def buy_stock(request, symbol: str, price: float, shares: int, qtoid: str = "", strategy_id: str = ""):
        """买入股票"""
        require_api_key_or_session(request)
        logger.info("收到买入委托请求: symbol={}, price={}, shares={}", symbol, price, shares)
        result = trade_service.buy(symbol, price, shares, qtoid=qtoid, strategy_id=strategy_id)
        if result.get("success"):
            logger.info(
                "买入委托已提交: symbol={}, shares={}, price={}, qtoid={}, order_id={}",
                symbol,
                shares,
                price,
                result.get("qtoid", ""),
                result.get("order_id", ""),
            )
        else:
            logger.warning(
                "买入委托失败: symbol={}, shares={}, price={}, error={}",
                symbol,
                shares,
                price,
                result.get("error", "未知错误"),
            )
        return result

    @app.post("/api/trade/sell")
    def sell_stock(request, symbol: str, price: float, shares: int, qtoid: str = "", strategy_id: str = ""):
        """卖出股票"""
        require_api_key_or_session(request)
        logger.info("收到卖出委托请求: symbol={}, price={}, shares={}", symbol, price, shares)
        result = trade_service.sell(symbol, price, shares, qtoid=qtoid, strategy_id=strategy_id)
        if result.get("success"):
            logger.info(
                "卖出委托已提交: symbol={}, shares={}, price={}, qtoid={}, order_id={}",
                symbol,
                shares,
                price,
                result.get("qtoid", ""),
                result.get("order_id", ""),
            )
        else:
            logger.warning(
                "卖出委托失败: symbol={}, shares={}, price={}, error={}",
                symbol,
                shares,
                price,
                result.get("error", "未知错误"),
            )
        return result

    @app.post("/api/trade/cancel")
    def cancel_order(request, qtoid: str = "", order_id: str = "", view: str = "json"):
        """撤单"""
        require_api_key_or_session(request)
        target_order_id = qtoid or order_id
        logger.info("收到撤单请求: order_id={}", target_order_id)
        result = trade_service.cancel_order(target_order_id)
        if result.get("success"):
            logger.info("撤单请求已提交: order_id={}, qtoid={}", target_order_id, result.get("qtoid", ""))
        else:
            logger.warning("撤单请求失败: order_id={}, error={}", target_order_id, result.get("error", "未知错误"))
        if view == "table":
            from qmt_gateway.web.pages.trading import OrdersTable
            return _render_fragment(OrdersTable(get_latest_orders_data()))
        return result

    @app.post("/api/asset/principal")
    def update_principal(request, principal: float):
        """修改本金

        修改本金会在 asset 表中插入一条新的记录。
        如果当天已有记录，则更新该记录的本金字段。

        Args:
            principal: 新本金金额

        Returns:
            JSONResponse: 操作结果
        """
        user = require_api_key_or_session(request)

        if principal <= 0:
            return JSONResponse(
                {"code": 1, "message": "本金金额必须大于0"},
                status_code=400
            )

        try:
            portfolio_id = DEFAULT_PORTFOLIO_ID
            existing = _get_latest_asset(portfolio_id)

            if existing:
                existing.principal = principal
                db["assets"].upsert(existing.to_dict(), pk=Asset.__pk__)
                logger.info(
                    f"更新本金: portfolio_id={portfolio_id}, dt={existing.dt}, principal={principal}"
                )
            else:
                today = datetime.date.today()
                current_asset = get_latest_asset_data(portfolio_id)
                new_asset = Asset(
                    portfolio_id=portfolio_id,
                    dt=today,
                    principal=principal,
                    cash=_as_float(current_asset.get("cash", 0)),
                    frozen_cash=_as_float(current_asset.get("frozen_cash", 0)),
                    market_value=_as_float(current_asset.get("market_value", 0)),
                    total=_as_float(current_asset.get("total", principal), principal),
                )

                db.insert_asset(new_asset)
                logger.info(
                    f"插入新本金记录: portfolio_id={portfolio_id}, dt={today}, principal={principal}"
                )

            latest_asset = _get_latest_asset(portfolio_id)
            latest_date = latest_asset.dt if latest_asset else datetime.date.today()
            return JSONResponse({
                "code": 0,
                "message": "本金修改成功",
                "data": {
                    "principal": principal,
                    "date": latest_date.isoformat(),
                }
            })

        except Exception as e:
            logger.error(f"修改本金失败: {e}")
            return JSONResponse(
                {"code": 1, "message": f"修改本金失败: {str(e)}"},
                status_code=500
            )
