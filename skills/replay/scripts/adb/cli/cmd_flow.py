"""adb-replay CLI：Flow 子命令（D21 统一入口）"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from adb_core.config import SCRIPTS_DIR
from adb_core.flow import load_flow
from adb_core.port_utils import ensure_port_free


# ── 新 CLI 入口（D21 统一，由 cli/main.py 调用）──


def cmd_flow_run(args) -> int:
    """flow run <id> 入口"""
    _scripts = str(SCRIPTS_DIR)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)

    if getattr(args, "no_notify", False):
        os.environ["REPLAY_NO_NOTIFY"] = "1"

    flow_name = args.id
    step_indices = getattr(args, "step_indices", None) or []
    from flow_runner import run_flow
    return run_flow(
        flow_name,
        device=getattr(args, "device", None),
        speed=getattr(args, "speed", 1.0),
        max_delay=getattr(args, "max_delay", None),
        step_indices=step_indices or None,
        fail_fast=getattr(args, "fail_fast", False),
        rerun=getattr(args, "rerun", False),
    )


def cmd_flow_report(args) -> int:
    """flow report <id> 入口"""
    _scripts = str(SCRIPTS_DIR)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)

    from flow_runner import list_flow_runs
    from flow_report import generate_flow_report, generate_critical_snapshot
    from core.cli import tips_report_layout

    flow_id = args.id
    runs = list_flow_runs(flow_id)
    if not runs:
        print(f"❌ Flow「{flow_id}」没有运行记录")
        return 1
    latest = max(runs, key=lambda r: r.get("started_at", ""))
    run_dir = Path(latest["dir"])
    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        print("❌ 目录中没有 summary.json")
        return 1
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    report_file = generate_flow_report(run_dir, summary)
    snapshot_file = generate_critical_snapshot(run_dir, summary, layout=args.layout)
    print(f"✅ 报告已生成")
    print(f"   📄 HTML 报告: {report_file}")
    if snapshot_file:
        print(f"   🖼  关键截图: {snapshot_file}")
    tips_report_layout(args.id)
    return 0


def cmd_report_rerun(args) -> int:
    """report <run_dir> 入口"""
    _scripts = str(SCRIPTS_DIR)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)

    from flow_report import generate_flow_report, generate_critical_snapshot

    run_dir = Path(args.run_dir).resolve()
    summary_file = run_dir / "summary.json"
    if not summary_file.exists():
        print(f"❌ {run_dir} 中没有 summary.json")
        return 1
    summary = json.loads(summary_file.read_text(encoding="utf-8"))
    report_file = generate_flow_report(run_dir, summary)
    snapshot_file = generate_critical_snapshot(run_dir, summary, layout=args.layout)
    print(f"✅ 报告已生成: {report_file}")
    if snapshot_file:
        print(f"   🖼  关键截图: {snapshot_file}")
    return 0
