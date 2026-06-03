"""主布局模块

提供带 header 的主页面布局（无 sidebar，符合文档要求）。
"""

from fasthtml.common import *
from monsterui.all import *

from qmt_gateway.web.theme import AppTheme, PRIMARY_COLOR


CONNECTION_ICON_DATA_URI = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxZW0iIGhlaWdodD0iMWVtIiB2aWV3Qm94PSIwIDAgMjQgMjQiPgoJPHBhdGggZD0iTTAgMGgyNHYyNEgweiIgZmlsbD0ibm9uZSIgLz4KCTxwYXRoIGZpbGw9Im5vbmUiIHN0cm9rZT0iY3VycmVudENvbG9yIiBzdHJva2UtZGFzaGFycmF5PSIyOCIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIiBzdHJva2Utd2lkdGg9IjIiIGQ9Ik0xMyA2bDIgLTJjMSAtMSAzIC0xIDQgMGwxIDFjMSAxIDEgMyAwIDRsLTUgNWMtMSAxIC0zIDEgLTQgME0xMSAxOGwtMiAyYy0xIDEgLTMgMSAtNCAwbC0xIC0xYy0xIC0xIC0xIC0zIDAgLTRsNSAtNWMxIC0xIDMgLTEgNCAwIj4KCQk8YW5pbWF0ZSBmaWxsPSJmcmVlemUiIGF0dHJpYnV0ZU5hbWU9InN0cm9rZS1kYXNob2Zmc2V0IiBkdXI9IjAuNnMiIHZhbHVlcz0iMjg7MCIgLz4KCTwvcGF0aD4KPC9zdmc+Cg=="
)

CONNECTION_ICON_STYLE = (
    "display:inline-block;"
    "width:1.1rem;"
    "height:1.1rem;"
    "background-color:#dc2626;"
    f"mask:url('{CONNECTION_ICON_DATA_URI}') center / contain no-repeat;"
    f"-webkit-mask:url('{CONNECTION_ICON_DATA_URI}') center / contain no-repeat;"
)


def _nav_link(label: str, href: str, is_active: bool = False):
    """渲染顶部导航链接。"""
    base_cls = (
        "rounded-lg px-3 py-2 text-sm font-medium transition-colors "
        "hover:bg-gray-100"
    )
    if is_active:
        return A(
            label,
            href=href,
            cls=f"{base_cls} bg-blue-50 text-blue-600",
        )

    return A(
        label,
        href=href,
        cls=f"{base_cls} text-gray-600 hover:text-gray-900",
    )


def Header(user: dict | None = None, active_menu: str = ""):
    """顶部导航栏（无 alarm，符合文档要求）

    Args:
        user: 当前用户信息
        active_menu: 当前激活的导航项
    """
    user_menu = Div(
        Div(
            Div(
                user.get("username", "User")[0].upper() if user else "U",
                cls="w-8 h-8 rounded-full bg-gray-300 flex items-center justify-center text-sm font-bold cursor-pointer hover:bg-gray-400",
                tabindex="0",
            ),
            cls="dropdown dropdown-end",
        ),
        Ul(
            Li(A("修改本金", href="#", onclick="showPrincipalModal(); return false;")),
            Li(A("修改密码", href="#", onclick="showChangePasswordModal(); return false;")),
            Li(A("管理 API key", href="#", onclick="showApiKeyModal(); return false;")),
            Li(A("退出登录", href="/auth/logout")),
            cls=(
                "dropdown-content menu p-2 shadow bg-base-100 "
                "rounded-box w-52 mt-4 z-50"
            ),
        ),
        cls="dropdown dropdown-end",
    ) if user else Div()

    status_controls = Div(
        Button(
            Span("", id="trade-connection-indicator", style=CONNECTION_ICON_STYLE),
            type="button",
            id="trade-connection-status",
            title="交易接口连接断开，点击后重启 QMT",
            onclick="window.handleTradeConnectionAction(); return false;",
            cls="btn btn-ghost btn-sm h-9 w-9 min-h-0 p-0",
        ),
        Button(
            Span("🔔", cls="text-lg leading-none text-gray-600"),
            Span(
                "0",
                id="alarm-unread-count",
                cls=(
                    "absolute -right-1 -top-1 hidden min-w-[1.2rem] rounded-full "
                    "bg-red-600 px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white"
                ),
            ),
            type="button",
            title="未读消息",
            cls="btn btn-ghost btn-sm relative h-9 w-9 min-h-0 p-0",
            onclick="window.openNotificationCenter(); return false;",
        ),
        cls="flex items-center gap-1",
    ) if user else Div()

    return Div(
        Div(
            Div(
                # Logo 和 Brand
                Div(
                    Span("QMT", cls="text-xl font-bold", style=f"color: {PRIMARY_COLOR};"),
                    Span("Gateway", cls="text-xl font-light text-gray-600 ml-1"),
                    cls="flex items-center",
                ),
                Div(
                    status_controls,
                    _nav_link("交易", "/", is_active=active_menu == "trading"),
                    _nav_link("日志", "/logs", is_active=active_menu == "logs"),
                    user_menu,
                    cls="flex items-center gap-2",
                ),
                cls="flex justify-between items-center px-6 py-3",
            ),
            cls="w-full max-w-[1200px] mx-auto",
        ),
        cls="w-full bg-white shadow-sm",
    )


