"""Tests for ``qmt_gateway.core.xtwrapper``.

Covers:

- ``_resolve_xtquant_sys_path``: 路径校验逻辑——必须在两种合法的目录布局
  （package 与 flat）中至少识别一种，并强制要求 ``xtdata.py`` 存在。
- ``add_xtquant_path``: sys.path / DLL 注入顺序与现有 ``qmt_path`` 逻辑的兼容性。

回归点：

- #120: 用户把不是 xtquant SDK 的目录填到 ``xtquant_path``，系统应当抛出
  ``XTQuantNotFoundError``，而不是把任意路径塞进 sys.path 后期待 ``import
  xtquant`` 自己失败。
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from qmt_gateway.core import xtwrapper
from qmt_gateway.core.xtwrapper import (
    XTQuantNotFoundError,
    _resolve_xtquant_sys_path,
    add_xtquant_path,
)


@pytest.fixture(autouse=True)
def _restore_sys_path_and_cache():
    snapshot = list(sys.path)
    yield
    sys.path[:] = snapshot


def _make_pkg_layout(root: Path) -> Path:
    """构造 subdir-package 布局（#120 官方推荐）：

        ``<root>/xtquant/__init__.py``
        ``<root>/xtquant/xtdata.py``
        ``<root>/xtquant/xttrader.py``
    """
    root.mkdir(parents=True, exist_ok=True)
    pkg = root / "xtquant"
    pkg.mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "xtdata.py").write_text("# stub", encoding="utf-8")
    (pkg / "xttrader.py").write_text("# stub", encoding="utf-8")
    return root


def _make_root_pkg_layout(root: Path) -> Path:
    """构造 root-package 布局——``xtquant_path`` 本身就是个包::

        ``<root>/__init__.py``
        ``<root>/xtdata.py``
        ``<root>/xttrader.py``

    这是用户机器上 ``C:\\apps\\xtquant`` 的真实形态：目录名就叫 ``xtquant``，
    里面直接有 ``__init__.py``、``xtdata.py``、``xttrader.py`` 等。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "__init__.py").write_text('__version__ = "xtquant"', encoding="utf-8")
    (root / "xtdata.py").write_text("# stub", encoding="utf-8")
    (root / "xttrader.py").write_text("# stub", encoding="utf-8")
    (root / "xtconstant.py").write_text("# stub", encoding="utf-8")
    return root


