"""AAF 发布前检查 - 自动化检查编译状态、版本号更新和模块完整性"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config_reader import get_aaf_root, read_config


@dataclass
class CheckItem:
    """单项检查结果"""

    name: str
    passed: bool
    message: str
    details: list[str] = field(default_factory=list)


@dataclass
class ReleaseReport:
    """发布检查报告"""

    checks: list[CheckItem] = field(default_factory=list)
    publish_command: str = ""

    @property
    def all_passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def summary(self) -> str:
        lines = ["\n## AAF 发布检查报告\n"]
        for c in self.checks:
            icon = "✅" if c.passed else "❌"
            lines.append(f"{icon} **{c.name}**: {c.message}")
            for d in c.details:
                lines.append(f"   - {d}")

        lines.append("")
        if self.all_passed:
            lines.append("🎉 所有检查通过，可以发布！")
            if self.publish_command:
                lines.append(f"\n## 发布命令\n\n```\n{self.publish_command}\n```")
        else:
            failed = [c.name for c in self.checks if not c.passed]
            lines.append(f"⛔ 有 {len(failed)} 项未通过: {', '.join(failed)}")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "all_passed": self.all_passed,
                "checks": [
                    {"name": c.name, "passed": c.passed, "message": c.message, "details": c.details}
                    for c in self.checks
                ],
                "publish_command": self.publish_command,
            },
            indent=2,
            ensure_ascii=False,
        )


def release_check(skip_build: bool = False) -> ReleaseReport:
    """执行完整的发布前检查"""
    aaf_root = get_aaf_root()
    report = ReleaseReport()

    # Step 1: 版本号检查
    report.checks.append(_check_version(aaf_root))

    # Step 2: 修改模块完整性检查
    report.checks.append(_check_develop_modules(aaf_root))

    # Step 3: 依赖配置变更检查
    report.checks.append(_check_dependency_changes(aaf_root))

    # Step 4: Git 状态检查
    report.checks.append(_check_git_status(aaf_root))

    # Step 5: 编译检查（可跳过）
    if not skip_build:
        report.checks.append(_check_build(aaf_root))
    else:
        report.checks.append(CheckItem(name="编译检查", passed=True, message="已跳过（--skip-build）"))

    # Step 6: 获取发布命令
    report.publish_command = _get_publish_command(aaf_root)

    return report


def _check_version(aaf_root: Path) -> CheckItem:
    """Step 1: 检查 moduleVersionName 是否已提升"""
    # 读取当前版本
    deps_gradle = aaf_root / "dependencies.gradle"
    if not deps_gradle.exists():
        return CheckItem(name="版本号检查", passed=False, message="dependencies.gradle 不存在")

    content = deps_gradle.read_text(encoding="utf-8")
    m = re.search(r'moduleVersionName\s*=\s*["\']([^"\']+)["\']', content)
    if not m:
        return CheckItem(name="版本号检查", passed=False, message="无法解析 moduleVersionName")

    current_version = m.group(1)

    # 获取最新 Tag_AAF_* tag
    result = subprocess.run(
        ["git", "tag", "--list", "Tag_AAF_*", "--sort=-v:refname"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    tags = result.stdout.strip().splitlines()

    if not tags:
        return CheckItem(
            name="版本号检查",
            passed=True,
            message=f"当前版本 {current_version}（无历史 Tag，首次发布）",
        )

    latest_tag = tags[0]
    # 从 Tag_AAF_x.y.z 提取版本号
    tag_version = latest_tag.replace("Tag_AAF_", "")

    if current_version == tag_version:
        return CheckItem(
            name="版本号检查",
            passed=False,
            message=f"版本号未提升！当前 {current_version} == 最新 Tag {latest_tag}",
            details=["Bug 修复: +0.0.1", "新功能: +0.1.0", "重大更新: +1.0.0"],
        )

    # 简单比较版本号
    if _version_gt(current_version, tag_version):
        return CheckItem(
            name="版本号检查",
            passed=True,
            message=f"版本已提升: {tag_version} → {current_version}",
        )
    else:
        return CheckItem(
            name="版本号检查",
            passed=False,
            message=f"版本号异常: 当前 {current_version} < 最新 Tag {tag_version}",
        )


def _check_develop_modules(aaf_root: Path) -> CheckItem:
    """Step 2: 检查修改模块是否都在 developModule 中"""
    # 获取最新 Tag
    result = subprocess.run(
        ["git", "tag", "--list", "Tag_AAF_*", "--sort=-v:refname"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    tags = result.stdout.strip().splitlines()
    if not tags:
        return CheckItem(name="模块完整性", passed=True, message="无历史 Tag，跳过检查")

    latest_tag = tags[0]

    # 获取自上次 Tag 以来修改的目录（模块）
    result = subprocess.run(
        ["git", "diff", "--name-only", latest_tag, "HEAD"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return CheckItem(name="模块完整性", passed=False, message=f"git diff 失败: {result.stderr.strip()}")

    changed_files = result.stdout.strip().splitlines()
    # 提取顶层目录作为模块名
    changed_modules = set()
    for f in changed_files:
        parts = f.split("/")
        if len(parts) > 1:
            module = parts[0]
            # 排除非模块目录
            if not module.startswith(".") and module not in ("gradle", "buildSrc", "config"):
                changed_modules.add(module)

    # 排除 APP* 和 Base* 开头的模块
    changed_modules = {m for m in changed_modules if not m.startswith("APP") and not m.startswith("Base")}

    if not changed_modules:
        return CheckItem(name="模块完整性", passed=True, message="无需发布的模块变更")

    # 读取 developModule
    deps_gradle = aaf_root / "dependencies.gradle"
    content = deps_gradle.read_text(encoding="utf-8")
    # 匹配 ext.developModule = ["Module1", "Module2", ...]
    m = re.search(r'developModule\s*=\s*\[([^\]]+)\]', content, re.DOTALL)
    if not m:
        return CheckItem(
            name="模块完整性",
            passed=False,
            message="无法解析 ext.developModule",
        )

    develop_modules_str = m.group(1)
    develop_modules = set(re.findall(r'"(\w+)"', develop_modules_str))

    # 检查差集
    missing = changed_modules - develop_modules
    if missing:
        return CheckItem(
            name="模块完整性",
            passed=False,
            message=f"有 {len(missing)} 个修改模块未加入 developModule",
            details=[f"{m} — 有变更但未在发布列表中" for m in sorted(missing)],
        )

    return CheckItem(
        name="模块完整性",
        passed=True,
        message=f"所有 {len(changed_modules)} 个修改模块均在 developModule 中",
    )


def _check_dependency_changes(aaf_root: Path) -> CheckItem:
    """Step 3: 检查依赖配置变更是否影响了未加入发布列表的模块"""
    # 获取最新 Tag
    result = subprocess.run(
        ["git", "tag", "--list", "Tag_AAF_*", "--sort=-v:refname"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    tags = result.stdout.strip().splitlines()
    if not tags:
        return CheckItem(name="依赖配置检查", passed=True, message="无历史 Tag，跳过检查")

    latest_tag = tags[0]

    # 检查 dependencies_aaf_config.gradle 是否有变更
    config_file = "dependencies_aaf_config.gradle"
    result = subprocess.run(
        ["git", "diff", latest_tag, "HEAD", "--", config_file],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )

    if not result.stdout.strip():
        return CheckItem(name="依赖配置检查", passed=True, message="依赖配置无变更")

    # 解析变更的 key
    diff_content = result.stdout
    changed_keys = set()
    for line in diff_content.splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            # 匹配 "keyName" : "value" 格式
            m = re.search(r'"(\w+)"\s*:', line)
            if m:
                changed_keys.add(m.group(1))

    if not changed_keys:
        return CheckItem(name="依赖配置检查", passed=True, message="依赖配置有变更但无 key 变化")

    # 查找引用这些 key 的模块（扫描所有 build.gradle）
    affected_modules = set()
    for build_gradle in aaf_root.glob("*/build.gradle"):
        module_name = build_gradle.parent.name
        content = build_gradle.read_text(encoding="utf-8")
        for key in changed_keys:
            if key in content:
                affected_modules.add(module_name)
                break

    # 排除 APP* 和 Base*
    affected_modules = {m for m in affected_modules if not m.startswith("APP") and not m.startswith("Base")}

    if not affected_modules:
        return CheckItem(
            name="依赖配置检查",
            passed=True,
            message=f"依赖配置有 {len(changed_keys)} 个 key 变更，无受影响模块",
        )

    # 检查受影响模块是否在 developModule 中
    deps_gradle = aaf_root / "dependencies.gradle"
    content = deps_gradle.read_text(encoding="utf-8")
    m = re.search(r'developModule\s*=\s*\[([^\]]+)\]', content, re.DOTALL)
    develop_modules = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()

    missing = affected_modules - develop_modules
    if missing:
        return CheckItem(
            name="依赖配置检查",
            passed=False,
            message=f"依赖变更影响 {len(affected_modules)} 个模块，{len(missing)} 个未加入发布列表",
            details=[
                f"变更 key: {', '.join(sorted(changed_keys))}",
                *[f"{m} — 受影响但未在发布列表中" for m in sorted(missing)],
            ],
        )

    return CheckItem(
        name="依赖配置检查",
        passed=True,
        message=f"依赖变更影响 {len(affected_modules)} 个模块，均已在发布列表中",
    )


def _check_git_status(aaf_root: Path) -> CheckItem:
    """Step 4: 检查 Git 工作区状态"""
    # 检查是否有未提交的变更
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    uncommitted = result.stdout.strip()

    # 获取当前分支
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    branch = result.stdout.strip()

    details = []
    passed = True

    if uncommitted:
        passed = False
        dirty_count = len(uncommitted.splitlines())
        details.append(f"有 {dirty_count} 个未提交的文件")

    if branch and branch not in ("master", "main", "develop"):
        details.append(f"当前分支: {branch}（非主分支，请确认）")

    message = f"分支: {branch}" if not uncommitted else f"分支: {branch}，工作区不干净"
    return CheckItem(name="Git 状态", passed=passed, message=message, details=details)


def _check_build(aaf_root: Path) -> CheckItem:
    """Step 5: 执行编译检查"""
    gradlew = aaf_root / "gradlew"
    if not gradlew.exists():
        return CheckItem(name="编译检查", passed=False, message="gradlew 不存在")

    result = subprocess.run(
        ["./gradlew", "clean", "assembleDebug"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
        timeout=600,  # 10 分钟超时
    )

    if result.returncode == 0:
        return CheckItem(name="编译检查", passed=True, message="BUILD SUCCESSFUL")
    else:
        # 提取最后几行错误信息
        stderr_lines = result.stderr.strip().splitlines()
        stdout_lines = result.stdout.strip().splitlines()
        error_lines = stderr_lines[-5:] if stderr_lines else stdout_lines[-5:]
        return CheckItem(
            name="编译检查",
            passed=False,
            message="BUILD FAILED",
            details=error_lines,
        )


def _get_publish_command(aaf_root: Path) -> str:
    """获取发布命令"""
    gradlew = aaf_root / "gradlew"
    if not gradlew.exists():
        return ""

    result = subprocess.run(
        ["./gradlew", "showPublishCommand"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode == 0:
        # 提取输出中的命令部分
        output = result.stdout.strip()
        # 通常输出在 > Task :showPublishCommand 之后
        lines = output.splitlines()
        cmd_lines = []
        capture = False
        skip_patterns = ("Deprecated Gradle", "You can use", "For more on this", "BUILD SUCCESSFUL", "actionable task")
        for line in lines:
            if "showPublishCommand" in line:
                capture = True
                continue
            if capture and line.strip() and not line.startswith(">"):
                if not any(p in line for p in skip_patterns):
                    cmd_lines.append(line.strip())
            elif capture and line.startswith(">"):
                break
        return "\n".join(cmd_lines) if cmd_lines else ""
    return ""


def _version_gt(v1: str, v2: str) -> bool:
    """比较版本号 v1 > v2"""
    try:
        parts1 = [int(x) for x in v1.split(".")]
        parts2 = [int(x) for x in v2.split(".")]
        return parts1 > parts2
    except (ValueError, AttributeError):
        return v1 > v2
