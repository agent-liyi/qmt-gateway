"""FastHTML 应用主入口

组装所有路由和中间件。
"""

import asyncio
import datetime
from contextlib import asynccontextmanager
from pathlib import Path

from fastcore.xml import to_xml
from fasthtml.common import *
from loguru import logger
from qmt_gateway.access_log import configure_access_log
from qmt_gateway.apis import (
    login_required,
    auction_ws,
    quote_ws,
    register_api_key_routes,
    register_ping_routes,
    register_auction_routes,
    register_auth_routes,
    register_history_routes,
    register_quotes_routes,
    register_stock_routes,
    register_system_routes,
    register_trade_routes,
)
from qmt_gateway.apis.auth import hash_password
from qmt_gateway.config import config
from qmt_gateway.db import db
from qmt_gateway.db.models import Asset, Settings, User
from qmt_gateway.runtime import runtime
from qmt_gateway.services.scheduler import scheduler
from qmt_gateway.web.pages.data_mgmt import DataMgmtPage
from qmt_gateway.web.pages.init_wizard import (
    InitWizardForm,
    InitWizardPage,
    _WizardProgressModal,
)
from qmt_gateway.web.pages.logs import LogsPage
from qmt_gateway.web.pages.trading import TradingPage
from qmt_gateway.web.theme import PRIMARY_COLOR
from starlette.responses import HTMLResponse, StreamingResponse

# 存储向导表单数据的临时缓存
_wizard_data: dict = {}

# 后台 QMT 重启任务状态：None=未启动, {}=运行中, {"success":...}=已完成
_restart_status: dict | None = None


def _render_page(page) -> HTMLResponse:
    """显式渲染完整页面，规避 FastHTML 在文档响应上的兼容问题。"""
    return HTMLResponse(to_xml(page))


def _render_fragment(*fragments) -> HTMLResponse:
    """显式渲染 HTMX 片段，规避 FastHTML 片段响应兼容问题。

    支持多个片段同时输出（用于 OOB 交换）。
    """
    return HTMLResponse(to_xml(fragments if len(fragments) > 1 else fragments[0]))


def _redirect_after_hx(request, location: str = "/"):
    """Prefer HTMX-native redirects so wizard completion jumps immediately.

    Plain ``302`` responses work for full-page requests, but HTMX may follow
    them as an AJAX request and only swap the resulting HTML later. Returning
    ``HX-Redirect`` makes the browser navigate as soon as the response arrives.
    """

    if str(request.headers.get("HX-Request", "")).lower() == "true":
        return HTMLResponse("", headers={"HX-Redirect": location})
    return RedirectResponse(location, status_code=302)


def _seed_wizard_data_from_current_settings() -> dict:
    """用数据库中现有的 settings 与管理员账号预填向导表单。

    这样在 ``force=true`` 模式下，用户一路点击"下一步"而不修改任何字段，
    最终点击"完成初始化"时，提交的内容与原值一致，**等价于一次 no-op**。
    """
    seed: dict = {}
    try:
        settings = db.get_settings()
    except Exception:
        settings = None
    if settings is not None:
        seed["server_port"] = str(settings.server_port)
        seed["log_path"] = settings.log_path
        seed["log_rotation"] = settings.log_rotation
        seed["log_retention"] = str(settings.log_retention)
        seed["qmt_account_id"] = settings.qmt_account_id
        seed["qmt_path"] = settings.qmt_path
        seed["xtquant_path"] = settings.xtquant_path
        seed["principal"] = "1000000"  # 本金不强制保留；给个默认以便 no-op
    try:
        existing = db.get_user("admin")
        if existing is not None:
            seed["username"] = existing.username
    except Exception:
        pass
    return seed


def _snapshot_wizard_state(username: str) -> dict:
    """在 ``/init-wizard/complete`` 落盘前抓取需要回滚的字段。

    涵盖：
    - 现有 settings（用于回滚端口、日志、QMT 路径等）
    - 现管理员用户的 ``password_hash``、``auto_login``（密码可能被改写）
    - 现有 ``assets`` 表中 ``portfolio_id='default'`` 当天那一行（本金可能被改写）
    """
    snapshot: dict = {"settings": None, "user": None, "asset": None}
    try:
        snapshot["settings"] = db.get_settings().to_dict()
    except Exception:
        pass
    try:
        user = db.get_user(username) if username else None
        if user is not None:
            snapshot["user"] = user.to_dict()
    except Exception:
        pass
    try:
        asset_row = db.conn.execute(
            """
            select portfolio_id, dt, principal, cash, frozen_cash,
                   market_value, total
            from assets
            where portfolio_id = ?
            order by dt desc
            limit 1
            """,
            ("default",),
        ).fetchone()
        if asset_row is not None:
            snapshot["asset"] = {
                "portfolio_id": asset_row[0],
                "dt": asset_row[1],
                "principal": asset_row[2],
                "cash": asset_row[3],
                "frozen_cash": asset_row[4],
                "market_value": asset_row[5],
                "total": asset_row[6],
            }
    except Exception:
        pass
    return snapshot


