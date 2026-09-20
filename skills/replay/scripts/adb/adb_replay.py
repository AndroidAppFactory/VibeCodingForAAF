#!/usr/bin/env python3
"""adb-replay CLI 兼容入口

委托给 cli/main.py，保留原入口路径供外部引用。
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

# 查找公共模块：本目录（部署嵌入）或 $ZIXIEKIT_HOME/scripts/（仓库源码）
_self = Path(__file__).resolve().parent
sys.path.insert(0, str(_self))
# replay-core 共享模块（core.snapshot 等），优先级在自身 core 之后
_replay_core = str(_self.parent.parent / "scripts")
sys.path.insert(1, _replay_core)
_zk = os.environ.get("ZIXIEKIT_HOME")
if _zk:
    sys.path.insert(2, str(Path(_zk) / "scripts"))
del _self, _replay_core, _zk


def main(argv: list[str] | None = None) -> int:
    """委托给 cli/main.py"""
    from cli.main import main as _cli_main
    return _cli_main(argv)


if __name__ == "__main__":
    sys.exit(main())