def NotificationCenterModal():
    return Div(
        Div(
            Div(
                H3("未读消息", cls="text-lg font-bold"),
                Button(
                    "✕",
                    type="button",
                    cls="btn btn-sm btn-circle btn-ghost",
                    onclick="closeNotificationCenter()",
                ),
                cls="mb-4 flex items-center justify-between",
            ),
            Div(id="notification-center-list", cls="flex flex-col gap-3"),
            Div(
                Button(
                    "上一页",
                    type="button",
                    id="notification-center-prev",
                    cls="btn btn-ghost btn-sm",
                    onclick="changeNotificationPage(-1)",
                ),
                Span("第 1 / 1 页", id="notification-center-page-info", cls="text-sm text-gray-500"),
                Button(
                    "下一页",
                    type="button",
                    id="notification-center-next",
                    cls="btn btn-ghost btn-sm",
                    onclick="changeNotificationPage(1)",
                ),
                cls="mt-5 flex items-center justify-between",
            ),
            cls="modal-box max-w-2xl",
        ),
        id="notification-center-modal",
        cls="modal",
    )


def RestartQmtModal():
    return Div(
        Div(
            Div(
                H3("重启 QMT 交易端", cls="text-lg font-bold"),
                Button(
                    "✕",
                    type="button",
                    cls="btn btn-sm btn-circle btn-ghost",
                    onclick="closeRestartQmtModal()",
                ),
                cls="mb-4 flex items-center justify-between",
            ),
            P(
                "使用已存储的交易密码自动登录 QMT 客户端。",
                cls="mb-3 text-sm leading-6 text-gray-600",
            ),
            Div(
                P(
                    "警告：如果 QMT 正在运行，将不得不强行终止其进程，这可能导致不期望的结果。",
                    cls="text-sm leading-6 text-amber-700",
                ),
                cls="mb-4 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3",
            ),
            # 密码输入区域（当没有存储密码时显示）
            Div(
                Label("QMT 交易密码", cls="block text-sm font-medium text-gray-700 mb-1"),
                Input(
                    type="password",
                    id="restart-qmt-password",
                    name="password",
                    placeholder="请输入 QMT 交易密码",
                    cls="input input-bordered w-full",
                ),
                P(
                    "未检测到已存储的密码，请手动输入。",
                    cls="text-xs text-gray-500 mt-1",
                ),
                id="restart-qmt-password-section",
                cls="mb-4 hidden",
            ),
            Div(id="restart-qmt-message", cls="hidden text-sm mb-4"),
            Div(
                Button(
                    "取消",
                    type="button",
                    cls="btn btn-ghost",
                    onclick="closeRestartQmtModal()",
                ),
                Button(
                    "确认重启",
                    type="button",
                    id="restart-qmt-submit",
                    cls="btn btn-primary",
                    onclick="submitRestartQmt()",
                ),
                cls="flex justify-end gap-2",
            ),
            cls="modal-box max-w-lg",
        ),
        id="restart-qmt-modal",
        cls="modal",
    )


def PrincipalModal():
    """修改本金 Modal"""
    return Div(
        Div(
            Div(
                H3("修改本金", cls="text-lg font-bold"),
                Button(
                    "✕",
                    cls="btn btn-sm btn-circle btn-ghost",
                    onclick="closePrincipalModal()",
                ),
                cls="flex justify-between items-center mb-4",
            ),
            Div(
                Label("新本金金额（元）", cls="label"),
                Input(
                    type="number",
                    id="principal-input",
                    placeholder="请输入本金金额",
                    cls="input input-bordered w-full",
                    step="0.01",
                ),
                cls="mb-4",
            ),
            Div(id="principal-message", cls="hidden text-sm mb-4"),
            Div(
                Button(
                    "取消",
                    cls="btn btn-ghost",
                    onclick="closePrincipalModal()",
                ),
                Button(
                    "确认修改",
                    cls="btn btn-primary",
                    onclick="updatePrincipal()",
                ),
                cls="flex justify-end gap-2",
            ),
            cls="modal-box",
        ),
        id="principal-modal",
        cls="modal",
    )


