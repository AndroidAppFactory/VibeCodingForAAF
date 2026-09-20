"""replay-core 统一 CLI 框架

四端共享的命令结构定义。各端只需：
1. import build_parser
2. 注册平台专有参数（--device 等）
3. 绑定各子命令的 handler
"""

from __future__ import annotations

import argparse
from typing import Callable, Optional


def build_parser(
    platform: str,
    *,
    description: str = "",
    add_platform_args: Optional[Callable[[argparse.ArgumentParser, str], None]] = None,
) -> argparse.ArgumentParser:
    """构建统一的 CLI parser

    Args:
        platform: 平台名（adb/web/win/mac）
        description: 顶层描述
        add_platform_args: 回调，给特定子命令追加平台专有参数
            签名：(sub_parser, sub_command_name) -> None
    """
    prog = f"zk replay {platform}"
    parser = argparse.ArgumentParser(
        prog=prog,
        description=description or f"ZixieKit {platform.upper()} Replay",
    )
    subs = parser.add_subparsers(dest="command", help="子命令")

    # ── record ──
    p_record = subs.add_parser("record", help="录制（素材 → ZIXIEKIT_TMP，自动命名）")
    if add_platform_args:
        add_platform_args(p_record, "record")

    # ── play ──
    p_play = subs.add_parser("play", help="回放素材确认")
    p_play.add_argument("target", help="录制目录路径或名称")
    p_play.add_argument("--speed", type=float, default=1.0, help="速度倍率（默认 1.0）")
    p_play.add_argument("--max-delay", type=float, default=None, help="单步等待上限（秒，超过则截断）")
    p_play.add_argument("--repeat", "-r", type=int, default=1, help="重复次数（默认 1）")
    p_play.add_argument("--screenshot-duration", type=float, default=1.0, help="截图间隔秒数（默认 1.0）")
    if add_platform_args:
        add_platform_args(p_play, "play")

    # ── flow ──
    p_flow = subs.add_parser("flow", help="Flow 管理与运行")
    flow_subs = p_flow.add_subparsers(dest="flow_command", help="flow 子命令")

    # flow run
    p_run = flow_subs.add_parser("run", help="运行 Flow")
    p_run.add_argument("id", help="Flow ID")
    p_run.add_argument("--speed", type=float, default=1.0, help="速度倍率")
    p_run.add_argument("--max-delay", type=float, default=None, help="单步等待上限（秒，超过则截断）")
    p_run.add_argument("--step", type=str, default=None, help="步骤选择（如 1,3,5-8）")
    p_run.add_argument("--fail-fast", action="store_true", help="遇错即停")
    p_run.add_argument("--rerun", action="store_true", help="复用上次目录重跑")
    p_run.add_argument("--no-notify", action="store_true", help="跳过所有通知（文本 + 图片）")
    if add_platform_args:
        add_platform_args(p_run, "flow_run")

    # flow report
    p_freport = flow_subs.add_parser("report", help="重新生成 Flow 报告")
    p_freport.add_argument("id", help="Flow ID")
    p_freport.add_argument("--layout", choices=["compare", "order"], default="order",
                           help="关键图拼图布局：order=按执行顺序排列（默认），compare=相同步骤前后对比")

    # ── init ──
    p_init = subs.add_parser("init", help="初始化环境（安装平台依赖：adb:zinput / web:playwright）")
    if add_platform_args:
        add_platform_args(p_init, "init")

    # ── doctor ──
    p_doctor = subs.add_parser("doctor", help="环境检查")
    if add_platform_args:
        add_platform_args(p_doctor, "doctor")

    # ── install ──
    p_install = subs.add_parser("install", help="安装平台依赖（adb:zinput / web:playwright）")
    if add_platform_args:
        add_platform_args(p_install, "install")

    # ── report ──
    p_report = subs.add_parser("report", help="对已有运行产物重生成报告")
    p_report.add_argument("run_dir", help="运行产物目录路径")
    p_report.add_argument("--layout", choices=["compare", "order"], default="order",
                          help="关键图拼图布局：order=按执行顺序排列（默认），compare=相同步骤前后对比")

    # ── edit ──
    p_edit = subs.add_parser("edit", help="打开录制素材编辑器（Web 管理界面）")
    p_edit.add_argument("target", nargs="?", default=None, help="录制目录路径（可选，默认打开编辑器首页）")
    if add_platform_args:
        add_platform_args(p_edit, "edit")

    return parser


