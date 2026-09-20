"""install/doctor 子命令 —— web-replay 环境安装与检查"""

import subprocess
import sys


# ── install：安装 Playwright ──


def cmd_install(args) -> int:
    """安装 web-replay 依赖（Playwright + 浏览器）"""
    from core.cli import log_success, log_error, log_info
    import shutil

    log_info("安装 Playwright...")
    # pipx 管理的环境用 pipx inject，否则用 pip3
    if shutil.which("pipx") and "pipx" in sys.executable:
        pip_cmd = ["pipx", "inject", "zixiekit", "playwright"]
    else:
        pip_cmd = ["python3", "-m", "pip", "install", "playwright"]

    try:
        result = subprocess.run(
            pip_cmd, capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log_error("pip install playwright 失败", result.stderr.strip())
            return 1
        log_success("playwright 包已安装")
    except subprocess.TimeoutExpired:
        log_error("安装超时")
        return 1

    # playwright install chromium
    log_info("安装 Chromium 浏览器...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            log_error("playwright install chromium 失败", result.stderr.strip())
            return 1
        log_success("Chromium 已安装")
    except subprocess.TimeoutExpired:
        log_error("浏览器安装超时（300s）")
        return 1

    log_success("安装完成！")
    return 0


# ── doctor：环境检查 ──


def cmd_doctor(args) -> int:
    """检查 web-replay 运行环境"""
    from core.cli import log_success, log_error, log_warning

    print("🔍 环境检查...")

    # 1. playwright 模块
    try:
        import playwright  # noqa: F401
        log_success("playwright 模块可用")
    except ImportError:
        log_error("playwright 未安装")
        print(f"   安装命令: zk replay init web")
        return 1

    # 2. chromium 浏览器
    try:
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True, text=True, timeout=10,
        )
        # dry-run 成功表示已安装（部分版本不支持 --dry-run，fallback）
        if result.returncode == 0:
            log_success("Chromium 浏览器可用")
        else:
            log_warning("Chromium 可能未安装")
            print(f"   安装命令: zk replay init web")
    except Exception:
        # fallback：直接尝试 launch
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                b = p.chromium.launch(headless=True)
                b.close()
            log_success("Chromium 浏览器可用（launch 验证通过）")
        except Exception as e:
            log_error("Chromium 不可用", str(e))
            print(f"   安装命令: zk replay init web")
            return 1

    log_success("环境检查完成")
    return 0
