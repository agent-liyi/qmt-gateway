"""QMT login window automation helpers."""

from __future__ import annotations

QMT_LOGIN_BUTTON_TEXTS = ("登录", "登 录", "确定", "确认", "进入")
QMT_PASSWORD_HINT_TOKENS = ("交易密码", "密码", "password", "passwd", "pwd")
QMT_ACCOUNT_HINT_TOKENS = ("账号", "账户", "account", "user", "客户号", "资金账号")
QMT_LOGIN_WINDOW_TITLE_TOKENS = ("qmt", "国金", "交易端", "交易终端", "sinolink")
QMT_SPLASH_WINDOW_TITLES = ("xtitclient",)
QMT_PASSWORD_FIELD_CENTER = (0.50, 0.70)
QMT_LOGIN_BUTTON_CENTER = (0.38, 0.85)
QMT_NON_INPUT_HINT_TOKENS = (
    "button",
    "按钮",
    "text",
    "文本",
    "static",
    "image",
    "图片",
    "checkbox",
    "check box",
    "radio",
    "tab",
    "list",
    "tree",
    "table",
)


def _safe_text(value) -> str:
    return str(value or "").strip()


def _is_visible(control) -> bool:
    try:
        return bool(control.is_visible())
    except Exception:
        return False


def _is_enabled(control) -> bool:
    try:
        return bool(control.is_enabled())
    except Exception:
        return True


def _control_descriptor(control) -> str:
    parts: list[str] = []

    try:
        parts.append(_safe_text(control.window_text()))
    except Exception:
        pass

    try:
        parts.append(_safe_text(control.friendly_class_name()))
    except Exception:
        pass

    element = getattr(control, "element_info", None)
    if element is not None:
        for attr in ("name", "automation_id", "class_name", "control_type"):
            parts.append(_safe_text(getattr(element, attr, "")))

    return " ".join(part for part in parts if part).lower()


def _is_password_descriptor(descriptor: str) -> bool:
    return any(token in descriptor for token in QMT_PASSWORD_HINT_TOKENS)


def _is_account_descriptor(descriptor: str) -> bool:
    return any(token in descriptor for token in QMT_ACCOUNT_HINT_TOKENS)


def _is_non_input_descriptor(descriptor: str) -> bool:
    return any(token in descriptor for token in QMT_NON_INPUT_HINT_TOKENS)


def _is_edit_like(control, descriptor: str) -> bool:
    if hasattr(control, "set_edit_text"):
        return True
    return "edit" in descriptor or "richedit" in descriptor


def _is_interactive_input(control, descriptor: str) -> bool:
    if _is_non_input_descriptor(descriptor):
        return False
    if _is_edit_like(control, descriptor):
        return True
    return "custom" in descriptor or "pane" in descriptor


def _descendants(control, **kwargs):
    try:
        return list(control.descendants(**kwargs))
    except Exception:
        return []


def _control_text(control) -> str:
    try:
        return _safe_text(control.window_text())
    except Exception:
        return ""


def _iter_control_context(control):
    current = control
    for _ in range(3):
        try:
            current = current.parent()
        except Exception:
            break
        if current is None:
            break
        yield current


def _window_relative_coords(window, x_ratio: float, y_ratio: float) -> tuple[int, int]:
    try:
        rect = window.rectangle()
    except Exception as exc:
        raise RuntimeError(f"无法获取 QMT 登录窗口坐标: {exc}") from exc

    left = int(getattr(rect, "left", 0))
    top = int(getattr(rect, "top", 0))
    right = int(getattr(rect, "right", 0))
    bottom = int(getattr(rect, "bottom", 0))
    width = max(right - left, 1)
    height = max(bottom - top, 1)
    x = min(max(int(round(width * x_ratio)), 1), max(width - 2, 1))
    y = min(max(int(round(height * y_ratio)), 1), max(height - 2, 1))
    return (x, y)


def _click_window_relative(window, x_ratio: float, y_ratio: float) -> tuple[int, int]:
    coords = _window_relative_coords(window, x_ratio, y_ratio)
    try:
        window.click_input(coords=coords)
    except Exception as exc:
        raise RuntimeError(f"点击 QMT 登录窗口失败: coords={coords}, error={exc}") from exc
    return coords


def _window_dimensions(window) -> tuple[int, int]:
    try:
        rect = window.rectangle()
    except Exception:
        return (0, 0)

    left = int(getattr(rect, "left", 0))
    top = int(getattr(rect, "top", 0))
    right = int(getattr(rect, "right", 0))
    bottom = int(getattr(rect, "bottom", 0))
    return (max(right - left, 0), max(bottom - top, 0))


def _window_priority(window) -> int:
    title = _control_text(window).lower()
    width, height = _window_dimensions(window)
    score = 0

    if any(token in title for token in QMT_LOGIN_WINDOW_TITLE_TOKENS):
        score += 100
    if title in QMT_SPLASH_WINDOW_TITLES:
        score -= 100
    if width >= 900:
        score += 10
    if height >= 600:
        score += 10
    return score


def is_probable_login_window(window) -> bool:
    title = _control_text(window).lower()
    if title in QMT_SPLASH_WINDOW_TITLES:
        return False
    return _window_priority(window) > 0


def iter_login_windows(desktop, process_ids: list[int] | set[int]):
    process_id_set = {int(process_id) for process_id in process_ids if int(process_id) > 0}
    windows = []
    for window in desktop.windows():
        try:
            if not window.is_visible():
                continue
            element = getattr(window, "element_info", None)
            if element is None or getattr(element, "process_id", None) not in process_id_set:
                continue
            windows.append(window)
        except Exception:
            continue
    windows.sort(key=_window_priority, reverse=True)
    return windows


