"""日志页面。

提供日志查看、自动刷新和双重过滤能力。
"""

from __future__ import annotations

from fasthtml.common import Option as HtmlOption
from fasthtml.common import Select as HtmlSelect
from fasthtml.common import *
from monsterui.all import *
from qmt_gateway.services.log_viewer import LOG_LEVELS
from qmt_gateway.web.layouts.main import create_main_page


def LogFilterBar(level: str = "INFO", keyword: str = ""):
    """日志过滤栏。"""
    options = [
        HtmlOption(
            "全部级别" if item == "ALL" else item,
            value=item,
            selected="selected" if item == level else None,
        )
        for item in LOG_LEVELS
    ]
    return Form(
        Div(
            Div(
                Label("级别", _for="log-level", cls="text-sm font-medium text-gray-600"),
                HtmlSelect(
                    *options,
                    id="log-level",
                    name="level",
                    cls="uk-select select select-bordered w-full bg-white",
                    onchange="window.applyLogFilter()",
                ),
                cls="flex min-w-[180px] flex-col gap-2",
            ),
            Div(
                Label("关键词", _for="log-keyword", cls="text-sm font-medium text-gray-600"),
                Input(
                    id="log-keyword",
                    name="keyword",
                    type="search",
                    value=keyword,
                    placeholder="输入关键词过滤日志",
                    autocomplete="off",
                    spellcheck="false",
                    cls="input input-bordered w-full bg-white",
                    onkeydown="if (event.key === 'Enter') { event.preventDefault(); window.applyLogFilter(); }",
                ),
                cls="flex flex-1 flex-col gap-2",
            ),
            Div(
                Button(
                    "清空",
                    type="button",
                    cls="btn btn-ghost mt-6",
                    onclick="window.clearLogFilter()",
                ),
                Button(
                    "刷新",
                    type="button",
                    cls="btn btn-primary mt-6",
                    onclick="window.resetLogStream()",
                ),
                cls="flex items-center gap-2",
            ),
            cls="flex flex-col gap-4 lg:flex-row lg:items-end",
        ),
        Div(
            "实时推送日志，新增日志自动追加到尾部。",
            cls="text-xs text-gray-500",
        ),
        id="log-filter-form",
        cls="rounded-xl bg-white p-4 shadow",
    )


def LogTerminalContainer():
    """日志终端容器（SSE 实时追加模式）。"""
    return Div(
        Div(
            Div(
                Div("运行日志", cls="text-sm font-semibold text-gray-700"),
                Div(
                    "实时推送中...",
                    id="log-status-bar",
                    cls="text-xs text-gray-500",
                ),
                cls="mb-3 flex flex-col gap-1",
            ),
            Div(
                Div(
                    Span("qmt-gateway", cls="text-green-300"),
                    Span(": 等待连接...", cls="text-gray-400", id="log-file-path"),
                    cls="border-b border-gray-800 px-4 py-3 text-xs font-medium",
                ),
                Pre(
                    "",
                    id="log-terminal-body",
                    cls=(
                        "h-[68vh] overflow-auto whitespace-pre-wrap break-all px-4 py-4 "
                        "font-mono text-[12px] leading-5 text-green-300"
                    ),
                ),
                cls="overflow-hidden rounded-xl border border-gray-800 bg-[#0b1220] shadow-inner",
            ),
            id="log-terminal-wrap",
            cls="rounded-xl bg-white p-4 shadow",
        ),
    )


