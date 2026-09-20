---


version: 4
category: android
name: apk-16kb-check
description: APK/AAB/AAR/工程目录 16KB 页面对齐检查助手 - 使用官方工具检查是否符合 Google Play 16KB 页面大小要求。支持 APK 直接检查、AAB 转 APK 后检查、AAR 直接解压检查 ELF 段、Android 工程目录自动构建后检查，失败时自动尝试修复
disable-model-invocation: true


---
# APK/AAB/AAR/工程目录 16KB 页面对齐检查助手

> **背景**：自 2025 年 11 月 1 日起，Google Play 要求所有以 Android 15 (API 35) 及以上为目标的应用必须支持 16KB 页面大小。

## 触发方式

`/apk.16kb`（仅 slash 命令触发，不响应自然语言）

## 前置检查

1. 从系统环境变量或 `~/.zixiekit/.env` 获取 `WORK_ROOT`（缺失则 fallback 到 `$HOME`） <!-- zk-lint: ignore hardcoded.zixiekit-path -->
2. AAB 模式需要 `bundletool`（脚本自动查找：`BUNDLETOOL`/`BUNDLETOOL_JAR` 环境变量 → PATH `bundletool` → 脚本同目录 `bundletool.jar` → `${ZIXIEKIT_TMP}/skill/apk-16kb-check/bundletool.jar`）。下载方式：
   - Google Maven 直链（jar 名**无 `-all` 后缀**）：`https://dl.google.com/dl/android/maven2/com/android/tools/build/bundletool/<ver>/bundletool-<ver>.jar`
   - GitHub Releases 直链（带版本号，**有 `-all` 后缀**）：`https://github.com/google/bundletool/releases/download/<ver>/bundletool-all-<ver>.jar`
   - ⚠️ GitHub API（`/releases/latest`）易触发限流，优先用上面两条直链；Maven Central 无 bundletool 产物
3. 工程目录模式需要 Java/Gradle/SDK 环境就绪
4. **zipalign 版本要求（Build-Tools ≥ 35.0.0-rc3，仅「检查端」）**：
   - 脚本会自动从 `ANDROID_HOME/build-tools/` 中优先挑选满足要求的最高版本；本机 zipalign 低于 35.0.0-rc3 时告警（旧版没有 `-P 16` 参数，无法正确验证 16KB 对齐）。
   - 安装：`sdkmanager "build-tools;35.0.0"`
   - ⚠️ **注意**：zipalign 只用于「检查/验证 APK」和「手动对齐 APK」，**不参与 AAB 打包**。AAB 打包（`bundleRelease`）不经过 zipalign，16KB 对齐由 **AGP 版本**决定（见下方「根因」）。

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
| AAB | ✅（脚本自动 dump config + bundletool 转 APK） | ✅ | 脚本自动完成：dump config 判读 → build-apks 转 universal → zipalign/ELF 检查 |
| AAR | ❌（跳过） | ✅（直接解压提取） | 中间产物，zipalign 由宿主 APK 决定 |
| 工程目录 | ✅ | ✅ | 自动构建 APK 后完整检查 |

> ⚠️ **实测坑 1（本地 APK ≠ AAB）**：本地独立构建/导出的 release APK 显示 zipalign "完全对齐"，**不代表**该项目上传 Google Play 的 `.aab` 就对齐——二者打包路径不同，结果可能相反（曾出现本地 APK 全部 OK，但用 bundletool 从同一次构建的 `.aab` 转出的 universal/split APK 全部 `Verification FAILED`，与 Play Console "未压缩原生库未按 16KB zip 对齐" 报错一致，ELF LOAD 段本身仍是对齐的，问题纯粹在 ZIP 层 offset）。**只要项目产出 AAB 用于发布，就必须用 bundletool 从实际 `.aab` 构建产物验证，不能用本地 APK 测试结果代替结论。**
>
> **根因（AGP 版本，已验证）**：AAB 的 16KB ZIP 对齐由 **AGP 版本**决定，**与 zipalign / build-tools 版本无关**。AGP ≥ 8.5.1 打包 AAB 时会在 config 里写入 `PAGE_ALIGNMENT_16K` 标记，bundletool 据此生成 16K 对齐的分发 APK；AGP < 8.5.1 则写入 `PAGE_ALIGNMENT_4K`（或缺失），bundletool 只做 4K 对齐 → 分发 APK 未按 16KB 对齐。验证：`bundletool dump config --bundle=xxx.aab | grep alignment`，出现 `PAGE_ALIGNMENT_4K` 即踩坑。修复：升级 AGP ≥ 8.5.1 重新 `bundleRelease`（或设 `useLegacyPackaging = true` 压缩存储规避）。

