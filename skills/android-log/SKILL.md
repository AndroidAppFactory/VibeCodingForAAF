---



version: 3
category: android
name: android-log
description: Android 日志抓取工具 - 抓取、清空、过滤 logcat 日志，查看调试历史和纠正记录



---
# Android 日志抓取工具

纯脚本驱动，LLM 仅做调度。所有操作通过 `scripts/android_log.sh` 执行。
## 脚本用法

```bash
# 抓取调试日志（默认 TAG=APP_DEBUG）
bash scripts/android_log.sh logcat [TAG]

# 抓取调试日志 + 异常
bash scripts/android_log.sh logcat-errors [TAG]

# 抓取原始 logcat（支持 grep 正则过滤）
bash scripts/android_log.sh logcat-raw [FILTER]

# 清空 logcat 缓冲区
bash scripts/android_log.sh clear

# 查看调试历史（最近 10 条）
bash scripts/android_log.sh history

# 查看纠正记录（最近 5 条）
bash scripts/android_log.sh corrections

# 记录调试历史
bash scripts/android_log.sh record "模块:X | 问题:Y | 根因:Z | 轮次:N | 已修复:是/否"

# 记录纠正
bash scripts/android_log.sh correct "结论错误" "模块名" "AI判断" "用户反馈"
```

## 典型工作流

```
用户说"抓日志"
    ↓
1. clear — 清空旧日志
    ↓
2. 用户运行复现
    ↓
3. logcat / logcat-errors — 抓取日志
    ↓
4. 输出日志内容供 AI 或用户分析
```

## 注意事项

- 设备必须通过 ADB 连接
- TAG 默认 `APP_DEBUG`，可传参覆盖
- 历史和纠正记录存储在 `${WORK_ROOT}/temp/cache/debug/`
