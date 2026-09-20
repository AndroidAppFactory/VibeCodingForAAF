"""replay-core Flow 数据模型与执行引擎单元测试（新统一契约）"""
import json
import sys
import tempfile
from pathlib import Path

# 模拟 FLOWS_DIR 指向临时目录
_scripts = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_scripts))

import core.config as config  # noqa: E402

_orig_dir = config.FLOWS_DIR
_tmp = tempfile.TemporaryDirectory()


def setup_module():
    config.FLOWS_DIR = Path(_tmp.name)
    config.FLOWS_DIR.mkdir(parents=True, exist_ok=True)
    # flow.py 在 import 时绑定了 FLOWS_DIR，需同步
    import core.flow as _flow
    _flow.FLOWS_DIR = config.FLOWS_DIR


def teardown_module():
    config.FLOWS_DIR = _orig_dir
    _tmp.cleanup()


def _clean():
    for f in config.FLOWS_DIR.iterdir():
        if f.suffix == ".json":
            f.unlink()


def _ev(action, **kw):
    """构造一个新契约动作步骤"""
    return {"type": "event", "action": action, **kw}


# ── 核心数据模型 CRUD ──────────────────────────────


def test_save_and_load_by_name():
    """保存 Flow 后可按名称加载"""
    _clean()
    from core.flow import save_flow, load_flow

    flow = {"name": "测试Flow", "platform": "adb", "steps": [_ev("tap", x=1, y=2)]}
    path = save_flow(dict(flow))
    assert path.exists()
    assert path.name.startswith("flow_")
    assert path.suffix == ".json"

    loaded = load_flow("测试Flow")
    assert loaded is not None
    assert loaded["name"] == "测试Flow"
    assert loaded["platform"] == "adb"
    assert len(loaded["steps"]) == 1
    assert loaded["id"] is not None


def test_save_and_load_by_id_prefix():
    """可按 id 前 4 位前缀查找 Flow"""
    _clean()
    from core.flow import save_flow, load_flow

    flow = {"name": "前缀查找", "platform": "web"}
    path = save_flow(dict(flow))
    data = json.loads(path.read_text(encoding="utf-8"))
    fid = data["id"]
    prefix = fid[:4]

    loaded = load_flow(prefix)
    assert loaded is not None
    assert loaded["name"] == "前缀查找"


def test_save_flow_update_by_id():
    """方案 C：带 id 保存视为更新，id 不变、内容更新"""
    _clean()
    from core.flow import save_flow

    f1 = save_flow({"name": "更新测试", "platform": "win", "steps": []})
    data1 = json.loads(f1.read_text(encoding="utf-8"))
    fid1 = data1["id"]

    f2 = save_flow({"id": fid1, "name": "更新测试", "platform": "win", "steps": [_ev("click", x=1, y=1)]})
    data2 = json.loads(f2.read_text(encoding="utf-8"))
    assert data2["id"] == fid1  # 带 id → 更新，id 不变
    assert len(data2["steps"]) == 1


def test_same_name_different_id_coexist():
    """方案 C：同名不同平台 flow 可共存（name 可重复，id 唯一）"""
    _clean()
    from core.flow import save_flow, find_flows_by_name

    save_flow({"name": "孤注一掷", "platform": "adb", "steps": []})
    save_flow({"name": "孤注一掷", "platform": "web", "steps": []})

    hits = find_flows_by_name("孤注一掷")
    assert len(hits) == 2
    assert {h["platform"] for h in hits} == {"adb", "web"}
    assert hits[0]["id"] != hits[1]["id"]  # id 各自唯一


def test_delete_flow():
    """删除 Flow 后按名称加载返回 None"""
    _clean()
    from core.flow import save_flow, load_flow, delete_flow

    save_flow({"name": "待删除", "platform": "mac", "steps": []})
    assert load_flow("待删除") is not None

    ok = delete_flow("待删除")
    assert ok is True
    assert load_flow("待删除") is None


def test_list_flows():
    """列出所有 Flow"""
    _clean()
    from core.flow import save_flow, list_flows

    save_flow({"name": "A", "platform": "adb", "steps": []})
    save_flow({"name": "B", "platform": "web", "steps": [_ev("click")]})

    flows = list_flows()
    names = {f["name"] for f in flows}
    assert names == {"A", "B"}