## 目录结构

```
scripts/
├── check_alignment.py        # 主入口：参数解析 + 路由分发
├── models.py                 # 数据模型（dataclass + 常量）
├── checker_common.py         # 通用工具（zipalign/ELF 检查/NDK 版本检测）
├── checker_apk.py            # APK 检查 + 自动修复
├── checker_aar.py            # AAR 直接解压检查
├── checker_aab.py            # AAB 检查（dump config 判读 + bundletool 转 APK 验证）
├── so_source_analyzer.py     # SO 来源分析（Gradle 依赖树 + 缓存匹配）
├── report_html.py            # HTML 报告生成
├── report_terminal.py        # 终端输出 + 批量检查
├── aar_builder.py            # AAR→APK 构建（保留备用）
└── check_elf_alignment.sh    # AOSP 官方 ELF 对齐检查脚本
```

## 报告输出规范

> ⚠️ **两端同步（强制）**：`report_terminal.py`（终端）与 `report_html.py`（HTML 报告）是同一检查结果的两个呈现端，**改任一端必须同步另一端**，否则会出现「终端有、HTML 漏」或两端修复建议不一致（历史：AAB 判读只加了终端、漏了 HTML）。

> ⚠️ **替换而非删空**：某模式（APK/AAB/AAR/SO）下内容不适用或误导时，**替换为该模式对应的正确内容**，不直接删空/跳过（历史：为消除 AAB 下「手动 zipalign」误导，把 tab-zipalign 下方整个跳过导致空白）。

> 📌 **区块归类**：检查结果（zipalign/ELF）进 `tab-zipalign` / `tab-elf`；根因分析 + 修复建议进 `tab-tips`（「💡 修复方案&参考资料」）。

## 使用方法

```bash
# APK（失败时自动修复）
python3 check_alignment.py <APK路径>

# APK + 手动指定项目源码目录（获取 AGP 版本告警和 SO 来源分析）
python3 check_alignment.py <APK路径> --project <项目源码目录>

# AAB（脚本自动 dump config 判读 + bundletool 转 universal APK 验证）
python3 check_alignment.py <AAB路径>

# AAR（直接解压检查 ELF 段，秒级完成）
python3 check_alignment.py <AAR路径...>

# 指定 HTML 输出路径
python3 check_alignment.py <文件路径> <HTML输出路径>

# 批量检查
python3 check_alignment.py --batch <目录路径>
```

**依赖**：Python 3.6+（标准库）、`zipalign`（Build-Tools **35.0.0-rc3+**）、`objdump`

> ⚠️ **zipalign 版本要求（仅检查端）**：验证 APK 是否 16KB 对齐需用 Build-Tools ≥ 35.0.0-rc3 的 zipalign（旧版没有 `-P 16` 参数，无法正确验证）。zipalign 只做「检查验证」和「手动对齐本地 APK」，**不参与 AAB 打包**——AAB 的 16KB 对齐由 AGP 版本决定（见上方「根因」）。

## 工作流程

