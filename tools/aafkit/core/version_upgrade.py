"""AAF 版本升级逻辑 - 扫描项目依赖并对比最新版本"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config_reader import AAFConfig, get_aaf_root, pull_latest, read_config


@dataclass
class VersionDiff:
    """单个模块的版本差异"""

    variable: str  # 版本变量名（如 aaf_version）或 "(硬编码)"
    artifact_id: str  # 模块 artifactId
    current: str  # 当前版本
    latest: str  # 最新版本
    file: str  # 定义所在文件
    needs_upgrade: bool = False

    def to_dict(self) -> dict:
        return {
            "variable": self.variable,
            "artifact_id": self.artifact_id,
            "current": self.current,
            "latest": self.latest,
            "file": self.file,
            "needs_upgrade": self.needs_upgrade,
        }


@dataclass
class ApplyResult:
    """版本升级执行结果"""
    
    changed_files: list[str] = field(default_factory=list)  # 修改的文件路径
    changes: list[str] = field(default_factory=list)  # 变更描述
    
    def to_dict(self) -> dict:
        return {
            "changed_files": self.changed_files,
            "changes": self.changes,
        }


@dataclass
class VersionReport:
    """版本检查报告"""

    project_name: str
    project_path: str
    aaf_config: AAFConfig
    diffs: list[VersionDiff] = field(default_factory=list)
    pull_status: str = ""

    @property
    def has_upgrades(self) -> bool:
        return any(d.needs_upgrade for d in self.diffs)

    def to_dict(self) -> dict:
        return {
            "project": self.project_name,
            "project_path": self.project_path,
            "pull_status": self.pull_status,
            "upgrades_available": self.has_upgrades,
            "diffs": [d.to_dict() for d in self.diffs],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """生成人类可读的升级报告"""
        lines = [
            f"## AAF 版本升级报告 — {self.project_name}",
            "",
            f"项目路径: `{self.project_path}`",
            f"AAF 拉取: {self.pull_status}",
            "",
            "| 版本变量 | 对应模块 | 当前版本 | 最新版本 | 操作 |",
            "|---------|---------|---------|---------|------|",
        ]
        for d in self.diffs:
            action = "⬆️ 升级" if d.needs_upgrade else "✓ 保持"
            lines.append(f"| {d.variable} | {d.artifact_id} | {d.current} | {d.latest} | {action} |")

        upgrade_count = sum(1 for d in self.diffs if d.needs_upgrade)
        lines.append("")
        lines.append(f"**共 {len(self.diffs)} 个模块，{upgrade_count} 个需要升级**")
        return "\n".join(lines)


def version_check(project_path: str | Path) -> VersionReport:
    """检查项目的 AAF 依赖版本，返回升级报告
    
    Args:
        project_path: 项目路径（绝对路径或相对路径）
    """
    # 1. 确定项目路径
    proj_path = Path(project_path).resolve()
    if not proj_path.exists():
        raise RuntimeError(f"项目路径不存在: {proj_path}")

    # 2. 拉取 AAF 最新代码
    aaf_root = get_aaf_root()
    pull_status = pull_latest(aaf_root)

    # 3. 读取 AAF 最新配置
    aaf_config = read_config(aaf_root)

    # 4. 扫描项目中的 AAF 依赖
    report = VersionReport(
        project_name=proj_path.name,
        project_path=str(proj_path),
        aaf_config=aaf_config,
        pull_status=pull_status,
    )

    # 扫描 config.gradle 或 dependencies_aaf_config.gradle 中的版本变量
    _scan_version_variables(proj_path, aaf_config, report)

    # 扫描硬编码的 AAF 依赖
    _scan_hardcoded_deps(proj_path, aaf_config, report)

    return report


def _scan_version_variables(project_path: Path, aaf_config: AAFConfig, report: VersionReport) -> None:
    """扫描项目中的版本变量引用"""
    # 查找 config.gradle 或 dependencies_aaf_config.gradle
    candidates = [
        project_path / "config.gradle",
        project_path / "dependencies_aaf_config.gradle",
    ]

    for config_file in candidates:
        if not config_file.exists():
            continue
        content = config_file.read_text(encoding="utf-8")

        # 匹配 aaf_xxx_version = 'x.x.x' 或 aaf_version = 'x.x.x'
        for m in re.finditer(r"(aaf\w*version\w*)\s*=\s*['\"]([^'\"]+)['\"]", content, re.IGNORECASE):
            var_name = m.group(1)
            current_ver = m.group(2)

            # 根据变量名推断对应的 artifactId
            artifact_id = _variable_to_artifact(var_name, project_path)
            latest_ver = _find_latest_version(artifact_id, aaf_config)

            report.diffs.append(VersionDiff(
                variable=var_name,
                artifact_id=artifact_id,
                current=current_ver,
                latest=latest_ver,
                file=config_file.name,
                needs_upgrade=(current_ver != latest_ver),
            ))


def _scan_hardcoded_deps(project_path: Path, aaf_config: AAFConfig, report: VersionReport) -> None:
    """扫描硬编码的 com.bihe0832.android:xxx:version 依赖"""
    # 已经通过变量扫描到的 artifactId
    scanned_artifacts = {d.artifact_id for d in report.diffs}

    # 扫描所有 .gradle 文件
    for gradle_file in project_path.rglob("*.gradle"):
        if not gradle_file.is_file():
            continue
        if ".gradle/" in str(gradle_file) or "/build/" in str(gradle_file):
            continue
        content = gradle_file.read_text(encoding="utf-8")

        for m in re.finditer(
            r"com\.bihe0832\.android:([^:'\"\s]+):([^'\"\s]+)",
            content,
        ):
            artifact_id = m.group(1)
            current_ver = m.group(2)

            # 跳过变量引用（如 $aaf_version）
            if current_ver.startswith("$") or current_ver.startswith("{"):
                continue

            # 跳过已扫描的
            if artifact_id in scanned_artifacts:
                continue
            scanned_artifacts.add(artifact_id)

            latest_ver = _find_latest_version(artifact_id, aaf_config)
            report.diffs.append(VersionDiff(
                variable="(硬编码)",
                artifact_id=artifact_id,
                current=current_ver,
                latest=latest_ver,
                file=str(gradle_file.relative_to(project_path)),
                needs_upgrade=(current_ver != latest_ver),
            ))


def _variable_to_artifact(var_name: str, project_path: Path) -> str:
    """根据版本变量名从项目 gradle 文件中动态查找对应的 artifactId
    
    扫描项目中所有 gradle 文件，找出变量被哪个 com.bihe0832.android:xxx 引用。
    支持格式: ${project.var_name}, ${var_name}, ${ext.var_name}, $project.var_name, $var_name
    """
    # 支持的变量引用格式
    var_patterns = [
        rf"com\.bihe0832\.android:([^:]+):\$\{{project\.{re.escape(var_name)}\}}",
        rf"com\.bihe0832\.android:([^:]+):\$\{{ext\.{re.escape(var_name)}\}}",
        rf"com\.bihe0832\.android:([^:]+):\$\{{{re.escape(var_name)}\}}",
        rf"com\.bihe0832\.android:([^:]+):\$project\.{re.escape(var_name)}\b",
        rf"com\.bihe0832\.android:([^:]+):\$ext\.{re.escape(var_name)}\b",
        rf"com\.bihe0832\.android:([^:]+):\${re.escape(var_name)}\b",
    ]

    # 扫描项目中所有 gradle 文件
    for gradle_file in project_path.rglob("*.gradle"):
        if not gradle_file.is_file():
            continue
        if ".gradle/" in str(gradle_file) or "/build/" in str(gradle_file):
            continue
        content = gradle_file.read_text(encoding="utf-8")
        for pattern in var_patterns:
            m = re.search(pattern, content)
            if m:
                return m.group(1)

    return f"unknown({var_name})"


def _find_latest_version(artifact_id: str, aaf_config: AAFConfig) -> str:
    """从 AAF 配置中查找模块最新版本"""
    if artifact_id in aaf_config.module_versions:
        return aaf_config.module_versions[artifact_id]
    # fallback 到 moduleVersionName
    return aaf_config.module_version_name


def version_apply(project_path: str | Path, report: VersionReport | None = None) -> ApplyResult:
    """执行版本号替换，返回变更结果
    
    Args:
        project_path: 项目路径（绝对路径或相对路径）
        report: 可选的版本检查报告，如未提供则自动检查
    """
    proj_path = Path(project_path).resolve()
    if not proj_path.exists():
        raise RuntimeError(f"项目路径不存在: {proj_path}")

    if report is None:
        report = version_check(proj_path)

    result = ApplyResult()
    
    if not report.has_upgrades:
        result.changes.append("无需升级，所有版本已是最新")
        return result

    project_path = Path(report.project_path)

    for diff in report.diffs:
        if not diff.needs_upgrade:
            continue

        target_file = project_path / diff.file
        if not target_file.exists():
            result.changes.append(f"⚠️ 文件不存在: {diff.file}")
            continue

        content = target_file.read_text(encoding="utf-8")

        if diff.variable == "(硬编码)":
            # 替换硬编码版本
            old = f"com.bihe0832.android:{diff.artifact_id}:{diff.current}"
            new = f"com.bihe0832.android:{diff.artifact_id}:{diff.latest}"
            if old in content:
                content = content.replace(old, new)
                target_file.write_text(content, encoding="utf-8")
                result.changed_files.append(str(target_file.relative_to(project_path)))
                result.changes.append(f"✅ {diff.file}: {diff.artifact_id} {diff.current} → {diff.latest}")
            else:
                result.changes.append(f"⚠️ 未找到: {old}")
        else:
            # 替换版本变量
            pattern = rf"({re.escape(diff.variable)}\s*=\s*['\"]){re.escape(diff.current)}(['\"])"
            new_content, count = re.subn(pattern, rf"\g<1>{diff.latest}\2", content)
            if count > 0:
                target_file.write_text(new_content, encoding="utf-8")
                result.changed_files.append(str(target_file.relative_to(project_path)))
                result.changes.append(f"✅ {diff.file}: {diff.variable} {diff.current} → {diff.latest}")
            else:
                result.changes.append(f"⚠️ 未匹配: {diff.variable}={diff.current} in {diff.file}")

    return result


def generate_commit_message(report: VersionReport) -> str:
    """生成提交信息"""
    upgrades = [d for d in report.diffs if d.needs_upgrade]
    if not upgrades:
        return ""

    subject = f"chore(deps): 升级 {report.project_name} AAF 依赖版本"
    lines = [subject, ""]
    for d in upgrades:
        label = d.artifact_id if d.variable == "(硬编码)" else d.variable
        lines.append(f"- {label}: {d.current} → {d.latest}")

    return "\n".join(lines)