def _rollback_wizard_state(snapshot: dict) -> None:
    """根据 :func:`_snapshot_wizard_state` 抓取的内容恢复 DB。

    任一字段不存在时（首次初始化、用户从未被创建过等）会跳过该字段的恢复。
    """
    if not snapshot:
        return
    if snapshot.get("settings") is not None:
        try:
            db.save_settings(Settings.from_dict(snapshot["settings"]))
        except Exception as e:
            logger.error(f"回滚 settings 失败: {e}")
    if snapshot.get("user") is not None:
        try:
            db.save_user(User.from_dict(snapshot["user"]))
        except Exception as e:
            logger.error(f"回滚 user 失败: {e}")
    if snapshot.get("asset") is not None:
        try:
            asset = Asset.from_dict(snapshot["asset"])
            db["assets"].upsert(asset.to_dict(), pk=Asset.__pk__)
        except Exception as e:
            logger.error(f"回滚 asset 失败: {e}")


def _build_settings_from_wizard_data(wizard_data: dict) -> "Settings":
    """根据向导表单数据构造新的 Settings 对象（不落库）。"""
    try:
        server_port = int(wizard_data.get("server_port", 8130))
    except (TypeError, ValueError):
        server_port = 8130
    try:
        log_retention = int(wizard_data.get("log_retention", 10))
    except (TypeError, ValueError):
        log_retention = 10

    new_settings = db.get_settings()
    new_settings.server_port = server_port
    new_settings.log_path = str(
        Path(wizard_data.get("log_path", "~/.qmt-gateway/log"))
        .expanduser()
        .resolve()
    )
    new_settings.log_rotation = wizard_data.get("log_rotation", "10 MB")
    new_settings.log_retention = log_retention
    new_settings.qmt_account_id = wizard_data.get("qmt_account_id", "")

    qmt_path = wizard_data.get("qmt_path", "")
    new_settings.qmt_path = str(Path(qmt_path).expanduser().resolve()) if qmt_path else ""

    xtquant_path = wizard_data.get("xtquant_path", "")
    new_settings.xtquant_path = str(Path(xtquant_path).expanduser().resolve()) if xtquant_path else ""

    # 加密存储 QMT 交易密码：只要用户填了就保存，与 auto_start_qmt 无关
    qmt_password = wizard_data.get("qmt_password", "")
    admin_password = wizard_data.get("password", "")
    auto_start_qmt = wizard_data.get("auto_start_qmt") == "on"
    new_settings.auto_start_qmt = auto_start_qmt

    if qmt_password and admin_password:
        from qmt_gateway.core.crypto_utils import encrypt_password
        encrypted, salt = encrypt_password(qmt_password, admin_password)
        new_settings.qmt_password_encrypted = encrypted
        new_settings.qmt_password_salt = salt

    # auto-start 专用加密：仅当用户授权自动重启时生成（机器密钥加密，
    # 供进程启动时无 session 解密使用）
    if auto_start_qmt and qmt_password:
        from qmt_gateway.core.crypto_utils import encrypt_for_auto_start
        new_settings.qmt_password_auto_start = encrypt_for_auto_start(qmt_password)
    else:
        new_settings.qmt_password_auto_start = ""

    new_settings.init_step = 5
    return new_settings


def _commit_wizard_settings(wizard_data: dict, new_settings) -> None:
    """原子提交向导配置：用户、Settings、本金、标记初始化完成。"""
    username = wizard_data.get("username", "admin")
    password = wizard_data.get("password", "")

    try:
        principal = float(wizard_data.get("principal", 1000000))
        if principal <= 0:
            principal = 1000000
    except (TypeError, ValueError):
        principal = 1000000

    if password:
        existing_user = db.get_user(username)
        if existing_user is not None:
            existing_user.password_hash = hash_password(password)
            existing_user.auto_login = False
            db.save_user(existing_user)
            logger.info(f"更新现有用户: {username}")
        else:
            db.save_user(
                User(
                    username=username,
                    password_hash=hash_password(password),
                    auto_login=False,
                )
            )
            logger.info(f"创建新用户: {username}")

    db.save_settings(new_settings)

    today = datetime.date.today()
    portfolio_id = "default"
    asset_row = db.conn.execute(
        """
        select cash, frozen_cash, market_value, total
        from assets
        where portfolio_id = ?
        order by dt desc
        limit 1
        """,
        (portfolio_id,),
    ).fetchone()
    if asset_row:
        cash = float(asset_row[0] or 0)
        frozen_cash = float(asset_row[1] or 0)
        market_value = float(asset_row[2] or 0)
        total = float(asset_row[3] or principal)
    else:
        cash = principal
        frozen_cash = 0.0
        market_value = 0.0
        total = principal

    initial_asset = Asset(
        portfolio_id=portfolio_id,
        dt=today,
        principal=principal,
        cash=cash,
        frozen_cash=frozen_cash,
        market_value=market_value,
        total=total if total > 0 else principal,
    )
    db["assets"].upsert(initial_asset.to_dict(), pk=Asset.__pk__)

    new_settings.init_completed = True
    new_settings.init_completed_at = datetime.datetime.now()
    db.save_settings(new_settings)
    config.reload()


def check_init_required():
    """检查是否需要初始化"""
    try:
        settings = db.get_settings()
        return not settings.init_completed
    except Exception:
        return True


