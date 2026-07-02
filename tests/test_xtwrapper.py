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
    """构造 package 布局：

        ``<root>/xtquant/__init__.py``
        ``<root>/xtquant/xtdata.py``
        ``<root>/xtquant/xttrader.py``
    """
    root.mkdir(parents=True, exist_ok=True)
    pkg = root / "xtquant"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "xtdata.py").write_text("# stub", encoding="utf-8")
    (pkg / "xttrader.py").write_text("# stub", encoding="utf-8")
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
    """package 布局：parent 加进 sys.path。"""
    sdk_root = _make_pkg_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root.parent


def test_resolve_accepts_flat_layout(tmp_path):
    """flat 布局：sdk_root 自己加进 sys.path。"""
    sdk_root = _make_flat_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root


def test_resolve_strips_xtquant_subdir_when_user_points_there_in_pkg_layout(tmp_path):
    """用户填了 ``<root>/xtquant`` 但 SDK 是包布局时，__init__.py 在子目录。

    当前实现在两种情形中只接受 sdk_root（含 __init__.py 时为包、否则 flat），
    不递归向上推断。``tmp_path/xtquant`` 自己就是包目录视为合法。
    """
    sdk_root = _make_pkg_layout(tmp_path / "xtquant")

    assert _resolve_xtquant_sys_path(str(sdk_root)) == sdk_root.parent


def test_resolve_rejects_missing_directory(tmp_path):
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(XTQuantNotFoundError, match="不存在或不是目录"):
        _resolve_xtquant_sys_path(str(nonexistent))


def test_resolve_rejects_random_directory_without_xtquant_marker(tmp_path):
    """防止用户把 ``C:\\Program Files\\Python311`` 之类的目录当成 xtquant。"""
    bogus = tmp_path / "not-xtquant"
    bogus.mkdir()
    (bogus / "random.txt").write_text("hi", encoding="utf-8")

    with pytest.raises(XTQuantNotFoundError, match="xtquant\\.py|xtquant/__init__.py"):
        _resolve_xtquant_sys_path(str(bogus))


def test_resolve_rejects_pkg_layout_without_xtdata(tmp_path):
    """存在 __init__.py 但缺 xtdata.py 的不完整 SDK 必须被拒。"""
    pkg_root = tmp_path / "xtquant"
    pkg = pkg_root / "xtquant"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    # 故意不放 xtdata.py

    with pytest.raises(XTQuantNotFoundError, match="缺.*xtdata\\.py"):
        _resolve_xtquant_sys_path(str(pkg_root))


def test_resolve_rejects_flat_layout_without_xtdata(tmp_path):
    """存在 xtquant.py 但缺 xtdata.py 的 flat SDK 必须被拒。"""
    flat_root = tmp_path / "xtquant"
    flat_root.mkdir()
    (flat_root / "xtquant.py").write_text("# stub", encoding="utf-8")
    (flat_root / "xttrader.py").write_text("# stub", encoding="utf-8")

    with pytest.raises(XTQuantNotFoundError, match="缺.*xtdata\\.py"):
        _resolve_xtquant_sys_path(str(flat_root))


def test_resolve_returns_none_when_path_is_none_or_empty():
    """空输入直接放过，返回 None——业务代码自己决定怎么报。"""
    assert _resolve_xtquant_sys_path(None) is None
    assert _resolve_xtquant_sys_path("") is None
    assert _resolve_xtquant_sys_path("   ") is None


def test_add_xtquant_path_injects_only_parent_for_pkg_layout(tmp_path):
    """add_xtquant_path 对 package 布局只把 parent 加进 sys.path。

    与 fix 的初衷一致：``import xtquant`` 必须通过 parent 才能找到 ``xtquant/`` 包。
    """
    sdk_root = _make_pkg_layout(tmp_path / "xtquant")
    parent = sdk_root.parent

    add_xtquant_path(xtquant_path=str(sdk_root), qmt_path=None)

    assert parent.as_posix() in sys.path


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
