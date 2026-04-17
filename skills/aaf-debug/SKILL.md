---
name: aaf-debug
description: AAF 代码调试助手（增强版）- 在 user 级 debug 流程基础上，增加 AAF 模块智能识别。当用户说"调试 AAF 的 LibXXX"时使用此 skill。
---

# AAF 代码调试助手（增强版）

> **前置依赖**：本 Skill 继承 user 级 `debug` Skill 的完整调试流程（阶段 2-7），仅补充 AAF 专属的模块识别能力。

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
【阶段 0：读取历史记录】（必须执行）
├─ 读取 $WORK_ROOT/temp/cache/aaf-debug/corrections.log（若存在），最近 5 条
├─ 读取 $WORK_ROOT/temp/cache/aaf-debug/history.log（若存在）
└─ 有纠正记录时，避免对同一模块重复犯错
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
    ↓
【阶段 8：记录日志】（必须执行）
├─ 成功 → 写入 $WORK_ROOT/temp/cache/aaf-debug/history.log
└─ 用户指出结论错误/修复无效/放弃 → 写入 $WORK_ROOT/temp/cache/aaf-debug/corrections.log
```

> 阶段 2-7 的详细定义见 user 级 `debug` Skill。

## 统计汇总（E1 量化评估）

每次调试完成后，输出统计行：

```
---
[统计] 统计：模块 [XXX] | 添加 X 处日志，收集 Y 条日志 | 定位问题 Z 个，修复 W 个 | 清理日志 V 处
```

## 自检清单（E4 元认知）

输出最终结果前，逐项自检：

| # | 检查项 | 标准 |
|---|--------|------|
| 1 | 模块识别 | 正确识别了用户描述的 AAF 模块 |
| 2 | 证据支撑 | 问题根因有日志/代码证据支撑，非猜测 |
| 3 | 修复验证 | 修复后重新运行确认问题解决 |
| 4 | 日志清理 | 调试日志已清理，无 AAF_DEBUG 残留 |

如有不通过项，在结果中标注 `[警告] 自检发现问题：[具体描述]`。

## 修复后验证（E5 自动化验证）

修复代码后：
1. 提示用户重新运行程序
2. 收集日志确认问题不再复现
3. 用 `search_content` 确认无 `AAF_DEBUG` 残留日志

## 历史归档（E2 记忆与复盘）

每次执行完成后，将摘要追加到 `$WORK_ROOT/temp/cache/aaf-debug/history.log`：

```bash
mkdir -p "$WORK_ROOT/temp/cache/aaf-debug"
[ $(wc -l < "$WORK_ROOT/temp/cache/aaf-debug/history.log" 2>/dev/null || echo 0) -lt 10 ] && \
  echo "[$(date '+%Y-%m-%d %H:%M')] [模块:XXX] 问题：[简述] | 根因：[简述] | 修复：[简述] | 状态：已解决/未解决" >> "$WORK_ROOT/temp/cache/aaf-debug/history.log"
```

## 负面反馈记录（E3 数据飞轮）

当用户指出调试建议有误（如根因判断错误、修复方案无效）时，将反馈追加到 `$WORK_ROOT/temp/cache/aaf-debug/corrections.log`：

```bash
mkdir -p "$WORK_ROOT/temp/cache/aaf-debug"
echo "[$(date '+%Y-%m-%d %H:%M')] [模块:XXX] [类型:根因错误/修复无效]
用户反馈: <用户说了什么>
正确方案: <YYY>
---" >> "$WORK_ROOT/temp/cache/aaf-debug/corrections.log"
```

执行前**应读取** `$WORK_ROOT/temp/cache/aaf-debug/corrections.log`（如存在），避免对同一模块重复犯错。

## 人机协作（E7）

- 添加调试日志前，**告知用户**将在哪些位置添加
- 问题定位后，修复方案需**用户确认**后再执行
- 如无法定位问题，**明确告知**而非猜测，建议用户提供更多信息
