---
name: replay
version: 18
category: test
description: 四端 UI 自动化录制与回放 — adb/web/mac/win，共享 core 内核（Flow 编排、报告、通知、前端）
---

# replay

跨平台 UI 自动化录制与回放工具集，支持 Android (ADB)、Web (Playwright)、macOS (CGEventTap)、Windows (pynput) 四端。

## 架构

```
replay/
├── SKILL.md          ← 本文件
├── flows/            ← Flow 定义仓库
├── scripts/          ← 所有 Python 代码
│   ├── core/         ← 共享内核（Flow CRUD/Runner/Report/Notify）
│   ├── adb/          ← Android 端（录制器 + ADB 执行器）
│   ├── web/          ← Web 端（Playwright 录制器 + 回放执行器）
│   ├── mac/          ← macOS 端（CGEventTap 录制器 + 执行器）
│   └── win/          ← Windows 端（pynput 录制器 + 执行器）
└── edit/             ← 前端资源
    ├── editor.html   ← 事件编辑器
    ├── flow.html     ← Flow 管理器
    ├── js/           ← 前端 JS
    └── css/          ← 样式
```

core 提供所有"录制后"能力，各端只保留**录制器**（平台采集层）和**执行器**（平台动作适配器）：

| 模块 | core 提供 | 各端保留 |
|------|-----------|----------|
| flow CRUD | core.flow（save/load/list/delete/resolve/flows_summary） | re-export |
| runner | core.runner（run_flow/run_steps + hook 注入） | setup_hook + step_executor |
| report | core.report（HTML 报告 + 关键截图） | — |
| notify | core.notify（企业微信 webhook） | — |
| schema | core.schema（normalize_step + 校验） | — |
| CLI | core.cli（build_parser + tips） | main.py 路由 |
| HTTP 服务 | core.hsrv（manage + editor） | — |
| 前端 | editor.html + flow.html + JS/CSS | — |

## CLI 命令

> ⚠️ 命令结构以 `zk replay <cmd> --help` 实际输出为准，本文档可能滞后于代码实现；修改命令提示前先实跑验证。

```bash
# ZixieKit 内（zk 命令；平台作为位置参数，run/report 自动解析平台）
zk replay record {adb|web|win} [名称]
zk replay play <录制目录>
zk replay edit <录制目录>
zk replay run <id>
zk replay report <id>
zk replay manage
zk replay doctor {adb|web|win}
zk replay init {adb|web|win}
zk replay install {adb|web}
zk replay clean --days 7

# 独立部署（python3；platform ∈ adb/web/win/mac）
python3 replay/scripts/{adb|web|win|mac}/cli/main.py record [名称]
python3 replay/scripts/{adb|web|win|mac}/cli/main.py play <录制目录>
python3 replay/scripts/{adb|web|win|mac}/cli/main.py edit <录制目录>
python3 replay/scripts/{adb|web|win|mac}/cli/main.py flow run <id>
python3 replay/scripts/{adb|web|win|mac}/cli/main.py flow report <id>
python3 replay/scripts/core/manage.py --port 8090
python3 replay/scripts/{adb|web|win|mac}/cli/main.py doctor
python3 replay/scripts/{adb|web|win|mac}/cli/main.py init
```

## Android (adb)

通过 getevent 录制手机触摸/按键操作，保存为 JSON，支持截图。

**支持的事件**：`tap`、`swipe`、`keyevent`、`text`、`adb`、`tips`

**前置条件**：ADB 已安装、手机 USB 连接并授权调试、Python 3.8+

## Web

基于 Playwright + CDP 的浏览器 UI 自动化。

**支持的事件**：`click`、`dblclick`、`navigate`、`type`、`scroll`、`keyboard`、`hover`、`select`、`check`、`wait`

**依赖**：playwright (Chromium)

## macOS

CGEventTap 捕获系统级鼠标/键盘事件，CGEventPost 精确回放。

**依赖**：`pyobjc-framework-Quartz`、`pyobjc-framework-Cocoa`

**前置条件**：macOS 10.15+、辅助功能权限、屏幕录制权限

## Windows

pynput 监听系统级鼠标/键盘事件，pyautogui/pynput 驱动回放。

**支持的事件**：`click`、`dblclick`、`rclick`、`type`、`keyboard`、`hotkey`、`scroll`、`drag`、`move`、`launch`、`quit`

**依赖**：pynput、Pillow

