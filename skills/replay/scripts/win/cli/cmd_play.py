"""win-replay play 子命令"""

from pathlib import Path


def cmd_play(args) -> int:
    """回放 win 录制素材"""
    from win_flow_runner import run_flow_by_name
    from core.cli import tips_after_play, log_error

    target = args.target
    speed = getattr(args, "speed", 1.0)
    max_delay = getattr(args, "max_delay", None)

    # win play 直接调用 run_flow_by_name（素材即 flow）
    try:
        run_flow_by_name(target, speed=speed, max_delay=max_delay)
    except Exception as e:
        log_error("回放失败", str(e))
        return 1

    script = str(Path(__file__).resolve().parents[1] / "win_replay.py")
    tips_after_play("win", target, script_path=script)
    return 0
