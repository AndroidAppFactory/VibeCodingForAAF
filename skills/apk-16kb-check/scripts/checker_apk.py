#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_apk.py
APK 检查器：检查 APK 文件的 16KB 对齐状态，失败时自动修复
"""

import os
import zipfile
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from models import CheckResult, FixResult, Colors
from checker_common import (
    check_compressed_so, run_zipalign_verify, run_elf_check, run_zipalign_fix
)


def _extract_so_from_apk(apk_path: str, dest_dir: str) -> int:
    """从 APK 中提取所有 .so 文件到目标目录，保持 lib/{abi}/ 目录结构
    
    Returns: 提取的 SO 文件数量
    """
    so_count = 0
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.endswith('.so') and not info.is_dir():
                    zf.extract(info.filename, dest_dir)
                    so_count += 1
    except Exception:
        pass
    return so_count


def check_apk(file_path: str) -> CheckResult:
    """检查单个 APK 文件"""
    file_path = os.path.abspath(file_path)

    # 获取文件大小
    file_size_bytes = os.path.getsize(file_path)
    if file_size_bytes >= 1024 * 1024 * 1024:
        file_size = f"{file_size_bytes / (1024 * 1024 * 1024):.1f} GB"
    elif file_size_bytes >= 1024 * 1024:
        file_size = f"{file_size_bytes / (1024 * 1024):.1f} MB"
    elif file_size_bytes >= 1024:
        file_size = f"{file_size_bytes / 1024:.1f} KB"
    else:
        file_size = f"{file_size_bytes} B"

    result = CheckResult(
        file_path=file_path,
        file_size=file_size,
        check_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

    # 检查压缩存储的 .so
    has_compressed, compressed_names = check_compressed_so(file_path)
    result.has_compressed_so = has_compressed
    result.compressed_so_names = compressed_names

    # 运行官方 zipalign 验证
    result.zipalign = run_zipalign_verify(file_path)

    # 预先解压 APK 中的 SO 文件到临时目录，供 ELF 检查和 NDK 版本检测共用
    tmp_dir = None
    try:
        tmp_dir = tempfile.mkdtemp(prefix='apk_16kb_check_')
        _extract_so_from_apk(file_path, tmp_dir)

        # 运行官方 check_elf_alignment.sh，传入已解压的 SO 目录用于 NDK 版本检测
        elf_results, elf_output = run_elf_check(file_path, extracted_so_dir=tmp_dir)
        result.elf_results = elf_results
        result.elf_script_output = elf_output
    finally:
        # 所有检查完成后统一清理临时目录
        if tmp_dir and os.path.isdir(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return result


def try_fix_apk(original_apk: str) -> FixResult:
    """尝试自动修复 APK 的 16KB 对齐问题

    流程：
    1. zipalign -P 16 -f 4 original.apk aligned.apk
    2. 重新验证对齐后的 APK

    注意：修复后的 APK 不做签名处理，仅用于验证对齐方案可行性。
    """
    fix = FixResult(attempted=True)

    # 准备输出路径
    base, ext = os.path.splitext(original_apk)
    aligned_path = f"{base}_aligned{ext}"
    fix.aligned_path = aligned_path

    c = Colors

    # Step 1: zipalign
    fix.steps.append("Step 1: 执行 zipalign -P 16 对齐...")
    print(f"\n{c.CYAN}🔧 尝试自动修复...{c.NC}")
    print(f"  Step 1: 执行 zipalign -P 16 对齐...")

    ok, err = run_zipalign_fix(original_apk, aligned_path)
    if not ok:
        fix.error = err
        fix.steps.append(f"  ❌ 失败: {err}")
        print(f"  {c.RED}❌ 失败: {err}{c.NC}")
        return fix

    fix.steps.append(f"  ✅ 对齐完成: {aligned_path}")
    print(f"  {c.GREEN}✅ 对齐完成: {aligned_path}{c.NC}")

    # Step 2: 重新验证
    fix.steps.append("Step 2: 重新验证对齐后的 APK...")
    print(f"  Step 2: 重新验证对齐后的 APK...")

    try:
        verify_result = check_apk(aligned_path)
        fix.verify_result = verify_result

        if verify_result.zipalign.status != "fail" and verify_result.elf_failed == 0:
            fix.success = True
            fix.steps.append("  ✅ 验证通过！修复成功")
            print(f"  {c.GREEN}✅ 验证通过{c.NC}")
        else:
            fix.success = False
            fix.error = "对齐后仍有未通过项，可能是 SO 文件本身的 ELF 段未按 16KB 编译"
            fix.steps.append(f"  ❌ 验证仍有失败项: {fix.error}")
            print(f"  {c.YELLOW}⚠️  验证完成，详情见下方对比{c.NC}")
    except Exception as e:
        fix.error = f"验证出错: {e}"
        fix.steps.append(f"  ❌ 验证出错: {e}")
        print(f"  {c.RED}❌ 验证出错: {e}{c.NC}")

    return fix
