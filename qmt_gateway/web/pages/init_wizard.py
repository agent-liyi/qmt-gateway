"""初始化向导页面

5 步初始化向导：
1. 欢迎页面
2. 管理员设置
3. 服务器设置
4. 本金设置
5. QMT 配置
"""

from fasthtml.common import *
from monsterui.all import *

from qmt_gateway.web.layouts.base import create_base_page
from qmt_gateway.web.theme import PRIMARY_COLOR, PrimaryButton, SecondaryButton


def StepIndicator(current_step: int, total_steps: int = 5):
    """步骤指示器

    使用连接线 + 圆圈的样式，已完成步骤显示 ✓，
    当前步骤圆圈带外环高亮，未完成步骤灰色显示。
    连接线与圆圈垂直居中对齐，整体宽度与表单内容一致。
    """
    steps = [
        ("欢迎", 1),
        ("管理员", 2),
        ("服务器", 3),
        ("本金", 4),
        ("QMT配置", 5),
    ]

    # 所有圆圈统一 w-9 h-9 (36px)，圆心 = padding-top + 18px
    # 连接线 h-0.5 (2px)，线心 = margin-top + 1px
    # 对齐公式：padding-top + 18 = margin-top + 1  →  margin-top = padding-top + 17
    CIRCLE_PAD = 14       # px: 圆圈顶部留白
    LINE_MARGIN_TOP = CIRCLE_PAD + 17  # = 31px → 线心 = 31+1 = 32 = 14+18 ✓

    items = []
    for name, step in steps:
        is_active = step == current_step
        is_completed = step < current_step

        if is_active:
            circle = Div(
                str(step),
                cls="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold "
                    "text-white shrink-0",
                style=(
                    f"background: {PRIMARY_COLOR};"
                    f"box-shadow: 0 0 0 4px rgba(209,53,39,0.2);"
                ),
            )
            label_style = f"color: {PRIMARY_COLOR}; font-weight: 700;"
        elif is_completed:
            circle = Div(
                "✓",
                cls="w-9 h-9 rounded-full flex items-center justify-center text-sm font-bold "
                    "text-white shrink-0",
                style=f"background: {PRIMARY_COLOR};",
            )
            label_style = f"color: {PRIMARY_COLOR}; font-weight: 500;"
        else:
            circle = Div(
                str(step),
                cls="w-9 h-9 rounded-full flex items-center justify-center text-sm font-medium "
                    "shrink-0",
                style="background: #e5e7eb; color: #9ca3af;",
            )
            label_style = "color: #9ca3af;"

        step_col = Div(
            circle,
            Div(name, cls="text-xs mt-2 whitespace-nowrap", style=label_style),
            cls="flex flex-col items-center",
            style=f"padding-top: {CIRCLE_PAD}px;",
        )
        items.append(step_col)

        # 连接线（最后一个步骤后面不加）
        if step < total_steps:
            line_color = PRIMARY_COLOR if is_completed else "#e5e7eb"
            items.append(
                Div(
                    cls="flex-1 h-0.5 mx-2 shrink-0",
                    style=(
                        f"background: {line_color};"
                        f"min-width: 24px;"
                        f"margin-top: {LINE_MARGIN_TOP}px;"
                    ),
                )
            )

    return Div(
        *items,
        cls="flex items-start mb-10 max-w-lg mx-auto",
    )


def Step1_Welcome():
    """步骤1：欢迎页面"""
    return Div(
        H4("欢迎使用 QMT Gateway", cls="text-xl font-semibold mb-4", style=f"color: {PRIMARY_COLOR};"),
        P("QMT Gateway 是一个基于 Python 的量化交易网关。", cls="text-gray-600 mb-4"),
        P("在开始使用之前，我们需要完成一些初始化配置：", cls="text-gray-600 mb-4"),
        Ul(
            Li("设置管理员账号"),
            Li("配置服务器和日志"),
            Li("配置 QMT 账号和路径"),
            cls="list-disc list-inside text-gray-600 mb-4",
        ),
        P("整个初始化过程大约需要 1 分钟。", cls="text-gray-500 text-sm"),
        cls="max-w-lg mx-auto",
    )


