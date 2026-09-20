"""replay/core 公共常量和配置

Flow 编排核心，供 web-replay 和 win-replay 共用。
所有脚本统一从此模块获取路径配置。
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
REPLAY_CORE_DIR = ZIXIEKIT_TMP / "skill" / "scripts"
SCRIPTS_DIR = Path(__file__).resolve().parent.parent

# ─── Flow（全局单仓库，仓库内、纳入 git）────────────
# flow 是可版本化代码资产：四端共用同一目录，靠 flow.platform 字段区分。
# 位于 replay/flows/（SCRIPTS_DIR 的上级），随仓库进 git。

FLOWS_DIR = SCRIPTS_DIR.parent / "flows"

# ─── Flow 运行记录（临时产物，存 ZIXIEKIT_TMP，不进 git）──
# 录制/运行产物是临时数据，各 skill 可覆盖为自己的平台子目录。

FLOW_RUNS_DIR = ZIXIEKIT_TMP / "skill" / "replay" / "flow_runs"

# ─── 录制文件临时目录 ──────────────────────────────

REPLAY_DIR = REPLAY_CORE_DIR / "recordings"

# ─── HTML 前端资源 ────────────────────────────────

HTML_DIR = SCRIPTS_DIR.parent / "edit"  # edit/ 目录（flow.html / editor.html 所在）
