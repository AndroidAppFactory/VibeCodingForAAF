"""截图封装 — Pillow ImageGrab

全屏抓取（含多显示器虚拟屏幕），在指定坐标绘制红色十字标记，存为 JPG。
支持指定窗口截图（通过进程名定位窗口区域）。
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageGrab


def capture_fullscreen(output_path, mark_pos: tuple = None) -> bool:
    """全屏截图，保存为 JPG（原分辨率）。

    Args:
        output_path: 输出文件路径（.jpg）
        mark_pos: 可选 (x, y) 屏幕虚拟坐标，在该位置绘制鼠标指示器

    Returns:
        True 成功，False 失败
    """
    try:
        img = ImageGrab.grab(all_screens=True)
    except Exception:
        # 旧版 Pillow 不支持 all_screens 参数，退化为主屏
        try:
            img = ImageGrab.grab()
        except Exception as e:
            print(f"    ⚠ 截图失败: {e}")
            return False

    if img.mode == "RGBA":
        img = img.convert("RGB")

    if mark_pos:
        gx, gy = int(mark_pos[0]), int(mark_pos[1])
        if 0 <= gx < img.width and 0 <= gy < img.height:
            _draw_crosshair(img, gx, gy)

    return _save_image(img, output_path)


def capture_window(proc_name: str, output_path, mark_pos: tuple = None) -> bool:
    """截取指定进程的窗口区域，保存为 JPG。

    找不到窗口时自动 fallback 到全屏截图。

    Args:
        proc_name: 进程名（如 "YOUKU.exe"）
        output_path: 输出文件路径
        mark_pos: 可选 (x, y) 屏幕绝对坐标

    Returns:
        True 成功，False 失败
    """
    from bridge.window import find_window_by_process, get_window_rect

    hwnd, title = find_window_by_process(proc_name)
    if not hwnd:
        # 窗口未找到，fallback 全屏
        print(f"    ⚠ 窗口截图 fallback 全屏：找不到进程 {proc_name} 的窗口")
        return capture_fullscreen(output_path, mark_pos)

    rect = get_window_rect(hwnd)
    if not rect:
        print(f"    ⚠ 窗口截图 fallback 全屏：获取窗口区域失败 ({proc_name})")
        return capture_fullscreen(output_path, mark_pos)

    left, top, right, bottom = rect
    # 窗口尺寸异常时 fallback
    if right - left < 10 or bottom - top < 10:
        print(f"    ⚠ 窗口截图 fallback 全屏：窗口尺寸异常 {rect} ({proc_name})")
        return capture_fullscreen(output_path, mark_pos)

    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    except Exception:
        return capture_fullscreen(output_path, mark_pos)

    if img.mode == "RGBA":
        img = img.convert("RGB")

    # mark_pos 转换为窗口内相对坐标
    if mark_pos:
        gx = int(mark_pos[0]) - left
        gy = int(mark_pos[1]) - top
        if 0 <= gx < img.width and 0 <= gy < img.height:
            _draw_crosshair(img, gx, gy)

    return _save_image(img, output_path)


def capture_all_windows(exe_dir: str, output_path, mark_pos: tuple = None) -> bool:
    """截取指定目录下所有进程窗口的合并区域（多窗口同框），保存为 JPG。

    找不到窗口时自动 fallback 到全屏截图。

    Args:
        exe_dir: exe 所在目录
        output_path: 输出文件路径
        mark_pos: 可选 (x, y) 屏幕绝对坐标

    Returns:
        True 成功，False 失败
    """
    from bridge.window import find_all_windows_by_dir, get_window_rect

    windows = find_all_windows_by_dir(exe_dir)
    if not windows:
        print(f"    ⚠ 窗口截图 fallback 全屏：目录 {exe_dir} 下无可见窗口")
        return capture_fullscreen(output_path, mark_pos)

    # 计算所有窗口的合并边界
    left = right = top = bottom = None
    for hwnd, title, pid, pname in windows:
        rect = get_window_rect(hwnd)
        if not rect:
            continue
        l, t, r, b = rect
        if r - l < 10 or b - t < 10:
            continue
        if left is None:
            left, top, right, bottom = l, t, r, b
        else:
            left = min(left, l)
            top = min(top, t)
            right = max(right, r)
            bottom = max(bottom, b)

    if left is None:
        return capture_fullscreen(output_path, mark_pos)

    try:
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    except Exception:
        return capture_fullscreen(output_path, mark_pos)

    if img.mode == "RGBA":
        img = img.convert("RGB")

    if mark_pos:
        gx = int(mark_pos[0]) - left
        gy = int(mark_pos[1]) - top
        if 0 <= gx < img.width and 0 <= gy < img.height:
            _draw_crosshair(img, gx, gy)

    return _save_image(img, output_path)


def _save_image(img: Image.Image, output_path) -> bool:
    """按文件扩展名决定保存格式（.png → PNG，其余 → JPEG），消除文件名与内容不一致。"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = "PNG" if output_path.suffix.lower() == ".png" else "JPEG"
    try:
        if fmt == "PNG":
            img.save(str(output_path), format="PNG")
        else:
            img.save(str(output_path), format="JPEG", quality=85)
    except Exception as e:
        print(f"    ⚠ 截图保存失败: {e}")
        return False
    return True


def get_screen_size() -> tuple[int, int]:
    """获取虚拟屏幕总尺寸 (width, height)，与 all_screens 截图坐标基准一致。"""
    import ctypes
    user32 = ctypes.windll.user32
    w = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    h = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if not w or not h:
        return ImageGrab.grab(all_screens=True).size
    return int(w), int(h)


def _draw_crosshair(img: Image.Image, x: int, y: int):
    """在图片上绘制红色十字标记"""
    draw = ImageDraw.Draw(img)
    r = 15
    draw.ellipse([x - r, y - r, x + r, y + r], outline="#ff4444", width=3)
    draw.line([x - r - 5, y, x + r + 5, y], fill="#ff4444", width=2)
    draw.line([x, y - r - 5, x, y + r + 5], fill="#ff4444", width=2)
