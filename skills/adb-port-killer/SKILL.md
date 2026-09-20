---


version: 2
category: android
name: adb-port-killer
description: ADB 端口释放工具 - 查看并释放被占用的 ADB 端口（5037），自动保留 Android Studio 等保护进程
disable-model-invocation: true


---
# ADB 端口释放工具

## 触发方式

### 通过 aafkit 工具（集成环境）
```bash
# 检查端口状态
aaf kill-adb check

# 强制释放端口
aaf kill-adb kill

# 优雅关闭 ADB server
aaf kill-adb kill-server
```

### 通过独立 Python 脚本（独立环境）
```bash
# 检查端口状态
python3 scripts/adb_port_manager.py check

# 强制释放端口
python3 scripts/adb_port_manager.py kill

# 优雅关闭 ADB server
python3 scripts/adb_port_manager.py kill-server

# 支持指定端口号
python3 scripts/adb_port_manager.py check --port 5038

# JSON 格式输出
python3 scripts/adb_port_manager.py check --json
```

### 通过 slash 命令
`/adb.reset`（仅 slash 命令触发，不响应自然语言）

## 保护进程机制

工具会**自动保留**以下进程，不会 kill：

| 保护进程 | 说明 |
|----------|------|
| `studio` | Android Studio 的 ADB 连接 |
| `idea` | IntelliJ IDEA 的 ADB 连接 |
| `java` | 其他 Java IDE 的 ADB 连接 |

只 kill `adb` server 等非保护进程，Studio 会自动重连。

## 自动化流程

Python 实现封装了完整操作，无需手动执行 kill：

```
1. 执行 kill-server（优雅关闭）
   ├─ 尝试 adb kill-server（优雅关闭）
   ├─ 失败时自动回退到强制 kill 非保护进程
   ├─ 自动保留 studio/idea/java 等保护进程
   └─ 验证非保护进程是否已清除
       ↓
2. 报告结果
   ├─ 端口已释放（studio 保留）→ 提示成功
   └─ 仍有非保护进程占用 → 提示失败原因
```

## 工具用法

### aafkit 工具（集成环境）
```bash
# 检查端口状态（JSON 输出，区分 killable/protected）
aaf kill-adb check

# 优雅关闭（推荐，先 adb kill-server，失败则强制 kill 非保护进程）
aaf kill-adb kill-server

# 强制 kill 占用 5037 的非保护进程
aaf kill-adb kill

# 支持指定端口号
aaf kill-adb check --port 5038

# JSON 格式输出
aaf kill-adb check --json
```

### 独立 Python 脚本（独立环境）
```bash
# 检查端口状态（JSON 输出，区分 killable/protected）
python3 scripts/adb_port_manager.py check

# 优雅关闭（推荐，先 adb kill-server，失败则强制 kill 非保护进程）
python3 scripts/adb_port_manager.py kill-server

# 强制 kill 占用 5037 的非保护进程
python3 scripts/adb_port_manager.py kill

# 支持指定端口号
python3 scripts/adb_port_manager.py check --port 5038

# JSON 格式输出
python3 scripts/adb_port_manager.py check --json

# 终止指定 PID
python3 scripts/adb_port_manager.py kill-pid 12345
```