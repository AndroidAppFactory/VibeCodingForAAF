#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
check_alignment.py
检查 APK/AAR 中 .so 文件的 16KB 对齐状态（两项检查）：
  1. 官方 zipalign 验证：运行 zipalign -c -P 16 -v 4 验证 APK 整体对齐
  2. ELF LOAD 段对齐：运行官方 check_elf_alignment.sh 检查 .so 的 ELF LOAD 段 alignment

当输入为 AAR 时：
  自动从 cache 目录获取 AAFFor16KB 项目（不存在则 git clone），
  通过 build_aar_apk.sh 将 AAR 编译为 APK，然后对生成的 APK 进行检查。
  支持多个 AAR 文件合并到同一 APK 中一起检查。

当 zipalign 验证未通过时（APK 和 AAR 模式均适用），自动尝试修复：
  1. zipalign -P 16 重新对齐
  2. 重新验证修复后的 APK
  注意：修复后的 APK 仅用于验证对齐方案，不做签名处理。

用法:
  ./check_alignment.py <APK文件路径> [HTML输出路径]
  ./check_alignment.py <AAR文件路径...> [HTML输出路径]
  ./check_alignment.py --clean <AAR文件路径...>  # 清空历史 AAR 后构建
  ./check_alignment.py --batch <目录路径>  # 批量检查目录下所有 APK/AAR

依赖: Python 3.6+（标准库即可）
工具: zipalign (来自 ANDROID_HOME/build-tools/)
      官方 check_elf_alignment.sh (与本脚本同目录)
      git (AAR 首次检查时 clone AAFFor16KB 项目)
"""

import os
import sys
import re
import zipfile
import subprocess
import shutil
import html
import platform
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path


# ============================================================================
# 常量定义
# ============================================================================
ALIGN_SIZE = 16384  # 16KB = 0x4000

# 终端颜色
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'  # 无颜色


# ============================================================================
# 数据结构
# ============================================================================
@dataclass
class ElfAlignResult:
    """单个 .so 文件的 ELF LOAD 段对齐检查结果"""
    name: str           # 文件名
    arch: str           # 架构
    full_path: str      # ZIP 内完整路径
    align_value: str = ""  # 对齐值原始输出（如 2**14）
    status: str = "pass"  # "pass" / "fail" / "warn"(无法读取)
    error: str = ""     # 错误信息
    source_module: str = ""  # 来源模块/AAR（如 "com.example:sdk:1.2.3" 或 ":native-module"）
    source_type: str = ""    # 来源类型: "project" / "external" / ""(未知)


@dataclass
class ZipalignEntry:
    """zipalign 输出中的单条验证条目"""
    offset: str           # 偏移量
    file_path: str        # 文件路径
    status: str           # "ok" / "fail" / "compressed"
    detail: str = ""      # 额外信息（如 BAD 的偏移值）


@dataclass
class ZipalignResult:
    """官方 zipalign 验证结果"""
    available: bool = False
    status: str = "unavailable"  # "pass" / "fail" / "unavailable"
    summary: str = "⚠️ zipalign 不可用"
    ok_count: int = 0
    fail_count: int = 0
    compressed_count: int = 0
    total_count: int = 0
    output: str = ""
    entries: List[ZipalignEntry] = field(default_factory=list)  # 解析后的条目


@dataclass
class CheckResult:
    """检查结果汇总"""
    file_path: str
    file_size: str
    check_time: str
    elf_results: List[ElfAlignResult] = field(default_factory=list)
    zipalign: ZipalignResult = field(default_factory=ZipalignResult)
    elf_script_output: str = ""  # 官方脚本原始输出
    has_compressed_so: bool = False  # 是否有压缩存储的 .so
    compressed_so_names: List[str] = field(default_factory=list)  # 压缩存储的 .so 名称
    source_aar_paths: List[str] = field(default_factory=list)  # 原始 AAR 路径（AAR 模式时记录）
    project_root: str = ""  # Android 项目根目录（APK 模式时从路径反推）
    so_source_map: Dict[str, Dict] = field(default_factory=dict)  # .so名 → {module, type, aar_path} 映射
    fix_result: Optional['FixResult'] = None  # 自动修复结果（zipalign 失败时填充）

    # ELF 检查统计
    @property
    def elf_total(self) -> int:
        # 只统计需要检查的 64 位架构 SO 文件，忽略 32 位架构的豁免文件
        return sum(1 for r in self.elf_results if r.status != "exempt")

    @property
    def elf_passed(self) -> int:
        # 只统计需要检查的 64 位架构 SO 文件
        return sum(1 for r in self.elf_results if r.status == "pass")

    @property
    def elf_failed(self) -> int:
        # 只统计需要检查的 64 位架构 SO 文件
        return sum(1 for r in self.elf_results if r.status == "fail")

    def elf_exempt(self) -> int:
        # 统计 32 位架构的豁免 SO 文件数量
        return sum(1 for r in self.elf_results if r.status == "exempt")


# ============================================================================
# 压缩存储检测（辅助：检查 .so 是否被压缩存储）
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
        # zipalign -v 输出格式示例：
        #   50 lib/arm64-v8a/libfoo.so (OK)
        #   100 res/layout/main.xml (OK - compressed)
        #   200 lib/arm64-v8a/libbar.so (BAD - 12)
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
def run_elf_check(apk_path: str) -> Tuple[List[ElfAlignResult], str]:
    """使用官方 check_elf_alignment.sh 检查 APK 中 .so 文件的 ELF 对齐

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

        # 解析官方脚本输出
        # 官方脚本用 echo -e 输出 ANSI 颜色码，捕获时可能出现两种形式：
        #   真正的 ANSI: /path/libfoo.so: \x1b[32mALIGNED\x1b[0m (2**14)
        #   字面量:      /path/libfoo.so: \e[32mALIGNED\e[0m (2**14)
        # 统一去除后再匹配
        def strip_ansi(text: str) -> str:
            """去除 ANSI 颜色码（真正的 escape 和字面量 \\e[...m 两种形式）"""
            # 真正的 ANSI escape sequences
            text = re.sub(r'\x1b\[[0-9;]*m', '', text)
            # 字面量 \\e[...m（echo -e 未解析时）
            text = re.sub(r'\\e\[[0-9;]*m', '', text)
            return text

        for line in raw_output.splitlines():
                line = strip_ansi(line.strip())

                # 匹配 ELF 对齐结果行
                # 格式: /path/to/lib/arm64-v8a/libfoo.so: ALIGNED (2**14)
                # 或:   /path/to/lib/arm64-v8a/libfoo.so: UNALIGNED (2**12)
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
                # 32 位架构（armeabi-v7a、x86）不需要 16KB 对齐检查
                if arch in ('armeabi-v7a', 'x86'):
                    # 32 位架构，标记为豁免，不参与对齐检查统计
                    results.append(ElfAlignResult(
                        name=so_name,
                        arch=arch,
                        full_path=file_path,
                        align_value=align_value,
                        status="exempt",  # 新增状态：豁免检查
                    ))
                else:
                    # 64 位架构，正常检查
                    results.append(ElfAlignResult(
                        name=so_name,
                        arch=arch,
                        full_path=file_path,
                        align_value=align_value,
                        status="pass" if status_str == "ALIGNED" else "fail",
                    ))
        return results, raw_output

    except subprocess.TimeoutExpired:
        return results, "⚠️ check_elf_alignment.sh 执行超时"
    except Exception as e:
        return results, f"⚠️ check_elf_alignment.sh 执行出错: {e}"


# ============================================================================
# 自动修复：zipalign 重对齐
# ============================================================================
@dataclass
class FixResult:
    """自动修复结果"""
    attempted: bool = False        # 是否尝试了修复
    success: bool = False          # 修复是否成功
    aligned_path: str = ""         # 对齐后的 APK 路径
    verify_result: Optional[CheckResult] = None  # 修复后的验证结果
    error: str = ""                # 错误信息
    steps: List[str] = field(default_factory=list)  # 执行步骤日志


