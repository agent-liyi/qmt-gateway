"""认证 API

提供登录、登出和修改密码功能。
"""

import bcrypt
from fastcore.xml import to_xml
from fasthtml.common import *
from loguru import logger
from starlette.responses import HTMLResponse

from qmt_gateway.core.crypto_utils import _derive_key
from qmt_gateway.db import db
from qmt_gateway.db.models import User


def hash_password(password: str) -> str:
    """哈希密码"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """验证密码"""
    return bcrypt.checkpw(password.encode(), hashed.encode())


def login_required(handler):
    """登录验证装饰器"""
    def wrapper(request, *args, **kwargs):
        # 从 session 获取用户信息
        user = request.scope.get("session", {}).get("user")
        if not user:
            return RedirectResponse("/login", status_code=302)
        return handler(request, *args, **kwargs)
    return wrapper


def login_page(error: str = ""):
    """登录页面"""
    from qmt_gateway.web.layouts.base import create_base_page
    from qmt_gateway.web.theme import PRIMARY_COLOR, PrimaryButton

    error_msg = Div(error, cls="text-red-500 text-sm mb-4") if error else ""

    return create_base_page(
        Div(
            H3("QMT Gateway", cls="text-2xl font-bold text-center mb-2", style=f"color: {PRIMARY_COLOR};"),
            P("请登录以继续", cls="text-gray-500 text-center mb-6"),
            error_msg,
            Form(
                Div(
                    Label("用户名", cls="label"),
                    Input(
                        type="text",
                        name="username",
                        placeholder="请输入用户名",
                        cls="input input-bordered w-full",
                        required="required",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Label("密码", cls="label"),
                    Input(
                        type="password",
                        name="password",
                        placeholder="请输入密码",
                        cls="input input-bordered w-full",
                        required="required",
                    ),
                    cls="mb-4",
                ),
                Div(
                    Input(
                        type="checkbox",
                        name="auto_login",
                        id="auto_login",
                        cls="w-4 h-4 text-red-600 border-gray-300 rounded focus:ring-red-500",
                    ),
                    Label("本机自动登录", _for="auto_login", cls="ml-2 text-sm text-gray-700 cursor-pointer"),
                    cls="flex items-center mb-6",
                ),
                PrimaryButton("登录", type="submit", cls="w-full"),
                action="/auth/login",
                method="post",
            ),
            cls="max-w-md mx-auto bg-white rounded-lg shadow p-8 mt-12",
        ),
        page_title="登录 - QMT Gateway",
    )


def _render_page(page) -> HTMLResponse:
    """Render a full HTML page explicitly to avoid FastHTML tuple wrapping bugs."""
    return HTMLResponse(to_xml(page))


def handle_login(request, username: str, password: str, auto_login: bool = False):
    """处理登录请求"""
    user = db.get_user(username)

    if not user:
        return _render_page(login_page("用户名或密码错误"))

    if not verify_password(password, user.password_hash):
        return _render_page(login_page("用户名或密码错误"))

    # 更新自动登录设置
    if auto_login != user.auto_login:
        user.auto_login = auto_login
        db.save_user(user)

    # 设置 session
    request.scope["session"]["user"] = {
        "id": user.id,
        "username": user.username,
        "is_admin": user.is_admin,
    }

    # 如果已设置 QMT 交易密码，预计算解密密钥存储在 session 中
    settings = db.get_settings()
    if settings.qmt_password_encrypted and settings.qmt_password_salt:
        try:
            import base64
            salt_bytes = bytes.fromhex(settings.qmt_password_salt)
            derived_key = _derive_key(password, salt_bytes)
            request.scope["session"]["qmt_decrypt_key"] = derived_key.decode("ascii")
        except Exception as e:
            logger.warning(f"预计算 QMT 密码解密密钥失败: {e}")

    logger.info(f"用户登录成功: {username}, 自动登录: {auto_login}")
    return RedirectResponse("/", status_code=302)


def handle_logout(request):
    """处理登出请求"""
    request.scope["session"].clear()
    return RedirectResponse("/login", status_code=302)


def handle_change_password(
    request,
    old_password: str,
    new_password: str,
    new_password_confirm: str = "",
):
    """处理修改密码请求

    修改成功后立即使当前会话失效，强制用户重新登录。
    """
    user_info = request.scope.get("session", {}).get("user")
    if not user_info:
        return {"success": False, "message": "未登录"}

    user = db.get_user(user_info["username"])
    if not user:
        return {"success": False, "message": "用户不存在"}

    if not old_password or not new_password:
        return {"success": False, "message": "请填写完整"}

    if not verify_password(old_password, user.password_hash):
        return {"success": False, "message": "原密码错误"}

    if new_password != new_password_confirm:
        return {"success": False, "message": "两次输入的新密码不一致"}

    if new_password == old_password:
        return {"success": False, "message": "新密码不能与原密码相同"}

    # 更新密码
    user.password_hash = hash_password(new_password)
    db.save_user(user)

    # 重新加密 QMT 交易密码（使用新登录密码作为密钥）
    settings = db.get_settings()
    if settings.qmt_password_encrypted and settings.qmt_password_salt:
        try:
            from qmt_gateway.core.crypto_utils import (
                decrypt_password,
                encrypt_password,
            )
            qmt_password = decrypt_password(
                settings.qmt_password_encrypted,
                settings.qmt_password_salt,
                old_password,
            )
            new_encrypted, new_salt = encrypt_password(qmt_password, new_password)
            settings.qmt_password_encrypted = new_encrypted
            settings.qmt_password_salt = new_salt

            if settings.auto_start_qmt:
                from qmt_gateway.core.crypto_utils import encrypt_for_auto_start
                settings.qmt_password_auto_start = encrypt_for_auto_start(qmt_password)

            db.save_settings(settings)
            logger.info(f"已使用新登录密码重新加密 QMT 交易密码")
        except Exception as e:
            logger.warning(f"重新加密 QMT 交易密码失败: {e}")
            # 不阻断密码修改流程，用户可以在修改后重新设置 QMT 密码

    # 强制重新登录
    request.scope["session"].clear()
    logger.info(f"用户修改密码成功并已注销会话: {user.username}")
    return {"success": True, "message": "密码修改成功"}


def handle_change_qmt_password(
    request,
    login_password: str,
    new_qmt_password: str,
    new_qmt_password_confirm: str = "",
):
    """处理修改 QMT 交易密码请求。

    需要验证登录密码，然后使用登录密码作为密钥加密新的 QMT 交易密码。
    """
    user_info = request.scope.get("session", {}).get("user")
    if not user_info:
        return {"success": False, "message": "未登录"}

    user = db.get_user(user_info["username"])
    if not user:
        return {"success": False, "message": "用户不存在"}

    if not login_password:
        return {"success": False, "message": "请输入登录密码"}

    if not verify_password(login_password, user.password_hash):
        return {"success": False, "message": "登录密码错误"}

    if not new_qmt_password:
        return {"success": False, "message": "请输入 QMT 交易密码"}

    if new_qmt_password != new_qmt_password_confirm:
        return {"success": False, "message": "两次输入的 QMT 交易密码不一致"}

    # 加密并存储新的 QMT 交易密码
    from qmt_gateway.core.crypto_utils import encrypt_password

    try:
        encrypted, salt = encrypt_password(new_qmt_password, login_password)
        settings = db.get_settings()
        settings.qmt_password_encrypted = encrypted
        settings.qmt_password_salt = salt

        if settings.auto_start_qmt:
            from qmt_gateway.core.crypto_utils import encrypt_for_auto_start
            settings.qmt_password_auto_start = encrypt_for_auto_start(new_qmt_password)
        else:
            settings.qmt_password_auto_start = ""

        db.save_settings(settings)

        # 更新 session 中的解密密钥
        import base64
        salt_bytes = bytes.fromhex(salt)
        derived_key = _derive_key(login_password, salt_bytes)
        request.scope["session"]["qmt_decrypt_key"] = derived_key.decode("ascii")

        logger.info(f"QMT 交易密码已更新: {user.username}")
        return {"success": True, "message": "QMT 交易密码已保存"}
    except Exception as e:
        logger.warning(f"保存 QMT 交易密码失败: {e}")
        return {"success": False, "message": f"保存失败: {e}"}


def register_routes(app):
    """注册认证路由"""

    @app.get("/login")
    def get_login():
        return _render_page(login_page())

    @app.post("/auth/login")
    def post_login(request, username: str, password: str, auto_login: str = ""):
        return handle_login(request, username, password, auto_login=auto_login == "on")

    @app.get("/auth/logout")
    def get_logout(request):
        return handle_logout(request)

    @app.post("/auth/password")
    def post_change_password(
        request,
        old_password: str,
        new_password: str,
        new_password_confirm: str = "",
    ):
        return handle_change_password(
            request,
            old_password,
            new_password,
            new_password_confirm=new_password_confirm,
        )

    @app.post("/auth/qmt-password")
    def post_change_qmt_password(
        request,
        login_password: str,
        new_qmt_password: str,
        new_qmt_password_confirm: str = "",
    ):
        return handle_change_qmt_password(
            request,
            login_password,
            new_qmt_password,
            new_qmt_password_confirm=new_qmt_password_confirm,
        )