```
用户请求检查 → 识别输入类型
    ↓
┌─ .apk → 直接进入检查
├─ .aab → 自动 dump config 判读 + bundletool 转 universal APK 做 zipalign/ELF 检查
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

### AAB 处理（脚本自动执行，无需 AI 手动）

`check_alignment.py <xxx.aab>` 会自动完成以下完整检测（以前是 AI 手动 unzip + bundletool，现在脚本内置）：

1. **dump config 前置判断**：解析 `uncompressNativeLibraries.enabled` + ZIP 对齐标记（`PAGE_ALIGNMENT_16K/4K`），命中「未压缩 + 无 `PAGE_ALIGNMENT_16K`」时直接判读根因（对应 AGP < 8.5.1）
2. **bundletool build-apks --mode=universal**：转出 universal APK
3. **复用 APK 检查**：对 universal APK 做 zipalign + ELF 检查
4. **汇总根因**：zipalign 失败时明确提示「AAB 无法用 zipalign 修复，需重新 bundleRelease」

> ⚠️ **dump config 判读要点（实测）**：官方文档让 `grep alignment` 看 `PAGE_ALIGNMENT_16K` vs `PAGE_ALIGNMENT_4K`，但 AGP < 8.5.1 打包的 AAB 输出里**两个字段都没有**（bundletool 默认按 4K 对齐）。真正的判读点：
> - `optimizations.uncompressNativeLibraries.enabled`（true = 未压缩存储，需 16K ZIP 对齐）
> - 是否有 `PAGE_ALIGNMENT_16K` 标记（有 = 16K 对齐；无/`PAGE_ALIGNMENT_4K` = 4K 对齐）
> 二者结合：未压缩（enabled=true）且无 `PAGE_ALIGNMENT_16K` → 根因是「AGP < 8.5.1」，无需依赖源码里的 AGP 版本。

若 bundletool 不可用，脚本降级为「解压 AAB 仅做 ELF 检查」并提示需要 bundletool。

### 工程目录处理（AI 在 Skill 层面执行）

1. 定位 `settings.gradle` 确定 project_root
2. 识别 application 模块（多个时询问用户选择）
3. 执行 `gradlew :{module}:assemble{Variant}`（默认 debug）
4. 定位构建产物 APK，调用 `check_alignment.py`
5. 发现问题时自动进入阶段 6 修复
6. **发布场景**（用户提及 Google Play / 已存在 `bundleRelease` 产物 `.aab`）：额外执行 `gradlew :{module}:bundle{Variant}`，用 bundletool 转出 universal/split APK 重新验证 zipalign（见上方"实测坑"），不能仅凭本地 assemble APK 的结果下结论

## 修复方案

### 1. 压缩存储（优先级最高）

```groovy
android {
    packagingOptions {
        jniLibs { useLegacyPackaging = false }  // AGP 8.5.1+ 用 false，AGP < 8.5.1 必须用 true
    }
}
```

> **官方规则**（[支持 16KB 页面大小](https://developer.android.com/guide/practices/page-sizes?hl=zh-cn)）：
> - **AGP ≥ 8.5.1**：`useLegacyPackaging = false`（默认即可，无需手动设置），AAB config 写入 `PAGE_ALIGNMENT_16K`，bundletool 生成的分发 APK 自动按 16K 对齐
> - **AGP < 8.5.1**：AAB config 只有 `PAGE_ALIGNMENT_4K`，bundletool 生成的分发 APK 只按 4K 对齐（**已实测命中**），官方规避方案是**必须显式设 `useLegacyPackaging = true`**（改回压缩存储，压缩的 .so 不涉及 ZIP 对齐）
> - **AGP ≤ 8.0**：同上问题，且需额外在 `gradle.properties` 加 `android.bundle.enableUncompressedNativeLibs=false`
> - 能升级到 8.5.1+ 才是根治方案；无法升级时 `useLegacyPackaging = true` 是必须项，不是可选项

### 2. ELF 段对齐（需重新编译）

| 方案 | 操作 |
|------|------|
| **升级 NDK（推荐）** | `ndkVersion "28.0.12433566"` |
| **CMake 链接参数** | `target_link_options(lib PRIVATE -Wl,-z,max-page-size=16384)` |
| **Gradle cmake 参数** | `arguments "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"` |
| **第三方 SDK** | 升级 SDK 或联系供应商 |

### 3. zipalign 对齐（仅本地 APK）

| 方案 | 操作 |
|------|------|
| **升级 AGP（AAB 场景，根治，已验证）** | AGP 8.5.1+，重新 `bundleRelease` 后 AAB config 写入 `PAGE_ALIGNMENT_16K`，bundletool 转出的分发 APK 转为 16K 对齐 |
| **手动 zipalign（仅本地 APK）** | `zipalign -P 16 -f 4 input.apk output.apk`（脚本自动执行，仅对 APK 有效） |

> ⚠️ 正式发布：zipalign 必须在签名之前执行。AAB 场景**无法用「手动 zipalign」绕过**——AAB 里的 native lib 对齐由 bundletool 生成分发 APK 时根据 AAB config 的对齐标记（`PAGE_ALIGNMENT_16K/4K`）完成，只能靠升级 AGP ≥ 8.5.1 或设 `useLegacyPackaging = true` 解决。

## 阶段 6：构建目录自动修复

**触发条件**：APK 路径能反推到项目根目录 + 存在未通过项 + SO 来源分析已建立映射

**修复决策**：

| 问题类型 | SO 来源 | AI 操作 |
|----------|---------|---------|
| 压缩存储 | 任意 | 直接修改 `build.gradle`（AGP 版本决定 true/false） |
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
