"""Main layout notification regression tests."""

from fastcore.xml import to_xml

from qmt_gateway.web.layouts.main import ChangePasswordModal, ChangePasswordModalScript, HeaderStatusScript


def test_header_status_script_limits_unread_notifications_to_connection_and_trade_events():
    html = to_xml(HeaderStatusScript())

    assert "qmt-gateway-unread-notifications" in html
    assert "isSupportedNotificationCategory" in html
    assert "recordConnectionTransitionNotification" in html
    assert "window.recordUnreadAlarm(notificationMessage, 'connection');" in html
    assert "window.recordUnreadAlarm(errorMessage);" not in html
    assert "window.recordUnreadAlarm(message);" not in html


def test_change_password_modal_has_two_tabs():
    html = to_xml(ChangePasswordModal())
    assert "登录密码" in html
    assert "tab-login-password" in html
    assert "交易密码" in html
    assert "tab-qmt-password" in html


def test_change_password_qmt_tab_only_two_fields():
    html = to_xml(ChangePasswordModal())
    assert "change-qmt-login-password" in html
    assert "change-qmt-new-password" in html
    assert "change-qmt-confirm-password" not in html
    assert "再次输入新的 QMT 交易密码" not in html


def test_main_layout_renders_new_change_password_dialog():
    from qmt_gateway.web.layouts.main import MainLayout

    html = to_xml(MainLayout("x", user={"username": "admin"}, active_menu="trading"))
    assert "tab-login-password" in html
    assert "tab-qmt-password" in html
    assert "change-qmt-login-password" in html
    assert "change-qmt-new-password" in html
    assert "change-qmt-confirm-password" not in html
    assert "再次输入新的 QMT 交易密码" not in html


def test_change_password_qmt_submit_sends_confirm_equal_new():
    html = to_xml(ChangePasswordModalScript())
    assert "new_qmt_password_confirm: newPassword" in html
