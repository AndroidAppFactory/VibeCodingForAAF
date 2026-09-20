"""Flow 编辑器的 HTTP 处理器

Flow = 只有 flow（引用）步骤的编排器。使用 flow.html 进行可视化编排。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from core.config import FLOW_RUNS_DIR, HTML_DIR, SCRIPTS_DIR
from core.flow import save_flow, load_flow, list_flows, delete_flow
from core.hsrv.base import BaseEditHandler

# 记录当前 flow edit 关联的运行目录（供截图静态文件服务使用）
_last_run_dir: Path | None = None

# 记录当前 replay 编辑器的任务目录（供截图子请求使用，子请求不带 ?dir= 参数）
_last_replay_dir: Path | None = None


def _inject_last_run_screenshots(flow_name: str, events: list[dict]) -> None:
    """查找最近一次运行结果，将截图路径注入到 editor 事件数据中。

    截图路径格式：/flow_run_media/{step_dir}/screenshots/event_000_0_before.png
    对应 HTTP handler 的 /flow_run_media/ 路由。
    """
    global _last_run_dir

    if not FLOW_RUNS_DIR.exists():
        return

    # 查找最近一次运行目录（按目录名倒序，取第一个包含 summary.json 的）
    from core.flow import load_flow as _lf
    resolved = _lf(flow_name)
    resolved_id = resolved["id"] if resolved else ""

    run_dir = None
    is_direct = False
    for d in sorted(FLOW_RUNS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        sf = d / "summary.json"
        if not sf.exists():
            continue
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            if resolved_id and s.get("flow_id") == resolved_id:
                run_dir = d
                is_direct = True
                break
        except (json.JSONDecodeError, OSError):
            continue

    # 回退：flow 作为子 flow 运行时，找 steps 里含该 flow_id 的运行目录
    if not run_dir and resolved_id:
        for d in sorted(FLOW_RUNS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            sf = d / "summary.json"
            if not sf.exists():
                continue
            try:
                s = json.loads(sf.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if any(st.get("flow_id") == resolved_id for st in s.get("steps", [])):
                run_dir = d
                break

    if not run_dir:
        return

    _last_run_dir = run_dir

    # 从 summary.json 读取步骤对应关系
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    run_steps = summary.get("steps", [])
    # 子 flow 场景：只注入该 flow 的步骤
    if not is_direct and resolved_id:
        run_steps = [st for st in run_steps if st.get("flow_id") == resolved_id]

    # 只处理 event 类型的步骤（跳过 pause/adb_cmd）
    event_idx = 0
    for step_info in run_steps:
        if step_info.get("_skip"):
            continue
        if event_idx >= len(events):
            break

        step_dir_name = step_info.get("dir", "")
        if not step_dir_name:
            event_idx += 1
            continue

        # 从步骤的 data.json 读取截图类型
        data_file = run_dir / step_dir_name / "data.json"
        if data_file.exists():
            try:
                step_data = json.loads(data_file.read_text(encoding="utf-8"))
                step_events = step_data.get("events", [])
                if step_events and step_events[0].get("screenshots"):
                    ss = step_events[0]["screenshots"]
                    screenshots = {}
                    for phase in ("before", "after"):
                        mtype = ss.get(f"{phase}_type")
                        if mtype:
                            ext = "mp4" if mtype == "video" else "png"
                            slot = "0_before" if phase == "before" else "1_after"
                            screenshots[phase] = f"/flow_run_media/{step_dir_name}/screenshots/event_000_{slot}.{ext}"
                            screenshots[f"{phase}_type"] = mtype
                    if screenshots:
                        events[event_idx]["screenshots"] = screenshots
            except (json.JSONDecodeError, OSError):
                pass

        event_idx += 1


def _export_replay(body: dict) -> str:
    """将 Flow 的 event 步骤（递归解析引用后）导出为录制 data.json"""
    from datetime import datetime
    from core.config import REPLAY_DIR

    name = body.get("name", "flow_replay")
    steps = body.get("steps", [])
    flows_by_id = {f["id"]: f for f in list_flows() if f.get("id")}

    def _collect_events(_steps: list[dict], _depth: int = 0) -> list[dict]:
        if _depth > 10:
            return []
        events = []
        for s in _steps:
            if s.get("type") == "flow":
                ref = flows_by_id.get(s.get("flow_id", ""))
                if ref:
                    events.extend(_collect_events(ref.get("steps", []), _depth + 1))
            elif s.get("type", "event") == "event":
                ev = {"type": s.get("action", "tap")}
                for k in ("x", "y", "x1", "y1", "x2", "y2", "duration_ms",
                           "code", "content", "adb_action", "package",
                           "delay_before_ms", "delay_after_ms", "is_critical",
                           "capture_mode"):
                    if k in s and s[k] is not None and s[k] != "":
                        ev[k] = s[k]
                if s.get("adb_action"):
                    ev["action"] = s["adb_action"]
                events.append(ev)
        return events

    events = _collect_events(steps)
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    d = REPLAY_DIR / f"{ts}_{safe}"
    d.mkdir(parents=True, exist_ok=True)
    data = {"device": "flow_export", "resolution": [1080, 2340], "events": events}
    with open(d / "data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(d)


def _serve_flow_editor(handler, flow_name: str) -> bool:
    """服务 editor.html 编辑 Flow 的事件"""
    flow = load_flow(flow_name)
    if not flow:
        handler.send_response(404)
        handler.end_headers()
        return False

    # 展示用名称：URL 里传的是 id，这里取真实 name
    flow_display_name = flow.get("name") or flow_name

    # 转换为 editor 事件格式
    events = []
    for s in flow.get("steps", []):
        stype = s.get("type", "event")
        if stype == "event":
            # 黑名单：排除的字段（已通过其他方式映射）
            _READ_EXCLUDE = frozenset({
                "type", "action",    # 映射为 event.type
                "screenshots",       # 注入运行时截图，不保留原始
            })
            ev = {"type": s.get("action", "tap")}
            # 所有未排除的字段原样复制
            for k, v in s.items():
                if k in _READ_EXCLUDE:
                    continue
                if v is not None and v != "":
                    ev[k] = v
            if s.get("action") == "adb":
                ev["action"] = s.get("adb_action", s["action"])
            events.append(ev)
        elif stype == "pause":
            events.append({"type": "pause", "_task_type": "pause", "_task_hint": s.get("hint", "")})
        elif stype == "adb_cmd":
            events.append({"type": "adb_cmd", "_task_type": "adb_cmd", "_task_command": s.get("command", "")})

    # 注入最近一次运行的截图（如果有）
    _inject_last_run_screenshots(flow_name, events)

    # D19：从 meta.profiles[default_profile] 取 device/resolution
    meta = flow.get("meta", {})
    profiles = meta.get("profiles", flow.get("profiles", {}))  # 兼容旧格式
    default_profile_key = meta.get("default_profile", flow.get("default_profile", ""))
    default_profile_data = profiles.get(default_profile_key, {})
    device = default_profile_data.get("device", flow.get("device", "flow_edit"))
    resolution = default_profile_data.get("resolution", flow.get("resolution", [1080, 2340]))
    rotation = meta.get("rotation", default_profile_data.get("rotation", 0))
    data = json.dumps({"device": device, "resolution": resolution, "rotation": rotation,
                        "events": events, "_flow_name": flow_display_name}, ensure_ascii=False)

    editor_html = HTML_DIR / "editor.html"
    if not editor_html.exists():
        handler.send_response(404)
        handler.end_headers()
        return False

    html = editor_html.read_text(encoding="utf-8")
    html = html.replace('href="css/', 'href="/css/')
    html = html.replace('src="js/', 'src="/js/')
    flow_platform = flow.get("platform") or ""
    inject = f"""<script>
