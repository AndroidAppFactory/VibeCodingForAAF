"""web-replay 回放引擎

Playwright 驱动 Chromium，按录制的事件序列逐步骤回放。

用法：
    from web_player import replay_events
    replay_events("events.json", headless=False, timeout=30, speed=1.0)
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

_replay_core = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_replay_core) not in sys.path:
    sys.path.insert(0, str(_replay_core))

from core.schema import EventType, normalize_step  # noqa: E402

# ─── 日志 ──────────────────────────────────────────

def _now():
    return datetime.fromtimestamp(time.time()).strftime("%H:%M:%S")

def _log(msg=""):
    print(f"  [{_now()}] {msg}")

# ─── 内部页面识别 ──────────────────────────────────

def _is_internal_url(url: str) -> bool:
    """判断是否为浏览器内部 scheme（chrome://、devtools:// 等）。

    此类 URL 是自动化控制的 Chromium 环境噪声（如新标签页的 chrome://newtab/
    在自动化模式下可能退化为 chrome-error://chromewebdata/），无法通过
    page.goto() 真实导航到，也不代表用户真实操作意图，回放时应跳过而非报错/死等。
    """
    if not url:
        return False
    return url.startswith(("chrome://", "chrome-error://", "devtools://", "edge://"))

# ─── 选择器定位 ────────────────────────────────────

def _locate_element(page, selectors: list[dict], timeout_ms: int = 30000):
    """按 selector fallback 链尝试定位，返回 (locator, matched_selector_info)

    先用短超时探测元素是否存在于 DOM（attached），确认存在才用完整 timeout 等待可见——
    避免对不存在的 selector 逐个死等完整 timeout（曾观测到 3 个 selector 全部失效时
    卡顿近 90s：3 × 30s，用户误以为回放卡死）。
    """
    probe_ms = min(2000, timeout_ms)
    for i, sel in enumerate(selectors):
        stype = sel.get("type", "")
        value = sel.get("value", "")
        if not value:
            continue
        try:
            t_start = time.time()
            if stype in ("data-testid", "id", "class"):
                loc = page.locator(value)
            elif stype == "aria-label":
                loc = page.locator(value)
            elif stype == "text":
                loc = page.get_by_text(value, exact=False)
            elif stype == "xpath":
                loc = page.locator(f"xpath={value}")
            elif stype == "nth-child":
                loc = page.locator(value)
            else:
                loc = page.locator(value)

            try:
                loc.first.wait_for(state="attached", timeout=probe_ms)
            except Exception:
                continue  # DOM 中根本不存在该元素，快速跳到下一个 selector

            loc.wait_for(state="visible", timeout=timeout_ms)
            elapsed = (time.time() - t_start) * 1000
            return loc, f"{stype}={value[:40]} ({elapsed:.0f}ms)"
        except Exception:
            continue
    return None, ""


def _capture(page, step_dir: Path, index: int, phase: str):
    """统一截图入口，使用 core.screenshot 命名规范（event_XXX_0_before.jpg）"""
    from core.screenshot import screenshot_name
    screenshots_dir = step_dir / "screenshots"
    screenshots_dir.mkdir(parents=True, exist_ok=True)
    name = screenshot_name(index, phase)
    page.screenshot(path=str(screenshots_dir / name), full_page=False, type="jpeg", quality=85)


# ─── 步骤执行器 ────────────────────────────────────

def step_executor(step: dict, ctx) -> tuple[bool, dict]:
    page = ctx.browser_page
    timeout_ms = ctx.timeout * 1000
    raw_type = step.get("type", "event")
    # 统一 adb 模式：按 action 分派（旧格式 type 即动作，已在 load 边界归一化）。
    # 结构步骤(pause) 无 action 时回退到 type，保证 pause/wait 分支仍生效。
    # 复用 stype 变量名承载 action 值，使下方整条 EventType 分派链无需改动。
    stype = step.get("action", "") or (raw_type if raw_type != "event" else "")
    # 目录名/日志编号优先用全局序号（多 recording 编排时避免各录制内序号从1开始冲突），
    # 单文件回放（replay_events）未设置 _global_index 时回退到 _sub_index（原行为不变）
    idx = step.get("_global_index") or step.get("_sub_index", 0)
    selectors = step.get("selectors", [])
    value = step.get("value", "")

    if stype == "pause":
        _log(f"#{idx:02d} pause ⏸ | 等待手动继续")
        input(f"  [{_now()}] 按 Enter 继续...")
        return True, {"name": step.get("name", "断点")}

    if stype == "wait":
        wait_sec = float(value or 1)
        _log(f"#{idx:02d} wait ⏳ | {wait_sec}s")
        time.sleep(wait_sec)
        return True, {"name": f"等待 {wait_sec}s"}

    # 截图 before — 已移至调用侧按正确时机捕获，step_executor 不再负责截图逻辑
    t0 = time.time()
    sel_detail = ""
    err = ""

    try:
        if stype in (EventType.CLICK.value, ""):
            if selectors:
                loc, sel_detail = _locate_element(page, selectors, timeout_ms)
                if not loc:
                    sel_list = [f"{s['type']}={s.get('value','')[:20]}" for s in selectors[:3]]
                    err = f"选择器全部未命中 ({len(selectors)} chain): {sel_list}"
                    return False, {"error": err}

                def _do_click():
                    try:
                        loc.click()
                    except Exception:
                        _log(f"  ⚡ force click (被拦截)")
                        loc.click(force=True)

                # 下一步是 switch_tab：说明这次点击预期会打开新标签页，
                # 用 expect_page() 在点击的同一操作里主动等待并直接抓住新页面，
                # 避免"点击完再被动轮询 context.pages"的时序竞争（曾观测到通知延迟 30s+）
                if step.get("_next_action") == EventType.SWITCH_TAB.value:
                    try:
                        with ctx.browser_context.expect_page(timeout=timeout_ms) as new_page_info:
                            _do_click()
                        ctx.pending_new_page = new_page_info.value
                        sel_detail += f" | expect_page捕获新标签"
                    except Exception:
                        ctx.pending_new_page = None
                        _log(f"  ⚠️ expect_page 超时，点击未触发新标签页")
                else:
                    _do_click()
            else:
                page.click("body")
                sel_detail = "fallback:body"

        elif stype == EventType.INPUT.value:
            if selectors:
                loc, sel_detail = _locate_element(page, selectors, timeout_ms)
                if loc:
                    loc.fill(value)
                else:
                    page.keyboard.type(value)
                    sel_detail = "fallback:keyboard.type"
            else:
                page.keyboard.type(value)
                sel_detail = "keyboard.type(no_selector)"

        elif stype == EventType.NAVIGATE.value:
            if _is_internal_url(value):
                # 浏览器内部页面（历史录制产物中的环境噪声，如 chrome-error://chromewebdata/），
                # 无法真实导航，跳过该步骤视为成功
                sel_detail = f"跳过内部页面 url={value[:50]}"
            # 下一步是 switch_tab：导航可能自动打开新标签页（如 window.open），用 expect_page 捕获
            elif step.get("_next_action") == EventType.SWITCH_TAB.value:
                try:
                    with ctx.browser_context.expect_page(timeout=timeout_ms) as new_page_info:
                        page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
                    ctx.pending_new_page = new_page_info.value
                    sel_detail = f"url={value[:50]} | expect_page捕获新标签"
                except Exception:
                    ctx.pending_new_page = None
                    sel_detail = f"url={value[:50]} (未触发新标签)"
            else:
                try:
                    page.goto(value, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:
                    sel_detail = f"url={value[:50]} (导航超时)"
                else:
                    sel_detail = f"url={value[:50]}"

        elif stype == EventType.SCROLL.value:
            if selectors:
                loc, sel_detail = _locate_element(page, selectors, timeout_ms)
                if loc:
                    loc.scroll_into_view_if_needed()
            elif value:
                page.evaluate(f"window.scrollTo(0, {float(value)})")
                sel_detail = f"y={value}"

        elif stype == EventType.HOVER.value:
            loc, sel_detail = _locate_element(page, selectors, timeout_ms)
            if not loc:
                return False, {"error": "hover 目标未找到"}
            loc.hover()

        elif stype == EventType.SELECT.value:
            loc, sel_detail = _locate_element(page, selectors, timeout_ms)
            if not loc:
                return False, {"error": "select 元素未找到"}
            loc.select_option(value)

        elif stype == EventType.CHECK.value:
            loc, sel_detail = _locate_element(page, selectors, timeout_ms)
            if not loc:
                return False, {"error": "checkbox/radio 未找到"}
            checked = value.lower() in ("true", "1", "yes")
            if checked:
                loc.check()
            else:
                loc.uncheck()

        elif stype == EventType.KEYBOARD.value:
            page.keyboard.press(value)
            sel_detail = f"key={value}"

        elif stype == EventType.SWITCH_TAB.value:
            tabs = ctx.browser_context.pages
            tab_idx = int(value) if value else 0
            target_url = step.get("url", "")
            target_is_internal = _is_internal_url(target_url)
            target_p = None
            # 0. 优先消费上一步 click 用 expect_page() 主动抓到的新页面（无竞争）
            pending = getattr(ctx, "pending_new_page", None)
            ctx.pending_new_page = None
            if pending is not None:
                try:
                    pending.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass
                target_p = pending
                _log(f"  🗂 使用 expect_page 捕获的新页面 | url={target_p.url[:60]}")
            # 等待可能由前一步click打开的新页面加载完成（轮询窗口跟随 --timeout，而非固定6s）
            # 内部页面（如 chrome://newtab/）无法通过 URL 稳定匹配，跳过轮询直接走新建页面分支
            if target_url and not target_p and not target_is_internal:
                target_base = target_url.rstrip("/")
                deadline = time.time() + (timeout_ms / 1000.0)
                poll_count = 0
                while time.time() < deadline:
                    poll_count += 1
                    for t in ctx.browser_context.pages:
                        t_url_clean = t.url.rstrip("/")
                        if t_url_clean == target_base or t_url_clean.startswith(target_base):
                            target_p = t
                            _log(f"  🗂 复用已有页面(#{ctx.browser_context.pages.index(t)})")
                            break
                    if target_p:
                        break
                    time.sleep(0.3)
                if not target_p:
                    page_urls = [t.url for t in ctx.browser_context.pages]
                    waited = poll_count * 0.3
                    _log(f"  ⚠️ 未找到匹配页面(等待约{waited:.1f}s), 目标={target_url[:50]}, 现有={page_urls}")
            # 2. 按索引查找
            if not target_p and 0 <= tab_idx < len(tabs):
                target_p = tabs[tab_idx]
            # 3. 新建页面
            if not target_p and target_url:
                _log(f"  🗂 新建页面: {target_url[:60]}")
                target_p = ctx.browser_context.new_page()
                if not target_is_internal:
                    target_p.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
                    time.sleep(0.5)
            if target_p:
                target_p.bring_to_front()
                ctx.browser_page = target_p
                sel_detail = f"tab={tab_idx} url={target_p.url[:60]}"
            else:
                sel_detail = f"tab={tab_idx}未打开"

        elif stype == EventType.ALERT.value:
            sel_detail = "dialog(已录制时自动处理)"

        else:
            err = f"未知事件类型: {stype}"
            return False, {"error": err}

    except Exception as e:
        err = str(e)
        return False, {"error": err}

    elapsed_ms = (time.time() - t0) * 1000

    # 弹窗检测：click后若有可见弹窗，尝试按Escape关闭
    if stype in (EventType.CLICK.value, ""):
        try:
            modal = page.locator('[role="dialog"].show, .modal.show, .device-modal.show').first
            if modal.is_visible(timeout=1000):
                _log(f"  ⚠️ 检测到弹窗残留，尝试Escape关闭")
                page.keyboard.press("Escape")
                time.sleep(0.5)
        except Exception:
            pass
    # 截图 after — 已移至调用侧
    _log(f"#{idx:02d} {stype} ✅ | {elapsed_ms:.0f}ms | {sel_detail}")
    return True, {"name": step.get("name", "")}


# ─── 回放主流程 ────────────────────────────────────

def replay_events(
    events_file: Path | str,
    *,
    headless: bool = False,
    timeout: int = 30,
    speed: float = 1.0,
    repeat: int = 1,
    flow_name: str = "",
) -> list[dict]:
    from playwright.sync_api import sync_playwright

    events_file = Path(events_file)
    if not events_file.exists():
        raise FileNotFoundError(f"事件文件不存在: {events_file}")

    with open(events_file, encoding="utf-8") as f:
        data = json.load(f)

    # load 边界归一化：旧格式 {type:"click"} → {type:"event", action:"click"}，delay 秒→毫秒
    events = [normalize_step(e) for e in data.get("events", [])]
    if not events:
        raise ValueError("事件列表为空")

    flow_name = flow_name or data.get("name", "web-replay")

    _log("=== 回放引擎启动 ===")
    _log(f"文件={events_file.name} | 事件数={len(events)} | headless={headless} | timeout={timeout}s | speed={speed}x | repeat={repeat}")

    # 统计事件类型
    type_counts = {}
    for ev in events:
        t = ev.get("action") or ev.get("type", "?")
        type_counts[t] = type_counts.get(t, 0) + 1
    types_str = " ".join(f"{t}={c}" for t, c in sorted(type_counts.items()))
    _log(f"事件分布: {types_str}")

    replay_log: list[dict] = []
    results = []

    for run_idx in range(repeat):
        _log(f"\n{'='*40}")
        _log(f"第 {run_idx+1}/{repeat} 次回放开始")
        passed = 0
        failed = 0
        browser = None

        try:
            with sync_playwright() as p:
                # 禁用 Chromium 后台标签页/窗口限流：target=_blank 打开新标签后新标签抢占焦点，
                # 原标签所在进程会被系统判定为"后台"而限流，导致 CDP 新页面通知严重滞后（实测延迟可达30s+）
                browser = p.chromium.launch(headless=headless, args=[
                    "--start-maximized",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                    "--disable-background-timer-throttling",
                    "--disable-ipc-flooding-protection",
                ])
                _log(f"浏览器启动 | headless={headless} | {browser.version}")
                context = browser.new_context(no_viewport=True)
                page = context.new_page()

                start_url = data.get("start_url", "")
                if start_url:
                    _log(f"导航到起始URL | {start_url}")
                    page.goto(start_url, wait_until="domcontentloaded", timeout=timeout * 1000)
                    _log(f"起始页加载完成 | url={page.url} | title=\"{page.title()}\"")

                # 回放环境信息
                viewport = page.viewport_size or {}
                _log(f"🖥 视口: {viewport.get('width', '?')}x{viewport.get('height', '?')} | 起始URL={start_url[:50]}")
                _log(f"📋 总步骤: {len(events)} | 超时: {timeout}s | 速度: {speed}x\n")

                # 监听新页面（popup / target=_blank）
                def _on_replay_new_page(p):
                    _log(f"  🆕 检测到新页面: {p.url[:60]} (共{len(context.pages)}页)")
                context.on("page", _on_replay_new_page)

                # 回放产物目录（与 flow run 统一，每个事件生成 before/after 截图）
                ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
                run_dir = events_file.parent.parent / "play_runs" / f"{flow_name}_{ts_tag}"
                run_dir.mkdir(parents=True, exist_ok=True)
                ctx = type("WebReplayCtx", (), {
                    "browser_page": page,
                    "browser_context": context,
                    "browser": browser,
                    "timeout": timeout,
                    "speed": speed,
                    "run_dir": run_dir,
                    "pending_new_page": None,
                })()

                total_events = len(events)
                for i, ev in enumerate(events):
                    etype = ev.get("action") or ev.get("type", "?")

                    # 前延迟：优先用事件记录的 delay_before_ms（毫秒），否则从时间戳推算
                    dbm = ev.get("delay_before_ms")
                    delay_before = (dbm / 1000.0) if dbm else 5.0
                    if not dbm and i > 0 and "timestamp" in ev:
                        prev_ts = events[i-1].get("timestamp", 0)
                        cur_ts = ev.get("timestamp", 0)
                        if cur_ts and prev_ts:
                            delay_before = max(5.0, cur_ts - prev_ts)

                    # 后延迟：优先用事件记录的 delay_after_ms（毫秒），否则用相同值
                    dam = ev.get("delay_after_ms")
                    delay_after = (dam / 1000.0) if dam else delay_before

                    # 事件分隔线 + 进度
                    _log(f"─── 事件 #{i+1}/{total_events} {etype} ──────────────────────────────")
                    _log(f"  ⏱ 前={delay_before:.1f}s 后={delay_after:.1f}s")

                    step_dir_name = f"{i+1:04d}"
                    step_dir = run_dir / step_dir_name
                    # 1) 操作前截图
                    _capture(page, step_dir, i, "before")

                    # 2) 前延迟
                    if delay_before >= 3.0:
                        _log(f"  ⏳ 等待 {delay_before:.0f}s ...")
                    time.sleep(delay_before)

                    # 3) 执行操作
                    step = {
                        "type": ev.get("type", "event"),
                        "action": ev.get("action", ""),
                        "name": etype,
                        "selectors": ev.get("selectors", []),
                        "value": ev.get("value", ""),
                        "url": ev.get("url", ""),
                        "is_critical": ev.get("is_critical", False),
                        "_sub_index": i + 1,
                        "_flow_name": flow_name,
                        "_next_action": events[i + 1].get("action") if i + 1 < len(events) else None,
                    }
                    success, meta = step_executor(step, ctx)
                    if success:
                        passed += 1
                    else:
                        failed += 1
                        err_msg = meta.get("error", "未知错误")
                        _log(f"  ❌ 失败: {err_msg}")
                        _log(f"━━━ 选择器链: {json.dumps(ev.get('selectors', [])[:3], ensure_ascii=False)}")

                    # 记录回放结果
                    replay_log.append({
                        "index": i + 1, "type": etype,
                        "expected_url": ev.get("url", ""),
                        "expected_selectors": [s.get("type", "?") for s in ev.get("selectors", [])[:3]],
                        "success": success,
                        "error": meta.get("error", ""),
                        "pages": len(ctx.browser_context.pages),
                    })

                    # 4) 后延迟
                    time.sleep(delay_after)

                    # 5) 操作后截图
                    _capture(page, step_dir, i, "after")

                _log(f"\n--- 本轮完成 | 通过={passed} 失败={failed} 总计={len(events)}")

        except KeyboardInterrupt:
            _log(f"\n⏹ 回放已取消 | 通过={passed} 失败={failed}")

        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass

        results.append({"run": run_idx+1, "steps": len(events), "passed": passed, "failed": failed})

    # 汇总 + 对比录制日志
    print(f"\n══════════ 回放报告 ══════════")
    for r in results:
        ok = "✅" if r["failed"] == 0 else "❌"
        print(f"  {ok} 第{r['run']}次: {r['passed']}通过 / {r['failed']}失败 / {r['steps']}总计")

    # 读取录制日志对比
    record_log_path = events_file.parent / "record.log"
    if record_log_path.exists():
        try:
            record_data = json.loads(record_log_path.read_text(encoding="utf-8"))
            record_events = record_data.get("event_details", [])
            print(f"\n--- 录制 vs 回放 对比 ---")
            for i, rl in enumerate(replay_log):
                ri = i + 1
                rec = record_events[i] if i < len(record_events) else {}
                rs = "✅" if rl["success"] else "❌"
                r_sel = rl.get("expected_selectors", [])
                c_sel = rec.get("selectors", [])
                url_rec = rec.get("url", "")[:50]
                url_rep = rl.get("expected_url", "")[:50]
                url_match = "✓" if url_rec == url_rep else f"✗(录:{url_rec} 回:{url_rep})"
                print(f"  #{ri:02d} {rl['type']:12s} {rs} | 录制url={url_rec} | 选择器 录:{c_sel} 回:{r_sel}")
        except Exception:
            pass

    print(f"══════════════════════════════")
    print(f"\n📸 截图产物: {run_dir}")

    return results


# ─── Flow 事件级执行（多 recording 编排，共享同一浏览器） ──────

def _flow_step_desc(step: dict) -> str:
    """生成事件步骤的可读描述，用于报告展示"""
    t = step.get("action") or step.get("type", "?")
    if t in ("click", "event"):
        return "click"
    if t == "input":
        v = step.get("value", "")
        return f'input "{v[:30]}"' if v else "input"
    if t == "navigate":
        url = step.get("value", "")
        return f"navigate {url[:60]}" if len(url) > 60 else f"navigate {url}"
    if t == "scroll":
        return "scroll"
    if t == "select":
        return f"select {step.get('value', '')}"
    if t == "keyboard":
        return f"key {step.get('value', '')}"
    if t == "switch_tab":
        return "switch_tab"
    return t


def build_hooks(headless: bool = False, timeout: int = 30, speed: float = 1.0):
    """构造 web 平台的 (setup, teardown, executor) 三元组。

    供单端 run_flow_events 和 mixed 单进程编排共用。
    浏览器/上下文/page 存入 ctx.extra，run_dir 从 ctx.run_dir 取。
    """
    # ── setup：启动浏览器 ──
    def setup(ctx):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless, args=[
            "--start-maximized",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-ipc-flooding-protection",
        ])
        _log(f"浏览器启动 | headless={headless} | {browser.version}")
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        def _on_new_page(p):
            _log(f"  🆕 检测到新页面: {p.url[:60]}")
        context.on("page", _on_new_page)

        ctx.extra["pw"] = pw
        ctx.extra["browser"] = browser
        ctx.extra["context"] = context
        ctx.extra["page"] = page

    # ── teardown：关闭浏览器 ──
    def teardown(ctx):
        browser = ctx.extra.get("browser")
        pw = ctx.extra.get("pw")
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass

    # ── executor：delay + 截图 + 执行 + 截图 + delay_after ──
    def executor(ctx, step: dict) -> tuple[bool, dict]:
        from core.screenshot import screenshot_name

        page_ = ctx.extra["page"]
        context_ = ctx.extra["context"]
        browser_ = ctx.extra["browser"]
        all_steps = ctx.all_steps
        actual_num = step.get("_actual_num", 0)
        step_dir_name = f"{actual_num:04d}"
        i = actual_num - 1  # 0-based

        # delay_before
        dbm = step.get("delay_before_ms")
        delay_before = (dbm / 1000.0) if dbm else 5.0
        if not dbm and i > 0 and "timestamp" in step:
            prev = all_steps[i - 1] if i < len(all_steps) else {}
            if (prev.get("_step_type", "event") == "event"
                    and prev.get("_rec_name") == step.get("_rec_name")):
                prev_ts = prev.get("timestamp", 0)
                cur_ts = step.get("timestamp", 0)
                if cur_ts and prev_ts:
                    delay_before = max(5.0, cur_ts - prev_ts)
        dam = step.get("delay_after_ms")
        delay_after = (dam / 1000.0) if dam else delay_before

        step_dir = ctx.run_dir / step_dir_name
        before_name = screenshot_name(actual_num - 1, "before")
        after_name = screenshot_name(actual_num - 1, "after")

        # 操作详情
        action = step.get("action", "")
        value = step.get("value", "")
        detail = f"{action} {value}"[:80].strip() if value else action
        if detail:
            _log(f"▶ {detail}")

        _log(f"⏱ 前={delay_before:.1f}s 后={delay_after:.1f}s")

        # delay_before
        time.sleep(delay_before)

        # 截图 before
        _capture(page_, step_dir, actual_num - 1, "before")
        _log(f"📸 截屏(前): {before_name}")

        # 执行动作
        exec_step = dict(step)
        exec_step["_global_index"] = actual_num
        exec_step["_next_action"] = all_steps[i + 1].get("action") if i + 1 < len(all_steps) else None

        web_ctx = type("WebCtx", (), {
            "browser_page": page_,
            "browser_context": context_,
            "browser": browser_,
            "timeout": timeout,
            "speed": speed,
            "run_dir": ctx.run_dir,
            "pending_new_page": None,
        })()

        try:
            success, meta = step_executor(exec_step, web_ctx)
        except Exception as e:
            success, meta = False, {"error": str(e)}

        if not success:
            _log(f"❌ 失败: {meta.get('error', '未知错误')}")

        # delay_after（最后一步也要等待，确保页面渲染完再截图）
        last_step_min_wait = 3.0  # 最后一步最少等 3 秒
        actual_delay = delay_after if i < len(all_steps) - 1 else max(delay_after, last_step_min_wait)
        time.sleep(actual_delay)

        # 截图 after
        _capture(page_, step_dir, actual_num - 1, "after")
        _log(f"📸 截屏(后): {after_name}")

        # critical_screenshots (统一命名: step_dir/screenshots/event_XXX_X_phase.jpg)
        is_critical = step.get("is_critical", False)
        critical_screenshots = []
        if is_critical:
            for ph in ("before", "after"):
                path = f"{step_dir_name}/screenshots/{screenshot_name(actual_num - 1, ph)}"
                if (ctx.run_dir / path).exists():
                    critical_screenshots.append(path)

        step_name = _flow_step_desc(step)
        return success, {"name": step_name, "critical_screenshots": critical_screenshots}

    return setup, teardown, executor


def probe() -> bool:
    """探测 web 平台是否可用：playwright 可 import。

    实际浏览器启动失败由 setup 阶段的 skipped 兜底，此处不启动浏览器避免开销。
    """
    try:
        import playwright  # noqa: F401
        return True
    except ImportError:
        return False


def run_flow_events(
    steps: list[dict],
    run_dir: Path,
    *,
    headless: bool = False,
    timeout: int = 30,
    speed: float = 1.0,
    max_delay: float | None = None,
    notify_hook=None,
    report_hook=None,
    tips_hook=None,
    flow_data=None,
) -> dict:
    """执行已展开的 Flow 步骤列表（统一调用 core.runner.run_steps）。

    浏览器生命周期在调用 core.runner 之前/之后管理，page 通过 extra 传入 step_executor。
    """
    # 环境预检：自动安装缺失依赖
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        _log("📦 playwright 未安装，自动安装中...")
        import subprocess, sys, shutil
        if shutil.which("pipx") and "pipx" in sys.executable:
            subprocess.run(["pipx", "inject", "zixiekit", "playwright"], check=True)
        else:
            subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        _log("✅ playwright 安装完成")
    from core.runner import run_steps

    _log("=== Flow 事件级回放启动 ===")

    # ── setup/teardown/executor：复用 build_hooks 工厂（与 mixed 单进程共用）──
    _setup, _teardown, web_step_executor = build_hooks(headless=headless, timeout=timeout, speed=speed)

    # ── 调用 core.runner.run_steps（含 setup/teardown）──
    summary = run_steps(
        steps=steps,
        step_executor=web_step_executor,
        name=flow_data.get("name", "web_flow") if flow_data else "web_flow",
        flow_data=flow_data,
        speed=speed,
        max_delay=max_delay,
        device="web",
        run_dir=run_dir,
        setup_hook=_setup,
        teardown_hook=_teardown,
        notify_hook=notify_hook,
        report_hook=report_hook,
        tips_hook=tips_hook,
        extra={},
    )

    return summary
