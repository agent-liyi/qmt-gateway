from types import SimpleNamespace

from qmt_gateway.qmt_login_automation import (
    describe_window,
    is_probable_login_window,
    iter_login_windows,
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


def test_locate_password_input_matches_placeholder_container():
    password_container = FakeControl(text="", class_name="Custom", control_type="Custom", friendly="Custom")
    password_placeholder = FakeControl(
        text="交易密码",
        class_name="Static",
        control_type="Text",
        friendly="Text",
        parent=password_container,
    )
    password_container._descendants = [password_placeholder]
    account_input = FakeControl(text="8881457417", class_name="Edit", control_type="Edit", friendly="Edit")
    window = FakeControl(descendants=[account_input, password_container, password_placeholder])

    located = locate_password_input(window)

    assert located is password_container


def test_populate_password_input_falls_back_to_click_and_type():
    control = FakeControl(text="交易密码", supports_set_edit=False)

    populate_password_input(control, "trade-secret")

    assert ("click_input", None, {}) in control.actions
    assert any(action[0] == "type_keys" and action[1] == "trade-secret" for action in control.actions)


def test_populate_password_via_tab_uses_account_input():
    account_input = FakeControl(text="8881457417", class_name="Edit", control_type="Edit", friendly="Edit")
    window = FakeControl(descendants=[account_input])

    populate_password_via_tab(window, "trade-secret")

    assert account_input.actions[0][0] == "focus"
    assert ("click_input", None, {}) in account_input.actions
    assert any(action[0] == "type_keys" and action[1] == "{TAB}" for action in account_input.actions)
    assert any(action[0] == "type_keys" and action[1] == "trade-secret" for action in account_input.actions)


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

    assert ("click_input", None, {"coords": (500, 560)}) in window.actions
    assert any(action[0] == "type_keys" and action[1] == "trade-secret" for action in window.actions)


def test_submit_login_via_layout_clicks_login_button_position():
    window = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1000, bottom=800))

    submit_login_via_layout(window)

    assert window.actions == [("click_input", None, {"coords": (380, 680)})]


def test_iter_login_windows_prefers_named_qmt_login_window_over_xtitclient_splash():
    splash = FakeControl(text="XtItClient", rect=FakeRect(right=800, bottom=600), process_id=42)
    login = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1168, bottom=768), process_id=42)
    desktop = FakeDesktop([splash, login])

    windows = iter_login_windows(desktop, [42])

    assert windows[0] is login
    assert windows[1] is splash


def test_is_probable_login_window_rejects_xtitclient_splash():
    splash = FakeControl(text="XtItClient", rect=FakeRect(right=800, bottom=600))
    login = FakeControl(text="国金证券QMT交易端 2.0.8.300", rect=FakeRect(right=1168, bottom=768))

    assert is_probable_login_window(splash) is False
    assert is_probable_login_window(login) is True