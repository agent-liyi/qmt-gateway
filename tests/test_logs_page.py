"""Logs page regression tests."""

from fastcore.xml import to_xml

from qmt_gateway.web.pages.logs import LogsPage


def test_logs_page_updates_file_path_on_stream_connection():
    html = to_xml(LogsPage())

    assert 'id="log-file-path"' in html
    assert 'event: file-info' not in html
    assert 'function updateFilePath(text, muted)' in html
    assert 'updateFilePath(": 等待连接...", true);' in html
    assert 'es.addEventListener("file-info", function(e)' in html
    assert 'updateFilePath(": 日志流已连接", false);' in html
    assert 'updateFilePath(": 等待重连...", true);' in html