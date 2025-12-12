---
name: aaf-debug
description: 代码调试助手 - 帮助定位和分析代码问题。当用户说"debug一下XX模块"、"调试XX"、"帮我排查XX问题"、"分析XX日志"等关键词时使用此 skill。通过添加关键日志、运行程序、分析 ADB 日志来定位问题。
---

# AAF 代码调试助手

## 概述

**AI 辅助调试** Android 代码问题，通过以下流程：
1. 📍 定位目标模块和代码
2. 🔍 理解代码逻辑
3. 📝 添加关键日志
4. ▶️ 用户运行程序
5. 📊 分析 ADB 日志
6. 💡 定位问题原因

## 触发关键词

- "debug 一下 XX"
- "调试 XX 模块"
- "帮我排查 XX 问题"
- "XX 功能有问题"
- "分析一下 XX 的日志"
- "XX 不工作了"

## 工作流程

```
用户请求调试
    ↓
【阶段 1：信息收集】
AI 询问：
├─ 具体是哪个模块/功能？
├─ 问题现象是什么？
├─ 什么时候出现？（操作步骤）
└─ 有没有错误提示？
    ↓
【阶段 2：代码理解】
AI 执行：
├─ 定位相关代码文件
├─ 阅读和理解代码逻辑
├─ 识别关键执行路径
└─ 确定日志插入点
    ↓
【阶段 3：添加日志】
AI 执行：
├─ 在关键位置添加日志
├─ 使用统一的 TAG 前缀
├─ 记录关键变量值
└─ 标记执行流程
    ↓
【阶段 4：等待运行】
AI 告知用户：
├─ 日志已添加完成
├─ 请运行程序并复现问题
└─ 完成后告诉我"结束"
    ↓
【阶段 5：日志收集】
用户说"结束"后，AI 执行：
├─ 读取 ADB 日志
├─ 过滤相关日志
└─ 分析日志内容
    ↓
【阶段 6：问题分析】
AI 输出：
├─ 问题原因分析
├─ 代码执行路径
├─ 修复建议
└─ 可选：自动修复
    ↓
【阶段 7：清理】
AI 执行：
├─ 移除调试日志
└─ 恢复代码原状
```

## 阶段详解

### 阶段 1：信息收集

**AI 需要了解的信息**：

| 信息项 | 说明 | 示例 |
|-------|------|------|
| 模块名称 | 具体的功能模块 | "音效使用"、"下载功能"、"登录" |
| 问题现象 | 具体表现 | "点击没反应"、"数据不显示"、"闪退" |
| 复现步骤 | 如何触发问题 | "打开页面 → 点击按钮 → 出现问题" |
| 错误信息 | 如果有的话 | 崩溃日志、Toast 提示 |

**对话示例**：

```
用户：debug 一下音效使用功能

AI：好的，我来帮你调试音效使用功能。请告诉我：
1. 具体是什么问题？（比如：点击没反应、数据不对、闪退等）
2. 如何复现这个问题？（操作步骤）
3. 有没有看到什么错误提示？

用户：点击使用按钮后，英雄列表没有更新

AI：明白了。我来定位相关代码...
```

### 阶段 2：代码理解

**AI 执行步骤**：

1. **定位代码文件**
   ```bash
   # 搜索相关文件
   search_content "useOrUnUseVoice" /path/to/project
   search_file "*ViewModel.kt" /path/to/project
   ```

2. **阅读代码逻辑**
   - 理解函数调用链
   - 识别状态管理方式
   - 找出数据流向

3. **确定日志插入点**
   - 函数入口/出口
   - 条件分支
   - 异步回调
   - 状态变更点

### 阶段 3：添加日志

**日志规范**：

```kotlin
// 统一 TAG 前缀，便于过滤
private const val DEBUG_TAG = "AAF_DEBUG"

// 函数入口
ZLog.d(DEBUG_TAG, ">>> useOrUnUseVoice: isUse=$isUse, voiceID=$voiceID, heroIdList=$heroIdList")

// 关键变量
ZLog.d(DEBUG_TAG, "--- currentState: ${_voiceUsageStates.value}")

// 条件分支
ZLog.d(DEBUG_TAG, "--- branch: isUse=true, entering use logic")

// 异步回调
ZLog.d(DEBUG_TAG, "--- callback: onSuccess called, result=$result")

// 函数出口
ZLog.d(DEBUG_TAG, "<<< useOrUnUseVoice: finalList=$finalList")
```