def parse_step_indices(step_str: str) -> list[int]:
    """解析 --step 参数为步骤序号列表

    支持格式：1,3,5-8 → [1, 3, 5, 6, 7, 8]
    """
    if not step_str:
        return []
    indices = []
    for part in step_str.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            indices.extend(range(int(a), int(b) + 1))
        else:
            indices.append(int(part))
    return sorted(set(indices))


# ── 统一输出格式 ──


def print_banner_start(name: str, steps: int, device: str, run_dir: str, note: str = "") -> None:
    """运行开始 banner"""
    print(f"\n{'═' * 50}")
    print(f"🚀 运行: {name} {note}")
    print(f"   设备: {device}")
    print(f"   步骤: {steps}")
    print(f"   产物: {run_dir}")
    print(f"{'═' * 50}\n")


def print_banner_end(success: int, total: int, report_path: str = "") -> None:
    """运行结束 banner"""
    icon = "✅" if success == total else "⚠️"
    print(f"\n{'═' * 50}")
    print(f"{icon} 完成: {success}/{total} 成功")
    if report_path:
        print(f"   报告: {report_path}")
    print(f"{'═' * 50}")


# ── 视频合成脚本生成 ──


def generate_merge_video_script(base_dir: str, media_paths: list, screenshot_duration: float = 1) -> str | None:
    """生成 merge_video.sh，将截图+录屏合成为 replay.mp4。

    Args:
        base_dir:     产物根目录（脚本写入 base_dir/merge_video.sh）
        media_paths:  [(full_path, is_video), ...] 媒体文件列表
        screenshot_duration: 截图停留秒数
    Returns:
        生成的脚本路径，没有媒体时返回 None
    """
    import os
    from pathlib import Path

    if not media_paths:
        return None

    base = Path(base_dir)
    img_count = sum(1 for _, is_vid in media_paths if not is_vid)
    video_count = sum(1 for _, is_vid in media_paths if is_vid)

    script_file = base / "merge_video.sh"
    tmp_dir = base / "tmp_segments"
    concat_list = base / "concat_list.txt"
    output_mp4 = base / "replay.mp4"

    with open(script_file, "w", encoding="utf-8") as sf:
        sf.write("#!/bin/bash\n")
        sf.write("# 自动生成的视频合成脚本（截图+录屏 → replay.mp4）\n")
        sf.write("set -e\n\n")
        sf.write(f'RECORD_DIR="{base}"\n')
        sf.write(f'TMP_DIR="{tmp_dir}"\n')
        sf.write(f'CONCAT_LIST="{concat_list}"\n')
        sf.write(f'OUTPUT="{output_mp4}"\n\n')
        sf.write(f'SCREENSHOT_DURATION=${{SCREENSHOT_DURATION:-{screenshot_duration}}}\n\n')
        sf.write('mkdir -p "$TMP_DIR"\n')
        sf.write('rm -f "$CONCAT_LIST"\n\n')

        first_media = media_paths[0][0] if media_paths else ""
        sf.write("# 获取统一分辨率（取第一个媒体文件的尺寸）\n")
        if first_media.endswith((".mp4", ".webm")):
            sf.write(f"RESOLUTION=$(ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of csv=p=0 '{first_media}' | head -1)\n")
        else:
            sf.write(f"RESOLUTION=$(ffprobe -v error -show_entries stream=width,height -of csv=p=0 '{first_media}' | head -1)\n")
        sf.write('WIDTH=$(echo $RESOLUTION | cut -d"," -f1)\n')
        sf.write('HEIGHT=$(echo $RESOLUTION | cut -d"," -f2)\n')
        sf.write("WIDTH=$((WIDTH / 2 * 2))\n")
        sf.write("HEIGHT=$((HEIGHT / 2 * 2))\n")
        sf.write('echo "统一分辨率: ${WIDTH}x${HEIGHT}"\n\n')

        for i, (path, is_video) in enumerate(media_paths):
            segment_name = f"seg_{i:04d}.mp4"
            segment_path = f"$TMP_DIR/{segment_name}"
            if is_video:
                sf.write(f"# 片段 {i}: 录屏\n")
                sf.write(f'ffmpeg -y -i \'{path}\' -vf "scale=${{WIDTH}}:${{HEIGHT}}:force_original_aspect_ratio=decrease,pad=${{WIDTH}}:${{HEIGHT}}:(ow-iw)/2:(oh-ih)/2" -c:v libx264 -pix_fmt yuv420p -an "{segment_path}" 2>/dev/null\n')
            else:
                sf.write(f"# 片段 {i}: 截图（$SCREENSHOT_DURATION 秒）\n")
                sf.write(f'ffmpeg -y -loop 1 -i \'{path}\' -t $SCREENSHOT_DURATION -vf "scale=${{WIDTH}}:${{HEIGHT}}:force_original_aspect_ratio=decrease,pad=${{WIDTH}}:${{HEIGHT}}:(ow-iw)/2:(oh-ih)/2" -c:v libx264 -pix_fmt yuv420p "{segment_path}" 2>/dev/null\n')
            sf.write(f'echo "file \'{tmp_dir}/{segment_name}\'" >> "$CONCAT_LIST"\n\n')

        sf.write("# 拼接所有片段\n")
        sf.write('echo "正在拼接..."\n')
        sf.write('ffmpeg -y -f concat -safe 0 -i "$CONCAT_LIST" -c copy "$OUTPUT"\n\n')
        sf.write("# 清理临时文件\n")
        sf.write('rm -rf "$TMP_DIR" "$CONCAT_LIST"\n\n')
        sf.write('echo "✅ 合成完成: $OUTPUT"\n')

    os.chmod(script_file, 0o755)
    print(f"   合成脚本: merge_video.sh ({img_count} 张截图, {video_count} 个录屏)")
    return str(script_file)


