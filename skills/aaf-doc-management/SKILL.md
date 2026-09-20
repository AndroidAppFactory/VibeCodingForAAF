---


version: 2
category: aaf
name: aaf-doc-management
description: AAF 文档管理 - 分析模块源码生成/更新文档。当用户说"生成AAF文档"、"整理AAF文档"、"同步AAF文档"、"更新AAF文档"时使用此 skill


---

# AAF 文档管理

## 概述

分析 AAF 模块源码，按 AI-facing 格式生成或更新文档。文档定位是**给 AI 编码时参考的 API 能力索引**，强调签名的完整性和约束的精确性，不写内部实现。

## 模式

| 触发词 | 模式 | 说明 |
|--------|------|------|
| "生成文档"、"整理文档" | 完整生成 | 需指定模块名 |
| "同步文档"、"更新文档" | 增量更新 | 自动检测变更模块 |

## 执行流程

```
用户请求
    ↓
aaf projects              → 定位 AAF_HOME 下的项目
    ↓
根据触发词判断模式
    ├─ 完整生成 → aaf doc-info <module> --json
    └─ 增量更新 → aaf doc-changes --json
    ↓
【Skill: aaf-doc-generator】执行文档生成/更新
    ├─ 传入 module + aaf_path + doc_path
    ├─ 写前检查文件是否存在 → 已存在则全量覆盖
    ├─ 文档文件直接写入（无需用户确认）
    └─ SUMMARY.md 修改建议返回给主流程
    ↓
展示 SUMMARY.md 修改建议，**等待用户确认后才执行**
```

## CLI 命令

| 命令 | 功能 |
|------|------|
| `aaf doc-inspect` | 检查模块与文档对应关系（覆盖率/缺失列表） |
| `aaf doc-info <module>` | 获取模块元信息（artifactId/版本/公共API） |
| `aaf doc-changes` | 获取自上次 Tag 以来的变更模块列表 |

## 内部 Skill

| Skill | 路径 | 职责 |
|-------|------|------|
| `aaf-project-finder` | `../aaf-project-finder/` | 定位 AAF 相关项目位置 |
| `aaf-doc-generator` | `../aaf-doc-generator/` | 分析源码按 AI-facing 模板生成/更新文档 |

## 注意事项

1. 文档由 Agent 直接写入，**写前全量覆盖**，不执行增量合并
2. SUMMARY.md 索引修改**必须**经用户确认
3. 文档定位是**给 AI 看的 API 索引**，不是给人读的手册
4. 确定性操作（模块信息提取、巡检）由 CLI 承载，LLM 只负责语义理解和文档撰写
