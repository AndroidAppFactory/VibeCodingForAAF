#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
aar_builder.py
AAR → APK 构建（保留备用）：将 AAR 编译为 APK 用于 zipalign 验证
"""

import os
import subprocess
import shutil
from typing import List, Optional, Tuple
from pathlib import Path

from models import Colors


# ============================================================================
# AAR → APK 构建
# ============================================================================
AAFFOR16KB_REPO = "https://github.com/bihe0832/AAFFor16KB.git"
AAFFOR16KB_DIR_NAME = "AAFFor16KB"


def get_aar_project_dir() -> Tuple[bool, str, str]:
    """获取 AAFFor16KB 项目目录（用于 AAR → APK 构建）

    查找/准备顺序：
    1. $WORK_ROOT/temp/cache/apk-16kb-check/AAFFor16KB/（优先）
    2. $HOME/temp/cache/apk-16kb-check/AAFFor16KB/（WORK_ROOT 未设置时 fallback 到 $HOME）
    3. 目录不存在时自动 git clone

    返回: (成功, 项目目录路径, 错误信息)
    """
    work_root = os.path.expanduser(os.environ.get("WORK_ROOT", str(Path.home())))
    cache_base = os.path.join(work_root, "temp", "cache", "apk-16kb-check")

    project_dir = os.path.join(cache_base, AAFFOR16KB_DIR_NAME)
    build_script = os.path.join(project_dir, "build_aar_apk.sh")

    # 已存在且包含构建脚本 → 先 git pull 更新，再使用
    if os.path.isfile(build_script):
        c = Colors
        print(f"\n{c.CYAN}📦 AAFFor16KB 项目已存在，正在更新...{c.NC}")
        print(f"  目录: {project_dir}")
        try:
            proc = subprocess.run(
                ['git', 'pull', '--rebase'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=project_dir
            )
            if proc.returncode == 0:
                pull_msg = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else "updated"
                print(f"  {c.GREEN}✅ 更新完成: {pull_msg}{c.NC}")
            else:
                print(f"  {c.YELLOW}⚠️ 更新失败（使用已有代码继续）: {proc.stderr.strip()}{c.NC}")
        except subprocess.TimeoutExpired:
            print(f"  {c.YELLOW}⚠️ 更新超时（使用已有代码继续）{c.NC}")
        except Exception as e:
            print(f"  {c.YELLOW}⚠️ 更新出错（使用已有代码继续）: {e}{c.NC}")
        return True, project_dir, ""

    # 目录不存在或不完整 → clone
    c = Colors
    print(f"\n{c.CYAN}📦 AAFFor16KB 项目未找到，正在 clone...{c.NC}")
    print(f"  仓库: {AAFFOR16KB_REPO}")
    print(f"  目标: {project_dir}")

    os.makedirs(cache_base, exist_ok=True)

    if os.path.isdir(project_dir):
        shutil.rmtree(project_dir)

    try:
        proc = subprocess.run(
            ['git', 'clone', '--depth', '1', AAFFOR16KB_REPO, project_dir],
            capture_output=True,
            text=True,
            timeout=120
        )
        if proc.returncode == 0 and os.path.isfile(build_script):
            print(f"  {c.GREEN}✅ clone 成功{c.NC}")
            return True, project_dir, ""
        else:
            error = proc.stderr.strip() or proc.stdout.strip()
            return False, "", f"git clone 失败: {error}"
    except subprocess.TimeoutExpired:
        return False, "", "git clone 超时 (>2分钟)"
    except FileNotFoundError:
        return False, "", "未找到 git 命令，请先安装 git"
    except Exception as e:
        return False, "", f"git clone 出错: {e}"


def build_aar_to_apk(aar_paths, output_dir: Optional[str] = None, clean: bool = False) -> Tuple[bool, str, str]:
    """将 AAR 文件编译为 APK

    Args:
        aar_paths: 单个 AAR 路径（str）或多个 AAR 路径列表（List[str]）
        output_dir: APK 输出目录（默认为 AAFFor16KB 项目的 build/16kb-check/ 目录）
        clean: 是否先清空 libs 目录中的历史 AAR

    返回: (成功, APK路径, 错误信息)
    """
    c = Colors

    # 统一为列表
    if isinstance(aar_paths, str):
        aar_paths = [aar_paths]

    # Step 1: 获取项目目录
    ok, project_dir, error = get_aar_project_dir()
    if not ok:
        return False, "", error

    build_script = os.path.join(project_dir, "build_aar_apk.sh")
    aar_paths = [os.path.abspath(p) for p in aar_paths]
    if output_dir is None:
        output_dir = os.path.join(project_dir, "build", "16kb-check")

    # Step 2: 调用构建脚本
    print(f"\n{c.CYAN}🔨 检测到 AAR 文件，启动 AAR → APK 构建...{c.NC}")
    if len(aar_paths) == 1:
        print(f"  AAR: {aar_paths[0]}")
    else:
        print(f"  AAR: {len(aar_paths)} 个文件")
        for p in aar_paths:
            print(f"    - {os.path.basename(p)}")
    print(f"  项目: {project_dir}")
    print()

    cmd = ['bash', build_script]
    if clean:
        cmd.append('--clean')
    cmd.extend(aar_paths)
    cmd.append(output_dir)

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600
        )

        apk_path = ""
        for line in proc.stdout.splitlines():
            if line.startswith("APK_OUTPUT_PATH="):
                apk_path = line.split("=", 1)[1].strip()
                break

        if proc.returncode == 0 and apk_path and os.path.isfile(apk_path):
            print(f"{c.GREEN}✅ AAR → APK 构建成功{c.NC}")
            print(f"  APK: {apk_path}")
            return True, apk_path, ""
        else:
            error_output = proc.stderr.strip() or proc.stdout.strip()
            error_lines = error_output.splitlines()[-20:]
            error_msg = "\n".join(error_lines)
            print(f"{c.RED}❌ AAR → APK 构建失败{c.NC}")
            if error_msg:
                print(f"  最后输出:\n{error_msg}")
            return False, "", f"构建失败 (exit code: {proc.returncode})"

    except subprocess.TimeoutExpired:
        return False, "", "构建超时 (>10分钟)"
    except Exception as e:
        return False, "", f"构建出错: {e}"
