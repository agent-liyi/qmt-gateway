"""Main layout notification regression tests."""

from fastcore.xml import to_xml

from qmt_gateway.web.layouts.main import HeaderStatusScript


def test_header_status_script_limits_unread_notifications_to_connection_and_trade_events():
    html = to_xml(HeaderStatusScript())

    assert "qmt-gateway-unread-notifications" in html
    assert "isSupportedNotificationCategory" in html
    assert "recordConnectionTransitionNotification" in html
    assert "window.recordUnreadAlarm(notificationMessage, 'connection');" in html
    assert "window.recordUnreadAlarm(errorMessage);" not in html
    assert "window.recordUnreadAlarm(message);" not in html