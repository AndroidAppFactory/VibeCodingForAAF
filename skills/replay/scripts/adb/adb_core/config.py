"""adb-replay 公共常量和配置

所有脚本统一从此模块获取路径配置，避免硬编码散落各处。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# 加载环境变量（~/.zixiekit/scripts/bootstrap.py 由 zk init / zk instance update 部署）
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
from bootstrap import load_env  # noqa: E402

load_env()


# ─── 根路径 ───────────────────────────────────────

ZIXIEKIT_TMP = Path(os.environ.get("ZIXIEKIT_TMP", str(Path.home() / ".zixiekit")))
REPLAY_DIR = ZIXIEKIT_TMP / "skill" / "adb-replay"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent


# ─── 任务录制 ────────────────────────────────────

TASKS_DIR = REPLAY_DIR / "tasks"
# 录制输出统一放 tasks/ 下（每个 task 一个子目录）
TASK_RECORD_DIR = TASKS_DIR
# 旧 tasks.json 备份文件（只读，保留给迁移用）
TASKS_FILE = TASKS_DIR / "tasks.json"


# ─── Flow ─────────────────────────────────────────

# replay-core 共享资源
_REPLAY_CORE = Path(__file__).resolve().parents[3] / "scripts"
FLOWS_DIR = _REPLAY_CORE.parent / "flows"
HTML_DIR = _REPLAY_CORE.parent / "edit"
# 所有平台统一：~/.zixiekit/skill/replay/flow_runs/
FLOW_RUNS_DIR = ZIXIEKIT_TMP / "skill" / "replay" / "flow_runs"


# ─── 安装 APK ─────────────────────────────────────

# install 事件动作读取 APK 的固定目录
INSTALL_DIR = ZIXIEKIT_TMP / "skill" / "replay" / "install"
