"""QMT Mini login window automation helpers."""

from __future__ import annotations

QMT_LOGIN_BUTTON_TEXTS = ("登录", "登 录", "确定", "确认", "进入")
QMT_PASSWORD_HINT_TOKENS = ("交易密码", "密码", "password", "passwd", "pwd")
QMT_CAPTCHA_REFRESH_TOKENS = ("刷新验证码", "刷新 验证码", "换一张", "点击刷新", "refresh captcha")
QMT_ACCOUNT_HINT_TOKENS = ("账号", "账户", "account", "user", "客户号", "资金账号")
QMT_LOGIN_WINDOW_TITLE_TOKENS = ("qmt", "国金", "交易端", "交易终端", "sinolink", "xtminiqmt")
QMT_SPLASH_WINDOW_TITLES = ("xtminiqmt",)
QMT_PASSWORD_FIELD_CENTER = (0.50, 0.60)
QMT_LOGIN_BUTTON_CENTER = (0.50, 0.80)
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


def _is_captcha_refresh_descriptor(descriptor: str) -> bool:
    return any(token in descriptor for token in QMT_CAPTCHA_REFRESH_TOKENS)


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


def _control_position(control) -> tuple[int, int]:
    try:
        rect = control.rectangle()
    except Exception:
        return (0, 0)
    try:
        top = int(getattr(rect, "top", 0))
        left = int(getattr(rect, "left", 0))
    except (TypeError, ValueError):
        return (0, 0)
    return (top, left)


def _visible_input_fields(window):
    """Return visible, enabled, interactive input controls in the window,
    ordered top-to-bottom (and left-to-right as a tie-breaker).

    The XtMiniQmt login window layout is: account field, password field,
    captcha input field, then the login button. The "刷新验证码" label
    sits near the captcha area and serves as an anchor for locating the
    password field (the input directly above it).
    """

    inputs: list[tuple[object, tuple[int, int]]] = []
    for control in _descendants(window):
        if not _is_visible(control) or not _is_enabled(control):
            continue
        descriptor = _control_descriptor(control)
        if not _is_interactive_input(control, descriptor):
            continue
        inputs.append((control, _control_position(control)))

    inputs.sort(key=lambda item: (item[1][0], item[1][1]))
    return [control for control, _ in inputs]


def _control_index(controls, target) -> int:
    if target is None:
        return -1
    for index, control in enumerate(controls):
        if control is target:
            return index
    return -1


def _locate_captcha_refresh_control(window):
    """Find the control that contains the '刷新验证码' text.

    This label/button sits next to or below the captcha area in the
    XtMiniQmt login window. Locating it allows us to find the password
    input as the edit-like input directly above it.
    """
    for control in _descendants(window):
        descriptor = _control_descriptor(control)
        if _is_captcha_refresh_descriptor(descriptor):
            return control
    return None


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


def _window_handle(window) -> int | None:
    handle = getattr(window, "handle", None)
    if handle:
        try:
            return int(handle)
        except (TypeError, ValueError):
            return None
    element = getattr(window, "element_info", None)
    if element is None:
        return None
    element_handle = getattr(element, "handle", None)
    try:
        return int(element_handle) if element_handle else None
    except (TypeError, ValueError):
        return None


def _is_window_minimized(window) -> bool:
    try:
        return bool(window.is_minimized())
    except Exception:
        return False


