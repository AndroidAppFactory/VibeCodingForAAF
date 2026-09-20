#!/usr/bin/env python3
"""
AAF Sample 项目升级工具（单个项目）

检查并升级单个 AAF Sample 项目（Template-AAF、Template_Android、Template-Empty）到最新 AAF 版本

职责：
- 单个项目的配置检查、依赖升级、代码同步、编译验证
- 与 aaf-sample-apply Skill 职责对齐
- 批量升级请使用 aaf-sample-upgrade Skill（通过 Agent 子代理编排）

使用场景：
1. 作为 CLI 工具直接调用：aaf sample-apply [项目路径]
2. 被 aaf-sample-upgrade workflow 调用执行具体升级操作
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config_reader import AAFConfig, build_project, get_aaf_home, get_aaf_root, pull_latest, read_config


# 支持的单个项目类型
SUPPORTED_SAMPLE_TYPES = ["Template-AAF", "Template_Android", "Template-Empty"]


@dataclass
class FileDiff:
    """单个文件的差异"""

    file: str  # 相对路径
    field: str  # 配置项名
    current: str  # 当前值
    expected: str  # 期望值
    action: str = "update"  # update / copy / create

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "field": self.field,
            "current": self.current,
            "expected": self.expected,
            "action": self.action,
        }


@dataclass
class ProjectCheckResult:
    """单个项目的检查结果"""

    name: str
    path: str
    status: str = "ready"  # ready / dirty / not_found
    diffs: list[FileDiff] = field(default_factory=list)
    copy_files: list[str] = field(default_factory=list)  # 需要直接复制的文件

    @property
    def has_changes(self) -> bool:
        return len(self.diffs) > 0 or len(self.copy_files) > 0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.path,
            "status": self.status,
            "has_changes": self.has_changes,
            "diffs": [d.to_dict() for d in self.diffs],
            "copy_files": self.copy_files,
        }


@dataclass
class SampleCheckReport:
    """Sample 升级检查报告"""

    aaf_config: AAFConfig
    pull_status: str = ""
    projects: list[ProjectCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "pull_status": self.pull_status,
            "config": self.aaf_config.to_dict(),
            "projects": [p.to_dict() for p in self.projects],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """生成人类可读的检查报告（单个项目）"""
        if len(self.projects) != 1:
            return f"报告应包含1个项目，实际包含: {len(self.projects)}"
        
        proj = self.projects[0]
        
        lines = [
            "## AAF Sample 升级检查报告（单个项目）",
            "",
            f"项目: {proj.name}",
            f"路径: `{proj.path}`",
            f"AAF 拉取: {self.pull_status}",
            f"moduleVersionName: {self.aaf_config.module_version_name}",
            "",
        ]

        status_icon = {"ready": "🟢", "dirty": "🟡", "not_found": "🔴"}.get(proj.status, "⚪")
        lines.append(f"### {status_icon} 项目状态")
        lines.append("")

        if proj.status == "not_found":
            lines.append(f"⚠️ 路径不存在: `{proj.path}`")
        elif proj.status == "dirty":
            lines.append("⚠️ 有未提交的本地变更，跳过")
        elif not proj.has_changes:
            lines.append("✓ 已是最新，无需更新")
        else:
            if proj.diffs:
                lines.append("### 📝 配置变更")
                lines.append("| 文件 | 配置项 | 当前 | 期望 |")
                lines.append("|------|--------|------|------|")
                for d in proj.diffs:
                    lines.append(f"| {d.file} | {d.field} | {d.current} | {d.expected} |")
                lines.append("")
            if proj.copy_files:
                lines.append("### 📋 文件复制")
                lines.append(f"需要复制 {len(proj.copy_files)} 个文件:")
                for copy_file in proj.copy_files:
                    lines.append(f"- {copy_file}")
                lines.append("")

        total_changes = len(proj.diffs) + len(proj.copy_files)
        lines.append(f"**总计: {total_changes} 处变更**")
        return "\n".join(lines)


def sample_check(project_path: str | Path) -> SampleCheckReport:
    """检查单个 Template 项目与 AAF 最新配置的差异
    
    Args:
        project_path: 项目路径（绝对路径或相对路径）
    """
    proj_path = Path(project_path)
    aaf_root = get_aaf_root()

    # 拉取最新
    pull_status = pull_latest(aaf_root)

    # 读取配置
    aaf_config = read_config(aaf_root)

    report = SampleCheckReport(aaf_config=aaf_config, pull_status=pull_status)
    
    # 验证项目类型
    proj_name = proj_path.name
    if proj_name not in SUPPORTED_SAMPLE_TYPES:
        raise ValueError(f"不支持的项目类型: {proj_name}，仅支持: {SUPPORTED_SAMPLE_TYPES}")

    result = ProjectCheckResult(name=proj_name, path=str(proj_path))

    if not proj_path.exists():
        result.status = "not_found"
        report.projects.append(result)
        return report

    # 检查工作区是否干净
    git_status = subprocess.run(
        ["git", "status", "--short"],
        cwd=proj_path,
        capture_output=True,
        text=True,
    )
    if git_status.stdout.strip():
        result.status = "dirty"
        report.projects.append(result)
        return report

    # 按项目类型检查差异
    if proj_name == "Template-AAF":
        _check_template_aaf(proj_path, aaf_root, aaf_config, result)
    elif proj_name == "Template_Android":
        _check_template_android(proj_path, aaf_root, aaf_config, result)
    elif proj_name == "Template-Empty":
        _check_template_empty(proj_path, aaf_root, aaf_config, result)

    report.projects.append(result)
    return report


def _check_sdk_config(
    proj_path: Path, aaf_config: AAFConfig, result: ProjectCheckResult,
    use_app_min_sdk: bool = False,
) -> None:
    """检查 config.gradle 中的 SDK 配置

    Args:
        use_app_min_sdk: Template-Empty 使用 appMinSdkVersion 而非 libMinSdkVersion
    """
    config_file = proj_path / "config.gradle"
    if not config_file.exists():
        return

    content = config_file.read_text(encoding="utf-8")
    checks = [
        ("compileSdkVersion", aaf_config.compile_sdk_version),
        ("buildToolsVersion", aaf_config.build_tools_version),
        ("targetSdkVersion", aaf_config.target_sdk_version),
    ]

    # Template-Empty 使用 appMinSdkVersion
    if use_app_min_sdk:
        checks.append(("appMinSdkVersion", aaf_config.app_min_sdk_version))
    else:
        checks.append(("libMinSdkVersion", aaf_config.lib_min_sdk_version))

    for field_name, expected in checks:
        if not expected:
            continue
        current = _extract_value(content, field_name)
        if current and current != expected:
            result.diffs.append(FileDiff(
                file="config.gradle",
                field=field_name,
                current=current,
                expected=expected,
            ))


def _check_kotlin_gradle(proj_path: Path, aaf_config: AAFConfig, result: ProjectCheckResult) -> None:
    """检查 build.gradle 中的 kotlin/gradle 版本"""
    build_file = proj_path / "build.gradle"
    if not build_file.exists():
        return

    content = build_file.read_text(encoding="utf-8")

    # kotlin_version
    if aaf_config.kotlin_version:
        current = _extract_value(content, "kotlin_version")
        if not current:
            current = _extract_value(content, "ext.kotlin_version")
        if current and current != aaf_config.kotlin_version:
            result.diffs.append(FileDiff(
                file="build.gradle",
                field="kotlin_version",
                current=current,
                expected=aaf_config.kotlin_version,
            ))

    # gradle 插件版本
    if aaf_config.gradle_plugin_version:
        m = re.search(r"com\.android\.tools\.build:gradle:([^\s'\"]+)", content)
        if m and m.group(1) != aaf_config.gradle_plugin_version:
            result.diffs.append(FileDiff(
                file="build.gradle",
                field="gradle_plugin_version",
                current=m.group(1),
                expected=aaf_config.gradle_plugin_version,
            ))


def _check_gradle_wrapper(proj_path: Path, aaf_config: AAFConfig, result: ProjectCheckResult) -> None:
    """检查 gradle-wrapper.properties"""
    wrapper_file = proj_path / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if not wrapper_file.exists() or not aaf_config.gradle_distribution_url:
        return

    content = wrapper_file.read_text(encoding="utf-8")
    m = re.search(r"distributionUrl\s*=\s*(.+)", content)
    if m:
        current_url = m.group(1).strip().replace("\\:", ":")
        if current_url != aaf_config.gradle_distribution_url:
            result.diffs.append(FileDiff(
                file="gradle/wrapper/gradle-wrapper.properties",
                field="distributionUrl",
                current=current_url,
                expected=aaf_config.gradle_distribution_url,
            ))


def _check_aaf_dependencies(
    proj_path: Path,
    aaf_config: AAFConfig,
    result: ProjectCheckResult,
    dep_files: list[str] | None = None,
) -> None:
    """检查 AAF 依赖版本"""
    if dep_files is None:
        dep_files = ["dependencies.gradle"]

    for dep_file_name in dep_files:
        dep_file = proj_path / dep_file_name
        if not dep_file.exists():
            continue
        content = dep_file.read_text(encoding="utf-8")

        # 查找 com.bihe0832.android:xxx:version
        for m in re.finditer(r"com\.bihe0832\.android:([^:'\"\s]+):([^'\"\s$]+)", content):
            artifact_id = m.group(1)
            current_ver = m.group(2)
            # 跳过变量引用
            if current_ver.startswith("$") or current_ver.startswith("{"):
                continue
            latest_ver = aaf_config.module_versions.get(artifact_id, aaf_config.module_version_name)
            if current_ver != latest_ver:
                result.diffs.append(FileDiff(
                    file=dep_file_name,
                    field=f"dep:{artifact_id}",
                    current=current_ver,
                    expected=latest_ver,
                ))

        # 查找版本变量
        for m in re.finditer(r"(aaf\w*version\w*)\s*=\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE):
            var_name = m.group(1)
            current_ver = m.group(2)
            # 简单映射
            artifact_id = _var_to_artifact_simple(var_name)
            latest_ver = aaf_config.module_versions.get(artifact_id, aaf_config.module_version_name)
            if current_ver != latest_ver:
                result.diffs.append(FileDiff(
                    file=dep_file_name,
                    field=var_name,
                    current=current_ver,
                    expected=latest_ver,
                ))


def _check_compose_config(
    proj_path: Path, aaf_config: AAFConfig, result: ProjectCheckResult,
    build_file: str = "APPTest/build.gradle",
) -> None:
    """检查 APPTest/build.gradle 中的 Compose 配置和 AAF 依赖"""
    target_file = proj_path / build_file
    if not target_file.exists():
        return

    content = target_file.read_text(encoding="utf-8")

    # 检查 kotlinCompilerExtensionVersion（Compose Compiler 版本）
    if aaf_config.compose_compiler_version:
        m = re.search(r'kotlinCompilerExtensionVersion\s*[=:]\s*["\']([^"\']+)["\']', content)
        if m and m.group(1) != aaf_config.compose_compiler_version:
            result.diffs.append(FileDiff(
                file=build_file,
                field="kotlinCompilerExtensionVersion",
                current=m.group(1),
                expected=aaf_config.compose_compiler_version,
            ))

    # 检查 AAF 依赖版本
    for m in re.finditer(r"com\.bihe0832\.android:([^:'\"\ \s]+):([^'\"\ \s$]+)", content):
        artifact_id = m.group(1)
        current_ver = m.group(2)
        if current_ver.startswith("$") or current_ver.startswith("{"):
            continue
        latest_ver = aaf_config.module_versions.get(artifact_id, aaf_config.module_version_name)
        if current_ver != latest_ver:
            result.diffs.append(FileDiff(
                file=build_file,
                field=f"dep:{artifact_id}",
                current=current_ver,
                expected=latest_ver,
            ))


def _check_manifest_exported(proj_path: Path, result: ProjectCheckResult, manifest_rel: str) -> None:
    """检查 AndroidManifest.xml 中 LAUNCHER Activity 是否有 android:exported=true"""
    manifest_file = proj_path / manifest_rel
    if not manifest_file.exists():
        return

    content = manifest_file.read_text(encoding="utf-8")

    # 查找包含 LAUNCHER category 的 activity 块
    # 简单检查：如果有 LAUNCHER 但没有 exported="true"，标记需要修复
    if "android.intent.category.LAUNCHER" in content:
        # 查找 LAUNCHER 所在的 activity 块
        # 使用简单的正则检查是否有 exported
        launcher_pattern = re.compile(
            r'<activity[^>]*?>(.*?)</activity>',
            re.DOTALL,
        )
        for m in launcher_pattern.finditer(content):
            activity_block = m.group(0)
            if "android.intent.category.LAUNCHER" in activity_block:
                if 'android:exported="true"' not in activity_block:
                    result.diffs.append(FileDiff(
                        file=manifest_rel,
                        field="android:exported",
                        current="missing",
                        expected="true",
                        action="update",
                    ))
                break


def _check_template_aaf(proj_path: Path, aaf_root: Path, aaf_config: AAFConfig, result: ProjectCheckResult) -> None:
    """检查 Template-AAF"""
    _check_sdk_config(proj_path, aaf_config, result)
    _check_kotlin_gradle(proj_path, aaf_config, result)
    _check_gradle_wrapper(proj_path, aaf_config, result)
    _check_aaf_dependencies(proj_path, aaf_config, result)

    # APPTest/build.gradle — Compose 配置 + AAF 依赖
    _check_compose_config(proj_path, aaf_config, result)

    # AndroidManifest.xml — exported 属性
    _check_manifest_exported(proj_path, result, "APPTest/src/main/AndroidManifest.xml")

    # 需要直接复制的文件（Compose UI 代码）
    copy_pairs = [
        ("APPTest/src/main/java/com/bihe0832/android/test/module/DebugTempView.kt",
         "APPTest/src/main/java"),
        ("APPTest/src/main/java/com/bihe0832/android/test/module/DebugRouterView.kt",
         "APPTest/src/main/java"),
        ("APPTest/src/main/java/com/bihe0832/android/test/DebugMainActivity.kt",
         "APPTest/src/main/java"),
    ]
    for src_rel, _ in copy_pairs:
        src = aaf_root / src_rel
        dst = proj_path / src_rel
        if src.exists() and dst.exists():
            if src.read_text(encoding="utf-8") != dst.read_text(encoding="utf-8"):
                result.copy_files.append(src_rel)
        elif src.exists() and not dst.exists():
            result.copy_files.append(src_rel)


def _check_template_android(proj_path: Path, aaf_root: Path, aaf_config: AAFConfig, result: ProjectCheckResult) -> None:
    """检查 Template_Android"""
    _check_sdk_config(proj_path, aaf_config, result)
    _check_kotlin_gradle(proj_path, aaf_config, result)
    _check_gradle_wrapper(proj_path, aaf_config, result)

    # Application/build.gradle 中的 AAF 依赖
    _check_aaf_dependencies(proj_path, aaf_config, result, [
        "Application/build.gradle",
    ])

    # APPTest/build.gradle — Compose 配置 + AAF 依赖
    _check_compose_config(proj_path, aaf_config, result)

    # AndroidManifest.xml — exported 属性
    _check_manifest_exported(proj_path, result, "APPTest/src/main/AndroidManifest.xml")

    # 从 Template-AAF 复制的文件
    aaf_home = get_aaf_home()
    template_aaf = aaf_home / "Template-AAF"
    if template_aaf.exists():
        copy_sources = [
            "APPTest/src/main/java/com/bihe0832/android/test/module/DebugTempView.kt",
            "APPTest/src/main/java/com/bihe0832/android/test/module/DebugRouterView.kt",
            "APPTest/src/main/java/com/bihe0832/android/test/DebugMainActivity.kt",
        ]
        for src_rel in copy_sources:
            src = template_aaf / src_rel
            dst = proj_path / src_rel
            if src.exists() and dst.exists():
                if src.read_text(encoding="utf-8") != dst.read_text(encoding="utf-8"):
                    result.copy_files.append(src_rel)


def _check_template_empty(proj_path: Path, aaf_root: Path, aaf_config: AAFConfig, result: ProjectCheckResult) -> None:
    """检查 Template-Empty"""
    # Template-Empty 使用 appMinSdkVersion 而非 libMinSdkVersion
    _check_sdk_config(proj_path, aaf_config, result, use_app_min_sdk=True)
    _check_gradle_wrapper(proj_path, aaf_config, result)

    # App/build.gradle 中的 AAF 依赖
    _check_aaf_dependencies(proj_path, aaf_config, result, ["App/build.gradle"])

    # AndroidManifest.xml — exported 属性
    _check_manifest_exported(proj_path, result, "App/src/main/AndroidManifest.xml")


def sample_apply(project_path: str | Path, report: SampleCheckReport | None = None) -> dict[str, list[str]]:
    """执行单个 Sample 项目升级，返回 {项目名: [变更列表]}
    
    Args:
        project_path: 项目路径（绝对路径或相对路径）
        report: 可选的检查报告，如未提供则自动检查
    """
    proj_path = Path(project_path)
    
    # 验证项目类型
    proj_name = proj_path.name
    if proj_name not in SUPPORTED_SAMPLE_TYPES:
        raise ValueError(f"不支持的项目类型: {proj_name}，仅支持: {SUPPORTED_SAMPLE_TYPES}")

    if report is None:
        report = sample_check(project_path)

    results: dict[str, list[str]] = {}
    aaf_root = get_aaf_root()

    # 只处理单个项目
    if len(report.projects) != 1:
        raise ValueError(f"报告应包含1个项目，实际包含: {len(report.projects)}")
    
    proj = report.projects[0]
    
    if proj.status != "ready" or not proj.has_changes:
        results[proj.name] = [f"跳过（状态: {proj.status}，变更: {proj.has_changes})"]
        return results

    changes: list[str] = []

    # 先 git pull
    pull_result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=proj_path,
        capture_output=True,
        text=True,
    )
    if pull_result.returncode != 0:
        changes.append(f"⚠️ git pull 失败: {pull_result.stderr.strip()}")
        results[proj.name] = changes
        return results

    # 执行配置更新
    for diff in proj.diffs:
        target_file = proj_path / diff.file
        if not target_file.exists():
            changes.append(f"⚠️ 文件不存在: {diff.file}")
            continue

        content = target_file.read_text(encoding="utf-8")
        new_content = _apply_diff(content, diff)
        if new_content != content:
            target_file.write_text(new_content, encoding="utf-8")
            changes.append(f"✅ {diff.file}: {diff.field} {diff.current} → {diff.expected}")
        else:
            changes.append(f"⚠️ 未匹配: {diff.field} in {diff.file}")

    # 执行文件复制
    for copy_file in proj.copy_files:
        # 确定源文件
        src = aaf_root / copy_file
        if not src.exists():
            # 可能来自 Template-AAF
            aaf_home = get_aaf_home()
            src = aaf_home / "Template-AAF" / copy_file
        dst = proj_path / copy_file
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            changes.append(f"📋 复制: {copy_file}")
        else:
            changes.append(f"⚠️ 源文件不存在: {copy_file}")

    results[proj.name] = changes
    return results


def _apply_diff(content: str, diff: FileDiff) -> str:
    """应用单个差异到文件内容"""
    if diff.field == "android:exported":
        # AndroidManifest.xml — 为 LAUNCHER Activity 添加 exported="true"
        return _apply_manifest_exported(content)
    elif diff.field.startswith("dep:"):
        # 依赖版本替换
        artifact_id = diff.field[4:]
        old = f"com.bihe0832.android:{artifact_id}:{diff.current}"
        new = f"com.bihe0832.android:{artifact_id}:{diff.expected}"
        return content.replace(old, new)
    elif diff.field == "distributionUrl":
        # gradle wrapper URL
        escaped_expected = diff.expected.replace(":", "\\:")
        return re.sub(
            r"distributionUrl\s*=\s*.+",
            f"distributionUrl={escaped_expected}",
            content,
        )
    elif diff.field == "gradle_plugin_version":
        return content.replace(
            f"com.android.tools.build:gradle:{diff.current}",
            f"com.android.tools.build:gradle:{diff.expected}",
        )
    elif diff.field == "kotlinCompilerExtensionVersion":
        # Compose Compiler 版本替换
        return re.sub(
            rf'(kotlinCompilerExtensionVersion\s*[=:]\s*["\']){re.escape(diff.current)}(["\'])',
            rf'\g<1>{diff.expected}\2',
            content,
        )
    else:
        # 通用 key = value 替换
        patterns = [
            (rf'({re.escape(diff.field)}\s*=\s*["\']){re.escape(diff.current)}(["\'])',
             rf'\g<1>{diff.expected}\2'),
            (rf'({re.escape(diff.field)}\s*=\s*){re.escape(diff.current)}(\s)',
             rf'\g<1>{diff.expected}\2'),
        ]
        for pattern, replacement in patterns:
            new_content, count = re.subn(pattern, replacement, content)
            if count > 0:
                return new_content
        return content


def _apply_manifest_exported(content: str) -> str:
    """为 LAUNCHER Activity 添加 android:exported=\"true\""""
    # 查找包含 LAUNCHER 的 activity 块
    launcher_pattern = re.compile(
        r'(<activity[^>]*?)(>)(.*?android\.intent\.category\.LAUNCHER.*?</activity>)',
        re.DOTALL,
    )
    m = launcher_pattern.search(content)
    if m:
        activity_tag = m.group(1)
        if 'android:exported' not in activity_tag:
            # 在 activity 标签中添加 exported="true"
            new_tag = activity_tag + '\n            android:exported="true"'
            content = content[:m.start(1)] + new_tag + m.group(2) + m.group(3) + content[m.end():]
    return content


def _var_to_artifact_simple(var_name: str) -> str:
    """简单的变量名到 artifactId 映射"""
    mapping = {
        "aaf_version": "common-wrapper",
        "aaf_test_version": "common-debug",
        "aaf_screen_version": "lib-wrapper-screen",
        "aaf_router_version": "lib-router-compiler",
    }
    return mapping.get(var_name.lower(), "common-wrapper")


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
