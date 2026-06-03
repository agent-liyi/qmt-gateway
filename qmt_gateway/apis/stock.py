"""股票信息 API

提供股票查询、搜索等功能。
"""

from fastcore.xml import to_xml
from fasthtml.common import *
from loguru import logger
from starlette.responses import HTMLResponse

from qmt_gateway.apis.api_keys import require_api_key_or_session
from qmt_gateway.services.stock_service import stock_service


def _render_fragment(fragment) -> HTMLResponse:
    return HTMLResponse(to_xml(fragment))


def _to_float(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _extract_pre_close(tick_data: dict) -> float:
    for key in ("preClose", "lastClose", "prevClose", "pre_close", "last_close"):
        value = _to_float(tick_data.get(key))
        if value > 0:
            return value
    return 0.0


def _get_last_close_from_xtdata(xtdata, symbol: str) -> float:
    try:
        full_tick = xtdata.get_full_tick([symbol])
        if isinstance(full_tick, dict):
            tick = full_tick.get(symbol)
            if isinstance(tick, dict):
                value = _extract_pre_close(tick)
                if value > 0:
                    return value
    except Exception:
        pass
    try:
        history = xtdata.get_market_data(["close"], [symbol], period="1d", count=1)
        if history and symbol in history:
            close_series = history[symbol]["close"]
            if len(close_series) > 0:
                value = _to_float(close_series.iloc[-1])
                if value > 0:
                    return value
    except Exception:
        pass
    return 0.0


def register_routes(app):
    """注册股票相关路由"""

    @app.get("/api/stocks/search")
    def search_stocks(request, stock_search: str = ""):
        """搜索股票（带自动补全）

        该端点会被搜索下拉控件在浏览器中频繁调用，因此保留
        session 鉴权即可，外部脚本无法拿到 cookie。
        """
        require_api_key_or_session(request)

        q = stock_search

        if not q or len(q) < 1:
            return ""

        stocks = stock_service.search_stocks(q)

        if not stocks:
            return _render_fragment(Div("无匹配结果", cls="p-2 text-gray-500 text-sm"))
        
        # 如果只有一个结果，自动填充
        if len(stocks) == 1:
            stock = stocks[0]
            safe_name = stock.name.replace("'", "\\'")
            return _render_fragment(Div(
                # 下拉列表显示
                Div(
                    Div(
                        Span(stock.name, cls="font-medium"),
                        Span(f" ({stock.symbol})", cls="text-gray-500 text-sm ml-1"),
                        Span(f" {stock.pinyin}", cls="text-gray-400 text-xs ml-1"),
                        cls="p-2 hover:bg-blue-50 cursor-pointer",
                        onclick=f"if(window.selectStock){{window.selectStock('{stock.symbol}', '{safe_name}', {stock.last_close});}}else{{console.error('selectStock not found');}}",
                    ),
                ),
                # 自动填充脚本
                Script(f"""
                    setTimeout(function() {{
                        if(window.selectStock) {{
                            window.selectStock('{stock.symbol}', '{safe_name}', {stock.last_close});
                        }} else {{
                            console.error('selectStock not found');
                        }}
                    }}, 100);
                """),
            ))

        # 多个结果，显示下拉列表
        items = []
        for stock in stocks[:10]:  # 最多显示10个
            # 转义股票名称中的单引号，避免 JavaScript 语法错误
            safe_name = stock.name.replace("'", "\\'")
            items.append(
                Div(
                    Div(
                        Span(stock.name, cls="font-medium"),
                        Span(f" ({stock.symbol})", cls="text-gray-500 text-sm ml-1"),
                        Span(f" {stock.pinyin}", cls="text-gray-400 text-xs ml-1"),
                        cls="p-2 hover:bg-blue-50 cursor-pointer",
                        onclick=f"if(window.selectStock){{window.selectStock('{stock.symbol}', '{safe_name}', {stock.last_close});}}else{{console.error('selectStock not found');}}",
                    ),
                )
            )
        
        return _render_fragment(Div(*items))

    @app.get("/api/stock/info")
    def get_stock_info(request, symbol: str = ""):
        """获取股票信息并返回 Speed Dial HTML

        Args:
            symbol: 股票代码

        Returns:
            Speed Dial HTML
        """
        require_api_key_or_session(request)
        from qmt_gateway.web.pages.trading import SpeedDialGrid

        if not symbol:
            return _render_fragment(SpeedDialGrid(0))

        stock = stock_service.get_stock(symbol)
        if stock and stock.last_close > 0:
            return _render_fragment(SpeedDialGrid(stock.last_close))

        try:
            from qmt_gateway.core.xtwrapper import require_xtdata
            xtdata = require_xtdata()
            last_close = _get_last_close_from_xtdata(xtdata, symbol)
            return _render_fragment(SpeedDialGrid(last_close))
        except Exception as e:
            logger.warning(f"获取股票 {symbol} 信息失败: {e}")
            return _render_fragment(SpeedDialGrid(0))

    @app.get("/api/stock/resolve")
    def resolve_stock(request, q: str = ""):
        """根据输入内容解析股票代码。

        Args:
            q: 用户输入的名称、代码或拼音

        Returns:
            股票解析结果
        """
        require_api_key_or_session(request)
        keyword = (q or "").strip()
        if not keyword:
            return {"ok": False}
        stocks = stock_service.search_stocks(keyword)
        if not stocks:
            return {"ok": False}
        normalized_keyword = keyword.upper()
        preferred = None
        exact_code_matches = []
        for item in stocks:
            symbol = (item.symbol or "").upper()
            code = symbol.split(".")[0]
            if item.name == keyword or symbol == normalized_keyword:
                preferred = item
                break
            if code == normalized_keyword:
                exact_code_matches.append(item)
        if preferred is not None:
            target = preferred
        elif len(exact_code_matches) == 1:
            target = exact_code_matches[0]
        elif len(stocks) == 1:
            target = stocks[0]
        else:
            return {"ok": False, "ambiguous": True, "count": len(stocks)}
        last_close = float(target.last_close or 0)
        if last_close <= 0:
            try:
                from qmt_gateway.core.xtwrapper import require_xtdata
                xtdata = require_xtdata()
                last_close = _get_last_close_from_xtdata(xtdata, target.symbol)
            except Exception:
                pass
        return {
            "ok": True,
            "symbol": target.symbol,
            "name": target.name,
            "last_close": last_close,
        }

    @app.get("/api/stocks")
    def get_all_stocks(request):
        """获取所有股票列表"""
        require_api_key_or_session(request)
        stocks = stock_service.get_all_stocks()
        return [s.to_dict() for s in stocks]
