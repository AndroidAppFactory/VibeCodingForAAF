# 代码质量巡检

多项目批量代码质量巡检，支持增量检查、自动修复、生成结构化报告。

## 执行规则

**必须调用 `aaf-code-quality-checker` Agent 执行**，按该 Agent 定义的完整流程运行（项目发现 → 增量策略 → 子 Agent 编排 → 报告汇总）。

## 可选参数

- `--force` — 强制全量检查
- `--projects` — 指定项目（逗号分隔）
- `--rules` — 指定检查类型（code-style, code-review, aaf-architecture）
- `--auto-fix` — 自动修复级别（info, warning, error）
- `--dry-run` — 只检查不修复