def PrincipalModalScript():
    """修改本金 Modal 的 JavaScript"""
    return Script("""
        // 显示修改本金 Modal
        function showPrincipalModal() {
            var modal = document.getElementById('principal-modal');
            if (modal) {
                modal.classList.add('modal-open');
            }
        }
        
        // 关闭修改本金 Modal
        function closePrincipalModal() {
            var modal = document.getElementById('principal-modal');
            if (modal) {
                modal.classList.remove('modal-open');
            }
            var input = document.getElementById('principal-input');
            if (input) {
                input.value = '';
            }
            var message = document.getElementById('principal-message');
            if (message) {
                message.className = 'hidden text-sm mb-4';
                message.textContent = '';
            }
        }
        
        // 更新本金
        async function updatePrincipal() {
            var input = document.getElementById('principal-input');
            var message = document.getElementById('principal-message');
            var principal = input ? parseFloat(input.value) : 0;

            function showMessage(text, ok) {
                if (!message) return;
                message.classList.remove('hidden');
                if (ok) {
                    message.className = 'text-sm mb-4 text-green-600 bg-green-50 px-3 py-2 rounded';
                } else {
                    message.className = 'text-sm mb-4 text-red-600 bg-red-50 px-3 py-2 rounded';
                }
                message.textContent = text;
            }
            
            if (!principal || principal <= 0) {
                showMessage('请输入有效的本金金额', false);
                return;
            }
            
            try {
                var response = await fetch('/api/asset/principal', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/x-www-form-urlencoded',
                    },
                    body: new URLSearchParams({
                        principal: principal.toString(),
                    }),
                });
                
                var result = await response.json();
                
                if (response.ok && result.code === 0) {
                    showMessage('本金修改成功', true);
                    closePrincipalModal();
                    window.location.href = '/trading?_t=' + Date.now();
                } else {
                    showMessage('本金修改失败: ' + (result.message || '未知错误'), false);
                }
            } catch (e) {
                console.error('Update principal error:', e);
                showMessage('本金修改失败: ' + e.message, false);
            }
        }
        
        // 点击 modal 背景关闭
        document.addEventListener('click', function(e) {
            var modal = document.getElementById('principal-modal');
            if (modal && e.target === modal) {
                closePrincipalModal();
            }
        });
    """)


def ChangePasswordModal():
    return Div(
        Div(
            Div(
                H3("修改密码", cls="text-lg font-bold"),
                Button(
                    "✕",
                    type="button",
                    cls="btn btn-sm btn-circle btn-ghost",
                    onclick="closeChangePasswordModal()",
                ),
                cls="mb-4 flex items-center justify-between",
            ),
            # Tab 导航
            Div(
                Button(
                    "登录密码",
                    type="button",
                    id="tab-login-password",
                    cls="tab tab-bordered tab-active",
                    onclick="switchPasswordTab('login')",
                ),
                Button(
                    "QMT 交易密码",
                    type="button",
                    id="tab-qmt-password",
                    cls="tab tab-bordered",
                    onclick="switchPasswordTab('qmt')",
                ),
                cls="tabs tabs-boxed mb-4",
            ),
            # 登录密码表单
            Div(
                id="login-password-form",
                children=[
                    P(
                        "修改登录密码后，当前会话将立即失效，需要重新登录。",
                        cls="mb-4 text-sm text-gray-600",
                    ),
                    Div(
                        Label("原密码", cls="label"),
                        Input(
                            type="password",
                            id="change-password-old",
                            placeholder="请输入当前密码",
                            cls="input input-bordered w-full",
                            autocomplete="current-password",
                        ),
                        cls="mb-3",
                    ),
                    Div(
                        Label("新密码", cls="label"),
                        Input(
                            type="password",
                            id="change-password-new",
                            placeholder="请输入新密码",
                            cls="input input-bordered w-full",
                            autocomplete="new-password",
                        ),
                        cls="mb-3",
                    ),
                    Div(
                        Label("再次输入新密码", cls="label"),
                        Input(
                            type="password",
                            id="change-password-confirm",
                            placeholder="请再次输入新密码",
                            cls="input input-bordered w-full",
                            autocomplete="new-password",
                        ),
                        cls="mb-3",
                    ),
                ],
            ),
            # QMT 交易密码表单
            Div(
                id="qmt-password-form",
                cls="hidden",
                children=[
                    P(
                        "修改 QMT 交易密码后，下次重启 QMT 时将自动使用新密码登录。",
                        cls="mb-4 text-sm text-gray-600",
                    ),
                    Div(
                        Label("登录密码", cls="label"),
                        Input(
                            type="password",
                            id="change-qmt-login-password",
                            placeholder="请输入登录密码以验证身份",
                            cls="input input-bordered w-full",
                            autocomplete="current-password",
                        ),
                        cls="mb-3",
                    ),
                    Div(
                        Label("新的 QMT 交易密码", cls="label"),
                        Input(
                            type="password",
                            id="change-qmt-new-password",
                            placeholder="请输入新的 QMT 交易密码",
                            cls="input input-bordered w-full",
                        ),
                        cls="mb-3",
                    ),
                    Div(
                        Label("再次输入新的 QMT 交易密码", cls="label"),
                        Input(
                            type="password",
                            id="change-qmt-confirm-password",
                            placeholder="请再次输入新的 QMT 交易密码",
                            cls="input input-bordered w-full",
                        ),
                        cls="mb-3",
                    ),
                ],
            ),
            Div(id="change-password-message", cls="hidden text-sm mb-4"),
            Div(
                Button(
                    "取消",
                    type="button",
                    cls="btn btn-ghost",
                    onclick="closeChangePasswordModal()",
                ),
                Button(
                    "保存",
                    type="button",
                    id="change-password-submit",
                    cls="btn btn-primary",
                    onclick="submitChangePassword()",
                ),
                cls="flex justify-end gap-2",
            ),
            cls="modal-box",
        ),
        id="change-password-modal",
        cls="modal",
    )