# ── 后续命令提示（双格式：zk + python3）──


def _tip(icon: str, label: str) -> None:
    """提示标题行：emoji + 标题（命令在下一行，避免 emoji 宽度影响对齐）"""
    print(f"{icon} {label}")


def _cmd(command: str) -> None:
    """命令行：统一 3 空格缩进"""
    print(f"   {command}")


def _format_step_indices(indices: list) -> str:
    """把步骤序号列表转回 --step 参数格式（连续区间合并、逗号分隔）。"""
    s = sorted(set(indices))
    ranges = []
    start = prev = s[0]
    for i in s[1:]:
        if i == prev + 1:
            prev = i
        else:
            ranges.append(f"{start}-{prev}" if start != prev else str(start))
            start = prev = i
    ranges.append(f"{start}-{prev}" if start != prev else str(start))
    return ",".join(ranges)


def build_run_command(flow_id: str, *,
                      speed: float = 1.0, max_delay: float | None = None,
                      step_indices: list | None = None,
                      fail_fast: bool = False, rerun: bool = False) -> str:
    """构造完整的 flow run 命令（含非默认运行时参数）。

    平台由 `zk replay run` 根据 Flow 的 platform 字段自动解析，无需显式指定。
    """
    fid = flow_id[:4] if len(flow_id) > 4 else flow_id
    parts = [f"zk replay run {fid}"]
    if speed and abs(speed - 1.0) > 1e-9:
        parts.append(f"--speed {speed:g}")
    if max_delay is not None:
        parts.append(f"--max-delay {max_delay:g}")
    if step_indices:
        parts.append(f"--step {_format_step_indices(step_indices)}")
    if fail_fast:
        parts.append("--fail-fast")
    if rerun:
        parts.append("--rerun")
    return " ".join(parts)


def tips_after_record(platform: str, record_dir: str, script_path: str = "") -> None:
    """录制结束后的提示"""
    print(f"\n💡 后续命令：")
    _tip("▶️", "回放确认")
    _cmd(f"zk replay play {record_dir}")
    if script_path:
        _cmd(f"python3 {script_path} play {record_dir}")
    _tip("✏️", "编辑")
    _cmd(f"zk replay edit {record_dir}")
    if script_path:
        _cmd(f"python3 {script_path} edit {record_dir}")
    _tip("🖥️", "管理器")
    _cmd("zk replay manage")
    if script_path:
        _cmd(f"python3 {script_path} flow manage")


def tips_after_play(platform: str, record_dir: str, script_path: str = "") -> None:
    """回放确认后的提示"""
    print(f"\n💡 后续命令：")
    _tip("▶️", "再次回放")
    _cmd(f"zk replay play {record_dir}")
    if script_path:
        _cmd(f"python3 {script_path} play {record_dir}")
    _tip("✏️", "编辑")
    _cmd(f"zk replay edit {record_dir}")
    if script_path:
        _cmd(f"python3 {script_path} edit {record_dir}")
    _tip("🖥️", "管理器")
    _cmd("zk replay manage  （发布为 Flow / 编辑）")
    if script_path:
        _cmd(f"python3 {script_path} flow manage")


