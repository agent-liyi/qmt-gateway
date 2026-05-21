"""日志服务测试。"""

from __future__ import annotations

from pathlib import Path

from qmt_gateway.services.log_viewer import LogEventSource, read_recent_logs


class TestReadRecentLogs:
    """read_recent_logs 单元测试。"""

    def test_empty_file(self, tmp_path: Path):
        log_file = tmp_path / "empty.log"
        log_file.touch()
        result = read_recent_logs(log_file=log_file, limit=100)
        assert result.lines == []
        assert result.total_matches == 0

    def test_returns_last_n_lines(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        lines = [f"2026-01-01 10:00:{i:02d} | INFO     | test:{i} - line {i}" for i in range(10)]
        log_file.write_text("\n".join(lines), encoding="utf-8")
        result = read_recent_logs(log_file=log_file, limit=5)
        assert len(result.lines) == 5
        assert result.total_matches == 10
        assert result.lines[0] == lines[5]

    def test_level_filter(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2026-01-01 | DEBUG    | app - debug line\n"
            "2026-01-01 | INFO     | app - info line\n"
            "2026-01-01 | ERROR    | app - error line\n"
            "2026-01-01 | WARNING  | app - warn line\n",
            encoding="utf-8",
        )
        result = read_recent_logs(log_file=log_file, level="INFO")
        assert len(result.lines) == 3
        assert all("debug line" not in line for line in result.lines)
        assert any("info line" in line for line in result.lines)
        assert any("warn line" in line for line in result.lines)
        assert any("error line" in line for line in result.lines)

    def test_keyword_filter(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2026-01-01 | INFO | a - apple\n"
            "2026-01-01 | INFO | b - banana\n"
            "2026-01-01 | INFO | c - apple pie\n",
            encoding="utf-8",
        )
        result = read_recent_logs(log_file=log_file, keyword="apple")
        assert len(result.lines) == 2

    def test_combined_filters(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2026-01-01 | DEBUG | a - debug apple\n"
            "2026-01-01 | ERROR | a - error apple\n"
            "2026-01-01 | INFO  | a - info apple\n"
            "2026-01-01 | ERROR | b - error banana\n"
            "2026-01-01 | INFO  | b - info banana\n",
            encoding="utf-8",
        )
        result = read_recent_logs(log_file=log_file, level="INFO", keyword="apple")
        assert len(result.lines) == 2
        assert all("debug apple" not in line for line in result.lines)
        assert any("error apple" in line for line in result.lines)
        assert any("info apple" in line for line in result.lines)


class TestLogEventSource:
    """LogEventSource 单元测试。"""

    def _write_and_init(self, tmp_path: Path, content: str) -> LogEventSource:
        log_file = tmp_path / "test.log"
        if content and not content.endswith("\n"):
            content = content + "\n"
        log_file.write_text(content, encoding="utf-8")
        es = LogEventSource()
        es._file_path = log_file
        es._matched_lines = []
        es._total_matches = 0
        es._position = 0
        es._inode = None
        try:
            stat = log_file.stat()
            es._inode = stat.st_ino
            es._position = stat.st_size
        except OSError:
            pass
        return es

    def test_poll_returns_only_new_lines(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text("\n".join([f"line {i}" for i in range(5)]), encoding="utf-8")
        es = self._write_and_init(tmp_path, "\n".join([f"line {i}" for i in range(5)]))
        new_content = (
            "\n".join([f"line {i}" for i in range(5)])
            + "\n"
            + "\n".join([f"new line {i}" for i in range(3)])
        )
        log_file.write_text(new_content, encoding="utf-8")
        new_lines = es.poll_new_lines()
        assert len(new_lines) == 3
        assert new_lines[0] == "new line 0"
        assert new_lines[2] == "new line 2"

    def test_poll_no_change(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        content = "\n".join([f"line {i}" for i in range(5)])
        log_file.write_text(content, encoding="utf-8")
        es = self._write_and_init(tmp_path, content)
        new_lines = es.poll_new_lines()
        assert new_lines == []

    def test_poll_with_level_filter(self, tmp_path: Path):
        content = (
            "2026-01-01 | DEBUG | debug line\n"
            "2026-01-01 | INFO | info line\n"
            "2026-01-01 | ERROR | error line\n"
            "2026-01-01 | INFO | info line 2\n"
            "2026-01-01 | WARNING | warn line\n"
        )
        es = self._write_and_init(tmp_path, content)
        es.level = "INFO"
        new_content = content + "2026-01-01 | INFO | new info\n2026-01-01 | ERROR | new error\n"
        log_file = tmp_path / "test.log"
        log_file.write_text(new_content, encoding="utf-8")
        new_lines = es.poll_new_lines()
        assert len(new_lines) == 2
        assert any("new info" in line for line in new_lines)
        assert any("new error" in line for line in new_lines)

    def test_poll_with_keyword_filter(self, tmp_path: Path):
        content = "2026-01-01 | INFO | apple pie\n2026-01-01 | INFO | banana\n"
        es = self._write_and_init(tmp_path, content)
        es.keyword = "apple"
        new_content = content + "2026-01-01 | INFO | new apple\n2026-01-01 | INFO | new banana\n"
        log_file = tmp_path / "test.log"
        log_file.write_text(new_content, encoding="utf-8")
        new_lines = es.poll_new_lines()
        assert len(new_lines) == 1
        assert "new apple" in new_lines[0]

    def test_debug_threshold_includes_all_known_levels(self, tmp_path: Path):
        log_file = tmp_path / "test.log"
        log_file.write_text(
            "2026-01-01 | DEBUG    | app - debug line\n"
            "2026-01-01 | INFO     | app - info line\n"
            "2026-01-01 | WARNING  | app - warn line\n"
            "2026-01-01 | ERROR    | app - error line\n"
            "2026-01-01 | CRITICAL | app - critical line\n",
            encoding="utf-8",
        )
        result = read_recent_logs(log_file=log_file, level="DEBUG")
        assert len(result.lines) == 5

    def test_file_truncated_resets_position(self, tmp_path: Path):
        content = "\n".join([f"line {i}" for i in range(10)])
        es = self._write_and_init(tmp_path, content)
        assert es._position > 0
        short_content = "\n".join([f"line {i}" for i in range(3)])
        log_file = tmp_path / "test.log"
        log_file.write_text(short_content, encoding="utf-8")
        new_lines = es.poll_new_lines()
        assert len(new_lines) == 3
        assert new_lines[0] == "line 0"
