"""AAF 文档生成辅助 - 提取模块元信息供 LLM 生成文档"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .config_reader import get_aaf_home, get_aaf_root, read_config


@dataclass
class PublicAPI:
    """公共 API 信息"""

    class_name: str
    file_path: str  # 相对路径
    methods: list[str] = field(default_factory=list)  # 方法签名列表


@dataclass
class ModuleInfo:
    """模块元信息"""

    module_name: str  # 模块目录名（如 LibAudio）
    artifact_id: str  # Maven artifactId
    version: str  # 当前版本
    source_file: str  # 来源配置文件
    module_type: str  # lib / common / services 等
    dependencies: list[str] = field(default_factory=list)  # 依赖列表
    source_files: list[str] = field(default_factory=list)  # 源文件列表
    public_apis: list[PublicAPI] = field(default_factory=list)  # 公共 API
    doc_path: str = ""  # 文档应写入的路径
    doc_exists: bool = False  # 文档是否已存在

    def to_dict(self) -> dict:
        return {
            "module_name": self.module_name,
            "artifact_id": self.artifact_id,
            "version": self.version,
            "source_file": self.source_file,
            "module_type": self.module_type,
            "dependencies": self.dependencies,
            "source_files": self.source_files,
            "public_apis": [
                {"class_name": api.class_name, "file_path": api.file_path, "methods": api.methods}
                for api in self.public_apis
            ],
            "doc_path": self.doc_path,
            "doc_exists": self.doc_exists,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        """生成人类可读的模块信息摘要"""
        lines = [
            f"## 模块信息 — {self.module_name}",
            "",
            f"| 字段 | 值 |",
            f"|------|-----|",
            f"| artifactId | `{self.artifact_id}` |",
            f"| 版本 | {self.version} |",
            f"| 类型 | {self.module_type} |",
            f"| 来源 | {self.source_file} |",
            f"| 源文件数 | {len(self.source_files)} |",
            f"| 公共类数 | {len(self.public_apis)} |",
            f"| 文档路径 | `{self.doc_path}` |",
            f"| 文档已存在 | {'是' if self.doc_exists else '否'} |",
            "",
        ]

        if self.dependencies:
            lines.append("### 依赖")
            for dep in self.dependencies:
                lines.append(f"- `{dep}`")
            lines.append("")

        if self.public_apis:
            lines.append(f"### 公共 API（{len(self.public_apis)} 个类）")
            lines.append("")
            for api in self.public_apis:
                lines.append(f"#### `{api.class_name}`")
                lines.append(f"文件: `{api.file_path}`")
                if api.methods:
                    lines.append("")
                    for method in api.methods[:20]:  # 最多展示 20 个方法
                        lines.append(f"- `{method}`")
                    if len(api.methods) > 20:
                        lines.append(f"- ... 还有 {len(api.methods) - 20} 个方法")
                lines.append("")

        return "\n".join(lines)


@dataclass
class UpdateInfo:
    """增量更新信息"""

    last_tag: str
    changed_modules: list[str]  # 有变更的模块列表
    module_changes: dict[str, list[str]] = field(default_factory=dict)  # {模块: [变更文件]}

    def to_dict(self) -> dict:
        return {
            "last_tag": self.last_tag,
            "changed_modules": self.changed_modules,
            "module_changes": self.module_changes,
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary(self) -> str:
        lines = [
            "## 增量变更信息",
            "",
            f"上次 Tag: `{self.last_tag}`",
            f"变更模块数: {len(self.changed_modules)}",
            "",
        ]
        if self.changed_modules:
            lines.append("| 模块 | 变更文件数 |")
            lines.append("|------|-----------|")
            for mod in self.changed_modules:
                count = len(self.module_changes.get(mod, []))
                lines.append(f"| {mod} | {count} |")
        else:
            lines.append("无变更模块。")
        return "\n".join(lines)


def get_module_info(module_name: str) -> ModuleInfo:
    """获取指定模块的完整元信息"""
    aaf_root = get_aaf_root()
    aaf_home = get_aaf_home()
    doc_root = aaf_home / "AndroidAppFactory-Doc"

    config = read_config(aaf_root)

    # 查找模块
    info = ModuleInfo(module_name=module_name, artifact_id="", version="", source_file="", module_type="")

    # 从 config 中查找 artifactId 和版本
    # 先尝试精确匹配模块名
    _find_module_in_config(aaf_root, module_name, info)

    # 如果没找到，尝试通过 artifactId 反查
    if not info.artifact_id:
        # 尝试将模块名转为 artifactId 格式
        possible_artifact = _module_name_to_artifact(module_name)
        if possible_artifact in config.module_versions:
            info.artifact_id = possible_artifact
            info.version = config.module_versions[possible_artifact]
            info.source_file = config.module_sources.get(possible_artifact, "")

    # 扫描源文件
    module_dir = aaf_root / module_name
    if module_dir.exists():
        info.source_files = _scan_source_files(module_dir)
        info.public_apis = _extract_public_apis(module_dir)

    # 确定文档路径
    info.doc_path = _determine_doc_path(info)

    # 检查文档是否已存在
    if doc_root.exists() and info.doc_path:
        full_doc_path = doc_root / info.doc_path
        info.doc_exists = full_doc_path.exists()

    return info


def get_update_info(module: str | None = None) -> UpdateInfo:
    """获取增量更新信息（自上次 Tag 以来的变更）"""
    aaf_root = get_aaf_root()

    # 获取最新 Tag
    result = subprocess.run(
        ["git", "tag", "-l", "Tag_AAF_*"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    tags = sorted(result.stdout.strip().splitlines()) if result.stdout.strip() else []
    last_tag = tags[-1] if tags else "HEAD~50"

    # 获取变更文件
    result = subprocess.run(
        ["git", "diff", "--name-only", last_tag, "HEAD"],
        cwd=aaf_root,
        capture_output=True,
        text=True,
    )
    changed_files = result.stdout.strip().splitlines() if result.stdout.strip() else []

    # 按模块分组
    module_changes: dict[str, list[str]] = {}
    for f in changed_files:
        parts = f.split("/")
        if len(parts) < 2:
            continue
        mod = parts[0]
        # 排除非模块目录
        if mod.startswith(".") or mod in ("gradle", "build", "buildSrc", "config.gradle"):
            continue
        if mod not in module_changes:
            module_changes[mod] = []
        module_changes[mod].append(f)

    # 只保留 src/main 有变更的模块
    src_modules = {
        mod: files
        for mod, files in module_changes.items()
        if any("src/main/" in f for f in files)
    }

    # 如果指定了模块，过滤
    if module:
        src_modules = {k: v for k, v in src_modules.items() if module.lower() in k.lower()}

    return UpdateInfo(
        last_tag=last_tag,
        changed_modules=sorted(src_modules.keys()),
        module_changes=src_modules,
    )


def _find_module_in_config(aaf_root: Path, module_name: str, info: ModuleInfo) -> None:
    """从 dependencies_*.gradle 中查找模块信息"""
    type_map = {
        "dependencies_lib.gradle": "lib",
        "dependencies_common.gradle": "common",
        "dependencies_services.gradle": "services",
        "dependencies_tbs.gradle": "tbs",
        "dependencies_lock_widget.gradle": "lock_widget",
        "dependencies_asr.gradle": "asr",
        "dependencies_deprecated.gradle": "deprecated",
    }

    for dep_file in sorted(aaf_root.glob("dependencies_*.gradle")):
        content = dep_file.read_text(encoding="utf-8")
        # 查找 "ModuleName" : [ ... ]
        pattern = rf'"{re.escape(module_name)}"\s*:\s*\[([^\]]+)\]'
        m = re.search(pattern, content, re.DOTALL)
        if m:
            block = m.group(1)
            artifact_match = re.search(r'"artifactId"\s*:\s*"([^"]+)"', block)
            version_match = re.search(r'"version"\s*:\s*"([^"]+)"', block)
            deps_match = re.search(r'"apidependenciesList"\s*:\s*\[([^\]]*)\]', block)

            if artifact_match:
                info.artifact_id = artifact_match.group(1)
            if version_match:
                info.version = version_match.group(1)
            info.source_file = dep_file.name
            info.module_type = type_map.get(dep_file.name, "other")

            if deps_match:
                deps_str = deps_match.group(1)
                info.dependencies = [
                    d.strip().strip('"').strip("'")
                    for d in deps_str.split(",")
                    if d.strip().strip('"').strip("'")
                ]
            break


def _module_name_to_artifact(module_name: str) -> str:
    """将模块名转为可能的 artifactId（如 LibAudio → lib-audio）"""
    result = ""
    for i, c in enumerate(module_name):
        if c.isupper() and i > 0:
            result += "-"
        result += c.lower()
    return result


def _scan_source_files(module_dir: Path) -> list[str]:
    """扫描模块源文件"""
    src_dirs = [
        module_dir / "src" / "main" / "java",
        module_dir / "src" / "main" / "kotlin",
    ]
    files: list[str] = []
    for src_dir in src_dirs:
        if src_dir.exists():
            for f in sorted(src_dir.rglob("*")):
                if f.is_file() and f.suffix in (".kt", ".java"):
                    files.append(str(f.relative_to(module_dir)))
    return files


def _extract_public_apis(module_dir: Path) -> list[PublicAPI]:
    """提取模块的公共 API（类名 + 方法签名）"""
    apis: list[PublicAPI] = []
    src_dirs = [
        module_dir / "src" / "main" / "java",
        module_dir / "src" / "main" / "kotlin",
    ]

    for src_dir in src_dirs:
        if not src_dir.exists():
            continue
        for f in sorted(src_dir.rglob("*")):
            if not f.is_file() or f.suffix not in (".kt", ".java"):
                continue

            content = f.read_text(errors="ignore")

            # 跳过内部实现文件
            if "internal" in str(f.relative_to(module_dir)).lower():
                continue

            # 提取类名
            class_match = re.search(
                r"(?:public\s+)?(?:open\s+|abstract\s+|sealed\s+)?(?:class|interface|object)\s+(\w+)",
                content,
            )
            if not class_match:
                continue

            class_name = class_match.group(1)

            # 提取公共方法签名
            methods: list[str] = []
            if f.suffix == ".kt":
                # Kotlin: fun xxx(...)
                for m in re.finditer(
                    r"^\s*(?:@\w+\s+)*(?:public\s+|open\s+|override\s+)*fun\s+(\w+\s*\([^)]*\)(?:\s*:\s*\S+)?)",
                    content,
                    re.MULTILINE,
                ):
                    sig = m.group(1).strip()
                    if not sig.startswith("_"):  # 跳过私有约定
                        methods.append(sig)
            else:
                # Java: public xxx(...)
                for m in re.finditer(
                    r"^\s*public\s+(?:static\s+)?(?:\w+(?:<[^>]+>)?)\s+(\w+\s*\([^)]*\))",
                    content,
                    re.MULTILINE,
                ):
                    methods.append(m.group(1).strip())

            if methods:
                apis.append(PublicAPI(
                    class_name=class_name,
                    file_path=str(f.relative_to(module_dir)),
                    methods=methods,
                ))

    return apis


def _determine_doc_path(info: ModuleInfo) -> str:
    """根据模块类型确定文档路径"""
    type_to_dir = {
        "lib": "use/libs/noui",
        "common": "use/common",
        "services": "use/services",
        "tbs": "use/services",
        "lock_widget": "use/libs/ui",
        "asr": "use/libs/noui",
        "deprecated": "use/common",
    }

    # 判断是否是 UI 模块
    dir_prefix = type_to_dir.get(info.module_type, "use/libs/noui")
    if info.module_type == "lib" and any(
        kw in info.module_name.lower() for kw in ("ui", "view", "dialog", "widget", "compose")
    ):
        dir_prefix = "use/libs/ui"

    artifact = info.artifact_id or _module_name_to_artifact(info.module_name)
    return f"{dir_prefix}/{artifact}.md"
