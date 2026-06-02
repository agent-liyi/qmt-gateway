"""API key 管理。

颁发仅显示一次的程序化访问令牌。原始明文不存储，仅保留
``sha256`` 摘要用于校验；列表接口也只回显前缀。

颁发接口需要登录会话；调用 ``/api/...`` 的程序化端点可通过
``X-API-Key`` 请求头携带令牌访问（见 :func:`require_api_key_or_session`）。
"""

import datetime
import hashlib
import secrets

from fasthtml.common import *
from loguru import logger
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

from qmt_gateway.db import db
from qmt_gateway.db.models import ApiKey


API_KEY_PREFIX = "qmt_"
API_KEY_RANDOM_BYTES = 32
API_KEY_VISIBLE_PREFIX_LEN = 12


def _hash_api_key(plaintext: str) -> str:
    """计算 API key 的 sha256 摘要，用于存储与校验。"""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def generate_api_key() -> tuple[str, str, str]:
    """生成新的 API key。

    Returns:
        (plaintext, key_hash, key_prefix) 三元组。
        - ``plaintext`` 应当仅返回给用户一次；
        - ``key_hash`` 写入数据库用于校验；
        - ``key_prefix`` 写入数据库用于列表显示。
    """
    random_part = secrets.token_hex(API_KEY_RANDOM_BYTES)
    plaintext = f"{API_KEY_PREFIX}{random_part}"
    key_hash = _hash_api_key(plaintext)
    key_prefix = plaintext[:API_KEY_VISIBLE_PREFIX_LEN]
    return plaintext, key_hash, key_prefix


def _serialize(key: ApiKey) -> dict:
    """将 API key 序列化为对外可见的 dict（不含 hash）。"""
    return {
        "id": key.id,
        "name": key.name,
        "key_prefix": key.key_prefix,
        "created_at": key.created_at.isoformat() if key.created_at else None,
        "last_used_at": key.last_used_at.isoformat() if key.last_used_at else None,
        "revoked": key.is_revoked,
    }


def _require_session(request) -> dict:
    """检查请求是否已登录（仅会话认证，不接受 API key）。

    用于颁发/吊销 API key 的管理接口：必须由已登录用户操作，
    防止使用 API key 自行颁发新 key。
    """
    user = request.scope.get("session", {}).get("user")
    if not user:
        raise HTTPException(status_code=401, detail="未登录")
    return user


def handle_create_api_key(request, name: str = ""):
    """处理 API key 创建请求。"""
    _require_session(request)
    timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    label = (name or "").strip() or f"key-{timestamp}"
    plaintext, key_hash, key_prefix = generate_api_key()
    record = ApiKey(
        name=label,
        key_hash=key_hash,
        key_prefix=key_prefix,
    )
    db.insert_api_key(record)
    logger.info(f"创建 API key: name={label}, prefix={key_prefix}")
    return JSONResponse(
        {
            "code": 0,
            "message": "ok",
            "data": {
                "id": record.id,
                "name": record.name,
                "key_prefix": key_prefix,
                "plaintext": plaintext,
            },
        }
    )


def handle_list_api_keys(request):
    """列出全部 API key（不含明文与 hash）。"""
    _require_session(request)
    records = db.list_api_keys()
    return JSONResponse(
        {
            "code": 0,
            "message": "ok",
            "data": [_serialize(record) for record in records],
        }
    )


def handle_revoke_api_key(request, key_id: str):
    """吊销指定 API key。"""
    _require_session(request)
    if not key_id:
        return JSONResponse({"code": 1, "message": "key id 不能为空"}, status_code=400)
    if not db.revoke_api_key(key_id):
        return JSONResponse({"code": 1, "message": "API key 不存在"}, status_code=404)
    logger.info(f"吊销 API key: id={key_id}")
    return JSONResponse({"code": 0, "message": "ok"})


def _login_or_api_key(request) -> tuple[dict | None, ApiKey | None]:
    """从 session 或 ``X-API-Key`` 头解析身份。

    Returns:
        ``(user, None)`` 表示 session 登录；
        ``(None, api_key)`` 表示通过 API key 认证；
        校验失败时抛 :class:`HTTPException`。
    """
    user = request.scope.get("session", {}).get("user")
    if user:
        return user, None

    header_value = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if not header_value:
        raise HTTPException(status_code=401, detail="未登录或缺少 API key")

    key_hash = _hash_api_key(header_value.strip())
    record = db.get_api_key_by_hash(key_hash)
    if record is None:
        raise HTTPException(status_code=401, detail="API key 无效或已吊销")

    db.touch_api_key_last_used(record.id)
    return None, record


def require_api_key_or_session(request):
    """请求级鉴权依赖：session 登录或 ``X-API-Key`` 任一通过即可。"""
    user, _ = _login_or_api_key(request)
    return user


def register_routes(app):
    """注册 API key 管理路由。"""

    @app.post("/api/api-keys")
    def post_create_api_key(request, name: str = ""):
        return handle_create_api_key(request, name=name)

    @app.get("/api/api-keys")
    def get_list_api_keys(request):
        return handle_list_api_keys(request)

    @app.delete("/api/api-keys/{key_id}")
    def delete_revoke_api_key(request, key_id: str):
        return handle_revoke_api_key(request, key_id)
