#!/usr/bin/env python3
"""下载前端静态资源到 ``qmt_gateway/web/static/``。

CI 构建 NSIS 安装包前会运行本脚本，把 htmx 和 daisyui 打包进应用目录，
避免运行时从 unpkg/jsdelivr 拉取（Tracking Prevention 会拦截跨域
localStorage，导致 htmx 历史缓存失效）。

本脚本也可在本地手动执行：

    python installer/fetch-static-assets.py

依赖：仅标准库（urllib）。
"""
from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

# 仓库根目录（脚本在 installer/ 下，仓库根是父目录）
REPO_ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = REPO_ROOT / "qmt_gateway" / "web" / "static"

ASSETS: list[tuple[str, str]] = [
    (
        "https://unpkg.com/htmx.org@1.9.12/dist/htmx.min.js",
        "htmx.min.js",
    ),
    (
        "https://cdn.jsdelivr.net/npm/daisyui@4.12.10/dist/full.min.css",
        "daisyui.min.css",
    ),
]

USER_AGENT = "qmt-gateway-installer/1.0"


def _expected_sha256() -> dict[str, str] | None:
    """可选的校验和文件：``installer/static-assets.sha256``。

    每行 ``<sha256>  <filename>``，缺失文件时跳过校验。
    """
    sha_file = REPO_ROOT / "installer" / "static-assets.sha256"
    if not sha_file.exists():
        return None
    out: dict[str, str] = {}
    for line in sha_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            out[parts[1]] = parts[0]
    return out


def _download(url: str, dest: Path) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return data


def main() -> int:
    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    expected = _expected_sha256()

    failed = False
    for url, name in ASSETS:
        dest = STATIC_DIR / name
        try:
            data = _download(url, dest)
        except Exception as exc:
            print(f"[FAIL] {name}: {exc}", file=sys.stderr)
            failed = True
            continue

        sha = hashlib.sha256(data).hexdigest()
        size = len(data)
        print(f"[OK]   {name} ({size:,} bytes) sha256={sha[:12]}...")

        if expected is not None:
            want = expected.get(name)
            if want and want != sha:
                print(
                    f"[FAIL] {name}: sha256 mismatch (expected {want[:12]}..., got {sha[:12]}...)",
                    file=sys.stderr,
                )
                failed = True

    if failed:
        print("Some assets failed to download.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())