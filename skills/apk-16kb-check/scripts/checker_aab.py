#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
checker_aab.py
AAB 检查器：自动完成 AAB 的完整 16KB 对齐检测

与 APK 模式的关键区别：AAB 是发布产物，Google Play 用 bundletool 从 AAB 生成分发 APK
时才会真正落地 ZIP 层 16KB 对齐。本地 assembleRelease APK 通过 ≠ AAB 通过。

因此 AAB 检测必须（以前是 AI 手动执行，现在脚本自动前置判断）：

1. dump config 前置判断：解析 uncompressNativeLibraries.enabled + ZIP 对齐标记（PAGE_ALIGNMENT_16K/4K）
   （AGP < 8.5.1 未写入 PAGE_ALIGNMENT_16K，bundletool 默认按 4K 对齐 → 直接判读根因）
2. bundletool build-apks --mode=universal 转出 universal APK
3. 对 universal APK 做完整 zipalign + ELF 检查（复用 check_apk）

若 bundletool 不可用，则降级为「解压 AAB 提取 .so 仅做 ELF 检查」并提示。
"""

import os
import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from models import CheckResult, Colors, ZipalignResult
from checker_common import find_bundletool, _run_java_jar, run_elf_check
from checker_apk import check_apk


def _aab_tmp_dir() -> str:
    """AAB 检查临时目录（遵循 ZIXIEKIT_TMP 规范，禁止 /tmp）"""
    zixie_tmp = os.environ.get('ZIXIEKIT_TMP', os.path.join(str(Path.home()), '.zixiekit'))
    base = os.path.join(zixie_tmp, 'skill', 'apk-16kb-check')
    os.makedirs(base, exist_ok=True)
    return tempfile.mkdtemp(prefix='aab_16kb_check_', dir=base)


def _format_size(size_bytes: int) -> str:
    """格式化文件大小"""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def dump_bundle_config(bundletool_path: str, aab_path: str):
    """运行 bundletool dump config，解析关键字段

    返回: (bundletool_version, uncompress_native_libraries, page_alignment, raw_output)
      - page_alignment: "16K" / "4K" / ""（无 alignment 字段时为空，bundletool 默认按 4K 对齐）
    """
    try:
        proc = _run_java_jar(bundletool_path, 'dump', 'config', '--bundle=' + aab_path, timeout=120)
        raw = proc.stdout + proc.stderr
        data = json.loads(raw)
        bt_version = data.get('bundletool', {}).get('version', '')
        uncompress = data.get('optimizations', {}).get(
            'uncompressNativeLibraries', {}).get('enabled')
        # ZIP 对齐标记：PAGE_ALIGNMENT_16K = 16K 对齐；PAGE_ALIGNMENT_4K 或缺失 = 4K 对齐
        page_alignment = ''
        if 'PAGE_ALIGNMENT_16K' in raw:
            page_alignment = '16K'
        elif 'PAGE_ALIGNMENT_4K' in raw:
            page_alignment = '4K'
        return bt_version, uncompress, page_alignment, raw
    except Exception as e:
        return '', None, '', f'⚠️ dump config 解析失败: {e}'


def build_universal_apk(bundletool_path: str, aab_path: str, tmp_dir: str):
    """bundletool build-apks --mode=universal → 解压 → 返回 universal.apk 路径

    返回: (universal_apk_path, error)
    """
    apks_path = os.path.join(tmp_dir, 'app.apks')
    apks_extract_dir = os.path.join(tmp_dir, 'apks')
    os.makedirs(apks_extract_dir, exist_ok=True)

    try:
        proc = _run_java_jar(
            bundletool_path,
            'build-apks',
            '--bundle=' + aab_path,
            '--output=' + apks_path,
            '--mode=universal',
            timeout=600
        )
    except Exception as e:
        return '', f'bundletool build-apks 执行出错: {e}'

    if proc.returncode != 0 or not os.path.isfile(apks_path):
        err = (proc.stderr or proc.stdout or '').strip()[:500]
        return '', f'bundletool build-apks 失败: {err}'

    try:
        with zipfile.ZipFile(apks_path, 'r') as zf:
            zf.extractall(apks_extract_dir)
    except Exception as e:
        return '', f'解压 .apks 失败: {e}'

    universal_apk = os.path.join(apks_extract_dir, 'universal.apk')
    if not os.path.isfile(universal_apk):
        return '', '未在 .apks 中找到 universal.apk'

    return universal_apk, ''


def _elf_check_from_aab(aab_path: str, tmp_dir: str):
    """fallback：直接解压 AAB 提取 .so 做 ELF 检查（bundletool 不可用时）"""
    extract_dir = os.path.join(tmp_dir, 'aab_extract')
    os.makedirs(extract_dir, exist_ok=True)
    try:
        with zipfile.ZipFile(aab_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.endswith('.so') and not info.is_dir():
                    zf.extract(info.filename, extract_dir)
    except Exception:
        pass
    elf_results, elf_output = run_elf_check(extract_dir, extracted_so_dir=extract_dir)
    return elf_results, elf_output


def check_aab(aab_path: str) -> CheckResult:
    """检查 AAB 文件"""
    aab_path = os.path.abspath(aab_path)
    c = Colors

    result = CheckResult(
        file_path=aab_path,
        file_size=_format_size(os.path.getsize(aab_path)),
        check_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    )

    # ---- 定位 bundletool ----
    bundletool_path = find_bundletool()
    if not bundletool_path:
        result.bundletool_available = False
        result.zipalign = ZipalignResult(
            available=False,
            status="unavailable",
            summary="⚠️ 未找到 bundletool，无法转出分发 APK 做 zipalign 验证"
        )
        # fallback：仅 ELF 检查
        tmp_dir = _aab_tmp_dir()
        try:
            elf_results, elf_output = _elf_check_from_aab(aab_path, tmp_dir)
            result.elf_results = elf_results
            result.elf_script_output = elf_output
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        return result

    result.bundletool_available = True

    # ---- 1. dump config 前置判断 ----
    bt_version, uncompress, page_alignment, dump_raw = dump_bundle_config(bundletool_path, aab_path)
    result.bundletool_version = bt_version
    result.uncompress_native_libraries = uncompress
    result.page_alignment = page_alignment
    result.dump_config_raw = dump_raw

    # ---- 2. build-apks 转 universal APK ----
    tmp_dir = _aab_tmp_dir()
    try:
        universal_apk, err = build_universal_apk(bundletool_path, aab_path, tmp_dir)
        if err:
            result.zipalign = ZipalignResult(
                available=False,
                status="fail",
                summary=f"⚠️ {err}"
            )
            return result

        result.aab_universal_apk = universal_apk

        # ---- 3. 复用 check_apk 检查 universal APK（zipalign + ELF + 压缩检测）----
        apk_result = check_apk(universal_apk)
        result.zipalign = apk_result.zipalign
        result.elf_results = apk_result.elf_results
        result.elf_script_output = apk_result.elf_script_output
        result.has_compressed_so = apk_result.has_compressed_so
        result.compressed_so_names = apk_result.compressed_so_names

    finally:
        # 保留 tmp_dir：universal.apk 供调试，目录位于 ZIXIEKIT_TMP 可随时清理
        pass

    return result
