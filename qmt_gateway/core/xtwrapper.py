"""xtquant 包装器模块

提供动态导入 xtquant 的功能，处理路径设置和错误处理。
"""

import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger


class XTQuantError(Exception):
    """xtquant 相关错误"""
    pass


class XTQuantNotFoundError(XTQuantError):
    """xtquant 模块未找到"""
    pass


class XTQuantImportError(XTQuantError):
    """xtquant 导入失败"""
    pass


# 缓存导入的模块
_xt_module: Any = None
_xtdata_module: Any = None


def _resolve_xtquant_sys_path(xtquant_path: str | Path | None) -> Path | None:
    """把用户填写的 xtquant 路径归一化，并返回应当加入 sys.path 的目录。

    支持两种目录布局（这是 xtquant SDK 在不同券商处的标准打包方式）：

    1. **package 布局**（官方推荐、当前 C:\\apps\\xtquant 的实际形态）::

           C:\\apps\\xtquant\\
               xtquant\\__init__.py
               xtquant\\xtdata.py
               xtquant\\xttrader.py
               ...

       用户填 ``C:\\apps\\xtquant``——我们要 import 的是 ``xtquant`` 包，
       所以把 ``C:\\apps``（``xtquant/`` 的父目录）加进 sys.path。

    2. **flat 布局**（少数券商 SDK 把所有模块直接摊开在根下）::

           C:\\apps\\xtquant\\
               xtquant.py
               xtdata.py
               xttrader.py
               ...

       用户填 ``C:\\apps\\xtquant``——``xtquant.py`` 就是一个普通模块，
       所以把 ``C:\\apps\\xtquant`` 自己加进 sys.path。

    两种布局都必须能在该目录或其子目录下找到 ``xtdata.py``——
    因为 ``XtQuantTrader`` 在 C 扩展初始化阶段依赖它。

    Args:
        xtquant_path: 用户填写的路径，允许为 None/空。

    Returns:
        应加入 ``sys.path`` 的目录。

    Raises:
        XTQuantNotFoundError: 路径不存在、或者两种布局都找不到关键的
            ``xtquant`` 标识文件（``xtquant.py`` 或 ``xtquant/__init__.py``
            至少有一个），或者找不到 ``xtdata.py``。
    """
    if not xtquant_path:
        return None
    raw = str(xtquant_path).strip()
    # 兜底兜空：''、'.'、'./'、'\\'、None、Path('.') 等都会被
    # ``config.get_expanded_path`` 或未初始化的 DB 字段翻译成 falsy。
    # 这种"未配置"状态允许被静默跳过——首次启动 wizard 之前不应该报错。
    if not raw or raw in {".", "./", ".\\", "\\"}:
        return None

    configured = Path(raw).expanduser().resolve()
    if not configured.exists() or not configured.is_dir():
        raise XTQuantNotFoundError(
            f"xtquant 路径不存在或不是目录: {configured}"
        )

    candidate_modules = configured / "xtquant"
    flat_module_py = configured / "xtquant.py"
    package_init_py = candidate_modules / "__init__.py"
    xtdata_py = configured / "xtdata.py"
    xtdata_py_inside_pkg = candidate_modules / "xtdata.py"

    has_flat_layout = flat_module_py.is_file()
    has_package_layout = package_init_py.is_file()
    has_xtdata = xtdata_py.is_file() or xtdata_py_inside_pkg.is_file()

    if not (has_flat_layout or has_package_layout):
        raise XTQuantNotFoundError(
            f"xtquant 路径不正确: {configured}\n"
            f"该目录下既找不到 xtquant.py，也找不到 xtquant/__init__.py。\n"
            f"请填写包含 xtquant SDK 的根目录（如 C:\\apps\\xtquant），"
            f"而不是它的子目录或其父目录。"
        )
    if not has_xtdata:
        raise XTQuantNotFoundError(
            f"xtquant 路径不完整: {configured}\n"
            f"找到了 xtquant {'包' if has_package_layout else '模块'}，但缺少 xtdata.py——"
            f"请确认 SDK 文件齐全。"
        )

    sys_path_entry = configured.parent if has_package_layout else configured
    logger.info(
        "xtquant 路径验证通过: configured={}, 布局={}, sys.path 条目={}",
        configured,
        "package (xtquant/__init__.py)" if has_package_layout else "flat (xtquant.py)",
        sys_path_entry,
    )
    return sys_path_entry


