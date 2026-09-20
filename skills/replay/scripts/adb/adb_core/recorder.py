"""ADB 操作录制 — 核心业务逻辑

通过 adb shell getevent 捕获触摸/按键事件，解析为结构化操作序列并保存为 JSON。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time as _time
from pathlib import Path

# 加载环境变量（~/.zixiekit/scripts/bootstrap.py 由 zk init / zk instance update 部署）
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
from bootstrap import load_env  # noqa: E402

load_env()
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from adb_tools import (  # noqa: E402
    get_adb_cmd, check_adb_connection, get_device_info,
    find_touch_device, get_touch_max, take_screenshot,
    get_display_rotation, print_rotation_check,
)


def _check_tracking_id(adb: list[str], event_dev: str, model: str) -> None:
    """检测设备是否支持 ABS_MT_TRACKING_ID（MT Protocol B）"""
    try:
        probe = subprocess.run(
            adb + ["shell", "getevent", "-p", event_dev],
            capture_output=True, text=True, timeout=5,
        )
        stdout = probe.stdout or ""
    except (subprocess.TimeoutExpired, OSError):
        stdout = ""

    device_supports_tracking_id = ("ABS_MT_TRACKING_ID" in stdout or "0039" in stdout)
    if not device_supports_tracking_id:
        print(f"\n❌ 不支持该设备的触摸协议（MT Protocol A）")
        print(f"   设备: {model}")
        sys.exit(1)

    print("   getevent 权限: ✅")


@dataclass
class TouchState:
    """跟踪当前触摸状态"""
    tracking_id: int = -1
    x: int = -1
    y: int = -1
    start_x: int = -1
    start_y: int = -1
    is_down: bool = False
    down_time: float = 0.0
    before_screenshot: Optional[str] = None

    def reset(self) -> None:
        self.x = -1
        self.y = -1
        self.start_x = -1
        self.start_y = -1
        self.is_down = False
        self.before_screenshot = None


@dataclass
class RecordSession:
    """录制会话"""
    device: str = ""
    resolution: tuple[int, int] = (0, 0)
    events: list[dict] = field(default_factory=list)
    last_event_time: float = 0.0
    screenshot_counter: int = 0


def take_event_screenshot(adb: list[str], output_dir: str, session: RecordSession, event_index: int, screenshot_type: str) -> Optional[str]:
    """为指定事件截图"""
    screenshots_dir = os.path.join(output_dir, "screenshots")
    os.makedirs(screenshots_dir, exist_ok=True)
    idx = str(event_index).zfill(3)
    suffix = "0_before" if screenshot_type == "before" else "1_after"
    screenshot_name = f"event_{idx}_{suffix}.png"
    screenshot_path = os.path.join(screenshots_dir, screenshot_name)
    if take_screenshot(adb, screenshot_path):
        session.screenshot_counter += 1
        return os.path.join("screenshots", screenshot_name)
    return None


def record(output_path: str, device: Optional[str] = None, verbose: bool = False, enable_screenshot: bool = False,
           on_event=None, stop_event=None) -> None:
    """执行录制"""
    print("🔍 检测设备信息...")

    if not check_adb_connection(device):
        print("❌ ADB 连接失败，请检查设备连接状态")
        sys.exit(1)

    model, physical_res = get_device_info(device)
    rotation = get_display_rotation(device)
    print(f"   设备: {model}")
    print(f"   物理分辨率: {physical_res[0]}x{physical_res[1]}")
    if rotation in (90, 270):
        print_rotation_check(device)

    event_dev = find_touch_device(device)
    print(f"   触摸设备: {event_dev}")

    max_x, max_y = get_touch_max(device, event_dev)
    print(f"   触摸范围: {max_x}x{max_y}")

    adb = get_adb_cmd(device)
    _check_tracking_id(adb, event_dev, model)

    if enable_screenshot:
        print("📸 截图功能: 已启用")

    # 坐标统一存「物理自然方向坐标」（evdev 按物理分辨率线性映射，不随旋转），
    # 分辨率字段也存物理自然方向（wm size），与历史 flow 数据语义一致；
    # 回放侧在 input tap 前再按当前屏幕旋转映射为逻辑显示坐标。
    session = RecordSession(device=model, resolution=physical_res)

    scale_x = physical_res[0] / max_x if max_x > 0 else 1.0
    scale_y = physical_res[1] / max_y if max_y > 0 else 1.0

    log_path = os.path.join(os.path.dirname(output_path), "data.log")
    log_file = open(log_path, "w", encoding="utf-8")
    log_file.write(f"# ADB 录制详细日志\n")
    log_file.write(f"# 设备: {model}\n")
    log_file.write(f"# 物理分辨率: {physical_res[0]}x{physical_res[1]}\n")
    log_file.write(f"# 屏幕旋转: {rotation}°\n")
    log_file.write(f"# 触摸设备: {event_dev}\n")
    log_file.write(f"# 触摸范围: {max_x}x{max_y}\n")
    log_file.write(f"# 缩放比例: x={scale_x:.4f}, y={scale_y:.4f}\n")
    log_file.write(f"# 截图功能: {'启用' if enable_screenshot else '禁用'}\n")
    log_file.write(f"#\n")

    print("\n🔴 开始录制（按 Ctrl+C 停止）...\n")

    touch = TouchState()

    def _start_getevent() -> subprocess.Popen:
        return subprocess.Popen(
            adb + ["shell", "getevent", "-lt", event_dev],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )

    proc = _start_getevent()

    _time.sleep(0.5)
    if proc.poll() is not None:
        stderr_out = proc.stderr.read() if proc.stderr else ""
        print(f"\n❌ getevent 进程异常退出！（退出码: {proc.returncode}）")
        if stderr_out.strip():
            print(f"   stderr: {stderr_out.strip()}")
        print(f"\n   录制命令: adb shell getevent -lt {event_dev}")
        print(f"   设备: {model}")
        log_file.close()
        sys.exit(1)

    EV_ABS_LABELS = {"EV_ABS", "0003"}
    EV_SYN_LABELS = {"EV_SYN", "0000"}
    EV_KEY_LABELS = {"EV_KEY", "0001"}
    TRACKING_ID_LABELS = {"ABS_MT_TRACKING_ID", "0039"}
    POSITION_X_LABELS = {"ABS_MT_POSITION_X", "0035"}
    POSITION_Y_LABELS = {"ABS_MT_POSITION_Y", "0036"}
    SYN_REPORT_LABELS = {"SYN_REPORT", "0000"}
    BTN_TOUCH_LABELS = {"BTN_TOUCH", "014a"}

    line_count = 0
    parsed_count = 0

    try:
        for line in proc.stdout:
            if stop_event and stop_event.is_set():
                break
            line = line.strip()
            if not line:
                continue
            line_count += 1
            log_file.write(f"{line}\n")
            if verbose:
                print(f"  [raw] {line}")

            m = re.match(r"\[\s*([\d.]+)\]\s+\S+:\s+(\S+)\s+(\S+)\s+(\w+)", line)
            if not m:
                m = re.match(r"\[\s*([\d.]+)\]\s+(\S+)\s+(\S+)\s+(\w+)", line)
                if not m:
                    continue

            parsed_count += 1
            timestamp = float(m.group(1))
            ev_type = m.group(2)
            ev_code = m.group(3)
            ev_value = m.group(4)

            def _finish_touch(ts: float) -> None:
                nonlocal touch
                if not touch.is_down:
                    return
                dx = abs(touch.x - touch.start_x)
                dy = abs(touch.y - touch.start_y)
                duration = ts - touch.down_time
                delay_ms = 0
                if session.last_event_time > 0:
                    delay_ms = int((touch.down_time - session.last_event_time) * 1000)
                delay_ms = max(0, delay_ms)

                sx = int(touch.start_x * scale_x)
                sy = int(touch.start_y * scale_y)
                ex = int(touch.x * scale_x)
                ey = int(touch.y * scale_y)

                after_screenshot = None
                if enable_screenshot:
                    after_screenshot = take_event_screenshot(adb, os.path.dirname(output_path), session, len(session.events), "after")

                if dx < 10 and dy < 10:
                    event = {
                        "type": "tap", "x": sx, "y": sy,
                        "delay_before_ms": delay_ms, "delay_after_ms": 0,
                    }
                    if touch.before_screenshot:
                        event["screenshots"] = {
                            "before": touch.before_screenshot,
                            "after": after_screenshot,
                        }
                    elif after_screenshot:
                        event["screenshots"] = {"after": after_screenshot}
                    session.events.append(event)
                    print(f"  ✓ tap({sx}, {sy}) +{delay_ms}ms")
                else:
                    dur_ms = int(duration * 1000)
                    event = {
                        "type": "swipe", "x1": sx, "y1": sy, "x2": ex, "y2": ey,
                        "duration_ms": dur_ms, "delay_before_ms": delay_ms, "delay_after_ms": 0,
                    }
                    if touch.before_screenshot:
                        event["screenshots"] = {
                            "before": touch.before_screenshot,
                            "after": after_screenshot,
                        }
                    elif after_screenshot:
                        event["screenshots"] = {"after": after_screenshot}
                    session.events.append(event)
                    print(f"  ✓ swipe({sx},{sy} → {ex},{ey}, {dur_ms}ms) +{delay_ms}ms")

                if after_screenshot:
                    print(f"    📸 操作后截图: {after_screenshot}")

                if on_event:
                    on_event(event)
                session.last_event_time = ts
                touch.is_down = False

            def _start_touch(ts: float, tracking_id: int = 0) -> None:
                nonlocal touch
                if touch.is_down:
                    return
                touch.reset()
                touch.tracking_id = tracking_id
                touch.is_down = True
                touch.down_time = ts
                _evt_idx = len(session.events) + 1
                print(f"  ── 事件 #{_evt_idx} ──")
                if enable_screenshot:
                    before_screenshot = take_event_screenshot(adb, os.path.dirname(output_path), session, len(session.events), "before")
                    if before_screenshot:
                        print(f"    📸 操作前截图: {before_screenshot}")
                    touch.before_screenshot = before_screenshot

            if ev_type in EV_ABS_LABELS:
                if ev_code in TRACKING_ID_LABELS:
                    val = int(ev_value, 16)
                    if val == 0xffffffff:
                        _finish_touch(timestamp)
                    else:
                        _start_touch(timestamp, val)
                elif ev_code in POSITION_X_LABELS:
                    touch.x = int(ev_value, 16)
                    if touch.is_down and touch.start_x < 0:
                        touch.start_x = touch.x
                elif ev_code in POSITION_Y_LABELS:
                    touch.y = int(ev_value, 16)
                    if touch.is_down and touch.start_y < 0:
                        touch.start_y = touch.y
            elif ev_type in EV_KEY_LABELS and ev_code in BTN_TOUCH_LABELS:
                pass
            elif ev_type in EV_SYN_LABELS and ev_code in SYN_REPORT_LABELS:
                if touch.is_down and touch.start_x < 0:
                    touch.start_x = touch.x
                    touch.start_y = touch.y

    except KeyboardInterrupt:
        print("\n⏹️  录制已中断，正在保存已录制数据...")
    finally:
        import signal
        try:
            signal.signal(signal.SIGINT, signal.SIG_IGN)
        except (KeyboardInterrupt, OSError):
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (Exception, KeyboardInterrupt):
            pass

    if line_count == 0:
        stderr_out = proc.stderr.read() if proc.stderr else ""
        print(f"\n⚠️  录制异常：getevent 未产生任何数据！")
        if stderr_out.strip():
            print(f"   stderr: {stderr_out.strip()}")
        print(f"   排查: 手动执行 adb shell getevent -lt {event_dev} 并触摸屏幕")

    print(f"\n⏹️  录制结束，共 {len(session.events)} 个事件")
    print(f"   原始行数: {line_count}，成功解析: {parsed_count}")
    if enable_screenshot:
        print(f"   截图数量: {session.screenshot_counter}")

    log_file.write(f"\n# --- 录制结束 ---\n")
    log_file.write(f"# 事件数: {len(session.events)}\n")
    log_file.write(f"# 原始行数: {line_count}，成功解析: {parsed_count}\n")
    if enable_screenshot:
        log_file.write(f"# 截图数量: {session.screenshot_counter}\n")
    log_file.close()

    output = {
        "device": session.device,
        "resolution": list(session.resolution),
        "rotation": rotation,
        "events": session.events,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💾 重放文件: {output_path}")
    print(f"📋 详细日志: {log_path}")
    if enable_screenshot:
        screenshots_dir = os.path.join(os.path.dirname(output_path), "screenshots")
        print(f"📸 截图目录: {screenshots_dir}")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="adb-recorder", description="ADB 操作录制器 — 录制手机触摸/按键操作为 JSON")
    parser.add_argument("output", help="输出 JSON 文件路径")
    parser.add_argument("--device", "-s", help="指定设备序列号")
    parser.add_argument("--verbose", "-v", action="store_true", help="打印原始 getevent 日志")
    parser.add_argument("--screenshot", "-ss", action="store_true", default=True, help="启用截图功能（默认开启）")
    parser.add_argument("--no-screenshot", dest="screenshot", action="store_false", help="禁用截图功能")

    args = parser.parse_args()

    try:
        record(args.output, args.device, args.verbose, args.screenshot)
    except subprocess.TimeoutExpired:
        print("❌ ADB 连接超时，请检查设备连接", file=sys.stderr)
        return 1
    except FileNotFoundError:
        print("❌ 未找到 adb 命令，请确认已安装并加入 PATH", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