# ── platform 校验 ─────────────────────────────────


def test_save_flow_missing_platform_raises():
    """缺 platform 字段应报错（无历史兼容）"""
    _clean()
    from core.flow import save_flow
    import pytest

    with pytest.raises(ValueError):
        save_flow({"name": "无平台", "steps": []})


def test_save_flow_invalid_platform_raises():
    """非法 platform 值应报错"""
    _clean()
    from core.flow import save_flow
    import pytest

    with pytest.raises(ValueError):
        save_flow({"name": "错平台", "platform": "ios", "steps": []})


# ── 步骤契约校验 ──────────────────────────────────


def test_legacy_single_layer_step_raises():
    """旧单层步骤 {type:动作} 应被拒绝"""
    _clean()
    from core.flow import save_flow
    import pytest

    with pytest.raises(ValueError):
        save_flow({"name": "旧格式", "platform": "adb", "steps": [{"type": "tap", "x": 1, "y": 2}]})


def test_legacy_second_delay_raises():
    """秒单位 delay 字段应被拒绝"""
    _clean()
    from core.flow import save_flow
    import pytest

    with pytest.raises(ValueError):
        save_flow({
            "name": "秒delay", "platform": "adb",
            "steps": [_ev("tap", x=1, y=2, delay_before=1)],
        })


# ── 步骤递归展开 ──────────────────────────────────


def test_resolve_flat_events():
    """原子 Flow 直接展开为扁平步骤"""
    _clean()
    from core.flow import save_flow, resolve_flow_steps

    flow = {
        "name": "原子Flow",
        "platform": "web",
        "steps": [
            _ev("navigate", url="https://example.com"),
            _ev("click", selectors=[{"type": "class", "value": ".btn"}]),
            _ev("input", content="hello"),
        ],
    }
    save_flow(dict(flow))
    loaded = save_flow  # noqa: F841

    from core.flow import load_flow
    resolved = resolve_flow_steps(load_flow("原子Flow"))
    assert len(resolved) == 3
    assert [s["_sub_index"] for s in resolved] == [1, 2, 3]
    assert all(s["_flow_name"] == "原子Flow" for s in resolved)
    assert all(s["_platform"] == "web" for s in resolved)


def test_resolve_with_flow_ref_cross_platform():
    """跨平台子 Flow 引用：展开步骤带各自平台归属"""
    _clean()
    from core.flow import save_flow, load_flow, resolve_flow_steps

    child = {"name": "web子Flow", "platform": "web",
             "steps": [_ev("click", selectors=[])]}
    save_flow(dict(child))

    parent = {
        "name": "mixed父Flow",
        "platform": "mixed",
        "steps": [
            _ev("tap", x=1, y=1),
            {"type": "flow", "flow_id": "web子Flow"},
        ],
    }
    save_flow(dict(parent))

    resolved = resolve_flow_steps(load_flow("mixed父Flow"))
    assert len(resolved) == 2
    # 顶层原子步骤属 mixed，子 flow 步骤属 web
    assert resolved[0]["_platform"] == "mixed"
    assert resolved[1]["_flow_name"] == "web子Flow"
    assert resolved[1]["_platform"] == "web"


def test_resolve_pause_step():
    """pause 步骤保留原样"""
    _clean()
    from core.flow import save_flow, load_flow, resolve_flow_steps

    flow = {
        "name": "含暂停",
        "platform": "adb",
        "steps": [
            _ev("tap", x=1, y=1),
            {"type": "pause", "hint": "请确认"},
            _ev("tap", x=2, y=2),
        ],
    }
    save_flow(dict(flow))

    resolved = resolve_flow_steps(load_flow("含暂停"))
    assert len(resolved) == 3
    assert resolved[1]["type"] == "pause"
    assert resolved[1]["hint"] == "请确认"


