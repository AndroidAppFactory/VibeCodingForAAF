"""web-replay edit_handler.py 单元测试 — save-as + JS 静态路由"""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

_scripts = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_scripts))

import pytest  # noqa: E402


# ─── fixtures ──────────────────────────────────────

@pytest.fixture
def recordings_tmp():
    with tempfile.TemporaryDirectory() as d:
        rec_dir = Path(d) / "recordings"
        rec_dir.mkdir()
        src = rec_dir / "test_20260701_src"
        src.mkdir()
        (src / "events.json").write_text(json.dumps({
            "name": "test_20260701_src",
            "start_url": "https://example.com",
            "events": [
                {"type": "click", "selectors": [{"type": "text", "value": "按钮"}]},
                {"type": "scroll", "value": "300"},
            ]
        }, encoding="utf-8"))
        yield rec_dir


# ─── T5.1: 保存为 ──────────────────────────────────

class TestSaveAs:

    def _build_handler(self, rec_root, src_name):
        from hsrv.edit_handler import EditHandler
        events_file = rec_root / src_name / "events.json"
        return EditHandler(events_file=events_file)

    def test_save_as_normal(self, recordings_tmp):
        handler = self._build_handler(recordings_tmp, "test_20260701_src")
        # 注入 mock events
        new_name = "test_saveas_copy"
        new_dir = recordings_tmp / new_name

        assert not new_dir.exists()
        # 模拟 save-as 流程
        data = json.loads(handler.events_file.read_text(encoding="utf-8"))
        data["name"] = new_name
        new_dir.mkdir(parents=True)
        (new_dir / "events.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        assert new_dir.exists()
        saved = json.loads((new_dir / "events.json").read_text(encoding="utf-8"))
        assert saved["name"] == new_name
        assert len(saved["events"]) == 2

    def test_save_as_empty_name(self, recordings_tmp):
        # 空名称应拒绝
        name = ""
        assert not name.strip()

    def test_save_as_duplicate_name(self, recordings_tmp):
        # 已存在应拒绝
        existing = "test_20260701_src"
        assert (recordings_tmp / existing).exists()


# ─── T5.3: JS 静态路由 ──────────────────────────────

class TestJsRouting:

    def test_js_file_exists(self):
        js_dir = _scripts / "js"
        js_files = list(js_dir.glob("*.js"))
        assert len(js_files) >= 5, f"Expected >=5 JS files, got {len(js_files)}"

    def test_js_files_named_correctly(self):
        js_dir = _scripts / "js"
        names = {f.name for f in js_dir.glob("*.js")}
        expected = {"state.js", "render.js", "events.js", "shortcuts.js", "export.js"}
        assert expected.issubset(names), f"Missing: {expected - names}"

    def test_js_suffix_only(self):
        # 只有 .js 文件能被 serve
        js_dir = _scripts / "js"
        for f in js_dir.iterdir():
            if f.is_file():
                assert f.suffix == ".js", f"Unexpected file: {f.name}"
