---
version: 5
category: android
name: xlog-decode
description: Mars xlog 解密工具 - 将腾讯 mars xlog 加密日志解密为明文文本，与具体产品无关，供各诊断/分析 skill 复用
---

# Mars xlog 解密工具

纯脚本驱动，通过 `scripts/decode_xlog.py` 执行。

## 用法

```bash
# 解密单个 xlog（输出到同目录 .log）
python3 scripts/decode_xlog.py /path/to/xxx.xlog

# 指定输出文件
python3 scripts/decode_xlog.py /path/to/xxx.xlog -o /path/to/out.log

# 批量解密目录下所有 .xlog
python3 scripts/decode_xlog.py /path/to/logdir/

# 覆盖默认私钥（适配其他使用 mars xlog 的项目）
python3 scripts/decode_xlog.py /path/to/xxx.xlog --priv-key <hex私钥>
```

## 依赖

- Python 3（纯标准库实现，零第三方依赖）

## 注意事项

- 私钥读取链路（ZixieKit 规范）：系统环境变量 `XLOG_PRIV_KEY` → `~/.zixiekit/.env`；其他项目可用 `--priv-key` 覆盖
- 非标准 xlog / 密钥不符时明确报错，不静默