def run_zipalign_fix(input_apk: str, output_apk: str) -> Tuple[bool, str]:
    """执行 zipalign -P 16 对齐

    新版语法（Build-Tools 35+）：zipalign -P <pagesize_kb> [-f] <align> infile outfile
    -P 16: 16KB 页面对齐 .so 文件
    4: 基础对齐字节数
    注意：-P 和 -p 不能混用，-p 仅支持 4KB 对齐

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
                # pull 失败不阻塞流程，用已有代码继续
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

    # 如果目录已存在但不完整，先清理
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
        # APK 和所有临时产物都放在 AAFFor16KB 的 build 目录，不污染 AAR 原路径
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

    # 构建命令参数
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
            timeout=600  # 构建可能需要较长时间
        )

        # 从输出中提取 APK 路径
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


# ============================================================================
# SO 来源分析：APK → 项目根目录 → 依赖树 → .so 归属
# ============================================================================

# APK 产物路径的典型模式（从最具体到最通用）
_APK_OUTPUT_PATTERNS = [
    # {module}/build/outputs/apk/{flavor}/{buildType}/{apk}
    # {module}/build/outputs/apk/{buildType}/{apk}
    'build/outputs/apk/',
    # {module}/build/outputs/bundle/{variant}/{aab} (AAB 也适用)
    'build/outputs/bundle/',
    # {module}/build/intermediates/apk/{buildType}/{apk} (AGP 中间产物路径)
    'build/intermediates/apk/',
]


def detect_project_root(apk_path: str) -> Optional[Tuple[str, str]]:
    """从 APK 路径反推 Android 项目根目录和模块名

    匹配模式: {project_root}/{module}/build/outputs/apk/{variant}/{apk}

    返回: (project_root, module_name) 或 None
    """
    abs_path = os.path.abspath(apk_path)
    # 规范化路径分隔符
    normalized = abs_path.replace('\\', '/')

    for pattern in _APK_OUTPUT_PATTERNS:
        idx = normalized.find(pattern)
        if idx == -1:
            continue

        # pattern 之前的部分 = {project_root}/{module}
        module_path = normalized[:idx].rstrip('/')
        if not module_path:
            continue

        # 分离 module_name
        module_name = os.path.basename(module_path)
        project_root_candidate = os.path.dirname(module_path)

        # 验证: 项目根目录应包含 settings.gradle / settings.gradle.kts
        for settings_name in ('settings.gradle', 'settings.gradle.kts'):
            if os.path.isfile(os.path.join(project_root_candidate, settings_name)):
                return project_root_candidate, module_name

        # fallback: module 目录本身就是项目根（单模块项目）
        for settings_name in ('settings.gradle', 'settings.gradle.kts'):
            if os.path.isfile(os.path.join(module_path, settings_name)):
                return module_path, module_name

    return None


def _find_gradlew(project_root: str) -> Optional[str]:
    """在项目根目录查找 gradlew"""
    gradlew = os.path.join(project_root, 'gradlew')
    if os.path.isfile(gradlew) and os.access(gradlew, os.X_OK):
        return gradlew
    # Windows
    gradlew_bat = os.path.join(project_root, 'gradlew.bat')
    if os.path.isfile(gradlew_bat):
        return gradlew_bat
    return None


def run_gradle_dependencies(project_root: str, module_name: str,
                            variant: str = "release") -> List[str]:
    """运行 gradlew dependencies 获取依赖坐标列表

    返回: 依赖坐标列表（如 ["com.example:sdk:1.2.3", "androidx.core:core:1.12.0"]）
    """
    gradlew = _find_gradlew(project_root)
    if not gradlew:
        return []

    # 尝试常见的 configuration 名称
    configurations = [
        f"{variant}RuntimeClasspath",
        f"{variant}CompileClasspath",
        "releaseRuntimeClasspath",
        "releaseCompileClasspath",
    ]

    c = Colors
    for config in configurations:
        task = f":{module_name}:dependencies"
        try:
            proc = subprocess.run(
                [gradlew, task, '--configuration', config, '-q'],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=project_root
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return _parse_dependency_tree(proc.stdout)
        except (subprocess.TimeoutExpired, Exception):
            continue

    return []


def _parse_dependency_tree(output: str) -> List[str]:
    """解析 gradlew dependencies 输出，提取所有依赖坐标

    输出格式示例:
    +--- com.example:sdk:1.2.3
    |    +--- com.example:core:1.0.0
    \\--- androidx.core:core:1.12.0 -> 1.13.0 (*)

    返回: 去重后的坐标列表（group:artifact:version）
    """
    coords = set()
    # 匹配 group:artifact:version 模式（可能有 -> 升级标记和 (*) 标记）
    pattern = re.compile(r'[\w\-\.]+:[\w\-\.]+:[\w\-\.]+')

    for line in output.splitlines():
        # 跳过非依赖行
        stripped = line.strip()
        if not stripped or stripped.startswith('(') or stripped.startswith('No dependencies'):
            continue

        matches = pattern.findall(stripped)
        for m in matches:
            # 如果有 " -> " 升级标记，取升级后的版本
            if ' -> ' in stripped:
                # 提取实际使用的坐标
                parts = stripped.split(' -> ')
                if len(parts) == 2:
                    upgraded = pattern.findall(parts[1])
                    if upgraded:
                        # 用原坐标的 group:artifact + 升级后的 version
                        orig_parts = m.split(':')
                        up_parts = upgraded[0].split(':')
                        if len(orig_parts) >= 2 and len(up_parts) >= 1:
                            coords.add(f"{orig_parts[0]}:{orig_parts[1]}:{up_parts[-1]}")
                            continue
            coords.add(m)

    return sorted(coords)


def scan_gradle_cache_for_so(dependency_coords: List[str]) -> Dict[str, Dict]:
    """扫描 Gradle 缓存，找出每个依赖包含的 .so 文件

    搜索路径:
    1. ~/.gradle/caches/transforms-*/（AGP transform 缓存）
    2. ~/.gradle/caches/modules-*/files-*/（原始 AAR 下载缓存）

    返回: {so_name: {module: "group:artifact:version", type: "external", aar_path: "..."}}
    """
    so_map: Dict[str, Dict] = {}
    gradle_home = os.path.expanduser('~/.gradle')
    caches_dir = os.path.join(gradle_home, 'caches')

    if not os.path.isdir(caches_dir):
        return so_map

    # 将依赖坐标解析为 (group, artifact, version) 以便匹配目录名
    coord_parts = []
    for coord in dependency_coords:
        parts = coord.split(':')
        if len(parts) >= 3:
            coord_parts.append((parts[0], parts[1], parts[2], coord))
        elif len(parts) == 2:
            coord_parts.append((parts[0], parts[1], '', coord))

    if not coord_parts:
        return so_map

    # 策略 1: 扫描 transforms 缓存
    # transforms-3/*/transformed/ 下的目录名通常包含 artifact 名称
    _scan_transforms_cache(caches_dir, coord_parts, so_map)

    # 策略 2: 扫描 modules 缓存中的原始 AAR
    _scan_modules_cache(caches_dir, coord_parts, so_map)

    return so_map


def _scan_transforms_cache(caches_dir: str, coord_parts: list, so_map: Dict):
    """扫描 Gradle transforms 缓存"""
    for transforms_dir_name in os.listdir(caches_dir):
        if not transforms_dir_name.startswith('transforms-'):
            continue
        transforms_dir = os.path.join(caches_dir, transforms_dir_name)
        if not os.path.isdir(transforms_dir):
            continue

        # transforms-3/ 下有许多哈希目录
        try:
            for hash_dir in os.listdir(transforms_dir):
                hash_path = os.path.join(transforms_dir, hash_dir)
                if not os.path.isdir(hash_path):
                    continue

                transformed_dir = os.path.join(hash_path, 'transformed')
                if not os.path.isdir(transformed_dir):
                    continue

                # transformed/ 下的目录名通常是 artifact-version 格式
                for artifact_dir in os.listdir(transformed_dir):
                    artifact_dir_lower = artifact_dir.lower()
                    for group, artifact, version, coord in coord_parts:
                        # 匹配 artifact 名称（目录名可能是 artifact-version 或 artifact）
                        if artifact.lower() in artifact_dir_lower:
                            _collect_so_files(
                                os.path.join(transformed_dir, artifact_dir),
                                coord, "external", so_map
                            )
                            break
        except PermissionError:
            continue


def _scan_modules_cache(caches_dir: str, coord_parts: list, so_map: Dict):
    """扫描 Gradle modules 缓存中的原始 AAR"""
    for modules_dir_name in os.listdir(caches_dir):
        if not modules_dir_name.startswith('modules-'):
            continue
        files_dir = os.path.join(caches_dir, modules_dir_name, 'files-1')
        if not os.path.isdir(files_dir):
            continue

        try:
            for group_dir in os.listdir(files_dir):
                group_path = os.path.join(files_dir, group_dir)
                if not os.path.isdir(group_path):
                    continue

                for group, artifact, version, coord in coord_parts:
                    # group 目录名格式通常是 "com.example" 或 "com.example.sub"
                    if group_dir == group:
                        artifact_path = os.path.join(group_path, artifact)
                        if not os.path.isdir(artifact_path):
                            continue
                        # 遍历版本目录
                        for ver_dir in os.listdir(artifact_path):
                            ver_path = os.path.join(artifact_path, ver_dir)
                            if not os.path.isdir(ver_path):
                                continue
                            # 查找 AAR 文件并解压检查 .so
                            for hash_dir in os.listdir(ver_path):
                                file_path = os.path.join(ver_path, hash_dir)
                                if os.path.isdir(file_path):
                                    for f in os.listdir(file_path):
                                        if f.endswith('.aar'):
                                            _extract_so_from_aar(
                                                os.path.join(file_path, f),
                                                coord, so_map
                                            )
                                elif file_path.endswith('.aar'):
                                    _extract_so_from_aar(file_path, coord, so_map)
        except PermissionError:
            continue


def _collect_so_files(directory: str, coord: str, source_type: str, so_map: Dict):
    """递归收集目录下的 .so 文件"""
    if not os.path.isdir(directory):
        return
    try:
        for root, dirs, files in os.walk(directory):
            for f in files:
                if f.endswith('.so'):
                    if f not in so_map:
                        so_map[f] = {
                            'module': coord,
                            'type': source_type,
                            'path': os.path.join(root, f)
                        }
    except PermissionError:
        pass


def _extract_so_from_aar(aar_path: str, coord: str, so_map: Dict):
    """从 AAR 中提取 .so 文件名列表（不实际解压，只读目录）"""
    try:
        with zipfile.ZipFile(aar_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.endswith('.so'):
                    so_name = Path(info.filename).name
                    if so_name not in so_map:
                        so_map[so_name] = {
                            'module': coord,
                            'type': 'external',
                            'path': aar_path
                        }
    except Exception:
        pass


def reverse_lookup_so_in_transforms(so_names: set) -> Dict[str, Dict]:
    """反向查找：在 Gradle transforms 缓存中搜索包含指定 SO 的目录

    当正向匹配（依赖坐标→缓存目录）找不到时，用此方法反向查找。
    适用于本地 AAR（fileTree 引入）等不在 Maven 依赖树中的场景。

    搜索 ~/.gradle/caches/transforms-*/  下的所有 transformed/ 目录，
    找到包含目标 SO 的目录，从目录名推断来源。

    返回: {so_name: {module: "目录名(推断)", type: "external"}}
    """
    if not so_names:
        return {}

    so_map: Dict[str, Dict] = {}
    gradle_home = os.path.expanduser('~/.gradle')
    caches_dir = os.path.join(gradle_home, 'caches')
    if not os.path.isdir(caches_dir):
        return so_map

    try:
        for transforms_dir_name in os.listdir(caches_dir):
            if not transforms_dir_name.startswith('transforms-'):
                continue
            transforms_dir = os.path.join(caches_dir, transforms_dir_name)
            if not os.path.isdir(transforms_dir):
                continue

            for hash_dir in os.listdir(transforms_dir):
                hash_path = os.path.join(transforms_dir, hash_dir)
                if not os.path.isdir(hash_path):
                    continue

                transformed_dir = os.path.join(hash_path, 'transformed')
                if not os.path.isdir(transformed_dir):
                    continue

                for artifact_dir in os.listdir(transformed_dir):
                    artifact_path = os.path.join(transformed_dir, artifact_dir)
                    if not os.path.isdir(artifact_path):
                        continue

                    # 在此 artifact 目录下搜索 .so 文件
                    for root, dirs, files in os.walk(artifact_path):
                        for f in files:
                            if f in so_names and f not in so_map:
                                # 从目录名推断来源
                                # 目录名格式通常是 "artifact-version" 或 "ArtifactName-release"
                                source_name = artifact_dir
                                # 去除常见后缀使显示更清晰
                                for suffix in ('-release', '-debug'):
                                    if source_name.lower().endswith(suffix):
                                        source_name = source_name[:-len(suffix)]
                                        break
                                so_map[f] = {
                                    'module': source_name,
                                    'type': 'external',
                                    'path': os.path.join(root, f)
                                }

                    # 如果全部找到就提前退出
                    if so_names <= set(so_map.keys()):
                        return so_map
    except PermissionError:
        pass

    return so_map


def _get_project_modules(project_root: str, module_name: str) -> list:
    """解析 settings.gradle 获取所有子模块列表

    返回: [(mod_dir, mod_name), ...] 格式的列表
    """
    modules_to_check = [module_name]

    # 解析 settings.gradle 获取更多子模块
    for settings_name in ('settings.gradle', 'settings.gradle.kts'):
        settings_path = os.path.join(project_root, settings_name)
        if os.path.isfile(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                # 匹配 include ':xxx', ':yyy:zzz' 等
                includes = re.findall(r"""['\"]:([\w\-:]+)['\"]""", content)
                for inc in includes:
                    mod_dir = inc.replace(':', '/')
                    mod_name_str = ':' + inc
                    modules_to_check.append((mod_dir, mod_name_str))
            except Exception:
                pass
            break

    # 统一格式
    normalized = []
    for m in modules_to_check:
        if isinstance(m, tuple):
            normalized.append(m)
        else:
            normalized.append((m, f':{m}'))
    return normalized


def scan_project_native_modules(project_root: str, module_name: str) -> Dict[str, Dict]:
    """扫描项目自身模块的 .so 文件（仅源码目录，不含 Gradle 合并产物）

    只检查真正属于项目自身的路径:
    1. {module}/src/main/jniLibs/  — 手动放置的 SO
    2. {module}/libs/               — 手动放置的 SO/JAR
    3. 其他子模块的同类路径

    注意：不扫描 merged_native_libs / stripped_native_libs，
    因为它们是 Gradle 合并后的产物，包含所有来源（项目+外部AAR）。

    返回: {so_name: {module: ":module_name", type: "project"}}
    """
    so_map: Dict[str, Dict] = {}
    normalized = _get_project_modules(project_root, module_name)

    for mod_dir, mod_name in normalized:
        mod_path = os.path.join(project_root, mod_dir)
        if not os.path.isdir(mod_path):
            continue

        # 只检查项目自有的 SO 目录（非 Gradle 合并产物）
        so_dirs = [
            os.path.join(mod_path, 'src', 'main', 'jniLibs'),
            os.path.join(mod_path, 'libs'),
        ]

        for so_dir in so_dirs:
            if os.path.isdir(so_dir):
                _collect_so_files(so_dir, mod_name, 'project', so_map)

    return so_map


