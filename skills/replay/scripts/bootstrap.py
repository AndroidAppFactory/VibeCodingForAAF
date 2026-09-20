"""ZixieKit 脚本引导模块（零外部依赖）

为独立脚本提供：
  - find_repo_root(): 定位 ZixieKit 仓库根目录
  - load_env(): 加载 ~/.zixiekit/.env + secrets.env 环境变量
  - mask_secret(): 统一密钥脱敏（供展示）

~/.zixiekit/scripts/ 由 install/init 自动同步。

用法：
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path.home() / ".zixiekit" / "scripts"))
    from bootstrap import find_repo_root, load_env, mask_secret
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# find_repo_root
# ---------------------------------------------------------------------------

def find_repo_root() -> Path:
    """定位 ZixieKit 仓库根目录。

    查找策略：
    1. 先 load_env() 确保环境变量已加载
    2. 从 ZIXIEKIT_HOME 环境变量获取路径
    3. 报错退出

    返回：仓库根目录的绝对路径
    """
    # 确保 .env 已加载
    load_env()

    zk_home = os.environ.get("ZIXIEKIT_HOME", "")
    if zk_home:
        p = Path(os.path.expandvars(os.path.expanduser(zk_home))).resolve()
        if p.exists():
            return p

    # 报错
    print(
        "❌ 无法定位 ZixieKit 仓库。请在 ~/.zixiekit/.env 中配置：\n"
        "  ZIXIEKIT_HOME=<ZixieKit 仓库路径>",
        file=sys.stderr,
    )
    sys.exit(3)


# ---------------------------------------------------------------------------
# load_env
# ---------------------------------------------------------------------------

_GLOBAL_ENV_PATH = Path.home() / ".zixiekit" / ".env"


def mask_secret(value: str, keep: int = 4) -> str:
    """统一密钥脱敏：保留前 keep 字符 + ***；短值（<=keep）全 ***。

    零依赖公共 API，供 skill 脚本展示密钥时复用：
        from bootstrap import mask_secret
    """
    s = str(value)
    return f"{s[:keep]}***" if len(s) > keep else "***"


def _read_flat_env(path: Path) -> dict[str, str]:
    """读扁平 key=value 文件（.env / secrets.env），返回 dict（不展开引用）。

    ⚠️ 解析逻辑与 tools/zixiekit/core/global_env.py 的 read_global_env 保持一致，
    改此必须同步改那边（ADR-010 双入口，本模块零依赖无法复用对侧）。
    """
    result: dict[str, str] = {}
    if not path.is_file():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        result[key.strip()] = value.strip().strip("'\"")
    return result


def _read_instance_target(inst_yaml: Path) -> tuple[str, str]:
    """读 instance.yaml 的 install.target，按 type 映射到 (变量名, 值)。

    hermes → HERMES_HOME，openclaw → OPENCLAW_HOME。无映射返回 ("", "")。
    """
    if not inst_yaml.is_file():
        return "", ""
    try:
        import yaml  # 延迟 import，保持模块零外部依赖
    except ImportError:
        return "", ""
    try:
        data = yaml.safe_load(inst_yaml.read_text(encoding="utf-8")) or {}
    except Exception:
        return "", ""
    target = (data.get("install") or {}).get("target", "")
    if not target:
        return "", ""
    var_map = {"hermes": "HERMES_HOME", "openclaw": "OPENCLAW_HOME"}
    var = var_map.get(data.get("type", ""))
    if not var:
        return "", ""
    return var, target


def _secrets_env_path(zk_tmp: str = "") -> Path:
    """secrets.env 密钥文件路径（ZIXIEKIT_TMP 优先，默认 ~/.zixiekit）。

    与 zk secrets 的 _vault_path 一致。格式与 .env 相同（key=value），
    复用 _read_flat_env 解析。
    """
    base_raw = zk_tmp or os.environ.get("ZIXIEKIT_TMP", "")
    if base_raw:
        base = Path(os.path.expandvars(os.path.expanduser(base_raw)))
    else:
        base = Path.home() / ".zixiekit"
    return base / "secrets.env"


def load_env() -> None:
    """装配环境变量到 os.environ（不覆盖已存在的变量）。

    来源与优先级（低 → 高）：
      1. ~/.zixiekit/.env              —— 全局配置（路径等，非密钥）
      2. ~/.zixiekit/secrets.env       —— 集中式密钥（WECOM_KEY 等）
      3. instance.yaml 的 install.target —— HERMES_HOME / OPENCLAW_HOME
    os.environ 已存在的变量最高（容器注入不覆盖）。

    实例定位依赖 ZIXIEKIT_HOME（仓库）+ AI_NAME（实例名）；二者缺一（本地/非实例环境）
    则只读全局配置（.env + secrets.env），不读实例配置。
    """
    merged: dict[str, str] = {}

    # 1. 全局 ~/.zixiekit/.env
    merged.update(_read_flat_env(_GLOBAL_ENV_PATH))

    # 1b. secrets.env（集中式密钥，覆盖 .env 同名密钥）
    merged.update(_read_flat_env(_secrets_env_path(merged.get("ZIXIEKIT_TMP", ""))))

    # 2. 定位实例目录
    #    ZIXIEKIT_HOME：os.environ 优先，全局 .env 兜底（全局路径，可放 .env）
    #    AI_NAME：仅从 os.environ 读（运行时注入）；全局 .env 不配置 AI_NAME（实例级变量）
    zk_home = os.path.expandvars(os.path.expanduser(
        os.environ.get("ZIXIEKIT_HOME") or merged.get("ZIXIEKIT_HOME", "")
    ))
    ai_name = os.environ.get("AI_NAME", "")
    inst_dir = Path(zk_home) / "instances" / ai_name if zk_home and ai_name else None

    # 3. 实例配置（仅 install.target；instance.env 已废弃，不再读取）
    if inst_dir and inst_dir.is_dir():
        var, target = _read_instance_target(inst_dir / "instance.yaml")
        if var:
            merged[var] = target

    # 4. 展开引用 + 注入（setdefault：不覆盖已存在的环境变量）
    for key, value in merged.items():
        value = os.path.expanduser(os.path.expandvars(value))
        os.environ.setdefault(key, value)



