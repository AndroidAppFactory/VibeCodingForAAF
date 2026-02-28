# 代码规范检查

对指定文件或当前打开的文件执行代码规范检查（格式、命名、注释、import、代码结构），支持自动修复。

## 执行规则

**必须调用 `aaf-style-checker` Agent 执行**，按该 Agent 定义的完整流程运行。

补充要求：
1. 确定检查范围：优先使用用户指定的文件/目录，否则使用当前打开的文件
2. 读取忽略规则配置：`.codebuddy/config/quality-ignore-rules.json`
3. 对 `globalIgnores` 中的规则不报告，对 `manualReviewRequired` 中的规则标记为需人工确认
4. 输出结构化报告，按严重级别分组（Bug > 格式 > 代码质量 > 注释 > 优化建议）
5. 询问用户是否执行自动修复
