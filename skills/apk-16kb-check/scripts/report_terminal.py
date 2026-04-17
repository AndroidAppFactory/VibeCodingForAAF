#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_terminal.py
终端输出：print_result、print_batch_summary、open_html_report
"""

import platform
import subprocess
from typing import List, Tuple
from pathlib import Path

from models import CheckResult, ZipalignEntry, Colors
from checker_common import find_check_elf_script


# ============================================================================
# zipalign BAD 条目分类
# ============================================================================
def classify_zipalign_bad_entries(result: CheckResult) -> Tuple[List[ZipalignEntry], List[ZipalignEntry], List[ZipalignEntry]]:
    """将 zipalign BAD 条目分为三类：可修复 / 需重编译 / 非 SO 文件

    分类依据：
    - BAD 条目对应的 .so 文件如果 ELF LOAD 段也未对齐 → 需重编译（zipalign 修不了）
    - BAD 条目对应的 .so 文件如果 ELF LOAD 段已对齐   → zipalign 可修复
    - BAD 条目不是 .so 文件 → zipalign 可修复（非 SO 资源文件）

    返回: (fixable_entries, unfixable_entries, non_so_entries)
    """
    elf_failed_paths = set()
    for elf_r in result.elf_results:
        if elf_r.status == "fail":
            if elf_r.arch and elf_r.arch != "unknown":
                elf_failed_paths.add(f"lib/{elf_r.arch}/{elf_r.name}")

    fixable: List[ZipalignEntry] = []
    unfixable: List[ZipalignEntry] = []
    non_so: List[ZipalignEntry] = []

    for entry in result.zipalign.entries:
        if entry.status != "fail":
            continue
        if not entry.file_path.endswith('.so'):
            non_so.append(entry)
        elif entry.file_path in elf_failed_paths:
            unfixable.append(entry)
        else:
            fixable.append(entry)

    return fixable, unfixable, non_so


# ============================================================================
# 终端输出
# ============================================================================
def print_result(result: CheckResult) -> None:
    """在终端输出检查结果"""
    c = Colors
    is_aar = bool(result.source_aar_paths)

    print("=" * 44)
    print(" APK/AAR 16KB 对齐检查工具")
    print("=" * 44)
    print()
    if is_aar:
        print(f"AAR 文件: {', '.join(Path(p).name for p in result.source_aar_paths)}")
    else:
        # 根据文件扩展名判断文件类型
        file_ext = Path(result.file_path).suffix.lower()
        if file_ext == '.so':
            file_type_label = "SO 文件"
        elif file_ext == '.aar':
            file_type_label = "AAR 文件"
        else:
            file_type_label = "APK 文件"
        print(f"{file_type_label}: {result.file_path}")
    print(f"文件大小: {result.file_size}")
    print()

    # 压缩存储提示
    if result.has_compressed_so:
        print(f"{c.RED}📦 压缩存储（必须改为 stored）:{c.NC}")
        for name in sorted(result.compressed_so_names):
            print(f"  {c.RED}• {name} — 被压缩存储，无法被系统 mmap{c.NC}")
        print(f"{c.YELLOW}  修复: 在 build.gradle 中设置 android.packagingOptions.jniLibs.useLegacyPackaging = false{c.NC}")
        print()

    # 官方 zipalign 验证结果
    print("=" * 44)
    print(" 官方 zipalign 验证")
    print("=" * 44)
    if result.zipalign.available:
        color = c.GREEN if result.zipalign.status == "pass" else c.RED
        print(f" {color}{result.zipalign.summary}{c.NC}")
        print(f" 通过: {result.zipalign.ok_count}, 失败: {result.zipalign.fail_count}")
    else:
        print(f" {c.YELLOW}{result.zipalign.summary}{c.NC}")
        print(f" {c.YELLOW}请确保 ANDROID_HOME 环境变量已设置且 Build-Tools 已安装{c.NC}")

    # zipalign BAD 条目分类展示
    fix = result.fix_result
    if result.zipalign.status == "fail" and result.zipalign.entries:
        fixable, unfixable, non_so = classify_zipalign_bad_entries(result)

        if fixable or unfixable:
            print()
            if fixable:
                print(f" {c.YELLOW}📦 zipalign 可修复（ZIP 偏移未对齐，ELF 段正常）: {len(fixable)} 个{c.NC}")
                fixable_sorted = sorted(fixable, key=lambda x: x.file_path)
                for entry in fixable_sorted:
                    print(f"   {c.YELLOW}• {entry.file_path} ({entry.detail}){c.NC}")
            if unfixable:
                print(f" {c.RED}🔧 需重新编译（ELF LOAD 段未 16KB 对齐，zipalign 无法修复）: {len(unfixable)} 个{c.NC}")
                unfixable_sorted = sorted(unfixable, key=lambda x: x.file_path)
                for entry in unfixable_sorted:
                    source_info = ""
                    so_name = Path(entry.file_path).name
                    if so_name in result.so_source_map:
                        info = result.so_source_map[so_name]
                        source_label = "项目" if info.get('type') == "project" else "外部"
                        source_info = f" ← [{source_label}] {info.get('module', '')}"
                    print(f"   {c.RED}• {entry.file_path} ({entry.detail}){source_info}{c.NC}")

    # 修复后的对比结果
    if fix and fix.attempted:
        print()
        print("-" * 44)
        print(f" zipalign -P 16 自动修复结果")
        print("-" * 44)
        if fix.success and fix.verify_result:
            vr = fix.verify_result
            print(f" {c.GREEN}✅ 修复成功{c.NC}")
            print(f" 修复后: 通过 {vr.zipalign.ok_count}, 失败 {vr.zipalign.fail_count}")
            print(f" 文件: {fix.aligned_path}")
        elif fix.verify_result:
            vr = fix.verify_result
            orig_fail = result.zipalign.fail_count
            fixed_fail = vr.zipalign.fail_count
            fixed_count = orig_fail - fixed_fail
            if fixed_fail == 0:
                print(f" {c.GREEN}✅ zipalign 偏移对齐已全部修复（{fixed_count} 个）{c.NC}")
                print(f" 修复前: 通过 {result.zipalign.ok_count}, 失败 {orig_fail}")
                print(f" 修复后: 通过 {vr.zipalign.ok_count}, 失败 0")
                if vr.elf_failed > 0:
                    print(f" {c.YELLOW}⚠️  但仍有 {vr.elf_failed} 个 SO 的 ELF LOAD 段未对齐（需重新编译，见下方）{c.NC}")
            else:
                print(f" {c.YELLOW}⚠️  部分修复{c.NC}")
                print(f" 修复前: 通过 {result.zipalign.ok_count}, 失败 {orig_fail}")
                print(f" 修复后: 通过 {vr.zipalign.ok_count}, 失败 {fixed_fail}")
                if fixed_count > 0:
                    print(f" {c.GREEN}✅ zipalign 修复了 {fixed_count} 个偏移对齐问题{c.NC}")
                print(f" {c.RED}❌ 仍有 {fixed_fail} 个无法通过 zipalign 修复（ELF LOAD 段问题）{c.NC}")
            print(f" 文件: {fix.aligned_path}")
        else:
            print(f" {c.RED}❌ 修复失败: {fix.error}{c.NC}")
        print(f" {c.YELLOW}⚠️  注意：修复后的 APK 未签名，仅用于验证对齐方案{c.NC}")

    print()

    # ELF LOAD 段对齐检查结果
    print("=" * 44)
    print(" ELF LOAD 段对齐检查 (check_elf_alignment.sh)")
    print("=" * 44)
    if result.elf_results:
        print(f" 检查 SO 数: {result.elf_total} (仅 64 位架构)")
        print(f" {c.GREEN}✅ ALIGNED (≥ 16KB): {result.elf_passed}{c.NC}")
        print(f" {c.RED}❌ UNALIGNED: {result.elf_failed}{c.NC}")
        if result.elf_exempt() > 0:
            print(f" {c.CYAN}ℹ️  豁免检查 (32 位架构): {result.elf_exempt()}{c.NC}")
        print()

        elf_failed_list = [r for r in result.elf_results if r.status == "fail"]
        if elf_failed_list:
            print(f"{c.RED}❌ ELF 段未对齐（需重新编译，zipalign 无法修复）:{c.NC}")
            elf_failed_list_sorted = sorted(elf_failed_list, key=lambda x: x.name)
            for r in elf_failed_list_sorted:
                source_info = ""
                if r.source_module:
                    source_label = "项目" if r.source_type == "project" else "外部"
                    source_info = f" ← [{source_label}] {r.source_module}"
                print(f"  {c.RED}• {r.name} ({r.arch}) - 对齐值: {r.align_value} - NDK: {r.ndk_version}{source_info}{c.NC}")
            print()
            print(f"{c.YELLOW}修复方案: 升级 NDK r28+ 或添加 -Wl,-z,max-page-size=16384{c.NC}")
            project_failed = [r for r in elf_failed_list if r.source_type == "project"]
            external_failed = [r for r in elf_failed_list if r.source_type == "external"]
            unknown_failed = [r for r in elf_failed_list if not r.source_type or r.source_type == 'not_configured']
            if project_failed:
                so_names = ', '.join(sorted(set(r.name for r in project_failed)))
                print(f"{c.YELLOW}  📦 项目模块 .so: {so_names} → 修改 CMake/ndk-build 参数重新编译{c.NC}")
            if external_failed:
                seen_external = set()
                for r in external_failed:
                    key = (r.name, r.source_module)
                    if key not in seen_external:
                        seen_external.add(key)
                        print(f"{c.YELLOW}  📦 外部依赖: {r.name} ← {r.source_module} → 联系供应商或升级版本{c.NC}")
            if unknown_failed:
                so_names = ', '.join(sorted(set(r.name for r in unknown_failed)))
                print(f"{c.YELLOW}  📦 来源未知: {so_names} → 需手动确认是项目 SO 还是第三方 SDK{c.NC}")
            print()
    elif not find_check_elf_script():
        print(f" {c.YELLOW}⚠️ check_elf_alignment.sh 不可用，跳过 ELF 段检查{c.NC}")
        print(f" {c.YELLOW}请确保脚本存在于 scripts/ 目录下{c.NC}")
        print()
    else:
        # 根据文件扩展名判断文件类型
        file_ext = Path(result.file_path).suffix.lower()
        if file_ext == '.so':
            print(f" {c.YELLOW}SO 文件检查结果{c.NC}")
        else:
            print(f" {c.YELLOW}APK 中未找到 .so 文件{c.NC}")
        print()


def open_html_report(html_path: str) -> None:
    """自动用浏览器打开 HTML 报告"""
    system = platform.system()

    try:
        if system == "Darwin":
            subprocess.run(["open", html_path], check=False)
        elif system == "Linux":
            subprocess.run(["xdg-open", html_path], check=False)
        elif system == "Windows":
            subprocess.run(["start", html_path], shell=True, check=False)
    except Exception:
        pass


# ============================================================================
# 批量检查
# ============================================================================
def batch_check(directory: str) -> List[CheckResult]:
    """批量检查目录下所有 APK/AAR 文件"""
    import os
    from checker_apk import check_apk
    from checker_aar import check_aar

    results = []
    directory = os.path.abspath(directory)

    for root, dirs, files in os.walk(directory):
        for f in files:
            ext = Path(f).suffix.lower()
            if ext == '.apk':
                file_path = os.path.join(root, f)
                print(f"检查: {file_path}")
                try:
                    result = check_apk(file_path)
                    results.append(result)
                except Exception as e:
                    print(f"  错误: {e}")
            elif ext == '.aar':
                file_path = os.path.join(root, f)
                print(f"检查 AAR: {file_path}")
                try:
                    result = check_aar(file_path)
                    results.append(result)
                except Exception as e:
                    print(f"  错误: {e}")

    return results


def print_batch_summary(results: List[CheckResult]) -> None:
    """输出批量检查汇总"""
    c = Colors

    print()
    print("=" * 60)
    print(" 批量检查汇总")
    print("=" * 60)
    print()

    total_files = len(results)
    passed_files = sum(1 for r in results if r.zipalign.status != "fail" and r.elf_failed == 0)
    failed_files = total_files - passed_files

    print(f"检查文件数: {total_files}")
    print(f"{c.GREEN}全部通过: {passed_files}{c.NC}")
    print(f"{c.RED}存在问题: {failed_files}{c.NC}")
    print()

    if failed_files > 0:
        print(f"{c.RED}问题文件列表:{c.NC}")
        for r in results:
            if r.zipalign.status == "fail" or r.elf_failed > 0:
                print(f"  {c.RED}• {Path(r.file_path).name}{c.NC}")
                issues = []
                if r.zipalign.status == "fail":
                    issues.append("zipalign 未通过")
                if r.elf_failed > 0:
                    issues.append(f"ELF 未对齐: {r.elf_failed} 个")
                print(f"    {', '.join(issues)}")
