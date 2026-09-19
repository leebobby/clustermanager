#!/usr/bin/env python3
"""
生成应用图标 —— 方案 A「三平面」。

为什么自己写光栅化: 图标只由圆角矩形和圆两种形状组成, 用 4x4 超采样算覆盖率
就能得到干净的反锯齿边, 不值得为此让构建依赖 Pillow / cairosvg。
只用标准库(zlib + struct), 在任何 Python 3 上都跑得出来。

产物已入库, 平时不需要跑这个脚本; 改图标时:

    python tools/make_icon.py

写出:
    backend/app.ico              PyInstaller 的 exe 图标
    frontend/public/favicon.ico  浏览器 / WebView 标签页
    frontend/public/logo.svg     侧栏用矢量

.ico 里 <=64px 的帧用 32 位 BMP(兼容性最好), 128/256 用 PNG(不然一个文件
就要几百 KB)。
"""

import math
import os
import struct
import sys
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 图标几何 (64x64 画布, 与设计稿一致) ──────────────────────────────────────
BRAND = (0x24, 0x57, 0xD6)
GREEN = (0x3D, 0xD1, 0x7D)
WHITE = (0xFF, 0xFF, 0xFF)

CANVAS = 64.0

# 画的顺序就是叠的顺序
SHAPES = [
    # 底: 圆角方块
    ("rrect", (0, 0, 64, 64, 14), BRAND, 1.0),
    # 三条平面横杠, 越往下越淡
    ("rrect", (13, 16, 38, 6, 3), WHITE, 1.0),
    ("rrect", (13, 29, 38, 6, 3), WHITE, 0.82),
    ("rrect", (13, 42, 38, 6, 3), WHITE, 0.64),
    # 右下角健康徽章: 先用底色挖一个环, 再填绿
    ("circle", (50, 50, 11), BRAND, 1.0),
    ("circle", (50, 50, 8), GREEN, 1.0),
]

SUBSAMPLES = 4  # 每像素 4x4


def _inside_rrect(px, py, x, y, w, h, r):
    """圆角矩形 SDF: 取符号判定内外"""
    qx = abs(px - (x + w / 2.0)) - (w / 2.0 - r)
    qy = abs(py - (y + h / 2.0)) - (h / 2.0 - r)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return min(max(qx, qy), 0.0) + outside - r <= 0.0


def _inside_circle(px, py, cx, cy, r):
    return math.hypot(px - cx, py - cy) <= r


def _sample(px, py):
    """一个采样点的颜色 —— 按叠放顺序做 alpha 合成, 返回 (r, g, b, a) 0..1"""
    r = g = b = 0.0
    a = 0.0
    for kind, geom, color, alpha in SHAPES:
        hit = _inside_rrect(px, py, *geom) if kind == "rrect" else _inside_circle(px, py, *geom)
        if not hit:
            continue
        sr, sg, sb = (c / 255.0 for c in color)
        # source-over
        na = alpha + a * (1.0 - alpha)
        if na <= 0.0:
            continue
        r = (sr * alpha + r * a * (1.0 - alpha)) / na
        g = (sg * alpha + g * a * (1.0 - alpha)) / na
        b = (sb * alpha + b * a * (1.0 - alpha)) / na
        a = na
    return r, g, b, a


def render(size):
    """渲染成 size*size 的 RGBA 字节串(直通 alpha, 逐行从上到下)"""
    scale = CANVAS / size
    step = 1.0 / SUBSAMPLES
    offsets = [(i + 0.5) * step for i in range(SUBSAMPLES)]
    n = float(SUBSAMPLES * SUBSAMPLES)

    out = bytearray(size * size * 4)
    i = 0
    for row in range(size):
        for col in range(size):
            ar = ag = ab = aa = 0.0
            for oy in offsets:
                py = (row + oy) * scale
                for ox in offsets:
                    px = (col + ox) * scale
                    r, g, b, a = _sample(px, py)
                    # 先乘 alpha 再平均, 否则透明边缘会被不透明像素的颜色污染
                    ar += r * a
                    ag += g * a
                    ab += b * a
                    aa += a
            if aa > 0.0:
                out[i] = min(255, int(round(ar / aa * 255)))
                out[i + 1] = min(255, int(round(ag / aa * 255)))
                out[i + 2] = min(255, int(round(ab / aa * 255)))
                out[i + 3] = min(255, int(round(aa / n * 255)))
            i += 4
    return bytes(out)


# ── PNG ──────────────────────────────────────────────────────────────────────

def _chunk(tag, data):
    return (struct.pack(">I", len(data)) + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def png_bytes(size, rgba):
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    stride = size * 4
    raw = b"".join(b"\x00" + rgba[y * stride:(y + 1) * stride] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


# ── ICO ──────────────────────────────────────────────────────────────────────

def _bmp_frame(size, rgba):
    """ICO 里的 32 位 BMP 帧: BITMAPINFOHEADER + BGRA(自底向上) + 全零 AND 掩码"""
    header = struct.pack(
        "<IiiHHIIiiII",
        40,          # biSize
        size,        # biWidth
        size * 2,    # biHeight —— ICO 规定要算上 AND 掩码, 所以是两倍
        1,           # biPlanes
        32,          # biBitCount
        0, 0, 0, 0, 0, 0,
    )
    stride = size * 4
    rows = []
    for y in range(size - 1, -1, -1):
        row = rgba[y * stride:(y + 1) * stride]
        rows.append(b"".join(bytes((row[x + 2], row[x + 1], row[x], row[x + 3]))
                             for x in range(0, stride, 4)))
    mask_stride = ((size + 31) // 32) * 4
    return header + b"".join(rows) + b"\x00" * (mask_stride * size)


def ico_bytes(sizes):
    frames = []
    for size in sizes:
        rgba = render(size)
        # 大尺寸用 PNG, 否则单个 256 帧就 256KB
        frames.append((size, png_bytes(size, rgba) if size > 64 else _bmp_frame(size, rgba)))

    out = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries, blobs = [], []
    for size, blob in frames:
        entries.append(struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 256 在这个字段里记作 0
            0 if size >= 256 else size,
            0, 0, 1, 32, len(blob), offset,
        ))
        blobs.append(blob)
        offset += len(blob)
    return out + b"".join(entries) + b"".join(blobs)


# ── SVG ──────────────────────────────────────────────────────────────────────

LOGO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="集群运维">
  <rect width="64" height="64" rx="14" fill="#2457D6"/>
  <rect x="13" y="16" width="38" height="6" rx="3" fill="#FFFFFF"/>
  <rect x="13" y="29" width="38" height="6" rx="3" fill="#FFFFFF" opacity=".82"/>
  <rect x="13" y="42" width="38" height="6" rx="3" fill="#FFFFFF" opacity=".64"/>
  <circle cx="50" cy="50" r="11" fill="#2457D6"/>
  <circle cx="50" cy="50" r="8" fill="#3DD17D"/>
</svg>
"""


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    blob = ico_bytes(sizes)

    targets = [
        os.path.join(ROOT, "backend", "app.ico"),
        os.path.join(ROOT, "frontend", "public", "favicon.ico"),
    ]
    for path in targets:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(blob)
        print(f"  {os.path.relpath(path, ROOT)}  {len(blob):,} 字节  {len(sizes)} 个尺寸")

    svg_path = os.path.join(ROOT, "frontend", "public", "logo.svg")
    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(LOGO_SVG)
    print(f"  {os.path.relpath(svg_path, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