def test_resolve_three_level_nesting():
    """三层嵌套 Flow：最内层原子步骤的 _flow_name 应指向最内层 Flow"""
    _clean()
    from core.flow import save_flow, load_flow, resolve_flow_steps

    # 最内层（原子）
    inner = {
        "name": "最内层原子",
        "platform": "adb",
        "steps": [
            _ev("tap", x=100, y=200),
            _ev("tap", x=300, y=400),
        ],
    }
    save_flow(dict(inner))

    # 中间层
    middle = {
        "name": "中间层",
        "platform": "adb",
        "steps": [
            _ev("tap", x=1, y=1),
            {"type": "flow", "flow_id": "最内层原子"},
        ],
    }
    save_flow(dict(middle))

    # 最外层
    outer = {
        "name": "最外层",
        "platform": "adb",
        "steps": [
            {"type": "flow", "flow_id": "中间层"},
            _ev("tap", x=999, y=999),
        ],
    }
    save_flow(dict(outer))

    resolved = resolve_flow_steps(load_flow("最外层"))
    # 中间层有 1 个事件 + 最内层有 2 个事件 + 最外层 1 个事件 = 4 步
    assert len(resolved) == 4
    # 最内层的两个步骤 _flow_name 应为 "最内层原子"
    assert resolved[1]["_flow_name"] == "最内层原子"
    assert resolved[2]["_flow_name"] == "最内层原子"
    # 中间层自己的事件应保持中间层名
    assert resolved[0]["_flow_name"] == "中间层"
    # 最外层自己的事件应是最外层名
    assert resolved[3]["_flow_name"] == "最外层"


def test_shell_cmd_step():
    """shell_cmd 结构步骤保留"""
    _clean()
    from core.flow import save_flow, load_flow, resolve_flow_steps

    flow = {
        "name": "含命令",
        "platform": "adb",
        "steps": [
            {"type": "shell_cmd", "command": "am force-stop com.x"},
            _ev("tap", x=1, y=1),
        ],
    }
    save_flow(dict(flow))
    resolved = resolve_flow_steps(load_flow("含命令"))
    assert resolved[0]["type"] == "shell_cmd"
    assert resolved[0]["command"] == "am force-stop com.x"


def test_save_name_sanitization():
    """名保护：去除特殊字符，空名兜底"""
    _clean()
    from core.flow import save_flow, load_flow

    save_flow({"name": "te<st>'a\"b", "platform": "adb", "steps": []})
    assert load_flow("testab") is not None

    save_flow({"name": "", "platform": "adb", "steps": []})
    assert load_flow("未命名") is not None


def test_save_cleans_flow_step():
    """保存时自动清理 flow 引用步骤的冗余 flow_name 字段"""
    _clean()
    from core.flow import save_flow, load_flow

    save_flow({"name": "子", "platform": "adb", "steps": [_ev("tap", x=1, y=1)]})
    save_flow({
        "name": "父",
        "platform": "adb",
        "steps": [
            {"type": "flow", "flow_id": "子", "flow_name": "子"},
        ],
    })

    loaded = load_flow("父")
    assert loaded is not None
    flow_step = loaded["steps"][0]
    assert "flow_id" in flow_step
    assert "flow_name" not in flow_step  # 已清理


def test_resolve_ref_keeps_sub_index_within_flow():
    """ref 展开的步骤，_sub_index/_sub_total 应为所属子 flow 内进度，而非父层全局序号"""
    _clean()
    from core.flow import save_flow, load_flow, resolve_flow_steps

    child = {"name": "子A", "platform": "adb",
             "steps": [_ev("tap", x=1, y=1), _ev("tap", x=2, y=2), _ev("tap", x=3, y=3)]}
    save_flow(dict(child))

    parent = {
        "name": "父",
        "platform": "adb",
        "steps": [
            {"type": "flow", "flow_id": "子A"},
            _ev("tap", x=9, y=9),
        ],
    }
    save_flow(dict(parent))

    resolved = resolve_flow_steps(load_flow("父"))
    assert len(resolved) == 4
    # 子A 3 步：_sub_index = 1,2,3（子 flow 内），_sub_total = 3
    assert [s["_sub_index"] for s in resolved[:3]] == [1, 2, 3]
    assert all(s["_sub_total"] == 3 for s in resolved[:3])
    assert all(s["_flow_name"] == "子A" for s in resolved[:3])
    # 父自己的步骤：_sub_index = 1，_sub_total = 1
    assert resolved[3]["_sub_index"] == 1
    assert resolved[3]["_sub_total"] == 1
    assert resolved[3]["_flow_name"] == "父"
