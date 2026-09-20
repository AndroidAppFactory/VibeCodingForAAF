#!/usr/bin/env python3
"""ZixieKit 通用通知模块

通过企业微信 Webhook 发送通知，任何脚本/插件均可调用。

用法（CLI）：
    python3 scripts/notify.py --title "AI_NAME missing" --message "请检查平台运行时注入"
    python3 scripts/notify.py --image /path/to/pic.png  # 发送图片（JPG/PNG，≤2MB）
    python3 scripts/notify.py --title "xxx" --key <webhook_key>   # 外部直传 key

用法（Python import）：
    from notify import send_notification, send_image, compress_for_wecom
    send_notification("AI_NAME missing", "请检查平台运行时注入")
    send_image("/path/to/pic.png")
    send_notification("xxx", key="w-xxx")            # 外部直传 key，用于区分通知去向
    compressed = compress_for_wecom("/path/to/big.png")  # 压缩到 ≤2MB，不覆盖源文件

环境依赖：
    WECOM_KEY — 默认企业微信 Webhook key（从 ~/.zixiekit/secrets.env 加载）

key 解析优先级：显式传入的 key 参数 > 默认 WECOM_KEY。
若调用方需要按业务/场景使用不同 key（如私人群 vs 工作群），应自行读取对应环境变量
（如 WECOM_KEY_PUBLIC）后通过 key 参数显式传入，本模块不再内置渠道查找逻辑。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ─── 环境变量加载 ──────────────────────────────────────────────────────────────

# 复用 bootstrap.load_env（.env + secrets.env + 实例 target），与其它脚本统一。
# 先把本文件所在目录（scripts/）加入 sys.path，确保 bootstrap 可 import。
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from bootstrap import load_env  # pyright: ignore[reportImplicitRelativeImport]
    load_env()
except ImportError:
    pass  # bootstrap 不可用（极端场景），密钥依赖 os.environ 或外部注入

WECOM_KEY = os.environ.get("WECOM_KEY", "")
WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"


# ─── 内部工具 ──────────────────────────────────────────────────────────────────

# 企业微信 Webhook image 类型限制：仅 JPG/PNG，单张 ≤2MB（base64 编码前），不能为 0 字节
_IMAGE_MAX_BYTES = 2 * 1024 * 1024
_IMAGE_ALLOWED_SUFFIXES = (".jpg", ".jpeg", ".png")


def _resolve_key(key: str | None = None) -> str:
    """解析当前通知应使用的 Webhook key：显式传入的 key 优先，否则回退默认 WECOM_KEY。"""
    return key or WECOM_KEY


_WEBHOOK_RETRIES = 2  # 网络类异常的重试次数（不针对业务错误）


def _post_webhook(payload: dict[str, Any], key: str) -> bool:
    """向企业微信 Webhook POST payload，统一处理请求与错误。

    对连接类异常（如 WinError 10053「软件中止连接」、超时、连接重置）做有限重试：
    这类错误通常由本地防火墙/安全软件/VPN 在传输较大 body 时间歇性中断连接导致，
    大 body（图片消息）比小 body（文字消息）更易触发。重试后多数可成功。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    url = f"{WEBHOOK_URL}?key={key}"
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )

    last_err: Exception | None = None
    for attempt in range(_WEBHOOK_RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("errcode") == 0:
                    return True
                print(f"❌ notify: Webhook 返回错误: {result}", file=sys.stderr)
                return False
        except urllib.error.HTTPError as e:
            # 服务端明确拒绝（4xx/5xx），重试无意义
            print(f"❌ notify: Webhook HTTP 错误: {e}", file=sys.stderr)
            return False
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            if attempt < _WEBHOOK_RETRIES:
                wait = 1.5 * (attempt + 1)
                print(f"⚠️  notify: Webhook 连接异常（第 {attempt + 1} 次），{wait:.1f}s 后重试: {e}", file=sys.stderr)
                time.sleep(wait)
                continue
    print(f"❌ notify: Webhook 请求失败（已重试 {_WEBHOOK_RETRIES} 次）: {last_err}", file=sys.stderr)
    return False


# ─── 公共 API ──────────────────────────────────────────────────────────────────


def send_notification(title: str, message: str = "", level: str = "info",
                       key: str | None = None) -> bool:
    """发送企业微信通知。

    Args:
        title: 通知标题
        message: 通知正文（可选）
        level: 级别 — info/warning/error（影响图标前缀）
        key: 外部直传的 Webhook key，未传入时回退默认 WECOM_KEY（可选）

    Returns:
        True 发送成功，False 失败
    """
    resolved_key = _resolve_key(key)
    if not resolved_key:
        print("⚠️  notify: WECOM_KEY 未设置，跳过通知", file=sys.stderr)
        return False

    level_icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌"}.get(level)

    content_lines = [f"{level_icon} **{title}**" if level_icon else f"**{title}**"]
    if message:
        # 多行 message 逐行进引用块，避免只有首行带 > 导致样式断裂
        content_lines.extend(f"> {line}" if line.strip() else ">" for line in message.splitlines())
    content = "\n".join(content_lines)

    payload = {
        "msgtype": "markdown",
        "markdown": {"content": content},
    }
    return _post_webhook(payload, resolved_key)


def compress_for_wecom(path: Path | str, max_bytes: int = _IMAGE_MAX_BYTES) -> Path:
    """将图片压缩到企业微信限制内：阶段一 PNG 降分辨率（无损），阶段二转 JPEG（有损兜底）。

    不覆盖源文件，压缩结果输出到同目录的 `{stem}_compressed.{ext}` 文件。
    若源文件本身已在限制内，直接返回源路径（不生成新文件）。
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"图片不存在: {path}")
    size_mb = path.stat().st_size / 1024 / 1024

    try:
        from PIL import Image
    except ImportError:
        print(f"  compress: PIL 不可用，跳过压缩", file=sys.stderr)
        return path

    img = Image.open(path)
    w, h = img.size
    print(f"  compress: {path.name} ({size_mb:.1f}MB) {w}x{h}", file=sys.stderr)
    if path.stat().st_size <= max_bytes:
        print(f"  compress: 已在限制内，跳过", file=sys.stderr)
        return path

    # 输出路径：不覆盖原文件
    out_png = path.with_stem(f"{path.stem}_compressed")

    # 阶段一：PNG 等比降分辨率（无损），自适应步长逼近 2MB
    scale = 1.0
    for _ in range(30):  # 最多 30 轮，防止死循环
        if scale < 0.19:
            break
        nw, nh = max(200, int(w * scale)), max(200, int(h * scale))
        r = img.resize((nw, nh), Image.LANCZOS)
        r.save(str(out_png), optimize=True)
        new_mb = out_png.stat().st_size / 1024 / 1024
        if new_mb <= max_bytes / 1024 / 1024:
            print(f"  compress: PNG {scale:.1%} → {nw}x{nh} ({new_mb:.1f}MB)", file=sys.stderr)
            return out_png
        # 自适应步长：文件越大降越快，越接近目标越慢
        ratio = (max_bytes / 1024 / 1024) / max(new_mb, 0.01)
        step = pow(ratio, 0.35)  # 远→大步，近→小步
        prev_scale = scale
        scale = max(0.19, scale * min(step, 0.95))  # 单步最多降 5%，防震荡
        print(f"  compress: PNG {prev_scale:.1%} → {nw}x{nh} ({new_mb:.1f}MB)  next {scale:.1%}", file=sys.stderr)

    # 阶段二：最小分辨率仍超限，转 JPEG 降画质
    out_jpg = path.with_name(f"{path.stem}_compressed.jpg")
    rgb = img.convert("RGB") if img.mode == "RGBA" else img
    nw, nh = max(200, int(w * 0.19)), max(200, int(h * 0.19))
    last = rgb.resize((nw, nh), Image.LANCZOS)
    for quality in (85, 80, 75, 70, 65, 60, 55, 50, 45, 40):
        last.save(str(out_jpg), format="JPEG", quality=quality, optimize=True)
        new_mb = out_jpg.stat().st_size / 1024 / 1024
        print(f"  compress: JPEG q={quality} → {new_mb:.1f}MB", file=sys.stderr)
        if out_jpg.stat().st_size <= max_bytes:
            out_png.unlink(missing_ok=True)
            return out_jpg
    print(f"  compress: 所有方案均超限，返回 JPEG q=40", file=sys.stderr)
    out_png.unlink(missing_ok=True)
    return out_jpg


def send_image(image_path: str, key: str | None = None) -> bool:
    """发送企业微信图片消息（参考 https://developer.work.weixin.qq.com/document/path/91880）。

    Args:
        image_path: 本地图片文件路径，仅支持 JPG/PNG，单张不超过 2MB
        key: 外部直传的 Webhook key，未传入时回退默认 WECOM_KEY（可选）

    Returns:
        True 发送成功，False 失败
    """
    resolved_key = _resolve_key(key)
    if not resolved_key:
        print("⚠️  notify: WECOM_KEY 未设置，跳过通知", file=sys.stderr)
        return False

    path = Path(image_path)
    if not path.is_file():
        print(f"❌ notify: 图片文件不存在: {image_path}", file=sys.stderr)
        return False
    if path.suffix.lower() not in _IMAGE_ALLOWED_SUFFIXES:
        print(f"❌ notify: 仅支持 JPG/PNG 格式: {image_path}", file=sys.stderr)
        return False

    image_data = path.read_bytes()
    if not image_data:
        print(f"❌ notify: 图片文件为空: {image_path}", file=sys.stderr)
        return False
    if len(image_data) > _IMAGE_MAX_BYTES:
        print(f"⚠️  notify: 图片 {path.stat().st_size / 1024 / 1024:.1f}MB，自动压缩...", file=sys.stderr)
        try:
            path = compress_for_wecom(path, _IMAGE_MAX_BYTES)
            image_data = path.read_bytes()
            if len(image_data) > _IMAGE_MAX_BYTES:
                print(f"❌ notify: 压缩后仍超 2MB: {path}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"❌ notify: 压缩失败: {e}", file=sys.stderr)
            return False

    payload = {
        "msgtype": "image",
        "image": {
            "base64": base64.b64encode(image_data).decode("utf-8"),
            "md5": hashlib.md5(image_data).hexdigest(),
        },
    }
    return _post_webhook(payload, resolved_key)


# ─── CLI 入口 ───────────────────────────────────────────────────────────────────


def main():
    import argparse

    parser = argparse.ArgumentParser(description="ZixieKit 通知发送")
    parser.add_argument("--title", type=str, default="", help="通知标题")
    parser.add_argument("--message", type=str, default="", help="通知正文")
    parser.add_argument("--image", type=str, default="",
                        help="图片文件路径（JPG/PNG，≤2MB），指定后发送图片消息而非文本")
    parser.add_argument("--level", type=str, default="info",
                        choices=["info", "warning", "error"], help="通知级别")
    parser.add_argument("--key", type=str, default="",
                        help="外部直传的 Webhook key，未指定时回退默认 WECOM_KEY")
    args = parser.parse_args()

    key = args.key or None
    if args.image:
        success = send_image(args.image, key=key)
    elif args.title:
        success = send_notification(args.title, args.message, args.level, key=key)
    else:
        parser.error("必须指定 --title 或 --image")
        return
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