**日志级别**：
- `ZLog.d` - 调试信息（默认使用）
- `ZLog.i` - 重要信息
- `ZLog.w` - 警告
- `ZLog.e` - 错误

**日志内容要求**：
- ✅ 包含关键变量值
- ✅ 标记执行位置（>>>入口, ---中间, <<<出口）
- ✅ 使用统一 TAG
- ✅ 简洁但信息完整

### 阶段 4：等待运行

**AI 输出模板**：

```
✅ 调试日志已添加完成！

📍 添加位置：
- BaseSkillVoiceViewModel.kt (5 处)
- SkillVoiceMineViewModel.kt (3 处)

📝 日志 TAG：AAF_DEBUG

▶️ 请执行以下步骤：
1. 运行程序
2. 复现问题（按你描述的操作步骤）
3. 完成后告诉我"结束"

我会读取日志并分析问题。
```

### 阶段 5：日志收集

**用户说"结束"后，AI 执行**：

```bash
# 获取最近的日志（过滤 DEBUG_TAG）
adb logcat -d | grep "AAF_DEBUG"

# 或获取更多上下文
adb logcat -d -t 1000 | grep -E "(AAF_DEBUG|Exception|Error)"

# 如果需要完整日志
adb logcat -d > /tmp/debug_log.txt
```

**日志过滤策略**：
1. 优先过滤 `AAF_DEBUG` TAG
2. 同时关注 `Exception`、`Error`、`Crash`
3. 保留时间戳以分析执行顺序

### 阶段 6：问题分析

**分析维度**：

| 维度 | 检查内容 |
|-----|---------|
| 执行流程 | 函数是否被调用？调用顺序是否正确？ |
| 参数值 | 传入参数是否符合预期？ |
| 状态变化 | 状态是否正确更新？ |
| 异步回调 | 回调是否触发？时序是否正确？ |
| 异常 | 是否有异常抛出？ |

**输出模板**：

```
📊 日志分析结果

🔍 执行流程：
1. useOrUnUseVoice 被调用 ✅
2. isUse=false, heroIdList=[] 
3. 进入取消逻辑 ✅
4. currentList.filter 执行 ✅
5. finalList 结果：[105, 106] ❌ 应该为空

💡 问题定位：
当 heroIdList 为空时，filter { it !in heroIdList } 不会移除任何元素，
导致 finalList 保留了原来的值。

🔧 修复建议：
在 updateVoiceUsageState 中添加判断：
当 isUse=false 且 heroIdList 为空时，直接设置 finalList 为空列表。

是否需要我帮你修复这个问题？
```

### 阶段 7：清理

**问题解决后，AI 执行**：

```kotlin
// 移除所有调试日志
// 使用 replace_in_file 删除添加的日志行

// 或者使用 git 恢复
git checkout -- path/to/file.kt
```

**清理确认**：
```
🧹 清理完成

已移除调试日志：
- BaseSkillVoiceViewModel.kt (5 处)
- SkillVoiceMineViewModel.kt (3 处)

代码已恢复原状。
```

## 日志收集命令参考

### 基础命令

```bash
# 清空日志缓冲区（开始前执行）
adb logcat -c

# 实时查看日志
adb logcat | grep "AAF_DEBUG"

# 导出日志到文件
adb logcat -d > /tmp/app_log.txt

# 过滤特定 TAG
adb logcat -d -s AAF_DEBUG

# 过滤多个 TAG
adb logcat -d -s AAF_DEBUG:D SkillVoice:D

# 获取最近 N 行
adb logcat -d -t 500

# 带时间戳
adb logcat -d -v time | grep "AAF_DEBUG"
```

### 崩溃日志

