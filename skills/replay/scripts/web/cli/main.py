"""web-replay CLI 入口（D21 统一结构）"""

from __future__ import annotations

import sys
from pathlib import Path

# scripts 目录加入 path
_scripts_dir = Path(__file__).resolve().parent.parent
if str(_scripts_dir) not in sys.path:
    sys.path.insert(0, str(_scripts_dir))

# replay-core 路径
_replay_core = Path(__file__).resolve().parents[3] / "scripts"
if str(_replay_core) not in sys.path:
    sys.path.insert(0, str(_replay_core))


def _add_web_args(sub_parser, sub_command: str) -> None:
    """给 web 平台子命令追加专有参数"""
    if sub_command == "record":
        sub_parser.add_argument("--url", help="起始 URL")
        sub_parser.add_argument("--profile", help="持久化浏览器 profile 路径")
    if sub_command == "play":
        sub_parser.add_argument("--headless", action="store_true", help="无头模式")
        sub_parser.add_argument("--timeout", type=int, default=30, help="元素等待超时（秒，默认 30）")
    if sub_command == "flow_run":
        sub_parser.add_argument("--headless", action="store_true", help="无头模式")
        sub_parser.add_argument("--timeout", type=int, default=30, help="元素等待超时（秒，默认 30）")


def main(argv: list[str] | None = None) -> int:
    from core.cli import build_parser, parse_step_indices

    parser = build_parser(
        "web",
        description="ZixieKit Web Replay - 录制/回放/编排",
        add_platform_args=_add_web_args,
    )
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "record":
        from cli.cmd_record import cmd_record
        return cmd_record(args)

    elif args.command == "play":
        from cli.cmd_play import cmd_play
        return cmd_play(args)

    elif args.command == "flow":
        if not args.flow_command:
            parser.parse_args(["flow", "--help"])
            return 1

        if args.flow_command == "run":
            from cli.cmd_flow import cmd_flow_run
            step_indices = None
            if args.step:
                step_indices = parse_step_indices(args.step)
                if not args.rerun:
                    args.rerun = True
            args.step_indices = step_indices
            return cmd_flow_run(args)

        elif args.flow_command == "report":
            from cli.cmd_flow import cmd_flow_report
            return cmd_flow_report(args)

    elif args.command == "init":
        from cli.cmd_doctor import cmd_install
        return cmd_install(args)

    elif args.command == "install":
        from cli.cmd_doctor import cmd_install
        return cmd_install(args)

    elif args.command == "doctor":
        from cli.cmd_doctor import cmd_doctor
        return cmd_doctor(args)

    elif args.command == "report":
        from cli.cmd_flow import cmd_report_rerun
        return cmd_report_rerun(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
