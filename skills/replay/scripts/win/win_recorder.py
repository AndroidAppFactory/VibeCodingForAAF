#!/usr/bin/env python3
"""Windows 桌面操作录制引擎

通过 pynput 监听鼠标/键盘事件，状态机推断高层语义事件（click/type/scroll/drag/...），
坐标定位，同步截图，输出 events.json + raw.log。
"""

from __future__ import annotations

import atexit
import sys

# DPI 感知必须在 pynput 导入前设置
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per Monitor
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import json
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# 将 scripts/ 目录加入 import 路径
_scripts_dir = Path(__file__).resolve().parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

from pynput import mouse as p_mouse, keyboard as p_keyboard

from bridge.screenshot import capture_fullscreen, get_screen_size
from flowcore.config import RECORDINGS_DIR

# 拖拽触发的最小像素移动
DRAG_THRESHOLD_PX = 5.0
# 双击最大间隔（秒）
DOUBLE_CLICK_INTERVAL = 0.3
# 文本输入空闲超时（毫秒）：超过该间隔没有新字符则 flush 为 type 事件
TYPING_IDLE_MS = 600


class WinRecorder:
    """Windows 桌面操作录制器。"""

    def __init__(self):
        self._stop_event = threading.Event()
        self._events = []          # 语义事件列表
        self._raw_buffer = []      # 原始事件缓冲（延迟写盘）
        self._raw_log = None       # raw.log 文件句柄
        self._output_dir = None
        self._screenshots_dir = None

        # 状态机状态
        self._mouse_down = False
        self._mouse_down_pos = (0.0, 0.0)
        self._mouse_down_time = 0.0
        self._mouse_button = "left"
        self._last_click_time = 0.0
        self._last_event_time = 0.0

        # 文本输入缓冲
        self._typing_buffer = []
        self._last_typing_ts = 0.0
        self._typing_timer = None

        # 修饰键状态
        self._modifiers = set()

        # 截图异步队列
        self._screenshot_queue = queue.Queue()
        self._screenshot_thread = None

    # ── 公共入口 ──────────────────────────────────────

    def record(self, name: str = None) -> Path:
        """开始录制。"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if name is None:
            name = timestamp
        self._output_dir = RECORDINGS_DIR / name
        self._screenshots_dir = self._output_dir / "screenshots"
        if self._screenshots_dir.exists():
            for f in self._screenshots_dir.iterdir():
                f.unlink()
        self._screenshots_dir.mkdir(parents=True, exist_ok=True)

        # 打开 raw.log
        raw_log_path = self._output_dir / "raw.log"
        self._raw_log = open(str(raw_log_path), "w", encoding="utf-8")
        atexit.register(self._cleanup)

        print(f"开始录制 → {self._output_dir}")
        print("按 Esc 停止录制...")

        # 启动截图工作线程
        self._screenshot_thread = threading.Thread(
            target=self._screenshot_worker, daemon=True
        )
        self._screenshot_thread.start()

        mouse_listener = p_mouse.Listener(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
        )
        kb_listener = p_keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )

        mouse_listener.start()
        kb_listener.start()

        try:
            # 主线程等待 Esc
            while not self._stop_event.is_set():
                self._maybe_flush_typing()
                time.sleep(0.1)
        finally:
            self._stop_recording()
            mouse_listener.stop()
            kb_listener.stop()

        # 收尾：flush 残留文本
        self._flush_typing(force=True)
        self._save_events(name)

        print(f"录制完成，共 {len(self._events)} 个事件")
        print(f" 产物: {self._output_dir / 'events.json'}")

        # 自动生成报告
        try:
            from win_report import generate_report
            report_path = generate_report(self._output_dir, self._output_dir)
            print(f"\n📊 报告已自动生成: {report_path}")
        except Exception:
            pass
        return self._output_dir

    # ── 鼠标事件 ──────────────────────────────────────

    def _on_move(self, x, y):
        pass  # 移动事件不记录（拖拽在 down/up 间推断）

    def _on_click(self, x, y, button, pressed):
        now = time.time()
        self._flush_typing(now=now)
        button_name = "right" if button == p_mouse.Button.right else "left"

        if pressed:
            self._mouse_down = True
            self._mouse_down_pos = (x, y)
            self._mouse_down_time = now
            self._mouse_button = button_name
            self._raw_buffer.append({"t": now, "type": f"{button_name}MouseDown",
                                     "loc": [int(x), int(y)]})
        else:
            if not self._mouse_down:
                return
            self._mouse_down = False
            dx = x - self._mouse_down_pos[0]
            dy = y - self._mouse_down_pos[1]
            dist = (dx**2 + dy**2) ** 0.5
            self._raw_buffer.append({"t": now, "type": f"{button_name}MouseUp",
                                     "loc": [int(x), int(y)]})

            if button_name == "right":
                self._add_event("rightclick", {"x": int(x), "y": int(y)}, now)
                return

            if dist > DRAG_THRESHOLD_PX:
                self._add_event("drag", {
                    "x1": int(self._mouse_down_pos[0]),
                    "y1": int(self._mouse_down_pos[1]),
                    "x2": int(x),
                    "y2": int(y),
                    "duration_ms": int((now - self._mouse_down_time) * 1000),
                }, now)
                return

            dbl = (now - self._last_click_time) < DOUBLE_CLICK_INTERVAL
            if dbl:
                self._events.pop()  # 移除上一个 click
                self._add_event("dblclick", {"x": int(x), "y": int(y)}, now)
            else:
                self._add_event("click", {"x": int(x), "y": int(y)}, now)
            self._last_click_time = now

    def _on_scroll(self, x, y, dx, dy):
        now = time.time()
        self._flush_typing(now=now)
        self._raw_buffer.append({"t": now, "type": "Scroll",
                                 "loc": [int(x), int(y)], "delta": [int(dx), int(dy)]})
        self._add_event("scroll", {
            "x": int(x), "y": int(y),
            "delta_x": int(dx), "delta_y": int(dy),
        }, now)

    # ── 键盘事件 ──────────────────────────────────────

    def _on_press(self, key):
        now = time.time()

        # Esc → 停止
        if key == p_keyboard.Key.esc:
            print("\n检测到 Esc，停止录制...")
            self._stop_event.set()
            return

        # 修饰键
        if key in (p_keyboard.Key.ctrl, p_keyboard.Key.ctrl_l, p_keyboard.Key.ctrl_r):
            self._modifiers.add("ctrl")
            return
        if key in (p_keyboard.Key.alt, p_keyboard.Key.alt_l, p_keyboard.Key.alt_r):
            self._modifiers.add("alt")
            return
        if key in (p_keyboard.Key.shift, p_keyboard.Key.shift_l, p_keyboard.Key.shift_r):
            self._modifiers.add("shift")
            return
        if key == p_keyboard.Key.cmd:
            self._modifiers.add("win")
            return

        # Backspace：删除刚输入的最后一个字符（不 flush、不记事件）
        if key == p_keyboard.Key.backspace:
            if self._typing_buffer:
                self._typing_buffer.pop()
                self._last_typing_ts = now
            self._raw_buffer.append({"t": now, "type": "KeyBackspace"})
            return

        # 字符键（含 Shift 产出的可见字符）
        if hasattr(key, "char") and key.char is not None and key.char.isprintable():
            if self._modifiers & {"ctrl", "alt", "win"}:
                # 组合键：先把已输入文本 flush 为 type 事件，再忽略该字符
                self._flush_typing(now=now, force=True)
                self._raw_buffer.append({"t": now, "type": "KeyCharCombo", "char": key.char})
                return
            self._typing_buffer.append(key.char)
            self._last_typing_ts = now
            self._raw_buffer.append({"t": now, "type": "KeyChar", "char": key.char})
            return

        # 非字符键：先 flush 文本，再记录 keyboard 事件
        self._flush_typing(now=now, force=True)
        key_name = self._key_name(key)
        keys = sorted(self._modifiers) + ([key_name] if key_name else [])
        if key_name:
            self._add_event("keyboard", {"keys": keys}, now)
            self._raw_buffer.append({"t": now, "type": "KeySpecial", "key": key_name})
            self._raw_buffer.append({"t": now, "type": "KeySpecial", "key": key_name})

    def _on_release(self, key):
        if key in (p_keyboard.Key.ctrl, p_keyboard.Key.ctrl_l, p_keyboard.Key.ctrl_r):
            self._modifiers.discard("ctrl")
        elif key in (p_keyboard.Key.alt, p_keyboard.Key.alt_l, p_keyboard.Key.alt_r):
            self._modifiers.discard("alt")
        elif key in (p_keyboard.Key.shift, p_keyboard.Key.shift_l, p_keyboard.Key.shift_r):
            self._modifiers.discard("shift")
        elif key == p_keyboard.Key.cmd:
            self._modifiers.discard("win")

    # ── 文本 flush ────────────────────────────────────

    def _maybe_flush_typing(self):
        if not self._typing_buffer:
            return
        if (time.time() - self._last_typing_ts) * 1000 >= TYPING_IDLE_MS:
            self._flush_typing(force=True)

    def _flush_typing(self, now: float = None, force: bool = False):
        if not self._typing_buffer:
            return
        if not force and now is not None:
            if (now - self._last_typing_ts) * 1000 < TYPING_IDLE_MS:
                return
        content = "".join(self._typing_buffer)
        self._typing_buffer = []
        if content:
            ts = now if now is not None else self._last_typing_ts
            self._add_event("type", {"content": content}, ts)

    # ── 事件添加 / 截图 ───────────────────────────────

    def _key_name(self, key) -> str:
        name = str(key)
        if name.startswith("Key."):
            return name[4:].lower()
        return ""

    def _add_event(self, event_type: str, extra: dict, timestamp: float):
        seq = len(self._events)
        x = extra.get("x", extra.get("x1", 0))
        y = extra.get("y", extra.get("y1", 0))

        # 先截操作前截图（此时屏幕还是旧状态）
        before_path = self._screenshots_dir / f"event_{seq:03d}_0_before.jpg"
        capture_fullscreen(str(before_path), mark_pos=(x, y))

        delay_before_ms = 0
        if self._events:
            prev_ts = self._events[-1].get("timestamp", timestamp)
            delay_before_ms = int((timestamp - prev_ts) * 1000)

        event = {
            "type": event_type,
            "timestamp": timestamp,
            "delay_before_ms": max(0, delay_before_ms),
            "delay_after_ms": 0,
            # 截图预览：注入相对路径供编辑器加载（jpg，与 capture_fullscreen 输出一致）
            "screenshots": {
                "before": f"screenshots/event_{seq:03d}_0_before.jpg",
                "after": f"screenshots/event_{seq:03d}_1_after.jpg",
                "before_type": "screenshot",
                "after_type": "screenshot",
            },
        }
        event.update(extra)
        self._events.append(event)

        print(f"  #{seq + 1} 🎯 {event_type} 屏幕({x},{y})")

        # 截图交给后台线程异步处理
        self._screenshot_queue.put((seq, x, y))

    def _screenshot_worker(self):
        while True:
            item = self._screenshot_queue.get()
            if item is None:
                self._screenshot_queue.task_done()
                break
            seq, x, y = item
            after = self._screenshots_dir / f"event_{seq:03d}_1_after.jpg"
            capture_fullscreen(str(after), mark_pos=(x, y))
            self._screenshot_queue.task_done()

    # ── 收尾 ──────────────────────────────────────────

    def _stop_recording(self):
        if self._screenshot_thread is not None:
            self._screenshot_queue.put(None)
            self._screenshot_thread.join(timeout=30)
            self._screenshot_thread = None

        if self._raw_buffer and self._raw_log:
            for entry in self._raw_buffer:
                self._raw_log.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._raw_buffer = []
        if self._raw_log and not self._raw_log.closed:
            self._raw_log.close()

    def _save_events(self, name: str):
        output = {
            "name": name,
            "created_at": datetime.now().isoformat(),
            "platform": "win",
            "resolution": list(get_screen_size()),
            "events": self._events,
        }
        events_path = self._output_dir / "events.json"
        with open(str(events_path), "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

    def _cleanup(self):
        self._stop_recording()


def start_recording(name: str = None) -> Path:
    """顶层入口，供 cmd_record 调用。"""
    return WinRecorder().record(name=name)