def Step2_Admin():
    """步骤2：管理员设置"""
    label_cls = "w-28 shrink-0 text-sm font-semibold text-gray-700"
    return Div(
        H4("设置管理员账号", cls="text-xl font-semibold mb-4", style=f"color: {PRIMARY_COLOR};"),
        Card(
            CardBody(
                Div(
                    Label("用户名", cls=label_cls),
                    Input(
                        type="text",
                        name="username",
                        value="admin",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                Div(
                    Label("密码", cls=label_cls),
                    Input(
                        type="password",
                        name="password",
                        placeholder="请输入密码",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                Div(
                    Label("确认密码", cls=label_cls),
                    Input(
                        type="password",
                        name="password_confirm",
                        placeholder="请再次输入密码",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3",
                ),
            ),
            cls="mb-4",
        ),
        cls="max-w-lg mx-auto",
    )


def Step3_Server():
    """步骤3：服务器设置"""
    label_cls = "w-28 shrink-0 text-sm font-semibold text-gray-700"
    return Div(
        H4("服务器设置", cls="text-xl font-semibold mb-4", style=f"color: {PRIMARY_COLOR};"),
        P("建议使用默认配置。", cls="text-gray-600 mb-4"),
        Card(
            CardBody(
                Div(
                    Label("服务器端口", cls=label_cls),
                    Input(
                        type="number",
                        name="server_port",
                        value="8130",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                Div(
                    Label("日志路径", cls=label_cls),
                    Input(
                        type="text",
                        name="log_path",
                        value="~/.qmt-gateway/log",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                Div(
                    Label("日志轮转大小", cls=label_cls),
                    Input(
                        type="text",
                        name="log_rotation",
                        value="10 MB",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                Div(
                    Label("日志保留数量", cls=label_cls),
                    Input(
                        type="number",
                        name="log_retention",
                        value="10",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3",
                ),
            ),
            cls="mb-4",
        ),
        cls="max-w-lg mx-auto",
    )


def Step4_Principal():
    """步骤4：本金设置"""
    label_cls = "w-28 shrink-0 text-sm font-semibold text-gray-700"
    return Div(
        H4("本金设置", cls="text-xl font-semibold mb-4", style=f"color: {PRIMARY_COLOR};"),
        P("设置账户起始资金，用于盈亏和仓位计算基准。", cls="text-gray-600 mb-4"),
        Card(
            CardBody(
                Div(
                    Label("初始本金（元）", cls=label_cls),
                    Input(
                        type="number",
                        name="principal",
                        value="1000000",
                        min="0.01",
                        step="0.01",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3",
                ),
            ),
            cls="mb-4",
        ),
        cls="max-w-lg mx-auto",
    )


def Step5_QMT(form_data: dict | None = None):
    """步骤5：QMT 配置"""
    fd = form_data or {}
    label_cls = "w-28 shrink-0 text-sm font-semibold text-gray-700"
    return Div(
        H4("QMT 配置", cls="text-xl font-semibold mb-4", style=f"color: {PRIMARY_COLOR};"),
        Card(
            CardBody(
                # QMT 账号 - 横向布局
                Div(
                    Label("QMT 账号", cls=label_cls),
                    Input(
                        type="text",
                        name="qmt_account_id",
                        value=fd.get("qmt_account_id", ""),
                        placeholder="请输入 QMT 账号",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                # QMT 交易密码 - 横向布局
                Div(
                    Label("QMT 交易密码", cls=label_cls, id="qmt-password-label"),
                    Input(
                        type="password",
                        name="qmt_password",
                        id="qmt-password-input",
                        value=fd.get("qmt_password", ""),
                        placeholder="选填，启用自动启动时必填",
                        cls="input input-bordered flex-1",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                # 自动启动 QMT - 复选框
                Div(
                    Input(
                        type="checkbox",
                        name="auto_start_qmt",
                        id="auto_start_qmt",
                        value="on",
                        checked=fd.get("auto_start_qmt") == "on",
                        cls="w-4 h-4 text-red-600 border-gray-300 rounded focus:ring-red-500",
                    ),
                    Label(
                        "允许自动启动、重启 QMT（需要填写交易密码）",
                        _for="auto_start_qmt",
                        cls="ml-2 text-sm text-gray-700 cursor-pointer",
                    ),
                    cls="flex items-center gap-3 mb-4",
                ),
                # QMT 路径 - 横向布局 + 保留下方提示
                Div(
                    Label("QMT 路径", cls=label_cls),
                    Input(
                        type="text",
                        name="qmt_path",
                        value=fd.get("qmt_path", ""),
                        placeholder=(
                            "如果不知道 QMT 安装位置，可以从启动 QMT 的快捷方式中"
                            "查看目标，复制到此处，例如:"
                            r" C:\apps\qmt\bin.x64\XtMiniQmt.exe"
                        ),
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3",
                ),
                P(
                    "可填 XtMiniQmt.exe 所在 bin.x64 目录、其上级目录，或 QMT 根目录。"
                    "向导会自动校验是否存在 bin.x64\\XtMiniQmt.exe。",
                    cls="text-xs text-gray-500 mt-1 ml-31",
                ),
                # xtquant 路径 - 横向布局（必填——必须明确指定，不能从 QMT
                # 目录推断；qmt_path 仅用作 DLL 搜索目录，不进 sys.path）
                Div(
                    Label("xtquant 路径", cls=label_cls),
                    Input(
                        type="text",
                        name="xtquant_path",
                        value=fd.get("xtquant_path", ""),
                        placeholder=r"包含 xtquant.py 的文件目录，例如: C:\apps\xtquant",
                        cls="input input-bordered flex-1",
                        required="required",
                    ),
                    cls="flex items-center gap-3 mt-4",
                ),
                P(
                    "填写包含 xtquant.py 的目录。如果解压到 C:\\apps\\xtquant，则填入 C:\\apps\\xtquant。",
                    cls="text-xs text-gray-500 mt-1 ml-31",
                ),
            ),
            cls="mb-4",
        ),
        cls="max-w-lg mx-auto",
    )


def WizardContent(step: int, form_data: dict | None = None):
    """根据步骤渲染内容"""
    if step == 5:
        return Step5_QMT(form_data=form_data)
    content_map = {
        1: Step1_Welcome(),
        2: Step2_Admin(),
        3: Step3_Server(),
        4: Step4_Principal(),
    }
    return content_map.get(step, Step1_Welcome())


def WizardButtons(step: int, total_steps: int = 5):
    """向导导航按钮"""
    left_buttons = []
    right_buttons = []

    # 上一步按钮
    if step > 1:
        left_buttons.append(
            SecondaryButton(
                "上一步",
                hx_post=f"/init-wizard/step/{step - 1}",
                hx_target="#wizard-form-container",
                hx_include="#wizard-form",
            )
        )

    # 下一步/完成按钮
    if step < total_steps:
        right_buttons.append(
            PrimaryButton(
                "下一步",
                hx_post=f"/init-wizard/step/{step + 1}",
                hx_target="#wizard-form-container",
                hx_include="#wizard-form",
            )
        )
    else:
        # 最后一步：完成初始化
        right_buttons.append(
            PrimaryButton(
                "完成初始化",
                hx_post="/init-wizard/complete",
                hx_target="#wizard-form-container",
                hx_include="#wizard-form",
            )
        )

    return Div(
        Div(*left_buttons, cls="flex gap-2"),
        Div(*right_buttons, cls="flex gap-2"),
        cls="flex justify-between mt-8 pt-5 border-t border-gray-200",
    )


def _WizardProgressModal(visible: bool = False, oob: bool = False):
    """QMT 启动/连接进度对话框（独立于表单容器，不会被 HTMX 交换替换）。

    内容区域 id="wizard-progress-content" 支持 OOB 交换，
    用于动态更新加载状态、错误信息与重试按钮。

    对话框包含：
    - 标题 "检测 QMT 是否正在运行"
    - 加载动画 + 状态文字
    - 已等待时间计数器
    - 重试按钮（30 秒后启用）+ 返回修改配置按钮

    Args:
        visible: 是否可见（用于 OOB 交换时强制显示对话框）。
        oob: 是否作为 HTMX OOB 交换元素返回（响应片段中使用）。
    """
    modal_cls = "modal modal-open" if visible else "modal"
    kwargs = dict(
        cls=modal_cls,
        id="wizard-progress-modal",
    )
    if oob:
        kwargs["hx_swap_oob"] = "true"
    return Div(
        Div(cls="modal-backdrop"),
        Div(
            Div(
                # 标题
                H3(
                    "检测 QMT 是否正在运行",
                    cls="text-lg font-bold text-gray-800 mb-6",
                ),
                # 可 OOB 替换的内容区
                Div(
                    Div(
                        Span(cls="loading loading-spinner loading-lg text-primary"),
                        cls="mb-4",
                    ),
                    P(
                        "正在自动启动 QMT 客户端并测试连接，请稍候...",
                        cls="text-base text-gray-700 mb-2",
                        id="wizard-progress-text",
                    ),
                    P(
                        "已等待 0 秒",
                        cls="text-sm text-gray-400",
                        id="wizard-elapsed",
                    ),
                    # 按钮区域
                    Div(
                        Button(
                            "重试",
                            cls="btn px-8 py-2",
                            id="wizard-retry-btn",
                            disabled="disabled",
                            style="background: #d1d5db; color: white; border: none; cursor: not-allowed;",
                            hx_post="/init-wizard/retry-startup",
                            hx_target="#wizard-form-container",
                        ),
                        Button(
                            "返回修改配置",
                            cls="btn btn-ghost px-8 py-2",
                            hx_get="/init-wizard/step/5",
                            hx_target="#wizard-form-container",
                        ),
                        cls="flex justify-center gap-3 mt-6",
                    ),
                    id="wizard-progress-content",
                    cls="text-center py-2 px-2",
                ),
                cls="py-6 px-6",
            ),
            cls="modal-box bg-white shadow-2xl",
        ),
        **kwargs,
    )


def _WizardScript():
    """向导页面的 HTMX 事件处理脚本。

    - 点击"完成初始化"或"重试"按钮时**立即**显示进度对话框并启动计时器
        - 重试按钮累计等待 30 秒后启用；auto-retry 不应重置这个计时
    - 请求成功后在 beforeSwap 中拦截，阻止 htmx 交换并全页跳转首页
    - 请求出错时隐藏进度对话框
    """
    return NotStr(r"""
<script>
(function() {
  var _timer = null;
    var _retryDelay = 30;
  var _wizardRequestActive = false;
    var _progressStartedAt = 0;

    function currentElapsedSeconds() {
        if (!_progressStartedAt) return 0;
        return Math.max(0, Math.floor((Date.now() - _progressStartedAt) / 1000));
    }

    function updateElapsedText() {
        var el = document.getElementById('wizard-elapsed');
        if (el) el.textContent = '已等待 ' + currentElapsedSeconds() + ' 秒';
    }

  function enableRetryBtn() {
    var btn = document.getElementById('wizard-retry-btn');
        if (!btn) return;
    btn.disabled = false;
    btn.textContent = '重试';
    btn.style.background = '#D13527';
    btn.style.cursor = 'pointer';
  }

  function disableRetryBtn(text) {
    var btn = document.getElementById('wizard-retry-btn');
    if (!btn) return;
    btn.disabled = true;
    btn.textContent = text || '重试';
    btn.style.background = '#d1d5db';
    btn.style.cursor = 'not-allowed';
  }

    function syncProgressState() {
        updateElapsedText();
        if (_wizardRequestActive) {
            disableRetryBtn('正在重试...');
            return;
        }
        if (currentElapsedSeconds() >= _retryDelay) {
            enableRetryBtn();
            return;
        }
        disableRetryBtn('重试');
    }

    function ensureProgressTimer() {
        if (_timer) return;
        _timer = setInterval(function() {
            syncProgressState();
        }, 1000);
    }

    function openProgressModal(options) {
        options = options || {};
    var m = document.getElementById('wizard-progress-modal');
    if (!m) return;
        var shouldResetTimer = !!options.resetTimer;
        var shouldResetContent = !!options.resetContent;

        if (!m.classList.contains('modal-open') || !_progressStartedAt) {
            shouldResetTimer = true;
        }

    m.classList.add('modal-open');

    var content = document.getElementById('wizard-progress-content');
        if (content && shouldResetContent) {
      content.innerHTML =
        '<div class="mb-4"><span class="loading loading-spinner loading-lg text-primary"></span></div>' +
        '<p class="text-base text-gray-700 mb-2" id="wizard-progress-text">正在自动启动 QMT 客户端并测试连接，请稍候...</p>' +
        '<p class="text-sm text-gray-400" id="wizard-elapsed">已等待 0 秒</p>' +
        '<div class="flex justify-center gap-3 mt-6">' +
          '<button class="btn px-8 py-2" id="wizard-retry-btn" disabled ' +
            'style="background:#d1d5db;color:white;border:none;cursor:not-allowed;" ' +
            'hx-post="/init-wizard/retry-startup" hx-target="#wizard-form-container">重试</button>' +
          '<button class="btn btn-ghost px-8 py-2" ' +
            'hx-get="/init-wizard/step/5" hx-target="#wizard-form-container">返回修改配置</button>' +
        '</div>';
      if (window.htmx) htmx.process(content);
    }

        if (shouldResetTimer) {
            _progressStartedAt = Date.now();
        }
        ensureProgressTimer();
        syncProgressState();
  }

  function closeProgressModal() {
    if (_timer) { clearInterval(_timer); _timer = null; }
    _wizardRequestActive = false;
        _progressStartedAt = 0;
    var m = document.getElementById('wizard-progress-modal');
    if (m) m.classList.remove('modal-open');
  }

  /* 1. 点击"完成初始化"或"重试"时处理进度对话框 */
  document.body.addEventListener('click', function(e) {
    var btn = e.target.closest('button');
    if (!btn) return;
    var hxPost = btn.getAttribute('hx-post') || '';

    if (hxPost.indexOf('/init-wizard/complete') !== -1) {
      var pwInput = document.getElementById('qmt-password-input');
      var pwValue = pwInput ? pwInput.value.trim() : '';
      if (!pwValue) return;
      _wizardRequestActive = true;
      var target = document.getElementById('wizard-form-container');
      if (target) {
        try { htmx.abort(target); } catch(ex) {}
      }
      openProgressModal({ resetTimer: true, resetContent: true });
    } else if (hxPost.indexOf('/init-wizard/retry-startup') !== -1) {
            _wizardRequestActive = true;
      var target = document.getElementById('wizard-form-container');
      if (target) {
        try { htmx.abort(target); } catch(ex) {}
      }
            openProgressModal({
                resetTimer: btn.id !== 'wizard-auto-retry',
                resetContent: btn.id !== 'wizard-auto-retry'
            });
    }
  });

  /* 2. 请求发送前：校验 auto_start_qmt + 密码，拦截无效提交 */
  document.body.addEventListener('htmx:beforeRequest', function(evt) {
    var path = (evt.detail.requestConfig && evt.detail.requestConfig.path) || '';
    if (path.indexOf('/init-wizard/complete') === -1) return;

    var pwInput = document.getElementById('qmt-password-input');
    var pwLabel = document.getElementById('qmt-password-label');
    var autoStartCb = document.getElementById('auto_start_qmt');
    var pwValue = pwInput ? pwInput.value.trim() : '';
    var autoStartChecked = autoStartCb ? autoStartCb.checked : false;

    if (autoStartChecked && !pwValue) {
      evt.preventDefault();
      if (pwInput) { pwInput.classList.add('input-error'); pwInput.focus(); }
      if (pwLabel) { pwLabel.classList.add('text-red-600'); }
      return;
    }
    if (pwInput) pwInput.classList.remove('input-error');
    if (pwLabel) pwLabel.classList.remove('text-red-600');
  });

  /* 3. 请求发送前：标记 + 禁用重试按钮 */
  document.body.addEventListener('htmx:beforeRequest', function(evt) {
    var path = (evt.detail.requestConfig && evt.detail.requestConfig.path) || '';
    if (path.indexOf('/init-wizard/complete') !== -1 ||
        path.indexOf('/init-wizard/retry-startup') !== -1) {
      _wizardRequestActive = true;
            syncProgressState();
    }
  });

  /* 3. 交换前：检测重定向（302 被透明跟随为 200 + 首页 HTML）
        必须在 beforeSwap 拦截，阻止 htmx 把首页 HTML 塞进 wizard 容器 */
  document.body.addEventListener('htmx:beforeSwap', function(evt) {
    if (!_wizardRequestActive) return;

    var xhr = evt.detail.xhr;
        var hxRedirect = xhr.getResponseHeader('HX-Redirect');

        if (hxRedirect) {
            evt.preventDefault();
            _wizardRequestActive = false;
            window.location.href = hxRedirect;
            return;
        }

    /* 显式 3xx */
    if (xhr.status >= 300 && xhr.status < 400) {
      evt.preventDefault();
      _wizardRequestActive = false;
      window.location.href = xhr.getResponseHeader('Location') || '/';
      return;
    }

    /* 200 但响应不含 wizard 片段 → 说明是重定向后的全页 HTML */
    if (xhr.status === 200) {
      var text = xhr.responseText || '';
      if (text.indexOf('wizard-form-container') === -1) {
        evt.preventDefault();
        _wizardRequestActive = false;
        window.location.href = '/';
        return;
      }
    }
  });

    document.body.addEventListener('htmx:afterSwap', function(evt) {
        var target = evt.detail.target;
        if (!target) return;
        if (target.id === 'wizard-form-container' ||
                target.id === 'wizard-progress-content' ||
                target.id === 'wizard-progress-modal') {
            syncProgressState();
        }
    });

  /* 4. 请求完成后：清除标记，重新启用重试按钮 */
  document.body.addEventListener('htmx:afterRequest', function(evt) {
    var path = (evt.detail.requestConfig && evt.detail.requestConfig.path) || '';
    if (path.indexOf('/init-wizard/complete') === -1 &&
        path.indexOf('/init-wizard/retry-startup') === -1) return;

    _wizardRequestActive = false;
        syncProgressState();
  });

  /* 5. 请求出错时关闭对话框 */
  document.body.addEventListener('htmx:responseError', function(evt) {
    closeProgressModal();
  });

  /* 6. auto_start_qmt + 密码联动：输入密码后或取消勾选时清除错误样式 */
  document.body.addEventListener('input', function(e) {
    if (e.target.id === 'qmt-password-input') {
      if (e.target.value.trim()) {
        e.target.classList.remove('input-error');
        var pwLabel = document.getElementById('qmt-password-label');
        if (pwLabel) pwLabel.classList.remove('text-red-600');
      }
    }
  });
  document.body.addEventListener('change', function(e) {
    if (e.target.id === 'auto_start_qmt' && !e.target.checked) {
      var pwInput = document.getElementById('qmt-password-input');
      var pwLabel = document.getElementById('qmt-password-label');
      if (pwInput) pwInput.classList.remove('input-error');
      if (pwLabel) pwLabel.classList.remove('text-red-600');
    }
  });
})();
</script>
""")


def InitWizardForm(step: int = 1, form_data: dict | None = None, error: str = None):
    """初始化向导表单（用于 HTMX 更新，包含步骤指示器和表单内容）

    Args:
        step: 当前步骤
        form_data: 表单数据
        error: 错误信息（如果有）
    """
    content = WizardContent(step, form_data)
    buttons = WizardButtons(step)

    # 错误提示
    error_div = None
    if error:
        error_div = Div(
            P(f"✗ {error}", cls="text-red-600 font-bold mb-4 text-center"),
            cls="mb-4",
        )

    return Div(
        # 步骤指示器
        StepIndicator(step),
        # 错误提示（如果有）
        error_div if error else Div(),
        # 表单内容 - 使用 form 包裹以便 HTMX 正确序列化表单数据
        Form(
            Div(content, id="wizard-content-inner"),
            buttons,
            cls="bg-white rounded-lg shadow p-6 max-w-4xl mx-auto",
            id="wizard-form",
        ),
        # 错误信息 OOB 交换区域（用于在重试时清除旧错误）
        Div(id="wizard-error"),
        cls="py-8 px-4",
        id="wizard-form-container",
    )


def InitWizardPage(step: int = 1, form_data: dict | None = None):
    """初始化向导页面（完整页面）

    页面结构：
    - 向导表单（可被 HTMX 交换）
    - 进度对话框（独立于表单容器，持久存在）
    - HTMX 事件脚本
    """
    return create_base_page(
        Div(
            InitWizardForm(step, form_data),
            _WizardProgressModal(),
            _WizardScript(),
            cls="relative",
        ),
        page_title="系统初始化 - QMT Gateway",
    )
