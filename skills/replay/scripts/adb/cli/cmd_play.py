"""adb-replay CLI：回放命令"""

from __future__ import annotations

import argparse
from pathlib import Path

from adb_core.config import REPLAY_DIR, SCRIPTS_DIR
from adb_core.player import play
from cli.utils import list_recordings
from core.cli import tips_after_play


def cmd_play(args: argparse.Namespace) -> int:
    """回放操作 — 直接调用 core.player.play()"""
    target_dir = args.target

    if not target_dir:
        recordings = list_recordings()
        if not recordings:
            print("⚠️  没有找到录制文件")
            print(f"   目录: {REPLAY_DIR}")
            return 1

        print("📂 本地录制：\n")
        for i, rec in enumerate(recordings, 1):
            log_mark = "📋" if rec["has_log"] else "  "
            shot_mark = "📸" if rec["has_screenshots"] else "  "
            print(f"  {i}. {rec['name']}"
                  f"（{rec['event_count']} 个事件，{rec['device']}）{log_mark}{shot_mark}")

        print(f"\n  {len(recordings) + 1}. 输入自定义目录路径")
        print()

        try:
            choice = input("请选择序号: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n取消")
            return 0

        if not choice.isdigit():
            print("❌ 无效输入")
            return 1

        idx = int(choice)
        if idx == len(recordings) + 1:
            try:
                target_dir = input("请输入目录路径: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n取消")
                return 0
        elif 1 <= idx <= len(recordings):
            target_dir = recordings[idx - 1]["path"]
        else:
            print("❌ 序号超出范围")
            return 1

    if not target_dir:
        print("❌ 未指定目录")
        return 1

    target_path = Path(target_dir).resolve()
    data_file = target_path / "data.json"

    if not target_path.exists() or not target_path.is_dir():
        print(f"❌ 目录不存在: {target_dir}")
        return 1
    if not data_file.exists():
        print(f"❌ 目录中没有 data.json: {target_dir}")
        return 1

    try:
        play(str(target_path), speed=args.speed or 1.0, device=args.device,
             max_delay=getattr(args, "max_delay", None),
             repeat=args.repeat or 1, screenshot=not args.no_screenshot,
             screenshot_duration=args.screenshot_duration or 1)
        returncode = 0
    except KeyboardInterrupt:
        print("\n⏹️  回放已中断")
        returncode = 0
    except Exception as e:
        print(f"❌ 回放异常: {e}")
        returncode = 1

    if returncode == 0:
        script_path = SCRIPTS_DIR / "adb_replay.py"
        screenshots_dir = target_path / "screenshots"
        print()
        print("=" * 50)
        tips_after_play("adb", str(target_path), str(script_path))
        if not args.no_screenshot and screenshots_dir.exists():
            merge_script = target_path / "merge_video.sh"
            print()
            print("  🎬 合成回放视频（截图+录屏）：")
            print(f"     bash '{merge_script}'")
        print("=" * 50)

    return returncode
