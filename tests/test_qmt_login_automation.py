from types import SimpleNamespace

from qmt_gateway.qmt_login_automation import (
    describe_window,
    is_probable_login_window,
    iter_login_windows,
    locate_account_input,
    locate_password_input,
    populate_password_input,
    populate_password_via_layout,
    populate_password_via_tab,
    submit_login_via_layout,
)


class FakeRect:
    def __init__(self, left=0, top=0, right=1000, bottom=800):
        self.left = left
        self.top = top
        self.right = right
        self.bottom = bottom


class FakeControl:
    def __init__(
        self,
        text="",
        *,
        class_name="Custom",
        control_type="Custom",
        friendly="Custom",
        visible=True,
        enabled=True,
        supports_set_edit=True,
        parent=None,
        descendants=None,
        rect=None,
        process_id=0,
    ):
        self._text = text
        self._friendly = friendly
        self._visible = visible
        self._enabled = enabled
        self._supports_set_edit = supports_set_edit
        self._parent = parent
        self._descendants = list(descendants or [])
        self._rect = rect or FakeRect()
        self.actions = []
        self.element_info = SimpleNamespace(
            name=text,
            automation_id="",
            class_name=class_name,
            control_type=control_type,
            process_id=process_id,
        )

    def window_text(self):
        return self._text

    def friendly_class_name(self):
        return self._friendly

    def is_visible(self):
        return self._visible

    def is_enabled(self):
        return self._enabled

    def descendants(self, **kwargs):
        controls = list(self._descendants)
        if "class_name" in kwargs:
            controls = [
                control
                for control in controls
                if getattr(control.element_info, "class_name", None) == kwargs["class_name"]
            ]
        if "control_type" in kwargs:
            controls = [
                control
                for control in controls
                if getattr(control.element_info, "control_type", None) == kwargs["control_type"]
            ]
        return controls

    def parent(self):
        return self._parent

    def set_focus(self):
        self.actions.append(("focus", None, {}))

    def set_edit_text(self, value):
        if not self._supports_set_edit:
            raise RuntimeError("set_edit_text unavailable")
        self.actions.append(("set_edit_text", value, {}))

    def click_input(self, **kwargs):
        self.actions.append(("click_input", None, kwargs))

    def type_keys(self, value, **kwargs):
        self.actions.append(("type_keys", value, kwargs))

    def rectangle(self):
        return self._rect


class FakeDesktop:
    def __init__(self, windows):
        self._windows = list(windows)

    def windows(self):
        return list(self._windows)


def test_locate_password_input_uses_captcha_refresh_anchor_when_present():
    """When a '刷新验证码' anchor exists, the password field is the
    Edit input immediately above the captcha input, even when the
    anchor itself sits a few pixels *below* the captcha input (as is
    the case in the real XtMiniQmt window).
    """
    account_input = FakeControl(
        text="8881457417",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=200, right=400, bottom=240),
    )
    password_input = FakeControl(
        text="",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=260, right=400, bottom=300),
    )
    captcha_input = FakeControl(
        text="",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=320, right=400, bottom=360),
    )
    captcha_refresh = FakeControl(
        text="刷新验证码",
        class_name="Pane",
        control_type="Text",
        friendly="Text",
        rect=FakeRect(left=420, top=326, right=560, bottom=360),
    )
    login_button = FakeControl(
        text="登录",
        class_name="Button",
        control_type="Button",
        friendly="Button",
        rect=FakeRect(left=100, top=420, right=240, bottom=460),
    )
    window = FakeControl(descendants=[account_input, password_input, captcha_input, captcha_refresh, login_button])

    located = locate_password_input(window)
    assert located is password_input


def test_locate_password_input_falls_back_to_input_below_account():
    """When no 刷新验证码 anchor exists, locate the password field as
    the input immediately below the account field.
    """
    account_input = FakeControl(
        text="8881457417",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=200, right=400, bottom=240),
    )
    password_input = FakeControl(
        text="",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=260, right=400, bottom=300),
    )
    window = FakeControl(descendants=[account_input, password_input])

    assert locate_account_input(window) is account_input
    assert locate_password_input(window) is password_input


def test_locate_password_input_uses_password_descriptor_when_present():
    account_input = FakeControl(
        text="8881457417",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=200, right=400, bottom=240),
    )
    password_input = FakeControl(
        text="交易密码",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=260, right=400, bottom=300),
    )
    window = FakeControl(descendants=[account_input, password_input])

    assert locate_password_input(window) is password_input


def test_locate_account_input_falls_back_to_first_input_when_empty():
    account_input = FakeControl(
        text="",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=200, right=400, bottom=240),
    )
    password_input = FakeControl(
        text="",
        class_name="Edit",
        control_type="Edit",
        friendly="Edit",
        rect=FakeRect(left=100, top=260, right=400, bottom=300),
    )
    window = FakeControl(descendants=[account_input, password_input])

    assert locate_account_input(window) is account_input
    assert locate_password_input(window) is password_input


def test_populate_password_input_falls_back_to_click_and_type():
    control = FakeControl(text="交易密码", supports_set_edit=False)
    window = FakeControl(descendants=[control])

    populate_password_input(window, control, "trade-secret")

    assert ("click_input", None, {}) in control.actions
    assert any(action[0] == "type_keys" and action[1] == "trade-secret" for action in control.actions)


