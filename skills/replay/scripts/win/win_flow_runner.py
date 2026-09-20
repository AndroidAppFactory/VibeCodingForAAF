#!/usr/bin/env python3
"""win-replay Flow 执行引擎

复用 replay 的 core.runner / core.report，把 Flow 步骤交给 Windows 输入层执行。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 模块级：子进程输出日志文件（run_flow 时设置）
_app_log_file: Path | None = None

# DPI 感知必须在 pynput 导入前设置（wininput bridge 内部使用 pynput Controller）
if sys.platform == "win32":
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

# 注入 notify 模块路径（~/.zixiekit/scripts/）
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
_zk_home = os.environ.get("ZIXIEKIT_HOME")
if _zk_home:
    sys.path.insert(0, str(Path(_zk_home) / "scripts"))

# 注入 replay 路径
_scripts_dir = Path(__file__).resolve().parent
_replay_core_dir = _scripts_dir.parent.parent / "scripts"
if str(_replay_core_dir) not in sys.path:
    sys.path.insert(0, str(_replay_core_dir))

from core.config import FLOW_RUNS_DIR
from core.runner import run_flow
from core.report import generate_flow_report, generate_critical_snapshot

# FLOWS_DIR 已统一指向全局 replay/flows/（S1 改造）

from bridge import wininput
from bridge import window
from bridge.screenshot import capture_fullscreen, capture_window, capture_all_windows

# 当前活跃进程名（launch 后设置，quit 后清除）
_active_process: str = ""
# launch 时 exe 所在目录（用于 dir-match 回退查找 UI 进程）
_active_dir: str = ""


def _check_process_running(target: str, timeout_ms: int = 10000, interval_ms: int = 500) -> bool:
    """检查指定 exe 的进程是否已启动。

    target: exe 路径
    timeout_ms: 最长等待时间（毫秒）
    interval_ms: 检查间隔（毫秒）
    返回 True 表示进程已运行。
    """
    proc_name = Path(target).name  # e.g. "YOUKU.exe"
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            result = subprocess.run(
                ["tasklist", "/fi", f"IMAGENAME eq {proc_name}", "/nh"],
                capture_output=True, text=True, timeout=5
            )
            if proc_name.lower() in result.stdout.lower():
                return True
        except Exception:
            pass
        time.sleep(interval_ms / 1000.0)
    return False


def _kill_process_by_exe(target: str):
    """根据 exe 路径杀掉已有进程（含子进程）。"""
    proc_name = Path(target).name  # e.g. "YOUKU.exe"
    try:
        result = subprocess.run(
            ["taskkill", "/f", "/t", "/im", proc_name],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            print(f"    🗑 已杀掉旧进程: {proc_name}")
            time.sleep(1)
        else:
            # 0x80 = 进程不存在，不算错误
            if result.returncode != 0x80:
                print(f"    ⚠ 杀进程失败({result.returncode}): {result.stderr.strip()}")
    except Exception as e:
        print(f"    ⚠ 杀进程异常: {e}")


def _quit_process(proc_name: str, timeout: int = 10) -> bool:
    """退出指定进程（含子进程树），返回是否成功"""
    try:
        r = subprocess.run(["taskkill", "/f", "/t", "/im", proc_name], capture_output=True, timeout=timeout)
        if r.returncode == 0:
            print(f"    🗑 已退出: {proc_name}（含子进程）")
            time.sleep(1)  # 等进程完全退出
            return True
        else:
            # 进程不存在也视为成功
            return True
    except Exception as e:
        print(f"    ⚠ 退出失败: {e}")
        return False


def _execute_action(step: dict):
    action = step.get("action", "")
    target = step.get("target", "")
    if action == "launch":
        if target:
            try:
                proc_name = Path(target).name
                if _check_process_running(proc_name, timeout_ms=2000):
                    print(f"    🔄 进程已在运行，先退出再重启: {proc_name}")
                    _quit_process(proc_name)
                _log_fh = open(_app_log_file, "a", encoding="utf-8") if _app_log_file else subprocess.DEVNULL
                subprocess.Popen(target, shell=True, stdout=_log_fh, stderr=_log_fh)
                if _check_process_running(proc_name, timeout_ms=15000):
                    print(f"    🚀 已启动: {proc_name}")
                else:
                    raise RuntimeError(f"窗口未出现（超时 15s），进程可能未成功启动")
            except Exception as e:
                print(f"    ⚠ 启动失败: {e}")
                raise
    elif action == "quit":
        if target:
            _quit_process(target)
    elif action == "activate":
        if target:
            window.focus_window(target)
    elif action == "close":
        window.close_foreground()
    elif action == "maximize":
        window.maximize_foreground()


def _execute_event(step: dict):
    """执行单个事件步骤（type=event）。"""
    action = step.get("action", step.get("type", ""))
    x = step.get("x", 0)
    y = step.get("y", 0)

    if action == "click":
        wininput.click(x, y)
    elif action == "dblclick":
        wininput.double_click(x, y)
    elif action == "rightclick":
        wininput.click(x, y, button="right")
    elif action == "type":
        wininput.type_text(step.get("content", ""))
    elif action in ("keyboard", "hotkey"):
        wininput.send_combo(step.get("keys", []))
    elif action == "scroll":
        wininput.scroll(x, y, step.get("delta_x", 0), step.get("delta_y", 0))
    elif action == "drag":
        wininput.drag(step.get("x1", x), step.get("y1", y),
                      step.get("x2", x), step.get("y2", y),
                      step.get("duration_ms", 500))
    elif action == "hover":
        wininput.hover(x, y, step.get("duration_ms", 500))
    elif action == "wait":
        time.sleep(step.get("duration_ms", 1000) / 1000.0)
    elif action == "tips":
        try:
            input(f"\n  💬 {step.get('content', '按 Enter 继续...')}")
        except (EOFError, KeyboardInterrupt):
            pass
    elif action == "launch":
        target = step.get("target", "")
        if target:
            try:
                proc_name = Path(target).name
                if _check_process_running(proc_name, timeout_ms=2000):
                    print(f"    🔄 进程已在运行，先退出再重启: {proc_name}")
                    _quit_process(proc_name)
                _log_fh = open(_app_log_file, "a", encoding="utf-8") if _app_log_file else subprocess.DEVNULL
                subprocess.Popen(target, shell=True, stdout=_log_fh, stderr=_log_fh)
                if _check_process_running(proc_name, timeout_ms=15000):
                    print(f"    🚀 已启动: {proc_name}")
                else:
                    raise RuntimeError(f"窗口未出现（超时 15s），进程可能未成功启动")
            except Exception as e:
                print(f"    ⚠ 启动失败: {e}")
                raise
    elif action == "quit":
        # 优先用 launch 记录的实际进程名（target 可能写错，如 mgtv.exe 实际是 芒果TV.exe）
        proc = _active_process or step.get("target", "")
        if proc:
            _quit_process(proc)
    elif action == "action":
        _execute_action(step)


from core.notify import notify_safe as _notify_safe, notify_image_safe as _notify_image_safe, build_notify_message  # noqa: E402


def _hostname():
    import platform
    return platform.node() or "windows"


def _title(flow_name: str, started_at: str, status: str = "") -> str:
    """通知标题（执行时间已移除；执行机器保留在标题）
    {icon} 💻 【{status} - Win】{flow_name}    执行机器：{host}
    """
    host = _hostname()
    icons = {"开始": "🚀", "结束": "✅", "失败": "⚠️"}
    icon = icons.get(status, "ℹ️")
    label = f"{icon} 💻 【{status} - Win】" if status else "ℹ️ 💻 Win"
    return f"{label}{flow_name}    执行机器：{host}"


def build_hooks(speed: float = 1.0):
    """构造 win 平台的 (setup, teardown, executor) 三元组。

    供单端 run_flow_by_name 和 mixed 单进程编排共用。
    活跃进程状态用模块级全局 _active_process/_active_dir 维护。
    """
    def _wlog(msg: str = ""):
        ts = datetime.fromtimestamp(time.time()).strftime("%H:%M:%S")
        print(f"  [{ts}] {msg}")

    # ── setup：显示桌面 + 设置 app 输出日志路径 ──
    def setup(ctx):
        global _app_log_file, _active_process, _active_dir
        _active_process = ""  # 每次运行重置
        _active_dir = ""
        _app_log_file = ctx.run_dir / "app_output.log"
        wininput.send_combo(["win", "d"])
        time.sleep(0.5)
        _wlog("📌 已显示桌面")

    # ── teardown：win 无常驻资源需释放（进程由 flow 内 quit 管理）──
    def teardown(ctx):
        pass

    # ── executor：只处理 event（pause/shell_cmd 由 core.runner 处理）──
    def executor(ctx, step: dict):
        global _active_process, _active_dir
        ss_dir = Path(step.get("_screenshot_dir", str(ctx.run_dir / "screenshots")))
        ss_dir.mkdir(parents=True, exist_ok=True)

        # delay_before：执行前等待
        delay_before = step.get("delay_before_ms", 0) / 1000.0
        if delay_before > 0:
            time.sleep(delay_before / speed)

        x = step.get("x", 0)
        y = step.get("y", 0)

        # 智能截图：多策略查找窗口
        def _find_active_window():
            """查找活跃应用窗口：先按进程名，失败则按目录匹配"""
            if not _active_process:
                return None
            hwnd, wtitle = window.find_window_by_process(_active_process)
            if hwnd:
                return hwnd, wtitle
            if _active_dir:
                proc = window.find_window_by_exe_dir(_active_dir)
                if proc:
                    return window.find_window_by_process(proc)
            return None, None

        def _capture(path, pos=None):
            if _active_dir:
                # 优先：按目录截所有窗口合集（支持多窗口应用）
                capture_all_windows(_active_dir, path, mark_pos=pos)
            elif _active_process:
                capture_window(_active_process, path, mark_pos=pos)
            else:
                capture_fullscreen(path, mark_pos=pos)

        _capture(str(ss_dir / "event_000_0_before.png"), (x, y))
        _wlog(f"📸 截屏(前): event_000_0_before.png")

        # 操作详情
        action = step.get("action", "")
        if action in ("click", "dblclick", "rightclick", "hover", "drag"):
            detail = f"{action} ({x}, {y})"
        elif action == "scroll":
            detail = f"scroll ({x}, {y}) dx={step.get('delta_x', 0)} dy={step.get('delta_y', 0)}"
        elif action == "type":
            content = step.get("content", "")
            detail = f"type \"{content[:30]}\""
        elif action == "keyboard":
            keys = step.get("keys", [])
            detail = f"keyboard {'+'.join(keys)}"
        elif action in ("launch", "quit", "activate", "close", "maximize"):
            detail = f"{action} {step.get('target', '')}"
        else:
            detail = action
        if detail:
            _wlog(f"▶ {detail}")
        _wlog(f"⏱ 前={delay_before:.1f}s") if delay_before > 0 else None

        try:
            _execute_event(step)
            success = True
            # 维护 _active_process 状态
            if action == "launch":
                target = step.get("target", "")
                if target:
                    target_name = Path(target).name
                    # 通过 target 所在目录查找有窗口的实际 UI 进程（重试等窗口就绪）
                    found = None
                    for _retry in range(20):  # 最多等 10 秒
                        found = window.find_window_by_exe_dir(Path(target).parent)
                        if found:
                            break
                        time.sleep(0.5)
                    if found:
                        _active_process = found
                        if _active_process.lower() != target_name.lower():
                            _wlog(f"📌 活跃进程: {_active_process}（目录匹配，target={target_name}）")
                        else:
                            _wlog(f"📌 活跃进程: {_active_process}")
                    else:
                        _active_process = target_name
                        _wlog(f"📌 活跃进程: {_active_process}（fallback 使用 target 文件名）")
                    _active_dir = str(Path(target).parent)
            elif action == "quit":
                _wlog(f"📌 清除活跃进程: {_active_process}")
                _active_process = ""
                _active_dir = ""
            # 非 launch/quit 操作后，检查前台窗口是否切换了进程（播放器弹窗等场景）
            elif action not in ("launch", "quit") and _active_dir:
                fg = window.get_foreground_info()
                if fg and fg.get("process"):
                    if fg["process"].lower() != _active_process.lower():
                        from pathlib import Path as _Path
                        try:
                            import psutil
                            p = psutil.Process(fg["pid"])
                            if p and str(_Path(p.exe()).parent).lower() == _active_dir.lower():
                                old = _active_process
                                _active_process = fg["process"]
                                _wlog(f"📌 进程切换: {old} → {_active_process}（前台窗口: {fg.get('title', '')}）")
                        except Exception:
                            pass
        except Exception as e:
            success = False
            _wlog(f"❌ 失败: {e}")

        # delay_after：执行后等待（等页面响应完再截 after 图）
        delay_after = step.get("delay_after_ms", 0) / 1000.0
        if delay_after > 0:
            time.sleep(delay_after / speed)
        # launch 后，如果启动的应用被弹出网页等窗口抢占了前台，截图前强制聚焦
        if action == "launch" and _active_process:
            hwnd, wtitle = _find_active_window()
            if hwnd:
                user32 = window.user32
                user32.SetForegroundWindow(hwnd)
                _wlog(f"📌 强制聚焦窗口: {wtitle}")
                time.sleep(1.0)
            else:
                _wlog(f"⚠️ 未找到 {_active_process} 的窗口，跳过聚焦")
        _capture(str(ss_dir / "event_000_1_after.png"), (x, y))
        _wlog(f"📸 截屏(后): event_000_1_after.png")

        # 写 data.json（含截图元数据，供 flow 编辑器注入运行截图预览）
        _step_dir_raw = step.get("_step_dir")
        if _step_dir_raw:
            try:
                _step_dir = Path(_step_dir_raw)
                _step_dir.mkdir(parents=True, exist_ok=True)
                _ev = {k: v for k, v in step.items() if not k.startswith("_")}
                _data = {
                    "device": "win",
                    "events": [dict(_ev, screenshots={"before_type": "screenshot", "after_type": "screenshot"})],
                }
                with open(_step_dir / "data.json", "w", encoding="utf-8") as _f:
                    json.dump(_data, _f, ensure_ascii=False, indent=2)
            except OSError:
                pass

        actual_num = step.get("_actual_num", 0)
        critical = []
        if step.get("is_critical"):
            critical = [
                f"{actual_num:04d}/screenshots/event_000_0_before.png",
                f"{actual_num:04d}/screenshots/event_000_1_after.png",
            ]
        return success, {"critical_screenshots": critical}

    return setup, teardown, executor


def probe() -> bool:
    """探测 win 平台是否可用：运行在 Windows 且 pywin32/pynput 可用。"""
    if sys.platform != "win32":
        return False
    try:
        import pynput  # noqa: F401
        return True
    except ImportError:
        return False


def run_flow_by_name(flow_name: str, speed: float = 1.0,
                     max_delay: float | None = None,
                     step_indices: list | None = None, fail_fast: bool = False,
                     rerun: bool = False):
    """运行指定 Flow，返回 (run_dir, summary, report_path)。"""
    global _active_process, _active_dir
    _active_process = ""  # 每次运行重置
    _active_dir = ""

    # ── 环境预检：自动安装缺失依赖 ──
    try:
        import pynput  # noqa: F401
    except ImportError:
        print("📦 pynput 未安装，自动安装中...", file=sys.stderr)
        import subprocess, sys, shutil
        if shutil.which("pipx") and "pipx" in sys.executable:
            subprocess.run(["pipx", "inject", "zixiekit", "pynput", "pyautogui", "psutil"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "pynput", "pyautogui", "psutil"], check=True)
        print("✅ pynput 安装完成", file=sys.stderr)
    started_at = datetime.now().isoformat()

    # 加载 Flow 以获取元信息
    from core.flow import load_flow
    flow = load_flow(flow_name)

    fid = (flow.get("id", "") or "")[:4] if flow else flow_name
    display_name = flow.get("name", flow_name) if flow else flow_name

    # ── setup/teardown/executor：复用 build_hooks 工厂（与 mixed 单进程共用）──
    _setup_win, _teardown_win, step_executor = build_hooks(speed=speed)

    # ── notify_hook：对齐 adb，用 win 完整标题覆盖 core 简化标题 ──
    def _notify_win(title: str, message: str, level: str) -> None:
        if "开始" in title:
            status = "开始"
        elif "失败" in title or "⚠️" in title:
            status = "失败"
        elif "结束" in title or "✅" in title:
            status = "结束"
        else:
            status = ""
        full_title = _title(display_name, started_at, status)
        msg_started_at = started_at if status in ("结束", "失败", "中断") else ""
        from core.cli import build_run_command
        full_msg = build_notify_message(
            message,
            started_at=msg_started_at,
            command=build_run_command(fid, speed=speed, max_delay=max_delay,
                                      step_indices=step_indices, fail_fast=fail_fast, rerun=rerun),
        )
        _notify_safe(full_title, full_msg, level)

    # ── report_hook：生成报告 + 关键截图（结果块会显示「报告/快照」行）──
    def _report_win(run_dir: Path, summary: dict):
        report_file = generate_flow_report(run_dir, summary, screenshot_cols=3)
        snapshot = generate_critical_snapshot(run_dir, summary, display_name=display_name, max_cols=2, rotate_landscape=False)
        if snapshot and not (os.environ.get("REPLAY_MIXED_MODE") == "1" or os.environ.get("REPLAY_NO_NOTIFY") == "1"):
            _notify_image_safe(snapshot)
        return report_file

    # ── tips_hook：后续命令提示 ──
    def _tips_win(fl: dict, run_dir: Path) -> None:
        from core.cli import tips_after_flow_run
        fid_ = (fl.get("id", "") or "")[:4]
        report_file = run_dir / "index.html"
        tips_after_flow_run("win", fid_, script_path="",
                            report_path=str(report_file) if report_file.exists() else "")

    summary = run_flow(
        flow_name,
        step_executor,
        fail_fast=fail_fast,
        speed=speed,
        max_delay=max_delay,
        step_indices=step_indices,
        rerun=rerun,
        device="windows",
        setup_hook=_setup_win,
        notify_hook=_notify_win,
        report_hook=_report_win,
        tips_hook=_tips_win,
    )
    run_dir = Path(summary.get("run_dir", ""))
    report = run_dir / "index.html"
    report = str(report) if report.exists() else None

    return run_dir, summary, report
