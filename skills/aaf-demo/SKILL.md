---


name: aaf-demo
version: 2
category: aaf
description: AAF Demo 开发助手。当用户说"AAF-demo"、"AAF-Temp"时使用此 skill


---

# AAF Demo 开发助手
## 前置条件

- 项目定位：通过 `aaf-project-finder` Skill 定位（`$AAF_HOME/AndroidAppFactory`）
- `$AAF_HOME/AndroidAppFactory/temp/AAF-Temp` 存在（由 init.sh 自动创建）

## 工作流程

### Step 1: 定位 Demo 项目

```
AAF-Temp 位置: $AAF_HOME/AndroidAppFactory/temp/AAF-Temp
```

### Step 2: 加载开发规范

读取本 Skill 目录下的 `aaf_demo.mdc`，严格遵守其中的检查清单和开发规范。

### Step 3: 开发 Demo

在 AAF-Temp/App 中编写代码，遵循：
- 所有新代码在 App 模块中（不创建新 Module）
- 优先使用 AAF 框架组件
- 不修改 Template-Empty

### Step 4: 自动运行模式（可选）

用户说"自动运行"后，每次修改自动执行：
1. `./gradlew :App:assembleDebug`
2. 检测 ADB 设备
3. 安装 APK
4. 启动应用

## 规则依赖

| 规则 | 级别 | 路径 |
|------|------|------|
| AAF Demo 开发规范 | 必须 | `./aaf_demo.mdc`（本 Skill 目录下） |

## 注意事项

1. AAF-Temp 是临时项目，可随意修改
2. 编译失败时**停止并报告错误**，禁止继续
3. 设备未连接时**提示用户**，禁止静默跳过
