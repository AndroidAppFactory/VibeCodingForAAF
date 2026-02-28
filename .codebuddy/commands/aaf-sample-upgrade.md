# 升级 Sample 项目

升级 AAF 示例项目（Template-AAF、Template_Android、Template-Empty）到最新 AAF 框架版本。

## 执行规则

**必须加载 `aaf-sample-upgrade` Skill 执行**，按该 Skill 定义的完整流程运行（项目定位 → 配置读取 → 按顺序升级 → 编译验证）。

升级顺序：Template-AAF → Template_Android → Template-Empty（Template-AAF 编译成功后可并发升级其他两个）。
