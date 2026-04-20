# CodeBuddyForAAF

AAF（AndroidAppFactory）开发辅助工具集。

---

## 功能概览

- **APK 16KB 对齐检查**：检查 APK/AAB/AAR 是否符合 Google Play 16KB 页面大小要求。
- **AAF 代码调试**（Skill）：AAF 模块智能识别 + 日志调试流程。
- **AAF Sample 升级**（Skill）：升级 Template-AAF / Template_Android / Template-Empty 到最新 AAF 框架版本。
- **ADB 端口释放**（Skill）：一键排查并释放 5037 端口占用。
- **AAF 规则集**（Rules）：AAF 发布检查、版本升级、文档管理、依赖规范等命令路由与规范。
- **AAF Agents**：AAF 专属的配置解析、文档生成、项目定位、Sample 更新 Agent。

---

## 目录结构

```
CodeBuddyForAAF/
├── skills/                # Skill 定义和脚本
│   ├── apk-16kb-check/    # 含可执行检查脚本（scripts/）
│   ├── aaf-debug/
│   ├── aaf-sample-upgrade/
│   └── adb-port-killer/
├── rules/                 # AAF 专属规则（*.mdc）
└── agents/                # AAF 专属 Agents（*.md）
```

---

## 使用方式

### 1. 直接运行可执行脚本

目前仅 `apk-16kb-check` 提供可独立运行的脚本：

```bash
python3 skills/apk-16kb-check/scripts/check_alignment.py <APK/AAB/AAR 路径>
```

### 2. 作为 CodeBuddy / Claude Skill 使用

将本仓库的 `skills/*/SKILL.md`、`rules/*.mdc`、`agents/*.md` 作为对应资源加载，或参考 `skills/*/SKILL.md` 的触发关键词在对话中直接唤起。

---

## 更新机制

本仓库由 [AIConfig](https://github.com/bihe0832/AIConfig) 自动同步。每次在 AIConfig 提交相关 skill / rule / agent 变更后，post-commit hook 会自动把最新内容推送到本仓库。

同步范围：
- `AIConfig/skills/aaf/*` 和 `AIConfig/skills/dev/adb-port-killer` → `skills/`
- `AIConfig/rules/aaf/aaf_*.mdc` → `rules/`
- `AIConfig/agents/aaf-*.md` → `agents/`

---

## License

MIT