def ChangePasswordModalScript():
    return Script("""
        var currentPasswordTab = 'login';

        function switchPasswordTab(tab) {
            currentPasswordTab = tab;
            var loginTab = document.getElementById('tab-login-password');
            var qmtTab = document.getElementById('tab-qmt-password');
            var loginForm = document.getElementById('login-password-form');
            var qmtForm = document.getElementById('qmt-password-form');
            var message = document.getElementById('change-password-message');

            if (message) {
                message.className = 'hidden text-sm mb-4';
                message.textContent = '';
            }

            if (tab === 'login') {
                if (loginTab) loginTab.classList.add('tab-active');
                if (qmtTab) qmtTab.classList.remove('tab-active');
                if (loginForm) loginForm.classList.remove('hidden');
                if (qmtForm) qmtForm.classList.add('hidden');
            } else {
                if (loginTab) loginTab.classList.remove('tab-active');
                if (qmtTab) qmtTab.classList.add('tab-active');
                if (loginForm) loginForm.classList.add('hidden');
                if (qmtForm) qmtForm.classList.remove('hidden');
            }
        }

        function showChangePasswordModal() {
            var modal = document.getElementById('change-password-modal');
            if (!modal) return;
            ['change-password-old', 'change-password-new', 'change-password-confirm',
             'change-qmt-login-password', 'change-qmt-new-password', 'change-qmt-confirm-password'].forEach(function(id) {
                var el = document.getElementById(id);
                if (el) el.value = '';
            });
            var message = document.getElementById('change-password-message');
            if (message) {
                message.className = 'hidden text-sm mb-4';
                message.textContent = '';
            }
            var submit = document.getElementById('change-password-submit');
            if (submit) {
                submit.disabled = false;
                submit.textContent = '保存';
            }
            switchPasswordTab('login');
            modal.classList.add('modal-open');
        }

        function closeChangePasswordModal() {
            var modal = document.getElementById('change-password-modal');
            if (modal) modal.classList.remove('modal-open');
        }

        function showChangePasswordMessage(text, ok) {
            var message = document.getElementById('change-password-message');
            if (!message) return;
            message.textContent = String(text || '');
            message.className = ok
                ? 'mb-4 rounded-xl border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700'
                : 'mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700';
        }

        async function submitChangePassword() {
            var submit = document.getElementById('change-password-submit');

            if (currentPasswordTab === 'login') {
                await submitLoginPassword(submit);
            } else {
                await submitQmtPassword(submit);
            }
        }

        async function submitLoginPassword(submit) {
            var oldEl = document.getElementById('change-password-old');
            var newEl = document.getElementById('change-password-new');
            var confirmEl = document.getElementById('change-password-confirm');
            var oldPassword = oldEl ? oldEl.value : '';
            var newPassword = newEl ? newEl.value : '';
            var confirmPassword = confirmEl ? confirmEl.value : '';

            if (!oldPassword || !newPassword || !confirmPassword) {
                showChangePasswordMessage('请完整填写原密码、新密码和确认密码', false);
                return;
            }
            if (newPassword !== confirmPassword) {
                showChangePasswordMessage('两次输入的新密码不一致', false);
                return;
            }
            if (submit) {
                submit.disabled = true;
                submit.textContent = '保存中...';
            }
            try {
                var response = await fetch('/auth/password', {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    },
                    body: new URLSearchParams({
                        old_password: oldPassword,
                        new_password: newPassword,
                        new_password_confirm: confirmPassword,
                    }).toString(),
                });
                var result = await response.json().catch(function() { return {}; });
                if (response.ok && result.success) {
                    showChangePasswordMessage('密码已修改，正在跳转登录页...', true);
                    window.setTimeout(function() {
                        window.location.href = '/login';
                    }, 800);
                    return;
                }
                showChangePasswordMessage(result.message || '修改失败', false);
                if (submit) {
                    submit.disabled = false;
                    submit.textContent = '保存';
                }
            } catch (e) {
                showChangePasswordMessage('修改失败: ' + e.message, false);
                if (submit) {
                    submit.disabled = false;
                    submit.textContent = '保存';
                }
            }
        }

        async function submitQmtPassword(submit) {
            var loginPwEl = document.getElementById('change-qmt-login-password');
            var newPwEl = document.getElementById('change-qmt-new-password');
            var confirmPwEl = document.getElementById('change-qmt-confirm-password');
            var loginPassword = loginPwEl ? loginPwEl.value : '';
            var newPassword = newPwEl ? newPwEl.value : '';
            var confirmPassword = confirmPwEl ? confirmPwEl.value : '';

            if (!loginPassword || !newPassword || !confirmPassword) {
                showChangePasswordMessage('请完整填写登录密码和新的 QMT 交易密码', false);
                return;
            }
            if (newPassword !== confirmPassword) {
                showChangePasswordMessage('两次输入的 QMT 交易密码不一致', false);
                return;
            }
            if (submit) {
                submit.disabled = true;
                submit.textContent = '保存中...';
            }
            try {
                var response = await fetch('/auth/qmt-password', {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    },
                    body: new URLSearchParams({
                        login_password: loginPassword,
                        new_qmt_password: newPassword,
                        new_qmt_password_confirm: confirmPassword,
                    }).toString(),
                });
                var result = await response.json().catch(function() { return {}; });
                if (response.ok && result.success) {
                    showChangePasswordMessage('QMT 交易密码已保存', true);
                    window.setTimeout(function() {
                        closeChangePasswordModal();
                    }, 1200);
                    return;
                }
                showChangePasswordMessage(result.message || '保存失败', false);
                if (submit) {
                    submit.disabled = false;
                    submit.textContent = '保存';
                }
            } catch (e) {
                showChangePasswordMessage('保存失败: ' + e.message, false);
                if (submit) {
                    submit.disabled = false;
                    submit.textContent = '保存';
                }
            }
        }

        document.addEventListener('click', function(e) {
            var modal = document.getElementById('change-password-modal');
            if (modal && e.target === modal) {
                closeChangePasswordModal();
            }
        });
    """)