```bash
# 获取崩溃信息
adb logcat -d | grep -E "(FATAL|AndroidRuntime|Exception)"

# 获取 ANR 信息
adb logcat -d | grep -E "(ANR|ActivityManager)"
```

### 组合命令

```bash
# 调试日志 + 错误信息
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error|FATAL)"

# 保存到文件并显示
adb logcat -d | tee /tmp/debug.log | grep "AAF_DEBUG"
```

## 常见调试场景

### 场景 1：UI 不更新

**可能原因**：
- StateFlow 未正确更新
- Compose 未正确观察状态
- 数据转换逻辑错误

**日志重点**：
- 状态变更前后的值
- Flow 的 emit/collect 调用
- Compose recomposition

### 场景 2：点击无响应

**可能原因**：
- 点击事件未绑定
- 条件判断阻止执行
- 异步操作未完成

**日志重点**：
- 点击回调是否触发
- 条件判断的值
- 异步操作的开始/结束

### 场景 3：数据不正确

**可能原因**：
- 数据源问题
- 转换逻辑错误
- 缓存数据过期

**日志重点**：
- 原始数据值
- 每步转换后的值
- 缓存读写操作

### 场景 4：崩溃/闪退

**可能原因**：
- 空指针异常
- 数组越界
- 并发问题

**日志重点**：
- 崩溃堆栈
- 崩溃前的操作
- 相关变量值

## AI 执行检查清单

### 信息收集阶段
- [ ] 确认目标模块
- [ ] 了解问题现象
- [ ] 获取复现步骤
- [ ] 记录错误信息（如有）

### 代码理解阶段
- [ ] 定位相关代码文件
- [ ] 理解代码逻辑
- [ ] 识别关键执行路径
- [ ] 确定日志插入点

### 添加日志阶段
- [ ] 使用统一 TAG（AAF_DEBUG）
- [ ] 函数入口添加日志
- [ ] 关键变量添加日志
- [ ] 条件分支添加日志
- [ ] 异步回调添加日志
- [ ] 函数出口添加日志
- [ ] 确认编译通过

### 等待运行阶段
- [ ] 告知用户日志已添加
- [ ] 说明添加位置和数量
- [ ] 提醒用户复现问题
- [ ] 等待用户说"结束"

### 日志分析阶段
- [ ] 收集 ADB 日志
- [ ] 过滤相关日志
- [ ] 分析执行流程
- [ ] 检查参数值
- [ ] 检查状态变化
- [ ] 定位问题原因

### 问题解决阶段
- [ ] 输出分析结果
- [ ] 提供修复建议
- [ ] 询问是否自动修复
- [ ] 执行修复（如需要）

### 清理阶段
- [ ] 移除调试日志
- [ ] 确认代码恢复
- [ ] 验证编译通过

## 注意事项

### 日志安全
- ❌ 不要记录敏感信息（密码、Token、用户隐私）
- ❌ 不要在生产代码中保留调试日志
- ✅ 调试完成后必须清理日志

### 性能考虑
- ❌ 不要在循环中添加大量日志
- ❌ 不要记录大型对象（会影响性能）
- ✅ 只记录关键信息

### 代码安全
- ✅ 添加日志前先理解代码
- ✅ 确保日志语句语法正确
- ✅ 添加后验证编译通过
- ✅ 使用 git 跟踪变更，便于恢复

## 快速参考

### 日志模板

```kotlin
// 入口
ZLog.d("AAF_DEBUG", ">>> functionName: param1=$param1, param2=$param2")

// 中间
ZLog.d("AAF_DEBUG", "--- checkpoint: state=$state")

// 分支
ZLog.d("AAF_DEBUG", "--- branch: condition=$condition, entering X")

// 回调
ZLog.d("AAF_DEBUG", "--- callback: result=$result")

// 出口
ZLog.d("AAF_DEBUG", "<<< functionName: return=$returnValue")
```

### ADB 命令

```bash
# 清空
adb logcat -c

# 收集
adb logcat -d | grep "AAF_DEBUG"

# 完整
adb logcat -d | grep -E "(AAF_DEBUG|Exception|Error)"
```
