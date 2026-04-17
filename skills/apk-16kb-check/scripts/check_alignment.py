#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_alignment.py
主入口：检查 APK/AAR 中 .so 文件的 16KB 对齐状态

APK 模式（两项检查）：
  1. 官方 zipalign 验证：运行 zipalign -c -P 16 -v 4 验证 APK 整体对齐
  2. ELF LOAD 段对齐：运行官方 check_elf_alignment.sh 检查 .so 的 ELF LOAD 段 alignment

AAR 模式（仅 ELF 段检查）：
  直接解压 AAR 提取 .so 文件到临时目录，用 check_elf_alignment.sh 检查 ELF LOAD 段对齐。
  AAR 是中间产物，zipalign 对齐由最终宿主 APK 打包时决定，因此跳过 zipalign 验证。
  支持多个 AAR 文件一起检查。

SO 模式（仅 ELF 段检查）：
  直接检查单个 .so 文件的 ELF LOAD 段对齐，无需解压或构建。
  适用于开发调试场景，快速验证 SO 库的对齐状态。

当 zipalign 验证未通过时（仅 APK 模式），自动尝试修复：
  1. zipalign -P 16 重新对齐
  2. 重新验证修复后的 APK
  注意：修复后的 APK 仅用于验证对齐方案，不做签名处理。

用法:
  ./check_alignment.py <APK文件路径> [HTML输出路径]
  ./check_alignment.py <AAR文件路径...> [HTML输出路径]
  ./check_alignment.py <SO文件路径> [HTML输出路径]
  ./check_alignment.py --batch <目录路径>

依赖: Python 3.6+（标准库即可）
工具: zipalign (来自 ANDROID_HOME/build-tools/)
      官方 check_elf_alignment.sh (与本脚本同目录)