window.__FLOW_EDIT=true;
window.__FLOW_NAME={json.dumps(flow_display_name, ensure_ascii=False)};
window.__FLOW_PLATFORM={json.dumps(flow_platform, ensure_ascii=False)};
window.__DEVICE_PROFILES={json.dumps(profiles, ensure_ascii=False)};
window.__DEFAULT_PROFILE={json.dumps(default_profile_key, ensure_ascii=False)};
window.__EDITOR_DATA={data};
document.addEventListener('DOMContentLoaded',function(){{
  if(typeof loadData==='function'){{loadData(window.__EDITOR_DATA);}}
  window.saveFile=function(){{
    if(!state.events||!state.events.length){{alert('没有数据可保存');return;}}
    if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
    var cleanEvents=state.events.map(function(ev){{
      var copy=Object.assign({{}},ev);
      delete copy.screenshots;
      if('delay_ms' in copy&&!('delay_before_ms' in copy))copy.delay_before_ms=copy.delay_ms;
      delete copy.delay_ms;
      if(!copy.delay_before_ms)copy.delay_before_ms=1000;
      if(!copy.delay_after_ms)copy.delay_after_ms=1000;
      if(!copy.is_critical)delete copy.is_critical;
      if(!copy.capture_mode||copy.capture_mode==='screenshot')delete copy.capture_mode;
      return copy;
    }});
    var output={{events:cleanEvents,_flow_name:{json.dumps(flow_name, ensure_ascii=False)},device:state.device,resolution:state.resolution,rotation:state.rotation,profiles:deviceProfiles,currentProfile:currentProfileKey}};
    fetch('/api/editor/save',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(output)}})
      .then(function(r){{return r.json()}})
      .then(function(d){{if(d.ok){{state.isDirty=false;renderEventList();updateStats();alert('✅ 已保存到 Flow');}}else{{throw new Error(d.error||'保存失败');}}}})
      .catch(function(e){{alert('❌ '+e.message)}});
  }};
  window.saveFileAs=function(){{
    if(!state.events||!state.events.length){{alert('没有数据可保存');return;}}
    var newName=prompt('另存为新 Flow（输入名称）：','');
    if(!newName||!newName.trim())return;
    newName=newName.trim();
    if(document.activeElement&&document.activeElement.blur)document.activeElement.blur();
    var cleanEvents=state.events.map(function(ev){{
      var copy=Object.assign({{}},ev);
      delete copy.screenshots;
      if('delay_ms' in copy&&!('delay_before_ms' in copy))copy.delay_before_ms=copy.delay_ms;
      delete copy.delay_ms;
      if(!copy.delay_before_ms)copy.delay_before_ms=1000;
      if(!copy.delay_after_ms)copy.delay_after_ms=1000;
      if(!copy.is_critical)delete copy.is_critical;
      return copy;
    }});
    fetch('/api/editor/save-as',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name:newName,events:cleanEvents,device:state.device,resolution:state.resolution,rotation:state.rotation,profiles:deviceProfiles,currentProfile:currentProfileKey,platform:window.__FLOW_PLATFORM}})}})
      .then(function(r){{return r.json()}})
      .then(function(d){{if(d.ok){{state.isDirty=false;alert('✅ 已另存为 Flow「'+d.name+'」');}}else{{throw new Error(d.error||'另存失败');}}}})
      .catch(function(e){{alert('❌ '+e.message)}});
  }};
}});
</script>"""
    html = html.replace("</head>", inject + "\n</head>")
    handler._html(html.encode("utf-8"))
    return True


def _save_flow_events(flow_name: str, events: list[dict],
                      device: str = "", resolution: list | None = None,
                      profiles: dict | None = None,
                      current_profile: str = "",
                      rotation: int = 0) -> bool:
    """将 editor 事件保存回 Flow"""
    flow = load_flow(flow_name)
    if not flow:
        return False

    # 原始步骤中 event/pause/shell_cmd 类型，排除 flow/recording 等结构步骤
    _orig_steps = [s for s in flow.get("steps", []) if s.get("type") not in ("flow", "recording")]

    steps = []
    for i, ev in enumerate(events):
        tt = ev.get("_task_type", ev.get("type", "event"))
        if tt == "pause":
            steps.append({"type": "pause", "hint": ev.get("_task_hint", "")})
        elif tt == "adb_cmd":
            steps.append({"type": "adb_cmd", "command": ev.get("_task_command", "")})
        else:
            # 黑名单：从 event 拷贝到 step 时排除的内部字段
            _SAVE_BLACKLIST = frozenset({
                "type",            # 映射为 step.action
                "action",          # adb 事件时映射为 step.adb_action
                "_task_type", "_task_hint", "_task_command",
                "screenshots", "delay_ms",
            })
            step = {"type": "event", "action": ev.get("type", "tap")}
            # 所有未排除的字段原样复制
            for k, v in ev.items():
                if k in _SAVE_BLACKLIST:
                    continue
                if v is not None and v != "":
                    step[k] = v
            # adb 事件：action 映射为 adb_action
            if ev.get("type") == "adb":
                step["adb_action"] = ev.get("action", "restart")
            # is_critical 布尔值：检查 key 是否存在，false 也要写入以覆盖安全网恢复
            if "is_critical" in ev:
                step["is_critical"] = ev["is_critical"]
            else:
                step["is_critical"] = False
            # 安全网：原始 step 中有但 event 中没有的字段（正常情况不会触发）
            if i < len(_orig_steps):
                orig = _orig_steps[i]
                for k, v in orig.items():
                    if k not in _SAVE_BLACKLIST and k not in step and k not in ("type", "action", "adb_action"):
                        step[k] = v
            steps.append(step)
    flow["steps"] = steps
    # D19：device/resolution/profiles 统一存 meta，不写顶层
    if profiles or device or resolution:
        meta = flow.setdefault("meta", {})
        if profiles:
            meta["profiles"] = profiles
            meta["default_profile"] = current_profile or meta.get("default_profile", "")
        elif device and resolution:
            # 无完整 profiles 时按当前设备构建单 profile
            density = 0  # 编辑器未传 density 时默认 0
            key = f"{resolution[0]}x{resolution[1]}@{density}" if density else f"{resolution[0]}x{resolution[1]}"
            meta.setdefault("profiles", {})[key] = {"device": device, "resolution": resolution, "density": density}
            meta["default_profile"] = key
        # 清理历史顶层字段（如有）
        flow.pop("device", None)
        flow.pop("resolution", None)
        flow.pop("profiles", None)
        flow.pop("default_profile", None)
    # rotation 存 meta 顶层（横屏 90/270，竖屏 0 时清除）
    meta = flow.setdefault("meta", {})
    if rotation:
        meta["rotation"] = rotation
    else:
        meta.pop("rotation", None)
    save_flow(flow)
    return True


def _save_flow_as_new(name: str, events: list[dict],
                      device: str = "", resolution: list | None = None,
                      profiles: dict | None = None,
                      current_profile: str = "",
                      platform: str = "",
                      rotation: int = 0) -> bool:
    """将 editor 事件另存为新 Flow"""
    steps = []
    for ev in events:
        tt = ev.get("_task_type", ev.get("type", "event"))
        if tt == "pause":
            steps.append({"type": "pause", "hint": ev.get("_task_hint", "")})
        elif tt == "adb_cmd":
            steps.append({"type": "adb_cmd", "command": ev.get("_task_command", "")})
        else:
            # 黑名单：从 event 拷贝到 step 时排除的内部字段
            _SAVE_BLACKLIST = frozenset({
                "type", "action", "_task_type", "_task_hint", "_task_command",
                "screenshots", "delay_ms",
            })
            step = {"type": "event", "action": ev.get("type", "tap")}
            for k, v in ev.items():
                if k in _SAVE_BLACKLIST:
                    continue
                if v is not None and v != "":
                    step[k] = v
            if ev.get("type") == "adb":
                step["adb_action"] = ev.get("action", "restart")
            if "is_critical" in ev:
                step["is_critical"] = ev["is_critical"]
            steps.append(step)
    flow = {"name": name, "platform": platform, "description": "", "steps": steps}
    # D19：device/resolution/profiles 统一存 meta
    if profiles or device or resolution:
        meta = {}
        if profiles:
            meta["profiles"] = profiles
            meta["default_profile"] = current_profile or next(iter(profiles), "")
        elif device and resolution:
            key = f"{resolution[0]}x{resolution[1]}"
            meta["profiles"] = {key: {"device": device, "resolution": resolution, "density": 0}}
            meta["default_profile"] = key
        if rotation:
            meta["rotation"] = rotation
        flow["meta"] = meta
    save_flow(flow)
    print(f"📂 另存为新 Flow: {name}")
    return True


def _serve_flow_run_media(handler, path: str) -> bool:
    """服务 flow_runs 目录下的截图/视频文件（/flow_run_media/0001/screenshots/...）"""
    import mimetypes
    if not _last_run_dir:
        handler.send_response(404)
        handler.end_headers()
        return False

    rel = path.removeprefix("/flow_run_media/").lstrip("/")
    target = _last_run_dir / rel
    if target.is_file():
        ct, _ = mimetypes.guess_type(str(target))
        handler.send_response(200)
        handler.send_header("Content-Type", ct or "application/octet-stream")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler._safe_write(target.read_bytes())
        return True
    handler.send_response(404)
    handler.end_headers()
    return False


def _print_save_tips(flow_name: str) -> None:
    """保存后输出后续命令提示到终端日志（与其他地方保持一致）"""
    from core.cli import tips_after_flow_save
    flow = load_flow(flow_name)
    if not flow:
        return
    fid = (flow.get("id", "") or "")[:4] or flow_name
    tips_after_flow_save(fid)




def _serve_replay(handler, path):
    """服务 editor.html 重放页面"""
    global _last_replay_dir
    from urllib.parse import parse_qs, urlparse
    qs = parse_qs(urlparse(handler.path).query)
    dir_raw = qs.get("dir", [""])[0]
    # 子请求（截图/视频等）不带 ?dir= 参数，回退到上次记录的目录
    if not dir_raw and _last_replay_dir:
        dir_path = _last_replay_dir
    else:
        dir_path = Path(dir_raw) if dir_raw else Path()
    data_file = dir_path / "data.json" if str(dir_path) else None
    # win-replay 录制产物用 events.json
    if data_file and not data_file.exists() and str(dir_path):
        alt = dir_path / "events.json"
        if alt.exists():
            data_file = alt
    rel = path.removeprefix("/replay/").lstrip("/")

    if not data_file or not data_file.exists():
        handler.send_response(404); handler.end_headers(); return

    if path == "/replay/data.json" or rel == "data.json":
        handler.send_response(200)
        handler.send_header("Content-Type", "application/json"); handler.end_headers()
        handler._safe_write(data_file.read_bytes())
        return

    if rel and (dir_path / rel).exists():
        import mimetypes
        ct, _ = mimetypes.guess_type(str(dir_path / rel))
        handler.send_response(200)
        handler.send_header("Content-Type", ct or "application/octet-stream")
        handler.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        handler.end_headers()
        handler._safe_write((dir_path / rel).read_bytes())
        return

    # 记录当前 replay 目录，供后续子请求（截图/视频等，不带 ?dir= 参数）使用
    _last_replay_dir = dir_path

    editor_html = HTML_DIR / "editor.html"
    if not editor_html.exists():
        handler.send_response(404); handler.end_headers(); return

    html = editor_html.read_text(encoding="utf-8")
    # 注入平台、数据加载脚本和 dir 参数
    from urllib.parse import quote
    dir_enc = quote(str(dir_path))
    # 从录制数据中读取 platform
    platform = "adb"
    try:
        raw = data_file.read_text(encoding="utf-8")
        platform = json.loads(raw).get("platform") or "adb"
    except Exception:
        pass
    s = f"""<script>