def ApiKeyModal():
    return Div(
        Div(
            Div(
                H3("API key 管理", cls="text-lg font-bold"),
                Button(
                    "✕",
                    type="button",
                    cls="btn btn-sm btn-circle btn-ghost",
                    onclick="closeApiKeyModal()",
                ),
                cls="mb-4 flex items-center justify-between",
            ),
            P(
                "生成新的 API key 用于程序化访问。",
                cls="mb-3 text-sm text-gray-600",
            ),
            Div(
                Button(
                    "生成新的 API key",
                    type="button",
                    id="api-key-generate",
                    cls="btn btn-primary btn-sm",
                    onclick="generateApiKey()",
                ),
                cls="mb-3",
            ),
            Div(
                Label("新生成的 key（仅显示一次，请立即复制并妥善保存）", cls="label"),
                Div(
                    Input(
                        type="text",
                        id="api-key-plaintext",
                        readonly="readonly",
                        placeholder="点击上方按钮生成",
                        cls="input input-bordered w-full font-mono text-sm",
                    ),
                    Button(
                        "复制并关闭",
                        type="button",
                        id="api-key-copy-close",
                        cls="btn btn-sm btn-primary",
                        onclick="copyAndCloseApiKey()",
                    ),
                    cls="flex gap-2",
                ),
                cls="mb-3",
            ),
            Div(id="api-key-message", cls="hidden text-sm mb-4"),
            Div(
                H4("已有的 key", cls="text-sm font-semibold mb-2 text-gray-700"),
                Div(id="api-key-list", cls="flex flex-col gap-2"),
                cls="mt-4",
            ),
            cls="modal-box max-w-2xl",
        ),
        id="api-key-modal",
        cls="modal",
    )


def ApiKeyModalScript():
    return Script("""
        function showApiKeyModal() {
            var modal = document.getElementById('api-key-modal');
            if (!modal) return;
            var plaintext = document.getElementById('api-key-plaintext');
            if (plaintext) plaintext.value = '';
            var message = document.getElementById('api-key-message');
            if (message) {
                message.className = 'hidden text-sm mb-4';
                message.textContent = '';
            }
            var submit = document.getElementById('api-key-generate');
            if (submit) {
                submit.disabled = false;
                submit.textContent = '生成新的 API key';
            }
            modal.classList.add('modal-open');
            refreshApiKeyList();
        }

        function closeApiKeyModal() {
            var modal = document.getElementById('api-key-modal');
            if (modal) modal.classList.remove('modal-open');
        }

        function showApiKeyMessage(text, ok) {
            var message = document.getElementById('api-key-message');
            if (!message) return;
            message.textContent = String(text || '');
            message.className = ok
                ? 'mb-4 rounded-xl border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700'
                : 'mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700';
        }

        async function refreshApiKeyList() {
            var list = document.getElementById('api-key-list');
            if (!list) return;
            list.innerHTML = '<div class="text-sm text-gray-400">加载中...</div>';
            try {
                var response = await fetch('/api/api-keys', {
                    headers: { 'Accept': 'application/json' },
                });
                var result = await response.json().catch(function() { return {}; });
                list.innerHTML = '';
                var data = Array.isArray(result.data) ? result.data : [];
                if (!data.length) {
                    list.innerHTML = '<div class="text-sm text-gray-400">尚未生成任何 API key</div>';
                    return;
                }
                data.forEach(function(item) {
                    var row = document.createElement('div');
                    row.className = 'flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white px-3 py-2';
                    row.dataset.keyId = String(item.id || '');
                    var left = document.createElement('div');
                    left.className = 'flex flex-col';
                    var name = document.createElement('span');
                    name.className = 'text-sm font-medium text-gray-800';
                    name.textContent = String(item.name || '(未命名)');
                    var meta = document.createElement('span');
                    meta.className = 'text-xs text-gray-500 font-mono';
                    var prefix = item.key_prefix || '';
                    var created = item.created_at || '';
                    meta.textContent = prefix + ' · ' + created;
                    left.appendChild(name);
                    left.appendChild(meta);
                    row.appendChild(left);
                    var btn = document.createElement('button');
                    btn.type = 'button';
                    btn.className = 'btn btn-xs btn-ghost text-red-600';
                    btn.textContent = '吊销';
                    btn.addEventListener('click', function() {
                        revokeApiKey(item.id, row);
                    });
                    row.appendChild(btn);
                    list.appendChild(row);
                });
            } catch (e) {
                list.innerHTML = '<div class="text-sm text-red-600">加载失败: ' + e.message + '</div>';
            }
        }

        async function generateApiKey() {
            var submit = document.getElementById('api-key-generate');
            if (submit) {
                submit.disabled = true;
                submit.textContent = '生成中...';
            }
            try {
                var response = await fetch('/api/api-keys', {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    },
                    body: '',
                });
                var result = await response.json().catch(function() { return {}; });
                if (response.ok && result.code === 0) {
                    var plaintext = document.getElementById('api-key-plaintext');
                    if (plaintext && result.data && result.data.plaintext) {
                        plaintext.value = String(result.data.plaintext);
                        plaintext.focus();
                        plaintext.select();
                    }
                    showApiKeyMessage('已生成新的 API key，请立即复制并妥善保存。它不会再次显示。', true);
                    refreshApiKeyList();
                } else {
                    showApiKeyMessage((result && result.message) || '生成失败', false);
                }
            } catch (e) {
                showApiKeyMessage('生成失败: ' + e.message, false);
            } finally {
                if (submit) {
                    submit.disabled = false;
                    submit.textContent = '生成新的 API key';
                }
            }
        }

        async function revokeApiKey(keyId, row) {
            if (!keyId) return;
            if (!window.confirm('确定要吊销该 API key 吗？吊销后无法恢复。')) {
                return;
            }
            try {
                var response = await fetch('/api/api-keys/' + encodeURIComponent(keyId), {
                    method: 'DELETE',
                    headers: { 'Accept': 'application/json' },
                });
                var result = await response.json().catch(function() { return {}; });
                if (response.ok && result.code === 0) {
                    if (row && row.parentNode) {
                        row.parentNode.removeChild(row);
                    }
                    if (list && list.children.length === 0) {
                        list.innerHTML = '<div class="text-sm text-gray-400">尚未生成任何 API key</div>';
                    }
                    showApiKeyMessage('已吊销', true);
                } else {
                    showApiKeyMessage((result && result.message) || '吊销失败', false);
                }
            } catch (e) {
                showApiKeyMessage('吊销失败: ' + e.message, false);
            }
        }

        async function copyAndCloseApiKey() {
            var plaintext = document.getElementById('api-key-plaintext');
            if (plaintext && plaintext.value) {
                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(plaintext.value);
                    } else {
                        plaintext.select();
                        document.execCommand('copy');
                    }
                } catch (e) {
                    console.warn('复制失败:', e);
                }
            }
            closeApiKeyModal();
        }

        document.addEventListener('click', function(e) {
            var modal = document.getElementById('api-key-modal');
            if (modal && e.target === modal) {
                closeApiKeyModal();
            }
        });
    """)


