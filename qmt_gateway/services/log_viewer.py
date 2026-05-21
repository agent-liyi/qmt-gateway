"""日志查看服务。

负责读取当前日志文件，并支持最近 N 行、级别过滤和关键词过滤。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

from qmt_gateway.config import config

LOG_LEVELS: tuple[str, ...] = (
    "ALL",
    "DEBUG",
    "INFO",
    "WARNING",
    "ERROR",
    "CRITICAL",
)

LOG_LEVEL_PRIORITY: dict[str, int] = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


@dataclass(frozen=True)
class LogTailResult:
    """日志查询结果。"""

    lines: list[str]
    file_path: Path
    total_matches: int


class LogEventSource:
    """日志事件源，管理文件位置跟踪和轮询。

    每次 poll() 会从上次读取位置之后开始读，返回新增行。
    当检测到文件被轮转（inode 变化或文件变短）时，自动从头开始读。
    """

    def __init__(
        self,
        *,
        level: str = "ALL",
        keyword: str = "",
        poll_interval: float = 1.0,
        maxlen: int = 300,
    ):
        self.level = _normalize_level(level)
        self.keyword = keyword.strip()
        self.poll_interval = poll_interval
        self.maxlen = maxlen

        self._file_path: Path | None = None
        self._position: int = 0
        self._inode: int | None = None
        self._matched_lines: deque[str] = deque(maxlen=maxlen)
        self._total_matches: int = 0

    def init_from_file(self) -> LogTailResult:
        """从日志文件初始化：读取最近 maxlen 行，返回初始化结果。

        供 SSE 首次连接时调用。
        """
        self._file_path = resolve_log_file()
        self._matched_lines: deque[str] = deque(maxlen=self.maxlen)
        self._total_matches = 0

        if not self._file_path.exists():
            return LogTailResult(lines=[], file_path=self._file_path, total_matches=0)

        try:
            stat = self._file_path.stat()
            self._inode = stat.st_ino
            self._position = stat.st_size
        except OSError:
            self._position = 0

        self._read_all_lines()
        return LogTailResult(
            lines=list(self._matched_lines),
            file_path=self._file_path,
            total_matches=self._total_matches,
        )

    def _read_all_lines(self) -> None:
        """读取整个日志文件并初始化匹配结果缓存。"""
        if self._file_path is None or not self._file_path.exists():
            return

        normalized_keyword = self.keyword.casefold() if self.keyword else ""
        try:
            with self._file_path.open("r", encoding="utf-8", errors="replace") as handle:
                for raw_line in handle:
                    line = raw_line.rstrip("\r\n")
                    if not _matches_level(line, self.level):
                        continue
                    if normalized_keyword and normalized_keyword not in line.casefold():
                        continue
                    self._matched_lines.append(line)
                    self._total_matches += 1
        except OSError:
            return

    def poll_new_lines(self) -> list[str]:
        """检查日志文件是否有新增行，返回新增的匹配行列表。

        同时更新内部 matched_lines 缓冲区（保留最近 maxlen 条）。
        """
        if self._file_path is None:
            return []

        target_file = self._file_path
        if not target_file.exists():
            return []

        try:
            stat = target_file.stat()
            current_inode = stat.st_ino
            current_size = stat.st_size
        except OSError:
            return []

        if self._inode != current_inode or current_size < self._position:
            self._inode = current_inode
            self._position = 0
            self._matched_lines.clear()
            self._total_matches = 0

        if current_size == self._position:
            return []

        new_lines: list[str] = []
        try:
            with target_file.open("r", encoding="utf-8", errors="replace") as handle:
                handle.seek(self._position)
                for raw_line in handle:
                    line = raw_line.rstrip("\r\n")
                    if not _matches_level(line, self.level):
                        continue
                    if self.keyword and self.keyword.casefold() not in line.casefold():
                        continue
                    self._matched_lines.append(line)
                    self._total_matches += 1
                    new_lines.append(line)
                self._position = handle.tell()
        except OSError:
            pass

        return new_lines

    @property
    def total_matches(self) -> int:
        return self._total_matches

    @property
    def current_filter_desc(self) -> str:
        parts = []
        if self.level != "ALL":
            parts.append(f"级别: {self.level}")
        if self.keyword:
            parts.append(f"关键词: {self.keyword}")
        return " | ".join(parts) if parts else ""


def resolve_log_file() -> Path:
    """返回当前主日志文件路径。"""
    return config.log_path / "qmt-gateway.log"


def read_recent_logs(
    *,
    level: str = "ALL",
    keyword: str = "",
    limit: int = 300,
    log_file: Path | None = None,
) -> LogTailResult:
    """读取最近的日志内容。

    Args:
        level: 日志级别；传入 ``ALL`` 表示不过滤。
        keyword: 关键词过滤，大小写不敏感。
        limit: 最多返回多少条匹配日志。
        log_file: 可选日志文件路径，便于测试注入。

    Returns:
        过滤后的日志结果。
    """
    normalized_limit = max(limit, 1)
    normalized_level = _normalize_level(level)
    normalized_keyword = keyword.strip().casefold()
    target_file = log_file or resolve_log_file()

    if not target_file.exists():
        return LogTailResult(lines=[], file_path=target_file, total_matches=0)

    matched_lines: deque[str] = deque(maxlen=normalized_limit)
    total_matches = 0
    with target_file.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.rstrip("\r\n")
            if not _matches_level(line, normalized_level):
                continue
            if normalized_keyword and normalized_keyword not in line.casefold():
                continue

            matched_lines.append(line)
            total_matches += 1

    return LogTailResult(
        lines=list(matched_lines),
        file_path=target_file,
        total_matches=total_matches,
    )


def _normalize_level(level: str) -> str:
    """规范化日志级别。"""
    normalized = level.strip().upper() if level else "ALL"
    return normalized if normalized in LOG_LEVELS else "ALL"


def _matches_level(line: str, level: str) -> bool:
    """判断日志行是否匹配级别阈值。"""
    if level == "ALL":
        return True

    threshold = LOG_LEVEL_PRIORITY.get(level.upper())
    if threshold is None:
        return True

    first_pipe = line.find("|")
    if first_pipe == -1:
        return False
    second_pipe = line.find("|", first_pipe + 1)
    if second_pipe == -1:
        return False
    extracted_level = line[first_pipe + 1 : second_pipe].strip()
    current_priority = LOG_LEVEL_PRIORITY.get(extracted_level.upper())
    if current_priority is None:
        return False

    return current_priority >= threshold
