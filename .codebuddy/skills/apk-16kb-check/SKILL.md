---
name: apk-16kb-check
description: APK/AAB/AAR/工程目录 16KB 页面对齐检查助手 - 使用官方工具检查是否符合 Google Play 16KB 页面大小要求。支持 APK 直接检查、AAB 转 APK 后检查、AAR 编译为 APK 再检查、Android 工程目录自动构建后检查，失败时自动尝试修复。当用户说"Android 16KB"、"安卓 16KB"、"检查 16KB 对齐"时使用此 skill。
---

# APK/AAB/AAR/工程目录 16KB 页面对齐检查助手

> **背景**：自 2025 年 11 月 1 日起，Google Play 要求所有以 Android 15 (API 35) 及以上为目标的应用必须在 64 位设备上支持 16KB 页面大小。

## 触发关键词

- "Android 16KB"
- "安卓 16KB"
- "检查 16KB 对齐"
- "16KB alignment"
- "页面大小检查"
- "检查 AAR 对齐"
- "检查 AAB 对齐"
- "检查工程 16KB"

## 前置检查

执行本 Skill 前，必须先完成以下检查：

1. **读取 `.env` 文件**，确认 `WORK_ROOT` 环境变量可用（用于 cache 目录定位）
2. 在终端中 `export WORK_ROOT=<值>` 后再调用脚本
3. 若 `.env` 不存在或 `WORK_ROOT` 未配置，脚本会 fallback 到 `$HOME`（即 `~/temp/cache/apk-16kb-check/`）
4. **AAB 模式额外依赖**：`bundletool`（从 [GitHub Releases](https://github.com/google/bundletool/releases) 下载），用于将 AAB 转为 APK Set
5. **工程目录模式额外依赖**：项目需要能正常执行 `gradlew` 构建（Java、Gradle、SDK 等环境就绪）

## 检查内容

使用 **两个官方工具** 执行检查：

| 检查项 | 工具 | 说明 | 修复方式 |
|--------|------|------|----------|
| **APK 整体对齐** | `zipalign -c -P 16 -v 4` | 官方 Build-Tools 工具，验证 APK 内所有文件的 16KB 对齐 | `zipalign -P 16` 重新对齐（**脚本自动修复**） |
| **ELF LOAD 段对齐** | `check_elf_alignment.sh` | [AOSP 官方脚本](https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh)，检查 .so 文件的 ELF LOAD 段 alignment | 重新编译（NDK r28+ 或添加链接参数） |

> **压缩存储检测**：作为辅助检查，脚本还会检测 .so 是否被压缩存储（deflated），因为这是 16KB 对齐的前提条件。

### 两项检查的区别

| 维度 | 官方 zipalign 验证 | ELF LOAD 段对齐 |
|------|-------------------|-----------------|
| **检查对象** | .so 在 APK 内的 ZIP offset 对齐 | .so 文件内部的 ELF LOAD 段 alignment 属性 |
| **问题根因** | APK 打包/对齐时未使用 `-P 16` 参数 | NDK 编译时未指定 16KB 对齐参数 |
| **修复方式** | `zipalign -P 16` 重新对齐（脚本自动执行） | 重新编译（需要改代码/构建配置） |
| **自动修复** | ✅ 脚本自动执行（仅 APK 模式） | ❌ 需手动重新编译 |

### AAB 支持

AAB（Android App Bundle）是 Google Play 推荐的发布格式，其内部结构与 APK 不同，但同样包含 .so 文件。

**处理方式**：

| 检查项 | AAB 处理方式 | 说明 |
|--------|-------------|------|
| **ELF LOAD 段对齐** | 直接从 AAB 解压检查 | AAB 本质是 ZIP，.so 在 `base/lib/{abi}/` 下，可直接提取检查 ELF 段 |
| **zipalign 验证** | 用 `bundletool` 转 APK 后验证 | AAB 本身不需要 zipalign，但最终分发的 APK 需要 |

```
输入 AAB → 解压提取 .so 文件
        → 直接检查 ELF LOAD 段对齐（核心检查）
        → 用 bundletool build-apks 转为 APK Set（可选）
        → 从 APK Set 中提取 universal.apk
        → 对 universal.apk 执行 zipalign 验证
        → 汇总结果
```

**AI 执行 AAB 检查的步骤**：

1. **识别 AAB 文件**：用户传入 `.aab` 后缀的文件
2. **ELF 段检查（直接）**：
   ```bash
   # 解压 AAB 到临时目录
   unzip -o app.aab -d /tmp/aab_extract/
   # .so 文件位于 base/lib/{abi}/ 下
   # 对每个 64 位 .so 执行 ELF 段检查
   ```
3. **zipalign 检查（通过 bundletool）**：
   ```bash
   # 生成 universal APK
   java -jar bundletool.jar build-apks \
     --bundle=app.aab \
     --output=app.apks \
     --mode=universal
   # 解压 APK Set
   unzip app.apks -d /tmp/apks/
   # 对 universal.apk 执行 zipalign 验证
   zipalign -c -P 16 -v 4 /tmp/apks/universal.apk
   ```
4. **调用检查脚本**：将提取/转换后的 APK 传给 `check_alignment.py` 执行完整检查
5. **汇总结果**：合并 ELF 检查和 zipalign 检查结果

> **注意**：AAB 模式下 zipalign 检查是可选的，因为 Google Play 在分发时会自动处理对齐。**ELF LOAD 段对齐才是 AAB 的核心检查项**——如果 .so 的 ELF 段未对齐，无论 Google Play 如何处理打包，运行时都会有问题。

> **bundletool 路径**：AI 应先检查 `$ANDROID_HOME/` 或 `$PATH` 中是否有 `bundletool`，没有则提示用户下载。

### AAR 支持

AAR 中的 SO 文件都是压缩存储的（deflated），无法直接检查 16KB 对齐。
脚本自动从 cache 目录获取 [AAFFor16KB](https://github.com/bihe0832/AAFFor16KB) 空工程（首次自动 `git clone`），调用 `build_aar_apk.sh` 将 AAR 编译为 APK 后再检查。

**支持多 AAR 输入**：可以一次传入多个 AAR 文件，合并到同一个 APK 中一起检查。

```
输入 AAR → 检查 cache 目录有无 AAFFor16KB
         → 没有 → git clone --depth 1
         → 调用 build_aar_apk.sh（支持多 AAR + -c/--clean 选项）
         → 复制 AAR 到 libs/ → Gradle assembleRelease → 生成 APK → 检查 APK
```

**build_aar_apk.sh 用法**：

```bash
# 单个 AAR
build_aar_apk.sh <AAR文件路径> [输出目录]

# 多个 AAR（合并检查）
build_aar_apk.sh <AAR1> <AAR2> ... [输出目录]

# 清空 libs 目录后再构建（避免历史 AAR 干扰）
build_aar_apk.sh -c <AAR文件路径>
build_aar_apk.sh --clean <AAR1> <AAR2> ... [输出目录]
```

**输出规则**：
- 单 AAR：`{AAR名}_16kb_check.apk`
- 多 AAR：`multi_aar_16kb_check.apk`
- 输出目录默认为 AAFFor16KB 项目的 `build/16kb-check/` 目录

**cache 目录**：`$WORK_ROOT/temp/cache/apk-16kb-check/AAFFor16KB/`（未设 `WORK_ROOT` 时 fallback 到 `$HOME/temp/cache/apk-16kb-check/AAFFor16KB/`）

> **AAR 依赖自动适配**：`build_aar_apk.sh` 不再修改 `build.gradle`，AAR 依赖由 AAFFor16KB 项目的 Gradle 配置自动适配。

### Android 工程目录支持

当用户直接提供 Android 工程目录（而非 APK/AAR/AAB 文件）时，AI 自动完成「构建 → 检查 → 分析 → 修复」的完整闭环。

**识别条件**（满足任一）：
- 用户传入的路径是目录，且包含 `settings.gradle` 或 `settings.gradle.kts`
- 用户传入的路径是模块目录，且父目录包含 `settings.gradle`
- 用户明确说「检查这个工程/项目的 16KB 对齐」

**处理流程**：

```
输入工程目录
    ↓
【Step 1：识别项目结构】
├─ 定位 project_root（含 settings.gradle 的目录）
├─ 解析 settings.gradle 获取所有模块列表
├─ 识别 application 模块（含 com.android.application 插件的模块）
│   └─ 如果有多个 application 模块 → 询问用户选择
└─ 确定构建变体（默认 debug，用户可指定 release）
    ↓
【Step 2：执行构建】
├─ 运行 gradlew :{module}:assemble{Variant}
│   例如: ./gradlew :app:assembleDebug
├─ 构建失败 → 展示错误日志，提示用户修复后重试
└─ 构建成功 → 从 build/outputs/apk/{variant}/ 中定位 APK
    ↓
【Step 3：执行检查】
├─ 将构建产物 APK 传给 check_alignment.py
├─ SO 来源分析自动生效（因为 APK 路径在构建目录下）
└─ 后续流程与 APK 模式完全一致（阶段 2-6）
```

**构建变体选择**：

| 用户输入 | 构建命令 | 说明 |
|----------|----------|------|
| 仅工程目录 | `assembleDebug` | 默认 debug，构建速度快 |
| 工程目录 + "release" | `assembleRelease` | 用户明确要求 release |
| 工程目录 + "检查发布包" | `assembleRelease` | 语义识别为 release |
| 工程目录 + 具体变体名 | `assemble{Variant}` | 用户指定具体变体 |

**与阶段 6 的联动**：

工程目录模式天然满足阶段 6 的触发条件（APK 路径在项目构建目录下），因此检查完成后如果有问题，会自动进入阶段 6 的修复流程。这形成了完整的闭环：

```
工程目录 → 构建 APK → 检查 → 发现问题 → 定位文件 → 修改源码 → 提示重新构建验证
```

> **注意**：构建可能耗时较长，AI 应在执行构建前告知用户预计等待时间。

## 工作流程

```
用户请求检查 APK/AAB/AAR/工程目录 16KB 对齐
    ↓
【阶段 0：输入类型识别】
├─ .apk 文件 → 直接进入阶段 2
├─ .aab 文件 → 进入阶段 1.3（AAB 预处理）
├─ .aar 文件 → 进入阶段 1.5（AAR 预处理）
├─ 目录路径（含 settings.gradle）→ 进入阶段 1.2（工程构建）
└─ 用户未提供 → 询问文件/目录路径
    ↓
【阶段 1.2：工程目录预处理（仅工程目录输入）】
├─ 识别 project_root 和 application 模块
├─ 多个 application 模块时询问用户选择
├─ 确定构建变体（默认 debug）
├─ 执行 gradlew :{module}:assemble{Variant}
├─ 构建失败 → 展示错误日志，提示修复
└─ 构建成功 → 定位 APK 产物，进入阶段 2
    ↓
【阶段 1.3：AAB 预处理（仅 AAB 输入）】
├─ 直接解压 AAB 提取 .so 用于 ELF 段检查
├─ 检查 bundletool 是否可用
├─ 可用 → bundletool build-apks --mode=universal 生成 APK
├─ 不可用 → 仅做 ELF 段检查，跳过 zipalign 验证
└─ 生成 APK 后进入阶段 2
    ↓
【阶段 1.5：AAR 预处理（仅 AAR 输入）】
├─ 检查 cache 目录有无 AAFFor16KB 项目
├─ 没有 → git clone --depth 1
├─ 调用 build_aar_apk.sh（支持多 AAR + -c/--clean 选项）
├─ AAR 依赖由项目自动适配，无需手动修改配置
└─ 构建失败 → 提示用户手动构建
    ↓
【阶段 2：执行检查（两个官方工具）】
├─ 1. zipalign -c -P 16 -v 4 官方验证
├─ 2. check_elf_alignment.sh ELF LOAD 段对齐检查
└─ 辅助：检测 .so 压缩存储情况
    ↓
【阶段 2.5：SO 来源分析（APK 模式，自动触发）】
├─ 检测 APK 路径是否为 Android 项目的构建产物
├─ 是 → 反推项目根目录和构建模块
│   ├─ 扫描项目自身模块的编译产物中的 .so
│   ├─ 运行 gradlew dependencies 获取外部依赖树
│   ├─ 扫描 Gradle 缓存匹配依赖中的 .so
│   └─ 建立 .so → 模块/AAR 映射（标注"项目"或"外部"）
└─ 否 → 跳过（报告中来源列显示"未知"）
    ↓
【阶段 3：汇总结果】
├─ 展示两项检查的通过/未通过数量
├─ 压缩存储的 .so 单独标记，提示 useLegacyPackaging = false
├─ 列出未通过的 .so 文件清单（含来源模块信息）
└─ 生成 HTML 报告（两个 Tab，ELF 表格含"来源模块"列）
    ↓
【阶段 4：自动修复（zipalign 失败时，APK 和 AAR 均适用）】
├─ 压缩存储的 .so 无法自动修复，提示需修改构建配置
├─ zipalign -P 16 重新对齐 APK
├─ 重新验证修复后的 APK
└─ 告知用户修复结果和构建流程修改建议
    ↓
【阶段 5：给出修复建议】
├─ ELF 对齐问题 → NDK 重编译方案
├─ zipalign 对齐问题 → 构建流程中添加 zipalign -P 16
└─ 第三方 SDK 问题 → 联系供应商
    ↓
【阶段 6：构建目录自动修复（APK 为项目构建产物时）】
├─ 前提：APK 路径能反推到项目根目录（detect_project_root 成功）
├─ 且存在未通过的检查项
├─ AI 根据检查结果 + SO 来源分析，定位需要修改的具体文件
├─ 生成修改方案（含文件路径、修改内容、修改原因）
├─ 展示方案并等待用户确认
└─ 用户确认后直接修改项目源码
```

## 关键路径

> 所有路径均相对于 Skill 根目录（SKILL.md 所在目录）。

| 路径 | 说明 |
|------|------|
| `scripts/check_alignment.py` | **主检查脚本**（调用官方工具，含自动修复） |
| `scripts/check_elf_alignment.sh` | **AOSP 官方 ELF 对齐检查脚本**（从 [AOSP 源码](https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh) 下载） |
| `{文件同目录}/{文件名}_alignment_report.html` | 生成的 HTML 报告（默认位置） |

## 目录结构

```
skills/aaf/apk-16kb-check/
├── SKILL.md                  # 本文件
└── scripts/
    ├── check_alignment.py        # 主检查脚本（调用官方工具 + 自动修复 + AAR 支持）
    ├── check_elf_alignment.sh    # AOSP 官方 ELF 对齐检查脚本
    └── debug.keystore            # 自动修复签名用密钥库
```

> **完整独立项目**：AAR → APK 构建依赖 [AAFFor16KB](https://github.com/bihe0832/AAFFor16KB) 项目（运行时自动 clone 到 cache 目录）。

## 使用方法

```bash
# 检查单个 APK（失败时自动尝试修复）
python3 check_alignment.py <APK文件路径>

# 检查单个 AAR（自动 clone AAFFor16KB 编译为 APK 再检查，首次需联网）
python3 check_alignment.py <AAR文件路径>

# 检查多个 AAR（合并到同一 APK 一起检查）
python3 check_alignment.py <AAR1> <AAR2> ...

# 指定 HTML 输出路径
python3 check_alignment.py <APK文件路径> <HTML输出路径>

# 批量检查目录下所有 APK/AAR
python3 check_alignment.py --batch <目录路径>
```

**AAB 检查**（由 AI 在 Skill 层面处理，非脚本直接支持）：
```bash
# AI 自动执行以下步骤：
# 1. 解压 AAB 提取 .so 做 ELF 段检查
# 2. 用 bundletool 转为 universal APK
# 3. 对 universal APK 调用 check_alignment.py
```

**工程目录检查**（由 AI 在 Skill 层面处理）：
```bash
# AI 自动执行以下步骤：
# 1. 识别项目结构和 application 模块
# 2. 执行 gradlew :module:assembleDebug 构建
# 3. 定位构建产物 APK
# 4. 调用 check_alignment.py 检查
# 5. 发现问题时自动进入阶段 6 修复流程
```

**依赖**：
- Python 3.6+（仅使用标准库）
- `zipalign` / `apksigner`（来自 `ANDROID_HOME/build-tools/`，用于官方验证和自动修复）
- `objdump`（check_elf_alignment.sh 依赖，通常系统自带或来自 NDK）
- `git`（AAR 首次检查时 clone AAFFor16KB 项目）
- Java 17+、Gradle（AAR 构建和工程目录构建需要）
- `bundletool`（AAB 模式可选，用于转 APK，[下载地址](https://github.com/google/bundletool/releases)）

**输出**：
- 终端显示两项检查的完整汇总
- 压缩存储的 .so 单独标记并给出 `useLegacyPackaging = false` 修复建议
- 生成详细的 HTML 报告（两个 Tab：zipalign 验证 + ELF 对齐检查）
- **zipalign 失败时自动修复**：zipalign 重对齐 → apksigner 签名 → 重新验证

### 自动修复流程

```
zipalign 验证未通过 → 检查是否有 compressed 的 .so
                   → compressed：提示需修改 useLegacyPackaging，zipalign 无法修复
                   → zipalign -P 16 重新对齐
                   → 重新验证对齐后的 APK
                   → 输出修复结果和构建建议
```

> ⚠️ 自动修复后的 APK **未签名**，仅用于**验证对齐方案是否可行**。正式发布需在构建流程中添加 `zipalign -P 16` 并使用正式签名。

## 修复方案

### 0. 压缩存储问题（优先级最高）

.so 被压缩存储（deflated）时，系统无法直接 mmap 加载，16KB 对齐无从谈起。**这是所有对齐检查的前提条件。**

```groovy
android {
    packagingOptions {
        jniLibs {
            useLegacyPackaging = false  // .so 以 stored（未压缩）方式打包
        }
    }
}
```

> 📌 AGP 8.5.1+ 已默认设置此选项，低版本需手动配置。

### 1. ELF 段对齐问题（需重新编译）

**方案 A：升级 NDK（推荐）**

```groovy
// 使用 NDK r28+ 默认支持 16KB 对齐
android {
    ndkVersion "28.0.12433566"  // 或更高版本
}
```

**方案 B：添加链接参数（NDK r27 及以下）**

```cmake
# CMakeLists.txt
target_link_options(your_lib PRIVATE
    -Wl,-z,max-page-size=16384
)
```

或在 `build.gradle` 中：

```groovy
android {
    defaultConfig {
        externalNativeBuild {
            cmake {
                arguments "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"
            }
        }
    }
}
```

**方案 C：第三方 SDK**

如果未通过的 .so 来自第三方 SDK：
1. 检查 SDK 是否有新版本已适配 16KB
2. 联系 SDK 供应商要求提供适配版本
3. 临时方案：在 manifest 中声明 `android:pageSizeCompat="true"`（不推荐长期使用）

### 2. zipalign 对齐问题（打包修复）

**方案 A：升级 AGP（推荐）**

```groovy
// 使用 AGP 8.5.1+ 自动支持
plugins {
    id 'com.android.application' version '8.5.1'
}
```

**方案 B：手动 zipalign（check_alignment.py 自动执行）**

```bash
# 对 APK 执行 16KB 对齐
zipalign -P 16 -f 4 input.apk output_aligned.apk

# 验证对齐结果
zipalign -c -P 16 -v 4 output_aligned.apk

# 正式发布时：先 zipalign 再签名
# zipalign -P 16 -f 4 unsigned.apk aligned.apk
# apksigner sign --ks release.keystore aligned.apk
```

> ✅ `check_alignment.py` 在检测到 zipalign 未通过时会**自动执行 zipalign 对齐并重新验证**。修复后的 APK 未签名，仅用于验证方案。
>
> ⚠️ **注意**：正式发布流程中，zipalign 必须在签名之前执行，签名后再执行 zipalign 会破坏签名。

## 检查结果解读

### 通过条件

| 检查项 | 通过条件 | 官方工具 |
|--------|----------|----------|
| APK 整体对齐 | `zipalign -c -P 16 -v 4` 输出 "Verification successful" | zipalign (Build-Tools 35+) |
| ELF LOAD 段对齐 | 所有 .so 的 LOAD 段 alignment ≥ 2\*\*14 (16KB) | check_elf_alignment.sh (AOSP) |

### 常见问题

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| zipalign 报 (OK - compressed) | .so 被压缩存储 | 设置 `useLegacyPackaging = false` 后重新打包 |
| ELF 检查报 UNALIGNED | NDK 版本过低或缺少参数 | 升级 NDK r28+ 或添加链接参数 |
| zipalign 通过但 ELF 未通过 | APK 打包对齐了，但 .so 编译时未对齐 | 重新编译 .so（NDK r28+ 或链接参数） |
| 大量第三方 .so UNALIGNED | SDK 未适配 16KB | 升级 SDK 或联系供应商 |
| check_elf_alignment.sh 不可用 | 未安装 objdump | 安装 binutils 或 NDK（llvm-objdump） |

### 官方验证命令

```bash
# zipalign 验证（需 Build-Tools 35.0.0+）
zipalign -c -P 16 -v 4 APK_NAME.apk

# ELF 对齐检查（AOSP 官方脚本）
check_elf_alignment.sh APK_NAME.apk
```

## 参考文档

- [Google 官方文档：支持 16KB 的页面大小](https://developer.android.com/guide/practices/page-sizes?hl=zh-cn)
- [AOSP check_elf_alignment.sh 源码](https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh)
- **截止日期**：2025 年 11 月 1 日起强制执行
- **适用范围**：所有以 Android 15 (API 35) 及以上为目标的新应用和更新

## 自检清单

执行检查后，AI 应逐项确认：

| # | 检查项 | 标准 |
|---|--------|------|
| 1 | 文件类型识别 | 正确区分 APK/AAB/AAR/工程目录，AAR 自动触发 AAFFor16KB 构建，AAB 自动提取或转 APK，工程目录自动构建 |
| 2 | 压缩存储检测 | 识别并标记被压缩存储的 .so，提示 `useLegacyPackaging = false` |
| 3 | zipalign 验证完成 | 运行 `zipalign -c -P 16 -v 4` 并输出结果 |
| 4 | ELF 段检查完成 | 运行 `check_elf_alignment.sh` 并输出结果（或脚本不可用时已提示） |
| 5 | HTML 报告已生成 | 报告包含两个 Tab：zipalign 验证 + ELF 对齐检查（含来源模块列） |
| 6 | 自动修复 | zipalign 失败时自动尝试了 zipalign 重对齐修复（APK 和 AAR 均适用） |
| 7 | 修复建议 | 针对不同问题类型给出了具体修复方案 |
| 8 | SO 来源分析 | APK 为项目构建产物时，自动分析 .so 归属：运行 gradlew dependencies + 扫描 Gradle 缓存，标注"项目模块"或"外部依赖(group:artifact:version)" |
| 9 | 第三方识别 | 基于来源分析结果，在报告和终端中标注哪些未通过的 .so 来自第三方依赖，给出对应的依赖坐标 |
| 10 | 构建目录自动修复 | APK 为项目构建产物且存在未通过项时，定位具体文件生成修改方案，用户确认后直接修改 |
| 11 | AAB 支持 | AAB 输入时正确执行 ELF 段检查（直接提取）和 zipalign 验证（bundletool 转 APK） |
| 12 | 工程目录支持 | 工程目录输入时自动构建 APK，构建成功后走完整检查流程，与阶段 6 形成闭环 |

### SO 来源分析说明

当用户提供的 APK 路径符合 Android 项目构建产物模式（如 `app/build/outputs/apk/release/app-release.apk`）时，脚本自动执行以下分析：

1. **反推项目根目录**：从 APK 路径匹配 `build/outputs/apk/` 模式，向上查找 `settings.gradle`
2. **扫描项目模块**：检查各模块的 `build/intermediates/merged_native_libs/` 和 `src/main/jniLibs/` 中的 .so
3. **获取依赖树**：运行 `gradlew :module:dependencies --configuration releaseRuntimeClasspath`
4. **Gradle 缓存匹配**：在 `~/.gradle/caches/transforms-*/` 和 `modules-*/` 中查找每个依赖包含的 .so
5. **建立映射**：每个 .so 标注来源为"项目模块"（`:module_name`）或"外部依赖"（`group:artifact:version`）

> 来源分析是**增量能力**，不影响核心检查流程。即使分析失败（如 gradlew 不可用），检查和报告仍正常生成，来源列显示"未知"。

## 阶段 6：构建目录自动修复

> **核心思路**：当 APK 路径能反推到 Android 项目根目录时，AI 不仅给出修复建议，还能直接定位并修改项目源码。

### 触发条件

同时满足以下条件时自动进入阶段 6：

1. APK 路径能反推到项目根目录（`detect_project_root` 成功）
2. 检查结果中存在未通过的项（压缩存储 / zipalign / ELF 对齐）
3. SO 来源分析已建立映射（知道哪些 .so 来自项目模块、哪些来自外部依赖）

### 修复决策矩阵

根据问题类型和 SO 来源，AI 采取不同的修复策略：

| 问题类型 | SO 来源 | AI 操作 | 需要修改的文件 |
|----------|---------|---------|---------------|
| **压缩存储** | 任意 | 直接修改 | 构建模块的 `build.gradle(.kts)` |
| **ELF 段未对齐** | 项目模块（CMake） | 直接修改 | `CMakeLists.txt` 或 `build.gradle(.kts)` |
| **ELF 段未对齐** | 项目模块（ndk-build） | 直接修改 | `Android.mk` 或 `build.gradle(.kts)` |
| **ELF 段未对齐** | 外部依赖 | 仅建议 | 无法修改，提示升级依赖或联系供应商 |
| **ELF 段未对齐** | 来源未知 | 仅建议 | 无法确定，提示用户手动确认 |
| **zipalign 未对齐** | 任意 | 直接修改 | 构建模块的 `build.gradle(.kts)` 或项目级 AGP 版本 |

### 自动修复流程

```
检查结果存在未通过项 + APK 为项目构建产物
    ↓
【Step 1：定位项目文件】
├─ 从 project_root 找到构建模块的 build.gradle(.kts)
├─ 扫描是否有 CMakeLists.txt / Android.mk（项目自有 SO）
├─ 读取项目级 build.gradle(.kts) 获取 AGP 版本和 NDK 版本
└─ 读取 gradle.properties 获取相关配置
    ↓
【Step 2：生成修改方案】
├─ 按问题优先级排序：压缩存储 > ELF 对齐 > zipalign 对齐
├─ 每个修改项包含：
│   ├─ 📄 文件路径（绝对路径）
│   ├─ 📝 修改内容（before → after）
│   ├─ 💡 修改原因（关联到哪些 .so 的哪个检查项）
│   └─ ⚠️ 影响范围（是否影响其他模块/功能）
└─ 外部依赖问题单独列出，标注依赖坐标和建议操作
    ↓
【Step 3：展示方案并等待确认】
├─ 向用户展示完整修改方案
├─ 区分「可自动修复」和「需手动处理」
└─ 等待用户确认（遵循多方案选择格式）
    ↓
【Step 4：执行修改】
├─ 用户确认后，使用编辑工具修改对应文件
├─ 修改完成后提示用户重新构建并再次检查
└─ 外部依赖问题提醒用户手动处理
```

### 具体修改模板

#### 1. 压缩存储修复

**定位文件**：`{project_root}/{module}/build.gradle(.kts)`

**查找**：`android { }` 块，检查是否已有 `packagingOptions` / `packaging` 配置

**修改内容**（Kotlin DSL）：
```kotlin
android {
    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
    }
}
```

**修改内容**（Groovy DSL）：
```groovy
android {
    packagingOptions {
        jniLibs {
            useLegacyPackaging = false
        }
    }
}
```

#### 2. ELF 段对齐修复（项目模块 - CMake）

**定位文件**：
- 优先：`{module}/src/main/cpp/CMakeLists.txt`（或 `externalNativeBuild.cmake.path` 指定的路径）
- 备选：`{module}/build.gradle(.kts)` 中的 cmake arguments

**方案 A — 修改 CMakeLists.txt**：
```cmake
# 在 target_link_libraries 之后添加
target_link_options(${TARGET_NAME} PRIVATE -Wl,-z,max-page-size=16384)
```

**方案 B — 修改 build.gradle(.kts)**：
```kotlin
android {
    defaultConfig {
        externalNativeBuild {
            cmake {
                arguments += "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"
            }
        }
    }
}
```

**方案 C — 升级 NDK 版本**（推荐，一劳永逸）：
```kotlin
android {
    ndkVersion = "28.0.12433566"  // r28+
}
```

#### 3. zipalign 对齐修复

**定位文件**：项目级 `build.gradle(.kts)`

**检查 AGP 版本**：如果 < 8.5.1，建议升级

```kotlin
plugins {
    id("com.android.application") version "8.5.1" // 或更高
}
```

### 注意事项

1. **只修改项目模块的问题**：外部依赖的 .so 无法通过修改项目源码修复
2. **优先推荐升级方案**：升级 NDK/AGP 是最简单且一劳永逸的方案
3. **修改前必须确认**：所有修改必须展示给用户并获得确认后才执行
4. **修改后提示重新构建**：修改源码后需要重新构建 APK 并再次运行检查验证
5. **DSL 格式适配**：根据项目实际使用的 Groovy / Kotlin DSL 格式生成对应代码
6. **不破坏现有配置**：修改时保留已有的配置项，仅追加或修改必要的部分
