"""replay-core Flow 数据模型与 CRUD

Flow 是步骤序列，每步可以是：
- event: 内联事件（click/input/navigate/scroll/hover/select/check/keyboard/wait）
- flow: 引用另一个 Flow（子流程）
- pause: 手动断点

文件名：flow_<8位id>.json，中文名存在 name 字段。
数据格式（flows/flow_a1b2c3d4.json）:
{
  "id": "a1b2c3d4",
  "name": "登录流程",
  "description": "...",
  "steps": [...]
}
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Optional

from core.config import FLOWS_DIR
from core.schema import normalize_flow, normalize_step

# ─── 内部工具 ──────────────────────────────────────


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


def ensure_dir() -> Path:
    FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    return FLOWS_DIR


def _iter_flow_files():
    """遍历全局仓库中的 flow 文件，产出 (path, data)。"""
    if not FLOWS_DIR.exists():
        return
    for f in sorted(FLOWS_DIR.iterdir()):
        if f.suffix != ".json" or f.name.startswith("_"):
            continue
        try:
            yield f, json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue


def _find_flow_file(name_or_id: str) -> Optional[Path]:
    """查找 flow 文件（方案 C：id 优先，name 可重复）。

    优先级：精确 id → id 前缀 → name（name 可能多个，返回第一个）。
    需要处理同名歧义时用 find_flows_by_name。
    """
    # 过滤复制粘贴时带入的不可见 Unicode 字符（​零宽空格、⁠WORD JOINER 等）
    import unicodedata
    name_or_id = "".join(
        ch for ch in name_or_id
        if unicodedata.category(ch) not in ("Cf", "Cc")
    )
    prefix_hit: Optional[Path] = None
    name_hit: Optional[Path] = None
    for f, data in _iter_flow_files():
        fid = data.get("id", "")
        if fid == name_or_id:
            return f  # 精确 id 最高优先
        if prefix_hit is None and fid and fid.startswith(name_or_id):
            prefix_hit = f
        if name_hit is None and data.get("name") == name_or_id:
            name_hit = f
    return prefix_hit or name_hit


def find_flows_by_name(name: str) -> list[dict]:
    """返回所有 name 匹配的 flow（含 id/platform），供 run 重名消歧。"""
    return [
        {"id": data.get("id", ""), "name": data.get("name", ""),
         "platform": data.get("platform", "")}
        for _, data in _iter_flow_files()
        if data.get("name") == name
    ]


def _clean_step(step: dict) -> dict:
    """清洗步骤数据，去掉冗余字段"""
    s = dict(step)
    # 引用步骤只保留 flow_id，去掉冗余的 flow_name
    if s.get("type") == "flow" and s.get("flow_id"):
        s.pop("flow_name", None)
    # 确保 is_critical 有默认值
    s.setdefault("is_critical", False)
    return s


# ─── CRUD ──────────────────────────────────────────


def save_flow(flow: dict) -> Path:
    """保存 Flow：有 id 则更新，无 id 则新建"""
    ensure_dir()
    # 名保护：去除特殊字符
    if "name" in flow:
        flow["name"] = flow["name"].replace("'", "").replace('"', "").replace("<", "").replace(">", "").strip()
        if not flow["name"]:
            flow["name"] = "未命名"

    # 清洗步骤
    steps = [_clean_step(s) for s in flow.get("steps", [])]
    flow["steps"] = steps

    # group → group_id 兼容：前端可能传旧的 "group" 字符串
    if "group" in flow and "group_id" not in flow:
        g_name = flow.pop("group", "")
        if g_name:
            flow["group_id"] = find_or_create_group(g_name)
    elif "group" in flow and "group_id" in flow:
        flow.pop("group", None)  # 有 group_id 时移除冗余 group

    # 方案 C：唯一标识是 id，name 可重复。有 id 则更新，无 id 则新建。
    # 不再按 name 查找旧文件迁移 id（name 不唯一）。
    fid = flow.get("id")
    if not fid:
        fid = _new_id()
        flow["id"] = fid

    # 顶层结构校验与补全（platform 校验、meta 下沉、步骤归一化）
    flow = normalize_flow(flow)

    # 写入文件
    f = FLOWS_DIR / f"flow_{fid}.json"
    with open(f, "w", encoding="utf-8") as fp:
        json.dump(flow, fp, ensure_ascii=False, indent=2)
    invalidate_flows_cache()
    return f


def load_flow(name_or_id: str) -> Optional[dict]:
    """根据 name 或 id（精确或前4位前缀）查找 Flow"""
    f = _find_flow_file(name_or_id)
    if f:
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def list_flows() -> list[dict]:
    """列出所有 Flow"""
    if not FLOWS_DIR.exists():
        return []
    flows = []
    for f in sorted(FLOWS_DIR.iterdir()):
        if f.suffix != ".json" or f.name.startswith("_"):
            continue
        try:
            flows.append(json.loads(f.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return flows


def delete_flow(name_or_id: str) -> bool:
    """删除 Flow（按 name 或 id）"""
    f = _find_flow_file(name_or_id)
    if f and f.exists():
        f.unlink()
        invalidate_flows_cache()
        return True
    return False


# ─── Flow 引用解析 ──────────────────────────────────


def resolve_flow_ref(step: dict) -> Optional[dict]:
    """根据步骤中的 flow_id 或 flow_name 解析引用的 Flow"""
    ref_id = step.get("flow_id", "") or step.get("flow_name", "")
    if not ref_id:
        return None
    return load_flow(ref_id)


def get_flow_id_by_name(name: str) -> str:
    """根据 Flow 名获取 id，没有则返回空字符串"""
    f = load_flow(name)
    return f["id"] if f else ""


# ─── 步骤解析（递归展开 Flow 引用）───────────────────


MAX_REF_DEPTH = 10


def resolve_steps_recursive(
    steps: list[dict],
    _flow_name: str = "",
    _flow_id: str = "",
    _platform: str = "",
    _depth: int = 0,
) -> list[dict]:
    """递归展开 Flow 步骤中的 ref 引用，返回扁平化的原子步骤列表。

    Args:
        steps: 待解析的步骤列表
        _flow_name: 当前 Flow 名称（内部递归用）
        _flow_id: 当前 Flow ID（内部递归用）
        _platform: 当前 Flow 的平台（内部递归用，用于 mixed 分段调度）
        _depth: 当前递归深度（超过 MAX_REF_DEPTH 报错）

    Returns:
        扁平化的步骤列表，ref 类型步骤已被替换为子 Flow 的展开步骤。
        每个步骤附 _flow_name、_flow_id、_sub_index、_platform 元数据。
    """
    if _depth > MAX_REF_DEPTH:
        raise ValueError(f"Flow 引用嵌套过深（超过 {MAX_REF_DEPTH} 层）")

    result: list[dict] = []
    sub_idx = 0
    for step in steps:
        stype = step.get("type", "event")

        if stype == "flow":
            ref = resolve_flow_ref(step)
            if ref:
                ref_name = ref.get("name", step.get("flow_name", "?"))
                ref_id = ref.get("id", step.get("flow_id", "?"))
                ref_platform = ref.get("platform", _platform)
                ref_steps = ref.get("steps", [])
                expanded = resolve_steps_recursive(
                    ref_steps, _flow_name=ref_name, _flow_id=ref_id,
                    _platform=ref_platform, _depth=_depth + 1,
                )
                # 父 Flow 步骤标记为关键事件时，传播到所有子步骤
                if step.get("is_critical"):
                    for s in expanded:
                        s["is_critical"] = True
                # 为展开的子步骤追加元数据（setdefault 保留子层已设的 flow 归属与
                # _sub_index/_sub_total，使 _sub_index 保持"所属 flow 内序号"而非父层全局序号）
                for s in expanded:
                    s.setdefault("_flow_name", ref_name)
                    s.setdefault("_flow_id", ref_id)
                    s.setdefault("_platform", ref_platform)
                    result.append(s)
            continue

        elif stype == "pause":
            step_copy = dict(step)
            step_copy["_flow_name"] = ""
            step_copy["_flow_id"] = ""
            step_copy["_platform"] = _platform
            step_copy["_sub_index"] = 0
            result.append(step_copy)
            continue

        # event / shell_cmd 等类型：归一化为统一契约并附来源元数据
        step_copy = normalize_step(step)
        step_copy["_flow_name"] = _flow_name
        step_copy["_flow_id"] = _flow_id
        step_copy["_platform"] = _platform
        sub_idx += 1
        step_copy["_sub_index"] = sub_idx
        result.append(step_copy)

    # 为本层直接产生的原子步骤补齐 _sub_total（= 本层原子步骤数）。
    # ref 展开的子步骤其 _sub_total 已在子层递归时设置，此处按 _flow_id 区分跳过。
    for s in result:
        if _flow_id and s.get("_flow_id") == _flow_id and s.get("_sub_index"):
            s["_sub_total"] = sub_idx

    return result


def resolve_flow_steps(flow: Optional[dict]) -> list[dict]:
    """展开 Flow 的全部步骤（含递归引用），返回扁平化列表。

    每个展开步骤附 _platform（取自所属子 flow 的 platform），供 runner 按平台分派 executor。
    """
    if not flow:
        return []
    flow_name = flow.get("name", "")
    flow_id = flow.get("id", "")
    flow_platform = flow.get("platform", "")
    steps = flow.get("steps", [])
    return resolve_steps_recursive(
        steps, _flow_name=flow_name, _flow_id=flow_id, _platform=flow_platform
    )


# ─── Flow 属性查询 ──────────────────────────────────


def is_atomic(flow: dict) -> bool:
    """原子 Flow：有步骤且不含有效 flow 引用"""
    ss = flow.get("steps", [])
    if not ss:
        return False
    return not any(
        s.get("type") == "flow" and (s.get("flow_id") or s.get("flow_name"))
        for s in ss
    )


def collect_events(steps: list[dict], depth: int = 0) -> list[dict]:
    """递归展开 Flow 步骤为扁平事件列表（纯事件，跳过 pause/shell_cmd）。

    供编辑器引用展示使用（与 resolve_flow_steps 不同：不保留 pause/shell_cmd/来源标记）。
    """
    if depth > 10:
        return []
    events: list[dict] = []
    for s in steps:
        stype = s.get("type", "")
        if stype == "flow":
            ref = resolve_flow_ref(s)
            if ref:
                events.extend(collect_events(ref.get("steps", []), depth + 1))
        elif stype not in ("pause", "shell_cmd", "adb_cmd"):
            events.append(normalize_step(s))
    return events


# ─── flows 摘要缓存 ──────────────────────────────────

_flows_cache: Optional[list[dict]] = None
_flows_cache_mtime: float = 0.0


def flows_summary() -> list[dict]:
    """返回 Flow 列表摘要，带内存缓存（FLOWS_DIR 目录 mtime 变化时刷新）"""
    global _flows_cache, _flows_cache_mtime

    if not FLOWS_DIR.exists():
        _flows_cache = []
        _flows_cache_mtime = 0
        return []

    dir_mtime = FLOWS_DIR.stat().st_mtime
    if _flows_cache is not None and dir_mtime == _flows_cache_mtime:
        return _flows_cache

    result = []
    for f in sorted(FLOWS_DIR.iterdir()):
        if f.suffix != ".json" or f.name.startswith("_"):
            continue
        try:
            flow = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        ss = flow.get("steps", [])
        atomic = is_atomic(flow)
        badge = "不可编排" if atomic else ("可编排" if len(ss) > 0 else "")
        group_id = flow.get("group_id", "")
        result.append({
            "name": flow.get("name", ""), "id": flow.get("id", ""),
            "platform": flow.get("platform", ""),
            "group_id": group_id,
            "group": get_group_name(group_id) if group_id else "",
            "steps": len(ss),
            "is_atomic": atomic, "badge": badge, "mtime": f.stat().st_mtime,
        })
    _flows_cache = result
    _flows_cache_mtime = dir_mtime
    return _flows_cache


def invalidate_flows_cache() -> None:
    """Flow 增删改后清缓存，下次请求重新扫描"""
    global _flows_cache, _flows_cache_mtime
    _flows_cache = None
    _flows_cache_mtime = 0


# ─── 分组管理（id + name）──────────────────────────────

_GROUPS_FILE = FLOWS_DIR / "_groups.json"


def _load_groups_raw() -> list[dict]:
    """从 _groups.json 加载原始数据"""
    if not _GROUPS_FILE.exists():
        return []
    try:
        return json.loads(_GROUPS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def _save_groups_raw(groups: list[dict]) -> None:
    """写入 _groups.json"""
    ensure_dir()
    with open(_GROUPS_FILE, "w", encoding="utf-8") as fp:
        json.dump(groups, fp, ensure_ascii=False, indent=2)


def list_groups() -> list[dict]:
    """列出所有分组 [{id, name}]"""
    return _load_groups_raw()


def get_group_name(group_id: str) -> str:
    """根据 group_id 获取分组名，找不到返回空字符串"""
    for g in _load_groups_raw():
        if g.get("id") == group_id:
            return g.get("name", "")
    return ""


def create_group(name: str) -> dict:
    """新建分组，返回 {id, name}"""
    groups = _load_groups_raw()
    gid = "g_" + _new_id()
    group = {"id": gid, "name": name}
    groups.append(group)
    _save_groups_raw(groups)
    return group


def rename_group(group_id: str, new_name: str) -> bool:
    """重命名分组，返回是否成功"""
    groups = _load_groups_raw()
    for g in groups:
        if g.get("id") == group_id:
            g["name"] = new_name
            _save_groups_raw(groups)
            return True
    return False


def delete_group(group_id: str) -> bool:
    """删除分组（不影响 flow 的 group_id 字段，变为"未分组"）"""
    groups = _load_groups_raw()
    new_groups = [g for g in groups if g.get("id") != group_id]
    if len(new_groups) == len(groups):
        return False
    _save_groups_raw(new_groups)
    return True


def pin_group(group_id: str, pinned: bool) -> bool:
    """置顶/取消置顶分组，返回是否成功"""
    groups = _load_groups_raw()
    for g in groups:
        if g.get("id") == group_id:
            if pinned:
                g["pinned"] = True
            else:
                g.pop("pinned", None)
            _save_groups_raw(groups)
            return True
    return False


def find_or_create_group(name: str) -> str:
    """按名称查找分组，找不到则新建，返回 group_id"""
    for g in _load_groups_raw():
        if g.get("name") == name:
            return g["id"]
    return create_group(name)["id"]
