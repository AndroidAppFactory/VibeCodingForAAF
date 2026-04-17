---
name: apk-16kb-check
description: APK/AAB/AAR/工程目录 16KB 页面对齐检查助手 - 使用官方工具检查是否符合 Google Play 16KB 页面大小要求。支持 APK 直接检查、AAB 转 APK 后检查、AAR 直接解压检查 ELF 段、Android 工程目录自动构建后检查，失败时自动尝试修复。当用户说"Android 16KB"、"安卓 16KB"、"检查 16KB 对齐"时使用此 skill。
---

# APK/AAB/AAR/工程目录 16KB 页面对齐检查助手

> **背景**：自 2025 年 11 月 1 日起，Google Play 要求所有以 Android 15 (API 35) 及以上为目标的应用必须支持 16KB 页面大小。

## 触发关键词

"Android 16KB"、"安卓 16KB"、"检查 16KB 对齐"、"16KB alignment"、"页面大小检查"、"检查 AAR/AAB/工程 16KB"

## 前置检查

1. 读取 `.env` 文件获取 `WORK_ROOT`（缺失则 fallback 到 `$HOME`）
2. AAB 模式需要 `bundletool`（[GitHub Releases](https://github.com/google/bundletool/releases)）
3. 工程目录模式需要 Java/Gradle/SDK 环境就绪

## 检查内容

| 检查项 | 工具 | 修复方式 |
|--------|------|----------|
| **APK 整体对齐** | `zipalign -c -P 16 -v 4` | `zipalign -P 16` 重新对齐（脚本自动修复） |
| **ELF LOAD 段对齐** | `check_elf_alignment.sh`（[AOSP 官方](https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh)） | 重新编译（NDK r28+ 或添加链接参数） |

> **关键区别**：zipalign 检查的是 .so 在 APK 内的 ZIP offset 对齐（打包问题，可自动修复）；ELF 段检查的是 .so 内部的 LOAD 段 alignment（编译问题，需重新编译）。

### 各输入类型的检查范围

| 输入类型 | zipalign 验证 | ELF 段检查 | 说明 |
|----------|:---:|:---:|------|
| APK | ✅ | ✅ | 完整检查 |
| AAB | ✅（需 bundletool 转 APK） | ✅（直接解压提取） | ELF 为核心检查项 |
| AAR | ❌（跳过） | ✅（直接解压提取） | 中间产物，zipalign 由宿主 APK 决定 |
| 工程目录 | ✅ | ✅ | 自动构建 APK 后完整检查 |

## 目录结构

```
scripts/
├── check_alignment.py        # 主入口：参数解析 + 路由分发
├── models.py                 # 数据模型（dataclass + 常量）
├── checker_common.py         # 通用工具（zipalign/ELF 检查/NDK 版本检测）
├── checker_apk.py            # APK 检查 + 自动修复
├── checker_aar.py            # AAR 直接解压检查
├── so_source_analyzer.py     # SO 来源分析（Gradle 依赖树 + 缓存匹配）
├── report_html.py            # HTML 报告生成
├── report_terminal.py        # 终端输出 + 批量检查
├── aar_builder.py            # AAR→APK 构建（保留备用）
└── check_elf_alignment.sh    # AOSP 官方 ELF 对齐检查脚本
```

## 使用方法

```bash
# APK（失败时自动修复）
python3 check_alignment.py <APK路径>

# AAR（直接解压检查 ELF 段，秒级完成）
python3 check_alignment.py <AAR路径...>

# 指定 HTML 输出路径
python3 check_alignment.py <文件路径> <HTML输出路径>

# 批量检查
python3 check_alignment.py --batch <目录路径>
```

**依赖**：Python 3.6+（标准库）、`zipalign`（Build-Tools 35+）、`objdump`

## 工作流程

```
用户请求检查 → 识别输入类型
    ↓
┌─ .apk → 直接进入检查
├─ .aab → 解压提取 .so 做 ELF 检查 + bundletool 转 APK 做 zipalign 检查
├─ .aar → 解压提取 .so 做 ELF 检查（跳过 zipalign）
└─ 工程目录 → 识别模块 → gradlew assemble → 定位 APK → 进入检查
    ↓
执行检查（zipalign + ELF 段）
    ↓
SO 来源分析（APK 为项目构建产物时自动触发）
    ↓
汇总结果 + 生成 HTML 报告
    ↓
zipalign 失败 → 自动修复（仅 APK 模式）
    ↓
给出修复建议 → 项目构建产物时可直接修改源码（阶段 6）
```

### AAB 处理（AI 在 Skill 层面执行）

```bash
# 1. 解压 AAB 提取 .so 做 ELF 段检查
unzip -o app.aab -d /tmp/aab_extract/
# .so 位于 base/lib/{abi}/ 下

# 2. 用 bundletool 转 universal APK 做 zipalign 检查
java -jar bundletool.jar build-apks --bundle=app.aab --output=app.apks --mode=universal
unzip app.apks -d /tmp/apks/
# 对 universal.apk 调用 check_alignment.py
```

### 工程目录处理（AI 在 Skill 层面执行）

1. 定位 `settings.gradle` 确定 project_root
2. 识别 application 模块（多个时询问用户选择）
3. 执行 `gradlew :{module}:assemble{Variant}`（默认 debug）
4. 定位构建产物 APK，调用 `check_alignment.py`
5. 发现问题时自动进入阶段 6 修复

## 修复方案

### 1. 压缩存储（优先级最高）

```groovy
android {
    packagingOptions {
        jniLibs { useLegacyPackaging = false }
    }
}
```

> AGP 8.5.1+ 已默认设置。

### 2. ELF 段对齐（需重新编译）

| 方案 | 操作 |
|------|------|
| **升级 NDK（推荐）** | `ndkVersion "28.0.12433566"` |
| **CMake 链接参数** | `target_link_options(lib PRIVATE -Wl,-z,max-page-size=16384)` |
| **Gradle cmake 参数** | `arguments "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"` |
| **第三方 SDK** | 升级 SDK 或联系供应商 |

### 3. zipalign 对齐

| 方案 | 操作 |
|------|------|
| **升级 AGP（推荐）** | AGP 8.5.1+ 自动支持 |
| **手动 zipalign** | `zipalign -P 16 -f 4 input.apk output.apk`（脚本自动执行） |

> ⚠️ 正式发布：zipalign 必须在签名之前执行。

## 阶段 6：构建目录自动修复

**触发条件**：APK 路径能反推到项目根目录 + 存在未通过项 + SO 来源分析已建立映射

**修复决策**：

| 问题类型 | SO 来源 | AI 操作 |
|----------|---------|---------|
| 压缩存储 | 任意 | 直接修改 `build.gradle` |
| ELF 未对齐 | 项目模块 | 修改 `CMakeLists.txt` / `build.gradle` |
| ELF 未对齐 | 外部依赖 | 仅建议（提示升级或联系供应商） |
| zipalign 未对齐 | 任意 | 修改 `build.gradle` 或升级 AGP |

**流程**：定位文件 → 生成修改方案（含 before/after + 原因 + 影响范围）→ 展示并等待用户确认 → 执行修改 → 提示重新构建验证

## 自检清单

| # | 检查项 |
|---|--------|
| 1 | 正确区分 APK/AAB/AAR/工程目录，走对应检查路径 |
| 2 | 压缩存储的 .so 已识别并标记 |
| 3 | zipalign 验证已完成（APK/AAB 模式） |
| 4 | ELF 段检查已完成 |
| 5 | HTML 报告已生成（含 zipalign + ELF 两个 Tab） |
| 6 | zipalign 失败时已自动尝试修复（仅 APK 模式） |
| 7 | 针对不同问题类型给出了具体修复方案 |
| 8 | APK 为项目构建产物时，已执行 SO 来源分析 |
| 9 | 项目构建产物且有未通过项时，已进入阶段 6 修复流程 |

## 参考文档

- [Google 官方：支持 16KB 页面大小](https://developer.android.com/guide/practices/page-sizes?hl=zh-cn)
- [AOSP check_elf_alignment.sh](https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh)
