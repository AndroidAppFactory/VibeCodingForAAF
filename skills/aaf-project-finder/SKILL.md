---


version: 2
category: aaf
name: aaf-project-finder
description: 定位 AAF 相关项目位置。通过 AAF_HOME 环境变量定位 AndroidAppFactory 等项目路径


---
# AAF Project Finder

## 定位策略

读取环境变量 `AAF_HOME`（在 `~/.zixiekit/.env` 中配置），所有 AAF 项目均位于该目录下： <!-- zk-lint: ignore hardcoded.zixiekit-path -->

```
$AAF_HOME/
├── AndroidAppFactory        ← 框架核心（必须存在）
├── AndroidAppFactory-Doc    ← 文档（可选）
├── Template-AAF             ← 完整示例（可选）
├── Template_Android         ← 基础示例（可选）
└── Template-Empty           ← 最简示例（可选）
```

## 执行逻辑

```bash
# 1. 读取 AAF_HOME
AAF_HOME="${AAF_HOME:?错误: 未设置 AAF_HOME 环境变量，请在 ~/.zixiekit/.env 中配置}" <!-- zk-lint: ignore hardcoded.zixiekit-path -->

# 2. 验证核心项目
if [ ! -d "$AAF_HOME/AndroidAppFactory" ]; then
    echo "错误: $AAF_HOME/AndroidAppFactory 不存在" >&2
    exit 1
fi

# 3. 返回路径
echo "AndroidAppFactory=$AAF_HOME/AndroidAppFactory"
```

## 模块源码查找

### 核心原理

AAF 的 Gradle 模块目录名（如 `LibAudio`）和 Maven artifactId（如 `lib-audio`）之间遵循命名约定，但**不完全一致**。查找源码时必须通过配置文件建立映射，不凭猜测。

### 三步查找法

**第 1 步：从 artifactId 反查模块目录名**

在 `$AAF_HOME/AndroidAppFactory/` 下扫描所有 `dependencies_*.gradle` 文件，查找包含目标 `artifactId` 的模块块：

```
"ModuleName" : [
    "artifactId" : "target-artifact",
    "version"    : "x.x.x",
]
```

`ModuleName` 即为 `$AAF_HOME/AndroidAppFactory/<ModuleName>/` 源码目录。

**第 2 步：从类名/包名推断 artifactId**

如果已知类名或 import 路径（如 `com.bihe0832.android.lib.audio.AudioManager`），按以下规则推断：
- 包名前缀 `com.bihe0832.android.` 固定
- 第二段为模块类型（`lib` / `common` / `services` 等）
- 第三段为核心功能名（如 `audio` → artifactId 可能是 `lib-audio`）

**第 3 步：通过 dependencies_*.gradle 确认**

推断后在 `dependencies_*.gradle` 中精确查找验证。

### 模块类型与配置文件映射

| 配置文件 | 模块类型 | 说明 |
|----------|---------|------|
| `dependencies_lib.gradle` | lib | 基础库模块 |
| `dependencies_common.gradle` | common | 通用封装模块 |
| `dependencies_services.gradle` | services | 服务类模块 |
| `dependencies_tbs.gradle` | tbs | TBS 相关模块 |
| `dependencies_lock_widget.gradle` | lock_widget | 锁屏组件模块 |
| `dependencies_asr.gradle` | asr | 语音识别模块 |
| `dependencies_deprecated.gradle` | deprecated | 已废弃模块 |

### 命名约定

模块目录名（ModuleName）为 PascalCase（如 `LibAudio`、`LibCommonWrapper`），artifactId 为 kebab-case（如 `lib-audio`、`common-wrapper`）。

转换规则：`PascalCase` → 每个大写字母前插入 `-` 并全小写（`LibAudio` → `lib-audio`）。

### 排除规则

以下模块不对外发布，查找时跳过：
- `APP*` 开头的模块（如 `APPTest`、`APPModule`）
- `Base*` 开头的模块（如 `BaseDebug`、`BaseTest`）

---

## 常见场景

### 场景 1：用户问"LibAudio 的源码在哪里"

1. 确认 `AAF_HOME` 已配置
2. 目录即 `$AAF_HOME/AndroidAppFactory/LibAudio/`
3. 验证目录存在

### 场景 2：用户问"com.bihe0832.android:lib-audio:7.0.0 的源码"

1. 从 artifactId `lib-audio` 反查：扫描 `dependencies_*.gradle` 找到 `"artifactId" : "lib-audio"` 所在的 `ModuleName`
2. 或直接用命名规则反推：`lib-audio` → `LibAudio`
3. 源码路径：`$AAF_HOME/AndroidAppFactory/LibAudio/`

### 场景 3：用户问"这个项目用了哪些 AAF 模块，源码在哪"

1. 在项目 `dependencies.gradle` 或 `build.gradle` 中搜索 `com.bihe0832.android:` 依赖
2. 对每个 artifactId 执行三步查找法
3. 汇总返回模块名 → 源码路径映射

---

## 返回格式

```
## AAF 项目位置

| 项目 | 路径 | 状态 |
|------|------|------|
| AndroidAppFactory | $AAF_HOME/AndroidAppFactory | ✓ |
| Template-AAF | $AAF_HOME/Template-AAF | ✓ / 不存在 |
| ... | ... | ... |
```

**AndroidAppFactory 找不到 → 报错终止，不继续。**