def locate_password_input(window):
    visible_controls = [control for control in _descendants(window) if _is_visible(control)]
    semantic_inputs = []
    semantic_anchors = []
    edit_candidates = []
    generic_inputs = []

    for control in visible_controls:
        if not _is_enabled(control):
            continue
        descriptor = _control_descriptor(control)
        if not descriptor:
            descriptor = type(control).__name__.lower()

        if _is_password_descriptor(descriptor):
            if _is_interactive_input(control, descriptor):
                semantic_inputs.append(control)
            else:
                semantic_anchors.append(control)

        if _is_edit_like(control, descriptor) and not _is_account_descriptor(descriptor):
            edit_candidates.append(control)

        if _is_interactive_input(control, descriptor) and not _is_account_descriptor(descriptor):
            generic_inputs.append(control)

    if semantic_inputs:
        return semantic_inputs[-1]

    for anchor in reversed(semantic_anchors):
        for container in _iter_control_context(anchor):
            contextual_controls = [container, *_descendants(container)]
            contextual_inputs = []
            for control in contextual_controls:
                if not _is_visible(control) or not _is_enabled(control):
                    continue
                descriptor = _control_descriptor(control)
                if _is_account_descriptor(descriptor):
                    continue
                if _is_interactive_input(control, descriptor):
                    contextual_inputs.append(control)
            if contextual_inputs:
                return contextual_inputs[-1]

    if edit_candidates:
        return edit_candidates[-1]

    if generic_inputs:
        return generic_inputs[-1]

    raise RuntimeError("未找到 QMT 登录密码输入框")


def locate_account_input(window):
    semantic_candidates = []
    edit_candidates = []

    for control in _descendants(window):
        if not _is_visible(control) or not _is_enabled(control):
            continue
        descriptor = _control_descriptor(control)
        if not _is_interactive_input(control, descriptor):
            continue

        text = _control_text(control).replace(" ", "")
        if _is_account_descriptor(descriptor) or (text.isdigit() and len(text) >= 6):
            semantic_candidates.append(control)
        if _is_edit_like(control, descriptor):
            edit_candidates.append(control)

    if semantic_candidates:
        return semantic_candidates[-1]
    if edit_candidates:
        return edit_candidates[0]
    raise RuntimeError("未找到 QMT 登录账号输入框")


def populate_password_input(control, password: str) -> None:
    last_error: Exception | None = None

    try:
        control.set_focus()
    except Exception as exc:
        last_error = exc

    try:
        control.set_edit_text(password)
        return
    except Exception as exc:
        last_error = exc

    try:
        control.click_input()
    except Exception as exc:
        last_error = exc

    for clear_keys in ("^a{BACKSPACE}", "^a{DEL}", "{HOME}+{END}{BACKSPACE}"):
        try:
            control.type_keys(clear_keys, set_foreground=True)
            break
        except Exception as exc:
            last_error = exc

    try:
        control.type_keys(password, with_spaces=True, set_foreground=True, vk_packet=True)
        return
    except Exception as exc:
        last_error = exc

    raise RuntimeError(f"写入 QMT 登录密码失败: {last_error}") from last_error


def populate_password_via_tab(window, password: str) -> None:
    account_input = locate_account_input(window)
    last_error: Exception | None = None

    for action in (
        lambda: account_input.set_focus(),
        lambda: account_input.click_input(),
        lambda: account_input.type_keys("{TAB}", set_foreground=True),
        lambda: account_input.type_keys(password, with_spaces=True, set_foreground=True, vk_packet=True),
    ):
        try:
            action()
        except Exception as exc:
            last_error = exc
            raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {exc}") from exc

    if last_error is not None:
        raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {last_error}") from last_error


def populate_password_via_layout(window, password: str) -> None:
    last_error: Exception | None = None

    try:
        window.set_focus()
    except Exception as exc:
        last_error = exc

    _click_window_relative(window, *QMT_PASSWORD_FIELD_CENTER)

    for clear_keys in ("^a{BACKSPACE}", "^a{DEL}"):
        try:
            window.type_keys(clear_keys, set_foreground=True)
            break
        except Exception as exc:
            last_error = exc

    try:
        window.type_keys(password, with_spaces=True, set_foreground=True, vk_packet=True)
        return
    except Exception as exc:
        last_error = exc

    raise RuntimeError(f"通过布局坐标输入 QMT 密码失败: {last_error}") from last_error


def submit_login_via_layout(window) -> None:
    _click_window_relative(window, *QMT_LOGIN_BUTTON_CENTER)


def describe_window(window, max_controls: int = 12) -> str:
    title = _control_text(window) or "<empty>"
    element = getattr(window, "element_info", None)
    handle = getattr(window, "handle", None)
    if not handle and element is not None:
        handle = getattr(element, "handle", None)
    class_name = _safe_text(getattr(element, "class_name", "") if element is not None else "")
    control_type = _safe_text(getattr(element, "control_type", "") if element is not None else "")

    controls = []
    for control in _descendants(window)[:max_controls]:
        if not _is_visible(control):
            continue
        descriptor = _control_descriptor(control)
        if descriptor:
            controls.append(descriptor)

    handle_text = hex(int(handle)) if handle else "n/a"
    controls_text = " | ".join(controls[:max_controls]) if controls else "<none>"
    return f"title={title}, handle={handle_text}, class={class_name or 'n/a'}, type={control_type or 'n/a'}, controls={controls_text}"


def submit_login_window(window):
    try:
        buttons = window.descendants(control_type="Button")
    except Exception:
        buttons = []
    for button in buttons:
        try:
            text = str(button.window_text() or "").strip()
            if button.is_enabled() and any(token in text for token in QMT_LOGIN_BUTTON_TEXTS):
                button.click_input()
                return
        except Exception:
            continue
    window.set_focus()
    window.type_keys("{ENTER}")