def add_xtquant_path(xtquant_path: str | None = None, qmt_path: str | None = None) -> None:
    """添加 xtquant 路径到 sys.path

    Args:
        xtquant_path: xtquant 库的路径（必填"包含 xtquant SDK 的根目录"）。
        qmt_path: QMT 安装路径（作为备选 DLL 搜索目录）。

    Raises:
        XTQuantNotFoundError: ``xtquant_path`` 非空但校验失败。
    """
    logger.info(f"add_xtquant_path 被调用: xtquant_path={xtquant_path}, qmt_path={qmt_path}")

    paths_to_try: list[Path] = []

    if xtquant_path:
        sys_path_entry = _resolve_xtquant_sys_path(xtquant_path)
        if sys_path_entry is not None:
            paths_to_try.append(sys_path_entry)

    if qmt_path:
        # 注意：qmt_path 绝对不能加到 sys.path——QMT 根目录下有 resource /
        # bin.x64 / bin 等子目录，Python 会把它们当成 namespace package，
        # 导致标准库 `import resource` 拿到空壳模块（Windows 上不存在），
        # apsw.ext 的 `resource.getrusage` 触发 AttributeError，整个
        # gateway 启动失败。qmt_path 只用于 os.add_dll_directory 加载
        # xtquant 的 C 扩展需要的 DLL，不需要进 sys.path。
        qmt_path_expanded = Path(qmt_path).expanduser().resolve()
        logger.info(f"处理 qmt_path: {qmt_path} -> {qmt_path_expanded}, exists={qmt_path_expanded.exists()}")

    logger.info(f"准备添加的路径列表: {paths_to_try}")
    
    for path in paths_to_try:
        # Windows 上使用正斜杠避免转义问题
        path_str = path.as_posix() if hasattr(path, 'as_posix') else str(path).replace("\\", "/")
        # 如果路径已存在，先移除再添加到最前面，确保优先级
        if path_str in sys.path:
            sys.path.remove(path_str)
        sys.path.insert(0, path_str)
        logger.info(f"已添加 xtquant 路径: {path_str}")

    # Windows 下添加 DLL 目录
    if os.name == "nt" and qmt_path:
        try:
            # 使用已处理的路径
            if qmt_path_expanded.exists() and str(qmt_path_expanded) != ".":
                os.add_dll_directory(str(qmt_path_expanded))
                logger.info(f"已添加 DLL 目录: {qmt_path_expanded}")
            elif str(qmt_path_expanded) == ".":
                logger.debug(f"跳过当前目录的 DLL 添加: {qmt_path_expanded}")
        except Exception as e:
            logger.debug(f"添加 DLL 目录失败（非关键错误）: {e}")


def require_xt(xtquant_path: str | None = None, qmt_path: str | None = None) -> Any:
    """获取 xtquant.xttrader 模块

    动态导入 xttrader，如果失败则抛出异常。

    Args:
        xtquant_path: xtquant 库的路径
        qmt_path: QMT 安装路径

    Returns:
        xtquant.xttrader 模块

    Raises:
        XTQuantNotFoundError: 如果 xtquant 未找到
        XTQuantImportError: 如果导入失败
    """
    global _xt_module

    if _xt_module is not None:
        return _xt_module

    # 添加路径
    add_xtquant_path(xtquant_path, qmt_path)

    try:
        import xtquant.xttrader as xt
        _xt_module = xt
        logger.info("xtquant.xttrader 模块导入成功")
        return xt
    except ImportError as e:
        raise XTQuantNotFoundError(
            f"无法导入 xtquant.xttrader 模块。请确保 xtquant 路径正确配置。错误: {e}"
        )


def require_xtdata(xtquant_path: str | None = None, qmt_path: str | None = None) -> Any:
    """获取 xtquant.xtdata 模块

    动态导入 xtdata，如果失败则抛出异常。

    Args:
        xtquant_path: xtquant 库的路径
        qmt_path: QMT 安装路径

    Returns:
        xtquant.xtdata 模块

    Raises:
        XTQuantNotFoundError: 如果 xtdata 未找到
    """
    global _xtdata_module

    if _xtdata_module is not None:
        return _xtdata_module

    # 添加路径
    add_xtquant_path(xtquant_path, qmt_path)

    try:
        import xtquant.xtdata as xtdata
        _xtdata_module = xtdata
        logger.info("xtquant.xtdata 模块导入成功")
        return xtdata
    except ImportError as e:
        raise XTQuantNotFoundError(
            f"无法导入 xtquant.xtdata 模块。请确保 xtquant 路径正确配置。错误: {e}"
        )


def clear_xt_cache() -> None:
    """清除 xtquant 模块缓存

    用于重新配置路径后重新导入。
    """
    global _xt_module, _xtdata_module
    _xt_module = None
    _xtdata_module = None

    # 从 sys.modules 中移除
    modules_to_remove = [
        "xtquant",
        "xtquant.xt",
        "xtquant.xtdata",
    ]
    for mod in modules_to_remove:
        if mod in sys.modules:
            del sys.modules[mod]
            logger.debug(f"已移除缓存的模块: {mod}")


def is_xt_available() -> bool:
    """检查 xtquant 是否可用"""
    try:
        require_xtdata()
        return True
    except XTQuantError:
        return False
