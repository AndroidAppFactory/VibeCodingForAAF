---



version: 2
category: android
name: apk-size-analyzer
description: APK 体积分析与瘦身助手 - 分析 APK/AAB/AAR 的体积构成，按 DEX/Native/资源/Assets 等维度拆解，识别大文件、未压缩 SO、可转 WebP 图片等，并将 SO 归因到 Gradle 模块或 Maven 依赖，最终给出针对性的瘦身优化建议



---
# APK 体积分析与瘦身助手

> **背景**：Google Play 对应用大小有诸多建议（< 150MB、优先 App Bundle），APK 体积直接影响下载转化率、更新成本和用户留存。本 Skill 帮助快速定位"体积都去哪了"，并给出可执行的瘦身方案。
## 前置检查

1. 仅需 Python 3.6+（标准库即可，无外部依赖）
2. 支持文件格式：`.apk` / `.aab` / `.aar`
3. 若 APK 为项目构建产物（路径含 `build/{outputs,intermediates}/apk/` 或 `.../bundle/`），可额外启用 SO 模块归因
4. **源码关联（可选）**：用户给出 APK 时 Skill 自动检查是否为工程产物，若能自动向上找到含 `settings.gradle(.kts)` 的工程根，则自动追加 `--project <root>` 启用「图片使用位置反查」与「Lint 未使用资源扫描」；同时从 APK 路径推断出 Gradle module 名（如 `APPTest`）。**脚本只读取现有的 Lint XML 报告，绝不会自动执行任何 gradle 命令**。找不到 Lint 报告时会打印一条手动命令 `./gradlew lintReportRelease`（稳定产出 `*/build/reports/lint-results-*.xml`，包含 Analyze 阶段）+ 本分析的重放命令，用户跑完 lint 再直接重放即可拿到结果

## 检查内容

| 检查维度 | 说明 | 依赖 |
|----------|------|------|
| **构成分类** | 按 DEX/Native/资源/Assets/签名/Kotlin 元数据/Manifest/其他拆分 | zipfile 遍历 |
| **DEX 分析** | 方法数、类数、字符串数；检测 MultiDex 与 R8 启用状态 | DEX 头解析（前 112 字节） |
| **Native 分析** | 按 ABI 分布；检测未压缩存储（STORED）的 .so | ZIP 条目 compress_type |
| **资源分析** | 大图识别（>100KB）、密度变体统计、可转 WebP 候选 | 文件后缀 + 路径 |
| **批量压缩清单** | 为 ≥100KB 的 PNG/JPG 反查工程源路径并生成 TinyPNG 压缩清单；通用 shell 本体常驻 skill 目录，报告端与 HTML 都会给出一键调用命令 | `compress_script_generator.py`，需 `--project` |
| **SO 模块归因** | 通过 Gradle transforms 缓存反查 SO 的来源模块 / Maven 坐标 | 复用 `apk-16kb-check/so_source_analyzer` |
| **图片使用位置** | 按 APK 路径对图片分 4 类分别反查（assets / res/raw / res/drawable+mipmap / 其他 res/*），各用专用正则：静态引用（`@drawable/`、`R.xxx`、`android_asset/...`、完整 url 路径等）、动态引用（字符串字面量，含带扩展名写法），三档可信度；扫描 Kotlin/Java/XML 以及 html/js/json/css/md 等文本文件，覆盖 WebView 加载 / AssetManager / Glide 等场景 | `resource_usage_finder.py`，需 `--project` |
| **Lint 未用资源** | 解析 `*/build/reports/lint-results-*.xml`（**多 module 聚合**），抽取 `UnusedResources` issue，结合 APK 条目倒推体积；找不到报告时打印「手动 `./gradlew lintReportRelease` + 重放命令」两行引导，**脚本绝不会自动执行 gradle 命令**，由用户手动跑 lint | `unused_resource_scanner.py`，需 `--project` |
| **优化建议** | 基于规则匹配生成：多 ABI、SO 存储、PNG 转 WebP、R8、App Bundle、未引用大图、未用资源汇总等 | 内置规则库 |

## 目录结构

```
scripts/
├── analyze_apk.py              # 主入口：参数解析 + 流程编排（含 --project 与自动推断）
├── models.py                   # 数据模型（dataclass + 常量 + FileCategory）
├── apk_parser.py               # APK 解析器：ZIP 遍历 + 按类型分类
├── dex_analyzer.py             # DEX 分析：方法数 / 类数 / 字符串数
├── so_analyzer.py              # SO 分析：ABI 分布 + 压缩状态
├── resource_analyzer.py        # 资源分析：子类型分组、大图检测
├── module_attributor.py        # SO 模块归因（复用 apk-16kb-check）
├── compress_script_generator.py # 批量压缩清单生成器（--project 启用）
├── templates/
│   └── compress_images.sh      # 批量压缩 shell（TinyPNG通用本体，常驻 skill 目录）
├── resource_usage_finder.py    # 图片源码反查（--project 启用）
├── unused_resource_scanner.py  # Lint 未用资源扫描（--project 启用）
├── optimization_advisor.py     # 优化建议引擎（规则匹配）
├── report_terminal.py          # 终端彩色输出
└── report_html.py              # HTML 可视化报告（CSS 饼图 + Tab）
```

## 使用方法

```bash
# 分析单个 APK（自动生成并打开 HTML 报告）
python3 analyze_apk.py <APK路径>

