---
name: aaf-debug
description: 代码调试助手 - 帮助定位和分析代码问题。当用户说"debug一下XX模块"、"调试XX"、"帮我排查XX问题"、"分析XX日志"等关键词时使用此 skill。通过添加关键日志、运行程序、分析 ADB 日志来定位问题。
---

# AAF 代码调试助手

## 概述

**AI 辅助调试** Android 代码问题，通过以下流程：
1. 📍 智能识别模块，只问问题现象
2. 🔍 理解代码逻辑
3. 📝 **优先使用现有日志**，必要时添加新日志
4. ▶️ 用户运行程序
5. 📊 分析 ADB 日志
6. 💡 定位问题原因

## 触发关键词

- "debug 一下 XX"
- "调试 XX 模块"
- "调试 AAF 的 LibXXX"
- "帮我排查 XX 问题"
- "XX 功能有问题"
- "XX 不工作了"

## 智能识别规则

### 模块识别

当用户说 **"调试 AAF 的 LibXXX"** 时，AI 应该：

1. **自动识别项目**：`AAF` = `AndroidAppFactory` 项目
2. **自动定位模块**：`LibXXX` = AAF 框架中的对应模块
3. **只问问题现象**：不需要问项目、不需要问复现步骤（用户自己操作）

**AAF 模块命名规则**：
- `LibXXX` - 基础库模块（如 LibTTS、LibDownload、LibNetwork）
- `CommonXXX` - 公共组件（如 CommonWrapper）
- 模块名直接对应目录名

**项目路径查找**：
```bash
# 查找顺序
1. 当前工作区同级：./AndroidAppFactory
2. 父目录同级：../AndroidAppFactory
3. 使用 find 命令定位
```

### 简化对话原则

**核心原则**：用户自己操作程序，AI 不需要问复现步骤

**AI 只需要问**：
- ✅ 具体是什么问题？（问题现象）
- ❌ ~~如何复现？~~（用户自己知道）
- ❌ ~~是哪个项目？~~（已从输入识别）

## 工作流程

```
用户请求调试（如：调试 AAF 的 LibTTS）
    ↓
【阶段 1：智能识别 + 问题收集】
AI 执行：
├─ 自动识别项目和模块
├─ 只询问：具体是什么问题？
└─ 用户回答后立即开始
    ↓
【阶段 2：代码理解】
AI 执行：
├─ 定位相关代码文件
├─ 阅读和理解代码逻辑
├─ **检查现有日志**（优先使用）
├─ 识别关键执行路径
└─ 确定是否需要添加新日志
    ↓
【阶段 3：日志准备】
AI 执行：
├─ **优先使用现有日志**
├─ 仅在必要时添加新日志
├─ 使用统一 TAG：AAF_DEBUG
└─ 确认编译通过（如有修改）
    ↓
【阶段 4：等待运行】
AI 告知用户：
├─ 日志已添加完成
├─ 请运行程序复现问题
└─ 完成后告诉我"结束"
    ↓
【阶段 5：日志收集与分析】
用户说"结束"后，AI 执行：
├─ 读取 ADB 日志
├─ 过滤 AAF_DEBUG 日志
├─ 分析执行流程
└─ 定位问题原因
    ↓
【阶段 6：问题解决】
AI 输出：
├─ 问题原因分析
├─ 修复建议
└─ 可选：自动修复
    ↓
【阶段 7：清理】
AI 执行：
├─ 移除调试日志
└─ 恢复代码原状
```

## 对话示例

### 示例 1：明确的模块

```
用户：调试 AAF 的 LibTTS

AI：好的，我来调试 LibTTS 模块。
📍 已定位：AndroidAppFactory/LibTTS

具体是什么问题？

用户：TTS 不发声

AI：明白了，我来分析 LibTTS 的代码并添加调试日志...
[开始阶段 2]
```

### 示例 2：功能描述

```
用户：调试下载功能

AI：好的，我来调试 AAF 的 LibDownload 模块。
📍 已定位：AndroidAppFactory/LibDownload

具体是什么问题？

用户：下载进度不更新

AI：明白了，我来分析下载进度相关代码...
[开始阶段 2]
```

## 阶段详解

### 阶段 1：智能识别 + 问题收集

**AI 自动解析用户输入**：

| 用户说 | 识别结果 |
|-------|---------|
| "调试 AAF 的 LibTTS" | 模块=LibTTS |
| "调试 AAF LibDownload" | 模块=LibDownload |
| "debug LibNetwork" | 模块=LibNetwork |
| "调试下载功能" | 模块=LibDownload |
| "TTS 有问题" | 模块=LibTTS |

**只问一个问题**：具体是什么问题？

### 阶段 2：代码理解

**AI 执行步骤**：

1. **定位代码文件**
   ```bash
   # 搜索模块目录
   list_files {AndroidAppFactory}/LibTTS/src/main/java
   
   # 搜索关键类
   search_file "*.kt" {AndroidAppFactory}/LibTTS
   ```

