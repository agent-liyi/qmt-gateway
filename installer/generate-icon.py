"""生成 QMT Gateway 托盘图标 installer/qmt-gateway.ico。

设计：品牌红（#D13527）圆角矩形底 + 居中白色粗体"匡"字。
多尺寸（16/32/48/64/128/256），托盘在所有 DPI 下都不糊。

字体按系统优先级自动选择：
  1. 微软雅黑 Bold (msyhbd.ttc)
  2. 黑体 (simhei.ttf)
  3. Arial Bold（fallback）
  4. PIL 默认位图字体
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _try_load_font(size: int) -> ImageFont.ImageFont:
    # 系统常见中文字体，按优先级排序
    candidates = [
        "C:/Windows/Fonts/msyhbd.ttc",     # 微软雅黑 Bold
        "C:/Windows/Fonts/msyh.ttc",       # 微软雅黑
        "C:/Windows/Fonts/simhei.ttf",     # 黑体
        "C:/Windows/Fonts/simsun.ttc",     # 宋体
        "C:/Windows/Fonts/arialbd.ttf",    # Arial Bold (fallback)
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # Linux 文泉驿
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        "/System/Library/Fonts/PingFang.ttc",  # macOS
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _draw(size: int) -> Image.Image:
    """绘制单个尺寸的图标：红底白"匡"字。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角矩形背景——比例上略大于 OS 默认 tray icon 边界，
    # 避免在小尺寸时被裁剪
    margin = max(1, size // 16)
    radius = max(2, size // 8)
    draw.rounded_rectangle(
        [(margin, margin), (size - margin - 1, size - margin - 1)],
        radius=radius,
        fill=(209, 53, 39, 255),  # 品牌红 #D13527
    )

    # 字号大约占图标 60%，让字在 16x16 下也清晰
    font_size = max(8, int(size * 0.6))
    font = _try_load_font(font_size)

    # "匡" 字居中——textbbox 返回 (l, t, r, b)，需要把字形偏移算回去
    text = "匡"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    draw.text((x, y), text, fill=(255, 255, 255, 255), font=font)

    return img


def main() -> int:
    out = Path(__file__).resolve().parent / "qmt-gateway.ico"
    sizes = [16, 32, 48, 64, 128, 256]
    # PIL 的 ICO writer 在 append_images 模式下不可靠；
    # 改为先写单个 size，再追加剩余 size
    images = [_draw(s) for s in sizes]
    images[0].save(out, format="ICO", size=(sizes[0], sizes[0]))
    for img, sz in zip(images[1:], sizes[1:]):
        img.save(out, format="ICO", size=(sz, sz), append_sizes=True)
    print(f"wrote {out} ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())