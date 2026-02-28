---
name: aaf-sample-upgrade
description: 升级 AAF Sample 项目（Template-AAF、Template_Android、Template-Empty）到最新 AAF 框架版本。当用户请求升级示例项目、更新模板版本、同步示例配置，或提到"升级sample"、"升级demo"、"更新Template版本"、"同步sample配置"等关键词时使用此 skill。
---

# AAF Sample 项目升级

## 概述

**AI 辅助升级** 三个 AAF 示例项目（Template-AAF、Template_Android、Template-Empty），同步最新的 AAF 框架版本、SDK 配置、Kotlin/Gradle 版本、Compose UI 代码和 Manifest 设置。

**工作方式**：
- 提供辅助脚本（项目定位、配置读取、编译验证）
- AI 根据指导执行实际的文件修改（使用 replace_in_file 等工具）
- 灵活处理特殊情况和错误
- 引用现有 rules 避免重复（aaf_version、aaf_dependency、aaf_git）

## 任务进度展示（必须）

**AI 必须使用 `todo_write` 工具展示升级进度**，让用户清晰了解当前状态。

### 初始化任务列表

用户触发升级后，立即创建任务列表：

```json
[
  {"id": "1", "status": "in_progress", "content": "定位项目位置"},
  {"id": "2", "status": "pending", "content": "读取 AAF 最新配置（含拉取 AAF 代码）"},
  {"id": "3", "status": "pending", "content": "升级 Template-AAF（第一优先级）"},
  {"id": "4", "status": "pending", "content": "升级 Template_Android（第二优先级）"},
  {"id": "5", "status": "pending", "content": "升级 Template-Empty（第三优先级）"},
  {"id": "6", "status": "pending", "content": "生成变更报告"},
  {"id": "7", "status": "pending", "content": "提供提交建议"}
]
```

### 状态更新规则

- 每完成一个步骤，更新对应任务为 `completed`，下一个任务为 `in_progress`
- 使用 `merge=true` 只更新变化的任务
- Template-AAF 完成后，任务 4 和 5 可同时设为 `in_progress`（并发升级）

### 并发升级时的进度更新

```
Template-AAF 编译成功后：
todo_write(merge=true, todos=[
  {"id": "3", "status": "completed", "content": "升级 Template-AAF（第一优先级）"},
  {"id": "4", "status": "in_progress", "content": "升级 Template_Android（第二优先级）"},
  {"id": "5", "status": "in_progress", "content": "升级 Template-Empty（第三优先级）"}
])
```

## 工作流程决策树

当用户触发此 skill 时，**通过 Agent 子代理执行升级**：

```
用户请求
    ↓
【创建任务列表】- 使用 todo_write 显示 7 个步骤
    ↓
【Agent: aaf-project-finder】定位项目位置 → 更新进度
    ├─ 找到 AndroidAppFactory 和三个 Template 项目的路径
    └─ 如果关键项目找不到 → 报错停止
    ↓
【Agent: aaf-config-reader】拉取 AAF 代码 + 读取最新配置 → 更新进度
    ├─ 拉取 AndroidAppFactory 最新代码（有本地变更则跳过）
    ├─ 读取 SDK 配置、版本号、模块版本
    └─ 返回结构化配置数据
    ↓
【Agent: aaf-sample-updater】升级 Template-AAF [必须先完成] → 更新进度
    ├─ 拉取 Template-AAF 最新代码（有本地变更则停止）
    ├─ 接收配置数据，执行完整升级
    ├─ 更新配置 + 同步依赖 + 同步 Compose UI 代码
    ├─ 验证编译
    └─ 返回结果（成功/失败+错误信息）
    ↓
    如果失败 → 主 Agent 展示错误，请求用户协助
    如果成功 ↓
    ↓
┌─────────────────────────────────────────────────────────┐
│ 并发 Agent（Template-AAF 成功后同时派出两个 Agent）    │
│ 任务 4 和 5 同时设为 in_progress                       │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ 【Agent: aaf-sample-updater】  【Agent: aaf-sample-updater】 │
│  升级 Template_Android          升级 Template-Empty    │
│  （第二优先级）                  （第三优先级）         │
│  ├─ 拉取最新代码               ├─ 拉取最新代码         │
│  ├─ 接收配置数据+参考路径       ├─ 接收配置数据+参考路径│
│  ├─ 执行完整升级                ├─ 执行完整升级         │
│  └─ 返回结果                    └─ 返回结果             │
│                                                         │
└─────────────────────────────────────────────────────────┘
    ↓
等待两个 Agent 都完成 → 更新进度
    ↓
主 Agent 汇总三个项目的结果，生成变更报告 → 更新进度
    ↓
提供提交建议 → 全部完成
```

### Agent 调用方式

