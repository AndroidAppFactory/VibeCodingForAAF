---
version: 2
category: aaf
name: aaf-sample-apply
description: 升级 Template-AAF 到最新 AAF 框架版本。当用户说"升级 Template-AAF"时使用此 skill
---

# AAF Sample Apply

升级 **Template-AAF** 到最新框架版本。

## 前置条件

- 项目定位：通过 `aaf-project-finder` Skill 定位（`$AAF_HOME/AndroidAppFactory`）
- `aaf` CLI 可用（`python3 -m aafkit` 或 pip install 后直接 `aaf`）
- Template-AAF 工作区干净（有未提交变更会被跳过）

## 工作流程

```
aaf sample-check              → 检查 Template-AAF 与 AAF 的差异
       ↓ 展示给用户
用户确认
       ↓
aaf sample-apply --build      → 升级 Template-AAF + 编译验证
       ↓
展示变更结果 + 建议提交信息
```

## 命令说明

### aaf sample-check

检查 Template-AAF 与 AAF 最新配置的差异（无需传项目参数）。

```bash
aaf sample-check          # 表格格式
aaf sample-check --json   # JSON 格式
```

### aaf sample-apply

升级 Template-AAF（无需传项目参数）。

```bash
aaf sample-apply --build  # 升级 + 编译验证
aaf sample-apply          # 仅升级不编译
```

### aaf sample-sync

将 Template-AAF 的修改同步到 Template_Android 和 Template-Empty。此命令由 `aaf-sample-upgrade` Skill 调用，不在本 Skill 流程中。

```bash
aaf sample-sync --build   # 同步 + 编译验证
aaf sample-sync           # 仅同步不编译
```

**同步策略**：
- Template_Android：直接复制 config.gradle、build.gradle、gradle-wrapper.properties、APPTest/build.gradle、AndroidManifest.xml、3 个 Compose UI 文件；Application/build.gradle 只同步 AAF 依赖版本
- Template-Empty：同步 gradle-wrapper.properties、config.gradle（使用 appMinSdkVersion）、App/build.gradle 只同步 AAF 依赖版本、检查 AndroidManifest exported

## 升级清单（Template-AAF）

| 文件 | 同步来源 | 内容 |
|------|---------|------|
| `config.gradle` | AAF `config.gradle` | SDK 配置 |
| `build.gradle` | AAF | kotlin_version / gradle 插件版本 |
| `gradle/wrapper/gradle-wrapper.properties` | AAF 同路径 | Gradle 发行版 URL |
| `dependencies.gradle` | AAF `dependencies_*.gradle` | AAF 模块版本号 |
| `APPTest/build.gradle` | AAF `APPTest/build.gradle` | Compose 配置 + AAF 依赖版本 |
| `APPTest/src/main/AndroidManifest.xml` | 检查 | LAUNCHER Activity 需 exported="true" |
| `APPTest/src/.../DebugMainActivity.kt` | AAF 同路径 | 直接复制 |
| `APPTest/src/.../module/DebugTempView.kt` | AAF 同路径 | 直接复制 |
| `APPTest/src/.../module/DebugRouterView.kt` | AAF 同路径 | 直接复制 |

## 核心原则

- **sample-check / sample-apply 固定只处理 Template-AAF**
- **不同模块可能有不同版本号**，逐个查找，不强行统一
- **LLM 不直接操作文件**，所有确定性逻辑由 `aaf` CLI 承载
- 编译失败不自行修复，展示错误请求用户协助

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 无需升级 / 升级+编译成功 |
| 1 | 错误或编译失败 |
| 2 | 有可用升级（sample-check 专用） |

## 与 aaf-sample-upgrade 的关系

`aaf-sample-apply` 只升级 Template-AAF 一个项目。`aaf-sample-upgrade` 是编排层，升级三个项目：先调用本 Skill 完成 Template-AAF 升级，再执行 `aaf sample-sync` 同步到 Template_Android 和 Template-Empty。
