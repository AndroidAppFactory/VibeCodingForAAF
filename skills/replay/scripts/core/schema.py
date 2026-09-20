"""replay-core 事件与 Flow 数据结构 Schema（唯一权威契约）

四端（web/win/mac/adb）统一契约：录制模块产出、回放模块消费、报告与前端展示均依据本模块。

契约要点（BREAKING，无历史兼容）：
- 动作步骤统一双层：{"type": "event", "action": <动作>, ...}，type 恒为 "event"。
- 结构步骤：flow / recording / pause / shell_cmd（保持自身 type，无 action）。
  * shell_cmd 为通用系统命令步骤（原 adb 特有的 adb_cmd 已泛化），各端注入执行器。
- delay 单位统一毫秒：delay_before_ms / delay_after_ms。
- 截图统一字段 screenshots:{before, after}，最终产物 JPG，命名 event_{index:03d}_{0_before|1_after}.jpg。
- 事件定位模型按平台并存：web 用 selectors 链、adb/win/mac 用 x/y 坐标。
- Flow 顶层含 platform 字段（web|win|mac|adb|mixed），平台专属元数据下沉 meta。

不做历史格式的向后兼容/自动升级；旧 examples 一次性改写为新结构。
"""

from __future__ import annotations

from enum import Enum


class EventType(str, Enum):
    """录制事件的动作枚举（action 字段取值，跨平台并集）"""
    # 通用
    CLICK = "click"
    INPUT = "input"
    SCROLL = "scroll"
    HOVER = "hover"
    KEYBOARD = "keyboard"
    WAIT = "wait"
    TIPS = "tips"
    # web 特有
    NAVIGATE = "navigate"
    SELECT = "select"
    CHECK = "check"
    SWITCH_TAB = "switch_tab"
    ALERT = "alert"
    # 桌面（win/mac）特有
    DBLCLICK = "dblclick"
    RIGHTCLICK = "rightclick"
    DRAG = "drag"
    TYPE = "type"
    # adb 特有
    TAP = "tap"
    MULTITAP = "multitap"
    SWIPE = "swipe"
    TEXT = "text"
    KEYEVENT = "keyevent"
    ADB = "adb"


# 结构步骤：保持 type 语义，不套 event 层
CONTROL_STEP_TYPES = frozenset({"flow", "recording", "pause", "shell_cmd"})


# ─── 平台枚举与校验 ─────────────────────────────────

class Platform(str, Enum):
    """Flow 归属平台"""
    WEB = "web"
    WIN = "win"
    MAC = "mac"
    ADB = "adb"
    MIXED = "mixed"


PLATFORMS = frozenset(p.value for p in Platform)


def validate_platform(platform: object) -> str:
    """校验 flow 顶层 platform 字段。

    缺失或非法一律报错，不做隐式推断（无历史兼容）。
    """
    if not isinstance(platform, str) or platform not in PLATFORMS:
        raise ValueError(
            f"flow 缺少合法的 platform 字段（应为 {sorted(PLATFORMS)} 之一），实际: {platform!r}"
        )
    return platform


# ─── 步骤归一化（仅结构校验 + 默认值，幂等） ───────────

def normalize_step(step: dict) -> dict:
    """校验并补全单个步骤的默认值（幂等）。

    不做历史升级：输入必须已是新契约。
    - 动作步骤：type == "event"，补 action 默认值、delay/is_critical 默认值。
    - 结构步骤（flow/pause/shell_cmd）：type 不变，无 action。
    - 遇到旧单层格式（type 直接是动作名）或秒单位 delay 字段：视为非法，报错。
    """
    s = dict(step)
    t = s.get("type", "")

    # 拒绝历史格式：秒单位 delay 字段
    if "delay_before" in s or "delay_after" in s:
        raise ValueError(
            f"检测到历史 delay 字段（秒单位），契约要求毫秒 delay_before_ms/delay_after_ms: {step!r}"
        )

    if t in CONTROL_STEP_TYPES:
        return s

    if t == "event":
        s.setdefault("action", "")
        s.setdefault("delay_before_ms", 0)
        s.setdefault("delay_after_ms", 0)
        s.setdefault("is_critical", False)
        return s

    # 其余一律非法（含旧单层 {type:<动作>}、空 type 等）
    raise ValueError(
        f"非法步骤 type={t!r}：动作步骤须为 {{'type':'event','action':...}}，"
        f"结构步骤须为 {sorted(CONTROL_STEP_TYPES)} 之一（无历史兼容）: {step!r}"
    )