def scan_merged_native_libs(project_root: str, module_name: str) -> set:
    """扫描 Gradle 合并产物目录，获取 APK 中所有 .so 名称的全量清单

    扫描路径:
    1. {module}/build/intermediates/merged_native_libs/
    2. {module}/build/intermediates/stripped_native_libs/

    返回: set of so_name（仅文件名，如 "libmmkv.so"）
    """
    all_so_names: set = set()
    normalized = _get_project_modules(project_root, module_name)

    for mod_dir, mod_name in normalized:
        mod_path = os.path.join(project_root, mod_dir)
        if not os.path.isdir(mod_path):
            continue

        merge_dirs = [
            os.path.join(mod_path, 'build', 'intermediates', 'merged_native_libs'),
            os.path.join(mod_path, 'build', 'intermediates', 'stripped_native_libs'),
        ]

        for merge_dir in merge_dirs:
            if not os.path.isdir(merge_dir):
                continue
            for root, dirs, files in os.walk(merge_dir):
                for f in files:
                    if f.endswith('.so'):
                        all_so_names.add(f)

    return all_so_names


def analyze_so_sources_from_aars(aar_paths) -> Dict[str, Dict]:
    """AAR 模式：直接从原始 AAR 文件中提取 .so 列表建立映射

    每个 AAR 就是来源本身，直接解压看里面有哪些 .so。
    多 AAR 时可以精确区分哪个 .so 来自哪个 AAR。

    返回: {so_name: {module: "AAR文件名", type: "external"}}
    """
    c = Colors
    if isinstance(aar_paths, str):
        aar_paths = [aar_paths]

    so_map: Dict[str, Dict] = {}
    print(f"\n{c.CYAN}🔍 分析 AAR 中的 .so 来源...{c.NC}")

    for aar_path in aar_paths:
        aar_path = os.path.abspath(aar_path)
        aar_name = Path(aar_path).name
        try:
            with zipfile.ZipFile(aar_path, 'r') as zf:
                for info in zf.infolist():
                    if info.filename.endswith('.so'):
                        so_name = Path(info.filename).name
                        # 从 AAR 内路径提取架构信息
                        # 典型路径: jni/arm64-v8a/libfoo.so
                        parts = info.filename.replace('\\', '/').split('/')
                        arch = "unknown"
                        for i, part in enumerate(parts):
                            if part in ('jni', 'lib') and i + 1 < len(parts):
                                arch = parts[i + 1]
                                break

                        # 用 "so_name" 作为 key（不含架构），因为同一 .so 在不同架构下来源相同
                        if so_name not in so_map:
                            so_map[so_name] = {
                                'module': aar_name,
                                'type': 'external',
                                'path': aar_path,
                            }
            so_count = sum(1 for info in zipfile.ZipFile(aar_path, 'r').infolist() if info.filename.endswith('.so'))
            print(f"  {c.GREEN}📦 {aar_name}: {so_count} 个 .so 文件{c.NC}")
        except Exception as e:
            print(f"  {c.YELLOW}⚠️ 无法读取 {aar_name}: {e}{c.NC}")

    if so_map:
        print(f"  {c.GREEN}✅ 共建立 {len(so_map)} 个 .so 来源映射{c.NC}")
    return so_map


def analyze_so_sources(apk_path: str) -> Tuple[Optional[str], Dict[str, Dict]]:
    """分析 APK 中 .so 文件的来源

    完整流程:
    1. 从 APK 路径反推项目根目录
    2. 扫描项目自身模块的 .so
    3. 运行 gradlew dependencies 获取依赖树
    4. 在 Gradle 缓存中匹配依赖的 .so
    5. 合并映射（项目模块优先）

    返回: (project_root, so_source_map) 或 (None, {})
    """
    c = Colors
    result = detect_project_root(apk_path)
    if not result:
        return None, {}

    project_root, module_name = result
    print(f"\n{c.CYAN}🔍 检测到 Android 项目，开始分析 .so 来源...{c.NC}")
    print(f"  项目根目录: {project_root}")
    print(f"  构建模块: {module_name}")

    so_map: Dict[str, Dict] = {}

    # Step 1: 扫描项目自有 SO 目录（jniLibs/libs，真正的项目自有 SO）
    print(f"  Step 1: 扫描项目模块源码目录...")
    project_so = scan_project_native_modules(project_root, module_name)
    so_map.update(project_so)
    if project_so:
        print(f"  {c.GREEN}  找到 {len(project_so)} 个项目自有 .so{c.NC}")
    else:
        print(f"  {c.YELLOW}  项目源码目录未发现自有 .so{c.NC}")

    # Step 2: 获取依赖树
    print(f"  Step 2: 获取 Gradle 依赖树...")

    # 从 APK 路径推断 variant
    variant = "release"
    apk_normalized = apk_path.replace('\\', '/').lower()
    if '/debug/' in apk_normalized:
        variant = "debug"

    deps = run_gradle_dependencies(project_root, module_name, variant)
    if deps:
        print(f"  {c.GREEN}  解析到 {len(deps)} 个依赖{c.NC}")

        # Step 3: 在 Gradle 缓存中查找依赖的 .so
        print(f"  Step 3: 扫描 Gradle 缓存匹配 .so 来源...")
        cache_so = scan_gradle_cache_for_so(deps)
        # 外部依赖覆盖项目扫描结果（Gradle 缓存更精确）
        so_map.update(cache_so)
        if cache_so:
            print(f"  {c.GREEN}  从缓存中匹配到 {len(cache_so)} 个外部依赖 .so{c.NC}")
    else:
        print(f"  {c.YELLOW}  未能获取依赖树（gradlew 不可用或执行失败）{c.NC}")
        print(f"  {c.YELLOW}  跳过 Gradle 缓存分析{c.NC}")

    # Step 4: 用合并产物目录兜底
    # merged_native_libs 中存在但未被上述匹配到的 SO，需要进一步识别来源
    all_merged_so = scan_merged_native_libs(project_root, module_name)
    unmatched_so = all_merged_so - set(so_map.keys())

    if unmatched_so:
        # Step 4a: 反向查找 transforms 缓存（覆盖本地 AAR 等非 Maven 依赖场景）
        reverse_map = reverse_lookup_so_in_transforms(unmatched_so)
        if reverse_map:
            so_map.update(reverse_map)
            print(f"  {c.GREEN}  反向匹配到 {len(reverse_map)} 个外部依赖 .so{c.NC}")
            unmatched_so -= set(reverse_map.keys())

        # Step 4b: 仍未匹配的标记为项目模块（来自 CMake/ndk-build 编译）
        for so_name in unmatched_so:
            so_map[so_name] = {'module': f':{module_name}', 'type': 'project'}

    total = len(so_map)
    if total > 0:
        print(f"  {c.GREEN}✅ 共建立 {total} 个 .so 来源映射{c.NC}")
    else:
        print(f"  {c.YELLOW}⚠️ 未能建立 .so 来源映射{c.NC}")

    return project_root, so_map


# ============================================================================
# 主检查逻辑
# ============================================================================
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

    # 运行官方 check_elf_alignment.sh
    elf_results, elf_output = run_elf_check(file_path)
    result.elf_results = elf_results
    result.elf_script_output = elf_output

    return result