# 指定 HTML 输出路径
python3 analyze_apk.py <APK路径> <HTML输出路径>

# 显式关联 Android 工程（启用图片使用位置反查 + 未用资源扫描）
python3 analyze_apk.py <APK路径> --project <工程根路径>

# 分析 AAB / AAR
python3 analyze_apk.py <AAB/AAR路径>

# 批量分析目录
python3 analyze_apk.py --batch <目录路径>
python3 analyze_apk.py --batch <目录路径> --project <工程根路径>
```

**依赖**：Python 3.6+（标准库）

## 输出约定

### 终端输出（极简模式，对齐 apk-16kb-check）

终端只输出**结论摘要**，所有详情由 HTML 承载：

```
═══════ 📦 APK 体积分析 ═══════
  文件: /abs/path/app.apk
  大小: 41.47 MB（原始 117.83 MB，1981 条目）
  ⚠️  2 条高优先级建议（详情见 HTML）
  📄 HTML 报告: /abs/path/app_size_report.html

🔄 重放命令（可复制）
  python3 "/abs/path/analyze_apk.py" "/abs/path/app.apk"
```

### HTML 报告（完整模式）

所有详情都在 HTML 中：最多 7 个 Tab（总览 / DEX / Native / 大文件 / 可优化图片 / **未用资源**（启用源码关联时） / 优化建议）、每个 Tab 标题带「大小·占比」徽章、交互排序表头、深色重放命令面板（对齐 apk-16kb-check 风格）、**可优化图片 Tab 支持缩略图预览 + 一键批量压缩命令面板**（把所有 ≥100KB 的图片解压到 `{report}_assets/images/`，点击放大；下方展示 dry-run/apply/restore 三条可复制命令）、**自动打包分享 zip**（含 HTML + 资源目录 + `compress_images.list`，解压即用）。

### 批量压缩清单（启用 `--project` 时自动生成）

当同时满足以下条件时，Skill 会在 `{report}_assets/` 下额外生成清单，并在 HTML「可优化图片」Tab / 终端提示中展示一键命令：

- 有效的 `--project <工程根>`（显式传入或自动推断）
- 存在 ≥100KB 的 PNG/JPG
- 工程内能定位到至少 1 张图的真实源路径

产物：

| 位置 | 文件 | 说明 |
|------|------|------|
| skill 目录（常驻） | `scripts/templates/compress_images.sh` | 通用压缩脚本，不复制到报告产物中 |
| `{report}_assets/` | `compress_images.list` | 本次压缩清单，每行「工程源文件真实路径 \| APK 内路径 \| 原大小」|

使用流程（HTML 面板和终端提示都会给出正确的绝对路径）：

```bash
export tinypng_api_key=your_key_here       # https://tinypng.com/developers 申请

# 1. dry-run 预览（默认）—— 打印将要压缩的文件，不动任何文件
bash <skill>/scripts/templates/compress_images.sh --list {report}_assets/compress_images.list

# 2. 真执行 —— 自动备份到 {report}_assets/.backup/，再调 TinyPNG 原地覆盖源文件
bash <skill>/scripts/templates/compress_images.sh --list {report}_assets/compress_images.list --apply

# 3. 一键回滚 —— 从 {report}_assets/.backup/ 恢复所有原文件
bash <skill>/scripts/templates/compress_images.sh --list {report}_assets/compress_images.list --restore
```

安全机制：

- **默认 dry-run**：必须加 `--apply` 才会真压缩
- **API Key 预校验**：启动先调 `/shrink` 验证 `$tinypng_api_key`，无效立即退出
- **自动备份**：每张图压缩前先镜像到清单同级 `.backup/{相对路径}/`
- **9-patch 强制跳过**：遇到 `*.9.png` 自动 skip（生成器和 shell 双重保护）
- **同格式压缩**：PNG→PNG、JPG→JPG，不做 WebP 转换
- **无收益不覆盖**：新文件 ≥ 原文件时保留原件
- **执行日志**：`{report}_assets/compress_images.log` 记录每张图 before/after/saved

## 工作流程

```
用户请求分析 → 识别输入类型 → 反查工程根（自动/显式）
    ↓
