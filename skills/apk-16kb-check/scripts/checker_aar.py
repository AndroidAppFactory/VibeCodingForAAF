#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_aar.py
AAR 检查器：直接解压 AAR 提取 .so 文件检查 ELF LOAD 段对齐
"""

import os
import zipfile
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from models import CheckResult, ZipalignResult, Colors
from checker_common import run_elf_check


def check_aar(aar_paths) -> CheckResult:
    """检查 AAR 文件中 .so 的 ELF LOAD 段对齐（直接解压，无需编译为 APK）

    AAR 是中间产物，zipalign 对齐由最终宿主 APK 打包时决定，
    因此 AAR 模式只做 ELF LOAD 段对齐检查，跳过 zipalign 验证。

    Args:
        aar_paths: 单个 AAR 路径（str）或多个 AAR 路径列表（List[str]）

    返回: CheckResult
    """
    c = Colors
    if isinstance(aar_paths, str):
        aar_paths = [aar_paths]

    aar_paths = [os.path.abspath(p) for p in aar_paths]

    # 计算总文件大小
    total_size = sum(os.path.getsize(p) for p in aar_paths if os.path.isfile(p))
    if total_size >= 1024 * 1024 * 1024:
        file_size = f"{total_size / (1024 * 1024 * 1024):.1f} GB"
    elif total_size >= 1024 * 1024:
        file_size = f"{total_size / (1024 * 1024):.1f} MB"
    elif total_size >= 1024:
        file_size = f"{total_size / 1024:.1f} KB"
    else:
        file_size = f"{total_size} B"

    result = CheckResult(
        file_path=aar_paths[0],  # 主文件路径（用于报告显示）
        file_size=file_size,
        check_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )
    result.source_aar_paths = aar_paths

    # AAR 模式跳过 zipalign 验证
    result.zipalign = ZipalignResult(
        available=False,
        status="skipped",
        summary="⏭️ AAR 模式跳过（zipalign 由宿主 APK 决定）"
    )

    # 解压所有 AAR 到临时目录，提取 .so 文件
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix='aar_16kb_check_')

        print(f"\n{c.CYAN}📦 AAR 直接解压检查模式（无需编译为 APK）{c.NC}")
        if len(aar_paths) == 1:
            print(f"  AAR: {aar_paths[0]}")
        else:
            print(f"  AAR: {len(aar_paths)} 个文件")
            for p in aar_paths:
                print(f"    - {os.path.basename(p)}")

        so_count = 0
        for aar_path in aar_paths:
            aar_name = Path(aar_path).name
            try:
                with zipfile.ZipFile(aar_path, 'r') as zf:
                    for info in zf.infolist():
                        if info.filename.endswith('.so'):
                            # 保持 jni/{abi}/libfoo.so 的目录结构
                            if len(aar_paths) > 1:
                                extract_path = os.path.join(tmp_dir, aar_name, info.filename)
                            else:
                                extract_path = os.path.join(tmp_dir, info.filename)

                            os.makedirs(os.path.dirname(extract_path), exist_ok=True)
                            with zf.open(info) as src, open(extract_path, 'wb') as dst:
                                dst.write(src.read())
                            so_count += 1
                print(f"  {c.GREEN}📦 {aar_name}: 提取完成{c.NC}")
            except Exception as e:
                print(f"  {c.YELLOW}⚠️ 无法读取 {aar_name}: {e}{c.NC}")

        if so_count == 0:
            print(f"  {c.YELLOW}⚠️ AAR 中未找到 .so 文件{c.NC}")
            return result

        print(f"  {c.GREEN}✅ 共提取 {so_count} 个 .so 文件到临时目录{c.NC}")
        print()

        # 使用 check_elf_alignment.sh 检查临时目录
        # 传入 tmp_dir 作为已解压的 SO 目录，供 NDK 版本检测使用
        elf_results, elf_output = run_elf_check(tmp_dir, extracted_so_dir=tmp_dir)
        result.elf_results = elf_results
        result.elf_script_output = elf_output

    finally:
        # 清理临时目录
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return result
