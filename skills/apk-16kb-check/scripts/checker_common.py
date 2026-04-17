#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_common.py
通用检查工具：工具查找、zipalign 验证、ELF 对齐检查、NDK 版本检测
"""

import os
import re
import struct
import zipfile
import subprocess
from typing import List, Optional, Tuple
from pathlib import Path

from models import (
    ElfAlignResult, ZipalignEntry, ZipalignResult
)


# ============================================================================
# 压缩存储检测
# ============================================================================
def check_compressed_so(apk_path: str) -> Tuple[bool, List[str]]:
    """检查 APK 中是否有 .so 文件以压缩方式存储

    返回: (has_compressed, compressed_names)
    """
    compressed_names = []
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.endswith('.so') and info.compress_type != 0:
                    so_name = Path(info.filename).name
                    if so_name not in compressed_names:
                        compressed_names.append(so_name)
    except Exception:
        pass
    return len(compressed_names) > 0, compressed_names


# ============================================================================
# 工具查找
# ============================================================================
def find_tool(tool_name: str) -> Optional[str]:
    """在 ANDROID_HOME/build-tools/ 中查找工具，优先高版本"""
    android_home = os.environ.get('ANDROID_HOME', '')
    if not android_home:
        return None

    build_tools_dir = os.path.join(android_home, 'build-tools')
    if not os.path.isdir(build_tools_dir):
        return None

    # 列出所有版本目录，按版本号降序排序
    versions = []
    for d in os.listdir(build_tools_dir):
        tool_path = os.path.join(build_tools_dir, d, tool_name)
        if os.path.isfile(tool_path) and os.access(tool_path, os.X_OK):
            versions.append((d, tool_path))

    if not versions:
        return None

    versions.sort(key=lambda x: x[0], reverse=True)
    return versions[0][1]


def find_check_elf_script() -> Optional[str]:
    """查找官方 check_elf_alignment.sh 脚本（与本脚本同目录）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(script_dir, 'check_elf_alignment.sh')
    if os.path.isfile(script_path) and os.access(script_path, os.X_OK):
        return script_path
    return None