def _activate_window(window) -> None:
    """Bring ``window`` to the foreground so that subsequent keystrokes
    and clicks reach it instead of whatever window the user is currently
    looking at.
    """

    handle = _window_handle(window)
    if handle:
        try:
            import ctypes

            user32 = ctypes.windll.user32
            if _is_window_minimized(window):
                user32.ShowWindow(handle, 9)
            user32.ShowWindow(handle, 5)
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
        except Exception:
            pass

    try:
        window.set_focus()
    except Exception:
        pass


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
    """Locate the XtMiniQmt password input.

    Strategy (in order):
    1. The input that advertises a password descriptor (e.g. contains
       "交易密码" or "密码").
    2. The edit-like input directly above the "刷新验证码" control.
       The XtMiniQmt layout is: account → password → (验证码 area
       with 刷新验证码 label) → login button. By finding 刷新验证码
       and looking at the input above it, we reliably locate the password
       field.
    3. The input that sits *immediately below* the account field.
    4. The first input whose value is empty -- QMT never pre-fills
       passwords.
    5. The second input as a final fallback.
    """

    inputs = _visible_input_fields(window)
    if not inputs:
        raise RuntimeError("未找到 QMT 登录密码输入框")

    for control in inputs:
        descriptor = _control_descriptor(control)
        if _is_password_descriptor(descriptor):
            return control

    captcha_anchor = _locate_captcha_refresh_control(window)
    if captcha_anchor is not None:
        captcha_pos = _control_position(captcha_anchor)
        best_edit: tuple[object, tuple[int, int]] | None = None
        for control in inputs:
            if control is captcha_anchor:
                continue
            descriptor = _control_descriptor(control)
            if not _is_edit_like(control, descriptor):
                continue
            pos = _control_position(control)
            if pos[0] >= captcha_pos[0]:
                continue
            if best_edit is None or abs(pos[0] - captcha_pos[0]) < abs(best_edit[1][0] - captcha_pos[0]):
                best_edit = (control, pos)
        if best_edit is not None:
            return best_edit[0]

    try:
        account_input = locate_account_input(window)
    except Exception:
        account_input = None

    if account_input is not None:
        for index, control in enumerate(inputs):
            if control is account_input and index + 1 < len(inputs):
                return inputs[index + 1]

    for control in inputs:
        if not _control_text(control).replace(" ", ""):
            return control

    if len(inputs) >= 2:
        return inputs[1]
    return inputs[-1]


def locate_account_input(window):
    """Locate the QMT account input.

    The account field is the top-most input that already has a value
    (the saved broker number). If no field has a value yet, the top-most
    input is the account field by convention.
    """

    inputs = _visible_input_fields(window)
    if not inputs:
        raise RuntimeError("未找到 QMT 登录账号输入框")

    for control in inputs:
        if _control_text(control).replace(" ", ""):
            return control

    return inputs[0]


def populate_password_input(window, control, password: str) -> None:
    last_error: Exception | None = None

    try:
        _activate_window(window)
    except Exception as exc:
        last_error = exc

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
    _activate_window(window)
    account_input = locate_account_input(window)

    try:
        account_input.set_focus()
    except Exception as exc:
        raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {exc}") from exc

    try:
        account_input.click_input()
    except Exception as exc:
        raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {exc}") from exc

    try:
        window.type_keys("{TAB}", set_foreground=True)
    except Exception as exc:
        raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {exc}") from exc

    try:
        password_input = locate_password_input(window)
        if password_input is account_input:
            raise RuntimeError("Tab 导航后仍然命中账号输入框")
        account_text = _control_text(account_input).replace(" ", "")
        password_text = _control_text(password_input).replace(" ", "")
        if account_text and password_text == account_text:
            raise RuntimeError("Tab 导航后命中账号文本（值与账号相同）")
        if account_text and not password_text:
            inputs = _visible_input_fields(window)
            try:
                account_index = inputs.index(account_input)
            except ValueError:
                account_index = -1
            if account_index >= 0 and account_index + 1 < len(inputs):
                fallback = inputs[account_index + 1]
                if fallback is not account_input:
                    password_input = fallback
        populate_password_input(window, password_input, password)
        return
    except Exception:
        pass

    try:
        window.type_keys(password, with_spaces=True, set_foreground=True, vk_packet=True)
    except Exception as exc:
        raise RuntimeError(f"通过 Tab 导航输入 QMT 密码失败: {exc}") from exc


def populate_password_via_layout(window, password: str) -> None:
    _activate_window(window)
    last_error: Exception | None = None

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
    _activate_window(window)
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