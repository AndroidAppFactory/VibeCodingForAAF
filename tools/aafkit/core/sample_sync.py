#!/usr/bin/env python3
"""
AAF Sample 同步工具

将 Template-AAF 的修改同步（复制替换）到 Template_Android 和 Template-Empty。

设计思路：
- Template-AAF 是"源"，用户先通过 aaf sample-apply 升级 Template-AAF
- 本模块将 Template-AAF 的配置和代码同步到另外两个项目
- Template_Android 和 Template-Empty 的特殊差异会自动处理
  - Template_Android：模块结构不同（Application/ + APPTest/），依赖名不同
  - Template-Empty：单模块（App/），使用 appMinSdkVersion，有独有依赖
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from .config_reader import build_project, get_aaf_home, get_aaf_root, read_config


def sample_sync() -> dict[str, list[str]]:
    """将 Template-AAF 的修改同步到 Template_Android 和 Template-Empty

    Returns:
        {项目名: [变更列表]}
    """
    aaf_home = get_aaf_home()
    template_aaf = aaf_home / "Template-AAF"

    if not template_aaf.exists():
        return {"错误": ["❌ Template-AAF 不存在"]}

    results: dict[str, list[str]] = {}

    # 同步到 Template_Android
    template_android = aaf_home / "Template_Android"
    if template_android.exists():
        results["Template_Android"] = _sync_to_template_android(template_aaf, template_android)
    else:
        results["Template_Android"] = ["⚠️ 项目不存在，跳过"]

    # 同步到 Template-Empty
    template_empty = aaf_home / "Template-Empty"
    if template_empty.exists():
        results["Template-Empty"] = _sync_to_template_empty(template_aaf, template_empty)
    else:
        results["Template-Empty"] = ["⚠️ 项目不存在，跳过"]

    return results


def _sync_to_template_android(src: Path, dst: Path) -> list[str]:
    """将 Template-AAF 的修改同步到 Template_Android

    Template_Android 与 Template-AAF 的关键差异：
    - 模块结构：Template-AAF 只有 APPTest/，Template_Android 有 Application/ + APPTest/
    - 依赖管理：Template-AAF 用 AAF 集中式（dependencies.gradle），
      Template_Android 用标准方式（模块 build.gradle）
    - APPTest 依赖名：Template-AAF 写 common-wrapper + lib-router-compiler，
      Template_Android 应写 common-debug + lib-router-compiler

    同步策略：
    - config.gradle → 直接复制
    - gradle-wrapper.properties → 直接复制
    - build.gradle → 同步关键配置（Kotlin 版本、Gradle 插件版本），不直接复制
    - APPTest/build.gradle → 同步 AAF 依赖版本（不直接复制，依赖名不同）
    - APPTest UI 代码 → 直接复制
    - APPTest/AndroidManifest.xml → 直接复制
    - Application/build.gradle → 同步 AAF 依赖版本
    """
    changes: list[str] = []

    # 检查工作区是否干净
    if not _check_clean(dst):
        return ["❌ 有未提交的本地变更，请先处理"]

    # git pull
    pull_msg = _git_pull(dst)
    if pull_msg:
        changes.append(pull_msg)
        if "❌" in pull_msg:
            return changes

    aaf_root = get_aaf_root()
    aaf_config = read_config(aaf_root)

    # 1. config.gradle — 直接复制
    changes.extend(_direct_copy_file(src, dst, "config.gradle"))

    # 2. gradle-wrapper.properties — 直接复制
    changes.extend(_direct_copy_file(src, dst, "gradle/wrapper/gradle-wrapper.properties"))

    # 3. build.gradle — 同步关键配置（Kotlin 版本、Gradle 插件版本），不直接复制
    changes.extend(_sync_root_build_gradle(src, dst, aaf_config))

    # 4. APPTest/build.gradle — 同步 AAF 依赖版本（不直接复制，依赖名不同）
    #    Template-AAF 写 common-wrapper + lib-router-compiler
    #    Template_Android 应写 common-debug + lib-router-compiler
    changes.extend(_sync_apptest_build_gradle_for_android(src, dst, aaf_config))

    # 5. APPTest UI 代码 — 直接复制
    ui_files = [
        "APPTest/src/main/java/com/bihe0832/android/test/DebugMainActivity.kt",
        "APPTest/src/main/java/com/bihe0832/android/test/module/DebugTempView.kt",
        "APPTest/src/main/java/com/bihe0832/android/test/module/DebugRouterView.kt",
    ]
    for rel_path in ui_files:
        changes.extend(_direct_copy_file(src, dst, rel_path))

    # 6. APPTest/src/main/AndroidManifest.xml — 直接复制
    changes.extend(_direct_copy_file(src, dst, "APPTest/src/main/AndroidManifest.xml"))

    # 7. Application/build.gradle — 同步 AAF 依赖版本
    app_build = dst / "Application/build.gradle"
    if app_build.exists():
        content = app_build.read_text(encoding="utf-8")
        new_content = _sync_aaf_deps_in_content(content, aaf_config)
        if new_content != content:
            app_build.write_text(new_content, encoding="utf-8")
            changes.append("✅ Application/build.gradle: 同步 AAF 依赖版本")

    # 8. 验证 lib-router-compiler Maven 可用性
    changes.extend(_check_lib_router_compiler_maven(aaf_config))

    if not changes:
        changes.append("✅ 已是最新，无需同步")

    return changes


def _sync_to_template_empty(src: Path, dst: Path) -> list[str]:
    """将 Template-AAF 的修改同步到 Template-Empty

    Template-Empty 与 Template-AAF 的关键差异：
    - 单模块结构：只有 App/，没有 APPTest/ 或 Application/
    - config.gradle 使用 appMinSdkVersion 而非 libMinSdkVersion
    - App/build.gradle 有独有依赖：common-compose-debug、common-wrapper-min、lib-router-compiler
    - 没有 Compose UI 代码需要同步
    - 需要 libs/ 目录

    同步策略：
    - config.gradle → 复制后修改 SDK 字段（使用 appMinSdkVersion）
    - gradle-wrapper.properties → 直接复制
    - App/build.gradle → 同步 AAF 依赖版本 + 添加独有依赖
    - App/src/main/AndroidManifest.xml → 检查 exported 属性
    - libs/ 目录 → 检查存在性
    """
    changes: list[str] = []

    # 检查工作区是否干净
    if not _check_clean(dst):
        return ["❌ 有未提交的本地变更，请先处理"]

    # git pull
    pull_msg = _git_pull(dst)
    if pull_msg:
        changes.append(pull_msg)
        if "❌" in pull_msg:
            return changes

    aaf_root = get_aaf_root()
    aaf_config = read_config(aaf_root)

    # 1. config.gradle — 复制后修改 SDK 字段
    changes.extend(_sync_config_gradle_for_empty(src, dst, aaf_config))

    # 2. gradle-wrapper.properties — 直接复制
    changes.extend(_direct_copy_file(src, dst, "gradle/wrapper/gradle-wrapper.properties"))

    # 3. App/build.gradle — 同步 AAF 依赖版本 + 添加独有依赖
    changes.extend(_sync_app_build_gradle_for_empty(dst, aaf_config))

    # 4. App/src/main/AndroidManifest.xml — 检查 exported
    manifest = dst / "App/src/main/AndroidManifest.xml"
    if manifest.exists():
        content = manifest.read_text(encoding="utf-8")
        new_content = _ensure_exported(content)
        if new_content != content:
            manifest.write_text(new_content, encoding="utf-8")
            changes.append('✅ App/src/main/AndroidManifest.xml: 添加 exported="true"')

    # 5. libs/ 目录 — 检查存在性
    libs_dir = dst / "App/libs"
    if not libs_dir.exists():
        libs_dir.mkdir(parents=True, exist_ok=True)
        changes.append("✅ App/libs/: 创建目录")

    # 6. 验证 lib-router-compiler Maven 可用性
    changes.extend(_check_lib_router_compiler_maven(aaf_config))

    if not changes:
        changes.append("✅ 已是最新，无需同步")

    return changes


# ============================================================
# 通用辅助函数
# ============================================================

def _direct_copy_file(src: Path, dst: Path, rel_path: str) -> list[str]:
    """直接复制单个文件（如内容不同）"""
    src_file = src / rel_path
    dst_file = dst / rel_path
    if not src_file.exists():
        return [f"⚠️ 源文件不存在: {rel_path}"]
    if dst_file.exists() and src_file.read_text(encoding="utf-8") == dst_file.read_text(encoding="utf-8"):
        return []  # 内容相同，跳过
    dst_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_file, dst_file)
    return [f"📋 复制: {rel_path}"]


def _sync_root_build_gradle(src: Path, dst: Path, aaf_config) -> list[str]:
    """同步根 build.gradle 的关键配置（Kotlin 版本、Gradle 插件版本）

    不直接复制整个文件，因为 Template_Android 和 Template-AAF 的根 build.gradle
    结构不同（Template-AAF 引用 dependencies.gradle，Template_Android 不引用）。
    """
    changes: list[str] = []

    src_build = src / "build.gradle"
    dst_build = dst / "build.gradle"
    if not src_build.exists() or not dst_build.exists():
        return changes

    src_content = src_build.read_text(encoding="utf-8")
    dst_content = dst_build.read_text(encoding="utf-8")
    new_dst_content = dst_content

    # 同步 Kotlin 版本（兼容 ext.kotlin_version 和 kotlin_version 两种写法）
    kotlin_ver = _extract_value(src_content, "ext.kotlin_version")
    if not kotlin_ver:
        kotlin_ver = _extract_value(src_content, "kotlin_version")
    if kotlin_ver:
        # 先尝试 ext.kotlin_version，再尝试 kotlin_version
        replaced = _replace_value(new_dst_content, "ext.kotlin_version", kotlin_ver)
        if replaced == new_dst_content:
            replaced = _replace_value(new_dst_content, "kotlin_version", kotlin_ver)
        new_dst_content = replaced

    # 同步 Gradle 插件版本（兼容 classpath 和 id+version 两种格式）
    gradle_plugin_ver = ""
    # 格式 1: classpath 'com.android.tools.build:gradle:x.x.x'
    gradle_plugin_match = re.search(
        r"classpath\s+['\"]com\.android\.tools\.build:gradle:([^'\"]+)['\"]", src_content
    )
    if gradle_plugin_match:
        gradle_plugin_ver = gradle_plugin_match.group(1)
    else:
        # 格式 2: id 'com.android.application' version 'x.x.x'
        gradle_plugin_match = re.search(
            r"id\s+['\"]com\.android\.application['\"]\s+version\s+['\"]([^'\"]+)['\"]", src_content
        )
        if gradle_plugin_match:
            gradle_plugin_ver = gradle_plugin_match.group(1)

    if gradle_plugin_ver:
        # 替换 classpath 格式
        new_dst_content = re.sub(
            r"classpath\s+['\"]com\.android\.tools\.build:gradle:([^'\"]+)['\"]",
            f"classpath 'com.android.tools.build:gradle:{gradle_plugin_ver}'",
            new_dst_content,
        )
        # 替换 id+version 格式
        new_dst_content = re.sub(
            r"(id\s+['\"]com\.android\.application['\"]\s+version\s+['\"])([^'\"]+)(['\"])",
            rf"\g<1>{gradle_plugin_ver}\3",
            new_dst_content,
        )

    if new_dst_content != dst_content:
        dst_build.write_text(new_dst_content, encoding="utf-8")
        changes.append("✅ build.gradle: 同步 Kotlin 和 Gradle 插件版本")

    return changes


def _sync_apptest_build_gradle_for_android(src: Path, dst: Path, aaf_config) -> list[str]:
    """同步 Template_Android 的 APPTest/build.gradle

    Template-AAF 的 APPTest/build.gradle 是源文件，但 Template_Android 的 APPTest/build.gradle
    有以下专属配置需要保留：
    - dependencies {} 块：包含 api project(':Application')、common-compose-debug、lib-router-compiler
    - kapt {} 块：correctErrorTypes 配置

    同步策略：
    1. 从 Template-AAF 提取 android {} 块内容
    2. 保留 Template_Android 的 dependencies {} 块和 kapt {} 配置
    3. 只更新 android {} 块内的配置（如 compileSdkVersion、Kotlin 版本等）
    4. 同步 AAF 依赖版本（在 dependencies 块中）
    """
    changes: list[str] = []

    src_file = src / "APPTest/build.gradle"
    dst_file = dst / "APPTest/build.gradle"
    if not src_file.exists() or not dst_file.exists():
        return changes

    src_content = src_file.read_text(encoding="utf-8")
    dst_content = dst_file.read_text(encoding="utf-8")

    # 提取 Template-AAF 的 android {} 块
    src_android_block = _extract_android_block(src_content)
    if not src_android_block:
        return changes

    # 提取 Template_Android 的 dependencies {} 块和 kapt {} 块
    dst_deps_block = _extract_block(dst_content, "dependencies")
    dst_kapt_block = _extract_block(dst_content, "kapt")

    # 构建新的内容：使用 Template-AAF 的头部 + android 块，保留 Template_Android 的 dependencies 和 kapt
    # 1. 头部（plugins + project.ext 配置）
    src_header = _extract_header(src_content)

    # 2. android 块（从 Template-AAF 来，但同步版本号）
    new_android_block = _sync_aaf_deps_in_content(src_android_block, aaf_config)

    # 3. 构建新内容
    new_content = src_header + "\n" + new_android_block

    # 4. 添加 kapt 块（如果在 Template_Android 中存在）
    if dst_kapt_block:
        new_content += "\n" + dst_kapt_block

    # 5. 添加 dependencies 块（从 Template_Android 保留，但同步版本号）
    if dst_deps_block:
        synced_deps = _sync_aaf_deps_in_content(dst_deps_block, aaf_config)
        new_content += "\n" + synced_deps

    # 6. 替换依赖名：common-wrapper → common-debug（如果在 dependencies 中有）
    new_content = new_content.replace("common-wrapper", "common-debug")

    if new_content != dst_content:
        dst_file.write_text(new_content, encoding="utf-8")
        changes.append("✅ APPTest/build.gradle: 同步 android 配置 + 保留依赖配置")

    return changes


def _extract_android_block(content: str) -> str:
    """提取 build.gradle 中的 android {} 块（包含块内容）"""
    # 找到 android { 的开始位置
    start = content.find("android {")
    if start == -1:
        return ""
    
    # 找到对应的结束 }
    brace_count = 0
    in_block = False
    end = start
    
    for i in range(start, len(content)):
        if content[i] == '{':
            brace_count += 1
            in_block = True
        elif content[i] == '}':
            brace_count -= 1
            if in_block and brace_count == 0:
                end = i + 1
                break
    
    return content[start:end]


def _extract_header(content: str) -> str:
    """提取 build.gradle 的头部（plugins + project.ext 配置，在 android {} 之前的内容）"""
    android_start = content.find("android {")
    if android_start == -1:
        return content
    return content[:android_start].strip()


def _extract_block(content: str, block_name: str) -> str:
    """提取 build.gradle 中的指定块（如 dependencies {} 或 kapt {}）"""
    # 找到块的开始位置
    pattern = rf'^{block_name}\s*\{{'
    lines = content.split('\n')
    start_idx = -1
    end_idx = -1
    
    for i, line in enumerate(lines):
        if re.match(pattern, line.strip()):
            start_idx = i
            brace_count = 0
            for j in range(i, len(lines)):
                brace_count += lines[j].count('{') - lines[j].count('}')
                if brace_count == 0 and j > i:
                    end_idx = j
                    break
            break
    
    if start_idx != -1 and end_idx != -1:
        return '\n'.join(lines[start_idx:end_idx + 1])
    return ""


def _sync_config_gradle_for_empty(src: Path, dst: Path, aaf_config) -> list[str]:
    """同步 Template-Empty 的 config.gradle

    Template-Empty 使用 appMinSdkVersion 而非 libMinSdkVersion。
    从 Template-AAF 复制 config.gradle 后，需要替换 SDK 字段。
    """
    changes: list[str] = []

    config_src = src / "config.gradle"
    config_dst = dst / "config.gradle"
    if not config_src.exists() or not config_dst.exists():
        return changes

    src_content = config_src.read_text(encoding="utf-8")
    dst_content = config_dst.read_text(encoding="utf-8")

    new_dst_content = src_content

    # 同步 SDK 版本字段
    for field in ["compileSdkVersion", "buildToolsVersion", "targetSdkVersion"]:
        src_val = _extract_value(src_content, field)
        if src_val:
            new_dst_content = _replace_value(new_dst_content, field, src_val)

    # Template-Empty 使用 appMinSdkVersion
    if aaf_config.app_min_sdk_version:
        # 先尝试替换已有的 appMinSdkVersion
        found = False
        for field in ["appMinSdkVersion", "minSdkVersion"]:
            if _extract_value(new_dst_content, field):
                new_dst_content = _replace_value(new_dst_content, field, aaf_config.app_min_sdk_version)
                found = True
                break
        # 如果没有找到，添加 appMinSdkVersion
        if not found and "libMinSdkVersion" in new_dst_content:
            new_dst_content = new_dst_content.replace("libMinSdkVersion", "appMinSdkVersion")
            new_dst_content = _replace_value(new_dst_content, "appMinSdkVersion", aaf_config.app_min_sdk_version)

    if new_dst_content != dst_content:
        config_dst.write_text(new_dst_content, encoding="utf-8")
        changes.append("✅ config.gradle: 同步 SDK 配置（使用 appMinSdkVersion）")

    return changes


def _sync_app_build_gradle_for_empty(dst: Path, aaf_config) -> list[str]:
    """同步 Template-Empty 的 App/build.gradle

    Template-Empty 有独有依赖：common-compose-debug、common-wrapper-min、lib-router-compiler
    这些依赖在 Template-AAF 中不存在，需要确保它们存在。
    """
    changes: list[str] = []

    app_build = dst / "App/build.gradle"
    if not app_build.exists():
        return changes

    content = app_build.read_text(encoding="utf-8")
    new_content = _sync_aaf_deps_in_content(content, aaf_config)

    # 确保独有依赖存在
    unique_deps = {
        "common-compose-debug": aaf_config.module_versions.get("common-compose-debug", aaf_config.module_version_name),
        "common-wrapper-min": aaf_config.module_versions.get("common-wrapper-min", aaf_config.module_version_name),
        "lib-router-compiler": aaf_config.module_versions.get("lib-router-compiler", aaf_config.module_version_name),
    }

    for artifact_id, version in unique_deps.items():
        dep_line = f'com.bihe0832.android:{artifact_id}:{version}'
        # 检查依赖是否已存在（不区分版本）
        pattern = rf'com\.bihe0832\.android:{re.escape(artifact_id)}:[^\s\'"]+'
        if not re.search(pattern, new_content):
            # 在 dependencies 块中添加
            if 'dependencies {' in new_content:
                new_content = new_content.replace(
                    'dependencies {',
                    f'dependencies {{\n    implementation "{dep_line}"',
                )
            else:
                new_content += f'\ndependencies {{\n    implementation "{dep_line}"\n}}\n'
            changes.append(f"✅ App/build.gradle: 添加缺失依赖 {artifact_id}")

    if new_content != content:
        app_build.write_text(new_content, encoding="utf-8")
        if "✅ App/build.gradle: 添加缺失依赖" not in " ".join(changes):
            changes.append("✅ App/build.gradle: 同步 AAF 依赖版本")

    return changes


def _check_lib_router_compiler_maven(aaf_config) -> list[str]:
    """验证 lib-router-compiler 的 Maven 可用性"""
    warnings: list[str] = []

    ver = aaf_config.module_versions.get("lib-router-compiler", aaf_config.module_version_name)
    if ver == aaf_config.module_version_name:
        warnings.append(
            f"⚠️ lib-router-compiler 未在 AAF 配置中找到独立版本号，"
            f"将使用通用版本 {ver}，请验证 Maven 可用性"
        )

    return warnings


# ============================================================
# 已有辅助函数（保留不变）
# ============================================================

def _sync_aaf_deps_in_content(content: str, aaf_config) -> str:
    """同步文件内容中的 AAF 依赖版本"""
    new_content = content
    for m in re.finditer(r"com\.bihe0832\.android:([^:'\"\s]+):([^'\"\s$]+)", content):
        artifact_id = m.group(1)
        current_ver = m.group(2)
        if current_ver.startswith("$") or current_ver.startswith("{"):
            continue
        latest_ver = aaf_config.module_versions.get(artifact_id, aaf_config.module_version_name)
        if current_ver != latest_ver:
            old = f"com.bihe0832.android:{artifact_id}:{current_ver}"
            new = f"com.bihe0832.android:{artifact_id}:{latest_ver}"
            new_content = new_content.replace(old, new)
    return new_content


def _ensure_exported(content: str) -> str:
    """确保 LAUNCHER Activity 有 android:exported=\"true\""""
    if "android.intent.category.LAUNCHER" not in content:
        return content

    launcher_pattern = re.compile(
        r'(<activity[^>]*?)(>)(.*?android\.intent\.category\.LAUNCHER.*?</activity>)',
        re.DOTALL,
    )
    m = launcher_pattern.search(content)
    if m:
        activity_tag = m.group(1)
        if 'android:exported' not in activity_tag:
            new_tag = activity_tag + '\n            android:exported="true"'
            content = content[:m.start(1)] + new_tag + m.group(2) + m.group(3) + content[m.end():]
    return content


def _extract_value(content: str, key: str) -> str:
    """从 Gradle 内容中提取值"""
    patterns = [
        rf'{key}\s*=\s*["\']([^"\']+)["\']',
        rf'{key}\s*=\s*(\d+)',
    ]
    for pattern in patterns:
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    return ""


def _replace_value(content: str, key: str, new_value: str) -> str:
    """替换 Gradle 内容中的值"""
    patterns = [
        (rf'({key}\s*=\s*["\'])([^"\']+)(["\'])', rf'\g<1>{new_value}\3'),
        (rf'({key}\s*=\s*)(\d+)(\s)', rf'\g<1>{new_value}\3'),
    ]
    for pattern, replacement in patterns:
        new_content, count = re.subn(pattern, replacement, content)
        if count > 0:
            return new_content
    return content


def _check_clean(project_path: Path) -> bool:
    """检查工作区是否干净"""
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def _git_pull(project_path: Path) -> str:
    """执行 git pull，返回状态消息（空字符串表示成功无需报告）"""
    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=project_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"❌ git pull 失败: {result.stderr.strip()}"
    return ""