"""

import os
import sys
from pathlib import Path

from models import Colors, CheckResult, ElfAlignResult, ZipalignResult
from checker_apk import check_apk, try_fix_apk
from checker_aar import check_aar
from checker_common import find_check_elf_script, get_ndk_version
from so_source_analyzer import analyze_so_sources, analyze_so_sources_from_aars
from report_html import generate_html_report
from report_terminal import (
    print_result, open_html_report, batch_check, print_batch_summary
)


def check_so(so_path: str) -> CheckResult:
    """检查单个 .so 文件的 ELF 对齐状态"""
    import subprocess
    import re
    
    zipalign_result = ZipalignResult()
    zipalign_result.status = "exempt"
    zipalign_result.summary = "SO 文件无需 zipalign 检查"
    
    result = CheckResult(
        file_path=so_path,
        file_size=str(os.path.getsize(so_path)),
        check_time="",
        zipalign=zipalign_result,
        elf_results=[],
        has_compressed_so=False,
        compressed_so_names=[]
    )
    
    script_path = find_check_elf_script()
    if not script_path:
        result.elf_results.append(ElfAlignResult(
            name=Path(so_path).name,
            arch="unknown",
            full_path=so_path,
            align_value="N/A",
            status="error",
            ndk_version="N/A",
            source_module="",
            source_type=""
        ))
        return result
    
    try:
        proc = subprocess.run(
            ['bash', script_path, so_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        raw_output = proc.stdout + proc.stderr
        
        def strip_ansi(text: str) -> str:
            """去除 ANSI 颜色码"""
            text = re.sub(r'\x1b\[[0-9;]*m', '', text)
            text = re.sub(r'\\e\[[0-9;]*m', '', text)
            return text
        
        for line in raw_output.splitlines():
            line = strip_ansi(line.strip())
            
            # 尝试匹配 ELF 检查脚本的输出格式
            # 格式示例: libaafcrop.so: ALIGNED (2**14)
            match = re.match(r'^(.+?\.so):\s+(ALIGNED|UNALIGNED)\s+\((.+?)\)$', line)
            if not match:
                # 尝试其他可能的格式
                match = re.match(r'^(.+?\.so):\s+(ALIGNED|UNALIGNED)', line)
                if not match:
                    continue
                align_value = "unknown"
            else:
                align_value = match.group(3)
            
            file_path = match.group(1)
            status_str = match.group(2)
            
            so_name = Path(file_path).name
            arch = "unknown"
            
            # 从路径中提取架构信息
            parts = file_path.replace('\\', '/').split('/')
            for i, part in enumerate(parts):
                if part in ('lib', 'jni') and i + 1 < len(parts):
                    arch = parts[i + 1]
                    break
            
            # 检测 NDK 版本：优先使用原始 so_path（绝对路径）
            ndk_version = get_ndk_version(so_path)
            
            result.elf_results.append(ElfAlignResult(
                name=so_name,
                arch=arch,
                full_path=file_path,
                align_value=align_value,
                status="pass" if status_str == "ALIGNED" else "fail",
                ndk_version=ndk_version,
                source_module="",
                source_type=""
            ))
        
        return result
        
    except subprocess.TimeoutExpired:
        result.elf_results.append(ElfAlignResult(
            name=Path(so_path).name,
            arch="unknown",
            full_path=so_path,
            align_value="N/A",
            status="error",
            ndk_version="N/A",
            source_module="",
            source_type=""
        ))
        return result
    except Exception as e:
        result.elf_results.append(ElfAlignResult(
            name=Path(so_path).name,
            arch="unknown",
            full_path=so_path,
            align_value="N/A",
            status="error",
            ndk_version="N/A",
            source_module="",
            source_type=""
        ))
        return result


def main():
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} <APK文件路径> [HTML输出路径]")
        print(f"  {sys.argv[0]} <AAR文件路径...> [HTML输出路径]")
        print(f"  {sys.argv[0]} <SO文件路径> [HTML输出路径]")
        print(f"  {sys.argv[0]} --batch <目录路径>")
        print()
        print("示例:")
        print(f"  {sys.argv[0]} app-release.apk")
        print(f"  {sys.argv[0]} my-library.aar")
        print(f"  {sys.argv[0]} lib1.aar lib2.aar  # 多 AAR 合并检查")
        print(f"  {sys.argv[0]} libnative.so  # 直接检查 SO 文件")
        print(f"  {sys.argv[0]} --batch ./apks/")
        print()
        print("说明:")
        print("  APK: 直接检查 16KB 对齐（zipalign + ELF），失败时自动尝试 zipalign 修复")
        print("  AAR: 直接解压提取 .so 检查 ELF LOAD 段对齐（无需编译，秒级完成）")
        print("       AAR 是中间产物，zipalign 由宿主 APK 决定，因此跳过 zipalign 验证")
        print("       支持多个 AAR 文件一起检查")
        print("  SO:  直接检查单个 .so 文件的 ELF LOAD 段对齐（开发调试专用）")
        print()
        print("检查项:")
        print("  APK: 1. 官方 zipalign -c -P 16 -v 4 验证 APK 整体对齐")
        print("       2. 官方 check_elf_alignment.sh 检查 .so 的 ELF LOAD 段对齐")
        print("  AAR: 仅 ELF LOAD 段对齐检查（核心检查项）")
        print("  SO:  仅 ELF LOAD 段对齐检查（开发调试）")
        sys.exit(1)

    # ==================== 批量模式 ====================
    if sys.argv[1] == "--batch":
        if len(sys.argv) < 3:
            print("错误: 请指定目录路径")
            sys.exit(1)

        directory = sys.argv[2]
        if not os.path.isdir(directory):
            print(f"错误: 目录不存在: {directory}")
            sys.exit(1)

        results = batch_check(directory)
        print_batch_summary(results)

        for r in results:
            html_path = r.file_path.rsplit('.', 1)[0] + '_alignment_report.html'
            generate_html_report(r, html_path)

        failed_count = sum(1 for r in results if r.zipalign.status == "fail" or r.elf_failed > 0)
        sys.exit(1 if failed_count > 0 else 0)

    # ==================== 单文件 / 多 AAR 模式 ====================
    file_args = list(sys.argv[1:])

    if not file_args:
        print("错误: 请指定至少一个文件")
        sys.exit(1)

    # 分离 AAR 文件和其他参数
    aar_paths = []
    other_args = []
    for arg in file_args:
        if os.path.isfile(arg) and Path(arg).suffix.lower() == '.aar':
            aar_paths.append(arg)
        else:
            other_args.append(arg)

    # 判断模式
    if len(aar_paths) >= 1:
        is_aar = True
        is_so = False
        html_output = None
        for arg in other_args:
            if arg.endswith('.html'):
                html_output = arg
    else:
        is_aar = False
        file_path = file_args[0]
        html_output = file_args[1] if len(file_args) > 1 else None

        if not os.path.isfile(file_path):
            print(f"错误: 文件不存在: {file_path}")
            sys.exit(1)

        ext = Path(file_path).suffix.lower()
        if ext not in ('.apk', '.so'):
            print(f"错误: 不支持的文件格式: {ext}")
            print("支持的格式: .apk, .aar, .so")
            sys.exit(1)
        
        is_so = (ext == '.so')

    # ==================== 执行检查 ====================
    if is_aar:
        # AAR 模式：直接解压检查 ELF 段
        result = check_aar(aar_paths)

        if html_output:
            html_path = html_output
        else:
            html_path = aar_paths[0].rsplit('.', 1)[0] + '_alignment_report.html'

        # SO 来源分析：直接从原始 AAR 中提取 .so 列表建立映射
        so_source_map = analyze_so_sources_from_aars(aar_paths)
        if so_source_map:
            result.so_source_map = so_source_map
            for elf_r in result.elf_results:
                if elf_r.name in so_source_map:
                    info = so_source_map[elf_r.name]
                    elf_r.source_module = info.get('module', '')
                    elf_r.source_type = info.get('type', '')
    elif is_so:
        # SO 模式：直接检查单个 .so 文件
        result = check_so(file_path)
        
        if html_output:
            html_path = html_output
        else:
            html_path = file_path.rsplit('.', 1)[0] + '_alignment_report.html'
    else:
        # APK 模式
        if html_output:
            html_path = html_output
        else:
            html_path = file_path.rsplit('.', 1)[0] + '_alignment_report.html'

        result = check_apk(file_path)

        # SO 来源分析：尝试从项目构建产物路径反推
        project_root, so_source_map = analyze_so_sources(file_path)
        if project_root:
            result.project_root = project_root
            result.so_source_map = so_source_map
            for elf_r in result.elf_results:
                if elf_r.name in so_source_map:
                    info = so_source_map[elf_r.name]
                    elf_r.source_module = info.get('module', '')
                    elf_r.source_type = info.get('type', '')

    # ==================== 结果处理 ====================
    c = Colors
    zipalign_failed = result.zipalign.status == "fail"
    has_compressed = result.has_compressed_so
    elf_failed = result.elf_failed > 0

    # zipalign 失败时先执行自动修复（仅 APK 模式）
    if zipalign_failed and not is_aar and not is_so:
        fix_result = try_fix_apk(file_path)
        result.fix_result = fix_result

    # 终端输出（包含修复前后对比）
    print_result(result)

    # 生成 HTML 报告
    generate_html_report(result, html_path)
    print(f"{c.CYAN}📄 HTML 报告已生成: {html_path}{c.NC}")

    # 自动打开 HTML 报告
    open_html_report(html_path)

    # 重放命令
    print()
    print(f"{c.YELLOW}🔄 重放命令:{c.NC}")
    if is_aar:
        aar_args = ' '.join(f'"{os.path.abspath(p)}"' for p in aar_paths)
        print(f"   python3 {os.path.abspath(__file__)} {aar_args}")
    else:
        print(f"   python3 {os.path.abspath(__file__)} \"{os.path.abspath(file_path)}\"")

    # 压缩存储提示
    if has_compressed:
        print()
        print(f"{c.YELLOW}⚠️  注意：{len(result.compressed_so_names)} 个 .so 被压缩存储，zipalign 无法修复此问题{c.NC}")
        print(f"{c.YELLOW}   需在 build.gradle 中设置 useLegacyPackaging = false 后重新打包{c.NC}")

    # ==================== 最终结论 ====================
    if elf_failed or (not is_aar and not is_so and (zipalign_failed or has_compressed)):
        if elf_failed:
            print(f"\n{c.YELLOW}⚠️  注意：ELF LOAD 段对齐问题无法通过 zipalign 修复，需重新编译 SO 文件{c.NC}")
        sys.exit(1)
    else:
        print()
        if is_aar:
            print(f"{c.GREEN}🎉 AAR 中所有 SO 库均已通过 ELF LOAD 段 16KB 对齐检查！{c.NC}")
        elif is_so:
            print(f"{c.GREEN}🎉 SO 库已通过 ELF LOAD 段 16KB 对齐检查！{c.NC}")
        else:
            print(f"{c.GREEN}🎉 所有 SO 库均已通过 16KB 对齐检查（zipalign + ELF LOAD 段）！{c.NC}")
        sys.exit(0)


if __name__ == "__main__":
    main()