window.__FLOW_PLATFORM={json.dumps(platform)};
window.__REPLAY_DIR={json.dumps(str(dir_path))};
(function(){{fetch('data.json?dir={dir_enc}').then(r=>r.json()).then(d=>{{if(d.events)loadData(d)}}).catch(e=>{{}});}})();
</script>"""
    html = html.replace("</head>", s + "\n</head>")
    html = html.replace('href="css/', 'href="/css/')
    html = html.replace('src="js/', 'src="/js/')
    handler._html(html.encode("utf-8"))


def make_flow_create_handler(flow, flows_api, port):
    """创建新 Flow 的 HTTP 处理器（编排器）"""
    editor_html = HTML_DIR / "flow.html"

    class _Handler(BaseEditHandler):
        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            import traceback
            p = self.path.split("?")[0]
            qs = parse_qs(urlparse(self.path).query)
            try:
                if p == "/":
                    _html = editor_html.read_text(encoding="utf-8")
                    _html = _html.replace(
                        "</head>",
                        f"<script>window.__SCRIPTS_DIR={json.dumps(str(SCRIPTS_DIR))};</script>\n</head>",
                    )
                    self._html(_html.encode("utf-8"))
                elif p.startswith("/editor/"):
                    fname = qs.get("flow", [None])[0]
                    if fname:
                        _serve_flow_editor(self, fname)
                elif p.startswith("/replay/"):
                    _serve_replay(self, p)
                elif p.startswith("/flow_run_media/"):
                    _serve_flow_run_media(self, p)
                elif p == "/api/flows":
                    self._json({"ok": True, "flows": _flows_summary()})
                elif p.startswith("/api/flows/") and len(p) > len("/api/flows/"):
                    flow_id = p[len("/api/flows/"):]
                    f = load_flow(flow_id)
                    if f:
                        self._json(f)
                    else:
                        self.send_response(404); self.end_headers()
                elif p == "/api/groups":
                    from core.flow import list_groups
                    self._json({"ok": True, "groups": list_groups()})
                elif p == "/api/flow":
                    name = qs.get("name", [None])[0]
                    if name:
                        f = load_flow(name)
                        self._json({"ok": True, "flow": f if f else {"name": name, "steps": []}})
                    else:
                        self._json({"ok": True, "flow": flow})
                else:
                    if not self._serve_static(p):
                        self.send_response(404)
                        self.end_headers()
            except Exception as e:
                import sys
                traceback.print_exc(file=sys.stderr)
                self._json({"ok": False, "error": str(e)}, status=500)

        def do_POST(self):
            import traceback as _tb
            from urllib.parse import parse_qs, urlparse
            from pathlib import Path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
                p = self.path.split("?")[0]
                qs = parse_qs(urlparse(self.path).query)
                if p == "/save":
                    dir_path = qs.get("dir", [None])[0]
                    if dir_path:
                        target = Path(dir_path) / "data.json"
                        target.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"💾 已保存: {target}")
                    self._json({"ok": True})
                elif self.path == "/api/replay/export":
                    export_dir = _export_replay(body)
                    self._json({"ok": True, "dir": export_dir})
                elif self.path == "/api/flow/save":
                    flow_data = body.get("flow", body)
                    if flow_data.get("name"):
                        save_flow(flow_data)
                        _invalidate_flows_cache()
                        print(f"📂 Flow 已保存: {flow_data['name']}")
                    self._json({"ok": True})
                elif self.path == "/api/flow/delete":
                    target = body.get("id", "")
                    if target:
                        delete_flow(target)
                        _invalidate_flows_cache()
                        print(f"🗑️  Flow 已删除: {target}")
                    self._json({"ok": True})
                elif self.path == "/api/groups/create":
                    from core.flow import create_group
                    name = body.get("name", "").strip()
                    if not name:
                        self._json({"ok": False, "error": "名称不能为空"}, status=400)
                    else:
                        group = create_group(name)
                        self._json({"ok": True, "group": group})
                elif self.path == "/api/groups/rename":
                    from core.flow import rename_group
                    gid = body.get("id", "")
                    new_name = body.get("name", "").strip()
                    if not gid or not new_name:
                        self._json({"ok": False, "error": "缺少 id 或 name"}, status=400)
                    else:
                        ok = rename_group(gid, new_name)
                        _invalidate_flows_cache()
                        self._json({"ok": ok})
                elif self.path == "/api/groups/delete":
                    from core.flow import delete_group
                    gid = body.get("id", "")
                    if gid:
                        delete_group(gid)
                        _invalidate_flows_cache()
                    self._json({"ok": True})
                elif self.path == "/api/groups/pin":
                    from core.flow import pin_group
                    gid = body.get("id", "")
                    if gid:
                        pin_group(gid, bool(body.get("pinned", False)))
                        _invalidate_flows_cache()
                    self._json({"ok": True})
                elif self.path == "/api/editor/save":
                    fname = body.get("_flow_name", body.get("name", ""))
                    events = body.get("events", [])
                    device = body.get("device", "")
                    resolution = body.get("resolution")
                    profiles = body.get("profiles")
                    current_profile = body.get("currentProfile", "")
                    if fname and _save_flow_events(fname, events, device=device, resolution=resolution,
                                                    profiles=profiles, current_profile=current_profile,
                                                    rotation=body.get("rotation", 0)):
                        _invalidate_flows_cache()
                        print(f"📝 Flow 事件已更新: {fname}")
                        _print_save_tips(fname)
                        self._json({"ok": True})
                    else:
                        self._json({"ok": False, "error": "保存失败"}, 500)
                elif self.path == "/api/editor/save-as":
                    new_name = body.get("name", "").strip()
                    events = body.get("events", [])
                    device = body.get("device", "")
                    resolution = body.get("resolution")
                    profiles = body.get("profiles")
                    current_profile = body.get("currentProfile", "")
                    platform = body.get("platform", "")
                    if not new_name:
                        self._json({"ok": False, "error": "名称不能为空"}, 400)
                    else:
                        _save_flow_as_new(new_name, events, device=device, resolution=resolution,
                                          profiles=profiles, current_profile=current_profile,
                                          platform=platform, rotation=body.get("rotation", 0))
                        _invalidate_flows_cache()
                        self._json({"ok": True, "name": new_name})
                elif self.path == "/api/close":
                    os._exit(0)
                else:
                    self._json({"ok": False})
            except Exception as e:
                import sys as _sys
                _tb.print_exc(file=_sys.stderr)
                self._json({"ok": False, "error": str(e)}, status=500)

    return _Handler


# ─── flows 缓存（避免每次请求都扫描磁盘） ──────────

_flows_cache: list[dict] | None = None
_flows_cache_mtime: float = 0.0


def _flows_summary() -> list[dict]:
    """返回 Flow 列表摘要，带内存缓存（目录 mtime 变化时刷新）"""
    global _flows_cache, _flows_cache_mtime
    import json
    from core.config import FLOWS_DIR

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
            with open(f, "r", encoding="utf-8") as fp:
                flow = json.load(fp)
        except (json.JSONDecodeError, OSError):
            continue
        ss = flow.get("steps", [])
        atomic = len(ss) > 0 and all(s.get("type", "event") != "flow" for s in ss)
        badge = "不可编排" if atomic else ("可编排" if len(ss) > 0 else "")
        meta = flow.get("meta", {})
        profiles_data = meta.get("profiles", flow.get("profiles", {}))
        profiles_summary = {k: v.get("device", "") for k, v in profiles_data.items()}
        group_id = flow.get("group_id", "")
        from core.flow import get_group_name
        result.append({"name": flow["name"], "id": flow.get("id", ""), "platform": flow.get("platform", ""),
                        "group_id": group_id,
                        "group": get_group_name(group_id) if group_id else "",
                        "steps": len(ss),
                        "is_atomic": atomic, "badge": badge, "mtime": f.stat().st_mtime,
                        "default_profile": meta.get("default_profile", flow.get("default_profile", "")),
                        "profile_count": len(profiles_data),
                        "profiles": profiles_summary})
    _flows_cache = result
    _flows_cache_mtime = dir_mtime
    return _flows_cache


def _invalidate_flows_cache():
    """Flow 增删改后清缓存，下次请求重新扫描"""
    global _flows_cache, _flows_cache_mtime
    _flows_cache = None
    _flows_cache_mtime = 0


def make_flow_edit_handler(flow, flows_api, port):
    """编辑已有 Flow 的 HTTP 处理器（编排器）"""
    editor_html_ = HTML_DIR / "flow.html"
    flow_name = flow["name"]

    class _Handler(BaseEditHandler):
        def do_GET(self):
            from urllib.parse import parse_qs, urlparse
            p = self.path.split("?")[0]
            qs = parse_qs(urlparse(self.path).query)
            if p == "/":
                html = editor_html_.read_bytes()
                flow_js = json.dumps(flow_name, ensure_ascii=False)
                init_script = f"<script>window.__INIT_FLOW={flow_js}</script>".encode("utf-8")
                html = html.replace(b"</head>", init_script + b"\n</head>")
                self._html(html)
            elif p.startswith("/editor/"):
                fname = qs.get("flow", [None])[0]
                if fname:
                    _serve_flow_editor(self, fname)
            elif p.startswith("/replay/"):
                _serve_replay(self, p)
            elif p.startswith("/flow_run_media/"):
                _serve_flow_run_media(self, p)
            elif p == "/api/flows":
                self._json({"ok": True, "flows": _flows_summary()})
            elif p == "/api/groups":
                from core.flow import list_groups
                self._json({"ok": True, "groups": list_groups()})
            elif p == "/api/flow":
                name = qs.get("name", [None])[0]
                if name:
                    f = load_flow(name)
                    self._json({"ok": True, "flow": f if f else {"name": name, "steps": []}})
                else:
                    self._json({"ok": True, "flow": flow})
            else:
                if not self._serve_static(p):
                    self.send_response(404)
                    self.end_headers()

        def do_POST(self):
            import traceback as _tb
            from urllib.parse import parse_qs, urlparse
            from pathlib import Path
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8"))
                p = self.path.split("?")[0]
                qs = parse_qs(urlparse(self.path).query)
                if p == "/save":
                    dir_path = qs.get("dir", [None])[0]
                    if dir_path:
                        target = Path(dir_path) / "data.json"
                        target.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
                        print(f"💾 已保存: {target}")
                    self._json({"ok": True})
                elif self.path == "/api/replay/export":
                    export_dir = _export_replay(body)
                    self._json({"ok": True, "dir": export_dir})
                elif self.path == "/api/flow/save":
                    flow_data = body.get("flow", body)
                    if flow_data.get("name"):
                        save_flow(flow_data)
                        _invalidate_flows_cache()
                        print(f"📂 Flow 已保存: {flow_data['name']}")
                    self._json({"ok": True})
                elif self.path == "/api/flow/delete":
                    target = body.get("id", "")
                    if target:
                        delete_flow(target)
                        _invalidate_flows_cache()
                        print(f"🗑️  Flow 已删除: {target}")
                    self._json({"ok": True})
                elif self.path == "/api/groups/create":
                    from core.flow import create_group
                    name = body.get("name", "").strip()
                    if not name:
                        self._json({"ok": False, "error": "名称不能为空"}, status=400)
                    else:
                        group = create_group(name)
                        self._json({"ok": True, "group": group})
                elif self.path == "/api/groups/rename":
                    from core.flow import rename_group
                    gid = body.get("id", "")
                    new_name = body.get("name", "").strip()
                    if not gid or not new_name:
                        self._json({"ok": False, "error": "缺少 id 或 name"}, status=400)
                    else:
                        ok = rename_group(gid, new_name)
                        _invalidate_flows_cache()
                        self._json({"ok": ok})
                elif self.path == "/api/groups/delete":
                    from core.flow import delete_group
                    gid = body.get("id", "")
                    if gid:
                        delete_group(gid)
                        _invalidate_flows_cache()
                    self._json({"ok": True})
                elif self.path == "/api/groups/pin":
                    from core.flow import pin_group
                    gid = body.get("id", "")
                    if gid:
                        pin_group(gid, bool(body.get("pinned", False)))
                        _invalidate_flows_cache()
                    self._json({"ok": True})
                elif self.path == "/api/editor/save":
                    fname = body.get("_flow_name", body.get("name", ""))
                    events = body.get("events", [])
                    device = body.get("device", "")
                    resolution = body.get("resolution")
                    profiles = body.get("profiles")
                    current_profile = body.get("currentProfile", "")
                    if fname and _save_flow_events(fname, events, device=device, resolution=resolution,
                                                    profiles=profiles, current_profile=current_profile,
                                                    rotation=body.get("rotation", 0)):
                        _invalidate_flows_cache()
                        print(f"📝 Flow 事件已更新: {fname}")
                        _print_save_tips(fname)
                        self._json({"ok": True})
                    else:
                        self._json({"ok": False, "error": "保存失败"}, 500)
                elif self.path == "/api/editor/save-as":
                    new_name = body.get("name", "").strip()
                    events = body.get("events", [])
                    device = body.get("device", "")
                    resolution = body.get("resolution")
                    profiles = body.get("profiles")
                    current_profile = body.get("currentProfile", "")
                    platform = body.get("platform", "")
                    if not new_name:
                        self._json({"ok": False, "error": "名称不能为空"}, 400)
                    else:
                        _save_flow_as_new(new_name, events, device=device, resolution=resolution,
                                          profiles=profiles, current_profile=current_profile,
                                          platform=platform, rotation=body.get("rotation", 0))
                        _invalidate_flows_cache()
                        self._json({"ok": True, "name": new_name})
                elif self.path == "/api/close":
                    os._exit(0)
                else:
                    self._json({"ok": False})
            except Exception as e:
                import sys as _sys
                _tb.print_exc(file=_sys.stderr)
                self._json({"ok": False, "error": str(e)}, status=500)

    return _Handler
