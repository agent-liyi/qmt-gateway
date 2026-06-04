"""系统级 ping 接口.

供外部应用（如 Millionaire）做轻量级连通性 + 鉴权体检：

- 可达性：是否能建立 HTTP 连接
- 鉴权：当前配置的 API key（或会话）是否被网关接受
- 延迟：往返时延

无副作用；不读取 QMT 账户/持仓等业务数据，便于在初始化向导阶段调用。
"""

from __future__ import annotations

import time

from loguru import logger

from qmt_gateway.apis.api_keys import require_api_key_or_session

PING_PATH = "/api/ping"


def register_routes(app) -> None:
    """注册 ping 路由。"""

    @app.get(PING_PATH)
    def get_ping(request):
        start = time.perf_counter()
        # 复用 API key / session 鉴权，认证失败会直接抛 401
        require_api_key_or_session(request)
        latency_ms = int((time.perf_counter() - start) * 1000)
        logger.debug(f"ping ok in {latency_ms}ms")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "ok": True,
                "latency_ms": latency_ms,
            },
        }


__all__ = ["PING_PATH", "register_routes"]
