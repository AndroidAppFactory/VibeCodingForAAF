# CodeBuddyForAAF

一个在 CodeBuddy 中嵌入 AAF（AndroidAppFactory）的完整工作区，提供智能化的开发规则和命令支持。

## 项目结构

```
CodeBuddyForAAF/
├── .codebuddy/rules/                    # CodeBuddy 规则配置
│   ├── aaf_commands.mdc                 # 命令索引（统一入口）
│   ├── aaf_cmd_doc_inspection.mdc       # 命令：文档巡检
│   ├── aaf_cmd_doc_management.mdc       # 命令：文档管理
│   ├── aaf_cmd_release_check.mdc        # 命令：发布检查
│   ├── aaf_cmd_rules_optimization.mdc   # 命令：规则优化
│   ├── aaf_cmd_sample_upgrade.mdc       # 命令：示例项目升级
│   ├── aaf_cmd_version_upgrade.mdc      # 命令：AAF 版本升级
│   ├── aaf_common.mdc                   # 通用开发规范
│   ├── aaf_demo.mdc                     # Demo 开发规范
│   ├── aaf_dependency.mdc               # 依赖管理规范
│   ├── aaf_git.mdc                      # Git 提交规范
│   ├── aaf_note.mdc                     # 注释规范
│   └── aaf_version.mdc                  # 版本查找方法
├── init.sh                              # 项目初始化脚本
├── README.md                            # 项目说明文档
├── AAF-Temp/                            # Demo 开发目录（自动创建，从 Template-Empty clone）
├── AndroidAppFactory/                   # AAF 核心框架（自动克隆）
├── AndroidAppFactory-Doc/              # AAF 文档（自动克隆）
├── Template-Empty/                      # Sample 示例项目 - 最简示例（自动克隆）
├── Template_Android/                    # Sample 示例项目 - 基础示例（自动克隆）
└── Template-AAF/                        # Sample 示例项目 - 完整示例（自动克隆）
```

## 快速开始

### 1. 环境准备
- JDK 8+
- Android SDK（配置 ANDROID_HOME 环境变量）
- 网络连接（用于自动克隆项目）

### 2. 项目初始化
```bash
./init.sh
```

**init.sh 功能：**
- 自动克隆缺失的 AAF 项目
- 移除克隆项目的 git 支持（避免意外提交）
- 配置开发环境

### 3. 开始开发

在 CodeBuddy 中直接使用自然语言命令进行开发，或进入 `AAF-Temp` 手动开发。

**参考示例：**
- `./AndroidAppFactory/BaseDebug` - View 系统示例
- `./AndroidAppFactory/BaseDebugCompose` - Compose 示例

## 智能命令系统

### 📚 文档相关

| 命令 | 功能 |
|------|------|
| `更新文档` `同步文档` | 检测代码变更并同步更新文档 |
| `生成文档` `整理文档` | 为指定模块生成标准文档 |
| `文档巡检` | 检查框架模块与文档的对应关系 |

**示例：**
```
你: "更新文档"
   → 分析代码变更并更新相关文档

你: "帮我整理一下 LibDownload 的文档"
   → 为 LibDownload 生成标准文档

你: "文档巡检"
   → 检查所有模块的文档完整性
```

### 🚀 发布相关

| 命令 | 功能 |
|------|------|
| `发布检查` `准备发布` | 执行发布前完整检查流程 |
| `编译检查` | 仅执行编译检查 |
| `版本检查` | 检查版本号是否已更新 |

**示例：**
```
你: "发布检查"
   → 执行版本号检查、模块完整性检查、编译检查

你: "准备发布"
   → 同上，生成完整的发布检查报告
```

### 🔧 开发相关

| 命令 | 功能 |
|------|------|
| `升级 AAF 版本` | 自动升级项目的 AAF 依赖版本 |
| `添加依赖` | 查看依赖管理规范 |
| `添加注释` | 查看注释规范 |
| `Demo 开发` | 查看 Demo 开发规范 |
| `提交规范` | 自动生成符合规范的 Git 提交信息 |
| `查询版本` | 查看 AAF 模块版本查找方法 |
| `总结提交` | 分析待提交变更，生成提交信息 |
| `自动运行` | Demo 开发时自动编译安装启动 |

**示例：**
```
你: "升级 Template-AAF 的 AAF 版本"
   → 自动识别项目模块，查找实际版本并升级

你: "我要给 LibDownload 添加 LibOkhttpWrapper 依赖"
   → 指导正确添加依赖

你: "提交规范"
   → 自动分析变更，生成符合规范的 Commit Message

你: "帮我给这个类添加注释"
   → 生成标准格式的注释

你: "如何查找 common-debug 的版本"
   → 提供 AAF 模块版本查找方法和步骤

你: "总结一下当前项目的提交"
   → 分析待提交变更，生成提交信息建议

你: "后续都自动运行"
   → 每次修改代码后自动编译、安装、启动应用
```

### 🔍 检查相关

| 命令 | 功能 |
|------|------|
| `全面检查` | 文档巡检 + 发布检查 + 文档同步 |
| `快速检查` | 编译 + 版本号检查 |
| `优化规则` | 整体审查并优化所有规则文件 |

### 📋 规则文件说明

#### 主索引
| 规则文件 | 说明 |
|---------|------|
| `aaf_commands.mdc` | 命令索引，所有命令的统一入口 |

#### 命令规则（`aaf_cmd_*`）
| 规则文件 | 说明 |
|---------|------|
| `aaf_cmd_doc_inspection.mdc` | 文档巡检命令 - 检查框架模块与文档的对应关系 |
| `aaf_cmd_doc_management.mdc` | 文档管理命令 - 文档生成、同步和更新的统一管理 |
| `aaf_cmd_release_check.mdc` | 发布检查命令 - 发布前自动检查编译状态和版本号更新 |
| `aaf_cmd_rules_optimization.mdc` | 规则优化命令 - 规则文件的优化、重构和目录结构管理 |
| `aaf_cmd_sample_upgrade.mdc` | 示例项目升级命令 - 自动同步示例项目的 AAF 版本和编译配置 |
| `aaf_cmd_version_upgrade.mdc` | AAF 版本升级命令 - 自动升级项目的 AAF 依赖版本 |

#### 配置/规范（`aaf_*`）
| 规则文件 | 说明 |
|---------|------|
| `aaf_common.mdc` | AAF 框架通用开发规范和项目结构 |
| `aaf_demo.mdc` | Demo 开发规范（AAF-Temp 临时开发） |
| `aaf_dependency.mdc` | 集中式依赖管理规范 |
| `aaf_git.mdc` | Git Commit Message 规范 |
| `aaf_note.mdc` | 代码注释规范和文档编写标准 |
| `aaf_version.mdc` | AAF 模块版本查找方法 |

## 常见问题

**Q: 初始化脚本会做什么？**
- 检查并克隆缺失的 AAF 项目
- 移除 .git 目录（避免意外提交到原项目）
- 配置开发环境

**Q: 为什么要移除 git 支持？**
- 避免意外提交到原始 AAF 项目
- 可自由修改代码
- 可根据需要重新初始化自己的 git 仓库

**Q: 如果克隆失败怎么办？**
- 检查网络连接
- 手动克隆项目到当前目录
- 重新运行 `init.sh`

## 相关链接

- [AAF 框架文档](https://android.bihe0832.com/doc/)
- [技术方案介绍](https://blog.bihe0832.com/android-dev-summary.html)
- [框架代码统计](https://android.bihe0832.com/source/lib/index.html)
