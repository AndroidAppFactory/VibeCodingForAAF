"""adb-replay Flow 报告渲染 — 三种场景 + 布局约束验证

对应 tasks.md 任务 17/18，验证标准见 `.sdd/designs/adb-replay-report-v2.md` 第4/5节 AC1-AC4。

运行方式（本 skill 无独立 pytest 配置，需显式指定路径）：
    python3 -m pytest skills/test/adb-replay/scripts/tests/test_flow_report_scenarios.py -v
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_TESTS_DIR = Path(__file__).resolve().parent
_SCRIPTS_DIR = _TESTS_DIR.parent
for _p in (_SCRIPTS_DIR, _TESTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from flow_report import generate_flow_report  # noqa: E402
from fixtures import build_scenario, build_wide_compare  # noqa: E402


def _render(scenario: str, tmp_path: Path) -> str:
    run_dir, summary = build_scenario(scenario, tmp_path)
    report_file = generate_flow_report(run_dir, summary)
    return report_file.read_text(encoding="utf-8")


def test_scenario_a_atomic_flow_no_compare_panel(tmp_path):
    """场景 A（原子 Flow）：全部 entries=1，全对比面板数量为 0（AC1）"""
    html = _render("A", tmp_path)
    assert html.count('class="compare-panel" id="compare-') == 0
    # 关键事件面板：1 个关键步骤（swipe） → before/after 合并为 1 个 block
    assert '<span class="badge">1 组</span>' in html


def test_scenario_b_non_atomic_no_duplicate_no_compare_panel(tmp_path):
    """场景 B（非原子 Flow，子 Flow 无重复引用）：全对比面板数量为 0（AC2）"""
    html = _render("B", tmp_path)
    assert html.count('class="compare-panel" id="compare-') == 0
    # 关键事件面板：2 个关键步骤 → before/after 合并为 2 个 block
    assert '<span class="badge">2 组</span>' in html


def test_scenario_c_duplicate_ref_produces_compare_and_critical_panels(tmp_path):
    """场景 C（非原子 Flow，子 Flow 重复引用）：全对比 1 组（启动App 按 flow 合并），关键事件 2 组（AC3）"""
    html = _render("C", tmp_path)
    assert html.count('class="compare-panel" id="compare-') == 1
    assert '<span class="badge">2 组</span>' in html

    # 关键事件面板中，"启动App|2" 组 entries=2（重复引用 2 次）→ before/after 合并，多次运行时 phase 标签附带执行序号
    critical_section = html.split('id="flat-all"')[1]
    # 多次运行的执行序号：phase 标签应含 #02/#05
    assert re.search(r'#02 before</div>', critical_section)
    assert re.search(r'#05 before</div>', critical_section)
    # block 排序：#02（启动App）应先于 #03（检查首页）出现
    idx_02 = critical_section.find("#02")
    idx_03 = critical_section.find("#03")
    assert 0 <= idx_02 < idx_03
    # header 标注所属 Flow 及其在该 Flow 内的序号（sub_index）
    assert "[启动App 第2步]" in critical_section
    assert "[检查首页 第1步]" in critical_section


def test_scenario_c_critical_panel_double_display_is_expected(tmp_path):
    """场景 C：`启动App|2` 组的截图应同时出现在全对比面板与关键事件面板（预期双重展示，非 bug）"""
    html = _render("C", tmp_path)
    src = "0002/screenshots/event_000_0_before.png"
    assert html.count(src) >= 2


def test_wide_compare_block_width_capped_at_3_columns(tmp_path):
    """8 entries 对比组：cv-block 宽度按 min(8,3)=3 列换算（默认 3 列）"""
    run_dir, summary = build_wide_compare(tmp_path, n_entries=8)
    report_file = generate_flow_report(run_dir, summary)
    html = report_file.read_text(encoding="utf-8")

    col_w = max(180, 600 // 3)  # = 200
    expected_width = 3 * col_w + 2 * 8 + 24 + 4  # = 644
    assert f"width:{expected_width}px" in html
    assert "overflow-x: auto" not in html
    assert "flex-wrap: wrap" in html
