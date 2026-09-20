"""AAF 文档巡检 - 检查框架模块与文档的对应关系"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config_reader import get_aaf_home, get_aaf_root


@dataclass
class DocInspectReport:
    """文档巡检报告"""

    # 统计
    total_modules: int = 0
    documented_modules: int = 0
    missing_docs: list[dict[str, str]] = field(default_factory=list)  # [{module, type}]
    missing_index: list[dict[str, str]] = field(default_factory=list)  # [{file, path, suggestion}]

    @property
    def coverage_rate(self) -> float:
        if self.total_modules == 0:
            return 0.0
        return self.documented_modules / self.total_modules * 100

    @property
    def index_completeness(self) -> float:
        total_docs = self.documented_modules + len(self.missing_index)
        if total_docs == 0:
            return 100.0
        return (total_docs - len(self.missing_index)) / total_docs * 100

    def summary(self) -> str:
        lines = ["\n## AAF 文档巡检报告\n"]

        # 统计信息
        lines.append("### 统计信息\n")
        lines.append(f"| 指标 | 值 |")
        lines.append(f"|------|-----|")
        lines.append(f"| 总模块数 | {self.total_modules} |")
        lines.append(f"| 已有文档 | {self.documented_modules} |")
        lines.append(f"| 缺失文档 | {len(self.missing_docs)} |")
        lines.append(f"| 缺失索引 | {len(self.missing_index)} |")
        lines.append(f"| 文档覆盖率 | {self.coverage_rate:.1f}% |")
        lines.append(f"| 索引完整率 | {self.index_completeness:.1f}% |")

        # 缺失文档
        if self.missing_docs:
            lines.append("\n### 缺失文档的模块\n")
            lines.append("| 模块 | 类型 |")
            lines.append("|------|------|")
            for item in self.missing_docs:
                lines.append(f"| {item['module']} | {item['type']} |")

        # 缺失索引
        if self.missing_index:
            lines.append("\n### 有文档但未加入 SUMMARY.md 索引\n")
            lines.append("| 文件 | 路径 | 建议插入位置 |")
            lines.append("|------|------|-------------|")
            for item in self.missing_index:
                lines.append(f"| {item['file']} | {item['path']} | {item['suggestion']} |")

        # 结论
        lines.append("")
        if not self.missing_docs and not self.missing_index:
            lines.append("🎉 所有模块文档完整，索引齐全！")
        else:
            if self.missing_docs:
                lines.append(f"⚠️ 有 {len(self.missing_docs)} 个模块缺少文档")
            if self.missing_index:
                lines.append(f"⚠️ 有 {len(self.missing_index)} 个文档未加入 SUMMARY.md")

        return "\n".join(lines)

    def to_json(self) -> str:
        return json.dumps(
            {
                "total_modules": self.total_modules,
                "documented_modules": self.documented_modules,
                "coverage_rate": round(self.coverage_rate, 1),
                "index_completeness": round(self.index_completeness, 1),
                "missing_docs": self.missing_docs,
                "missing_index": self.missing_index,
            },
            indent=2,
            ensure_ascii=False,
        )


def doc_inspect() -> DocInspectReport:
    """执行文档巡检"""
    aaf_root = get_aaf_root()
    aaf_home = get_aaf_home()
    doc_root = aaf_home / "AndroidAppFactory-Doc"

    if not doc_root.exists():
        raise RuntimeError(f"文档仓库不存在: {doc_root}")

    report = DocInspectReport()

    # Step 1: 扫描 AAF 模块，获取 {模块名: artifactId} 映射
    modules = _scan_modules(aaf_root)
    report.total_modules = len(modules)

    # Step 2: 扫描文档目录，获取已有文档列表
    existing_docs = _scan_docs(doc_root)

    # Step 3: 对比模块与文档
    for module_name, info in modules.items():
        artifact_id = info.get("artifactId", "")
        if artifact_id and artifact_id in existing_docs:
            report.documented_modules += 1
        elif _module_name_to_doc(module_name) in existing_docs:
            report.documented_modules += 1
        else:
            report.missing_docs.append({"module": module_name, "type": info.get("type", "unknown")})

    # Step 4: 检查 SUMMARY.md 索引完整性
    summary_file = doc_root / "SUMMARY.md"
    if summary_file.exists():
        summary_content = summary_file.read_text(encoding="utf-8")
        report.missing_index = _check_summary_index(doc_root, summary_content)

    return report


def _scan_modules(aaf_root: Path) -> dict[str, dict[str, str]]:
    """扫描 AAF 所有模块，返回 {模块名: {artifactId, type}}"""
    modules: dict[str, dict[str, str]] = {}

    # 从 dependencies_*.gradle 中解析模块信息
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
        module_type = type_map.get(dep_file.name, "other")
        content = dep_file.read_text(encoding="utf-8")

        # 匹配 "ModuleName" : [ ... "artifactId" : "xxx" ... ]
        blocks = re.finditer(r'"(\w+)"\s*:\s*\[([^\]]+)\]', content, re.DOTALL)
        for block in blocks:
            module_name = block.group(1)
            block_content = block.group(2)
            artifact_match = re.search(r'"artifactId"\s*:\s*"([^"]+)"', block_content)
            artifact_id = artifact_match.group(1) if artifact_match else ""

            # 排除 APP* 和 Base* 开头的模块
            if module_name.startswith("APP") or module_name.startswith("Base"):
                continue

            modules[module_name] = {"artifactId": artifact_id, "type": module_type}

    return modules


def _scan_docs(doc_root: Path) -> set[str]:
    """扫描文档目录，返回已有文档的 artifact-id 集合（不含 .md 后缀）"""
    docs: set[str] = set()
    doc_dirs = [
        doc_root / "use" / "libs" / "noui",
        doc_root / "use" / "libs" / "ui",
        doc_root / "use" / "common",
        doc_root / "use" / "services",
        doc_root / "use" / "router",
    ]

    for doc_dir in doc_dirs:
        if doc_dir.exists():
            for md_file in doc_dir.glob("*.md"):
                # 文件名即 artifact-id（不含 .md）
                docs.add(md_file.stem)

    return docs


def _module_name_to_doc(module_name: str) -> str:
    """尝试将模块名转为可能的文档文件名（仅作 fallback，不保证准确）"""
    # LibDownload → lib-download（简单转换，仅用于 fallback 匹配）
    result = ""
    for i, c in enumerate(module_name):
        if c.isupper() and i > 0:
            result += "-"
        result += c.lower()
    return result


def _check_summary_index(doc_root: Path, summary_content: str) -> list[dict[str, str]]:
    """检查文档文件是否都在 SUMMARY.md 中有索引"""
    missing: list[dict[str, str]] = []

    doc_dirs = {
        "use/libs/noui": "基础功能模块",
        "use/libs/ui": "UI 相关模块",
        "use/common": "公共组件",
        "use/services": "三方组件",
        "use/router": "路由组件",
    }

    for rel_dir, category in doc_dirs.items():
        full_dir = doc_root / rel_dir
        if not full_dir.exists():
            continue

        for md_file in sorted(full_dir.glob("*.md")):
            # 构造相对路径（SUMMARY.md 中使用的路径格式）
            rel_path = f"{rel_dir}/{md_file.name}"
            # 检查是否在 SUMMARY.md 中
            if rel_path not in summary_content and md_file.name not in summary_content:
                missing.append(
                    {
                        "file": md_file.name,
                        "path": rel_path,
                        "suggestion": f"在「{category}」分类下添加",
                    }
                )

    return missing
