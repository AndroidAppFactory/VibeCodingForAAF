# CODEBUDDY.md This file provides guidance to CodeBuddy Code when working with code in this repository.

## 项目概述

CodeBuddyForAAF 是 AAF（AndroidAppFactory）框架的智能开发工作区，通过 `.codebuddy/rules/` 和 `.codebuddy/skills/` 提供自然语言命令支持。

## 初始化

```bash
./init.sh
```

自动克隆必需项目到父目录，创建 AAF-Temp 开发目录。

## 项目布局

```
../                           # 父目录
├── AndroidAppFactory/        # AAF 核心框架（必需）
├── AndroidAppFactory-Doc/    # AAF 文档
├── Template-Empty/           # Sample: 最简示例
├── Template_Android/         # Sample: 基础示例
├── Template-AAF/             # Sample: 完整示例
└── CodeBuddyForAAF/          # 当前项目
    └── AAF-Temp/             # Demo: 内部临时开发
```

## 术语区分（重要）

| 术语 | 定位 | 项目 | 特点 |
|-----|------|------|------|
| **Sample** | 外部示例 | Template-AAF/Template_Android/Template-Empty | 供外部开发者参考，保持高质量，不直接修改 |
| **Demo** | 内部开发 | AAF-Temp | 临时验证功能，可随意修改 |

## Skill 系统

位于 `.codebuddy/skills/`，使用自然语言触发：

| Skill | 触发关键词 | 功能 |
|-------|-----------|------|
| `aaf-debug` | "debug XX"、"调试 XX"、"排查 XX 问题" | 代码调试助手 |
| `aaf-sample-upgrade` | "升级 sample"、"升级 Template 版本" | Sample 项目升级 |

### aaf-debug 流程
1. 智能识别模块（如 "调试 AAF 的 LibTTS" → LibTTS）
2. 只问问题现象，不问复现步骤
3. **优先使用现有日志**，必要时添加 `AAF_DEBUG` TAG
4. 用户运行程序后说"结束"
5. 分析 ADB 日志，定位问题
6. 清理调试日志

### aaf-sample-upgrade 流程
1. **必须按顺序**：Template-AAF → Template_Android → Template-Empty
2. 同步内容：SDK 配置、Kotlin/Gradle 版本、AAF 依赖、Compose UI 代码、Manifest
3. Template-AAF 编译成功后，可**并发**升级其他两个项目（节省 30-40% 时间）
4. 每个项目都必须验证编译通过

## 规则系统

位于 `.codebuddy/rules/`：

| 类型 | 规则文件 | 触发关键词 |
|-----|---------|-----------|
| 索引 | `aaf_commands.mdc` | 命令入口 |
| 命令 | `aaf_cmd_doc_management.mdc` | "更新文档"、"生成文档" |
| 命令 | `aaf_cmd_doc_inspection.mdc` | "文档巡检" |
| 命令 | `aaf_cmd_release_check.mdc` | "发布检查"、"准备发布" |
| 命令 | `aaf_cmd_version_upgrade.mdc` | "升级 AAF 版本" |
| 规范 | `aaf_git.mdc` | "提交规范"、"commit" |
| 规范 | `aaf_common.mdc` | 始终生效 |
| 规范 | `aaf_demo.mdc` | 始终生效 |
| 规范 | `aaf_dependency.mdc` | 始终生效 |
| 规范 | `aaf_note.mdc` | 始终生效 |
| 参考 | `aaf_version.mdc` | 版本查找 |

## 核心行为规范

### Git 提交（强制）

**流程**：检查 → 分析 → 展示方案 → 询问 → 等待授权 → 执行

| 禁止 | 允许 |
|-----|-----|
| 未经授权执行 `git commit/push` | 授权词："可以"、"执行"、"提交吧" |
| 用户只是查看变更时自动提交 | 一次授权仅限一次提交 |
| 复用之前的授权 | 每次提交需重新授权 |

**Commit Message**：`<type>(<scope>): <subject>`
- Type：feat / fix / docs / style / refactor / perf / test / build / ci / chore / revert

### Demo 开发

- 所有新代码在 `AAF-Temp/App` 中编写，不创建新 Module
- 触发"自动运行"后，每次修改自动编译、安装、启动
- 退出："停止自动运行"

### 依赖管理

| 项目 | 方式 |
|-----|-----|
| AndroidAppFactory | 集中式：根目录 `dependencies_*.gradle` |
| Template-Android/Empty | 标准：各模块 build.gradle |

### 版本查找

```bash
# 1. 优先：通过 artifactId 查找
grep -r '"artifactId".*:.*"模块名"' ../AndroidAppFactory/dependencies_*.gradle

# 2. 备选：使用主版本号
grep 'moduleVersionName' ../AndroidAppFactory/dependencies.gradle

# 3. 特殊：编译器模块（lib-router-compiler）通常独立版本
```

### 注释规范

- 所有 `public` 接口必须有 KDoc/JavaDoc 注释（中文）
- 新文件必须添加文件头注释（开发者、日期、功能说明）

## 常用命令

```bash
# 初始化项目
./init.sh

# AAF 框架编译
cd ../AndroidAppFactory && ./gradlew assembleDebug

# Demo 项目编译
cd AAF-Temp && ./gradlew :App:assembleDebug

# 安装并启动
adb install -r App/build/outputs/apk/debug/App-debug.apk
adb shell am start -n com.bihe0832.android.app/.MainActivity

# 查找模块版本
grep -r '"artifactId".*:.*"模块名"' ../AndroidAppFactory/dependencies_*.gradle
```

### ADB 调试命令

```bash
# 清空日志
adb logcat -c

# 收集调试日志
adb logcat -d | grep "AAF_DEBUG"

# 包含错误
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error|FATAL)"

# 带时间戳
adb logcat -d -v time | grep "AAF_DEBUG"
```

## 技术栈

- **语言**：Kotlin 优先，Java 兼容
- **UI**：Jetpack Compose 优先，传统 View 备选

## 代码质量标准

- ✅ 通过编译测试
- ✅ 移除未使用的 import
- ✅ 无编译错误和警告
- ✅ 功能正常运行
