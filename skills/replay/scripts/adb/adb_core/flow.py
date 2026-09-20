"""adb-replay Flow 数据模型（代理层）

所有 Flow CRUD 和解析能力统一由 replay-core 提供。
本模块仅做 re-export + 保留 adb 独有的历史数据迁移逻辑。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

# 确保 replay-core/scripts 在 sys.path 上
_replay_core = Path(__file__).resolve().parents[3] / "scripts"
if str(_replay_core) not in sys.path:
    sys.path.insert(0, str(_replay_core))

# ─── 从 core.flow 统一 re-export ──────────────────────
from core.flow import (  # noqa: E402, F401
    save_flow,
    load_flow,
    list_flows,
    delete_flow,
    resolve_flow_ref,
    get_flow_id_by_name,
    resolve_steps_recursive,
    resolve_flow_steps,
    find_flows_by_name,
    ensure_dir,
)

from adb_core.config import TASKS_FILE  # noqa: E402


# ─── adb 独有：历史数据迁移 ──────────────────────────────


def _event_to_step(ev: dict) -> dict:
    """将旧事件对象转为 Flow 步骤"""
    step = {
        "type": "event",
        "action": ev.get("type", "tap"),
        "delay_before_ms": ev.get("delay_before_ms", 0),
        "delay_after_ms": ev.get("delay_after_ms", 0),
        "is_critical": ev.get("is_critical", False),
    }
    t = step["action"]
    if t == "tap":
        step["x"] = ev.get("x", 0)
        step["y"] = ev.get("y", 0)
    elif t == "multitap":
        step["x"] = ev.get("x", 0); step["y"] = ev.get("y", 0)
        step["count"] = ev.get("count", 2)
    elif t == "swipe":
        step["x1"] = ev.get("x1", 0); step["y1"] = ev.get("y1", 0)
        step["x2"] = ev.get("x2", 0); step["y2"] = ev.get("y2", 0)
        step["duration_ms"] = ev.get("duration_ms", 500)
    elif t == "keyevent":
        step["code"] = ev.get("code", 3)
    elif t == "text":
        step["content"] = ev.get("content", "")
    elif t == "adb":
        step["adb_action"] = ev.get("action", "restart")
        step["package"] = ev.get("package", "")
        step["ssid"] = ev.get("ssid", "")
        step["password"] = ev.get("password", "")
    elif t == "tips":
        step["content"] = ev.get("content", "")
    elif t.startswith("capture") or t == "start_record" or t == "stop_record":
        pass  # 录制专用事件，回放时跳过
    return step


def migrate_to_flows() -> tuple[int, int]:
    """将旧 tasks.json 数据迁移到 flows/

    1. tasks.json 中每个任务的 events 拆成独立步骤 → Flow
    2. task_groups/（已废弃）

    Returns: (task 迁移数, group 迁移数)
    """
    from adb_core.config import FLOWS_DIR

    task_map = {}
    if TASKS_FILE.exists():
        try:
            with open(TASKS_FILE, "r", encoding="utf-8") as fp:
                for t in json.load(fp):
                    task_map[t["name"]] = t
        except (json.JSONDecodeError, OSError):
            pass

    tasks_migrated = 0
    for task_name, task_data in task_map.items():
        # 检查是否已有同名 flow
        if load_flow(task_name):
            continue
        steps = []
        for ev in task_data.get("events", []):
            step = _event_to_step(ev)
            if step["action"] in ("capture", "start_record", "stop_record"):
                continue
            if step["action"] == "adb" and not step.get("adb_action"):
                continue
            steps.append(step)
        if not steps:
            continue
        flow = {"name": task_name, "platform": "adb", "description": "", "steps": steps}
        save_flow(flow)
        tasks_migrated += 1

    groups_migrated = 0
    return tasks_migrated, groups_migrated
