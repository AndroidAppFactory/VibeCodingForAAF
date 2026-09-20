"""AAF 配置读取器 - 从 AndroidAppFactory 源码提取结构化配置"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AAFConfig:
    """AAF 框架配置数据"""

    # SDK 配置
    compile_sdk_version: str = ""
    build_tools_version: str = ""
    lib_min_sdk_version: str = ""
    app_min_sdk_version: str = ""
    target_sdk_version: str = ""

    # 构建工具版本
    kotlin_version: str = ""
    gradle_plugin_version: str = ""
    gradle_distribution_url: str = ""
    compose_compiler_version: str = ""

    # 模块默认版本
    module_version_name: str = ""

    # 各模块精确版本 {artifactId: version}
    module_versions: dict[str, str] = field(default_factory=dict)

    # 各模块所在配置文件 {artifactId: filename}
    module_sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "sdk": {
                "compileSdkVersion": self.compile_sdk_version,
                "buildToolsVersion": self.build_tools_version,
                "libMinSdkVersion": self.lib_min_sdk_version,
                "appMinSdkVersion": self.app_min_sdk_version,
                "targetSdkVersion": self.target_sdk_version,
            },
            "build_tools": {
                "kotlin_version": self.kotlin_version,
                "gradle_plugin_version": self.gradle_plugin_version,
                "gradle_distribution_url": self.gradle_distribution_url,
                "compose_compiler_version": self.compose_compiler_version,
            },
            "module_version_name": self.module_version_name,
            "modules": {
                aid: {"version": ver, "source": self.module_sources.get(aid, "unknown")}
                for aid, ver in self.module_versions.items()
            },
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


# 全局 .env 唯一固定位置（遵循 zixie_workspace.mdc）
ZIXIEKIT_ENV = Path.home() / ".zixiekit" / ".env"


def get_aaf_home() -> Path:
    """获取 AAF_HOME 路径，使用 global_env.py 的功能"""
    from pathlib import Path
    
    # 使用 global_env.py 的功能获取 AAF_HOME
    from zixiekit.core.global_env import get_global_var
    
    aaf_home = get_global_var("AAF_HOME")
    if not aaf_home:
        raise RuntimeError(
            f"未设置 AAF_HOME 环境变量，请在 ~/.zixiekit/.env 中配置，"
            f"例如: AAF_HOME=/path/to/your/aaf"
        )
    
    path = Path(aaf_home).resolve()
    if not path.exists():
        raise RuntimeError(f"AAF_HOME 目录不存在: {path}")
    return path


def get_aaf_root() -> Path:
    """获取 AndroidAppFactory 项目根目录"""
    aaf_home = get_aaf_home()
    aaf_root = aaf_home / "AndroidAppFactory"
    if not aaf_root.exists():
        raise RuntimeError(f"AndroidAppFactory 项目不存在: {aaf_root}")
    return aaf_root


def get_zixiekit_home() -> Path:
    """获取 ZixieKit 根目录，使用 global_env.py 的功能"""
    from pathlib import Path
    
    # 直接使用 global_env.py 的功能获取 ZIXIEKIT_HOME
    from zixiekit.core.global_env import get_global_var
    
    zk_home = get_global_var("ZIXIEKIT_HOME")
    if not zk_home:
        raise RuntimeError(
            "无法获取 ZIXIEKIT_HOME 环境变量。"
            "请在 ~/.zixiekit/.env 中配置 ZIXIEKIT_HOME=<ZixieKit 仓库路径>"
        )
    
    zk_path = Path(zk_home).resolve()
    if not zk_path.exists():
        raise RuntimeError(f"ZixieKit 仓库路径不存在: {zk_path}")
    
    return zk_path


def pull_latest(aaf_root: Path, quiet: bool = False) -> str:
    """拉取 AAF 最新代码，返回状态信息"""
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        return "跳过拉取（有本地变更）"

    result = subprocess.run(
        ["git", "pull", "--rebase"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return f"拉取失败: {result.stderr.strip()}"
    return "已拉取最新代码"


def read_config(aaf_root: Path) -> AAFConfig:
    """读取 AAF 框架的完整配置"""
    config = AAFConfig()

    # 1. 读取 config.gradle
    config_gradle = aaf_root / "config.gradle"
    if config_gradle.exists():
        content = config_gradle.read_text(encoding="utf-8")
        config.compile_sdk_version = _extract_gradle_value(content, "compileSdkVersion")
        config.build_tools_version = _extract_gradle_value(content, "buildToolsVersion")
        config.lib_min_sdk_version = _extract_gradle_value(content, "libMinSdkVersion")
        config.app_min_sdk_version = _extract_gradle_value(content, "appMinSdkVersion")
        config.target_sdk_version = _extract_gradle_value(content, "targetSdkVersion")
        config.kotlin_version = _extract_gradle_value(content, "kotlin_version")

    # 2. 读取 build.gradle（Gradle 插件版本）
    build_gradle = aaf_root / "build.gradle"
    if build_gradle.exists():
        content = build_gradle.read_text(encoding="utf-8")
        m = re.search(r"com\.android\.tools\.build:gradle:([^\s'\"]+)", content)
        if m:
            config.gradle_plugin_version = m.group(1)
        # 也可能是 id 'com.android.application' version 'x.x.x'
        if not config.gradle_plugin_version:
            m = re.search(r"id\s+['\"]com\.android\.application['\"]\s+version\s+['\"]([^'\"]+)", content)
            if m:
                config.gradle_plugin_version = m.group(1)

    # 3. 读取 gradle-wrapper.properties
    wrapper_props = aaf_root / "gradle" / "wrapper" / "gradle-wrapper.properties"
    if wrapper_props.exists():
        content = wrapper_props.read_text(encoding="utf-8")
        m = re.search(r"distributionUrl\s*=\s*(.+)", content)
        if m:
            config.gradle_distribution_url = m.group(1).strip().replace("\\:", ":")

    # 4. 读取 dependencies.gradle（moduleVersionName）
    deps_gradle = aaf_root / "dependencies.gradle"
    if deps_gradle.exists():
        content = deps_gradle.read_text(encoding="utf-8")
        config.module_version_name = _extract_gradle_value(content, "moduleVersionName")

    # 5. 读取 APPTest/build.gradle（Compose Compiler）
    apptest_gradle = aaf_root / "APPTest" / "build.gradle"
    if apptest_gradle.exists():
        content = apptest_gradle.read_text(encoding="utf-8")
        m = re.search(r"kotlinCompilerExtensionVersion\s*[=:]\s*['\"]([^'\"]+)", content)
        if m:
            config.compose_compiler_version = m.group(1)

    # 6. 读取所有 dependencies_*.gradle 中的模块版本
    for dep_file in sorted(aaf_root.glob("dependencies_*.gradle")):
        _parse_dependency_file(dep_file, config)

    return config


def _extract_gradle_value(content: str, key: str) -> str:
    """从 Gradle 文件中提取 key = value 或 key : value"""
    # 匹配 key = "value" 或 key = 'value' 或 key = value
    patterns = [
        rf'{key}\s*=\s*["\']([^"\']+)["\']',
        rf'{key}\s*=\s*(\d+)',
        rf'"{key}"\s*:\s*["\']([^"\']+)["\']',
        rf"'{key}'\s*:\s*['\"]([^'\"]+)['\"]",
    ]
    for pattern in patterns:
        m = re.search(pattern, content)
        if m:
            return m.group(1)
    return ""


def _parse_dependency_file(dep_file: Path, config: AAFConfig) -> None:
    """解析 dependencies_*.gradle 文件，提取模块版本"""
    content = dep_file.read_text(encoding="utf-8")
    filename = dep_file.name

    # 匹配模式：
    # "ModuleName" : [
    #     "version"    : "x.x.x",
    #     "artifactId" : "artifact-name",
    # ]
    # 使用多行匹配
    blocks = re.finditer(
        r'"(\w+)"\s*:\s*\[([^\]]+)\]',
        content,
        re.DOTALL,
    )
    for block in blocks:
        block_content = block.group(2)
        artifact_match = re.search(r'"artifactId"\s*:\s*"([^"]+)"', block_content)
        version_match = re.search(r'"version"\s*:\s*"([^"]+)"', block_content)
        if artifact_match and version_match:
            artifact_id = artifact_match.group(1)
            version = version_match.group(1)
            config.module_versions[artifact_id] = version
            config.module_sources[artifact_id] = filename


def find_project(project_name: str) -> Path:
    """在 AAF_HOME 下查找指定项目"""
    aaf_home = get_aaf_home()
    project_path = aaf_home / project_name
    if project_path.exists():
        return project_path
    # 模糊匹配
    candidates = [d for d in aaf_home.iterdir() if d.is_dir() and project_name.lower() in d.name.lower()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        raise RuntimeError(f"找到多个匹配项目: {names}，请指定完整名称")
    raise RuntimeError(f"在 {aaf_home} 下找不到项目: {project_name}")


def list_projects() -> list[dict[str, str]]:
    """列出 AAF_HOME 下所有项目"""
    aaf_home = get_aaf_home()
    projects = []
    known = ["AndroidAppFactory", "AndroidAppFactory-Doc", "Template-AAF", "Template_Android", "Template-Empty"]
    for name in known:
        path = aaf_home / name
        status = "✓" if path.exists() else "不存在"
        projects.append({"name": name, "path": str(path), "status": status})
    return projects


def build_project(project_path: Path) -> tuple[bool, str]:
    """编译 Android 项目，返回 (成功, 输出)"""
    gradlew = project_path / "gradlew"
    if not gradlew.exists():
        return False, "gradlew 不存在"

    result = subprocess.run(
        ["./gradlew", "clean", "assembleDebug"],
        cwd=project_path,
        capture_output=True,
        text=True,
        timeout=600,  # 10 分钟超时
    )
    if result.returncode == 0:
        return True, "编译成功"
    else:
        # 提取关键错误信息（最后 50 行）
        error_lines = result.stdout.splitlines()[-50:] + result.stderr.splitlines()[-20:]
        return False, "\n".join(error_lines)
