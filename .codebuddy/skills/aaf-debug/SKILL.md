---
name: aaf-debug
description: AAF 代码调试助手（增强版）- 在 user 级 debug 流程基础上，增加 AAF 模块智能识别。当用户说"调试 AAF 的 LibXXX"时使用此 skill。
---

# AAF 代码调试助手（增强版）

> 本 Skill 继承 user 级 `debug` Skill 的完整调试流程，仅补充 AAF 专属的模块识别能力。

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

## 其余流程

阶段 2-7（代码理解、日志准备、等待运行、日志分析、问题解决、清理）完全遵循 user 级 `debug` Skill 的定义。