┌─ .apk → 完整分析（含 SO 模块归因；有工程根时叠加源码关联）
├─ .aab → 构成分析 + DEX + SO（跳过模块归因与源码关联）
└─ .aar → 构成分析 + SO（跳过 DEX / 模块归因 / 源码关联）
    ↓
apk_parser：遍历 ZIP 条目 → 按类别分类统计
    ↓
dex_analyzer：解析各 DEX 头（method_ids_size/class_defs_size）
    ↓
so_analyzer：按 ABI 分组 + 检测 STORED 存储
    ↓
module_attributor：APK 是项目构建产物时，反查 Gradle 缓存
    ↓
（可选）resource_usage_finder：扫描工程源码反查可优化图片的引用位置
    ↓
（可选）unused_resource_scanner：解析 Lint 报告聚合未使用资源
    ↓
optimization_advisor：按规则生成优化建议列表
    ↓
report_terminal：终端彩色输出摘要
    ↓
report_html：生成 HTML 报告（饼图 + 最多 7 Tab）并自动打开
```

## 优化建议分类

建议按严重程度分为 `high` / `medium` / `low` / `info` 四档：

### Native SO 相关
- `multi_abi`：APK 包含多个 ABI → 高收益
- `so_stored`：存在 STORED 存储的 .so → 中收益
- `large_so`：存在 >1MB 的 .so → 低收益

### 资源相关
- `png_to_webp`：存在 >100KB 的 PNG/JPG → 高收益
- `drawable_densities`：存在 ≥4 个密度变体 → 中收益
- `large_assets`：assets/ 下有 >100KB 文件 → 中收益

### DEX / 代码相关
- `r8_not_enabled`：多 DEX 但方法数利用率 <50% → 高收益
- `dex_method_near_limit`：方法数 ≥ 上限 90% → 中收益

### 整体策略
- `shrink_resources`：res/ 目录 >2MB → 中收益
- `use_app_bundle`：APK >50MB → 高收益

## 常见优化方案速查

### 1. 切换到 App Bundle（优先级最高）
```bash
./gradlew bundleRelease
```

### 2. 限定 ABI
```groovy
android {
    defaultConfig {
        ndk { abiFilters 'arm64-v8a' }
    }
}
```

### 3. 启用 R8 + shrinkResources
```groovy
android {
    buildTypes {
        release {
            minifyEnabled true
            shrinkResources true
        }
    }
}
```

### 4. PNG/JPG 转 WebP
- Android Studio：右键 drawable 目录 → Convert to WebP
- 命令行：`cwebp -q 75 input.png -o output.webp`

### 5. 限定资源密度
```groovy
android {
    defaultConfig {
        resConfigs 'zh', 'en', 'xxhdpi', 'xxxhdpi'
    }
}
```

## 自检清单

| # | 检查项 |
|---|--------|
| 1 | 正确识别 APK/AAB/AAR 三种输入格式 |
| 2 | 分类统计覆盖所有条目（DEX/Native/资源/Assets/签名/其他） |
| 3 | DEX 头解析正确（method/class 数与 AS Build Analyzer 一致） |
| 4 | Native SO 按 ABI 正确分组，STORED 存储已标记 |
| 5 | 大文件（>1MB）和可优化图片（>100KB 非 WebP）已列出 |
| 6 | APK 为项目构建产物时，SO 模块归因已执行 |
| 7 | 优化建议按严重程度排序，high 建议提前展示 |
| 8 | HTML 报告含 6~7 个 Tab，支持交互排序 |
| 9 | 终端输出极简，重放命令格式正确 |

## 参考文档

- [Android 官方：减小 APK 大小](https://developer.android.com/topic/performance/reduce-apk-size?hl=zh-cn)
- [Android App Bundle 指南](https://developer.android.com/guide/app-bundle?hl=zh-cn)
- [姊妹 Skill：apk-16kb-check](../apk-16kb-check/SKILL.md)

## 开发经验

> 详细开发经验和踩坑记录见 [LESSONS.md](./LESSONS.md)，包含 37 条技术要点和优化经验。
