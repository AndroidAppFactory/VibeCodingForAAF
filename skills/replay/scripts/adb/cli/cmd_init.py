"""install/doctor 子命令 —— adb-replay 环境安装与检查"""

import subprocess
import sys
import urllib.request

ZINPUT_URL = "https://android.bihe0832.com/app/release/ZINPUT_official.apk"


# ── install：安装平台依赖 ──


def cmd_install(args) -> int:
    """安装 adb-replay 依赖（ZINPUT 输入法）"""
    return _install_zinput(args)


# ── doctor：环境检查 ──


def cmd_doctor(args) -> int:
    """检查 adb-replay 运行环境"""
    import adb_tools
    from core.cli import log_success, log_error

    device = getattr(args, "device", None)
    print("🔍 环境检查...")

    # 1. ADB 连接
    if not adb_tools.ensure_adb_ready(device, verbose=False):
        log_error("ADB 连接不可用", "请检查设备连接和 USB 调试开关")
        return 1
    model, _ = adb_tools.get_device_info(device)
    log_success(f"ADB 连接正常 · 设备: {model}")

    # 2. ZINPUT 是否已安装
    adb = adb_tools.get_adb_cmd(device)
    result = subprocess.run(adb + ["shell", "pm", "list", "packages", "com.bihe0832.adb.input"],
                            capture_output=True, text=True, timeout=10)
    if "com.bihe0832.adb.input" in result.stdout:
        log_success("ZINPUT 输入法已安装")
    else:
        from core.cli import log_warning
        log_warning("ZINPUT 输入法未安装（中文输入需要）")
        print(f"   安装命令: zk replay install adb")

    log_success("环境检查完成")
    return 0


# ── 兼容旧入口 ──


def _install_zinput(args) -> int:
    """下载 ZINPUT APK 并安装到设备"""
    from adb_core.config import REPLAY_DIR
    import adb_tools

    device = getattr(args, "device", None)

    # 1. 检查 ADB 连接
    print("🔍 检查 ADB 连接...")
    if not adb_tools.ensure_adb_ready(device, verbose=True):
        print("❌ ADB 连接不可用，请检查设备", file=sys.stderr)
        return 1

    adb = adb_tools.get_adb_cmd(device)
    model, _ = adb_tools.get_device_info(device)
    print(f"   ✅ 设备: {model}")

    # 2. 下载 APK
    cache_dir = REPLAY_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    apk_path = cache_dir / "ZINPUT_official.apk"

    print(f"\n📥 下载 ZINPUT...")
    print(f"   URL: {ZINPUT_URL}")
    try:
        urllib.request.urlretrieve(ZINPUT_URL, str(apk_path), _download_progress)
        print()  # 换行
    except Exception as e:
        print(f"\n❌ 下载失败: {e}", file=sys.stderr)
        return 1

    print(f"   ✅ 已下载: {apk_path} ({apk_path.stat().st_size / 1024 / 1024:.1f}MB)")

    # 3. 安装 APK
    print(f"\n📦 安装 ZINPUT...")
    try:
        result = subprocess.run(
            adb + ["install", "-r", str(apk_path)],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            print("   ✅ 安装成功")
        else:
            print(f"   ❌ 安装失败: {result.stderr.strip() or result.stdout.strip()}", file=sys.stderr)
            return 1
    except subprocess.TimeoutExpired:
        print("   ❌ 安装超时（120s）", file=sys.stderr)
        return 1

    print("\n✅ 初始化完成！ZINPUT 输入法已安装。")
    print("   提示: 请在手机「设置 → 语言和输入法」中启用 ZINPUT")
    return 0


def _download_progress(block_num: int, block_size: int, total_size: int) -> None:
    """下载进度回调"""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, downloaded * 100 // total_size)
        bar = "█" * (percent // 5) + "░" * (20 - percent // 5)
        print(f"\r   [{bar}] {percent}%", end="", flush=True)