def tips_after_flow_run(platform: str, flow_id: str, script_path: str = "", report_path: str = "", merge_script: str = "") -> None:
    """Flow 运行结束后的提示"""
    import os
    # mixed 模式下子 flow 的「再次运行」会指向子 flow 而非 mixed flow，误导用户；由 mixed 主进程统一提示
    if os.environ.get("REPLAY_MIXED_MODE") == "1":
        return
    fid = flow_id[:4] if len(flow_id) > 4 else flow_id
    print(f"\n💡 后续命令:")
    _tip("▶️", "再次运行")
    _cmd(f"zk replay run {fid}")
    if script_path:
        _cmd(f"python3 {script_path} flow run {fid}")
    _tip("📊", "重新生成报告")
    _cmd(f"按顺序（默认）: zk replay report {fid}")
    _cmd(f"前后对比: zk replay report {fid} --layout compare")
    if script_path:
        _cmd(f"python3 {script_path} flow report {fid}")
        _cmd(f"python3 {script_path} flow report {fid} --layout compare")
    _tip("🖥️", "管理器")
    _cmd("zk replay manage")
    if script_path:
        _cmd(f"python3 {script_path} flow manage")
    if report_path:
        _tip("📂", "打开报告")
        _cmd(f"open {report_path}")
    if merge_script:
        _tip("🎬", "合成视频")
        _cmd(f"bash {merge_script}")
    _tips_runs_cleanup()


def _tips_runs_cleanup(threshold_mb: int = 1024) -> None:
    """Flow 运行结束后检查：运行记录占用磁盘超过阈值时提醒清理"""
    import os
    from core.config import FLOW_RUNS_DIR

    if not FLOW_RUNS_DIR.exists():
        return
    total = _dir_size(FLOW_RUNS_DIR)
    if total > threshold_mb * 1024 * 1024:
        print(f"\n🧹 运行记录占用 {_fmt_size(total)}（> {threshold_mb} MB），建议清理:")
        print(f"   zk replay clean --days 7 --yes")
        print(f"   （或先 zk replay clean 做 dry-run 预览）")


def _dir_size(d) -> int:
    """目录总大小（字节），纯 Python os.walk 遍历，跨平台无外部依赖"""
    import os
    total = 0
    for root, _dirs, files in os.walk(d):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _fmt_size(n: int) -> str:
    """字节数格式化为可读单位"""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{int(n)} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def tips_after_flow_manage(platform: str, flow_id: str = "", script_path: str = "") -> None:
    """管理器关闭后的提示"""
    print(f"\n💡 后续命令:")
    if flow_id:
        fid = flow_id[:4] if len(flow_id) > 4 else flow_id
        _tip("▶️", "运行 Flow")
        _cmd(f"zk replay run {fid}")
        if script_path:
            _cmd(f"python3 {script_path} flow run {fid}")
    _tip("🎬", "录制")
    _cmd("zk replay record {adb|web|win}")
    if script_path:
        _cmd(f"python3 {script_path} record")


def tips_after_flow_save(flow_id: str) -> None:
    """Flow 保存后的提示（从 Web 管理界面保存时输出到终端）"""
    from core.config import SCRIPTS_DIR
    fid = flow_id[:4] if len(flow_id) > 4 else flow_id
    print(f"\n💡 后续命令：")
    _tip("▶️", "运行 Flow")
    _cmd(f"zk replay run {fid}")
    _cmd(f"python3 {SCRIPTS_DIR}/{{adb|web|win|mac}}/cli/main.py flow run {fid}")
    _tip("✏️", "继续编排")
    _cmd("zk replay manage")
    _cmd(f"python3 {SCRIPTS_DIR}/{{adb|web|win|mac}}/cli/main.py flow manage")


def tips_report_layout(fid: str) -> None:
    """report 命令结果末尾：提示两种拼图布局模式"""
    from core.config import SCRIPTS_DIR
    _tip("🔄", "切换布局")
    _cmd(f"按顺序（默认）: zk replay report {fid} --layout order")
    _cmd(f"前后对比: zk replay report {fid} --layout compare")
    _cmd(f"python3 {SCRIPTS_DIR}/{{adb|web|win|mac}}/cli/main.py flow report {fid} --layout order")
    _cmd(f"python3 {SCRIPTS_DIR}/{{adb|web|win|mac}}/cli/main.py flow report {fid} --layout compare")


# ── 日志工具 ──


def log_error(msg: str, detail: str = "") -> None:
    """统一错误日志格式（支持定位异常原因）"""
    print(f"❌ {msg}")
    if detail:
        print(f"   原因: {detail}")


def log_warning(msg: str) -> None:
    """统一警告日志"""
    print(f"⚠️  {msg}")


def log_info(msg: str) -> None:
    """统一信息日志"""
    print(f"ℹ️  {msg}")


def log_success(msg: str) -> None:
    """统一成功日志"""
    print(f"✅ {msg}")
