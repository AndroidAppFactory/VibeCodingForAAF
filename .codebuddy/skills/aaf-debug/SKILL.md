---
name: aaf-debug
description: AAF 代码调试助手（增强版）- 在 user 级 debug 流程基础上，增加 AAF 模块智能识别。当用户说"调试 AAF 的 LibXXX"时使用此 skill。
---

# AAF 代码调试助手（增强版）

> **前置依赖**：本 Skill 继承 user 级 `debug` Skill 的完整调试流程（阶段 2-7），仅补充 AAF 专属的模块识别能力。运行前请确认 user 级 `debug` Skill 已安装（位于 `~/.codebuddy/skills/debug/`）。

## 触发关键词

- "调试 AAF 的 LibXXX"
- "debug AAF LibXXX"
- "AAF 的 XX 有问题"

当用户明确提到 **AAF** 或 AAF 模块名时触发本 Skill，否则使用 user 级 `debug` Skill。

## AAF 模块识别

### 命名规则

- `LibXXX` - 基础库模块（如 LibTTS、LibDownload、LibNetwork）
- `CommonXXX` - 公共组件（如 CommonWrapper）
- 模块名直接对应目录名

### 识别映射

| 用户说 | 识别结果 |
|-------|---------|
| "调试 AAF 的 LibTTS" | 模块=LibTTS |
| "调试 AAF LibDownload" | 模块=LibDownload |
| "debug LibNetwork" | 模块=LibNetwork |
| "调试下载功能" | 模块=LibDownload |
| "TTS 有问题" | 模块=LibTTS |

### 项目路径查找

```bash
# 查找顺序
1. 当前工作区同级：./AndroidAppFactory
2. 父目录同级：../AndroidAppFactory
3. 使用 find 命令定位
```

## AAF 专属日志规范

在 user 级 `APP_DEBUG` TAG 基础上，AAF 使用 `AAF_DEBUG` 作为统一 TAG：

```kotlin
private const val DEBUG_TAG = "AAF_DEBUG"

// 使用 AAF 框架的日志工具
ZLog.d(DEBUG_TAG, ">>> functionName: param1=$param1")
```

### 日志收集

```bash
# AAF 调试日志
adb logcat -d | grep "AAF_DEBUG"

# 包含错误
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error|FATAL)"
```

## 工作流程

```
用户请求调试 AAF 模块
    ↓
【阶段 1：AAF 模块识别 + 问题收集】（本 Skill 增强）
├─ 按上方映射表自动识别 AAF 模块
├─ 按项目路径查找顺序定位 AndroidAppFactory
├─ 只询问：具体是什么问题？
└─ 使用 AAF_DEBUG TAG（替代 user 级 APP_DEBUG）
    ↓
【阶段 2-7：继承 user 级 debug Skill】
├─ 阶段 2：代码理解（定位模块代码、检查现有日志）
├─ 阶段 3：日志准备（使用 ZLog + AAF_DEBUG TAG）
├─ 阶段 4：等待用户运行程序
├─ 阶段 5：日志收集与分析
├─ 阶段 6：问题解决
└─ 阶段 7：清理调试日志
```

> 阶段 2-7 的详细定义见 user 级 `debug` Skill。
