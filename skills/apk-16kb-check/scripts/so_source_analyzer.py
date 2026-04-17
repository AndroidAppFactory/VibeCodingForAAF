#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
so_source_analyzer.py
SO 来源分析：从 APK/AAR 路径反推 .so 文件的来源模块

策略：
  1. 从 APK 路径反推项目根目录
  2. 从 APK 中提取 .so 文件名列表
  3. 在 Gradle transforms 缓存中反向查找来源
  4. 通过 modules-2 缓存反查完整 Maven 坐标（groupId:artifactId）
  5. 未匹配的标记为「来源未知」
"""

import os
import re
import zipfile
from typing import Dict, Optional, Tuple
from pathlib import Path

from models import Colors


# ============================================================================
# SO 来源分析：APK → Gradle transforms 缓存反向查找
# ============================================================================

# APK 产物路径的典型模式（从最具体到最通用）
_APK_OUTPUT_PATTERNS = [
    'build/outputs/apk/',
    'build/outputs/bundle/',
    'build/intermediates/apk/',
]


def detect_project_root(apk_path: str) -> Optional[Tuple[str, str]]:
    """从 APK 路径反推 Android 项目根目录和模块名

    匹配模式: {project_root}/{module}/build/outputs/apk/{variant}/{apk}

    返回: (project_root, module_name) 或 None
    """
    abs_path = os.path.abspath(apk_path)
    normalized = abs_path.replace('\\', '/')

    for pattern in _APK_OUTPUT_PATTERNS:
        idx = normalized.find(pattern)
        if idx == -1:
            continue

        module_path = normalized[:idx].rstrip('/')
        if not module_path:
            continue

        module_name = os.path.basename(module_path)
        project_root_candidate = os.path.dirname(module_path)

        for settings_name in ('settings.gradle', 'settings.gradle.kts'):
            if os.path.isfile(os.path.join(project_root_candidate, settings_name)):
                return project_root_candidate, module_name

        for settings_name in ('settings.gradle', 'settings.gradle.kts'):
            if os.path.isfile(os.path.join(module_path, settings_name)):
                return module_path, module_name

    return None


def _read_gradle_property(properties_file: str, key: str) -> Optional[str]:
    """从 gradle.properties 文件中读取指定属性值

    返回: 属性值字符串，或 None（文件不存在/属性不存在）
    """
    if not os.path.isfile(properties_file):
        return None
    try:
        with open(properties_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line.startswith('#') or '=' not in line:
                    continue
                k, _, v = line.partition('=')
                if k.strip() == key:
                    return v.strip()
    except Exception:
        pass
    return None


def _resolve_gradle_user_home(project_root: Optional[str] = None) -> Tuple[Optional[str], str]:
    """解析 Gradle User Home 路径

    解析优先级：
    1. 项目根目录 gradle.properties 中的 gradle.user.home（最高优先级）
    2. $GRADLE_USER_HOME 环境变量

    若两级均未配置，返回 None。

    返回: (gradle_user_home, source_desc)
      - gradle_user_home: 解析到的路径，或 None（未配置或路径无效）
      - source_desc: 来源描述（用于日志输出）
    """
    # 优先级 1: 项目根目录 gradle.properties（最高优先级）
    if project_root:
        project_props = os.path.join(project_root, 'gradle.properties')
        prop_value = _read_gradle_property(project_props, 'gradle.user.home')
        if prop_value:
            expanded = os.path.expanduser(prop_value)
            if os.path.isdir(expanded):
                return expanded, f'项目 gradle.properties: gradle.user.home={prop_value}'

    # 优先级 2: 环境变量
    env_home = os.environ.get('GRADLE_USER_HOME', '').strip()
    if env_home:
        expanded = os.path.expanduser(env_home)
        if os.path.isdir(expanded):
            return expanded, f'环境变量 GRADLE_USER_HOME={env_home}'

    return None, ''


def _get_gradle_cache_dirs(project_root: Optional[str] = None) -> Tuple[list, Optional[str], str]:
    """获取 Gradle caches 目录

    按 Gradle 标准优先级解析 GRADLE_USER_HOME，然后定位 caches 子目录。

    返回: (cache_dirs, gradle_user_home, source_desc)
    """
    gradle_user_home, source_desc = _resolve_gradle_user_home(project_root)
    if not gradle_user_home:
        return [], None, ''

    caches_dir = os.path.join(gradle_user_home, 'caches')
    if os.path.isdir(caches_dir):
        return [caches_dir], gradle_user_home, source_desc

    return [], gradle_user_home, source_desc


def _extract_artifact_name(artifact_dir: str) -> Tuple[str, bool]:
    """从 transforms 缓存目录名中提取 artifact 名称

    处理规则：
    1. 去掉 jetified- 前缀
    2. 去掉 -release / -debug 后缀（标记为本地项目模块）
    3. 去掉末尾版本号（如 camera-core-1.1.0 → camera-core）

    返回: (artifact_name, is_versioned)
      - is_versioned=True 表示带版本号的 Maven 依赖（优先级更高）
      - is_versioned=False 表示带 -release/-debug 后缀的本地模块
    """
    source_name = artifact_dir
    is_versioned = False

    # 去掉 jetified- 前缀
    if source_name.startswith('jetified-'):
        source_name = source_name[len('jetified-'):]

    # 检查是否带 -release / -debug 后缀（本地项目模块）
    for suffix in ('-release', '-debug'):
        if source_name.lower().endswith(suffix):
            source_name = source_name[:-len(suffix)]
            return source_name, False

    # 去掉末尾版本号（Maven 依赖）
    stripped = re.sub(r'-\d+(\.\d+)*$', '', source_name)
    if stripped != source_name:
        is_versioned = True
        source_name = stripped

    return source_name, is_versioned


def _resolve_maven_coordinate(artifact_name: str, caches_dir: str) -> Optional[str]:
    """通过 modules-2 缓存反查完整 Maven 坐标

    在 {caches_dir}/modules-2/files-2.1/{groupId}/{artifactId}/ 中查找匹配的目录。

    返回: "groupId:artifactId" 或 None
    """
    modules_dir = os.path.join(caches_dir, 'modules-2', 'files-2.1')
    if not os.path.isdir(modules_dir):
        return None

    # 遍历 groupId 目录，查找匹配的 artifactId
    try:
        for group_id in os.listdir(modules_dir):
            group_path = os.path.join(modules_dir, group_id)
            if not os.path.isdir(group_path):
                continue
            artifact_path = os.path.join(group_path, artifact_name)
            if os.path.isdir(artifact_path):
                return f"{group_id}:{artifact_name}"
    except PermissionError:
        pass

    return None


def reverse_lookup_so_in_transforms(so_names: set) -> Dict[str, Dict]:
    """反向查找：在 Gradle transforms 缓存中搜索包含指定 SO 的目录

    两阶段查找：
    1. 在 transforms 缓存中匹配 SO → artifact 名称
    2. 通过 modules-2 缓存反查完整 Maven 坐标（groupId:artifactId）

    返回: {so_name: {module: "groupId:artifactId" 或 "artifact名称", type: "external"}}
    """
    if not so_names:
        return {}

    # 第一阶段：transforms 缓存匹配
    # 收集所有匹配，优先选择带版本号的（Maven 依赖，能反查 groupId）
    so_map: Dict[str, Dict] = {}
    cache_dirs_used = []

    cache_dirs, _, _ = _get_gradle_cache_dirs()
    for caches_dir in cache_dirs:
        cache_dirs_used.append(caches_dir)
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

                        for root, dirs, files in os.walk(artifact_path):
                            for f in files:
                                if f not in so_names:
                                    continue

                                artifact_name, is_versioned = _extract_artifact_name(artifact_dir)

                                # 如果已有匹配，优先保留带版本号的（Maven 依赖）
                                if f in so_map:
                                    if not is_versioned:
                                        continue  # 已有更好的匹配，跳过
                                    if so_map[f].get('_is_versioned', False):
                                        continue  # 已有同等优先级的匹配

                                so_map[f] = {
                                    'module': artifact_name,
                                    'type': 'external',
                                    'path': os.path.join(root, f),
                                    '_is_versioned': is_versioned,
                                    '_artifact_name': artifact_name,
                                }

                        # 所有 SO 都已找到带版本号的匹配，提前退出
                        all_versioned = all(
                            so_map.get(s, {}).get('_is_versioned', False)
                            for s in so_names if s in so_map
                        )
                        if so_names <= set(so_map.keys()) and all_versioned:
                            break
        except PermissionError:
            pass

    # 第二阶段：通过 modules-2 反查完整 Maven 坐标
    for caches_dir in cache_dirs_used:
        for so_name, info in so_map.items():
            artifact_name = info.get('_artifact_name', '')
            if not artifact_name:
                continue

            maven_coord = _resolve_maven_coordinate(artifact_name, caches_dir)
            if maven_coord:
                info['module'] = maven_coord

    # 清理内部字段
    for info in so_map.values():
        info.pop('_is_versioned', None)
        info.pop('_artifact_name', None)

    return so_map


def _extract_so_names_from_apk(apk_path: str) -> set:
    """从 APK 文件中提取所有 .so 文件名

    返回: set of so_name（如 {'libfoo.so', 'libbar.so'}）
    """
    so_names: set = set()
    try:
        with zipfile.ZipFile(apk_path, 'r') as zf:
            for info in zf.infolist():
                if info.filename.endswith('.so'):
                    so_names.add(Path(info.filename).name)
    except Exception:
        pass
    return so_names


def analyze_so_sources_from_aars(aar_paths) -> Dict[str, Dict]:
    """AAR 模式：直接从原始 AAR 文件中提取 .so 列表建立映射

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

    流程：
    1. 从 APK 路径反推项目根目录
    2. 从 APK 中提取 .so 文件名列表
    3. 在 Gradle transforms 缓存中反向查找来源
    4. 通过 modules-2 缓存反查完整 Maven 坐标
    5. 未匹配的标记为「来源未知」

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

    # 解析 Gradle User Home
    cache_dirs, gradle_user_home, source_desc = _get_gradle_cache_dirs(project_root)
    if not gradle_user_home or not cache_dirs:
        print(f"  {c.YELLOW}⚠️ 未找到有效的 Gradle User Home，.so 来源将显示为未设置{c.NC}")
        print(f"  {c.YELLOW}   可在项目 gradle.properties 中配置 gradle.user.home 或设置 GRADLE_USER_HOME 环境变量{c.NC}")
    else:
        print(f"  Gradle User Home: {gradle_user_home}（{source_desc}）")

    so_map: Dict[str, Dict] = {}

    # Step 1: 从 APK 中提取 SO 文件名列表
    all_so_names = _extract_so_names_from_apk(apk_path)
    if not all_so_names:
        print(f"  {c.YELLOW}⚠️ APK 中未发现 .so 文件{c.NC}")
        return project_root, so_map

    print(f"  APK 中共有 {len(all_so_names)} 个 .so 文件")

    # Step 2: 在 Gradle transforms 缓存中反向查找来源 + modules-2 反查 Maven 坐标
    if cache_dirs:
        print(f"  反向查找 Gradle 缓存...")
        reverse_map = reverse_lookup_so_in_transforms(all_so_names)
        if reverse_map:
            so_map.update(reverse_map)
            print(f"  {c.GREEN}  匹配到 {len(reverse_map)} 个 .so 来源{c.NC}")

    # Step 3: 剩余未匹配的标记
    unmatched_so = all_so_names - set(so_map.keys())
    if unmatched_so:
        if cache_dirs:
            # 有缓存但未匹配到 → 来源未知
            print(f"  {c.YELLOW}  仍有 {len(unmatched_so)} 个 .so 来源未知{c.NC}")
            for so_name in unmatched_so:
                so_map[so_name] = {'module': '', 'type': ''}
        else:
            # 没有 Gradle 缓存 → 未设置
            for so_name in unmatched_so:
                so_map[so_name] = {'module': '', 'type': 'not_configured'}

    total = len(so_map)
    matched = sum(1 for v in so_map.values() if v.get('module'))
    if total > 0:
        print(f"  {c.GREEN}✅ 共建立 {total} 个 .so 来源映射（{matched} 个已识别，{total - matched} 个未知）{c.NC}")
    else:
        print(f"  {c.YELLOW}⚠️ 未能建立 .so 来源映射{c.NC}")

    return project_root, so_map
