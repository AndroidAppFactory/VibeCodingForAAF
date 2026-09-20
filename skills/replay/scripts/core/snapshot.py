#!/usr/bin/env python3
"""公共关键事件截图拼接模块

三端（adb/web/win）共用的拼图渲染逻辑。各端只需组装 cards 列表和 info_text，
调用 render_critical_snapshot() 即可生成统一样式的汇总图。
"""

from __future__ import annotations

import socket
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# ─── 常量 ────────────────────────────────────────────────────────────────────

SNAPSHOT_COLORS = ["#4fc3f7", "#66bb6a", "#ffa726", "#ef5350", "#ab47bc", "#26c6da"]


# ─── 工具函数 ─────────────────────────────────────────────────────────────────


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def snapshot_font(size: int, bold: bool = False):
    """跨平台中文字体加载"""
    from PIL import ImageFont
    candidates: list[str] = []
    if bold:
        candidates = [
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "C:/Windows/Fonts/msyhbd.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/simhei.ttf",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/noto/NotoSansCJK-Bold.ttc",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/PingFang.ttc",
            "C:/Windows/Fonts/msyh.ttc",
            "C:/Windows/Fonts/msyhl.ttc",
            "C:/Windows/Fonts/simsun.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/noto/NotoSansCJK-Regular.ttc",
        ]
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                continue
    return ImageFont.load_default()


def get_local_hostname() -> str:
    """获取本机名，去除 .local 后缀"""
    host = socket.gethostname()
    if host.endswith(".local"):
        host = host[: -len(".local")]
    return host


def format_started_at(summary: dict) -> str:
    raw = summary.get("started_at", "")
    try:
        return datetime.fromisoformat(raw).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return raw or "-"


def wrap_text(draw, text: str, font, max_width: int, max_lines: int = 2) -> list[str]:
    """按字符宽度换行，超过 max_lines 时截断"""
    lines: list[str] = []
    cur = ""
    for ch in text:
        test = cur + ch
        if cur and draw.textlength(test, font=font) > max_width:
            lines.append(cur)
            cur = ch
            if len(lines) >= max_lines:
                break
        else:
            cur = test
    if cur and len(lines) < max_lines:
        lines.append(cur)
    return lines[:max_lines]


# ─── 公共拼图函数 ─────────────────────────────────────────────────────────────


