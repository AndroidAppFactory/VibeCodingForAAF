"""web-replay CLI：Flow 子命令（D21 统一入口）"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# 注入 notify 模块路径（~/.zixiekit/scripts/）
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
_zk_home = os.environ.get("ZIXIEKIT_HOME")
if _zk_home:
    sys.path.insert(0, str(Path(_zk_home) / "scripts"))

# replay-core 路径
_replay_core = Path(__file__).resolve().parents[3] / "scripts"
if str(_replay_core) not in sys.path:
    sys.path.insert(0, str(_replay_core))
from core.notify import notify_safe as _notify_safe, notify_image_safe as _notify_image_safe, build_notify_message  # noqa: E402


def _run_flow_impl(flow: dict, max_delay=None, headless=False, timeout=30, speed=1.0) -> int:
    """运行 Flow：展开为事件级步骤列表，整个运行期间共享同一浏览器"""
    from web_player import run_flow_events
    from flowcore.flow import resolve_flow_steps
    from core.config import FLOW_RUNS_DIR
    from datetime import datetime

    try:
        steps = resolve_flow_steps(flow)
    except ValueError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1

    if not steps:
        print(f"❌ Flow「{flow['name']}」没有可执行步骤", file=sys.stderr)
        return 1

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in flow["name"])
    FLOW_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = FLOW_RUNS_DIR / f"{safe_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)

    started_at = datetime.now().isoformat(timespec="seconds")
    fid = (flow.get("id", "") or "")[:4] or flow["name"]

    # ── notify_hook：对齐 adb，用 web 完整标题覆盖 core 简化标题 ──
    def notify_hook(title: str, message: str, level: str) -> None:
        if "开始" in title:
            status = "开始"
        elif "失败" in title or "⚠️" in title:
            status = "失败"
        elif "结束" in title or "✅" in title:
            status = "结束"
        else:
            status = ""
        from flow_report import _get_local_hostname
        host = _get_local_hostname()
        icon = {"开始": "🚀", "结束": "✅", "失败": "⚠️"}.get(status, "ℹ️")
        full_title = f"{icon} 【{status} - WEB】{flow['name']}    执行机器：{host}"
        msg_started_at = started_at if status in ("结束", "失败", "中断") else ""
        from core.cli import build_run_command
        full_msg = build_notify_message(
            message,
            started_at=msg_started_at,
            command=build_run_command(fid, speed=speed, max_delay=max_delay),
        )
        _notify_safe(full_title, full_msg, level)

    # ── report_hook：生成报告 + 关键截图 ──
    def report_hook(run_dir: Path, summary: dict):
        from flow_report import generate_flow_report, generate_critical_snapshot
        report_file = generate_flow_report(run_dir, summary)
        snapshot_file = generate_critical_snapshot(run_dir, summary, max_cols=2, rotate_landscape=False)
        if snapshot_file and not (os.environ.get("REPLAY_MIXED_MODE") == "1" or os.environ.get("REPLAY_NO_NOTIFY") == "1"):
            _notify_image_safe(snapshot_file)
        return report_file

    # ── tips_hook ──
    def tips_hook(fl: dict, run_dir: Path) -> None:
        from core.cli import tips_after_flow_run
        fid_ = (fl.get("id", "") or "")[:4]
        report_file = run_dir / "index.html"
        tips_after_flow_run("web", fid_, script_path="",
                            report_path=str(report_file) if report_file.exists() else "")

    summary = run_flow_events(
        steps, run_dir,
        headless=headless, timeout=timeout, speed=speed, max_delay=max_delay,
        notify_hook=notify_hook, report_hook=report_hook, tips_hook=tips_hook,
        flow_data=flow,
    )

    return 0 if summary.get("failed_steps", 0) == 0 else 1


# ── D21 统一入口（由 cli/main.py 调用）──


def cmd_flow_run(args) -> int:
    """flow run <id>"""
    if getattr(args, "no_notify", False):
        os.environ["REPLAY_NO_NOTIFY"] = "1"
    from flowcore.flow import load_flow
    flow = load_flow(args.id)
    if not flow:
        from core.cli import log_error
        log_error(f"Flow「{args.id}」不存在")
        return 1
    return _run_flow_impl(
        flow,
        max_delay=getattr(args, "max_delay", None),
        headless=getattr(args, "headless", False),
        timeout=getattr(args, "timeout", 30),
        speed=getattr(args, "speed", 1.0),
    )


def cmd_flow_report(args) -> int:
    """flow report <id>"""
    from flowcore.flow import load_flow
    from core.config import FLOW_RUNS_DIR
    from flow_report import generate_flow_report, generate_critical_snapshot

    flow = load_flow(args.id)
    if not flow:
        from core.cli import log_error
        log_error(f"Flow「{args.id}」不存在")
        return 1

    if not FLOW_RUNS_DIR.exists():
        from core.cli import log_error
        log_error("没有运行记录")
        return 1
    fid = flow.get("id", "")
    # 运行目录名不含 flow_id，需读各目录 summary.json 的 flow_id 精确匹配
    runs = []
    for d in sorted(FLOW_RUNS_DIR.iterdir(), reverse=True):
        sf = d / "summary.json"
        if not d.is_dir() or not sf.exists():
            continue
        try:
            if json.loads(sf.read_text(encoding="utf-8")).get("flow_id") == fid:
                runs.append(d)
        except (json.JSONDecodeError, OSError):
            continue
    if not runs:
        from core.cli import log_error
        log_error(f"Flow「{flow['name']}」没有运行记录")
        return 1
    run_dir = runs[0]
    sf = run_dir / "summary.json"
    if not sf.exists():
        from core.cli import log_error
        log_error("目录中没有 summary.json")
        return 1
    summary = json.loads(sf.read_text(encoding="utf-8"))
    report = generate_flow_report(run_dir, summary)
    snapshot = generate_critical_snapshot(run_dir, summary, rotate_landscape=False, layout=args.layout)
    from core.cli import log_success, tips_report_layout
    log_success(f"报告已生成: {report}")
    if snapshot:
        print(f"   🖼  关键截图: {snapshot}")
    tips_report_layout(args.id)
    return 0


def cmd_report_rerun(args) -> int:
    """report <run_dir>"""
    from flow_report import generate_flow_report, generate_critical_snapshot

    run_dir = Path(args.run_dir).resolve()
    sf = run_dir / "summary.json"
    if not sf.exists():
        from core.cli import log_error
        log_error(f"{run_dir} 中没有 summary.json")
        return 1
    summary = json.loads(sf.read_text(encoding="utf-8"))
    report = generate_flow_report(run_dir, summary)
    snapshot = generate_critical_snapshot(run_dir, summary, rotate_landscape=False, layout=args.layout)
    from core.cli import log_success
    log_success(f"报告已生成: {report}")
    if snapshot:
        print(f"   🖼  关键截图: {snapshot}")
    return 0