# ============================================================================
# 官方 zipalign 验证（仅 APK）
# ============================================================================
def run_zipalign_verify(apk_path: str) -> ZipalignResult:
    """运行官方 zipalign 验证"""
    result = ZipalignResult()

    zipalign_path = find_tool('zipalign')
    if not zipalign_path:
        return result

    result.available = True

    try:
        # 运行 zipalign -c -P 16 -v 4 <apk>
        proc = subprocess.run(
            [zipalign_path, '-c', '-P', '16', '-v', '4', apk_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        result.output = proc.stdout + proc.stderr

        # 统计并解析每行条目
        for line in result.output.splitlines():
            line = line.strip()
            # 匹配 BAD 条目
            m_bad = re.match(r'^(\d+)\s+(.+?)\s+\(BAD\s*-\s*(\d+)\)$', line)
            if m_bad:
                result.entries.append(ZipalignEntry(
                    offset=m_bad.group(1),
                    file_path=m_bad.group(2),
                    status="fail",
                    detail=f"实际偏移 {m_bad.group(3)}"
                ))
                continue
            # 匹配 OK - compressed 条目
            m_comp = re.match(r'^(\d+)\s+(.+?)\s+\(OK\s*-\s*compressed\)$', line)
            if m_comp:
                result.entries.append(ZipalignEntry(
                    offset=m_comp.group(1),
                    file_path=m_comp.group(2),
                    status="compressed",
                ))
                continue

        result.ok_count = result.output.count('(OK')
        result.fail_count = result.output.count('(BAD')
        # compressed_count 只统计 .so 文件（其他压缩文件属于正常情况）
        result.compressed_count = sum(
            1 for e in result.entries
            if e.status == "compressed" and e.file_path.endswith('.so')
        )
        result.total_count = result.ok_count + result.fail_count

        # 判断结果
        if 'Verification successful' in result.output:
            result.status = "pass"
            result.summary = "✅ 验证通过"
        elif 'Verification FAILED' in result.output:
            result.status = "fail"
            result.summary = "❌ 验证失败"
        else:
            # 根据 exit code 判断
            result.status = "pass" if proc.returncode == 0 else "fail"
            result.summary = "✅ 验证通过" if result.status == "pass" else "❌ 验证失败"

    except subprocess.TimeoutExpired:
        result.status = "fail"
        result.summary = "⚠️ 验证超时"
        result.output = "验证执行超时"
    except Exception as e:
        result.status = "fail"
        result.summary = f"⚠️ 验证出错: {e}"
        result.output = str(e)

    return result


# ============================================================================
# ELF LOAD 段对齐检查（使用官方 check_elf_alignment.sh）
# ============================================================================
def run_elf_check(apk_path: str, extracted_so_dir: str = None) -> Tuple[List[ElfAlignResult], str]:
    """使用官方 check_elf_alignment.sh 检查 APK 中 .so 文件的 ELF 对齐

    Args:
        apk_path: APK/AAR 文件路径或已解压的目录路径
        extracted_so_dir: 已解压的 SO 文件目录，用于 NDK 版本检测。
                         如果提供，则直接从该目录中查找 SO 文件检测 NDK 版本，
                         避免重复解压。如果不提供，则跳过 NDK 版本检测。

    返回: (结果列表, 脚本原始输出)
    """
    results = []
    script_path = find_check_elf_script()

    if not script_path:
        return results, "⚠️ 未找到 check_elf_alignment.sh 脚本"

    # 确保 zipalign 在 PATH 中（官方脚本内部也会调用 zipalign）
    env = os.environ.copy()
    zipalign_path = find_tool('zipalign')
    if zipalign_path:
        zipalign_dir = os.path.dirname(zipalign_path)
        env['PATH'] = zipalign_dir + ':' + env.get('PATH', '')

    try:
        proc = subprocess.run(
            ['bash', script_path, apk_path],
            capture_output=True,
            text=True,
            timeout=120,
            env=env
        )
        raw_output = proc.stdout + proc.stderr

        def strip_ansi(text: str) -> str:
            """去除 ANSI 颜色码（真正的 escape 和字面量 \\e[...m 两种形式）"""
            text = re.sub(r'\x1b\[[0-9;]*m', '', text)
            text = re.sub(r'\\e\[[0-9;]*m', '', text)
            return text

        for line in raw_output.splitlines():
                line = strip_ansi(line.strip())

                match = re.match(r'^(.+?\.so):\s+(ALIGNED|UNALIGNED)\s+\((.+?)\)$', line)
                if not match:
                    continue

                file_path = match.group(1)
                status_str = match.group(2)
                align_value = match.group(3)

                # 从路径中提取架构和文件名
                so_name = Path(file_path).name
                arch = "unknown"
                parts = file_path.replace('\\', '/').split('/')
                for i, part in enumerate(parts):
                    if part in ('lib', 'jni') and i + 1 < len(parts):
                        arch = parts[i + 1]
                        break

                # 根据 AOSP 官方要求，只检查 64 位架构的 SO 文件
                if arch in ('armeabi-v7a', 'x86'):
                    results.append(ElfAlignResult(
                        name=so_name,
                        arch=arch,
                        full_path=file_path,
                        align_value=align_value,
                        status="exempt",
                        ndk_version="未知",
                    ))
                else:
                    results.append(ElfAlignResult(
                        name=so_name,
                        arch=arch,
                        full_path=file_path,
                        align_value=align_value,
                        status="pass" if status_str == "ALIGNED" else "fail",
                        ndk_version="未知",
                    ))

        # 如果提供了已解压的 SO 目录，直接从中检测 NDK 版本
        # 官方脚本会在退出时清理自己的临时目录，所以不能依赖脚本输出的路径
        if results and extracted_so_dir:
            _detect_ndk_versions_from_dir(extracted_so_dir, results)

        return results, raw_output

    except subprocess.TimeoutExpired:
        return results, "⚠️ check_elf_alignment.sh 执行超时"
    except Exception as e:
        return results, f"⚠️ check_elf_alignment.sh 执行出错: {e}"


def _detect_ndk_versions_from_dir(so_dir: str, results: List[ElfAlignResult]) -> None:
    """从已解压的目录中查找 SO 文件并检测 NDK 版本
    
    遍历目录查找与 results 中匹配的 SO 文件（按架构+文件名匹配），
    然后调用 get_ndk_version 检测 NDK 版本。
    
    Args:
        so_dir: 已解压的 SO 文件所在目录
        results: ELF 检查结果列表，会原地更新 ndk_version 字段
    """
    # 构建目录中所有 SO 文件的索引: (arch, name) -> 文件路径
    so_file_index = {}
    for root, dirs, files in os.walk(so_dir):
        for f in files:
            if f.endswith('.so'):
                full_path = os.path.join(root, f)
                # 从路径中提取架构信息
                rel_path = os.path.relpath(full_path, so_dir)
                parts = rel_path.replace('\\', '/').split('/')
                arch = "unknown"
                for i, part in enumerate(parts):
                    if part in ('lib', 'jni') and i + 1 < len(parts):
                        arch = parts[i + 1]
                        break
                so_file_index[(arch, f)] = full_path
                # 同时用 (unknown, name) 作为兜底
                if ("unknown", f) not in so_file_index:
                    so_file_index[("unknown", f)] = full_path

    # 为每个 result 查找对应的 SO 文件并检测 NDK 版本
    # 使用缓存避免同一文件重复检测
    ndk_cache = {}  # 文件路径 -> NDK 版本
    for r in results:
        # 优先按 (arch, name) 精确匹配
        so_path = so_file_index.get((r.arch, r.name))
        if not so_path:
            # 兜底按 (unknown, name) 匹配
            so_path = so_file_index.get(("unknown", r.name))
        
        if so_path:
            if so_path not in ndk_cache:
                ndk_cache[so_path] = get_ndk_version(so_path)
            r.ndk_version = ndk_cache[so_path]


# ============================================================================
# zipalign 修复工具
# ============================================================================
def run_zipalign_fix(input_apk: str, output_apk: str) -> Tuple[bool, str]:
    """执行 zipalign -P 16 对齐

    返回: (成功, 错误信息)
    """
    zipalign_path = find_tool('zipalign')
    if not zipalign_path:
        return False, "未找到 zipalign 工具"

    try:
        proc = subprocess.run(
            [zipalign_path, '-P', '16', '-f', '4', input_apk, output_apk],
            capture_output=True,
            text=True,
            timeout=120
        )
        if proc.returncode == 0 and os.path.isfile(output_apk):
            return True, ""
        else:
            error = proc.stderr.strip() or proc.stdout.strip() or f"exit code: {proc.returncode}"
            return False, f"zipalign 执行失败: {error}"
    except subprocess.TimeoutExpired:
        return False, "zipalign 执行超时"
    except Exception as e:
        return False, f"zipalign 执行出错: {e}"


# ============================================================================
# NDK 版本检测
# ============================================================================

def _get_ndk_from_elf_note(so_path: str) -> Optional[str]:
    """通过读取 ELF .note.android.ident 段精确获取 NDK 版本信息
    
    纯 Python 实现，不依赖外部工具（readelf/objdump）。
    直接解析 ELF 文件头和段表，定位 .note.android.ident 段，
    从中提取 Android API 级别、NDK 版本号和构建号。
    
    仅 NDK r14+ 编译的 SO 文件包含此信息。
    
    Returns:
        成功返回版本字符串（如 "NDK r28 (12077973), API 24"），失败返回 None
    """
    NDK_RESERVED_SIZE = 64
    
    try:
        with open(so_path, 'rb') as f:
            # ---- 解析 ELF 文件头 ----
            magic = f.read(4)
            if magic != b'\x7fELF':
                return None
            
            ei_class = struct.unpack('B', f.read(1))[0]  # 1=32bit, 2=64bit
            ei_data = struct.unpack('B', f.read(1))[0]   # 1=LE, 2=BE
            
            if ei_data == 1:
                endian = '<'
            elif ei_data == 2:
                endian = '>'
            else:
                return None
            
            if ei_class == 1:
                # ELF32: e_shoff at offset 32, e_shentsize at 46, e_shnum at 48, e_shstrndx at 50
                f.seek(32)
                e_shoff = struct.unpack(endian + 'I', f.read(4))[0]
                f.seek(46)
                e_shentsize = struct.unpack(endian + 'H', f.read(2))[0]
                e_shnum = struct.unpack(endian + 'H', f.read(2))[0]
                e_shstrndx = struct.unpack(endian + 'H', f.read(2))[0]
                sh_struct = endian + 'IIIIIIIIII'  # 10 个 uint32
            elif ei_class == 2:
                # ELF64: e_shoff at offset 40, e_shentsize at 58, e_shnum at 60, e_shstrndx at 62
                f.seek(40)
                e_shoff = struct.unpack(endian + 'Q', f.read(8))[0]
                f.seek(58)
                e_shentsize = struct.unpack(endian + 'H', f.read(2))[0]
                e_shnum = struct.unpack(endian + 'H', f.read(2))[0]
                e_shstrndx = struct.unpack(endian + 'H', f.read(2))[0]
                sh_struct = endian + 'IIQQQQIIQQ'  # ELF64 段头格式
            else:
                return None
            
            if e_shoff == 0 or e_shnum == 0:
                return None
            
            # ---- 读取段名字符串表 ----
            f.seek(e_shoff + e_shstrndx * e_shentsize)
            shstrtab_hdr = struct.unpack(sh_struct, f.read(e_shentsize))
            # shstrtab_hdr: [sh_name, sh_type, sh_flags, sh_addr, sh_offset, sh_size, ...]
            if ei_class == 1:
                strtab_offset = shstrtab_hdr[4]
                strtab_size = shstrtab_hdr[5]
            else:
                strtab_offset = shstrtab_hdr[4]
                strtab_size = shstrtab_hdr[5]
            
            f.seek(strtab_offset)
            strtab = f.read(strtab_size)
            
            # ---- 遍历段表，查找 .note.android.ident ----
            target_name = b'.note.android.ident'
            note_offset = None
            note_size = None
            
            for i in range(e_shnum):
                f.seek(e_shoff + i * e_shentsize)
                sh = struct.unpack(sh_struct, f.read(e_shentsize))
                sh_name_idx = sh[0]
                
                # 从字符串表中提取段名
                name_end = strtab.find(b'\x00', sh_name_idx)
                if name_end == -1:
                    name_end = len(strtab)
                sec_name = strtab[sh_name_idx:name_end]
                
                if sec_name == target_name:
                    if ei_class == 1:
                        note_offset = sh[4]
                        note_size = sh[5]
                    else:
                        note_offset = sh[4]
                        note_size = sh[5]
                    break
            
            if note_offset is None or note_size == 0:
                return None
            
            # ---- 解析 NOTE 段 ----
            f.seek(note_offset)
            sec_data = f.read(note_size)
            
            if len(sec_data) != note_size:
                return None
            
            def _round_up(val, step):
                return (val + (step - 1)) // step * step
            
            pos = 0
            while pos < len(sec_data):
                if pos + 12 > len(sec_data):
                    break
                namesz, descsz, kind = struct.unpack_from(endian + 'III', sec_data, pos)
                pos += 12
                
                name_padded = _round_up(namesz, 4)
                desc_padded = _round_up(descsz, 4)
                
                if pos + name_padded + desc_padded > len(sec_data):
                    break
                
                name = sec_data[pos:pos + namesz]
                pos += name_padded
                desc = sec_data[pos:pos + descsz]
                pos += desc_padded
                
                # 去掉 NUL 终止符
                if name and name[-1:] == b'\x00':
                    name = name[:-1]
                
                if name == b'Android' and kind == 1:
                    # 解析 descriptor
                    if len(desc) < 4:
                        continue
                    android_api = struct.unpack_from(endian + 'I', desc, 0)[0]
                    
                    # NDK r14+ 才有后续字段
                    if len(desc) < 4 + NDK_RESERVED_SIZE * 2:
                        return f"API {android_api}"
                    
                    ndk_version_raw = desc[4:4 + NDK_RESERVED_SIZE]
                    ndk_build_raw = desc[4 + NDK_RESERVED_SIZE:4 + NDK_RESERVED_SIZE * 2]
                    
                    ndk_version = ndk_version_raw.decode('utf-8', errors='ignore').rstrip('\x00').strip()
                    ndk_build = ndk_build_raw.decode('utf-8', errors='ignore').rstrip('\x00').strip()
                    
                    if not ndk_version:
                        return f"API {android_api}"
                    
                    # 构建版本字符串
                    parts = [f"NDK {ndk_version}"]
                    if ndk_build:
                        parts[0] += f" ({ndk_build})"
                    parts.append(f"API {android_api}")
                    return ', '.join(parts)
            
            return None
    
    except Exception:
        return None


def _get_ndk_from_comment(so_path: str) -> str:
    """通过 .comment 段和 strings 命令检测 NDK/编译器版本（Fallback 方法）
    
    当 .note.android.ident 段不存在时使用此方法。
    能检测非 NDK 编译的 SO（如 GCC 编译、自定义工具链），但精确度较低。
    """
    try:
        # 使用 objdump 读取 .comment 段
        proc = subprocess.run(
            ['objdump', '-s', '-j', '.comment', so_path],
            capture_output=True,
            text=True,
            timeout=60  # 增加超时时间
        )
        
        if proc.returncode == 0 and proc.stdout:
            output = proc.stdout
            
            clang_version = None
            ndk_version = None
            lld_version = None
            gcc_version = None
            
            # 扩展 Clang 版本信息匹配模式
            clang_patterns = [
                r'clang.*?(\d+\.\d+\.\d+)',  # 原始模式
                r'clang version (\d+\.\d+\.\d+)',  # 标准格式
                r'clang-(\d+\.\d+\.\d+)',  # 连字符格式
                r'clang/(\d+\.\d+\.\d+)',  # 斜杠格式
            ]
            
            for pattern in clang_patterns:
                clang_match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
                if clang_match:
                    clang_version = clang_match.group(1)
                    break
            
            # 扩展基于的构建版本匹配模式
            based_patterns = [
                r'based on r(\d+[a-z]?)',  # 原始模式
                r'r(\d+[a-z]?)\s+based',  # 变体格式
                r'NDK r(\d+[a-z]?)',  # 直接 NDK 版本
                r'android-ndk-r(\d+)',  # 完整格式
            ]
            
            for pattern in based_patterns:
                based_match = re.search(pattern, output, re.IGNORECASE)
                if based_match:
                    ndk_version = based_match.group(1)
                    break
            
            # 扩展 LLD 链接器信息匹配模式
            lld_patterns = [
                r'Linker: LLD (\d+\.\d+\.\d+)',  # 原始模式
                r'LLD (\d+\.\d+\.\d+)',  # 简化格式
                r'lld (\d+\.\d+\.\d+)',  # 小写格式
            ]
            
            for pattern in lld_patterns:
                lld_match = re.search(pattern, output, re.IGNORECASE)
                if lld_match:
                    lld_version = lld_match.group(1)
                    break
            
            # 查找 GCC 版本信息
            gcc_patterns = [
                r'gcc.*?(\d+\.\d+\.\d+)',
                r'gcc version (\d+\.\d+\.\d+)',
                r'gcc-(\d+\.\d+\.\d+)',
            ]
            
            for pattern in gcc_patterns:
                gcc_match = re.search(pattern, output, re.DOTALL | re.IGNORECASE)
                if gcc_match:
                    gcc_version = gcc_match.group(1)
                    break
            
            # 根据可用信息构建版本字符串
            if clang_version and ndk_version:
                ndk_range = ""
                if clang_version.startswith('19.'):
                    ndk_range = "r25+"
                elif clang_version.startswith('18.'):
                    ndk_range = "r25"
                elif clang_version.startswith('17.'):
                    ndk_range = "r25"
                elif clang_version.startswith('16.'):
                    ndk_range = "r25"
                elif clang_version.startswith('15.'):
                    ndk_range = "r24"
                elif clang_version.startswith('14.'):
                    ndk_range = "r23"
                elif clang_version.startswith('13.'):
                    ndk_range = "r23"
                elif clang_version.startswith('12.'):
                    ndk_range = "r23"
                elif clang_version.startswith('11.'):
                    ndk_range = "r21"
                elif clang_version.startswith('10.'):
                    ndk_range = "r21"
                elif clang_version.startswith('9.'):
                    ndk_range = "r21"
                
                if ndk_range:
                    return f"Clang {clang_version} (NDK {ndk_range}, r{ndk_version})"
                else:
                    return f"Clang {clang_version} (r{ndk_version})"
            
            elif clang_version:
                return f"Clang {clang_version}"
            elif gcc_version:
                return f"GCC {gcc_version}"
            elif ndk_version:
                return f"NDK r{ndk_version}"
            elif lld_version:
                return f"LLD {lld_version}"
            
            # 查找 Android 构建信息
            android_match = re.search(r'Android \((\d+)\)', output)
            if android_match:
                android_build = android_match.group(1)
                return f"Android {android_build}"
        
        # 如果 objdump 不可用或没有 .comment 段，尝试使用 strings 命令
        proc = subprocess.run(
            ['strings', so_path],
            capture_output=True,
            text=True,
            timeout=60  # 增加超时时间
        )
        
        if proc.returncode == 0 and proc.stdout:
            output = proc.stdout
            
            # 扩展 strings 命令的匹配模式
            clang_patterns = [
                r'clang(?:-\w+)?-(\d+\.\d+\.\d+)',
                r'clang version (\d+\.\d+\.\d+)',
                r'clang/(\d+\.\d+\.\d+)',
            ]
            
            for pattern in clang_patterns:
                clang_match = re.search(pattern, output, re.IGNORECASE)
                if clang_match:
                    clang_version = clang_match.group(1)
                    return f"Clang {clang_version}"
            
            gcc_patterns = [
                r'gcc(?:-\w+)?-(\d+\.\d+\.\d+)',
                r'gcc version (\d+\.\d+\.\d+)',
            ]
            
            for pattern in gcc_patterns:
                gcc_match = re.search(pattern, output, re.IGNORECASE)
                if gcc_match:
                    gcc_version = gcc_match.group(1)
                    return f"GCC {gcc_version}"
            
            ndk_patterns = [
                r'ndk-r(\d+)',
                r'android-ndk-r(\d+)',
                r'NDK r(\d+)',
            ]
            
            for pattern in ndk_patterns:
                ndk_match = re.search(pattern, output, re.IGNORECASE)
                if ndk_match:
                    ndk_version = ndk_match.group(1)
                    return f"NDK r{ndk_version}"
            
            # 匹配 NDK 路径格式，如 ndk/25.1.8937393 或 ndk/27.0.12077973
            ndk_path_match = re.search(r'ndk/(\d+)\.\d+\.\d+', output)
            if ndk_path_match:
                ndk_major = ndk_path_match.group(1)
                ndk_full = ndk_path_match.group(0).split('/')[-1]
                return f"NDK r{ndk_major} ({ndk_full})"
            
            # 尝试匹配构建哈希值
            hash_match = re.search(r'r(\d+[a-f0-9]{6,})', output, re.IGNORECASE)
            if hash_match:
                build_hash = hash_match.group(1)
                return f"Build r{build_hash}"
    
    except subprocess.TimeoutExpired:
        return "检测超时"
    except FileNotFoundError:
        return "工具未找到"
    except Exception as e:
        # 记录错误但不影响主流程
        import sys
        print(f"NDK 版本检测错误 ({so_path}): {e}", file=sys.stderr)
        return "检测失败"
    
    return "未知"


def get_ndk_version(so_path: str) -> str:
    """检测 SO 文件的 NDK 版本信息
    
    优先通过 ELF .note.android.ident 段精确获取（纯 Python，无外部依赖），
    失败则 fallback 到 .comment 段 + strings 命令近似检测。
    """
    # 优先：读取 ELF NOTE 段（精确，NDK r14+ 编译的 SO）
    note_result = _get_ndk_from_elf_note(so_path)
    if note_result:
        return note_result
    
    # Fallback：读取 .comment 段 + strings（近似，覆盖非 NDK 编译的 SO）
    return _get_ndk_from_comment(so_path)