def _make_flat_layout(root: Path) -> Path:
    """构造 flat 布局：

        ``<root>/xtquant.py``
        ``<root>/xtdata.py``
        ``<root>/xttrader.py``
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "xtquant.py").write_text("# stub", encoding="utf-8")
    (root / "xtdata.py").write_text("# stub", encoding="utf-8")
    (root / "xttrader.py").write_text("# stub", encoding="utf-8")
    return root


def test_resolve_accepts_package_layout(tmp_path):
    """subdir-package 布局：parent 加进 sys.path。"""
    sdk_root = _make_pkg_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root.parent


def test_resolve_accepts_root_package_layout(tmp_path):
    """root-package 布局（用户机器的真实形态）：sdk_root 自己的父目录加进 sys.path。

    ``tmp_path/xtquant/__init__.py`` 让该目录本身作为 ``xtquant`` 包被 ``import xtquant`` 命中。
    """
    sdk_root = _make_root_pkg_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root.parent


def test_resolve_accepts_flat_layout(tmp_path):
    """flat 布局：sdk_root 自己加进 sys.path。"""
    sdk_root = _make_flat_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root


def test_resolve_rejects_missing_directory(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(XTQuantNotFoundError, match="不存在或不是目录"):
        _resolve_xtquant_sys_path(str(nonexistent))


def test_resolve_rejects_random_directory_without_xtquant_marker(tmp_path):
    """防止用户把 ``C:\\Program Files\\Python311`` 之类的目录当成 xtquant。"""
    bogus = tmp_path / "not-xtquant"
    bogus.mkdir()
    (bogus / "random.txt").write_text("hi", encoding="utf-8")

    with pytest.raises(XTQuantNotFoundError, match="xtquant\\.py|__init__\\.py"):
        _resolve_xtquant_sys_path(str(bogus))


def test_resolve_rejects_pkg_layout_without_xtdata(tmp_path):
    """存在 __init__.py 但缺 xtdata.py 的不完整 SDK 必须被拒。"""
    pkg_root = tmp_path / "xtquant"
    pkg = pkg_root / "xtquant"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # 故意不放 xtdata.py

    with pytest.raises(XTQuantNotFoundError, match="没有 xtdata\\.py"):
        _resolve_xtquant_sys_path(str(pkg_root))


def test_resolve_rejects_flat_layout_without_xtdata(tmp_path):
    """存在 xtquant.py 但缺 xtdata.py 的 flat SDK 必须被拒。"""
    flat_root = tmp_path / "xtquant"
    flat_root.mkdir()
    (flat_root / "xtquant.py").write_text("# stub", encoding="utf-8")
    (flat_root / "xttrader.py").write_text("# stub", encoding="utf-8")

    with pytest.raises(XTQuantNotFoundError, match="没有 xtdata\\.py"):
        _resolve_xtquant_sys_path(str(flat_root))


def test_resolve_returns_none_when_path_is_none_or_empty():
    """空输入直接放过，返回 None——业务代码自己决定怎么报。"""
    assert _resolve_xtquant_sys_path(None) is None
    assert _resolve_xtquant_sys_path("") is None
    assert _resolve_xtquant_sys_path("   ") is None
    # 关键回归点：未初始化的 DB 字段经 ``config.get_expanded_path`` 会变成
    # ``Path(".")``（空字符串 expanduser 后是当前工作目录）。如果直接报错，
    # gateway 首次启动（用户还没填 wizard 之前）就会因 runtime.init() 抛
    # XTQuantNotFoundError 而崩溃。
    assert _resolve_xtquant_sys_path(".") is None
    assert _resolve_xtquant_sys_path("./") is None
    assert _resolve_xtquant_sys_path(".\\") is None
    assert _resolve_xtquant_sys_path(Path(".")) is None
    assert _resolve_xtquant_sys_path(Path(r"C:\apps")) is not None  # 真实路径不能被这条短路


def test_add_xtquant_path_injects_only_parent_for_pkg_layout(tmp_path):
    """add_xtquant_path 对 subdir-package 布局只把 parent 加进 sys.path。

    与 fix 的初衷一致：``import xtquant`` 必须通过 parent 才能找到 ``xtquant/`` 包。
    """
    sdk_root = _make_pkg_layout(tmp_path / "xtquant")
    parent = sdk_root.parent

    add_xtquant_path(xtquant_path=str(sdk_root), qmt_path=None)

    assert parent.as_posix() in sys.path


def test_add_xtquant_path_injects_only_parent_for_root_pkg_layout(tmp_path):
    """root-package 布局：同样把 parent 加进 sys.path。

    这是用户机器上 C:\\apps\\xtquant 的实际形态。
    """
    sdk_root = _make_root_pkg_layout(tmp_path / "xtquant")
    parent = sdk_root.parent

    add_xtquant_path(xtquant_path=str(sdk_root), qmt_path=None)

    assert parent.as_posix() in sys.path
    # 关键：sdk_root 自己**不能**进 sys.path，否则 ``import xtdata`` 会因为
    # 找不到 ``xtquant`` 包而失败（xtquant 需要以 parent 为入口）。
    assert sdk_root.as_posix() not in sys.path


def test_add_xtquant_path_injects_root_for_flat_layout(tmp_path):
    sdk_root = _make_flat_layout(tmp_path / "xtquant")

    add_xtquant_path(xtquant_path=str(sdk_root), qmt_path=None)

    assert sdk_root.as_posix() in sys.path


def test_add_xtquant_path_warns_and_skips_when_path_empty():
    """xtquant_path 为 None 或空时，函数应直接空操作。"""
    add_xtquant_path(xtquant_path=None, qmt_path=None)
    add_xtquant_path(xtquant_path="", qmt_path=None)


def test_add_xtquant_path_raises_for_invalid_path(tmp_path):
    """无效路径：应当抛 XTQuantNotFoundError，而不是悄悄注入。"""
    bogus = tmp_path / "garbage"
    bogus.mkdir()

    with pytest.raises(XTQuantNotFoundError):
        add_xtquant_path(xtquant_path=str(bogus), qmt_path=None)


@pytest.mark.skipif(
    sys.platform != "win32" or not Path(r"C:\apps\xtquant").exists(),
    reason="仅在用户本机的真实 SDK 目录下运行，用于回归验证 #120。",
)
def test_resolve_accepts_user_actual_xtquant_layout():
    """#120 回归：用真实 C:\\apps\\xtquant 验证。

    在 CI / 其他机器上无此目录，自动 skip。验证
    ``_resolve_xtquant_sys_path`` 对真实 SDK 布局返回正确的 sys.path 入口
    （注意该函数本身只返回值，由 ``add_xtquant_path`` 真正写入 sys.path）。
    """
    real_sdk = Path(r"C:\apps\xtquant")
    result = _resolve_xtquant_sys_path(str(real_sdk))

    # 真实 SDK 是 root-package 布局：直接父目录 C:\\apps 应被加入 sys.path。
    assert result == real_sdk.parent


def test_add_xtquant_path_injects_user_actual_layout():
    """#120 端到端：真实 SDK 路径走完 ``add_xtquant_path`` 后 sys.path 含 C:\\apps。

    这条不带 skip——若 C:\\apps\\xtquant 不存在，``add_xtquant_path`` 会抛
    ``XTQuantNotFoundError``，被 except 捕到，按异常路径断言 fail。
    """
    real_sdk = Path(r"C:\apps\xtquant")
    if not real_sdk.exists():
        pytest.skip("C:\\apps\\xtquant 不存在")

    add_xtquant_path(xtquant_path=str(real_sdk), qmt_path=None)

    # add_xtquant_path 用 as_posix() 形式注入（避免 Windows 反斜杠转义）
    assert real_sdk.parent.as_posix() in sys.path