# ============================================================================
# HTML 报告生成
# ============================================================================
def generate_html_report(result: CheckResult, html_path: str) -> None:
    """生成 HTML 报告"""
    is_aar = bool(result.source_aar_paths)
    file_name = Path(result.file_path).name

    # 整体状态
    zipalign_ok = result.zipalign.status != "fail"
    elf_ok = result.elf_failed == 0
    has_compressed = result.has_compressed_so

    if not zipalign_ok or result.elf_failed > 0:
        overall_color = "#ef4444"
        overall_text = "❌ 存在未对齐问题"
    elif has_compressed:
        overall_color = "#f59e0b"
        overall_text = "⚠️ 有 .so 被压缩存储"
    else:
        overall_color = "#10b981"
        overall_text = "✅ 全部通过"

    # HTML 模板
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APK 16KB 对齐检查报告</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #f0f2f5; color: #1f2937; line-height: 1.6; padding: 20px;
  }}
  .container {{ max-width: 1200px; margin: 0 auto; }}
  .header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white; border-radius: 16px; padding: 32px; margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
  }}
  .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
  .header .subtitle {{ opacity: 0.85; font-size: 14px; }}
  .meta-grid {{
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 12px; margin-top: 20px;
  }}
  .meta-item {{
    background: rgba(255,255,255,0.15); border-radius: 8px; padding: 12px 16px;
    min-width: 0;
  }}
  .meta-item .label {{ font-size: 12px; opacity: 0.75; margin-bottom: 4px; }}
  .meta-item .value {{
    font-size: 15px; font-weight: 600;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .tab-nav {{
    display: flex; gap: 0; margin-bottom: 24px; background: white;
    border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .tab-btn {{
    flex: 1; padding: 14px 20px; border: none; background: white;
    font-size: 14px; font-weight: 600; color: #6b7280; cursor: pointer;
    transition: all 0.2s; border-bottom: 3px solid transparent;
    white-space: nowrap;
  }}
  .tab-btn:hover {{ background: #f9fafb; color: #374151; }}
  .tab-btn.active {{ color: #667eea; border-bottom-color: #667eea; background: #f8f7ff; }}
  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  .mono {{ font-family: "SF Mono", "Fira Code", monospace; font-size: 13px; }}
  /* 压缩存储提示 */
  .compressed-note {{
    background: white; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #8b5cf6;
    overflow: hidden;
  }}
  .compressed-note-header {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 16px 20px; background: #faf5ff;
  }}
  .compressed-note-icon {{ font-size: 24px; flex-shrink: 0; }}
  .compressed-note-header strong {{ font-size: 14px; color: #5b21b6; }}
  .compressed-note-body {{
    padding: 12px 20px 16px; font-size: 13px; color: #374151; line-height: 1.7;
  }}
  .compressed-note-body p {{ margin: 0 0 8px; }}
  .compressed-note-body code {{
    background: #f3f4f6; padding: 1px 5px; border-radius: 3px;
    font-family: monospace; font-size: 12px;
  }}
  .tips {{
    background: white; border-radius: 12px; padding: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px;
  }}
  .tips h2 {{ font-size: 18px; margin-bottom: 12px; }}
  .tips ul {{ padding-left: 20px; }}
  .tips li {{ margin-bottom: 8px; color: #4b5563; font-size: 14px; }}
  .tips code {{
    background: #f3f4f6; padding: 2px 6px; border-radius: 4px;
    font-family: monospace; font-size: 13px; color: #e11d48;
  }}
  .footer {{ text-align: center; color: #9ca3af; font-size: 12px; padding: 16px; }}
  /* 重放命令面板 */
  .replay-panel {{
    background: #1e1e2e; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,.1);
  }}
  .replay-panel > summary {{
    padding: 12px 20px; font-size: 13px; font-weight: 600; color: #a5b4fc;
    display: flex; align-items: center; gap: 6px; cursor: pointer;
    user-select: none; list-style: none;
  }}
  .replay-panel > summary::-webkit-details-marker {{ display: none; }}
  .replay-panel > summary::before {{
    content: '▶'; font-size: 10px; color: #94a3b8;
    transition: transform .2s; flex-shrink: 0;
  }}
  .replay-panel[open] > summary::before {{ transform: rotate(90deg); }}
  .replay-panel .replay-body {{ padding: 0 20px 16px; }}
  .replay-panel .replay-cmd {{
    display: flex; align-items: center; justify-content: space-between;
    background: #2d2d3f; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px; color: #e2e8f0; line-height: 1.5;
  }}
  .replay-panel .replay-cmd:last-child {{ margin-bottom: 0; }}
  .replay-panel .replay-cmd .cmd-label {{
    color: #94a3b8; font-size: 11px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    white-space: nowrap; margin-right: 12px; min-width: 80px;
  }}
  .replay-panel .replay-cmd code {{ flex: 1; word-break: break-all; }}
  .replay-panel .replay-cmd .copy-btn {{
    background: none; border: 1px solid #4a4a6a; border-radius: 4px;
    color: #94a3b8; font-size: 11px; padding: 2px 8px; cursor: pointer;
    white-space: nowrap; margin-left: 10px; transition: all .2s;
  }}
  .replay-panel .replay-cmd .copy-btn:hover {{ border-color: #a5b4fc; color: #a5b4fc; }}
  /* 官方验证结果区块 */
  .official-verify {{
    background: white; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden;
  }}
  .official-verify .verify-header {{
    padding: 16px 24px; border-bottom: 1px solid #e5e7eb;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .official-verify .verify-header h2 {{ font-size: 18px; margin: 0; }}
  .official-verify .verify-status {{
    padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600;
  }}
  .official-verify .verify-status.pass {{ background: #d1fae5; color: #065f46; }}
  .official-verify .verify-status.fail {{ background: #fee2e2; color: #991b1b; }}
  .official-verify .verify-status.unavailable {{ background: #fef3c7; color: #92400e; }}
  .official-verify .verify-stats {{
    display: flex; gap: 16px; padding: 16px 24px; border-bottom: 1px solid #e5e7eb;
  }}
  .official-verify .verify-stat-card {{
    flex: 1; text-align: center; padding: 12px; background: #f8fafc; border-radius: 8px;
  }}
  .official-verify .verify-stat-card.pass {{ background: #ecfdf5; }}
  .official-verify .verify-stat-card.fail {{ background: #fef2f2; }}
  .official-verify .verify-stat-num {{
    display: block; font-size: 28px; font-weight: 700; color: #1e293b;
  }}
  .official-verify .verify-stat-card.pass .verify-stat-num {{ color: #059669; }}
  .official-verify .verify-stat-card.fail .verify-stat-num {{ color: #dc2626; }}
  .official-verify .verify-stat-label {{ font-size: 12px; color: #64748b; }}
  .official-verify .verify-details-open {{
    border-top: 1px solid #e5e7eb;
  }}
  .official-verify .verify-details-open summary.verify-details-title {{
    list-style: none; cursor: pointer; user-select: none;
  }}
  .official-verify .verify-details-open summary.verify-details-title::-webkit-details-marker {{
    display: none;
  }}
  .official-verify .verify-details-open summary.verify-details-title::before {{
    content: '▶'; display: inline-block; margin-right: 8px;
    font-size: 11px; color: #9ca3af; transition: transform 0.2s;
  }}
  .official-verify .verify-details-open[open] summary.verify-details-title::before {{
    transform: rotate(90deg);
  }}
  .official-verify .verify-details-title {{
    padding: 12px 24px; font-size: 14px; color: #6366f1;
    font-weight: 600; background: #f8fafc; border-bottom: 1px solid #e5e7eb;
  }}
  .official-verify .verify-output {{
    background: #1e1e2e; color: #e2e8f0; padding: 16px 20px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px; line-height: 1.6; max-height: 400px; overflow: auto;
    white-space: pre-wrap; word-break: break-all;
  }}
  .official-verify .verify-output .line-pass {{ color: #10b981; }}
  .official-verify .verify-output .line-fail {{ color: #ef4444; }}
  .official-verify .verify-output .line-info {{ color: #94a3b8; }}
  /* 表格样式 */
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #f9fafb; padding: 12px 16px; text-align: left;
    font-size: 12px; text-transform: uppercase; color: #6b7280;
    font-weight: 600; letter-spacing: 0.05em; border-bottom: 1px solid #e5e7eb;
    white-space: nowrap;
  }}
  tbody td {{
    padding: 10px 16px; border-bottom: 1px solid #f3f4f6; font-size: 14px;
  }}
  tbody tr:hover {{ background: #f9fafb; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 9999px;
    font-size: 12px; font-weight: 600;
  }}
  .badge-pass {{ background: #d1fae5; color: #065f46; }}
  .badge-fail {{ background: #fee2e2; color: #991b1b; }}
  .badge-warn {{ background: #fef3c7; color: #92400e; }}
  .badge-exempt {{ background: #dbeafe; color: #1e40af; }}
  .arch-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 500; font-family: monospace;
  }}
  .arch-arm64 {{ background: #dbeafe; color: #1e40af; }}
  .arch-armv7 {{ background: #fce7f3; color: #9d174d; }}
  .arch-x86 {{ background: #e0e7ff; color: #3730a3; }}
  .arch-other {{ background: #f3f4f6; color: #374151; }}
  @media (max-width: 768px) {{
    body {{ padding: 12px; }}
    .header {{ padding: 20px; }}
    .meta-grid {{ grid-template-columns: 1fr; }}
    .tab-nav {{ flex-direction: column; }}
    .tab-btn {{ font-size: 13px; padding: 10px 16px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📦 APK 16KB 对齐检查报告</h1>
    <div class="subtitle">官方 zipalign 验证 + 官方 check_elf_alignment.sh ELF LOAD 段对齐检查</div>
    <div class="meta-grid">
      <div class="meta-item">
        <div class="label">{'AAR 文件' if is_aar else 'APK 文件'}</div>
        <div class="value" title="{html.escape(', '.join(result.source_aar_paths)) if is_aar else html.escape(result.file_path)}">{html.escape(', '.join(Path(p).name for p in result.source_aar_paths)) if is_aar else html.escape(file_name)}</div>
      </div>
      <div class="meta-item">
        <div class="label">检查时间</div>
        <div class="value">{result.check_time}</div>
      </div>
      <div class="meta-item">
        <div class="label">整体状态</div>
        <div class="value" style="color: {overall_color}">{overall_text}</div>
      </div>'''

    # AAR 模式：额外显示构建 APK 路径
    if is_aar:
        html_content += f'''
      <div class="meta-item" style="grid-column: 1 / -1;">
        <div class="label">构建 APK</div>
        <div class="value mono" style="font-size: 13px; word-break: break-all;">{html.escape(result.file_path)}</div>
      </div>'''

    html_content += '''
    </div>
  </div>

'''

    # 重放命令面板（全局，不属于任何 Tab）
    script_path = os.path.abspath(__file__)
    elf_script_path = find_check_elf_script()
    zipalign_cmd = find_tool('zipalign')
    zipalign_replay = html.escape(zipalign_cmd) if zipalign_cmd else "$ANDROID_HOME/build-tools/&lt;VERSION&gt;/zipalign"
    elf_script_replay = html.escape(elf_script_path) if elf_script_path else "check_elf_alignment.sh"

    # AAR 模式：Python 重放命令用原始 AAR 路径
    if is_aar:
        aar_args = ' '.join(f'"{html.escape(p)}"' for p in result.source_aar_paths)
        python_replay_cmd = f'python3 {html.escape(script_path)} {aar_args}'
    else:
        python_replay_cmd = f'python3 {html.escape(script_path)} "{html.escape(result.file_path)}"'

    html_content += f'''
  <details class="replay-panel">
    <summary>🔄 重放命令</summary>
    <div class="replay-body">
      <div class="replay-cmd">
        <span class="cmd-label">{'AAR 检查' if is_aar else 'Python 检查'}</span>
        <code>{python_replay_cmd}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
      <div class="replay-cmd">
        <span class="cmd-label">官方 zipalign</span>
        <code>{zipalign_replay} -c -P 16 -v 4 {html.escape(result.file_path)}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
      <div class="replay-cmd">
        <span class="cmd-label">官方 ELF 检查</span>
        <code>bash {elf_script_replay} {html.escape(result.file_path)}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
    </div>
  </details>

  <div class="tab-nav">
    <button class="tab-btn active" onclick="switchTab('tab-zipalign')">🔍 zipalign 验证</button>
    <button class="tab-btn" onclick="switchTab('tab-elf')">🔬 ELF 对齐检查</button>
<button class="tab-btn" onclick="switchTab('tab-tips')">💡 修复方案&参考资料</button>
  </div>

  <div id="tab-zipalign" class="tab-pane active">
'''

    # 官方 zipalign 验证结果
    verify_status_class = result.zipalign.status
    html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔍 官方 zipalign 验证结果</h2>
      <span class="verify-status {verify_status_class}">{html.escape(result.zipalign.summary)}</span>
    </div>
'''

    if result.zipalign.available:
        html_content += f'''    <div class="verify-stats">
      <div class="verify-stat-card">
        <span class="verify-stat-num">{result.zipalign.total_count}</span>
        <span class="verify-stat-label">检查项总计</span>
      </div>
      <div class="verify-stat-card pass">
        <span class="verify-stat-num">{result.zipalign.ok_count}</span>
        <span class="verify-stat-label">通过</span>
      </div>
      <div class="verify-stat-card fail">
        <span class="verify-stat-num">{result.zipalign.fail_count}</span>
        <span class="verify-stat-label">未通过 (BAD)</span>
      </div>
      <div class="verify-stat-card" style="background: #fffbeb;">
        <span class="verify-stat-num" style="color: #d97706;">{result.zipalign.compressed_count}</span>
        <span class="verify-stat-label">SO 压缩存储</span>
      </div>
    </div>
'''

        # 问题条目表格：BAD（全部）+ compressed（仅 .so 文件）
        issue_entries = [
            e for e in result.zipalign.entries
            if e.status == "fail" or (e.status == "compressed" and e.file_path.endswith('.so'))
        ]

        # 分类 BAD 条目（可修复 vs 需重编译）
        fixable_set, unfixable_set, _ = _classify_zipalign_bad_entries(result)
        fixable_paths = {e.file_path for e in fixable_set}
        unfixable_paths = {e.file_path for e in unfixable_set}

        if issue_entries:
            # 未通过的(fail)排在最上面，再按 SO 文件名排序（相同 SO 的不同架构版本放在一起）
            issue_entries_sorted = sorted(issue_entries, key=lambda x: (0 if x.status == "fail" else 1, Path(x.file_path).name, x.file_path))
            details_open_attr = ' open' if verify_status_class != 'pass' else ''
            html_content += f'''    <details class="verify-details-open"{details_open_attr}>
      <summary class="verify-details-title">⚠️ 未通过 / SO 压缩存储条目</summary>
      <div style="padding: 0;">
        <table>
          <thead>
            <tr>
              <th style="width: 50px;">#</th>
              <th>文件路径</th>
              <th>偏移量</th>
              <th>状态</th>
              <th>修复方式</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
'''
            for idx, entry in enumerate(issue_entries_sorted, 1):
                if entry.status == "fail":
                    badge_class = "badge-fail"
                    badge_text = "❌ BAD"
                    note = html.escape(entry.detail) if entry.detail else "未对齐"
                    # 修复方式
                    if entry.file_path in unfixable_paths:
                        fix_badge = '<span class="badge badge-fail" style="font-size:11px;">需重新编译</span>'
                        # 附加来源信息
                        so_name = Path(entry.file_path).name
                        if so_name in result.so_source_map:
                            info = result.so_source_map[so_name]
                            note += f' ← {html.escape(info.get("module", ""))}'
                    elif entry.file_path in fixable_paths:
                        fix_badge = '<span class="badge badge-pass" style="font-size:11px;">zipalign 可修复</span>'
                    else:
                        fix_badge = '<span class="badge" style="background:#f3f4f6;color:#374151;font-size:11px;">zipalign 可修复</span>'
                else:
                    badge_class = "badge-warn"
                    badge_text = "⚠️ compressed"
                    note = "压缩存储，无法验证对齐"
                    fix_badge = '<span class="badge badge-warn" style="font-size:11px;">需改 stored</span>'

                html_content += f'''            <tr>
              <td>{idx}</td>
              <td class="mono" style="word-break: break-all;">{html.escape(entry.file_path)}</td>
              <td class="mono">{html.escape(entry.offset)}</td>
              <td><span class="badge {badge_class}">{badge_text}</span></td>
              <td>{fix_badge}</td>
              <td style="font-size: 13px; color: #6b7280;">{note}</td>
            </tr>
'''
            html_content += '''          </tbody>
        </table>
      </div>
    </details>
'''

        # 自动修复对比结果
        fix = result.fix_result
        if fix and fix.attempted:
            if fix.verify_result:
                vr = fix.verify_result
                orig_fail = result.zipalign.fail_count
                fixed_fail = vr.zipalign.fail_count
                fixed_count = orig_fail - fixed_fail

                if fix.success:
                    fix_status_class = "pass"
                    fix_status_text = "✅ 修复成功"
                elif fixed_fail == 0:
                    fix_status_class = "pass"
                    fix_status_text = "✅ zipalign 偏移已全部修复"
                elif fixed_count > 0:
                    fix_status_class = "unavailable"
                    fix_status_text = "⚠️ 部分修复"
                else:
                    fix_status_class = "fail"
                    fix_status_text = "❌ 修复失败"

                html_content += f'''
    <div style="border-top: 1px solid #e5e7eb; margin-top: 16px;">
      <div style="padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e5e7eb;">
        <h3 style="margin: 0; font-size: 16px;">🔧 zipalign -P 16 自动修复结果</h3>
        <span class="verify-status {fix_status_class}">{fix_status_text}</span>
      </div>
      <div class="verify-stats">
        <div class="verify-stat-card">
          <span class="verify-stat-num" style="font-size: 14px; color: #64748b;">修复前</span>
          <span class="verify-stat-label" style="font-size: 13px; margin-top: 4px;">
            通过 <strong>{result.zipalign.ok_count}</strong>&nbsp;&nbsp;失败 <strong style="color:#dc2626;">{orig_fail}</strong>
          </span>
        </div>
        <div class="verify-stat-card" style="background: #f0fdf4;">
          <span class="verify-stat-num" style="font-size: 14px; color: #16a34a;">修复后</span>
          <span class="verify-stat-label" style="font-size: 13px; margin-top: 4px;">
            通过 <strong>{vr.zipalign.ok_count}</strong>&nbsp;&nbsp;失败 <strong style="color:{"#dc2626" if fixed_fail > 0 else "#16a34a"};">{fixed_fail}</strong>
          </span>
        </div>
        <div class="verify-stat-card" style="background: #ecfdf5;">
          <span class="verify-stat-num" style="color: #059669;">{fixed_count}</span>
          <span class="verify-stat-label">修复数量</span>
        </div>
      </div>
'''
                # 补充说明
                notes = []
                if fixed_fail == 0 and vr.elf_failed > 0:
                    notes.append(f'zipalign 偏移已全部修复，但仍有 <strong>{vr.elf_failed}</strong> 个 SO 的 ELF LOAD 段未对齐（需重新编译，见 ELF 检查 Tab）')
                if fix.aligned_path:
                    notes.append(f'修复后文件：<code style="font-size:12px;">{html.escape(Path(fix.aligned_path).name)}</code>（未签名，仅用于验证）')

                if notes:
                    html_content += '      <div style="padding: 12px 24px; background: #fffbeb; border-top: 1px solid #fef3c7; font-size: 13px; color: #92400e;">\n'
                    for note_text in notes:
                        html_content += f'        <p style="margin: 4px 0;">⚠️ {note_text}</p>\n'
                    html_content += '      </div>\n'

                html_content += '    </div>\n'
            elif fix.error:
                html_content += f'''
    <div style="border-top: 1px solid #e5e7eb; margin-top: 16px; padding: 16px 24px;">
      <h3 style="margin: 0 0 8px; font-size: 16px;">🔧 zipalign -P 16 自动修复</h3>
      <span class="badge badge-fail">❌ 修复失败</span>
      <p style="margin: 8px 0 0; font-size: 13px; color: #991b1b;">{html.escape(fix.error)}</p>
    </div>
'''

        if result.zipalign.output:
            # 转义并高亮输出
            escaped_output = html.escape(result.zipalign.output)
            escaped_output = escaped_output.replace(
                '(OK)', '<span class="line-pass">(OK)</span>'
            ).replace(
                '(OK - compressed)', '<span class="line-pass">(OK - compressed)</span>'
            )
            escaped_output = re.sub(
                r'\(BAD - (\d+)\)',
                r'<span class="line-fail">(BAD - \1)</span>',
                escaped_output
            )
            escaped_output = escaped_output.replace(
                'Verification successful',
                '<span class="line-pass">Verification successful</span>'
            ).replace(
                'Verification FAILED',
                '<span class="line-fail">Verification FAILED</span>'
            )

            details_open_attr = ' open' if verify_status_class != 'pass' else ''
            html_content += f'''    <details class="verify-details-open"{details_open_attr}>
      <summary class="verify-details-title">📝 详细输出</summary>
      <div class="verify-output">{escaped_output}</div>
    </details>
'''
    else:
        html_content += '''    <div class="verify-output"><span class="line-info">zipalign 工具不可用。请确保：
1. ANDROID_HOME 环境变量已设置
2. Build-Tools 35.0.0+ 已安装
3. $ANDROID_HOME/build-tools/XX.0.0/zipalign 可执行</span></div>
'''

    html_content += '  </div>\n'

    # 压缩存储提示（合并到 zipalign tab 中）
    if result.has_compressed_so:
        compressed_list_html = ", ".join(
            f'<code>{html.escape(name)}</code>' for name in sorted(result.compressed_so_names)
        )
        html_content += f'''
  <div class="compressed-note">
    <div class="compressed-note-header">
      <span class="compressed-note-icon">📦</span>
      <div>
        <strong>关于官方 zipalign 验证通过但仍可能存在问题</strong>
        <p style="margin: 4px 0 0; font-size: 13px; color: #6b7280;">检测到 {len(result.compressed_so_names)} 个 .so 文件以压缩（deflated）方式存储</p>
      </div>
    </div>
    <div class="compressed-note-body">
      <p>官方 <code>zipalign -c</code> 对压缩存储的文件直接判定为 <code>(OK - compressed)</code>，<strong>但这并不意味着 16KB 对齐通过</strong>。</p>
      <p>Android 要求 .so 必须以 <strong>stored（未压缩）</strong> 方式存储，系统才能直接从 APK 中 mmap 加载，这是 16KB 页面对齐的<strong>前提条件</strong>。</p>
      <p style="margin-bottom: 4px;"><strong>受影响的 SO 文件：</strong>{compressed_list_html}</p>
      <div style="margin-top: 8px;">
        <div style="color: #6366f1; font-size: 13px; font-weight: 600; margin-bottom: 8px;">🔧 修复方法</div>
        <div style="background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 6px; padding: 12px;">
          <code style="font-size: 13px; color: #5b21b6;">// build.gradle (Module)<br>
android {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;packagingOptions {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;jniLibs {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;useLegacyPackaging = false<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;}}<br>
&nbsp;&nbsp;&nbsp;&nbsp;}}<br>
}}</code>
        </div>
        <p style="margin: 8px 0 0; color: #6b7280; font-size: 12px;">
          📌 AGP 8.5.1+ 已默认设置此选项，低版本需手动配置。
        </p>
      </div>
    </div>
  </div>
'''

    # ---- tab-zipalign 内的修复建议 ----
    fix = result.fix_result
    # 判断修复后 zipalign 是否全部通过
    fix_zipalign_all_pass = (
        fix and fix.attempted and fix.verify_result
        and fix.verify_result.zipalign.fail_count == 0
    )
    has_zipalign_tips = not zipalign_ok or result.has_compressed_so
    if has_zipalign_tips:
        html_content += '  <div class="tips" style="margin-top: 20px;">\n'
        html_content += '    <h2>💡 解决方案</h2>\n'

        # zipalign 未通过
        if not zipalign_ok:
            if fix_zipalign_all_pass:
                # 自动修复后 zipalign 全部通过 —— 给出确定性方案
                orig_fail = result.zipalign.fail_count
                html_content += f'''
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
        <span style="font-size: 20px;">✅</span>
        <strong style="font-size: 15px; color: #15803d;">zipalign 对齐问题可通过构建配置修复（已验证）</strong>
      </div>
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">
        原始 APK 有 <strong>{orig_fail}</strong> 个文件 ZIP 偏移未按 16KB 对齐。
        我们使用 <code>zipalign -P 16</code> 重新对齐后，<strong>zipalign 验证全部通过</strong>。
        这说明 SO 文件自身的 ELF 段对齐没有问题，只需在构建流程中启用 16KB 对齐即可。
      </p>
    </div>

    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #1e293b;">🔧 在构建流程中启用 16KB 对齐</h3>
    <p style="margin: 0 0 12px; font-size: 13px; color: #6b7280;">选择以下任一方案，重新构建后 zipalign 即可通过：</p>

    <div style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px; font-size: 14px; color: #1e293b;">方案一：升级 AGP ≥ 8.5.1（推荐）</h4>
      <p style="margin: 0 0 8px; font-size: 13px; color: #6b7280;">AGP 8.5.1+ 构建时自动执行 <code>zipalign -P 16</code>，无需额外配置。</p>
      <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle (project) 或 libs.versions.toml
classpath 'com.android.tools.build:gradle:8.5.1'  // 或更高</code></pre>
    </div>

    <div style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px; font-size: 14px; color: #1e293b;">方案二：手动 zipalign（低版本 AGP 或自定义构建）</h4>
      <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># ⚠️ 注意顺序：先 zipalign → 再 apksigner 签名
# 需要 Build-Tools 35.0.0+
zipalign -P 16 -f 4 app-unsigned.apk app-aligned.apk
apksigner sign --ks keystore.jks app-aligned.apk

# 验证
zipalign -c -P 16 -v 4 app-aligned.apk</code></pre>
    </div>

    <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 12px 16px; font-size: 13px; color: #1e40af;">
      <strong>📌 注意：</strong>同时确保 <code>useLegacyPackaging = false</code>（AGP 8.5.1+ 默认开启），让 .so 以 stored 方式存储：
      <pre style="background:rgba(255,255,255,0.6); padding:8px 12px; border-radius:6px; margin:8px 0 0; font-size:13px;"><code>// app/build.gradle
android {{
    packaging {{
        jniLibs {{
            useLegacyPackaging = false
        }}
    }}
}}</code></pre>
    </div>
'''
            else:
                # 自动修复不能完全解决，或没有修复结果 —— 给出通用建议
                html_content += '''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #1e293b;">📦 APK 未通过 zipalign 16KB 对齐验证</h3>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li><strong>确保 AGP &ge; 8.5.1</strong>：Android Gradle Plugin 8.5.1+ 构建时自动执行 16KB zipalign，低版本需手动处理
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle (project)
classpath 'com.android.tools.build:gradle:8.5.1'  // 或更高</code></pre>
      </li>
      <li><strong>设置 <code>useLegacyPackaging = false</code></strong>：让 .so 以未压缩方式存储在 APK 中
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// app/build.gradle
android {
    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
    }
}</code></pre>
      </li>
      <li><strong>手动 zipalign（低版本 AGP 或自定义构建流程）</strong>：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># ⚠️ 注意顺序：先 zipalign → 再 apksigner 签名
# Build-Tools 35.0.0+
zipalign -P 16 -f 4 input.apk output_aligned.apk
apksigner sign --ks keystore.jks output_aligned.apk

# 验证
zipalign -c -P 16 -v 4 output_aligned.apk</code></pre>
      </li>
    </ol>
'''

        # 压缩存储的 SO
        if result.has_compressed_so:
            compressed_names_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in result.compressed_so_names[:5])
            if len(result.compressed_so_names) > 5:
                compressed_names_html += f' 等 {len(result.compressed_so_names)} 个'
            html_content += f'''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #d97706;">⚠️ SO 文件被压缩存储</h3>
    <p style="margin: 4px 0 8px; color: #92400e; font-size: 13px;">
      {compressed_names_html} — 压缩存储的 .so 无法利用 16KB 页面对齐优势。
    </p>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li>在 <code>build.gradle</code> 中设置 <code>useLegacyPackaging = false</code>（见上方）</li>
      <li>确保 <code>AndroidManifest.xml</code> 中 <strong>没有</strong> <code>android:extractNativeLibs="true"</code>（AGP 默认为 false）</li>
    </ol>
'''

        html_content += '  </div>\n'

    # 关闭 tab-zipalign
    html_content += '  </div>\n\n'

    # ==================== Tab 2: ELF LOAD 段对齐检查 ====================
    html_content += '  <div id="tab-elf" class="tab-pane">\n'

    if result.elf_results:
        elf_failed_list = [r for r in result.elf_results if r.status == "fail"]
        elf_passed_list = [r for r in result.elf_results if r.status == "pass"]
        elf_warn_list = [r for r in result.elf_results if r.status == "warn"]

        if elf_failed_list:
            elf_status_class = "fail"
            elf_status_text = f"❌ {len(elf_failed_list)} 个 SO 未对齐"
        elif elf_warn_list:
            elf_status_class = "unavailable"
            elf_status_text = f"⚠️ {len(elf_warn_list)} 个无法检查"
        else:
            elf_status_class = "pass"
            elf_status_text = "✅ 全部通过"

        html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查（官方 check_elf_alignment.sh）</h2>
      <span class="verify-status {elf_status_class}">{elf_status_text}</span>
    </div>
    <div class="verify-stats">
      <div class="verify-stat-card">
        <span class="verify-stat-num">{result.elf_total}</span>
        <span class="verify-stat-label">SO 文件总计 (仅 64 位架构)</span>
      </div>
      <div class="verify-stat-card pass">
        <span class="verify-stat-num">{result.elf_passed}</span>
        <span class="verify-stat-label">ALIGNED (≥ 16KB)</span>
      </div>
      <div class="verify-stat-card fail">
        <span class="verify-stat-num">{result.elf_failed}</span>
        <span class="verify-stat-label">UNALIGNED</span>
      </div>
      {f'''<div class="verify-stat-card" style="background-color: #f0f9ff;">
        <span class="verify-stat-num" style="color: #0284c7;">{result.elf_exempt()}</span>
        <span class="verify-stat-label">豁免检查 (32 位架构)</span>
      </div>''' if result.elf_exempt() > 0 else ''}
    </div>
'''
        # ELF 详细表格
        has_source_info = any(r.source_module for r in result.elf_results)
        source_col_header = '<th>来源模块</th>' if has_source_info else ''
        elf_details_open_attr = ' open' if result.elf_failed > 0 else ''
        html_content += f'''    <details class="verify-details-open"{elf_details_open_attr}>
      <summary class="verify-details-title">📝 各 SO 文件 ELF 对齐详情</summary>
      <div style="padding: 0;">
        <table>
          <thead>
            <tr>
              <th style="width: 50px;">#</th>
              <th>SO 文件名</th>
              <th>架构</th>
              <th>对齐值</th>
              <th>状态</th>
              {source_col_header}
            </tr>
          </thead>
          <tbody>
'''
        # 未通过的排在最上面，再按名称排序
        sorted_elf_results = sorted(result.elf_results, key=lambda x: (0 if x.status == "fail" else (1 if x.status == "warn" else 2), x.name))
        for i, elf_r in enumerate(sorted_elf_results, 1):
            if elf_r.arch == "arm64-v8a":
                arch_class = "arch-arm64"
            elif elf_r.arch == "armeabi-v7a":
                arch_class = "arch-armv7"
            elif elf_r.arch.startswith("x86"):
                arch_class = "arch-x86"
            else:
                arch_class = "arch-other"

            if elf_r.status == "pass":
                badge_class = "badge-pass"
                badge_text = "✅ ALIGNED"
            elif elf_r.status == "fail":
                badge_class = "badge-fail"
                badge_text = "❌ UNALIGNED"
            elif elf_r.status == "exempt":
                badge_class = "badge-exempt"
                badge_text = "ℹ️ 豁免 (32位)"
            else:
                badge_class = "badge-warn"
                badge_text = f"⚠️ {html.escape(elf_r.error)}" if elf_r.error else "⚠️ 未知"

            # 来源模块列
            source_col = ''
            if has_source_info:
                if elf_r.source_module:
                    if elf_r.source_type == 'project':
                        source_tag = f'<span class="badge" style="background:#dbeafe;color:#1e40af;">项目</span> {html.escape(elf_r.source_module)}'
                    elif elf_r.source_type == 'external':
                        source_tag = f'<span class="badge" style="background:#fce7f3;color:#9d174d;">外部</span> <span class="mono" style="font-size:12px;">{html.escape(elf_r.source_module)}</span>'
                    else:
                        source_tag = html.escape(elf_r.source_module)
                else:
                    source_tag = '<span style="color:#9ca3af;">未知</span>'
                source_col = f'<td>{source_tag}</td>'

            html_content += f'''            <tr>
              <td>{i}</td>
              <td class="mono">{html.escape(elf_r.name)}</td>
              <td><span class="arch-tag {arch_class}">{html.escape(elf_r.arch)}</span></td>
              <td class="mono">{html.escape(elf_r.align_value)}</td>
              <td><span class="badge {badge_class}">{badge_text}</span></td>
              {source_col}
            </tr>
'''
        html_content += '''          </tbody>
        </table>
      </div>
    </details>
'''
        # ELF 修复提示
        if elf_failed_list:
            html_content += '''    <div style="padding: 12px 24px; background: #fef2f2; border-top: 1px solid #fecaca; font-size: 13px; color: #991b1b;">
      💡 <strong>ELF 对齐问题需重新编译</strong>：升级 NDK r28+ 或添加链接参数 <code style="background:#fee2e2;padding:1px 4px;border-radius:3px;">-Wl,-z,max-page-size=16384</code>。第三方 SDK 需联系供应商更新。
    </div>
'''

        # 官方脚本原始输出
        if result.elf_script_output:
            escaped_elf_output = html.escape(result.elf_script_output)
            escaped_elf_output = escaped_elf_output.replace(
                'ALIGNED', '<span class="line-pass">ALIGNED</span>'
            ).replace(
                'UNALIGNED', '<span class="line-fail">UNALIGNED</span>'
            ).replace(
                'ELF Verification Successful',
                '<span class="line-pass">ELF Verification Successful</span>'
            )
            elf_script_open_attr = ' open' if result.elf_failed > 0 else ''
            html_content += f'''    <details class="verify-details-open"{elf_script_open_attr}>
      <summary class="verify-details-title">📝 check_elf_alignment.sh 原始输出</summary>
      <div class="verify-output">{escaped_elf_output}</div>
    </details>
'''

        html_content += '  </div>\n'
    elif not find_check_elf_script():
        html_content += '''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查</h2>
      <span class="verify-status unavailable">⚠️ check_elf_alignment.sh 不可用</span>
    </div>
    <div class="verify-output"><span class="line-info">官方 check_elf_alignment.sh 脚本不可用。请确保：
1. 脚本文件存在于 scripts/ 目录下
2. 脚本具有执行权限 (chmod +x)
3. 系统已安装 objdump 或 llvm-objdump</span></div>
  </div>
'''
    else:
        html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查</h2>
      <span class="verify-status unavailable">⚠️ 未找到 .so 文件</span>
    </div>
    <div class="verify-output"><span class="line-info">APK 中未找到 .so 文件，无需检查 ELF 对齐。</span></div>
  </div>
'''

    # ---- tab-elf 内的修复建议 ----
    if result.elf_failed > 0:
        elf_failed_list_tips = [r for r in result.elf_results if r.status == "fail"]
        # 按 SO 名称去重，列出未对齐的 SO
        failed_so_names = sorted(set(r.name for r in elf_failed_list_tips))
        failed_so_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in failed_so_names)

        # 按来源类型分组
        project_failed = [r for r in elf_failed_list_tips if r.source_type == "project"]
        external_failed = [r for r in elf_failed_list_tips if r.source_type == "external"]
        unknown_failed = [r for r in elf_failed_list_tips if not r.source_type]

        html_content += '  <div class="tips" style="margin-top: 20px;">\n'
        html_content += '    <h2>💡 修复建议</h2>\n'
        html_content += f'''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #dc2626;">🔧 ELF LOAD 段未对齐（需重新编译 .so）</h3>
    <p style="margin: 4px 0 8px; color: #991b1b; font-size: 13px;">
      以下 SO 的 ELF LOAD segment 对齐值 &lt; 16KB，<strong>无法通过 zipalign 修复</strong>，必须重新编译：{failed_so_html}
    </p>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li><strong>区分 SO 来源</strong>：
'''
        # 如果有来源分析结果，展示具体分类
        if project_failed or external_failed:
            html_content += '        <div style="margin: 8px 0; padding: 12px; background: #f8fafc; border-radius: 8px; font-size: 13px;">\n'
            if project_failed:
                project_names = sorted(set(f'{r.name} ← {r.source_module}' for r in project_failed))
                html_content += '          <div style="margin-bottom: 8px;"><span class="badge" style="background:#dbeafe;color:#1e40af;">项目模块</span> 修改 CMake / ndk-build 参数后重新编译：</div>\n'
                html_content += '          <ul style="margin: 4px 0 8px; padding-left: 20px;">\n'
                for item in project_names:
                    html_content += f'            <li><code>{html.escape(item)}</code></li>\n'
                html_content += '          </ul>\n'
            if external_failed:
                # 按模块分组
                ext_by_module: Dict[str, List[str]] = {}
                for r in external_failed:
                    module = r.source_module or '未知'
                    ext_by_module.setdefault(module, []).append(r.name)
                html_content += '          <div style="margin-bottom: 8px;"><span class="badge" style="background:#fce7f3;color:#9d174d;">外部依赖</span> 联系供应商获取 16KB 对齐版本：</div>\n'
                html_content += '          <ul style="margin: 4px 0 8px; padding-left: 20px;">\n'
                for module, so_names_list in sorted(ext_by_module.items()):
                    names_str = ', '.join(f'<code>{html.escape(n)}</code>' for n in sorted(set(so_names_list)))
                    html_content += f'            <li><strong>{html.escape(module)}</strong> → {names_str}</li>\n'
                html_content += '          </ul>\n'
            if unknown_failed:
                unknown_names = sorted(set(r.name for r in unknown_failed))
                unknown_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in unknown_names)
                html_content += f'          <div><span class="badge" style="background:#f3f4f6;color:#374151;">来源未知</span> 需手动确认：{unknown_html}</div>\n'
            html_content += '        </div>\n'
        else:
            # 没有来源分析结果，显示通用建议
            html_content += '''        <ul style="margin: 4px 0; padding-left: 20px;">
          <li><strong>自己编译的 SO</strong> → 修改 CMake / ndk-build 参数后重新编译（见下方步骤 2-3）</li>
          <li><strong>第三方 SDK 预编译的 SO</strong> → 联系 SDK 供应商获取 16KB 对齐版本，或在其 GitHub 仓库提 Issue</li>
        </ul>
'''
        html_content += '''      </li>
      <li><strong>CMake 项目</strong> — 在 <code>CMakeLists.txt</code> 中添加链接参数：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># CMakeLists.txt
target_link_options(${TARGET} PRIVATE "-Wl,-z,max-page-size=16384")</code></pre>
        或在 <code>build.gradle</code> 中通过 <code>externalNativeBuild</code> 传递：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// app/build.gradle
android {
    defaultConfig {
        externalNativeBuild {
            cmake {
                // 方式 1：通过 cFlags/cppFlags + ldFlags
                arguments "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"
                // 方式 2：直接传 ldFlags
                cppFlags "-fPIC"
            }
        }
    }
}</code></pre>
      </li>
      <li><strong>ndk-build 项目</strong> — 在 <code>Android.mk</code> 或 <code>Application.mk</code> 中添加：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># Android.mk
LOCAL_LDFLAGS += -Wl,-z,max-page-size=16384

# 或者在 Application.mk
APP_LDFLAGS += -Wl,-z,max-page-size=16384</code></pre>
      </li>
      <li><strong>推荐升级 NDK r28+</strong>：NDK r28 及以上版本默认使用 16KB 页面对齐编译，无需手动添加参数
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle — 指定 NDK 版本
android {
    ndkVersion "28.0.12674087"  // 或更高
}</code></pre>
      </li>
      <li><strong>验证 SO 文件对齐</strong>：编译完成后，可用以下命令单独检查 .so 文件：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># 检查 ELF LOAD 段对齐值（应为 2**14 = 16384）
llvm-objdump -p libXxx.so | grep -A1 LOAD
# 或
readelf -l libXxx.so | grep -A1 LOAD</code></pre>
      </li>
    </ol>
'''
        html_content += '  </div>\n'

    # 关闭 tab-elf
    html_content += '  </div>\n\n'

# ==================== Tab 3: 修复方案&参考资料 ====================
    html_content += '  <div id="tab-tips" class="tab-pane">\n'
    html_content += '  <div class="tips">\n'

    # 全部通过时的祝贺信息
    if zipalign_ok and result.elf_failed == 0 and not result.has_compressed_so:
        html_content += '''
    <p style="color: #16a34a; font-size: 14px;">🎉 当前 APK 已通过所有 16KB 对齐检查，无需额外修复。以下为通用参考信息。</p>
'''

    # ---- 修复方案总览 ----
    has_any_issue = not zipalign_ok or result.elf_failed > 0 or result.has_compressed_so
    if has_any_issue:
        html_content += '    <h2 style="margin-bottom: 16px;">🔧 修复方案总览</h2>\n'
        html_content += '    <p style="margin: 0 0 16px; font-size: 13px; color: #6b7280;">以下汇总了当前 APK 所有 16KB 对齐问题的修复方案，详细检查结果请查看前两个 Tab。</p>\n'

        # 方案 1: zipalign 修复（ZIP 偏移对齐）
        if not zipalign_ok:
            fix_ref = result.fix_result
            fix_all_pass = (
                fix_ref and fix_ref.attempted and fix_ref.verify_result
                and fix_ref.verify_result.zipalign.fail_count == 0
            )
            html_content += '''
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #15803d;">📦 方案一：修复 ZIP 偏移对齐（zipalign）</h3>
'''
            if fix_all_pass:
                html_content += f'''
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">
        ✅ <strong>已验证可修复</strong> — 使用 <code>zipalign -P 16</code> 重新对齐后 zipalign 验证全部通过。
      </p>
'''
            html_content += '''
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">选择以下任一方式：</p>
      <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom: 8px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold; width: 160px;">升级 AGP ≥ 8.5.1<br><span style="font-weight:normal;color:#6b7280;">（推荐）</span></td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">AGP 8.5.1+ 构建时自动执行 <code>zipalign -P 16</code>，无需额外配置</td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold;">手动 zipalign</td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">
            <code style="font-size:12px;">zipalign -P 16 -f 4 input.apk output.apk</code><br>
            <span style="color:#6b7280;">⚠️ 顺序：先 zipalign → 再 apksigner 签名（Build-Tools 35.0.0+）</span>
          </td>
        </tr>
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold;">useLegacyPackaging</td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">确保 <code>packaging.jniLibs.useLegacyPackaging = false</code>（AGP 8.5.1+ 默认开启）</td>
        </tr>
      </table>
    </div>
'''

        # 方案 2: ELF 修复（重新编译 SO）
        if result.elf_failed > 0:
            elf_failed_list_ref = [r for r in result.elf_results if r.status == "fail"]
            project_failed_ref = [r for r in elf_failed_list_ref if r.source_type == "project"]
            external_failed_ref = [r for r in elf_failed_list_ref if r.source_type == "external"]

            html_content += '''
    <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #dc2626;">🔬 方案二：修复 ELF LOAD 段对齐（需重新编译）</h3>
      <p style="margin: 0 0 8px; font-size: 13px; color: #991b1b;">
        ⚠️ <strong>zipalign 无法修复此问题</strong> — 需要从源码重新编译 SO 文件。
      </p>
      <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom: 8px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold; width: 160px;">升级 NDK r28+<br><span style="font-weight:normal;color:#6b7280;">（推荐）</span></td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;">NDK r28+ 默认以 16KB 页面对齐编译，无需手动参数<br><code style="font-size:12px;">android { ndkVersion "28.0.12674087" }</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">CMake 项目</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">target_link_options(${TARGET} PRIVATE "-Wl,-z,max-page-size=16384")</code></td>
        </tr>
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">ndk-build 项目</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">LOCAL_LDFLAGS += -Wl,-z,max-page-size=16384</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">验证命令</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">llvm-objdump -p lib.so | grep -A1 LOAD</code>（应为 2**14 = 16384）</td>
        </tr>
      </table>
'''
            # 外部依赖提示
            if external_failed_ref:
                ext_modules: Dict[str, List[str]] = {}
                for r in external_failed_ref:
                    module = r.source_module or '未知'
                    ext_modules.setdefault(module, []).append(r.name)
                html_content += '      <div style="background:rgba(255,255,255,0.6); border-radius:6px; padding:10px 14px; margin-top:8px; font-size:13px;">\n'
                html_content += '        <strong style="color:#9d174d;">📦 外部依赖需联系供应商升级：</strong>\n'
                html_content += '        <ul style="margin:4px 0 0; padding-left:20px;">\n'
                for module, so_list in sorted(ext_modules.items()):
                    names_str = ', '.join(f'<code>{html.escape(n)}</code>' for n in sorted(set(so_list)))
                    html_content += f'          <li><strong>{html.escape(module)}</strong> → {names_str}</li>\n'
                html_content += '        </ul>\n'
                html_content += '      </div>\n'
            if project_failed_ref:
                proj_names = sorted(set(r.name for r in project_failed_ref))
                proj_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in proj_names)
                html_content += f'      <div style="background:rgba(255,255,255,0.6); border-radius:6px; padding:10px 14px; margin-top:8px; font-size:13px;">\n'
                html_content += f'        <strong style="color:#1e40af;">📦 项目模块需重新编译：</strong> {proj_html}\n'
                html_content += '      </div>\n'
            html_content += '    </div>\n'

        # 方案 3: 压缩存储 SO
        if result.has_compressed_so:
            html_content += '''
    <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #d97706;">📦 修复压缩存储的 SO 文件</h3>
      <p style="margin: 0 0 8px; font-size: 13px; color: #92400e;">
        压缩存储的 .so 无法被系统 mmap，也无法利用 16KB 页面对齐优势。
      </p>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fde68a; font-weight: bold; width: 160px;">build.gradle</td>
          <td style="padding: 8px 12px; border: 1px solid #fde68a;"><code>android.packaging.jniLibs.useLegacyPackaging = false</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fde68a; font-weight: bold;">AndroidManifest</td>
          <td style="padding: 8px 12px; border: 1px solid #fde68a;">确保 <strong>没有</strong> <code>android:extractNativeLibs="true"</code></td>
        </tr>
      </table>
    </div>
'''

    # ---- 通用参考资料（始终显示）----
    html_content += '''
<h2 style="margin: 24px 0 12px;">📚 修复方案&参考资料</h2>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">🔗 官方文档</h3>
      <ul style="line-height: 2; margin: 0; padding-left: 24px;">
        <li><a href="https://developer.android.com/guide/practices/page-sizes?hl=zh-cn" style="color: #667eea;" target="_blank">Google 官方：支持 16KB 的页面大小</a>（<strong>2025 年 11 月 1 日起强制执行</strong>）</li>
        <li><a href="https://developer.android.com/build/releases/gradle-plugin?hl=zh-cn" style="color: #667eea;" target="_blank">Android Gradle Plugin 版本说明</a></li>
        <li><a href="https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh" style="color: #667eea;" target="_blank">AOSP 官方 check_elf_alignment.sh 脚本</a></li>
      </ul>
    </div>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">🛠️ 工具版本要求</h3>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background: #f1f5f9;">
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">工具</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">最低版本</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">Android Gradle Plugin</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>8.5.1+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">构建时自动执行 <code>zipalign -P 16</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">NDK</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>r28+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">默认以 16KB 页面对齐编译 .so</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">Build-Tools</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>35.0.0+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign <code>-P</code> 参数支持</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">📋 常用命令</h3>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background: #f1f5f9;">
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">用途</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">命令</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign 对齐</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">zipalign -P 16 -f 4 input.apk output.apk</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign 验证</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">zipalign -c -P 16 -v 4 app.apk</code></td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">APK 签名</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">apksigner sign --ks keystore.jks output.apk</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">ELF 对齐检查</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">llvm-objdump -p lib.so | grep -A1 LOAD</code></td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">readelf 检查</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">readelf -l lib.so | grep -A1 LOAD</code></td>
          </tr>
        </tbody>
      </table>
    </div>
'''

    html_content += '  </div>\n'
    html_content += '  </div>\n\n'

    html_content += '''
  <div class="footer">
    Generated by check_alignment.py · 16KB Page Alignment Checker<br>
    ELF check powered by <a href="https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh" style="color: #667eea;">AOSP check_elf_alignment.sh</a>
  </div>
</div>

<script>
function switchTab(tabId) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => {
    if (b.getAttribute('onclick').includes(tabId)) b.classList.add('active');
  });
}

function copyCmd(btn) {
  const code = btn.parentElement.querySelector('code').textContent;
  navigator.clipboard.writeText(code).then(() => {
    const original = btn.textContent;
    btn.textContent = '已复制';
    btn.style.borderColor = '#10b981';
    btn.style.color = '#10b981';
    setTimeout(() => {
      btn.textContent = original;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 1500);
  });
}
</script>
</body>
</html>
'''

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)


# ============================================================================
# 终端输出
# ============================================================================
def _classify_zipalign_bad_entries(result: CheckResult) -> Tuple[List[ZipalignEntry], List[ZipalignEntry], List[ZipalignEntry]]:
    """将 zipalign BAD 条目分为三类：可修复 / 需重编译 / 非 SO 文件

    分类依据：
    - BAD 条目对应的 .so 文件如果 ELF LOAD 段也未对齐 → 需重编译（zipalign 修不了）
    - BAD 条目对应的 .so 文件如果 ELF LOAD 段已对齐   → zipalign 可修复
    - BAD 条目不是 .so 文件 → zipalign 可修复（非 SO 资源文件）

    返回: (fixable_entries, unfixable_entries, non_so_entries)
    """
    # 构建 ELF 不合规的 SO 名称集合（按 full_path 中的 lib/{arch}/{name} 匹配）
    elf_failed_paths = set()
    for elf_r in result.elf_results:
        if elf_r.status == "fail":
            # 构建 zipalign 输出中的路径格式: lib/{arch}/{name}
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


def print_result(result: CheckResult) -> None:
    """在终端输出检查结果

    当存在自动修复结果时（result.fix_result），展示修复前后的对比：
    - zipalign BAD 条目区分「zipalign 可修复」和「需重新编译」
    - 修复后展示验证结果对比
    """
    c = Colors

    print("=" * 44)
    print(" APK 16KB 对齐检查工具")
    print("=" * 44)
    print()
    print(f"APK 文件: {result.file_path}")
    print(f"APK 大小: {result.file_size}")
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
        fixable, unfixable, non_so = _classify_zipalign_bad_entries(result)

        if fixable or unfixable:
            print()
            if fixable:
                print(f" {c.YELLOW}📦 zipalign 可修复（ZIP 偏移未对齐，ELF 段正常）: {len(fixable)} 个{c.NC}")
                # 按文件路径名称排序
                fixable_sorted = sorted(fixable, key=lambda x: x.file_path)
                for entry in fixable_sorted:
                    print(f"   {c.YELLOW}• {entry.file_path} ({entry.detail}){c.NC}")
            if unfixable:
                print(f" {c.RED}🔧 需重新编译（ELF LOAD 段未 16KB 对齐，zipalign 无法修复）: {len(unfixable)} 个{c.NC}")
                # 按文件路径名称排序
                unfixable_sorted = sorted(unfixable, key=lambda x: x.file_path)
                for entry in unfixable_sorted:
                    # 附加来源信息
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
            # 对比修复前后
            orig_fail = result.zipalign.fail_count
            fixed_fail = vr.zipalign.fail_count
            fixed_count = orig_fail - fixed_fail
            if fixed_fail == 0:
                # zipalign 层面全部修复，但 ELF 段仍有问题
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

        # 列出 ELF 未对齐的 SO 文件
        elf_failed_list = [r for r in result.elf_results if r.status == "fail"]
        if elf_failed_list:
            print(f"{c.RED}❌ ELF 段未对齐（需重新编译，zipalign 无法修复）:{c.NC}")
            # 按名称排序，未通过的文件显示在最上面
            elf_failed_list_sorted = sorted(elf_failed_list, key=lambda x: x.name)
            for r in elf_failed_list_sorted:
                source_info = ""
                if r.source_module:
                    source_label = "项目" if r.source_type == "project" else "外部"
                    source_info = f" ← [{source_label}] {r.source_module}"
                print(f"  {c.RED}• {r.name} ({r.arch}) - 对齐值: {r.align_value}{source_info}{c.NC}")
            print()
            print(f"{c.YELLOW}修复方案: 升级 NDK r28+ 或添加 -Wl,-z,max-page-size=16384{c.NC}")
            # 按来源类型分类提示
            project_failed = [r for r in elf_failed_list if r.source_type == "project"]
            external_failed = [r for r in elf_failed_list if r.source_type == "external"]
            unknown_failed = [r for r in elf_failed_list if not r.source_type]
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
        print(f" {c.YELLOW}APK 中未找到 .so 文件{c.NC}")
        print()


def open_html_report(html_path: str) -> None:
    """自动用浏览器打开 HTML 报告"""
    system = platform.system()

    try:
        if system == "Darwin":  # macOS
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
                    ok, apk_path, error = build_aar_to_apk(file_path)
                    if ok:
                        result = check_apk(apk_path)
                        results.append(result)
                    else:
                        print(f"  AAR 构建失败: {error}")
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


# ============================================================================
# 主入口
# ============================================================================
def main():
    if len(sys.argv) < 2:
        print("用法:")
        print(f"  {sys.argv[0]} <APK文件路径> [HTML输出路径]")
        print(f"  {sys.argv[0]} <AAR文件路径...> [HTML输出路径]")
        print(f"  {sys.argv[0]} --batch <目录路径>")
        print()
        print("示例:")
        print(f"  {sys.argv[0]} app-release.apk")
        print(f"  {sys.argv[0]} my-library.aar")
        print(f"  {sys.argv[0]} lib1.aar lib2.aar  # 多 AAR 合并检查")
        print(f"  {sys.argv[0]} --batch ./apks/")
        print()
        print("选项:")
        print("  --clean    AAR 模式下，先清空 libs 目录中的历史 AAR 文件")
        print()
        print("说明:")
        print("  APK: 直接检查 16KB 对齐（zipalign + ELF），失败时自动尝试 zipalign 修复")
        print("  AAR: 自动 clone AAFFor16KB 项目编译为 APK 再检查（首次需联网）")
        print("       支持多个 AAR 文件合并到一个 APK 中一起检查")
        print("       zipalign 验证失败时同样自动尝试修复")
        print()
        print("检查项:")
        print("  1. 官方 zipalign -c -P 16 -v 4 验证 APK 整体对齐")
        print("  2. 官方 check_elf_alignment.sh 检查 .so 的 ELF LOAD 段对齐")
        sys.exit(1)

    # 批量模式
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

        # 生成每个文件的 HTML 报告
        for r in results:
            html_path = r.file_path.rsplit('.', 1)[0] + '_alignment_report.html'
            generate_html_report(r, html_path)

        failed_count = sum(1 for r in results if r.zipalign.status == "fail" or r.elf_failed > 0)
        sys.exit(1 if failed_count > 0 else 0)

    # 解析参数：支持多 AAR、--clean 选项
    clean = False
    file_args = []
    for arg in sys.argv[1:]:
        if arg == "--clean":
            clean = True
        else:
            file_args.append(arg)

    if not file_args:
        print("错误: 请指定至少一个文件")
        sys.exit(1)

    # 分离文件路径和可能的 HTML 输出路径
    aar_paths = []
    other_args = []
    for arg in file_args:
        if os.path.isfile(arg) and Path(arg).suffix.lower() == '.aar':
            aar_paths.append(arg)
        else:
            other_args.append(arg)

    # 多 AAR 模式
    if len(aar_paths) > 1:
        is_aar = True
        html_output = None
        for arg in other_args:
            if arg.endswith('.html'):
                html_output = arg

        ok, apk_path, error = build_aar_to_apk(aar_paths, clean=clean)
        if not ok:
            c = Colors
            print(f"\n{c.RED}❌ 无法检查 AAR: {error}{c.NC}")
            print(f"{c.YELLOW}提示: 可以手动将 AAR 集成到项目中，构建 APK 后再检查{c.NC}")
            sys.exit(1)
        file_path = apk_path
        print()
    elif len(aar_paths) == 1:
        # 单 AAR 模式
        is_aar = True
        html_output = other_args[0] if other_args else None

        ok, apk_path, error = build_aar_to_apk(aar_paths[0], clean=clean)
        if not ok:
            c = Colors
            print(f"\n{c.RED}❌ 无法检查 AAR: {error}{c.NC}")
            print(f"{c.YELLOW}提示: 可以手动将 AAR 集成到项目中，构建 APK 后再检查{c.NC}")
            sys.exit(1)
        file_path = apk_path
        print()
    else:
        # APK 模式（单文件）
        is_aar = False
        file_path = file_args[0]
        html_output = file_args[1] if len(file_args) > 1 else None

        if not os.path.isfile(file_path):
            print(f"错误: 文件不存在: {file_path}")
            sys.exit(1)

        ext = Path(file_path).suffix.lower()
        if ext != '.apk':
            print(f"错误: 不支持的文件格式: {ext}")
            print("支持的格式: .apk, .aar")
            sys.exit(1)

    # HTML 输出路径
    if html_output:
        html_path = html_output
    else:
        html_path = file_path.rsplit('.', 1)[0] + '_alignment_report.html'

    # 执行检查
    result = check_apk(file_path)

    # AAR 模式时记录原始 AAR 路径
    if is_aar:
        result.source_aar_paths = [os.path.abspath(p) for p in aar_paths]

    # SO 来源分析
    if is_aar:
        # AAR 模式：直接从原始 AAR 中提取 .so 列表建立映射
        so_source_map = analyze_so_sources_from_aars(aar_paths)
        if so_source_map:
            result.so_source_map = so_source_map
            for elf_r in result.elf_results:
                if elf_r.name in so_source_map:
                    info = so_source_map[elf_r.name]
                    elf_r.source_module = info.get('module', '')
                    elf_r.source_type = info.get('type', '')
    else:
        # APK 模式：尝试从项目构建产物路径反推
        project_root, so_source_map = analyze_so_sources(file_path)
        if project_root:
            result.project_root = project_root
            result.so_source_map = so_source_map
            for elf_r in result.elf_results:
                if elf_r.name in so_source_map:
                    info = so_source_map[elf_r.name]
                    elf_r.source_module = info.get('module', '')
                    elf_r.source_type = info.get('type', '')

    # 判断是否有失败
    c = Colors
    zipalign_failed = result.zipalign.status == "fail"
    has_compressed = result.has_compressed_so
    elf_failed = result.elf_failed > 0

    # zipalign 失败时先执行自动修复（在 print_result 之前，以便对比展示）
    if zipalign_failed:
        fix_result = try_fix_apk(file_path)
        result.fix_result = fix_result

    # 终端输出（包含修复前后对比）
    print_result(result)

    # 生成 HTML 报告
    generate_html_report(result, html_path)

    print(f"{c.CYAN}📄 HTML 报告已生成: {html_path}{c.NC}")

    # 自动打开 HTML 报告
    open_html_report(html_path)

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

    # 最终结论
    if zipalign_failed or has_compressed or elf_failed:
        if elf_failed:
            print(f"\n{c.YELLOW}⚠️  注意：ELF LOAD 段对齐问题无法通过 zipalign 修复，需重新编译 SO 文件{c.NC}")
        sys.exit(1)
    else:
        print()
        if is_aar:
            print(f"{c.GREEN}🎉 AAR 中所有 SO 库均已通过 16KB 对齐检查！{c.NC}")
        else:
            print(f"{c.GREEN}🎉 所有 SO 库均已通过 16KB 对齐检查（zipalign + ELF LOAD 段）！{c.NC}")
        sys.exit(0)


if __name__ == "__main__":
    main()