def HeaderStatusScript():
    return Script("""
        (function() {
            var notificationStorageKey = 'qmt-gateway-unread-notifications';
            var notificationPageSize = 10;
            var currentNotificationPage = 1;
            var connectionPollTimer = null;
            var restartRequestInFlight = false;
            var hasHydratedConnectionState = false;
            var tradeConnectionState = {
                connected: false,
                message: '交易接口连接断开',
            };

            function isSupportedNotificationCategory(category) {
                return category === 'connection' || category === 'trade';
            }

            function loadUnreadNotifications() {
                try {
                    var raw = window.localStorage.getItem(notificationStorageKey);
                    var items = raw ? JSON.parse(raw) : [];
                    if (!Array.isArray(items)) {
                        return [];
                    }
                    return items
                        .filter(function(item) {
                            return item && item.message && isSupportedNotificationCategory(item.category);
                        })
                        .sort(function(left, right) {
                            return String(right.createdAt || '').localeCompare(String(left.createdAt || ''));
                        });
                } catch (error) {
                    return [];
                }
            }

            function saveUnreadNotifications(items) {
                try {
                    window.localStorage.setItem(
                        notificationStorageKey,
                        JSON.stringify(Array.isArray(items) ? items.slice(0, 100) : [])
                    );
                } catch (error) {
                    return;
                }
            }

            function formatNotificationTime(value) {
                if (!value) {
                    return '--';
                }
                var date = new Date(value);
                if (Number.isNaN(date.getTime())) {
                    return String(value);
                }
                return date.toLocaleString('zh-CN', {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                    second: '2-digit',
                    hour12: false,
                });
            }

            function updateAlarmBadge() {
                var badge = document.getElementById('alarm-unread-count');
                if (!badge) {
                    return;
                }
                var unread = loadUnreadNotifications();
                if (!unread.length) {
                    badge.textContent = '0';
                    badge.classList.add('hidden');
                    return;
                }
                badge.textContent = unread.length > 99 ? '99+' : String(unread.length);
                badge.classList.remove('hidden');
            }

            function renderNotificationPage(page) {
                var list = document.getElementById('notification-center-list');
                var prevButton = document.getElementById('notification-center-prev');
                var nextButton = document.getElementById('notification-center-next');
                var pageInfo = document.getElementById('notification-center-page-info');
                if (!list || !prevButton || !nextButton || !pageInfo) {
                    return;
                }

                var unread = loadUnreadNotifications();
                var totalPages = Math.max(1, Math.ceil(unread.length / notificationPageSize));
                currentNotificationPage = Math.min(Math.max(page || 1, 1), totalPages);
                var start = (currentNotificationPage - 1) * notificationPageSize;
                var pageItems = unread.slice(start, start + notificationPageSize);

                list.innerHTML = '';
                if (!pageItems.length) {
                    var emptyState = document.createElement('div');
                    emptyState.className = 'rounded-xl border border-dashed border-gray-200 bg-gray-50 px-4 py-8 text-center text-sm text-gray-500';
                    emptyState.textContent = '暂无未读消息';
                    list.appendChild(emptyState);
                } else {
                    pageItems.forEach(function(item) {
                        var row = document.createElement('div');
                        row.className = 'rounded-xl border border-gray-200 bg-white px-4 py-3 shadow-sm';

                        var timeEl = document.createElement('div');
                        timeEl.className = 'mb-2 text-xs text-gray-400';
                        timeEl.textContent = formatNotificationTime(item.createdAt);

                        var messageEl = document.createElement('div');
                        messageEl.className = 'text-sm font-medium leading-6 text-gray-700';
                        messageEl.textContent = String(item.message || '');

                        row.appendChild(timeEl);
                        row.appendChild(messageEl);
                        list.appendChild(row);
                    });
                }

                pageInfo.textContent = '第 ' + String(currentNotificationPage) + ' / ' + String(totalPages) + ' 页';
                prevButton.disabled = currentNotificationPage <= 1;
                nextButton.disabled = currentNotificationPage >= totalPages;
            }

            function showRestartQmtMessage(text, ok) {
                var message = document.getElementById('restart-qmt-message');
                if (!message) {
                    return;
                }
                message.textContent = String(text || '');
                message.className = ok
                    ? 'mb-4 rounded-xl border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700'
                    : 'mb-4 rounded-xl border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700';
            }

            function resetRestartQmtForm() {
                var message = document.getElementById('restart-qmt-message');
                var submitButton = document.getElementById('restart-qmt-submit');
                var passwordInput = document.getElementById('restart-qmt-password');
                if (message) {
                    message.textContent = '';
                    message.className = 'hidden text-sm mb-4';
                }
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = '确认重启';
                }
                if (passwordInput) {
                    passwordInput.value = '';
                }
                restartRequestInFlight = false;
            }

            function updateConnectionIndicator(data) {
                var indicator = document.getElementById('trade-connection-indicator');
                var container = document.getElementById('trade-connection-status');
                if (!indicator || !container) {
                    return;
                }
                var connected = !!(data && data.connected);
                var message = data && data.message ? String(data.message) : (connected ? '交易接口已连接' : '交易接口未连接');
                var tooltip = connected ? message : (message + '，点击后重启 QMT');
                tradeConnectionState.connected = connected;
                tradeConnectionState.message = message;
                indicator.style.backgroundColor = connected ? '#16a34a' : '#dc2626';
                container.title = tooltip;
                container.setAttribute('aria-label', tooltip);
                container.dataset.connected = connected ? '1' : '0';
                container.classList.toggle('cursor-pointer', !connected);
                container.classList.toggle('cursor-default', connected);
            }

            function recordConnectionTransitionNotification(previousConnected, nextConnected, nextMessage) {
                if (!hasHydratedConnectionState) {
                    hasHydratedConnectionState = true;
                    return;
                }
                if (previousConnected === nextConnected || typeof window.recordUnreadAlarm !== 'function') {
                    return;
                }
                var notificationMessage = nextMessage || (nextConnected ? '交易接口已连接' : '交易接口连接断开');
                window.recordUnreadAlarm(notificationMessage, 'connection');
            }

            function refreshConnectionStatus() {
                fetch('/api/trade/connection-status', {
                    headers: { 'Accept': 'application/json' },
                })
                    .then(function(response) {
                        if (!response.ok) {
                            throw new Error('request failed');
                        }
                        return response.json();
                    })
                    .then(function(data) {
                        var nextData = data || {};
                        var previousConnected = !!tradeConnectionState.connected;
                        updateConnectionIndicator(nextData);
                        recordConnectionTransitionNotification(previousConnected, !!nextData.connected, tradeConnectionState.message);
                    })
                    .catch(function() {
                        updateConnectionIndicator({
                            connected: false,
                            message: '交易接口状态未知',
                        });
                    });
            }

            window.recordUnreadAlarm = function(message, category) {
                if (!message || !isSupportedNotificationCategory(category)) {
                    return;
                }
                var unread = loadUnreadNotifications();
                unread.unshift({
                    id: 'alarm-' + String(Date.now()) + '-' + Math.random().toString(16).slice(2),
                    message: String(message),
                    category: String(category),
                    createdAt: new Date().toISOString(),
                });
                saveUnreadNotifications(unread);
                updateAlarmBadge();
            };

            window.handleTradeConnectionAction = function() {
                if (tradeConnectionState.connected) {
                    return;
                }
                window.openRestartQmtModal();
            };

            window.openRestartQmtModal = function() {
                var modal = document.getElementById('restart-qmt-modal');
                if (!modal || tradeConnectionState.connected) {
                    return;
                }
                resetRestartQmtForm();
                
                // 检查是否有存储的密码
                var passwordSection = document.getElementById('restart-qmt-password-section');
                if (passwordSection) {
                    passwordSection.classList.add('hidden');
                }
                
                fetch('/api/trade/restart-qmt/has-password', {
                    headers: { 'Accept': 'application/json' },
                })
                    .then(function(response) { return response.json(); })
                    .then(function(data) {
                        if (!data.has_password && passwordSection) {
                            passwordSection.classList.remove('hidden');
                        }
                    })
                    .catch(function() {
                        if (passwordSection) {
                            passwordSection.classList.remove('hidden');
                        }
                    });
                
                modal.classList.add('modal-open');
            };

            window.closeRestartQmtModal = function() {
                var modal = document.getElementById('restart-qmt-modal');
                resetRestartQmtForm();
                if (modal) {
                    modal.classList.remove('modal-open');
                }
            };

            window.submitRestartQmt = function() {
                var submitButton = document.getElementById('restart-qmt-submit');

                if (restartRequestInFlight) {
                    return;
                }

                restartRequestInFlight = true;
                if (submitButton) {
                    submitButton.disabled = true;
                    submitButton.textContent = '重启中...';
                }
                showRestartQmtMessage('正在重启 QMT 并尝试重新连接交易接口，请稍候...', true);

                var passwordInput = document.getElementById('restart-qmt-password');
                var password = passwordInput ? passwordInput.value : '';
                
                fetch('/api/trade/restart-qmt', {
                    method: 'POST',
                    headers: {
                        'Accept': 'application/json',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    },
                    body: password ? 'password=' + encodeURIComponent(password) : '',
                })
                    .then(function(response) {
                        return response.json().catch(function() {
                            return {
                                success: false,
                                error: 'QMT 重启响应解析失败',
                            };
                        });
                    })
                    .then(function(result) {
                        if (result && result.success) {
                            showRestartQmtMessage(result.message || 'QMT 已重启并重新连接交易接口', true);
                            refreshConnectionStatus();
                            window.setTimeout(function() {
                                window.closeRestartQmtModal();
                                refreshConnectionStatus();
                            }, 1200);
                            return;
                        }

                        var errorMessage = result && (result.error || result.message)
                            ? String(result.error || result.message)
                            : 'QMT 重启失败';
                        showRestartQmtMessage(errorMessage, false);
                    })
                    .catch(function(error) {
                        var message = error && error.message ? error.message : 'QMT 重启失败';
                        showRestartQmtMessage(message, false);
                    })
                    .finally(function() {
                        restartRequestInFlight = false;
                        if (submitButton) {
                            submitButton.disabled = false;
                            submitButton.textContent = '确认重启';
                        }
                    });
            };

            window.openNotificationCenter = function() {
                var modal = document.getElementById('notification-center-modal');
                if (!modal) {
                    return;
                }
                renderNotificationPage(1);
                modal.classList.add('modal-open');
            };

            window.closeNotificationCenter = function() {
                var modal = document.getElementById('notification-center-modal');
                saveUnreadNotifications([]);
                updateAlarmBadge();
                if (modal) {
                    modal.classList.remove('modal-open');
                }
                renderNotificationPage(1);
            };

            window.changeNotificationPage = function(delta) {
                renderNotificationPage(currentNotificationPage + Number(delta || 0));
            };

            document.addEventListener('click', function(e) {
                var modal = document.getElementById('notification-center-modal');
                if (modal && e.target === modal) {
                    window.closeNotificationCenter();
                }
                var restartModal = document.getElementById('restart-qmt-modal');
                if (restartModal && e.target === restartModal) {
                    window.closeRestartQmtModal();
                }
            });

            window.addEventListener('storage', function() {
                updateAlarmBadge();
                renderNotificationPage(currentNotificationPage);
            });

            updateAlarmBadge();
            refreshConnectionStatus();
            connectionPollTimer = window.setInterval(refreshConnectionStatus, 5000);
        })();
    """)


