"""ADB 操作回放 — 核心业务逻辑

从 data.json 读取操作序列，通过 adb shell input 命令依次执行。
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 加载环境变量（~/.zixiekit/scripts/bootstrap.py 由 zk init / zk instance update 部署）
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
from bootstrap import load_env  # noqa: E402

load_env()
from pathlib import Path
from typing import Optional

import adb_tools  # noqa: E402


def _take_screenshot_retry(adb: list[str], path: str, max_retries: int = 2, delay: float = 0.5) -> bool:
    """截图并重试，失败时打印警告"""
    for attempt in range(max_retries):
        if adb_tools.take_screenshot(adb, path):
            return True
        if attempt < max_retries - 1:
            time.sleep(delay)
    print(f"    ⚠ 截屏失败（重试 {max_retries} 次）: {Path(path).name}", file=sys.stderr)
    return False


def _adb_log(msg: str = "") -> None:
    """ADB 统一日志，带毫秒时间戳前缀"""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"  [{ts}] {msg}")


def execute_event(event: dict, adb: list[str],
                  src_res: tuple[int, int],
                  dst_res: tuple[int, int],
                  speed: float,
                  screenshot_dir: Optional[Path] = None,
                  event_index: int = 0,
                  total_events: int = 0,
                  device: Optional[str] = None,
                  rotation: int = 0) -> dict:
    """执行单个事件，返回截屏/录屏信息

    Args:
        rotation: 当前屏幕旋转角度（0/90/180/270）。
                  坐标事件（tap/multitap/swipe）在 scale_coords 等比缩放后，
                  再按此旋转角映射为 input tap 使用的逻辑显示坐标。
    """
    step_prefix = f"[{event_index + 1}/{total_events}]" if total_events > 0 else ""

    # tips 类型不需要 ADB，跳过检查
    if event.get("type") != "tips":
        if not adb_tools.ensure_adb_ready(device, verbose=True):
            raise RuntimeError(f"事件 {event_index + 1} 执行前 ADB 连接不可用，已重试多次仍失败")

    captures = {}
    capture_mode = event.get("capture_mode", "screenshot")
    record_proc = None
    device_video_path = f"/sdcard/adb_replay_video_{event_index:03d}.mp4"

    delay_before = event.get("delay_before_ms", event.get("delay_ms", 0))

    if capture_mode == "none":
        # 跳过采集：只等待前延迟，不截屏不录屏
        if delay_before > 0 and speed > 0:
            time.sleep(delay_before / 1000.0 / speed)
    elif capture_mode == "video" and screenshot_dir:
        before_video_path = str(screenshot_dir / f"event_{event_index:03d}_0_before.mp4")
        record_time = min(int((delay_before / 1000.0 / speed) + 10), 30) if delay_before > 0 else 10
        record_proc = adb_tools.start_screenrecord(adb, device_video_path, time_limit=record_time)
        _adb_log(f"🎬 录屏(前)开始: event_{event_index:03d}_0_before.mp4")
        if delay_before > 0 and speed > 0:
            time.sleep(delay_before / 1000.0 / speed)
        if adb_tools.stop_screenrecord(adb, record_proc, device_video_path, before_video_path):
            captures["before_type"] = "video"
            _adb_log(f"🎬 录屏(前)完成: event_{event_index:03d}_0_before.mp4")
        record_proc = None
    else:
        if delay_before > 0 and speed > 0:
            time.sleep(delay_before / 1000.0 / speed)
        if screenshot_dir:
            before_path = str(screenshot_dir / f"event_{event_index:03d}_0_before.png")
            if _take_screenshot_retry(adb, before_path):
                captures["before_type"] = "screenshot"
                _adb_log(f"📸 截屏(前): event_{event_index:03d}_0_before.png")

    ev_type = event["type"]

    _adb_log(f"⏱ 前={delay_before/1000:.1f}s 后={event.get('delay_after_ms', 0)/1000:.1f}s")

    if ev_type == "tap":
        x, y = adb_tools.scale_coords(event["x"], event["y"], src_res, dst_res)
        x, y = adb_tools.rotate_coords_to_display(x, y, dst_res, rotation)
        subprocess.run(adb + ["shell", "input", "tap", str(x), str(y)], capture_output=True, timeout=10)
        _adb_log(f"{step_prefix} ▶ adb shell input tap {x} {y}")

    elif ev_type == "multitap":
        x, y = adb_tools.scale_coords(event["x"], event["y"], src_res, dst_res)
        x, y = adb_tools.rotate_coords_to_display(x, y, dst_res, rotation)
        count = max(1, int(event.get("count", 2)))
        for _ in range(count):
            subprocess.run(adb + ["shell", "input", "tap", str(x), str(y)], capture_output=True, timeout=10)
            time.sleep(0.1)
        _adb_log(f"{step_prefix} ▶ adb shell input tap {x} {y} ×{count}（连续点击，间隔 100ms）")

    elif ev_type == "swipe":
        x1, y1 = adb_tools.scale_coords(event["x1"], event["y1"], src_res, dst_res)
        x1, y1 = adb_tools.rotate_coords_to_display(x1, y1, dst_res, rotation)
        x2, y2 = adb_tools.scale_coords(event["x2"], event["y2"], src_res, dst_res)
        x2, y2 = adb_tools.rotate_coords_to_display(x2, y2, dst_res, rotation)
        duration = event.get("duration_ms", 300)
        subprocess.run(adb + ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], capture_output=True, timeout=10)
        _adb_log(f"{step_prefix} ▶ adb shell input swipe {x1} {y1} {x2} {y2} {duration}")

    elif ev_type == "keyevent":
        code = event["code"]
        subprocess.run(adb + ["shell", "input", "keyevent", str(code)], capture_output=True, timeout=10)
        _adb_log(f"{step_prefix} ▶ adb shell input keyevent {code}")

    elif ev_type == "text":
        content = event["content"]
        ZIXIE_IME = "com.bihe0832.adb.input/com.bihe0832.android.base.adb.input.ZixieIME"
        result = subprocess.run(adb + ["shell", "settings", "get", "secure", "default_input_method"], capture_output=True, text=True, timeout=5)
        current_ime = result.stdout.strip()
        if current_ime != ZIXIE_IME:
            subprocess.run(adb + ["shell", "ime", "set", ZIXIE_IME], capture_output=True, text=True, timeout=5)
            time.sleep(2)
        has_special = any(c in content for c in ['"', "'", '\\', '$', '`', '!', '(', ')', '&', '|', ';', '<', '>', ' '])
        if not has_special:
            subprocess.run(adb + ["shell", "am", "broadcast", "-a", "ZIXIE_ADB_INPUT_TEXT", "--es", "msg", content], capture_output=True, text=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell am broadcast -a ZIXIE_ADB_INPUT_TEXT --es msg \"{content}\"")
        else:
            encoded = base64.b64encode(content.encode('utf-8')).decode('ascii')
            subprocess.run(adb + ["shell", "am", "broadcast", "-a", "ZIXIE_ADB_INPUT_BASE64", "--es", "msg", encoded], capture_output=True, text=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell am broadcast -a ZIXIE_ADB_INPUT_BASE64 --es msg \"{encoded}\"")

    elif ev_type == "adb":
        action = event.get("action", "")
        package = event.get("package", "")
        if action == "force-stop":
            subprocess.run(adb + ["shell", "am", "force-stop", package], capture_output=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell am force-stop {package}")
        elif action == "clear":
            subprocess.run(adb + ["shell", "pm", "clear", package], capture_output=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell pm clear {package}")
        elif action == "restart":
            subprocess.run(adb + ["shell", "am", "force-stop", package], capture_output=True, timeout=10)
            subprocess.run(adb + ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell am force-stop {package} && adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        elif action == "launch":
            subprocess.run(adb + ["shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], capture_output=True, timeout=10)
            _adb_log(f"{step_prefix} ▶ adb shell monkey -p {package} -c android.intent.category.LAUNCHER 1")
        elif action == "clear-all":
            result = subprocess.run(adb + ["shell", "pm", "list", "packages", "-3"], capture_output=True, text=True, timeout=10)
            packages = []
            for line in result.stdout.strip().splitlines():
                line = line.strip()
                if line.startswith("package:"):
                    packages.append(line[len("package:"):])
            stopped = 0
            for pkg in packages:
                try:
                    subprocess.run(adb + ["shell", "am", "force-stop", pkg], capture_output=True, timeout=5)
                    stopped += 1
                except subprocess.TimeoutExpired:
                    pass
            _adb_log(f"{step_prefix} ▶ adb clear-all: 已清理 {stopped}/{len(packages)} 个后台应用")
        elif action == "lock-screen":
            result = subprocess.run(adb + ["shell", "dumpsys", "deviceidle"], capture_output=True, text=True, timeout=10)
            screen_on = "mScreenOn=true" in result.stdout
            if screen_on:
                subprocess.run(adb + ["shell", "input", "keyevent", "26"], capture_output=True, timeout=10)
                _adb_log(f"{step_prefix} ▶ adb 锁屏（屏幕已亮 → 锁定）")
            else:
                _adb_log(f"{step_prefix} ▶ adb 锁屏（屏幕已灭 → 跳过）")
        elif action == "wifi-connect":
            ssid = event.get("ssid", "")
            password = event.get("password", "")
            security = event.get("security", "wpa2")
            if not ssid or not password:
                _adb_log("⚠ 缺少 SSID 或密码")
            else:
                subprocess.run(adb + ["shell", "cmd", "wifi", "connect-network", ssid, security, password], capture_output=True, timeout=15)
                _adb_log(f"{step_prefix} ▶ adb shell cmd wifi connect-network {ssid} {security} {password}")
        elif action == "open-schema":
            uri = event.get("content", "")
            if uri:
                # 强制 NEW_TASK | CLEAR_TOP（0x14000000）：确保目标 Activity 重建，
                # 绕过 singleTop/singleTask 走 onNewIntent 导致页面不刷新 url 的问题
                subprocess.run(adb + ["shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", uri, "-f", "0x14000000"], capture_output=True, timeout=10)
                _adb_log(f"{step_prefix} ▶ adb shell am start -a android.intent.action.VIEW -d {uri} -f 0x14000000")
            else:
                _adb_log("⚠ open-schema 缺少 URI")
        elif action == "uninstall":
            subprocess.run(adb + ["uninstall", package], capture_output=True, text=True, timeout=30)
            _adb_log(f"{step_prefix} ▶ adb uninstall {package}")
        elif action == "install":
            from adb_core.config import INSTALL_DIR
            filename = event.get("content", "")
            if not filename:
                _adb_log("⚠ install 缺少文件名（content 字段）")
            else:
                if not filename.lower().endswith(".apk"):
                    filename = f"{filename}.apk"
                apk_path = INSTALL_DIR / filename
                if not apk_path.is_file():
                    _adb_log(f"⚠ APK 不存在: {apk_path}（请先放到 {INSTALL_DIR}）")
                else:
                    subprocess.run(adb + ["install", "-r", str(apk_path)], capture_output=True, text=True, timeout=120)
                    _adb_log(f"{step_prefix} ▶ adb install -r {apk_path}")
        else:
            _adb_log(f"⚠ 未知 adb 操作: {action}")

    elif ev_type == "tips":
        text = event.get("content", "")
        _adb_log(f"{step_prefix} 💡 {text}")
        input("     ↳ 按回车继续...")

    else:
        _adb_log(f"⚠ 未知事件类型: {ev_type}")

    delay_after = event.get("delay_after_ms", 0)

    if capture_mode == "none":
        # 跳过采集：只等待后延迟，不截屏不录屏
        if delay_after > 0 and speed > 0:
            time.sleep(delay_after / 1000.0 / speed)
    elif capture_mode == "video" and screenshot_dir:
        after_video_path = str(screenshot_dir / f"event_{event_index:03d}_1_after.mp4")
        device_video_after = f"/sdcard/adb_replay_video_{event_index:03d}_after.mp4"
        record_time = min(int((delay_after / 1000.0 / speed) + 5), 30) if delay_after > 0 else 5
        record_proc = adb_tools.start_screenrecord(adb, device_video_after, time_limit=record_time)
        _adb_log(f"🎬 录屏(后)开始: event_{event_index:03d}_1_after.mp4")
        if delay_after > 0 and speed > 0:
            time.sleep(delay_after / 1000.0 / speed)
        else:
            time.sleep(2.0)
        if adb_tools.stop_screenrecord(adb, record_proc, device_video_after, after_video_path):
            captures["after_type"] = "video"
            _adb_log(f"🎬 录屏(后)完成: event_{event_index:03d}_1_after.mp4")
    else:
        if delay_after > 0 and speed > 0:
            time.sleep(delay_after / 1000.0 / speed)
        if screenshot_dir:
            time.sleep(1.0)
            after_path = str(screenshot_dir / f"event_{event_index:03d}_1_after.png")
            if _take_screenshot_retry(adb, after_path):
                captures["after_type"] = "screenshot"
                _adb_log(f"📸 截屏(后): event_{event_index:03d}_1_after.png")

    return captures


def play(input_dir: str, speed: float = 1.0,
         device: Optional[str] = None, max_delay: Optional[float] = None,
         repeat: int = 1, screenshot: bool = False,
         screenshot_duration: float = 1) -> None:
    """执行回放"""
    record_dir = Path(input_dir).resolve()
    data_file = record_dir / "data.json"

    with open(data_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    src_res = tuple(data.get("resolution", [0, 0]))
    events = data.get("events", [])

    if max_delay and max_delay > 0:
        _cap_ms = max_delay * 1000
        events = [dict(ev) for ev in events]
        for _ev in events:
            for _k in ("delay_before_ms", "delay_after_ms"):
                if _ev.get(_k) and _ev[_k] > _cap_ms:
                    _ev[_k] = _cap_ms

    if not events:
        print("⚠️  录制文件中没有事件")
        return

    print(f"📱 录制设备: {data.get('device', 'unknown')}")
    print(f"   录制分辨率: {src_res[0]}x{src_res[1]}")
    print(f"   事件数: {len(events)}")
    print(f"   回放速度: {speed}x")
    print(f"   重复次数: {repeat}")
    if screenshot:
        print(f"   📸 截屏模式: 开启")

    adb = adb_tools.get_adb_cmd(device)

    dst_res = adb_tools.get_current_resolution(device)
    rotation = adb_tools.get_display_rotation(device)
    if dst_res[0] > 0:
        print(f"   当前分辨率: {dst_res[0]}x{dst_res[1]}")
        if rotation in (90, 270):
            adb_tools.print_rotation_check(device)
        if src_res != dst_res:
            print(f"   ⚠️  分辨率不同，将自动缩放坐标")
    else:
        dst_res = src_res
        rotation = 0

    screenshot_dir = None
    if screenshot:
        screenshot_dir = record_dir / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        print(f"   截屏目录: {screenshot_dir}")

    # 回放前确保 ADB 就绪
    print(f"\n🔍 检查 ADB 连接状态...")
    if not adb_tools.ensure_adb_ready(device, verbose=True):
        print("❌ ADB 连接不可用，无法开始回放", file=sys.stderr)
        return

    print(f"   ✅ ADB 连接正常")

    play_events = []

    for r in range(repeat):
        if repeat > 1:
            print(f"\n🔄 第 {r + 1}/{repeat} 轮")

        print(f"\n▶️  开始回放...\n")

        for i, event in enumerate(events):
            print(f"  ── 事件 #{i + 1}/{len(events)} ──")
            try:
                captures = execute_event(event, adb, src_res, dst_res, speed,
                                         screenshot_dir=screenshot_dir,
                                         event_index=i,
                                         total_events=len(events),
                                         device=device,
                                         rotation=rotation)
                ev_copy = dict(event)
                if captures:
                    ev_copy["screenshots"] = captures
                elif event.get("capture_mode") == "none":
                    ev_copy.pop("screenshots", None)
                play_events.append(ev_copy)
            except RuntimeError as e:
                print(f"  ❌ 事件 {i + 1} ADB 连接失败: {e}", file=sys.stderr)
                print(f"  ⏹️  回放中止（ADB 不可用，后续事件无法执行）", file=sys.stderr)
                play_events.append(dict(event))
                break
            except subprocess.TimeoutExpired:
                print(f"  ⚠️  事件 {i + 1} 执行超时，跳过")
                play_events.append(dict(event))
            except Exception as e:
                print(f"  ❌ 事件 {i + 1} 执行失败: {e}")
                play_events.append(dict(event))

    if screenshot and play_events:
        data["events"] = play_events
        with open(data_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n💾 已更新 data.json（含截屏路径）")

        from core.cli import generate_merge_video_script

        media_items = []
        for i, ev in enumerate(play_events):
            ss = ev.get("screenshots", {})
            for phase, slot in (("before", "0_before"), ("after", "1_after")):
                mtype = ss.get(f"{phase}_type", "")
                if not mtype:
                    continue
                ext = "mp4" if mtype == "video" else "png"
                path = f"screenshots/event_{i:03d}_{slot}.{ext}"
                full_path = str(record_dir / path)
                media_items.append((full_path, mtype == "video"))
        generate_merge_video_script(str(record_dir), media_items, screenshot_duration)

    print(f"\n✅ 回放完成")


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="adb-player", description="ADB 操作回放器 — 重放录制的操作序列")
    parser.add_argument("input", help="录制目录路径（包含 data.json）")
    parser.add_argument("--speed", type=float, default=1.0, help="回放速度倍率（默认 1.0，2.0 = 两倍速）")
    parser.add_argument("--device", "-s", help="指定设备序列号")
    parser.add_argument("--repeat", "-r", type=int, default=1, help="重复执行次数（默认 1）")
    parser.add_argument("--screenshot", action="store_true", help="每步操作前后截屏（保存到 screenshots/ 子目录）")
    parser.add_argument("--screenshot-duration", type=float, default=1, help="截图展示时长（秒，默认 1，仅截图模式生效）")

    args = parser.parse_args()

    if args.speed <= 0:
        print("❌ 速度必须大于 0", file=sys.stderr)
        return 1
    if args.repeat < 1:
        print("❌ 重复次数必须 >= 1", file=sys.stderr)
        return 1

    input_path = Path(args.input).resolve()
    if not input_path.is_dir():
        print(f"❌ 不是有效目录: {args.input}", file=sys.stderr)
        return 1
    if not (input_path / "data.json").exists():
        print(f"❌ 目录中没有 data.json: {args.input}", file=sys.stderr)
        return 1

    try:
        play(str(input_path), args.speed, args.device, args.repeat, args.screenshot, args.screenshot_duration)
    except FileNotFoundError as e:
        if "adb" in str(e):
            print("❌ 未找到 adb 命令，请确认已安装并加入 PATH", file=sys.stderr)
        else:
            print(f"❌ 文件不存在: {args.input}", file=sys.stderr)
        return 1
    except json.JSONDecodeError:
        print(f"❌ JSON 解析失败: {input_path / 'data.json'}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n⏹️  回放已中断")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
