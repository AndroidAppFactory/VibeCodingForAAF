#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
models.py
数据模型定义：所有 dataclass 和常量
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional


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
    ndk_version: str = ""    # NDK 版本信息


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


@dataclass
class FixResult:
    """自动修复结果"""
    attempted: bool = False        # 是否尝试了修复
    success: bool = False          # 修复是否成功
    aligned_path: str = ""         # 对齐后的 APK 路径
    verify_result: Optional[CheckResult] = None  # 修复后的验证结果
    error: str = ""                # 错误信息
    steps: List[str] = field(default_factory=list)  # 执行步骤日志