class MainLayout:
    """主布局类

    包含 header 和 main content（无 sidebar，符合文档要求）。
    """

    def __init__(
        self,
        *content,
        page_title: str = "QMT Gateway",
        user: dict | None = None,
        active_menu: str = "",
    ):
        self.content = content
        self.page_title = page_title
        self.user = user
        self.active_menu = active_menu

    def __ft__(self):
        return Html(
            Head(
                Title(self.page_title),
                *AppTheme.headers(),
            ),
            Body(
                # Header
                Header(self.user, self.active_menu),
                # Main Content Area（无 sidebar，最大宽度 1200px 居中）
                Div(
                    Div(
                        *self.content,
                        cls="w-full max-w-[1200px] mx-auto p-6",
                    ),
                    cls="flex-1 overflow-auto bg-gray-50",
                ),
                # 修改本金 Modal
                PrincipalModal(),
                ChangePasswordModal(),
                ApiKeyModal(),
                NotificationCenterModal(),
                RestartQmtModal(),
                # Modal JavaScript
                PrincipalModalScript(),
                ChangePasswordModalScript(),
                ApiKeyModalScript(),
                HeaderStatusScript(),
                cls="min-h-screen flex flex-col",
            ),
        )


def create_main_page(
    *content,
    page_title: str = "QMT Gateway",
    user: dict | None = None,
    active_menu: str = "",
):
    """创建主页面

    Args:
        content: 页面内容
        page_title: 页面标题
        user: 当前用户信息
        active_menu: 当前激活的导航项

    Returns:
        FastHTML 页面
    """
    layout = MainLayout(
        *content,
        page_title=page_title,
        user=user,
        active_menu=active_menu,
    )
    return layout