def render_critical_snapshot(
    cards: list[dict],
    info_text: str,
    out_path: Path,
    max_cols: int = 4,
    max_card_width: int = 0,
    rotate_landscape: bool = True,
) -> Optional[Path]:
    """将 cards 列表渲染为统一样式的关键事件拼图。

    Args:
        cards: [{"title": str, "image": Path}, ...]，已筛选好的关键截图
        info_text: 顶部信息栏文案（如 "执行时间：... 执行机器：..."）
        out_path: 输出 PNG 路径
        max_cols: 最大列数，默认 4
        max_card_width: 单卡片最大宽度（像素），0=不限制。多平台合并时建议 1600
        rotate_landscape: 是否把横图（宽>高）旋转 90° 统一为竖图。
            adb（手机）默认 True——手机竖屏截图不转，只把横屏视频转正；
            web/win（浏览器/桌面）截图天生横向，应传 False 保持原方向。

    Returns:
        成功返回 out_path，cards 为空返回 None
    """
    if not cards:
        return None

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None

    PAD = 20
    GAP = 16
    COLS = min(max_cols, len(cards))
    BG = (10, 10, 26)
    TITLE_COLOR = (79, 195, 247)

    # rotate_landscape：仅 adb 手机截图需要——把横屏视频（宽>高）转正为竖屏，
    # 使方向更协调；web/win 截图天生横向，传 False 保持原方向（否则网页侧躺）。
    thumbs = []
    for c in cards:
        img = Image.open(c["image"]).convert("RGB")
        if rotate_landscape and img.width > img.height:
            img = img.transpose(Image.ROTATE_270)
        thumbs.append(img)

    # 统一高度对齐（关键）：横竖屏混排（如 mixed 的 adb 竖屏 + web 横屏）时，
    # 若按统一列宽缩放，竖图会被放大到横图宽度导致高度暴增而被截断。
    # 改为「所有图缩放到统一高度、宽度各异」——横竖都不截断，视觉协调。
    # 统一高度取所有图原始高度的最小值（避免放大失真），并设上限防画布过大。
    target_h = min(t.height for t in thumbs)
    target_h = min(target_h, 2400)
    # 若限制了单卡片最大宽度，换算为对应高度上限（保证最宽的图不超过 max_card_width）
    if max_card_width:
        widest_ratio = max(t.width / t.height for t in thumbs)  # 宽高比最大 = 最宽的图
        if target_h * widest_ratio > max_card_width:
            target_h = int(max_card_width / widest_ratio)
    thumbs = [
        t.resize((max(1, int(t.width * target_h / t.height)), target_h), Image.LANCZOS)
        for t in thumbs
    ]
    thumb_ws = [t.width for t in thumbs]

    # 行分组（每行 COLS 张）：每行宽度 = 该行各图宽之和 + gap，画布宽取最大行宽
    rows = (len(cards) + COLS - 1) // COLS
    row_widths = []
    for r in range(rows):
        seg = thumb_ws[r * COLS:(r + 1) * COLS]
        row_widths.append(sum(seg) + GAP * (len(seg) - 1))
    body_w = max(row_widths)
    canvas_w = PAD * 2 + body_w

    # 字体按「实际画布宽」等比放大：notify 会把整图等比压缩到约 1000 宽，
    # 压缩后字号 = 原字号 × target/canvas_w，故字号需占画布宽足够比例才清晰。
    header_size = max(24, min(canvas_w // 50, 150))
    info_size = max(30, min(canvas_w // 44, 170))
    header_font = snapshot_font(header_size, bold=True)
    info_font = snapshot_font(info_size, bold=True)

    probe = Image.new("RGB", (10, 10))
    probe_draw = ImageDraw.Draw(probe)
    header_lines_list = [
        wrap_text(probe_draw, c["title"], header_font, max(40, thumb_ws[i] - 16))
        for i, c in enumerate(cards)
    ]
    max_lines = max(len(lines) for lines in header_lines_list)
    line_h = header_font.size + 6
    HEADER_H = max(40, line_h * max_lines + 14)

    card_h = target_h + HEADER_H
    # 标题栏高度自适应 info 字号，避免大字号溢出与首行卡片重合
    title_h = max(64, info_size + 24)

    canvas_h = title_h + PAD * 2 + rows * card_h + (rows - 1) * GAP

    canvas = Image.new("RGB", (canvas_w, canvas_h), BG)
    draw = ImageDraw.Draw(canvas)
    draw.text((PAD, (title_h - info_font.size) // 2), info_text, font=info_font, fill=TITLE_COLOR)

    # 按 group 分配颜色：同一个 group（如同一 flow 的同一 sub_index）同色
    group_colors: dict = {}
    color_idx = 0
    for i, (card, thumb, header_lines) in enumerate(zip(cards, thumbs, header_lines_list)):
        row, col = divmod(i, COLS)
        cw = thumb.width
        # 行内 x 累加（各图宽度不同）
        x = PAD + sum(thumb_ws[row * COLS:row * COLS + col]) + GAP * col
        y = title_h + PAD + row * (card_h + GAP)
        group = card.get("group", i)
        if group not in group_colors:
            group_colors[group] = SNAPSHOT_COLORS[color_idx % len(SNAPSHOT_COLORS)]
            color_idx += 1
        color = hex_to_rgb(group_colors[group])

        draw.rounded_rectangle([x - 3, y - 3, x + cw + 3, y + card_h + 3], radius=10, outline=color, width=3)
        draw.rectangle([x, y, x + cw, y + HEADER_H], fill=color)

        ty = y + (HEADER_H - line_h * len(header_lines)) // 2
        for line in header_lines:
            tw = draw.textlength(line, font=header_font)
            draw.text((x + (cw - tw) / 2, ty), line, font=header_font, fill=(255, 255, 255))
            ty += line_h

        canvas.paste(thumb, (x, y + HEADER_H))

    canvas.save(str(out_path), format="PNG", optimize=True)
    print(f"  快照已保存: {out_path} ({out_path.stat().st_size / 1024 / 1024:.1f}MB)", file=sys.stderr)
    return out_path
