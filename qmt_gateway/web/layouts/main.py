"""主布局模块

提供带 header 的主页面布局（无 sidebar，符合文档要求）。
"""

from fasthtml.common import *
from monsterui.all import *

from qmt_gateway.web.theme import AppTheme, PRIMARY_COLOR


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
            Li(A("退出登录", href="/auth/logout")),
            cls="dropdown-content menu p-2 shadow bg-base-100 rounded-box w-52 mt-4 z-50",
        ),
        cls="dropdown dropdown-end",
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
                # Modal JavaScript
                PrincipalModalScript(),
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
