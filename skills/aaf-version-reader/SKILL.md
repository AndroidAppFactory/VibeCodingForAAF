---


version: 2
category: aaf
name: aaf-version-reader
description: 读取 AAF 框架最新配置和版本信息。从 $AAF_HOME/AndroidAppFactory 提取 SDK 配置、版本号等结构化数据。当用户说"提取 AAF 配置"、"提取AAF版本号"时使用此 skill


---

# AAF Version Reader

> **AI 必须逐项检查以下清单，禁止跳过或自编检查项。**

| # | 检查项 | 必须 | 对应章节 |
|---|--------|:----:|----------|
| 1 | 每个模块独立查询版本，禁止假设所有模块相同 | 是 | 读取内容 |
| 2 | 禁止用 git tag 推断版本 | 是 | 读取内容 |
| 3 | 用户追问时回 AAF 源码交叉验证 | 是 | 读取内容 |
| 4 | module key 必须在源文件中实际搜索，禁止推导 | 是 | 读取内容 |
| 5 | 禁止在模块 `build.gradle` 中添加依赖 | 是 | 返回格式 |
| 6 | 依赖关系必须单向，禁止循环依赖 | 是 | 返回格式 |

## 前置条件

- 项目定位：通过 `aaf-project-finder` Skill 定位（`$AAF_HOME/AndroidAppFactory`），找不到则报错终止

## 读取内容

### 1. 拉取最新代码

```bash
cd "$AAF_HOME/AndroidAppFactory"
git status --short
# 工作区干净 → git pull --rebase
# 有本地变更 → 跳过，标注"使用本地版本"
```

### 2. 核心配置

| 来源文件 | 读取项 |
|---------|--------|
| `config.gradle` | compileSdkVersion, buildToolsVersion, libMinSdkVersion, targetSdkVersion, kotlin_version |
| `build.gradle` | Gradle 插件版本 |
| `gradle/wrapper/gradle-wrapper.properties` | Gradle 发行版版本 |
| `dependencies.gradle` | ext.moduleVersionName（模块默认版本） |
| `APPTest/build.gradle` | kotlinCompilerExtensionVersion（Compose Compiler） |

### 3. 模块版本

> `dependencies_*.gradle` 文件与模块类型的映射关系见 `aaf-project-finder` Skill。

从 `dependencies_*.gradle` 文件中按 artifactId 查找各模块版本。

查找方法（兼容两种输入格式）：

用户可能用**模块 key**（驼峰，如 `LibDownload`）或 **artifactId**（短横线，如 `lib-download`）查询。

```bash
# 输入为 artifactId（含短横线）→ 直接按 artifactId 搜索
grep -B 5 '"artifactId".*"lib-download"' dependencies_*.gradle | grep '"version"'

# 输入为模块 key（驼峰）→ 按 key 搜索（key 是 map 的键名）
grep -A 3 '"LibDownload"' dependencies_*.gradle | grep '"version"'
```

**判断规则**：输入含 `-` → 视为 artifactId；否则视为模块 key。

> ⚠️ 模块 key 与 artifactId **不是简单的驼峰↔短横线转换**（如 `LibCommonUtils` → `lib-utils-common`），必须在源文件中实际搜索，禁止自行推导。

找不到特定版本 → 使用 `ext.moduleVersionName` 并标注"默认版本"。

### 版本查找约束（强制）

| # | 约束 |
|---|------|
| 1 | AAF 是单仓多模块项目，每个模块有独立版本号，**禁止假设所有模块版本相同** |
| 2 | **禁止用 git tag 推断版本**（tag 只标记发布批次，不代表所有模块都升到该版本） |
| 3 | 优先用 artifactId 在 `dependencies_*.gradle` 中查找精确版本 |
| 4 | 找不到时次优使用 `ext.moduleVersionName`，并验证 Maven 发布状态 |
| 5 | 编译器类模块（如 `lib-router-compiler`）有独立版本，不跟随通用版本 |
| 6 | 模块找不到时检查 `dependencies_deprecated.gradle`（可能已废弃） |
| 7 | 用户追问版本正确性时，必须回到 AAF 源码交叉验证，禁止只看已修改文件 |

**版本优先级**：精确版本 → `ext.moduleVersionName` → Maven 已发布版本

### 依赖编辑约束（强制）

> 本节约束 LLM **手动编辑依赖**时的行为（如用户说"帮我给 LibDownload 加个依赖"）。
> 仅适用于 AAF 框架项目（AndroidAppFactory），Template-Android/Empty 使用标准方式。

| # | 约束 |
|---|------|
| 1 | **禁止在模块 `build.gradle` 中添加依赖**，所有依赖统一在根目录 `dependencies_*.gradle` 中声明 |
| 2 | 根据模块类型选择正确的配置文件（Lib→`dependencies_lib.gradle`、Common→`dependencies_common.gradle`、废弃→`dependencies_deprecated.gradle`） |
| 3 | 依赖关系必须单向，禁止循环依赖（底层模块不依赖上层模块） |
| 4 | 外部库版本通过 `project.xxx.library` 引用，在 `config.gradle` 中统一定义 |
| 5 | AAF 模块版本号由编译脚本自动更新，不需要手动维护 |
| 6 | 添加依赖后必须执行 `./gradlew :ModuleName:compileDebugKotlin` 验证 |

**依赖配置格式**：

```gradle
"ModuleName" : [
    "version"            : "版本号",
    "artifactId"         : "maven-artifact-id",
    "apidependenciesList": [
        "依赖模块1",
        project.xxx.library_name,
    ]
]
```

**配置文件选择**：见 `aaf-project-finder` Skill 中的"模块类型与配置文件映射"。

### 4. 目标项目对比（可选）

如调用者提供目标项目路径，读取其当前 AAF 依赖版本并列出差异。

## 返回格式

```
## AAF 最新配置

| 配置项 | 值 |
|--------|-----|
| moduleVersionName | x.x.x |
| compileSdkVersion | xx |
| ... | ... |

## 模块版本

| 模块 (artifactId) | 版本 | 来源文件 |
|-------------------|------|---------|
| common-wrapper | x.x.x | dependencies_common.gradle |
| ... | ... | ... |

## 需要更新的项（如有目标项目）

| 配置项 | AAF 最新 | 目标项目当前 |
|--------|---------|------------|
| ... | ... | ... |
```