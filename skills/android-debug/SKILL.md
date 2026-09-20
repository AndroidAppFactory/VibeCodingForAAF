---



version: 2
category: android
name: android-debug
description: Android 代码调试助手 - LLM 主导的代码调试分析。负责理解代码、添加日志、分析日志、给出修复建议



---
# Android 代码调试助手

> LLM 主导的调试分析。日志抓取由 `android-log` skill 的脚本完成，本 skill 负责代码理解、日志分析、修复建议。
## 工作流程

```
用户请求调试
    ↓
【阶段 0】读取历史 — 调用 android-log.sh corrections，避免重复同类错误
    ↓
【阶段 1】识别 + 收集 — 自动识别项目/模块，只问"具体什么问题？"
    ↓
【阶段 2】理解代码 — 定位文件、阅读逻辑、检查现有日志
    ↓
【阶段 3】日志准备 — 优先用现有日志；必要时添加，统一 TAG: APP_DEBUG
    ↓
【阶段 4】等待运行 — 清空日志(clear) → 请用户运行复现 → 完成后说"结束"
    ↓
【阶段 5】日志分析 — 调用 android-log.sh logcat/errors 抓取 → AI 分析 → 定位原因
    ↓
【阶段 6】修复 + 自检 — 给出修复建议（须有日志证据支撑）
    ↓
【阶段 7】清理 — 移除调试日志（仅移除新增的），恢复代码
    ↓
【阶段 8】记录 — 调用 android-log.sh record/correct 写入记录
```

## 依赖脚本

`android-log` skill 的 `scripts/android_log.sh`：

```bash
bash scripts/android_log.sh clear                    # 阶段4：清空旧日志
bash scripts/android_log.sh logcat [TAG]             # 阶段5：抓取调试日志
bash scripts/android_log.sh logcat-errors [TAG]      # 阶段5：抓取调试日志 + 异常
bash scripts/android_log.sh logcat-raw [FILTER]      # 阶段5：抓取原始 logcat
bash scripts/android_log.sh record "摘要"            # 阶段8：记录调试历史
bash scripts/android_log.sh correct "类型" "模块" "AI判断" "用户反馈"  # 阶段8：记录纠正
bash scripts/android_log.sh corrections              # 阶段0：读取纠正记录
```

## AI 执行策略

### 简化对话（只问问题现象）

- ✅ 问：具体是什么问题？
- ❌ 不问：如何复现？哪个项目？（已自动识别）

### 日志决策

```
现有日志覆盖关键路径 → 直接使用
不够 → 仅在必要位置添加新日志
```

### 新增日志格式

```
DEBUG_TAG = "APP_DEBUG"
>>> functionName: param=value    // 入口
--- state: value                  // 关键变量 / 分支
<<< functionName: return=value    // 出口
```

### 自检（阶段 6 修复建议前）

1. 问题原因有日志证据支撑（非纯推测）
2. 修复建议针对根因（非表面现象）
3. 修复建议不会引入新问题

无法确认根因 → 增加日志进入下一轮，不给不确定的修复建议。

### 统计汇总（阶段 6 后输出）

```
统计：调试轮次 X | 添加日志 N 行 | 分析日志 M 行 | 定位问题 P 个 | 修复建议 S 个
```

## 注意事项

- 不要记录敏感信息，不在循环中加大量日志
- 调试完成后必须清理新增日志，使用现有日志时无需清理
- 添加日志后验证编译通过
- 用 git 跟踪变更，便于恢复