def normalize_flow(flow: dict) -> dict:
    """校验并补全 flow 顶层结构（幂等）。

    - 校验 platform 合法（缺失/非法报错）。
    - 补全 name/description/steps/meta 默认值。
    - 逐个 normalize_step 校验步骤。
    - 平台专属元数据（device/resolution/profiles/default_profile）若残留顶层，收纳进 meta。
    """
    f = dict(flow)
    validate_platform(f.get("platform"))
    f.setdefault("name", "未命名")
    f.setdefault("description", "")
    f.setdefault("meta", {})

    # 平台专属元数据下沉 meta（若历史数据残留顶层）
    meta = dict(f.get("meta", {}))
    for k in ("device", "resolution", "profiles", "default_profile"):
        if k in f:
            meta.setdefault(k, f.pop(k))
    f["meta"] = meta

    f["steps"] = [normalize_step(s) for s in f.get("steps", [])]
    return f


# ─── 选择器（web 平台事件定位模型） ─────────────────

class SelectorType(str, Enum):
    """选择器类型，按优先级从高到低排列"""
    DATA_TESTID = "data-testid"   # 最佳，语义属性
    ID = "id"                     # 次优
    ARIA_LABEL = "aria-label"     # 良好
    TEXT = "text"                 # 元素文本内容
    CLASS = "class"               # CSS class 组合，不稳定
    XPATH = "xpath"               # 最后兜底，最不稳定
    NTH_CHILD = "nth-child"       # 动态列表项兜底


# 选择器优先级：值越小越优先
SELECTOR_PRIORITY: dict[SelectorType, int] = {
    SelectorType.DATA_TESTID: 0,
    SelectorType.ID: 1,
    SelectorType.ARIA_LABEL: 2,
    SelectorType.TEXT: 3,
    SelectorType.CLASS: 4,
    SelectorType.NTH_CHILD: 5,
    SelectorType.XPATH: 6,
}


# ─── 数据结构约定（文档） ─────────────────────────

"""
录制产物 events.json / Flow 文件 flow_<id>.json 统一结构：

{
  "id": "a1b2c3d4",                 // 8 位 hex（flow 文件）
  "name": "登录流程",
  "platform": "adb",                // web|win|mac|adb|mixed（必填，无缺省推断）
  "group": "银行相关",              // 分组（可选，随 flow 进 git）
  "description": "",
  "created_at": "2026-07-28T12:00:00",
  "meta": {                         // 平台专属元数据
    "device": "TNY-AL00",
    "resolution": [1080, 2340],
    "profiles": { "1080x2340@450": {...} },
    "default_profile": "1080x2340@450"
  },
  "steps": [
    // 动作步骤（双层）
    { "type": "event", "action": "tap", "x": 999, "y": 168,
      "delay_before_ms": 500, "delay_after_ms": 0, "is_critical": false,
      "screenshots": {"before": "screenshots/event_000_0_before.jpg",
                      "after":  "screenshots/event_000_1_after.jpg"} },
    // web 事件用 selectors 而非坐标
    { "type": "event", "action": "click",
      "selectors": [{"type":"data-testid","value":"submit"}, ...] },
    // 子流程引用（可跨平台）
    { "type": "flow", "flow_id": "e5f6g7h8" },
    // 通用系统命令（原 adb_cmd 泛化）
    { "type": "shell_cmd", "command": "..." },
    // 手动断点
    { "type": "pause", "hint": "手动登录" }
  ]
}

截图约定：
- 存放录制目录 screenshots/ 子目录；最终产物 JPG。
- 命名：event_{index:03d}_{0_before|1_after}.jpg。

选择器 fallback 链（web）：
- selectors[0] 最优先；至少含 XPath 兜底。
"""
