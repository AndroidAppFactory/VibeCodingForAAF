---


version: 2
category: aaf
name: aaf-version-upgrade
description: AAF 依赖版本升级。通过 aaf CLI 工具识别项目中所有 AAF 模块，查找最新版本，展示升级报告，用户确认后执行更新。当用户说"升级AAF版本"时使用此 skill


---

# AAF Version Upgrade

## 前置条件

- 项目定位：通过 `aaf-project-finder` Skill 定位（`$AAF_HOME/AndroidAppFactory`）
- `aaf` CLI 可用（`python3 -m aafkit` 或 pip install 后直接 `aaf`）

## 工作流程

```
aaf version-check <项目>   → 输出升级报告
       ↓ 展示给用户
用户确认（回复"执行"或"取消"）
       ↓
aaf version-apply <项目>   → 执行版本号替换
       ↓
展示变更结果 + 建议提交信息
```

## 执行步骤

### Step 1 — 检查版本

```bash
aaf version-check <项目路径>
# 或 JSON 格式（供脚本消费）
aaf version-check <项目路径> --json
```

输出升级报告表格，展示给用户。

### Step 2 — 用户确认

**必须等待用户明确授权后才执行更新。**

展示报告后询问用户：
- "执行升级" → 进入 Step 3
- "取消" → 结束

### Step 3 — 执行升级

```bash
aaf version-apply <项目路径>
```

自动替换配置文件中的版本号，输出变更列表和建议提交信息。

## 核心原则

- **支持任意项目路径**，不限于 AAF_HOME 下的项目
- **不同模块可能有不同版本号**，逐个查找真实版本，不强行统一
- **禁止用 git tag 推断版本**，必须查 `dependencies_*.gradle`
- LLM 不直接操作文件，所有确定性逻辑由 `aaf` CLI 承载

## 退出码

| 退出码 | 含义 |
|--------|------|
| 0 | 无需升级 / 升级成功 |
| 1 | 错误（AAF_HOME 未配置、项目不存在等） |
| 2 | 有可用升级（version-check 专用） |
