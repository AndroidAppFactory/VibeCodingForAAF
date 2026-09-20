---



name: aaf-release-check
version: 2
category: aaf
description: AAF 发布前检查。当用户说"准备发布"、"发布前"、"release"、"发版"时使用此 skill



---
# AAF 发布前检查（Workflow Skill）
## 前置条件

- 项目定位：通过 `aaf-project-finder` Skill 定位（`$AAF_HOME/AndroidAppFactory`）

## 工作流程

### Step 1: 执行 CLI 检查

```bash
# 快速检查（跳过编译，约 5 秒）
aaf release-check --skip-build

# 完整检查（含编译，约 5-10 分钟）
aaf release-check
```

### Step 2: 展示报告

将 CLI 输出展示给用户，报告包含：

| 检查项 | 说明 |
|--------|------|
| 版本号检查 | moduleVersionName 是否已提升（对比最新 Tag） |
| 模块完整性 | 修改模块是否都在 developModule 中 |
| 依赖配置检查 | 依赖变更影响的模块是否在发布列表中 |
| Git 状态 | 工作区是否干净、分支是否正确 |
| 编译检查 | assembleDebug 是否通过 |

### Step 3: 处理异常

| 异常 | LLM 行为 |
|------|----------|
| 版本号未提升 | 提示用户修改 dependencies.gradle |
| 模块未加入 developModule | 列出缺失模块，询问是否添加 |
| 编译失败 | 展示错误信息，协助排查 |
| 工作区不干净 | 提示用户先提交或 stash |

### Step 4: 全部通过后

展示 `./gradlew showPublishCommand` 的输出，提示用户执行发布。