2. **检查现有日志**（重要！）
   ```bash
   # 搜索模块中的日志
   search_content "ZLog\.|Log\.|TAG" {模块目录}
   ```
   
   **优先使用现有日志的原因**：
   - 减少代码修改
   - 现有日志通常覆盖关键路径
   - 避免引入编译问题
   - 更快开始调试

3. **阅读代码逻辑**
   - 理解函数调用链
   - 识别状态管理方式
   - 找出数据流向

4. **决定日志策略**
   - ✅ 现有日志足够 → 直接让用户运行
   - ⚠️ 需要补充 → 仅在关键位置添加

### 阶段 3：日志准备

**核心原则：优先使用现有日志**

**决策流程**：
```
检查现有日志
    ↓
现有日志是否覆盖关键路径？
    ├─ 是 → 直接使用，告知用户运行程序
    └─ 否 → 仅在必要位置添加新日志
```

**使用现有日志时的输出**：
```
✅ 发现模块已有调试日志，无需添加新日志

📍 现有日志 TAG：TTS / DebugTTSBasicView
📝 日志过滤命令：
adb logcat | grep -E "TTS|TextToSpeech"

▶️ 请运行程序复现问题，完成后告诉我"结束"
```

**需要添加新日志时的规范**：

```kotlin
// 统一 TAG
private const val DEBUG_TAG = "AAF_DEBUG"

// 函数入口
ZLog.d(DEBUG_TAG, ">>> functionName: param1=$param1")

// 关键变量
ZLog.d(DEBUG_TAG, "--- state: $state")

// 条件分支
ZLog.d(DEBUG_TAG, "--- branch: entering X")

// 异步回调
ZLog.d(DEBUG_TAG, "--- callback: result=$result")

// 函数出口
ZLog.d(DEBUG_TAG, "<<< functionName: return=$returnValue")
```

**日志标记**：
- `>>>` 函数入口
- `---` 中间过程
- `<<<` 函数出口

### 阶段 4：等待运行

**AI 输出模板（使用现有日志）**：

```
✅ 模块已有调试日志，可以直接开始调试

📍 日志 TAG：TTS / DebugTTSBasicView
📝 过滤命令：adb logcat | grep -E "TTS|TextToSpeech"

▶️ 请运行程序复现问题，完成后告诉我"结束"
```

**AI 输出模板（添加了新日志）**：

```
✅ 调试日志已添加完成！

📍 添加位置：
- TTSManager.kt (3 处)
- TTSPlayer.kt (2 处)

📝 日志 TAG：AAF_DEBUG

▶️ 请运行程序复现问题，完成后告诉我"结束"
```

### 阶段 5：日志收集与分析

**用户说"结束"后，AI 执行**：

```bash
# 收集日志
adb logcat -d | grep "AAF_DEBUG"

# 包含错误信息
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error)"
```

### 阶段 6：问题解决

**输出模板**：

```
📊 日志分析结果

🔍 执行流程：
1. speak() 被调用 ✅
2. 参数：text="测试文本"
3. initTTS() 返回 false ❌
4. 未进入播放逻辑

💡 问题定位：
TTS 引擎初始化失败，导致无法播放

🔧 修复建议：
检查 TTS 引擎是否正确安装，或添加初始化失败的重试逻辑

是否需要我帮你修复？
```

### 阶段 7：清理

**仅在添加了新日志时需要清理**：

```bash
# 使用 git 恢复
git checkout -- path/to/file.kt
```

**清理确认**：
```
🧹 清理完成，已移除所有调试日志
```

**使用现有日志时无需清理**。

## 日志收集命令

```bash
# 清空日志
adb logcat -c

# 收集调试日志（使用现有 TAG）
adb logcat -d | grep -E "TTS|模块TAG"

# 收集新增调试日志
adb logcat -d | grep "AAF_DEBUG"

# 包含错误
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error|FATAL)"

# 带时间戳
adb logcat -d -v time | grep "AAF_DEBUG"
```

## AI 执行检查清单

### 识别与收集
- [ ] 从用户输入识别模块名
- [ ] 定位模块路径
- [ ] 只问问题现象（不问复现步骤）

### 代码理解
- [ ] 定位相关代码文件
- [ ] **搜索现有日志**（优先使用）
- [ ] 理解代码逻辑
- [ ] 确定是否需要添加新日志

### 日志准备
- [ ] **优先使用现有日志**
- [ ] 仅在必要时添加新日志
- [ ] 使用统一 TAG（AAF_DEBUG）
- [ ] 确认编译通过（如有修改）

### 等待与分析
- [ ] 告知用户日志已添加
- [ ] 等待用户说"结束"
- [ ] 收集并分析 ADB 日志
- [ ] 定位问题原因

### 解决与清理
- [ ] 提供修复建议
- [ ] 执行修复（如需要）
- [ ] 移除调试日志

## 注意事项

- ❌ 不要记录敏感信息
- ❌ 不要在循环中添加大量日志
- ✅ 调试完成后必须清理日志
- ✅ 添加日志后验证编译通过
- ✅ 使用 git 跟踪变更，便于恢复
