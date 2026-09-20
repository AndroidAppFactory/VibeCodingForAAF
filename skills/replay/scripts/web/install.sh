#!/usr/bin/env bash
# web-replay 依赖安装脚本
# 自动检测 Python 环境并安装 playwright + Chromium 浏览器

set -euo pipefail

# 查找 zk/aaf 使用的 Python（pipx venv > 当前 Python > python3）
find_python() {
    # 方式 1：从 zk entry point 推断
    if command -v zk >/dev/null 2>&1; then
        local zk_shebang
        zk_shebang=$(head -1 "$(command -v zk)")
        if [[ "$zk_shebang" == '#!'* ]]; then
            echo "${zk_shebang:2}"
            return
        fi
    fi
    # 方式 2：当前环境
    if command -v python3 >/dev/null 2>&1; then
        echo "python3"
        return
    fi
    echo "python3"
}

PYTHON=$(find_python)
echo "🔍 检测到 Python: $PYTHON ($($PYTHON --version 2>&1))"

# 检测是否是 pipx 管理的 venv（pipx 剥离了 pip）
IS_PIPX=false
if [[ "$PYTHON" == *".local/pipx/venvs/"* ]]; then
    IS_PIPX=true
fi

# 检查 playwright 是否已可用
if $PYTHON -c "import playwright" 2>/dev/null; then
    echo "✅ playwright 已安装"
else
    echo "📦 安装 playwright ..."
    if $IS_PIPX; then
        VENV_NAME=$(echo "$PYTHON" | sed 's|.*/pipx/venvs/||' | cut -d/ -f1)
        echo "   检测到 pipx 环境: $VENV_NAME"
        pipx inject "$VENV_NAME" playwright
    elif $PYTHON -m pip --version >/dev/null 2>&1; then
        $PYTHON -m pip install playwright
    else
        echo "❌ 无法自动安装 playwright，请手动运行："
        if $IS_PIPX; then
            echo "   pipx inject zixiekit playwright"
        else
            echo "   $PYTHON -m pip install playwright"
        fi
        exit 1
    fi
    echo "✅ playwright 安装完成"
fi

# 检查 Chromium 浏览器
CHROMIUM_DIR="$($PYTHON -c "import playwright; from pathlib import Path; p=Path(playwright.__file__).parent; print(p)" 2>/dev/null)"
if [ -n "$CHROMIUM_DIR" ]; then
    echo "🔍 Chromium 路径: $CHROMIUM_DIR"
fi

echo "📦 安装 Chromium 浏览器 ..."
$PYTHON -m playwright install chromium 2>&1

echo ""
echo "✅ web-replay 依赖安装完成"
echo ""
echo "💡 测试命令:"
echo "   zk replay record web test --url https://example.com"
echo "   zk replay play test"
echo "   zk replay manage"
