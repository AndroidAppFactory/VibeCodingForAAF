"""web-replay play 子命令"""

from __future__ import annotations

from pathlib import Path


def cmd_play(args) -> int:
    """回放 web 录制素材"""
    from web_player import run_flow_events
    from flowcore.config import RECORDINGS_DIR
    from core.cli import tips_after_play, log_error
    import json

    target = args.target
    speed = getattr(args, "speed", 1.0)
    repeat = getattr(args, "repeat", 1)
    headless = getattr(args, "headless", False)
    timeout = getattr(args, "timeout", 30)
    max_delay = getattr(args, "max_delay", None)

    # 解析录制路径
    rec_path = Path(target)
    if not rec_path.exists():
        rec_path = RECORDINGS_DIR / target
    if not rec_path.exists():
        log_error(f"录制目录不存在: {target}")
        return 1

    data_file = rec_path / "data.json"
    if not data_file.exists():
        data_file = rec_path / "events.json"
    if not data_file.exists():
        log_error(f"录制数据文件不存在: {rec_path}")
        return 1

    data = json.loads(data_file.read_text(encoding="utf-8"))
    events = data.get("events", [])
    if not events:
        log_error("录制数据中没有事件")
        return 1

    # 运行
    from core.runner import run_steps
    from core.config import FLOW_RUNS_DIR
    from datetime import datetime

    FLOW_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = FLOW_RUNS_DIR / f"play_{rec_path.name}_{ts}"

    for i in range(repeat):
        if repeat > 1:
            print(f"\n🔄 第 {i+1}/{repeat} 次回放")
        result = run_flow_events(events, run_dir, headless=headless, timeout=timeout, speed=speed, max_delay=max_delay)

    script = str(Path(__file__).resolve().parents[1] / "web_replay.py")
    tips_after_play("web", str(rec_path), script_path=script)
    return 0