def test_activate_window_restores_and_brings_to_top(monkeypatch):
    import ctypes

    window = FakeControl(text="国金QMT")
    window.handle = 0xABCD
    window.is_minimized = lambda: True

    captured: dict = {
        "ShowWindow": [],
        "BringWindowToTop": [],
        "SetForegroundWindow": [],
        "SetWindowPos": [],
    }

    fake_user32 = SimpleNamespace(
        ShowWindow=lambda h, c: captured["ShowWindow"].append((h, c)),
        BringWindowToTop=lambda h: captured["BringWindowToTop"].append(h),
        SetForegroundWindow=lambda h: captured["SetForegroundWindow"].append(h),
        SetWindowPos=lambda h, after, x, y, cx, cy, flags: captured["SetWindowPos"].append(
            (h, after, flags)
        ),
    )
    fake_windll = SimpleNamespace(user32=fake_user32)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    import qmt_gateway.qmt_login_automation as qla

    qla._activate_window(window)

    assert (0xABCD, 9) in captured["ShowWindow"]
    assert 0xABCD in captured["BringWindowToTop"]
    assert 0xABCD in captured["SetForegroundWindow"]
    # 修复 #94：必须 SetWindowPos 设到 HWND_TOPMOST 才能绕过遮挡
    topmost_calls = [c for c in captured["SetWindowPos"] if c[1] == -1]
    assert topmost_calls, "activate_window must SetWindowPos to HWND_TOPMOST (-1)"


def test_deactivate_topmost_clears_topmost(monkeypatch):
    """_deactivate_topmost 必须 SetWindowPos 到 HWND_NOTOPMOST，否则 miniqmt
    登录窗口会一直浮在最顶层挡住用户。"""
    import ctypes

    window = FakeControl(text="国金QMT")
    window.handle = 0xABCD

    captured: list = []

    fake_user32 = SimpleNamespace(
        SetWindowPos=lambda h, after, x, y, cx, cy, flags: captured.append((h, after, flags)),
    )
    fake_windll = SimpleNamespace(user32=fake_user32)
    monkeypatch.setattr(ctypes, "windll", fake_windll, raising=False)

    import qmt_gateway.qmt_login_automation as qla

    qla._deactivate_topmost(window)

    # HWND_NOTOPMOST = -2
    notopmost = [c for c in captured if c[1] == -2]
    assert notopmost, "_deactivate_topmost must SetWindowPos to HWND_NOTOPMOST (-2)"


def test_populate_password_via_tab_uses_account_input():
    account_input = FakeControl(text="8881457417", class_name="Edit", control_type="Edit", friendly="Edit")
    window = FakeControl(descendants=[account_input])

    populate_password_via_tab(window, "trade-secret")

    assert account_input.actions[0][0] == "focus"
    assert ("click_input", None, {}) in account_input.actions
    window_key_actions = [action for action in window.actions if action[0] == "type_keys"]
    assert any(action[1] == "{TAB}" for action in window_key_actions)
    assert any(
        action[1] == "trade-secret" and action[2].get("set_foreground")
        for action in window_key_actions
    )
    assert not any(
        action[0] == "type_keys" and action[1] == "trade-secret" for action in account_input.actions
    )


def test_describe_window_includes_handle_and_controls():
    child = FakeControl(text="交易密码", class_name="Static", control_type="Text", friendly="Text")
    window = FakeControl(text="国金QMT智能策略交易终端", descendants=[child])
    window.handle = 0x1234

    description = describe_window(window)

    assert "0x1234" in description
    assert "国金QMT智能策略交易终端" in description
    assert "交易密码" in description


def test_populate_password_via_layout_uses_relative_window_clicks():
    window = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1000, bottom=800))

    populate_password_via_layout(window, "trade-secret")

    assert ("click_input", None, {"coords": (500, 480)}) in window.actions
    assert any(action[0] == "type_keys" and action[1] == "trade-secret" for action in window.actions)


def test_submit_login_via_layout_clicks_login_button_position():
    window = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1000, bottom=800))

    submit_login_via_layout(window)

    assert window.actions[-1] == ("click_input", None, {"coords": (500, 640)})


def test_iter_login_windows_prefers_named_qmt_login_window_over_splash():
    splash = FakeControl(text="XtMiniQmt", rect=FakeRect(right=800, bottom=600), process_id=42)
    login = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1168, bottom=768), process_id=42)
    desktop = FakeDesktop([splash, login])

    windows = iter_login_windows(desktop, [42])

    assert windows[0] is login
    assert windows[1] is splash


def test_is_probable_login_window_rejects_tiny_splash():
    splash = FakeControl(text="XtMiniQmt", rect=FakeRect(right=300, bottom=200))
    login = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1168, bottom=768))

    assert is_probable_login_window(splash) is False
    assert is_probable_login_window(login) is True


def test_is_probable_login_window_accepts_large_xtminiqmt_window():
    """The real XtMiniQmt login window keeps the 'XtMiniQmt' title
    throughout (splash → login form). It must not be rejected based on
    title alone — only very small splash placeholders are.
    """
    big = FakeControl(text="XtMiniQmt", rect=FakeRect(right=1168, bottom=768))

    assert is_probable_login_window(big) is True