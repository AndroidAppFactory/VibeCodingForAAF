"""web-replay 录制引擎

Playwright 驱动 Chromium，注入事件监听器，录制用户操作并提取 DOM 选择器。

用法：
    from web_recorder import start_recording
    events_path, screenshots_dir = start_recording("my-flow", url="https://example.com")
"""

from __future__ import annotations

import json
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

_replay_core = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_replay_core) not in sys.path:
    sys.path.insert(0, str(_replay_core))

from core.schema import EventType  # noqa: E402

STOP_HOTKEY = "Control+Shift+E"

# ─── 内部页面识别 ──────────────────────────────────

def _is_internal_url(url: str) -> bool:
    """判断是否为浏览器内部 scheme（chrome://、devtools:// 等）。

    此类 URL 是自动化控制的 Chromium 环境噪声（如新标签页的 chrome://newtab/
    在自动化模式下可能退化为 chrome-error://chromewebdata/），不代表用户真实
    导航意图，不应被记录为可回放的 navigate 事件。
    """
    if not url:
        return False
    return url.startswith(("chrome://", "chrome-error://", "devtools://", "edge://"))

# ─── 录制产物目录 ──────────────────────────────────

def _recordings_dir() -> Path:
    import os as _os
    base = Path(_os.environ.get("ZIXIEKIT_TMP", str(Path.home() / ".zixiekit")))
    return base / "skill" / "web-replay" / "recordings"

# ─── 选择器提取器 ───────────────────────────────────

_SELECTOR_EXTRACTOR = """
function __extractSelectors(el) {
    if (!el || el === document.body || el === document.documentElement) return [];
    const selectors = [];

    // 1. 元素自身属性优先
    const tid = el.getAttribute('data-testid');
    if (tid) selectors.push({type:'data-testid',value:'[data-testid=\"'+tid+'\"]'});
    if (el.id) selectors.push({type:'id',value:'#'+CSS.escape(el.id)});
    const al = el.getAttribute('aria-label');
    if (al) selectors.push({type:'aria-label',value:'[aria-label=\"'+al+'\"]'});

    // 2. 文本内容
    const txt = (el.textContent||'').trim();
    if (txt && txt.length < 200 && (!el.children.length || txt===(el.innerText||'').trim())) {
        selectors.push({type:'text',value:txt});
    }

    // 3. class 最短唯一组合
    if (el.className && typeof el.className === 'string') {
        const classes = el.className.trim().split(/\\s+/).filter(Boolean);
        if (classes.length) {
            let found = false;
            for (let i=0; i<classes.length; i++) {
                const combo = '.' + classes.slice(0,i+1).map(c => CSS.escape(c)).join('.');
                if (document.querySelectorAll(combo).length === 1) {
                    selectors.push({type:'class',value:combo}); found=true; break;
                }
            }
            if (!found) selectors.push({type:'class',value:'.'+classes.map(c=>CSS.escape(c)).join('.')});
        }
    }

    // 4. nth-child
    if (el.parentElement) {
        const sibs = Array.from(el.parentElement.children).filter(c => c.tagName === el.tagName);
        if (sibs.length>1) selectors.push({type:'nth-child',value:el.tagName.toLowerCase()+':nth-child('+(sibs.indexOf(el)+1)+')'});
    }

    // 5. 祖先属性兜底（仅 data-testid, aria-label，不含 id）
    let node = el.parentElement;
    while (node && node !== document.body) {
        const atid = node.getAttribute('data-testid');
        if (atid && !selectors.find(s=>s.type==='data-testid')) selectors.push({type:'data-testid',value:'[data-testid=\"'+atid+'\"]'});
        const aal = node.getAttribute('aria-label');
        if (aal && !selectors.find(s=>s.type==='aria-label')) selectors.push({type:'aria-label',value:'[aria-label=\"'+aal+'\"]'});
        node = node.parentElement;
    }

    // 6. xpath 兜底
    function getXpath(e) {
        if (e===document.body) return '/html/body';
        if (e.id) return '//*[@id=\"'+CSS.escape(e.id)+'\"]';
        let p='', cur=e;
        while (cur && cur!==document.body) {
            let tag=cur.tagName.toLowerCase(), idx=1, sib=cur.previousElementSibling;
            while (sib){if(sib.tagName===cur.tagName)idx++; sib=sib.previousElementSibling;}
            p='/'+tag+(cur.parentElement&&cur.parentElement.querySelectorAll(tag).length>1?'['+idx+']':'')+p;
            cur=cur.parentElement;
        }
        p='/html/body'+p;
        try{if(document.evaluate(p,document,null,XPathResult.FIRST_ORDERED_NODE_TYPE,null).singleNodeValue!==e)p='';}catch(ex){p='';}
        return p;
    }
    const xp = getXpath(el);
    if (xp) selectors.push({type:'xpath',value:xp});
    return selectors;
}
"""