def LogPageScript(level: str = "INFO", keyword: str = ""):
    """日志页 JavaScript：建立 SSE 连接，处理实时追加和过滤切换。"""
    return Script(
        f"""
        (function() {{
            var es = null;
                var currentLevel = "{level}";
            var currentKeyword = "{keyword}";

            function scrollToBottom() {{
                var body = document.getElementById("log-terminal-body");
                if (body) {{
                    body.scrollTop = body.scrollHeight;
                }}
            }}

            function updateStatus(text) {{
                var el = document.getElementById("log-status-bar");
                if (el) {{
                    el.textContent = text;
                }}
            }}

            function updateFilePath(text, muted) {{
                var el = document.getElementById("log-file-path");
                if (!el) {{
                    return;
                }}
                el.textContent = text;
                el.className = muted ? "text-gray-400" : "text-sky-300";
            }}

            function appendLines(text) {{
                var body = document.getElementById("log-terminal-body");
                if (!body) return;
                if (body.textContent && body.textContent.trim()) {{
                    body.textContent += "\\n" + text;
                }} else {{
                    body.textContent = text;
                }}
                scrollToBottom();
            }}

            function connectSSE() {{
                if (es) {{
                    es.close();
                    es = null;
                }}
                updateStatus("正在连接日志流...");
                updateFilePath(": 等待连接...", true);
                var params = new URLSearchParams();
                params.set("level", currentLevel || "INFO");
                if (currentKeyword) {{
                    params.set("keyword", currentKeyword);
                }}
                var url = "/logs/stream?" + params.toString();
                es = new EventSource(url);

                es.addEventListener("open", function() {{
                    updateStatus("实时推送中...");
                    updateFilePath(": 日志流已连接", false);
                }});

                es.addEventListener("file-info", function(e) {{
                    var value = (e && e.data ? e.data : "").trim();
                    if (!value) {{
                        updateFilePath(": 日志流已连接", false);
                        return;
                    }}
                    updateFilePath(": " + value, false);
                }});

                es.addEventListener("init", function(e) {{
                    var body = document.getElementById("log-terminal-body");
                    if (body) {{
                        body.textContent = e.data || "";
                        scrollToBottom();
                    }}
                }});

                es.addEventListener("new-log", function(e) {{
                    appendLines(e.data);
                }});

                es.addEventListener("status", function(e) {{
                    updateStatus("实时推送中 | " + e.data);
                }});

                es.addEventListener("error", function() {{
                    updateStatus("连接中断，正在重连...");
                    updateFilePath(": 等待重连...", true);
                    es.close();
                    setTimeout(connectSSE, 3000);
                }});
            }}

            window.applyLogFilter = function() {{
                var levelEl = document.getElementById("log-level");
                var keywordEl = document.getElementById("log-keyword");
                var newLevel = levelEl ? levelEl.value : "INFO";
                var newKeyword = keywordEl ? keywordEl.value.trim() : "";
                if (newLevel === currentLevel && newKeyword === currentKeyword) {{
                    return;
                }}
                var params = new URLSearchParams();
                params.set("level", newLevel);
                if (newKeyword) {{ params.set("keyword", newKeyword); }}
                window.location.search = params.toString();
            }};

            window.clearLogFilter = function() {{
                var levelEl = document.getElementById("log-level");
                var keywordEl = document.getElementById("log-keyword");
                if (levelEl) {{ levelEl.value = "INFO"; }}
                if (keywordEl) {{ keywordEl.value = ""; }}
                currentLevel = "INFO";
                currentKeyword = "";
                var params = new URLSearchParams();
                params.set("level", "INFO");
                window.location.search = params.toString();
            }};

            window.resetLogStream = function() {{
                if (es) {{
                    es.close();
                    es = null;
                }}
                var body = document.getElementById("log-terminal-body");
                if (body) {{ body.textContent = ""; }}
                updateFilePath(": 等待连接...", true);
                currentLevel = document.getElementById("log-level") ? document.getElementById("log-level").value : "INFO";
                currentKeyword = document.getElementById("log-keyword") ? document.getElementById("log-keyword").value.trim() : "";
                connectSSE();
            }};

            connectSSE();
        }})();
        """
    )


def LogsPage(
    *,
    user: dict | None = None,
    level: str = "INFO",
    keyword: str = "",
):
    """日志查看页面。"""
    normalized_level = level.strip().upper() if level else "INFO"
    if normalized_level not in LOG_LEVELS:
        normalized_level = "INFO"
    normalized_keyword = keyword.strip()

    return create_main_page(
        LogPageScript(level=normalized_level, keyword=normalized_keyword),
        Div(
            LogFilterBar(level=normalized_level, keyword=normalized_keyword),
            LogTerminalContainer(),
            cls="flex flex-col gap-4 px-4 py-4",
        ),
        page_title="运行日志 - QMT Gateway",
        user=user,
        active_menu="logs",
    )