使用 `task` 工具依次调用 Agent，每个 `task` 调用需传入：
- `subagent_name`：Agent 名称
- `description`：任务简述
- `prompt`：包含上一步返回的数据（项目路径、配置数据等）

**步骤 1**：`aaf-project-finder` — 传入工作区路径，返回各项目绝对路径
**步骤 2**：`aaf-config-reader` — 传入步骤 1 返回的路径，Agent 自动拉取 AAF 代码后读取配置
**步骤 3**：`aaf-sample-updater` — 传入 Template-AAF 路径 + 步骤 2 的配置数据
**步骤 4+5**：同一轮次并发两个 `aaf-sample-updater` — 分别传入 Template_Android / Template-Empty 路径 + 配置数据 + Template-AAF 参考路径

### Agent 执行优势

- **真正并发**：Template_Android 和 Template-Empty 由独立 Agent 同时执行
- **上下文隔离**：每个 Agent 只关注自己的项目，不会混淆
- **节省主上下文**：大量文件读写在 Agent 内完成，不占用主对话 token
- **效率提升**：预计节省 40-50% 时间（真正的并行编译）
- **失败隔离**：一个项目失败不影响另一个

## 核心升级策略

### 升级优先级顺序

**重要：必须按此顺序升级**：

1. **Template-AAF**（完整示例，第一优先级）
2. **Template_Android**（基础示例，第二优先级）
3. **Template-Empty**（最简示例，第三优先级）

**为什么顺序很重要**：
- Template-AAF 是最完整的参考实现
- 如果 Template-AAF 遇到问题，必须先修复再继续
- Template_Android 和 Template-Empty 参照 Template-AAF 的解决方案
- 绝不跳过 Template-AAF 或改变顺序

### 升级内容

**必须检查和同步**（具体升级清单由 `aaf-sample-updater` Agent 内部定义）：
1. SDK 配置、Kotlin/Gradle 版本
2. AAF 依赖版本
3. Compose 配置和 UI 代码
4. Manifest 配置

## 步骤 1：定位项目位置

**通过 Agent: aaf-project-finder 执行**。

调用 `aaf-project-finder` Agent，传入工作区路径，它会返回所有 AAF 相关项目的绝对路径。

需要定位的项目：
- `AndroidAppFactory`（配置源，**必须找到**）
- `Template-AAF`（目标 1）
- `Template_Android`（目标 2）
- `Template-Empty`（目标 3）

**重要**：如果 AndroidAppFactory 找不到，立即停止并报错。

## 步骤 2：读取 AAF 最新配置

**通过 Agent: aaf-config-reader 执行**，传入步骤 1 `aaf-project-finder` 返回的项目路径。

Agent 会先**拉取 AndroidAppFactory 最新代码**（有本地变更则跳过），然后读取 SDK 配置、版本号、模块版本等。

**版本查找策略**详见 `aaf_version` rule（使用 `read_rules` 工具读取，rule 名称为 `aaf_version`）。

## 步骤 3：升级 Template-AAF（第一优先级）

**通过 Agent: aaf-sample-updater 执行**。

这是最重要的步骤——所有其他项目都参照 Template-AAF 的结果。

Agent 会自动完成：拉取最新代码 → 更新配置/依赖/UI 代码 → 验证编译。

具体升级哪些文件、怎么改，由 `aaf-sample-updater` Agent 内部决定（详见 Agent 定义）。

**如果编译失败**：
- 停止 - 不要继续处理其他项目
- 展示 Agent 返回的错误信息
- 请求用户协助修复问题
- 验证修复有效后再继续

## 步骤 4 & 5：并发升级 Template_Android 和 Template-Empty

**重要**：Template-AAF 编译成功后，可以**同时**派出两个 `aaf-sample-updater` Agent。

每个 Agent 会自动完成：拉取最新代码 → 参照 Template-AAF 升级 → 验证编译。

**失败处理**：一个项目失败不影响另一个，分别处理。

## 步骤 6：生成变更报告

汇总三个项目的升级结果，按以下结构输出：
- AAF 最新配置（版本号、SDK、Kotlin、Gradle）
- 每个 Template 的变更详情（配置/依赖/UI/Manifest）
- 编译验证结果

## 步骤 7：提供提交建议

**只有在所有项目都编译成功后才提供提交建议！** 遵循 `aaf_git` 规范生成提交方案。

## 资源说明

### Agent 子代理

| Agent | 职责 |
|-------|------|
| `aaf-project-finder` | 定位所有 AAF 相关项目位置 |
| `aaf-config-reader` | 拉取 AAF 代码 + 读取配置和版本 |
| `aaf-sample-updater` | 拉取 Template 代码 + 升级项目 + 编译验证 |

### 外部引用（使用 read_rules 工具读取）

- **aaf_version** - AAF 模块版本查找方法
- **aaf_dependency** - AAF 依赖管理规范
- **aaf_git** - Git 提交规范