# ─── 录制主流程 ────────────────────────────────────

def start_recording(
    name: str,
    url: str = "",
    profile: Optional[Path] = None,
) -> tuple[Path, Path]:
    from playwright.sync_api import sync_playwright

    rec_dir = _recordings_dir() / name
    rec_dir.mkdir(parents=True, exist_ok=True)
    ss_dir = rec_dir / "screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    events: list[dict] = []
    event_index = 0
    # 保护 event_index/events：context.on("page"/"dialog") 回调可能在主循环执行
    # 同步阻塞调用（evaluate/screenshot）期间被 Playwright dispatcher 线程重入触发，
    # 与主循环并发分配 idx 会导致 index 重复/事件错乱（曾观测到 #05 click 与 #05 switch_tab 撞号）
    _state_lock = threading.Lock()
    stopped = False
    global_start = time.time()
    ic_map = {"click": "📍", "select": "📋", "check": "☑️", "keyboard": "⌨️",
              "input": "📝", "navigate": "🔗", "scroll": "📜", "switch_tab": "🗂", "alert": "🔔"}

    def _now():
        return datetime.fromtimestamp(time.time()).strftime("%H:%M:%S")

    def _elapsed():
        return time.time() - global_start

    def _log(msg=""):
        print(f"  [{_now()} +{_elapsed():05.1f}s] {msg}")

    def _log_event(idx, etype, detail=""):
        icon = ic_map.get(etype, "❓")
        parts = [f"{icon} #{idx:02d} {etype}"]
        if detail:
            parts.append(detail)
        _log(" | ".join(parts))

    _log("=== 录制引擎启动 ===")
    _log(f"名称={name} 起始URL={url or 'about:blank'} profile={'持久化' if profile else '临时'}")

    with sync_playwright() as p:
        launch_args = {"headless": False, "args": ["--start-maximized"]}
        if profile:
            profile = Path(profile).resolve()
            profile.parent.mkdir(parents=True, exist_ok=True)
            context = p.chromium.launch_persistent_context(user_data_dir=str(profile), **launch_args)
            _log(f"浏览器启动(持久化) | profile={profile}")
            _browser_ver = p.chromium.executable_path
        else:
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(no_viewport=True)
            _log(f"浏览器启动(临时) | Chromium={browser.version}")
            _browser_ver = browser.version

        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url if url else "about:blank", wait_until="domcontentloaded")
        _log(f"页面加载 | url={page.url} | title=\"{page.title()}\"")
        _viewport = page.viewport_size or {}
        _log(f"🖥 环境 | 视口={_viewport.get('width','?')}x{_viewport.get('height','?')} | OS={sys.platform}")

        # 注入监听器（必须在导航之后）
        all_pages: set = {id(page)}

        def _inject_listeners(target_page):
            try:
                target_page.evaluate("""
                (function() {
                """ + _SELECTOR_EXTRACTOR + """
                window.__wrEvents = window.__wrEvents || [];

                // 文本输入采集：失焦/Enter/Tab/点击别处时提交最终值（而非逐字符记录），
                // 用 __wrLastVal 标记去重，避免同一次输入被提交多次
                function __isTextInput(el) {
                    if (!el) return false;
                    if (el.isContentEditable) return true;
                    const tag = el.tagName;
                    if (tag === 'TEXTAREA') return true;
                    if (tag !== 'INPUT') return false;
                    const t = (el.type || 'text').toLowerCase();
                    return !['checkbox','radio','file','range','color','button','submit','reset','image'].includes(t);
                }
                function __maybeEmitInput(el) {
                    if (!__isTextInput(el)) return;
                    if (!el.__wrDirty) return;  // 未被真实编辑过（如页面 autofocus 又程序化 blur），跳过噪声
                    const val = el.isContentEditable ? (el.innerText || '') : (el.value || '');
                    if (el.__wrLastVal === val) return;
                    el.__wrLastVal = val;
                    el.__wrDirty = false;
                    try {
                        const sels = __extractSelectors(el);
                        window.__wrEvents.push({type:'input',selectors:sels,url:location.href,value:val,ts:Date.now()/1000});
                    } catch(err) {
                        console.error('wr input error:', err);
                    }
                }
                document.addEventListener('input', function(e) {
                    if (__isTextInput(e.target)) e.target.__wrDirty = true;
                }, true);
                document.addEventListener('click', function(e) {
                    __maybeEmitInput(document.activeElement);
                    try {
                        const sels = __extractSelectors(e.target);
                        window.__wrEvents.push({type:'click',selectors:sels,url:location.href,ts:Date.now()/1000,tag:e.target.tagName,text:(e.target.textContent||'').trim().slice(0,50)});
                    } catch(err) {
                        console.error('wr click error:', err);
                        window.__wrEvents.push({type:'click',selectors:[],url:location.href,ts:Date.now()/1000,error:err.message});
                    }
                }, true);
                document.addEventListener('change', function(e) {
                    try {
                        const el = e.target;
                        if (el.tagName === 'SELECT') {
                            const sels = __extractSelectors(el);
                            window.__wrEvents.push({type:'select',selectors:sels,url:location.href,value:el.value,ts:Date.now()/1000});
                        } else if (el.type === 'checkbox' || el.type === 'radio') {
                            const sels = __extractSelectors(el);
                            window.__wrEvents.push({type:'check',selectors:sels,url:location.href,value:String(el.checked),ts:Date.now()/1000});
                        } else {
                            __maybeEmitInput(el);
                        }
                    } catch(err) {
                        console.error('wr change error:', err);
                    }
                }, true);
                document.addEventListener('blur', function(e) {
                    __maybeEmitInput(e.target);
                }, true);
                document.addEventListener('keydown', function(e) {
                    if (e.ctrlKey && e.shiftKey && e.code === 'KeyE') {
                        window.__wrStopRequested = true;
                        return;
                    }
                    if (e.key === 'Enter' || e.key === 'Escape' || e.key === 'Tab') {
                        __maybeEmitInput(document.activeElement);
                        window.__wrEvents.push({type:'keyboard',key:e.key,url:location.href,ts:Date.now()/1000});
                    }
                }, true);
                window.__wrEvents.push({type:'_inject_ok',ts:Date.now()/1000});
                })();
                """)
                return True
            except Exception as e:
                _log(f"监听器注入失败 | url={target_page.url[:50]} | error={e}")
                return False

        ok = _inject_listeners(page)
        _log(f"首页监听器注入 | ok={ok} | {len(context.pages)}个页面")

        # 将初始页面加载记录为第一个事件
        event_index += 1
        idx = event_index
        before = ss_dir / f"{idx:04d}_before.jpg"
        try:
            page.screenshot(path=str(before), full_page=False, type="jpeg", quality=85)
        except Exception:
            pass
        events.append({
            "index": idx, "type": "event", "action": EventType.NAVIGATE.value,
            "selectors": [], "url": page.url, "value": page.url,
            "screenshots": {"before": f"screenshots/{idx:04d}_before.jpg"},
            "timestamp": time.time(), "tab_id": 0,
        })
        _log_event(idx, "navigate", f"page=0 url={page.url[:60]}")

        # 新 Tab 监听
        def _on_new_page(new_page):
            nonlocal event_index
            with _state_lock:
                all_pages.add(id(new_page))
            _log(f"检测到新Tab | url={new_page.url}")
            try:
                new_page.wait_for_load_state("domcontentloaded", timeout=15000)
                _log(f"新Tab加载完成 | title=\"{new_page.title()}\"")
            except Exception as e:
                _log(f"新Tab加载超时 | {e}")
            ok = _inject_listeners(new_page)
            _log(f"新Tab监听器注入 | ok={ok}")
            # idx 分配与 events.append 必须在同一把锁内完成，禁止用 len(events)+1
            # 计算下标（曾与主循环并发导致 index 撞号，如 #05 click 与 #05 switch_tab）
            with _state_lock:
                event_index += 1
                idx = event_index
                events.append({
                    "index": idx, "type": "event", "action": EventType.SWITCH_TAB.value,
                    "selectors": [], "url": new_page.url, "value": str(len(context.pages) - 1),
                    "screenshots": {"before": f"screenshots/{idx:04d}_before.jpg"},
                    "timestamp": time.time(), "tab_id": len(context.pages) - 1,
                })
            before = ss_dir / f"{idx:04d}_before.jpg"
            try:
                new_page.screenshot(path=str(before), full_page=False, type="jpeg", quality=85)
            except Exception:
                pass
            _log_event(idx, "switch_tab", f"tab={len(context.pages)-1} url={new_page.url}")

        context.on("page", _on_new_page)

        # 窗口关闭兜底停止
        _window_closed = False

        def _on_page_close(closed_page):
            nonlocal _window_closed
            remaining = [p for p in context.pages if not p.is_closed()]
            if not remaining:
                _window_closed = True
                _log("浏览器窗口已关闭，停止录制")

        context.on("page", lambda p: p.on("close", lambda: _on_page_close(p)))

        _log(f"🎬 开始监听用户操作 | 产物={rec_dir} | 按Ctrl+C停止\n")

        # 弹窗处理
        def _on_dialog(dialog):
            nonlocal event_index
            with _state_lock:
                event_index += 1
                idx = event_index
                events.append({
                    "index": idx, "type": "event", "action": EventType.ALERT.value,
                    "selectors": [], "url": page.url,
                    "value": json.dumps({"type": dialog.type, "message": dialog.message}),
                    "screenshots": {"before": f"screenshots/{idx:04d}_before.jpg"},
                    "timestamp": time.time(), "tab_id": 0,
                })
            _log(f"检测到弹窗 | type={dialog.type} msg={dialog.message[:60]}")
            before = ss_dir / f"{idx:04d}_before.jpg"
            try:
                page.screenshot(path=str(before), full_page=False, type="jpeg", quality=85)
            except Exception:
                pass
            dialog.accept()
            _log_event(idx, "alert", f"type={dialog.type} msg=\"{dialog.message[:40]}\"")

        page.on("dialog", _on_dialog)

        url_states: dict = {}
        scroll_states: dict = {}
        for p in context.pages:
            url_states[id(p)] = p.url

        # ── 主事件循环 ──
        try:
            while not stopped:
                time.sleep(0.3)

                # 窗口关闭兜底
                if _window_closed:
                    _log("⏹ 浏览器窗口已关闭，停止录制")
                    break

                # 热键停止检测 (Ctrl+Shift+E)
                for p in context.pages:
                    try:
                        if p.is_closed():
                            continue
                        stop_req = p.evaluate("() => !!window.__wrStopRequested")
                        if stop_req:
                            _log("⏹ 检测到热键 Ctrl+Shift+E，停止录制")
                            stopped = True
                            break
                    except Exception:
                        pass

                # 检测新页面
                for p in context.pages:
                    pid = id(p)
                    with _state_lock:
                        is_new = pid not in all_pages
                        if is_new:
                            all_pages.add(pid)
                    if is_new:
                        _log(f"发现未监听页面(可能由其他方式打开) | url={p.url}")
                        _inject_listeners(p)
                        url_states[pid] = p.url

                # URL 变化检测
                for p_idx, p in enumerate(context.pages):
                    try:
                        pid = id(p)
                        cur = p.url
                        if pid not in url_states:
                            url_states[pid] = cur
                            continue
                        if cur != url_states[pid]:
                            old = url_states[pid]
                            url_states[pid] = cur
                            if _is_internal_url(cur):
                                # 浏览器内部页面（环境噪声），不记录 navigate 事件，
                                # 也无 DOM 可注入监听器，直接跳过
                                continue
                            with _state_lock:
                                event_index += 1
                                idx = event_index
                                events.append({
                                    "index": idx, "type": "event", "action": EventType.NAVIGATE.value,
                                    "selectors": [], "url": cur, "value": cur,
                                    "screenshots": {"before": f"screenshots/{idx:04d}_before.jpg"},
                                    "timestamp": time.time(), "tab_id": p_idx,
                                })
                            before = ss_dir / f"{idx:04d}_before.jpg"
                            p.screenshot(path=str(before), full_page=False, type="jpeg", quality=85)
                            _log_event(idx, "navigate", f"from={old[:60]} → {cur[:60]}")
                            _inject_listeners(p)
                    except Exception:
                        pass

                # 用户事件轮询
                for p_idx, p in enumerate(context.pages):
                    try:
                        pending = p.evaluate("""
                            (() => {
                                const evs = window.__wrEvents || [];
                                window.__wrEvents = [];
                                return JSON.stringify(evs);
                            })()
                        """)
                        if not pending or pending == "[]":
                            continue
                        raw = json.loads(pending)
                    except Exception as e:
                        _log(f"事件轮询异常 | page={p_idx} error={e}")
                        continue

                    for rev in raw:
                        if rev.get("type") == "_inject_ok":
                            continue
                        if stopped:
                            break
                        etype = rev.get("type", "?")
                        ts = rev.get("ts", time.time())
                        sels = rev.get("selectors", [])
                        sel_types = [s.get("type", "?") for s in sels[:3]]

                        with _state_lock:
                            event_index += 1
                            idx = event_index
                            events.append({
                                "index": idx, "type": "event", "action": etype,
                                "selectors": sels,
                                "url": rev.get("url", p.url),
                                "value": rev.get("value", rev.get("key", "")),
                                "screenshots": {
                                    "before": f"screenshots/{idx:04d}_before.jpg",
                                    "after": f"screenshots/{idx:04d}_after.jpg",
                                },
                                "timestamp": ts, "tab_id": p_idx,
                            })

                        # 截图
                        before_path = ss_dir / f"{idx:04d}_before.jpg"
                        try:
                            p.screenshot(path=str(before_path), full_page=False, type="jpeg", quality=85)
                        except Exception:
                            pass
                        after_path = ss_dir / f"{idx:04d}_after.jpg"
                        try:
                            p.screenshot(path=str(after_path), full_page=False, type="jpeg", quality=85)
                        except Exception:
                            pass

                        detail_parts = [f"page={p_idx}"]
                        if sel_types:
                            detail_parts.append(f"selectors={sel_types}")
                        if etype == "click":
                            tag = rev.get("tag", "")
                            txt = rev.get("text", "")
                            detail_parts.append(f"tag=<{tag}> text=\"{txt}\"")
                        elif etype in ("select", "check", "input"):
                            detail_parts.append(f"value={rev.get('value','')}")
                        elif etype == "keyboard":
                            detail_parts.append(f"key={rev.get('key','')}")
                        err = rev.get("error")
                        if err:
                            detail_parts.append(f"ERROR={err}")
                        _log_event(idx, etype, " | ".join(detail_parts))

                # 滚动检测
                try:
                    for p_idx, p in enumerate(context.pages):
                        try:
                            y = p.evaluate("window.scrollY")
                            key = f"{id(p)}_scroll"
                            old = scroll_states.get(key, 0)
                            if abs(y - old) > 150:
                                scroll_states[key] = y
                                with _state_lock:
                                    event_index += 1
                                    idx = event_index
                                    events.append({
                                        "index": idx, "type": "event", "action": EventType.SCROLL.value,
                                        "selectors": [], "url": p.url, "value": str(y),
                                        "screenshots": {"before": f"screenshots/{idx:04d}_before.jpg"},
                                        "timestamp": time.time(), "tab_id": p_idx,
                                    })
                                before = ss_dir / f"{idx:04d}_before.jpg"
                                p.screenshot(path=str(before), full_page=False, type="jpeg", quality=85)
                                _log_event(idx, "scroll", f"y={y}")
                        except Exception:
                            pass
                except Exception:
                    pass

        except KeyboardInterrupt:
            _log("⏹ 收到终端信号，停止录制（也可在浏览器中按 Ctrl+Shift+E 停止）")

        finally:
            stopped = True
            _log(f"停止标志已设置 | 共{len(events)}个事件(含内部) | {len(context.pages)}个页面")
            # Ctrl+C 可能恰好打断某次 page.evaluate() 的等待响应，Playwright
            # 后台线程里对应的 asyncio Task 仍在等 CDP 响应；此处短暂等待让
            # 该 Task 自然完成/超时，避免 browser.close() 直接断连触发
            # "Task exception was never retrieved" 的 stderr 噪声
            time.sleep(0.5)
            try:
                if not profile:
                    browser.close()
                    _log("浏览器已关闭")
            except Exception as e:
                _log(f"浏览器关闭异常(可忽略): {e}")

    # ── 保存（过滤内部事件，按时间戳排序后重新编号）──
    clean = sorted(
        [e for e in events if e.get("type") != "_inject_ok"],
        key=lambda e: e.get("timestamp", 0)
    )
    for i, e in enumerate(clean):
        e["index"] = i + 1
    events_file = rec_dir / "events.json"
    type_counts = {}
    for e in clean:
        _t = e.get("action") or e.get("type", "?")
        type_counts[_t] = type_counts.get(_t, 0) + 1
    with open(events_file, "w", encoding="utf-8") as f:
        json.dump({
            "name": name, "start_url": url,
            "created_at": datetime.now().isoformat(),
            "platform": "web",
            "events": clean,
        }, f, ensure_ascii=False, indent=2)

    # 截图大小统计
    ss_total = sum(f.stat().st_size for f in ss_dir.glob("*.jpg") if f.is_file()) if ss_dir.exists() else 0

    # 保存录制日志
    log_data = {
        "name": name, "start_url": url, "total_events": len(clean),
        "event_details": [],
    }
    for e in clean:
        sel_types = [s.get("type", "?") for s in e.get("selectors", [])[:3]]
        log_data["event_details"].append({
            "index": e["index"], "type": e.get("type", "event"),
            "action": e.get("action", ""),
            "url": e.get("url", ""), "selectors": sel_types,
            "value": e.get("value", "")[:50],
        })
    with open(rec_dir / "record.log", "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    print(f"\n══════════ 录制报告 ══════════")
    print(f"  耗时: {_elapsed():.1f}s")
    print(f"  事件总数: {len(clean)}")
    for t, c in sorted(type_counts.items()):
        print(f"    {ic_map.get(t, '?'):2s} {t}: {c}")
    print(f"  截图: {len(list(ss_dir.glob('*.jpg')))} 张, {ss_total / 1024:.0f} KB")
    print(f"  产物: {rec_dir}")
    print(f"══════════════════════════════")
    print(f"\n💡 后续命令:")
    print(f"   ▶️  回放:    zk replay play {name}")
    print(f"   ✏️  编辑:    zk replay edit {name}")
    print(f"   📋 列出:    zk replay manage")

    return events_file, ss_dir
