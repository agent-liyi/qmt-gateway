"""主题配置模块

统一管理应用的主题颜色和样式。
"""

from fasthtml.common import *


# 主色调
PRIMARY_COLOR = "#D13527"
SECONDARY_COLOR = "#f3f4f6"
TEXT_COLOR = "#374151"
BORDER_COLOR = "#d1d5db"


class AppTheme:
    """应用主题配置类"""

    @staticmethod
    def headers():
        """获取主题 headers（CSS 和脚本）

        所有静态资源都从本地 ``/static/`` 提供，避免运行时跨域加载触发
        浏览器 Tracking Prevention（跨域 localStorage 被拦截会导致 htmx
        历史缓存失效）。静态文件由 ``installer/fetch-static-assets.py`` 在
        构建时下载到 ``qmt_gateway/web/static/``。
        """
        return [
            # Tailwind Play CDN（v3 JIT，本地化；与原 CDN 时代渲染完全一致）
            Script(src="/static/tailwind.min.js"),
            # DaisyUI（Tailwind 主题层）
            Link(rel="stylesheet", href="/static/daisyui.min.css"),
            # 自定义主题 CSS
            Style(f"""
                :root {{
                    --p: 4 90% 58%;  /* primary color in HSL: #D13527 approx */
                    --pf: 4 90% 48%; /* primary focus */
                    --pc: 0 0% 100%; /* primary content */
                }}
                .btn-primary {{
                    background-color: {PRIMARY_COLOR} !important;
                    border-color: {PRIMARY_COLOR} !important;
                }}
                .text-primary {{
                    color: {PRIMARY_COLOR} !important;
                }}
                .bg-primary {{
                    background-color: {PRIMARY_COLOR} !important;
                }}
                .border-primary {{
                    border-color: {PRIMARY_COLOR} !important;
                }}
            """),
            # HTMX
            Script(src="/static/htmx.min.js"),
        ]


def PrimaryButton(text, cls="", **kwargs):
    """主色调按钮"""
    base_cls = "btn px-8 py-2 rounded-md font-medium"
    if cls:
        base_cls += f" {cls}"
    return Button(
        text,
        cls=base_cls,
        style=f"background: {PRIMARY_COLOR}; color: white; border: none;",
        **kwargs,
    )


def SecondaryButton(text, cls="", **kwargs):
    """次要按钮"""
    base_cls = "btn px-8 py-2 rounded-md font-medium"
    if cls:
        base_cls += f" {cls}"
    return Button(
        text,
        cls=base_cls,
        style="background: white; color: #374151; border: 1px solid #d1d5db;",
        **kwargs,
    )


def PrimaryTitle(text, **kwargs):
    """主色调标题"""
    return H3(text, style=f"color: {PRIMARY_COLOR};", **kwargs)


def PrimarySubtitle(text, **kwargs):
    """主色调副标题"""
    return H4(text, style=f"color: {PRIMARY_COLOR};", **kwargs)
