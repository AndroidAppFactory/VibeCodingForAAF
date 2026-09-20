#!/usr/bin/env python3
"""ADB 工具库

提供 adb 相关的公共功能，包括：
- ADB 命令构建
- 设备状态诊断
- 设备信息获取
- 截屏/录屏功能

注意：此模块为公共工具，位于 scripts 目录，供所有 Android 相关技能共享使用。"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

# ---------------------------------------------------------------------------
# 超时配置
# ---------------------------------------------------------------------------

_ADB_FAST_TIMEOUT = 10    # 本地快速命令（version,which）
_ADB_SHELL_TIMEOUT = 15   # adb shell 命令
_ADB_PULL_TIMEOUT = 30    # 文件拉取/推送


# ---------------------------------------------------------------------------
# 路径导入支持
# ---------------------------------------------------------------------------

def _ensure_bootstrap_import() -> None:
    """确保 bootstrap 模块已导入，用于路径查找"""
    try:
        from bootstrap import find_repo_root
    except ImportError:
        # 如果 bootstrap 不可用，尝试相对导入
        import sys
        from pathlib import Path
        script_dir = Path(__file__).parent
        sys.path.insert(0, str(script_dir))


def _adb_exists(path: str) -> bool:
    """检查 adb 可执行文件是否存在（兼容 Windows .exe/.cmd 扩展名）"""
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return True
    # Windows 上可能没有扩展名，尝试常见后缀
    for ext in ('.exe', '.bat', '.cmd'):
        if os.path.isfile(path + ext):
            return True
    return False


def get_adb_cmd(device: Optional[str] = None) -> list[str]:
    """构建 adb 命令前缀
    
    Args:
        device: 设备序列号，可选
        
    Returns:
        adb 命令前缀列表
        
    Raises:
        FileNotFoundError: 未找到 adb 命令时抛出
    """
    import shutil

    adb_path = None

    # 1. shutil.which 优先——自动识别 Windows 可执行扩展名（.exe/.bat/.cmd）
    found = shutil.which('adb')
    if found:
        adb_path = found

    # 2. 检查 ANDROID_HOME/platform-tools/adb
    if not adb_path:
        android_home = os.environ.get('ANDROID_HOME')
        if android_home:
            platform_tools_adb = os.path.join(android_home, 'platform-tools', 'adb')
            if _adb_exists(platform_tools_adb):
                adb_path = platform_tools_adb

    # 3. 遍历 PATH 手动查找（兜底）
    if not adb_path:
        for path_dir in os.environ.get('PATH', '').split(os.pathsep):
            adb_candidate = os.path.join(path_dir, 'adb')
            if _adb_exists(adb_candidate):
                adb_path = adb_candidate
                break

    # 4. 未找到，报错
    if not adb_path:
        print("❌ 未找到 adb 命令")
        print("   请确认已安装 Android SDK 并正确配置环境变量")
        print("   解决方案：")
        print("   1. 设置 ANDROID_HOME 环境变量指向 Android SDK 目录")
        print("   2. 将 $ANDROID_HOME/platform-tools 添加到 PATH 环境变量")
        print("   3. 或者直接指定 adb 的绝对路径")
        raise FileNotFoundError("adb command not found")

    cmd = [adb_path]
    if device:
        cmd.extend(["-s", device])
    return cmd


def diagnose_adb_status(device: Optional[str] = None) -> None:
    """诊断 adb 状态：端口占用、版本、位置等信息
    
    Args:
        device: 设备序列号，可选
    """
    print("🔍 ADB 诊断信息：")
    
    # 0. 先检查并自动清理 ADB 端口占用（集成 adb-port-killer 功能）
    try:
        # 导入 adb-port-killer 功能
        import sys
        from pathlib import Path
        # 添加 adb-port-killer 脚本目录到路径
        port_killer_dir = Path(__file__).resolve().parent.parent / "skills" / "android" / "adb-port-killer" / "scripts"
        if port_killer_dir.exists():
            sys.path.insert(0, str(port_killer_dir))
            from adb_port_manager import get_port_status, kill_killable_processes
            
            # 检查端口状态
            status = get_port_status(5037)
            if status.status == "occupied" and status.killable:
                print("   检测到 ADB 端口被占用，正在自动清理...")
                print(f"   可终止进程: {len(status.killable)} 个")
                print(f"   保护进程: {len(status.protected)} 个")
                
                # 自动清理可终止进程
                if kill_killable_processes(5037):
                    print("   ✅ ADB 端口已自动清理完成")
                else:
                    print("   ⚠️  ADB 端口清理失败，请手动检查")
                print()
            else:
                print("   ✅ ADB 端口状态正常")
                print()
        else:
            print("   ℹ️  adb-port-killer 模块未找到，跳过自动清理")
            print()
    except Exception as e:
        print(f"   ⚠️  ADB 端口自动清理失败: {e}")
        print()
    
    # 1. 检查 adb 端口占用
    try:
        result = subprocess.run(["lsof", "-wni", ":5037"], capture_output=True, text=True, timeout=_ADB_FAST_TIMEOUT)
        if result.returncode == 0 and result.stdout.strip():
            print("   端口 5037 占用情况：")
            for line in result.stdout.strip().splitlines():
                print(f"     {line}")
        else:
            print("   端口 5037: 空闲")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        print("   端口 5037: 检查失败（lsof 命令不可用）")
    
    # 2. 检查 adb 版本和位置
    adb_cmd = get_adb_cmd(device)
    try:
        # 获取 adb 版本
        result = subprocess.run(adb_cmd + ["version"], capture_output=True, text=True, timeout=_ADB_FAST_TIMEOUT)
        if result.returncode == 0:
            print("   ADB 版本信息：")
            for line in result.stdout.strip().splitlines():
                print(f"     {line}")
        
        # 获取 adb 位置
        which_result = subprocess.run(["which", "adb"], capture_output=True, text=True, timeout=_ADB_FAST_TIMEOUT)
        if which_result.returncode == 0:
            print(f"   ADB 位置: {which_result.stdout.strip()}")
        
        # 检查设备连接
        devices_result = subprocess.run(adb_cmd + ["devices"], capture_output=True, text=True, timeout=_ADB_FAST_TIMEOUT)
        if devices_result.returncode == 0:
            print("   设备连接状态：")
            for line in devices_result.stdout.strip().splitlines():
                if line.strip() and not line.startswith("List of devices"):
                    print(f"     {line}")
        
        # 检查 ANDROID_HOME 环境变量
        android_home = os.environ.get('ANDROID_HOME')
        if android_home:
            print(f"   ANDROID_HOME: {android_home}")
        else:
            print("   ANDROID_HOME: 未设置")
            
    except subprocess.TimeoutExpired:
        print("   ADB 诊断超时")
    except Exception as e:
        print(f"   ADB 诊断失败: {e}")
    
    print()


def check_adb_connection(device: Optional[str] = None) -> bool:
    """只检测 ADB 连接状态，不执行端口清理
    
    Args:
        device: 设备序列号，可选
        
    Returns:
        ADB 是否连接正常
    """
    try:
        adb_cmd = get_adb_cmd(device)
        
        # 简单的设备列表检查
        result = subprocess.run(
            adb_cmd + ["devices"], 
            capture_output=True, 
            text=True, 
            timeout=_ADB_FAST_TIMEOUT
        )
        
        if result.returncode != 0:
            return False
            
        # 检查是否有设备连接
        lines = result.stdout.strip().splitlines()
        if len(lines) <= 1:  # 只有标题行
            return False
            
        # 检查是否有可用设备（状态为 device）
        for line in lines[1:]:
            if line.strip() and "device" in line and "offline" not in line:
                return True
                
        return False
        
    except (subprocess.TimeoutExpired, Exception):
        return False


def ensure_adb_ready(device: Optional[str] = None,
                     max_retries: int = 5,
                     retry_interval: float = 3.0,
                     verbose: bool = True) -> bool:
    """确保 ADB 连接可用，不可用时自动等待重连

    每次执行 ADB 操作前调用此函数，可避免因 ADB 断连导致命令/截图失败。
    重试期间会输出过程提示，方便定位问题。

    Args:
        device: 设备序列号，可选
        max_retries: 最大重试次数（默认 5 次，含首次检查共 6 次）
        retry_interval: 重试间隔秒数（默认 3 秒）
        verbose: 是否输出过程提示

    Returns:
        ADB 是否就绪
    """
    # 首次检查
    if check_adb_connection(device):
        return True

    if verbose:
        print(f"  ⚠ ADB 连接异常，开始等待重连（最多重试 {max_retries} 次，间隔 {retry_interval}s）...",
              file=sys.stderr)

    for attempt in range(1, max_retries + 1):
        if verbose:
            print(f"    🔄 第 {attempt}/{max_retries} 次重试...", file=sys.stderr)

        # 尝试重启 adb server
        if attempt == 1 or attempt == max_retries:
            try:
                adb_cmd = get_adb_cmd(device)
                if verbose:
                    print("    🔧 正在重启 adb server...", file=sys.stderr)
                subprocess.run(adb_cmd[:1] + ["kill-server"],
                               capture_output=True, timeout=_ADB_FAST_TIMEOUT)
                time.sleep(1)
                subprocess.run(adb_cmd[:1] + ["start-server"],
                               capture_output=True, timeout=_ADB_FAST_TIMEOUT)
                time.sleep(2)
            except (subprocess.TimeoutExpired, Exception) as e:
                if verbose:
                    print(f"    ⚠ adb server 重启失败: {e}", file=sys.stderr)

        time.sleep(retry_interval)

        if check_adb_connection(device):
            if verbose:
                print(f"    ✅ ADB 连接已恢复（第 {attempt} 次重试成功）", file=sys.stderr)
            return True

    if verbose:
        print(f"  ❌ ADB 连接恢复失败（已重试 {max_retries} 次）", file=sys.stderr)
        print("  💡 排查指引：", file=sys.stderr)
        print("     1. 手机已通过 USB 连接并开启开发者模式 / USB 调试", file=sys.stderr)
        print("     2. 执行 adb devices 能看到设备", file=sys.stderr)
    return False


def _parse_wm_size(output: str) -> Tuple[int, int]:
    """解析 wm size 输出，优先使用 Override size（系统实际使用的分辨率）

    wm size 可能输出两行：
      Physical size: 1080x2400
      Override size: 1080x2340
    adb shell input tap 的坐标系基于 Override size（如果有），
    所以必须取最后一个匹配（Override 优先），否则坐标会偏移。
    """
    matches = re.findall(r"(\d+)x(\d+)", output)
    if matches:
        # 最后一个匹配 = Override size（有的话）；只有一行则就是 Physical size
        return (int(matches[-1][0]), int(matches[-1][1]))
    return (0, 0)


def get_device_info(device: Optional[str] = None) -> Tuple[str, Tuple[int, int]]:
    """获取设备型号和分辨率
    
    Args:
        device: 设备序列号，可选
        
    Returns:
        (设备型号, (宽度, 高度))，超时返回 ("unknown", (0, 0))
    """
    adb = get_adb_cmd(device)
    model = "unknown"
    resolution = (0, 0)

    try:
        # 获取型号
        result = subprocess.run(
            adb + ["shell", "getprop", "ro.product.model"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        model = result.stdout.strip() or "unknown"
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell getprop 超时（{}s）".format(_ADB_SHELL_TIMEOUT))

    try:
        # 获取分辨率
        result = subprocess.run(
            adb + ["shell", "wm", "size"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        resolution = _parse_wm_size(result.stdout)
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell wm size 超时（{}s）".format(_ADB_SHELL_TIMEOUT))

    return model, resolution


def get_device_basic_info(device: Optional[str] = None) -> dict:
    """获取设备基本信息：型号、厂商、序列号、Android 版本、SDK 版本、分辨率、DPI

    Args:
        device: 设备序列号，可选

    Returns:
        {"model", "manufacturer", "serial", "android_version", "sdk_version", "resolution", "density"}
        任何字段获取失败均降级为 "unknown" / [0, 0] / 0，不抛异常
    """
    adb = get_adb_cmd(device)
    info = {
        "model": "unknown",
        "manufacturer": "unknown",
        "serial": device or "unknown",
        "android_version": "unknown",
        "sdk_version": "unknown",
        "resolution": [0, 0],
        "density": 0,
    }

    try:
        result = subprocess.run(
            adb + ["shell",
                   "getprop ro.product.model; "
                   "getprop ro.product.manufacturer; "
                   "getprop ro.build.version.release; "
                   "getprop ro.build.version.sdk"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        lines = result.stdout.strip().splitlines()
        if len(lines) >= 1 and lines[0].strip():
            info["model"] = lines[0].strip()
        if len(lines) >= 2 and lines[1].strip():
            info["manufacturer"] = lines[1].strip()
        if len(lines) >= 3 and lines[2].strip():
            info["android_version"] = lines[2].strip()
        if len(lines) >= 4 and lines[3].strip():
            info["sdk_version"] = lines[3].strip()
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell getprop 超时（{}s）".format(_ADB_SHELL_TIMEOUT))

    if not device:
        try:
            result = subprocess.run(
                adb + ["get-serialno"],
                capture_output=True, text=True, timeout=_ADB_FAST_TIMEOUT
            )
            serial = result.stdout.strip()
            if serial and "unknown" not in serial.lower():
                info["serial"] = serial
        except subprocess.TimeoutExpired:
            pass

    try:
        result = subprocess.run(
            adb + ["shell", "wm", "size"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        res = _parse_wm_size(result.stdout)
        if res[0] > 0:
            info["resolution"] = list(res)
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell wm size 超时（{}s）".format(_ADB_SHELL_TIMEOUT))

    try:
        result = subprocess.run(
            adb + ["shell", "wm", "density"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        # wm density 输出格式：Physical density: 480 （可能有 Override density: xxx）
        # 取最后一个数字（Override 优先）
        density_matches = re.findall(r"(\d+)", result.stdout)
        if density_matches:
            info["density"] = int(density_matches[-1])
    except subprocess.TimeoutExpired:
        pass

    return info


def get_current_resolution(device: Optional[str] = None) -> Tuple[int, int]:
    """获取当前设备分辨率
    
    Args:
        device: 设备序列号，可选
        
    Returns:
        (宽度, 高度)，超时返回 (0, 0)
    """
    adb = get_adb_cmd(device)
    try:
        result = subprocess.run(
            adb + ["shell", "wm", "size"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
        return _parse_wm_size(result.stdout)
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell wm size 超时（{}s），请检查设备连接".format(_ADB_SHELL_TIMEOUT))
    return (0, 0)


def get_display_rotation(device: Optional[str] = None) -> int:
    """获取当前屏幕旋转方向（0/90/180/270），失败返回 0

    屏幕旋转会改变逻辑坐标系（input tap 的坐标基准），
    但 wm size 返回的是物理/自然方向尺寸（不随旋转变），
    因此横屏应用必须读取旋转方向来正确换算坐标。
    """
    adb = get_adb_cmd(device)
    try:
        result = subprocess.run(
            adb + ["shell", "dumpsys", "window", "displays"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return 0

    m = re.search(r"mCurrentRotation=ROTATION_(\d+)", result.stdout)
    if m:
        return int(m.group(1))

    # 兜底：从 cur=WxH（当前逻辑尺寸）推断，宽>高即为横屏
    m2 = re.search(r"\bcur=(\d+)x(\d+)", result.stdout)
    if m2 and int(m2.group(1)) > int(m2.group(2)):
        return 90
    return 0


def rotate_coords_to_display(px: float, py: float,
                             physical_res: Tuple[int, int],
                             rotation: int) -> Tuple[int, int]:
    """把「物理自然方向坐标」旋转映射为「逻辑显示坐标」（input tap 坐标系）

    flow 里保存的坐标统一是「物理自然方向坐标」（evdev 按 wm size 物理分辨率
    线性映射，不随屏幕旋转变化）；而 `adb shell input tap` 使用随旋转变化的
    逻辑显示坐标系。二者需按当前屏幕旋转方向换算。

    Args:
        px, py: 物理自然方向坐标
        physical_res: 物理自然方向分辨率 (宽, 高)
        rotation: 旋转角度 0/90/180/270

    Returns:
        逻辑显示坐标 (lx, ly)
    """
    phys_w, phys_h = physical_res
    # 用「自然方向左上角 (0,0) 落到哪个逻辑角」描述旋转方向，避免顺/逆时针歧义。
    if rotation == 90:
        # 左上角 (0,0) → 逻辑左下角 (0, W)：lx = py, ly = W - px
        return int(py), int(phys_w - px)
    if rotation == 180:
        # 左上角 (0,0) → 逻辑右下角 (W, H)
        return int(phys_w - px), int(phys_h - py)
    if rotation == 270:
        # 左上角 (0,0) → 逻辑右上角 (H, 0)：lx = H - py, ly = px
        return int(phys_h - py), int(px)
    return int(px), int(py)


def verify_rotation_mapping(device: Optional[str] = None) -> dict:
    """自校验横屏坐标旋转映射（返回诊断信息，不抛异常）

    横屏时，验证「自然方向四角 → 逻辑坐标」的映射是否满足：
    1. 角点映射后不越界（都在逻辑尺寸范围内）
    2. 四角一一映射到逻辑四角（不重不漏）

    这能自动发现「公式写反 / 坐标轴错配」类错误。方向语义本身
    由 Android 标准确定（ROTATION_90/270），此处仅校验实现一致性。

    Returns:
        dict: {rotation, physical, logical, corners, ok}
    """
    rotation = get_display_rotation(device)
    physical = get_current_resolution(device)
    phys_w, phys_h = physical
    if rotation in (90, 270):
        logical = (phys_h, phys_w)
    else:
        logical = (phys_w, phys_h)

    corners = {
        "自然左上(0,0)": rotate_coords_to_display(0, 0, physical, rotation),
        f"自然右上({phys_w},0)": rotate_coords_to_display(phys_w, 0, physical, rotation),
        f"自然左下(0,{phys_h})": rotate_coords_to_display(0, phys_h, physical, rotation),
        f"自然右下({phys_w},{phys_h})": rotate_coords_to_display(phys_w, phys_h, physical, rotation),
    }

    log_w, log_h = logical
    ok = True
    seen: set = set()
    for _name, (lx, ly) in corners.items():
        if not (0 <= lx <= log_w and 0 <= ly <= log_h):
            ok = False
        seen.add((lx, ly))

    # 四角必须映射到四个不同的逻辑角
    expected = {(0, 0), (log_w, 0), (0, log_h), (log_w, log_h)}
    if seen != expected:
        ok = False

    return {
        "rotation": rotation,
        "physical": physical,
        "logical": logical,
        "corners": corners,
        "ok": ok,
    }


def print_rotation_check(device: Optional[str] = None) -> bool:
    """横屏时打印旋转自检对照表，返回是否通过

    竖屏（rotation 0/180）无需旋转，直接返回 True 且不打印。
    """
    info = verify_rotation_mapping(device)
    if info["rotation"] not in (90, 270):
        return True

    phys_w, phys_h = info["physical"]
    log_w, log_h = info["logical"]
    print(f"   🔍 横屏坐标自检: 自然 {phys_w}x{phys_h} → 逻辑 {log_w}x{log_h}（ROTATION_{info['rotation']}）")
    for name, (lx, ly) in info["corners"].items():
        print(f"      {name} → 逻辑({lx},{ly})")
    if info["ok"]:
        print(f"   ✅ 角点映射合法（四角一一对应）")
    else:
        print(f"   ⚠️  角点映射异常，请检查 rotate_coords_to_display 公式！")
    return info["ok"]


def find_touch_device(device: Optional[str] = None) -> str:
    """查找触摸输入设备路径
    
    Args:
        device: 设备序列号，可选
        
    Returns:
        触摸设备路径，如 /dev/input/event7
    """
    adb = get_adb_cmd(device)
    try:
        result = subprocess.run(
            adb + ["shell", "getevent", "-pl"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell getevent 超时（{}s），使用默认触摸设备".format(_ADB_SHELL_TIMEOUT))
        return "/dev/input/event1"

    current_dev = ""
    for line in result.stdout.splitlines():
        dev_match = re.match(r"add device \d+: (/dev/input/event\d+)", line)
        if dev_match:
            current_dev = dev_match.group(1)
        # 查找包含 ABS_MT_POSITION_X 的设备（触摸屏）
        if "ABS_MT_POSITION_X" in line and current_dev:
            return current_dev

    return "/dev/input/event1"  # fallback


def get_touch_max(device: Optional[str] = None, event_dev: str = "") -> Tuple[int, int]:
    """获取触摸设备的坐标最大值
    
    Args:
        device: 设备序列号，可选
        event_dev: 触摸设备路径
        
    Returns:
        (最大X坐标, 最大Y坐标)
    """
    adb = get_adb_cmd(device)
    try:
        result = subprocess.run(
            adb + ["shell", "getevent", "-pl"],
            capture_output=True, text=True, timeout=_ADB_SHELL_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        print("⏱️  adb shell getevent 超时（{}s），无法获取触摸最大值".format(_ADB_SHELL_TIMEOUT))
        return (0, 0)

    max_x, max_y = 0, 0
    in_target_dev = False

    for line in result.stdout.splitlines():
        dev_match = re.match(r"add device \d+: (/dev/input/event\d+)", line)
        if dev_match:
            in_target_dev = (dev_match.group(1) == event_dev)
            continue

        if not in_target_dev:
            continue

        # ABS_MT_POSITION_X: value 0, min 0, max 1079, ...
        if "ABS_MT_POSITION_X" in line:
            m = re.search(r"max\s+(\d+)", line)
            if m:
                max_x = int(m.group(1))
        elif "ABS_MT_POSITION_Y" in line:
            m = re.search(r"max\s+(\d+)", line)
            if m:
                max_y = int(m.group(1))

    return max_x, max_y


def scale_coords(x: int, y: int,
                 src_res: Tuple[int, int],
                 dst_res: Tuple[int, int]) -> Tuple[int, int]:
    """按分辨率比例缩放坐标
    
    Args:
        x: 原始X坐标
        y: 原始Y坐标
        src_res: 源分辨率 (宽度, 高度)
        dst_res: 目标分辨率 (宽度, 高度)
        
    Returns:
        (缩放后的X坐标, 缩放后的Y坐标)
    """
    if src_res[0] == 0 or src_res[1] == 0:
        return x, y
    if src_res == dst_res:
        return x, y

    sx = dst_res[0] / src_res[0]
    sy = dst_res[1] / src_res[1]
    return int(x * sx), int(y * sy)


def adb_pull(device: Optional[str] = None, adb: Optional[list] = None,
             remote_path: str = "", local_path: str = "",
             timeout: int = _ADB_PULL_TIMEOUT) -> bool:
    """从设备拉取文件/目录到本地（adb pull）

    Args:
        device: 设备序列号，可选（未传 adb 时用它构建 adb 命令）
        adb: 现成的 adb 命令前缀，可选（与 device 二选一，优先使用）
        remote_path: 设备端路径
        local_path: 本地目标路径
        timeout: 超时秒数（默认 30）

    Returns:
        是否成功
    """
    if adb is None:
        adb = get_adb_cmd(device)
    try:
        result = subprocess.run(
            adb + ["pull", remote_path, local_path],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode != 0:
            print("❌ adb pull 失败: %s" % result.stderr.strip())
            return False
        if result.stdout.strip():
            print(result.stdout.strip())
        return True
    except subprocess.TimeoutExpired:
        print("⏱️  adb pull 超时（%ds）" % timeout)
        return False


def take_screenshot(adb: list[str], output_path: str) -> bool:
    """截取设备屏幕并保存到本地
    
    Args:
        adb: adb 命令前缀
        output_path: 输出文件路径
        
    Returns:
        是否成功
    """
    try:
        # 在设备上截屏
        device_path = "/sdcard/adb_replay_screenshot.png"
        subprocess.run(
            adb + ["shell", "screencap", "-p", device_path],
            capture_output=True, timeout=_ADB_SHELL_TIMEOUT
        )
        # 拉取到本地
        adb_pull(adb=adb, remote_path=device_path, local_path=output_path)
        # 删除设备上的临时文件
        subprocess.run(
            adb + ["shell", "rm", device_path],
            capture_output=True, timeout=_ADB_FAST_TIMEOUT
        )
        return os.path.exists(output_path)
    except (subprocess.TimeoutExpired, Exception):
        return False


def start_screenrecord(adb: list[str], device_path: str,
                      time_limit: int = 30) -> subprocess.Popen:
    """在设备上开始录屏
    
    Args:
        adb: adb 命令前缀
        device_path: 设备端输出路径
        time_limit: 录制时长限制（秒）
        
    Returns:
        录屏进程对象
    """
    proc = subprocess.Popen(
        adb + ["shell", "screenrecord",
               "--time-limit", str(time_limit),
               device_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    return proc


def stop_screenrecord(adb: list[str], proc: subprocess.Popen,
                     device_path: str, output_path: str) -> bool:
    """停止录屏并拉取文件到本地
    
    Args:
        adb: adb 命令前缀
        proc: 录屏进程对象
        device_path: 设备端文件路径
        output_path: 本地输出路径
        
    Returns:
        是否成功
    """
    try:
        # 发送 SIGINT 优雅停止录屏
        subprocess.run(
            adb + ["shell", "pkill", "-SIGINT", "screenrecord"],
            capture_output=True, timeout=_ADB_SHELL_TIMEOUT
        )
        try:
            proc.wait(timeout=_ADB_SHELL_TIMEOUT)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        time.sleep(1)  # 等待文件写入完成
        # 拉取文件
        adb_pull(adb=adb, remote_path=device_path, local_path=output_path)
        # 清理设备临时文件
        subprocess.run(
            adb + ["shell", "rm", device_path],
            capture_output=True, timeout=_ADB_FAST_TIMEOUT
        )
        return os.path.exists(output_path)
    except (subprocess.TimeoutExpired, Exception):
        return False


if __name__ == "__main__":
    # 测试功能
    try:
        print("=== ADB 工具库测试 ===")
        
        # 测试 adb 命令构建
        adb_cmd = get_adb_cmd()
        print(f"✓ ADB 命令: {' '.join(adb_cmd)}")
        
        # 测试诊断功能
        diagnose_adb_status()
        
        # 测试设备信息获取
        model, resolution = get_device_info()
        print(f"✓ 设备型号: {model}")
        print(f"✓ 分辨率: {resolution[0]}x{resolution[1]}")
        
        # 测试触摸设备查找
        touch_dev = find_touch_device()
        print(f"✓ 触摸设备: {touch_dev}")
        
        print("✅ 所有功能测试通过")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")