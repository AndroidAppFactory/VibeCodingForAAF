"""win-replay install/doctor 子命令"""


def cmd_install(args) -> int:
    """安装 win-replay 依赖"""
    from core.cli import log_info, log_success, log_error
    import subprocess, sys, shutil

    log_info("安装 pynput / pillow...")
    # pipx 管理的环境用 pipx inject，否则用 pip3
    if shutil.which("pipx") and "pipx" in sys.executable:
        pip_cmd = ["pipx", "inject", "zixiekit", "pynput", "pillow"]
    else:
        pip_cmd = ["python3", "-m", "pip", "install", "pynput", "pillow"]

    result = subprocess.run(pip_cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        log_error("安装失败", result.stderr.strip())
        return 1
    log_success("依赖已安装（pynput + pillow）")
    return 0


def cmd_doctor(args) -> int:
    """检查 win-replay 环境"""
    from core.cli import log_success, log_error

    print("🔍 环境检查...")
    try:
        import pynput  # noqa: F401
        log_success("pynput 可用")
    except ImportError:
        log_error("pynput 未安装", "运行: zk replay init win")
        return 1
    try:
        from PIL import Image  # noqa: F401
        log_success("Pillow 可用")
    except ImportError:
        log_error("Pillow 未安装", "运行: zk replay init win")
        return 1
    log_success("环境检查完成")
    return 0
