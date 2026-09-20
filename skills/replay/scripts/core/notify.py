"""replay-core 通知模块

统一的通知发送（企业微信 webhook）。静默容错——任何失败不影响主流程。
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import notify as _notify_impl
except ImportError:
    _notify_impl = None


def _notify_key() -> Optional[str]:
    """从环境变量获取企业微信 webhook key"""
    return os.environ.get("WECOM_KEY_PUBLIC") or None


def notify_safe(title: str, message: str = "", level: str = "info") -> None:
    """静默发送文本通知，任何失败均不影响主流程

    title 已由 snapshot_title/_title 携带状态 icon（✅/🚀/⚠️），
    因此这里不再透传 level 给 send_notification 追加 level_icon，避免双重 icon。
    """
    if not _notify_impl:
        return
    try:
        _notify_impl.send_notification(title, message, None, key=_notify_key())
    except Exception:
        pass


def notify_image_safe(image_path: Optional[Path] = None) -> None:
    """静默发送图片消息，任何失败均不影响主流程（notify 库内置压缩）"""
    if not _notify_impl or not image_path:
        return
    try:
        _notify_impl.send_image(str(image_path), key=_notify_key())
    except Exception:
        pass


def snapshot_title(
    flow_name: str,
    device: str = "",
    started_at: str = "",
    status: str = "",
    platform: str = "",
) -> str:
    """生成通知标题（执行时间已移除；执行机器/运行设备保留在标题）

    格式：🚀 🤖 【开始 - ADB】{flow}    执行机器：{host}    运行设备：{device}
    """
    from core.report import _get_local_hostname

    host = _get_local_hostname()
    plat = platform.upper() or "REPLAY"

    icon = {"开始": "🚀", "结束": "✅", "失败": "⚠️"}.get(status, "ℹ️")
    label = f"{icon} 🤖 【{status} - {plat}】" if status else f"ℹ️ 🤖 {plat}"
    title = f"{label}{flow_name}    执行机器：{host}"
    if device:
        title += f"    运行设备：{device}"
    return title


def build_notify_message(
    message: str,
    *,
    started_at: str = "",
    command: str = "",
) -> str:
    """构造通知正文：执行命令 + 任务情况 + 任务耗时（结束/失败/中断通知）。

    message 通常是「N/M 成功」或「共 N 步」，会加上「任务情况：」前缀。
    started_at 非空时（结束/失败/中断通知）追加任务耗时（开始 → 当前时间）。
    """
    from core.report import _format_started_at

    lines = []
    if command:
        lines.append(f"执行命令：{command}")
    if message:
        lines.append(f"任务情况：{message}")
    if started_at:
        ts_start = _format_started_at({"started_at": started_at})
        end = datetime.now()
        ts_end = end.strftime("%Y-%m-%d %H:%M:%S")
        try:
            start_dt = datetime.fromisoformat(started_at)
            secs = int((end - start_dt).total_seconds())
            m, s = divmod(max(0, secs), 60)
            duration = f"{m}分{s}秒" if m > 0 else f"{s}秒"
            lines.append(f"任务耗时：{duration}（{ts_start} - {ts_end}）")
        except (ValueError, TypeError):
            pass
    return "\n".join(lines)