def create_app():
    """创建 FastHTML 应用"""

    # 初始化运行时
    runtime.init()
    configure_access_log(config.log_path)

    # 创建 FastHTML 应用
    app = FastHTML(
        hdrs=[
            # Tailwind Play CDN（v3 JIT 编译器，本地化；与原 CDN 渲染行为完全一致，
            # 保留全部 v3 原子类，包括 .shrink-0 .gap-x-* .focus:ring-* 等）。
            # 体积 ~400 KB（含编译器），小于 v2 预编译的 ~3 MB CSS。
            Script(src="/static/tailwind.min.js"),
            # DaisyUI（主题层；.btn .loading .text-primary 等组件）
            Link(rel="stylesheet", href="/static/daisyui.min.css"),
            # HTMX
            Script(src="/static/htmx.min.js"),
        ],
        session_cookie="qmt_gateway_session",
    )

    # 本地静态资源（/static/* -> qmt_gateway/web/static/*）。
    # 使用绝对路径而不是相对路径，避开"以哪个目录为 cwd"的歧义——
    # 安装后 cwd 是 $INSTDIR，开发时是仓库根，只有绝对路径两种场景都正确。
    _static_dir = Path(__file__).resolve().parent / "web" / "static"
    if _static_dir.is_dir():
        app.static_route_exts(prefix="/static/", static_path=str(_static_dir))

    # 注册 API 路由
    register_auth_routes(app)
    register_trade_routes(app)
    register_quotes_routes(app)
    register_auction_routes(app)
    register_stock_routes(app)
    register_history_routes(app)
    register_api_key_routes(app)
    register_ping_routes(app)
    register_system_routes(app)

    # 初始化向导路由
    @app.get("/init-wizard")
    def init_wizard(force: str = None):
        """初始化向导页面

        Args:
            force: 如果为 "true"，强制重新运行初始化向导

        注意：``force=true`` 走完全只读的流程，**不会在打开页面时修改任何持久化状态**。
        所有数据仅缓存在进程内的 ``_wizard_data``，直到用户最终点击
        ``完成初始化`` 时才会一次性原子提交。如果用户中途关闭页面，原有
        ``init_completed`` 状态保持不变，主应用继续可用。
        """
        global _wizard_data

        # 非 force 模式且已初始化完成 → 回到首页
        if force != "true" and not check_init_required():
            return RedirectResponse("/", status_code=302)

        # force 模式：用现有 settings 与管理员账号预填表单，以便用户在
        # 不修改任何字段时点击"完成初始化"等同于"保持现状"。
        if force == "true":
            try:
                _wizard_data = _seed_wizard_data_from_current_settings()
                logger.info("进入强制重新初始化向导（仅内存暂存，未落盘）")
            except Exception as e:
                logger.error(f"预填向导初始数据失败: {e}")
                _wizard_data = {}
        else:
            # 首次初始化：清空暂存
            _wizard_data = {}

        return _render_page(InitWizardPage(step=1))

    @app.post("/init-wizard/step/{step}")
    async def wizard_step(step: int, request):
        """向导步骤处理"""
        global _wizard_data

        # 保存当前步骤的数据（从表单数据获取）
        form_data = await request.form()
        form_dict = {k: v for k, v in form_data.items()}
        _wizard_data.update(form_dict)
        # HTML checkbox 未勾选时不提交，需要显式重置残留值
        if "auto_start_qmt" not in form_dict:
            _wizard_data["auto_start_qmt"] = ""
        logger.info(f"接收到表单数据: {form_dict}")

        # 第2步（管理员设置）点击下一步时，校验密码一致性与非空（#32）
        if step == 3:  # 即将进入第3步（服务器设置）
            password = _wizard_data.get("password", "")
            password_confirm = _wizard_data.get("password_confirm", "")
            logger.info(f"第2步密码校验: password='{password}', password_confirm='{password_confirm}'")
            if not password or not password.strip():
                return _render_fragment(
                    InitWizardForm(
                        step=2,
                        form_data=_wizard_data,
                        error="管理员密码不能为空，请输入密码后继续",
                    ),
                    _WizardProgressModal(visible=False, oob=True),
                )
            if password != password_confirm:
                return _render_fragment(
                    InitWizardForm(
                        step=2,
                        form_data=_wizard_data,
                        error="两次输入的密码不一致，请重新输入",
                    ),
                    _WizardProgressModal(visible=False, oob=True),
                )

        # 返回表单部分（用于 HTMX 更新）+ OOB 隐藏进度对话框
        return _render_fragment(
            InitWizardForm(step=step, form_data=_wizard_data),
            _WizardProgressModal(visible=False, oob=True),
        )

    @app.post("/init-wizard/complete")
    async def wizard_complete(request):
        """完成初始化（原子提交）。

        流程：

        1. 把最后一步的表单数据合并进 ``_wizard_data``；
        2. **快照**当前 settings / user / asset，以便回滚；
        3. **先检查 QMT 进程是否在运行**——若不在运行，跳过连接测试直接走 auto-retry；
        4. 若 QMT 已运行，用新值测试 xtquant 连接——失败则校验路径后重启 QMT；
        5. 测试通过后再**一次性**把 user / settings / asset 写回 DB；
        6. 标记 ``init_completed=True``、刷新内存配置并跳转首页。
        """
        global _wizard_data
        snapshot: dict = {}

        try:
            # 1. 合并表单数据
            form_data = await request.form()
            form_dict = {k: v for k, v in form_data.items()}
            logger.info(f"wizard_complete 接收表单: {form_dict}")
            _wizard_data.update(form_dict)
            # HTML checkbox 未勾选时不提交，需要显式重置残留值
            if "auto_start_qmt" not in form_dict:
                _wizard_data["auto_start_qmt"] = ""
            logger.info(f"wizard_complete 合并后 _wizard_data: qmt_path={_wizard_data.get('qmt_path')!r}, "
                        f"xtquant_path={_wizard_data.get('xtquant_path')!r}, "
                        f"qmt_account_id={_wizard_data.get('qmt_account_id')!r}")

            username = _wizard_data.get("username", "admin")
            password = _wizard_data.get("password", "")

            if not username.strip() or not password.strip():
                return HTMLResponse(
                    "管理员账号或密码不能为空，请返回第 2 步重新输入。",
                    status_code=400,
                )

            # 1b. 提前校验 QMT/xtquant 路径（#63），避免无效输入触发自动重启
            preview_settings = _build_settings_from_wizard_data(_wizard_data)
            # xtquant_path 必须显式填写——必须明确指定，不能从 QMT 目录推断
            # （qmt_path 仅用作 DLL 搜索目录，不进 sys.path）
            if not (preview_settings.xtquant_path or "").strip():
                return _render_fragment(
                    _build_wizard_failure_fragment(
                        original_error="xtquant 路径未填写",
                        recovery_reason="未指定 xtquant 路径",
                        recovery_hint=(
                            "请填写 xtquant SDK 的根目录（如 C:\\apps\\xtquant）。"
                            "系统会校验该目录下能否找到 xtquant 包"
                            "（xtquant\\__init__.py）或 xtquant.py 模块。"
                            "这一项必须显式指定——qmt 路径下推断不到 xtquant。"
                        ),
                    )
                )
            path_probe = probe_qmt_path(preview_settings.qmt_path)
            if not path_probe["valid"]:
                return _render_fragment(
                    _build_wizard_failure_fragment(
                        original_error=path_probe.get("reason", "QMT 路径无效"),
                        recovery_reason=path_probe.get("reason"),
                        recovery_hint=(
                            "请检查 QMT 路径是否正确：可填 XtMiniQmt.exe 所在 bin.x64 目录、"
                            "其上级目录，或 QMT 根目录。"
                        ),
                    )
                )

            # 2. 快照（必须在做任何写操作前完成）
            snapshot = _snapshot_wizard_state(username=username)

            # 3. 构造新 settings（在内存中，不落库）
            new_settings = _build_settings_from_wizard_data(_wizard_data)
            qmt_password = _wizard_data.get("qmt_password", "")

            # 4. 无 QMT 密码时跳过连接检查和自动启动，直接落库
            if not qmt_password or not qmt_password.strip():
                logger.info("未提供 QMT 交易密码，跳过连接检查和自动启动，直接完成初始化")
                _commit_wizard_settings(_wizard_data, new_settings)
                logger.info("初始化完成（无密码模式，跳过连接检查）")
                return _redirect_after_hx(request)

            # 4b. 有密码但未启用自动启动时，只保存密码不执行自动重启/重连
            auto_start_qmt = _wizard_data.get("auto_start_qmt") == "on"
            if not auto_start_qmt:
                logger.info("已提供 QMT 交易密码但未启用自动启动，跳过自动重启/重连")
                _commit_wizard_settings(_wizard_data, new_settings)
                logger.info("初始化完成（密码已保存，未执行自动重启）")
                return _redirect_after_hx(request)

            # 5. 有密码时，先尝试连接测试；若 QMT 未运行则尝试自动启动
            from qmt_gateway.qmt_init_helpers import is_qmt_process_running
            force_restart = False
            if is_qmt_process_running():
                # QMT 已在运行，直接测试 xtquant 连接
                logger.info("QMT 进程已存在，测试 xtquant 连接...")
                test_result = test_xtquant_connection(
                    xtquant_path=new_settings.xtquant_path or None,
                    qmt_path=new_settings.qmt_path or None,
                )
                if test_result["success"]:
                    # 连接成功，直接落库
                    _commit_wizard_settings(_wizard_data, new_settings)
                    logger.info("初始化完成（QMT 已运行且连接成功）")
                    return _redirect_after_hx(request)
                logger.warning("QMT 进程仍在运行但未完成登录，准备强制重启后重试")
                force_restart = True

            # QMT 未运行或连接失败，尝试自动启动 QMT
            logger.info("QMT 未运行或连接失败，尝试自动启动 QMT...")
            restart_result = _wizard_restart_qmt(
                qmt_path=new_settings.qmt_path,
                account_id=new_settings.qmt_account_id,
                qmt_password=qmt_password,
                kill_first=force_restart,
            )
            if restart_result.get("success"):
                # 启动成功后验证 xtdata 连接
                retest = test_xtquant_connection(
                    xtquant_path=new_settings.xtquant_path or None,
                    qmt_path=new_settings.qmt_path or None,
                )
                if retest["success"]:
                    _commit_wizard_settings(_wizard_data, new_settings)
                    logger.info("初始化完成（自动启动 QMT 后连接成功）")
                    return _redirect_after_hx(request)
                # xtdata 还没就绪，展示等待对话框让 auto-retry 继续验证
                return _render_fragment(
                    _build_wizard_wait_dialog(
                        message="QMT 已启动，正在等待 xtdata 连接就绪...",
                        error=retest.get("error", "xtdata 连接失败"),
                        auto_retry=True,
                    )
                )

            # 启动失败（路径不合法等），展示等待对话框让用户重试
            path_probe = probe_qmt_path(new_settings.qmt_path)
            if not path_probe["valid"]:
                _rollback_wizard_state(snapshot)
                logger.warning(f"QMT 路径不合法: {path_probe.get('reason')}")
                return _render_fragment(
                    _build_wizard_failure_fragment(
                        original_error=restart_result.get("error", "未知错误"),
                        recovery_reason=path_probe.get("reason"),
                        recovery_hint="请检查 QMT 路径是否正确。",
                    )
                )

            return _render_fragment(
                _build_wizard_wait_dialog(
                    message="正在重试连接...",
                    error=restart_result.get("error", "QMT 启动失败"),
                    auto_retry=True,
                )
            )

        except Exception as e:
            logger.error(f"完成初始化失败: {e}")
            try:
                _rollback_wizard_state(snapshot)
            except Exception:
                pass
            return Div(f"初始化失败: {e}", cls="text-red-500")

    @app.post("/init-wizard/retry-startup")
    async def wizard_retry_startup():
        """重试：杀旧进程 → 后台重启 QMT → 异步等待连接 → 验证 xtdata。

        注意（非阻塞设计）：
        - 杀掉残留 QMT 进程（快速同步）后，启动后台线程执行完整重启流程
        - **立即返回**等待对话框，不阻塞事件循环
        - auto-retry 会反复调用本端点，直到后台任务完成
        - 后台任务完成后检查结果：成功则验证 xtdata → 触发 complete；
          失败则继续展示 auto_retry 对话框
        """
        global _wizard_data, _restart_status

        qmt_password = _wizard_data.get("qmt_password", "")
        logger.info("[retry-startup] 收到重试请求, password={}", '***' if qmt_password else '(empty)')

        try:
            new_settings = _build_settings_from_wizard_data(_wizard_data)
            logger.info("[retry-startup] qmt_path={}, account_id={}",
                        new_settings.qmt_path, new_settings.qmt_account_id)

            # 先立即杀掉可能残留的 QMT 进程（这一小段很快，同步执行）
            from qmt_gateway.services.trade_service import trade_service
            try:
                executable = trade_service._resolve_qmt_client_path(new_settings.qmt_path)
                trade_service._kill_qmt_process(executable.name)
                logger.info("[retry-startup] 已主动终止 QMT 进程")
            except Exception:
                logger.info("[retry-startup] 未发现残留 QMT 进程，跳过终止")

            # =================================================================
            # 异步重启：根据 _restart_status 决定下一步动作
            #   None        → 尚未启动后台任务（首次或已消费完成）
            #   {}          → 后台任务正在执行中
            #   {"success"} → 后台任务已完成
            # =================================================================

            # 情况 A：后台任务还在执行
            if _restart_status is not None and not _restart_status:
                logger.info("[retry-startup] 后台重启仍在进行中，继续等待")
                return _render_fragment(
                    _build_wizard_wait_dialog(
                        message="QMT 正在重启中，请稍候...",
                        auto_retry=True,
                    )
                )

            # 情况 B：后台任务已完成，处理结果
            if _restart_status is not None and _restart_status:
                result = dict(_restart_status)
                _restart_status = None
                logger.info("[retry-startup] 后台重启已完成: {}", result)

                if result.get("success"):
                    logger.info("[retry-startup] restart_qmt 成功，直接完成初始化")
                    return _render_fragment(
                        _build_wizard_wait_dialog(
                            message="QMT 连接成功，正在完成初始化...",
                            auto_complete=True,
                        )
                    )

                # 重启失败
                return _render_fragment(
                    _build_wizard_wait_dialog(
                        message="正在重试连接...",
                        error=result.get("error", "连接失败"),
                        auto_retry=True,
                    )
                )

            # 情况 C：没有后台任务 → 启动一个（在线程池中执行，不阻塞事件循环）
            logger.info("[retry-startup] 启动后台重启任务...")
            _restart_status = {}

            async def _watch_restart():
                global _restart_status
                try:
                    result = await asyncio.to_thread(
                        _wizard_restart_qmt,
                        qmt_path=new_settings.qmt_path,
                        account_id=new_settings.qmt_account_id,
                        qmt_password=qmt_password,
                        kill_first=True,
                    )
                    _restart_status = result
                    logger.info("[retry-startup] 后台重启任务完成: {}", result)
                except Exception as exc:
                    _restart_status = {"success": False, "error": str(exc)}
                    logger.error("[retry-startup] 后台重启任务异常: {}", exc)

            asyncio.create_task(_watch_restart())

            return _render_fragment(
                _build_wizard_wait_dialog(
                    message="正在重启 QMT...",
                    auto_retry=True,
                )
            )

        except Exception as e:
            logger.error("[retry-startup] 异常: {}", e)
            return _render_fragment(
                _build_wizard_wait_dialog(
                    message="正在重试连接...",
                    error=str(e),
                    auto_retry=True,
                )
            )

    def _wizard_restart_qmt(
        *, qmt_path: str, account_id: str, qmt_password: str, kill_first: bool = False
    ) -> dict:
        """统一调用 TradeService.async_restart_and_login（init-wizard 与主界面共用入口）。

        init-wizard 场景：QMT 没在运行时启动它，已在运行时不做任何操作。
        kill_first=True 时先杀掉已有进程再重启（用于重试场景）。
        """
        from qmt_gateway.services.trade_service import trade_service
        from qmt_gateway.qmt_init_helpers import is_qmt_process_running

        if not qmt_password or not qmt_password.strip():
            return {"success": False, "error": "未提供 QMT 交易密码，无法自动启动"}

        if is_qmt_process_running() and not kill_first:
            logger.info("[wizard] QMT 已在运行，跳过启动")
            trade_service._qmt_path = qmt_path
            trade_service._account_id = account_id
            return {"success": True}

        return trade_service.restart_and_login(
            qmt_path=qmt_path,
            account_id=account_id,
            qmt_password=qmt_password,
            kill_first=kill_first,
            verify_connection=False,
        )

    def _build_wizard_failure_fragment(
        *,
        original_error: str,
        recovery_reason: str | None,
        recovery_hint: str | None,
    ):
        """构造 xtquant 连接失败时的错误反馈。

        返回一个 tuple：
        - 主内容：InitWizardForm(step=5)，保持向导上下文可见
        - OOB 1：更新 #wizard-progress-content 为错误信息 + 重试/返回按钮
        - OOB 2：清除 #wizard-error 旧错误信息

        对话框（#wizard-progress-modal）会保持可见，
        用户可在对话框内点击"重试"或"返回修改"。
        """
        messages: list[Any] = [
            Div(
                Span("✗", cls="text-4xl text-red-500"),
                cls="mb-4",
            ),
            P("QMT 连接失败", cls="text-lg font-bold text-red-600 mb-3"),
            P(
                f"{original_error}",
                cls="text-gray-700 mb-3 text-sm leading-relaxed",
            ),
        ]
        if recovery_reason:
            messages.append(
                P(
                    f"自动恢复: {recovery_reason}",
                    cls="text-gray-700 mb-2 text-sm",
                )
            )
        if recovery_hint:
            messages.append(
                P(recovery_hint, cls="text-gray-500 text-xs mb-6"),
            )
        else:
            messages.append(
                P(
                    "已自动回滚，本次提交未生效。",
                    cls="text-gray-500 text-xs mb-6",
                )
            )

        messages.append(
            P("已等待 0 秒", cls="text-sm text-gray-400 mb-4", id="wizard-elapsed")
        )

        messages.append(
            Div(
                Div(id="wizard-retry-loading", cls="htmx-indicator text-sm text-gray-500 mb-2",
                    children="正在操作，请稍候..."),
                Button(
                    "重试启动 QMT",
                    cls="btn px-8 py-2",
                    id="wizard-retry-btn",
                    style=f"background: {PRIMARY_COLOR}; color: white; border: none;",
                    hx_post="/init-wizard/retry-startup",
                    hx_target="#wizard-form-container",
                    hx_indicator="#wizard-retry-loading",
                ),
                Button(
                    "返回修改配置",
                    cls="btn btn-ghost px-8 py-2",
                    hx_post="/init-wizard/step/5",
                    hx_target="#wizard-form-container",
                ),
                cls="flex justify-center gap-3 mt-4",
            )
        )
        return (
            InitWizardForm(step=5, form_data=_wizard_data),
            Div(
                *messages,
                id="wizard-progress-content",
                hx_swap_oob="true",
                cls="text-center py-8 px-8",
            ),
            Div(id="wizard-error", hx_swap_oob="true"),
            _WizardProgressModal(visible=True, oob=True),
        )

    def _build_wizard_wait_dialog(
        *,
        message: str = "",
        error: str = "",
        auto_retry: bool = False,
        auto_complete: bool = False,
    ):
        """构造 QMT 启动等待/重试对话框（OOB 更新 #wizard-progress-content）。

        Args:
            message: 显示给用户的等待消息。
            error: 如果有错误，显示错误信息。
            auto_retry: 自动触发 POST /init-wizard/retry-startup（重启 QMT）。
            auto_complete: 自动触发 POST /init-wizard/complete（提交设置并跳转）。

        Returns:
            一个 tuple：(InitWizardForm(step=5), OOB progress-content, OOB wizard-error)。
        """
        inner_parts: list[Any] = []
        auto_delay = 1  # seconds
        auto_target = "/init-wizard/retry-startup"

        if auto_complete:
            # 连接成功 → 显示成功消息，自动触发 complete
            inner_parts.extend([
                Div(Span("✓", cls="text-4xl text-green-500"), cls="mb-4"),
                P(
                    message or "QMT 连接成功，正在完成初始化...",
                    cls="text-base text-green-700 font-semibold mb-2",
                ),
            ])
            auto_target = "/init-wizard/complete"
            auto_delay = 1
        elif error:
            inner_parts.extend([
                Div(Span("⚠", cls="text-4xl text-orange-500"), cls="mb-4"),
                P("QMT 启动失败，正在重试...", cls="text-lg font-bold text-orange-600 mb-3"),
                P(error, cls="text-gray-700 mb-3 text-sm leading-relaxed"),
            ])
        else:
            inner_parts.extend([
                Div(
                    Span(cls="loading loading-spinner loading-lg text-primary"),
                    cls="mb-4",
                ),
                P(
                    message or "检测到 QMT 未运行，正在尝试自动启动...",
                    cls="text-base text-gray-700 mb-2",
                ),
                P("请稍候，可能需要几秒到几十秒", cls="text-gray-500 text-sm mb-2"),
            ])

        # 已等待时间（JS 计时器会持续更新）
        inner_parts.append(
            P("已等待 0 秒", cls="text-sm text-gray-400 mb-4", id="wizard-elapsed")
        )

        # 按钮区域
        inner_parts.append(
            Div(
                Div(id="wizard-retry-loading", cls="htmx-indicator text-sm text-gray-500 mb-2",
                    children="正在操作，请稍候..."),
                Button(
                    "重试",
                    cls="btn px-8 py-2",
                    id="wizard-retry-btn",
                    disabled="disabled",
                    style="background: #d1d5db; color: white; border: none; cursor: not-allowed;",
                    hx_post="/init-wizard/retry-startup",
                    hx_target="#wizard-form-container",
                    hx_indicator="#wizard-retry-loading",
                ),
                Button(
                    "返回修改配置",
                    cls="btn btn-ghost px-8 py-2",
                    hx_get="/init-wizard/step/5",
                    hx_target="#wizard-form-container",
                ),
                cls="flex justify-center gap-3 mt-4",
            )
        )

        # 自动触发：用 inline 脚本直接调 htmx.ajax，绕过"hidden 按钮 + click 触发"
        # 的老路径（HTMX 在 display:none 元素上不挂 hx-* 事件，老路径下 auto-retry
        # 永远不触发，进度对话框会卡死）。
        if auto_retry or auto_complete:
            inner_parts.append(
                NotStr(
                    f'<script>'
                    f'(function(){{'
                    f'  var fired=window.__wizardAutoRetryFired;'
                    f'  if(fired)return;'
                    f'  window.__wizardAutoRetryFired=true;'
                    f'  setTimeout(function(){{'
                    f'    if(window.htmx){{'
                    f'      htmx.ajax("POST", "{auto_target}", '
                    f'        {{target:"#wizard-form-container", swap:"outerHTML"}})'
                    f'    }}'
                    f'  }},{auto_delay * 1000});'
                    f'}})();'
                    f'</script>'
                )
            )

        return (
            InitWizardForm(step=5, form_data=_wizard_data),
            Div(
                *inner_parts,
                id="wizard-progress-content",
                hx_swap_oob="true",
                cls="text-center py-8 px-8",
            ),
            Div(id="wizard-error", hx_swap_oob="true"),
            _WizardProgressModal(visible=True, oob=True),
        )

    def test_xtquant_connection(xtquant_path: str | None = None, qmt_path: str | None = None):
        """测试 xtquant 和 QMT 连接（不做 QMT 自愈）。

        Args:
            xtquant_path: 显式传入时使用传入值；为 None 时回退到 DB 当前 settings。
            qmt_path: 同上。
        """
        try:
            from qmt_gateway.core import require_xtdata

            if xtquant_path is None or qmt_path is None:
                settings = db.get_settings()
                xtquant_path = xtquant_path or (
                    settings.xtquant_path if settings.xtquant_path else None
                )
                qmt_path = qmt_path or (
                    settings.qmt_path if settings.qmt_path else None
                )

            xtdata = require_xtdata(
                xtquant_path=xtquant_path,
                qmt_path=qmt_path,
            )

            markets = xtdata.get_stock_list_in_sector("沪深A股")
            if markets and len(markets) > 0:
                logger.info(f"xtquant 连接测试成功，获取到 {len(markets)} 只股票")
                return {"success": True, "message": f"连接成功，共 {len(markets)} 只股票"}
            else:
                return {"success": False, "error": "无法获取股票列表，请检查 QMT 是否已登录"}

        except Exception as e:
            logger.error(f"xtquant 连接测试失败: {e}")
            return {"success": False, "error": str(e)}

    def probe_qmt_path(qmt_path: str | None) -> dict:
        """校验 qmt_path 能否解析为合法的 QMT 客户端可执行文件。

        Returns:
            ``{"valid": True, "executable": <Path>, "qmt_path": <Path>}``
            或 ``{"valid": False, "reason": <str>}``。
        """
        from qmt_gateway.qmt_init_helpers import resolve_qmt_executable

        try:
            executable = resolve_qmt_executable(qmt_path)
        except FileNotFoundError as exc:
            return {"valid": False, "reason": str(exc)}
        except ValueError as exc:
            return {"valid": False, "reason": str(exc)}
        except Exception as exc:  # 兜底
            return {"valid": False, "reason": f"校验 QMT 路径时发生异常: {exc}"}
        return {
            "valid": True,
            "executable": executable,
            "qmt_path": Path(executable).parent.parent,
        }

    # 主页面路由
    @app.get("/")
    def index(request):
        """首页"""
        if check_init_required():
            return RedirectResponse("/init-wizard", status_code=302)

        # 获取当前用户
        user = request.scope.get("session", {}).get("user")
        if not user:
            return RedirectResponse("/login", status_code=302)

        # 获取交易数据
        from qmt_gateway.apis.trade import (
            get_latest_asset_data,
            get_latest_positions_data,
            trade_service,
        )
        asset = get_latest_asset_data()
        positions = get_latest_positions_data()
        orders = trade_service.get_orders()
        trades = trade_service.get_trades()

        return _render_page(
            TradingPage(
                asset=asset,
                positions=positions,
                orders=orders,
                trades=trades,
                user=user,
            )
        )

    @app.get("/trading")
    def trading_page(request):
        """实盘交易页面"""
        if check_init_required():
            return RedirectResponse("/init-wizard", status_code=302)

        user = request.scope.get("session", {}).get("user")
        if not user:
            return RedirectResponse("/login", status_code=302)

        from qmt_gateway.apis.trade import (
            get_latest_asset_data,
            get_latest_positions_data,
            trade_service,
        )
        asset = get_latest_asset_data()
        positions = get_latest_positions_data()
        orders = trade_service.get_orders()
        trades = trade_service.get_trades()

        return _render_page(
            TradingPage(
                asset=asset,
                positions=positions,
                orders=orders,
                trades=trades,
                user=user,
            )
        )

    @app.get("/data")
    def data_page(request, sector_type: str = ""):
        """数据管理页面"""
        if check_init_required():
            return RedirectResponse("/init-wizard", status_code=302)

        user = request.scope.get("session", {}).get("user")
        if not user:
            return RedirectResponse("/login", status_code=302)

        return _render_page(
            DataMgmtPage(
                selected_type=sector_type,
                sectors=[],
                user=user,
            )
        )

    @app.get("/logs")
    def logs_page(request, level: str = "INFO", keyword: str = ""):
        """运行日志页面。"""
        if check_init_required():
            return RedirectResponse("/init-wizard", status_code=302)

        user = request.scope.get("session", {}).get("user")
        if not user:
            return RedirectResponse("/login", status_code=302)

        return _render_page(
            LogsPage(
                user=user,
                level=level,
                keyword=keyword,
            )
        )

    @app.get("/logs/stream")
    async def logs_stream(request, level: str = "INFO", keyword: str = ""):
        """SSE 端点：实时推送日志更新。

        Args:
            request: HTTP 请求
            level: 日志级别过滤
            keyword: 关键词过滤
        """
        if check_init_required():
            return StreamingResponse(iter([]), media_type="text/event-stream")

        user = request.scope.get("session", {}).get("user")
        if not user:
            return StreamingResponse(iter([]), media_type="text/event-stream")

        from qmt_gateway.services.log_viewer import LogEventSource

        es = LogEventSource(level=level, keyword=keyword, poll_interval=1.0, maxlen=300)
        init_result = es.init_from_file()

        def _encode_sse(event: str, data: str) -> bytes:
            """编码 SSE 事件，支持多行 data。"""
            data_lines = data.splitlines() or [""]
            payload = [f"event: {event}"]
            payload.extend(f"data: {line}" for line in data_lines)
            payload.append("")
            payload.append("")
            return "\n".join(payload).encode("utf-8")

        async def event_generator():
            yield _encode_sse("file-info", str(init_result.file_path))
            if init_result.lines:
                yield _encode_sse("init", "\n".join(init_result.lines))
            while True:
                await asyncio.sleep(es.poll_interval)
                new_lines = es.poll_new_lines()
                for line in new_lines:
                    yield _encode_sse("new-log", line)
                total = es.total_matches
                filter_desc = es.current_filter_desc
                info_parts = [f"共匹配 {total} 行"]
                if filter_desc:
                    info_parts.append(filter_desc)
                yield _encode_sse("status", " | ".join(info_parts))

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/logs/stream/{level}")
    async def logs_stream_compat(request, level: str):
        """兼容旧版 SSE 地址。"""
        return await logs_stream(request, level=level, keyword="")

    @app.get("/logs/stream/{level}/{keyword:path}")
    async def logs_stream_compat_keyword(request, level: str, keyword: str = ""):
        """兼容旧版 SSE 地址，支持关键词路径参数。"""
        return await logs_stream(request, level=level, keyword=keyword)

    # 启动服务
    @app.on_event("startup")
    async def startup():
        """应用启动时执行"""
        if not check_init_required():
            # 启动定时任务
            scheduler.start()
            # 启动行情服务（同步订阅 + 异步 worker）
            quote_ws.start()
            # 集合竞价独立 endpoint：订阅 quote_service 的原始 tick
            auction_ws.start()
            # 在事件循环中显式 await 一次 worker 启动，避免 schedule 漂移
            await quote_ws.start_async()
            await auction_ws.start_async()
            logger.info("应用启动完成")

    @app.on_event("shutdown")
    async def shutdown():
        """应用关闭时执行"""
        scheduler.stop()
        quote_ws.stop()
        auction_ws.stop()
        logger.info("应用已关闭")

    return app


app = create_app()

