"""replay-core Flow 执行引擎

以 adb-replay flow_runner 为蓝本的统一执行引擎。
各平台只需提供 step_executor 回调（执行单个 event），其余通用逻辑（步骤展开、
离散步骤选择、pause/shell_cmd 处理、rerun 合并、产物目录、进度打印、通知/报告 hook）
全部由 core 统一处理。
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from core.config import FLOW_RUNS_DIR
from core.flow import load_flow, resolve_flow_steps


# ─── 类型定义 ────────────────────────────────────────

# step_executor(ctx, step) -> (success: bool, meta: dict)
# 只负责执行单个 event 步骤，返回 (是否成功, 额外元数据如截图路径)
StepExecutor = Callable[["RunContext", dict], tuple[bool, dict]]

# 可选 hook：通知、报告生成、后续提示
NotifyHook = Callable[[str, str, str], None]  # (title, message, level)
ReportHook = Callable[[Path, dict], Optional[Path]]  # (run_dir, summary) -> report_path
TipsHook = Callable[[dict, Path], None]  # (flow, run_dir)

# setup_hook(ctx) -> None：步骤循环开始前调用（初始化平台资源：启动浏览器/连接设备等）
# teardown_hook(ctx) -> None：步骤循环结束后调用（释放资源：关闭浏览器等）；即使异常也保证调用
SetupHook = Callable[["RunContext"], None]
TeardownHook = Callable[["RunContext"], None]

# mixed flow 分段执行：按平台注册 (setup, teardown, executor)
# 当步骤的 _platform 变化时，teardown 上一平台 → setup 下一平台 → 用对应 executor 执行
PlatformHooks = dict[str, tuple[SetupHook, TeardownHook, StepExecutor]]


class RunContext:
    """单次 Flow 运行的上下文，供 step_executor 读取执行环境"""

    def __init__(self, **kwargs):
        self.flow: dict = kwargs.get("flow", {})
        self.flow_name: str = kwargs.get("flow_name", "")
        self.flow_id: str = kwargs.get("flow_id", "")
        self.run_dir: Path = kwargs.get("run_dir", Path("."))
        self.speed: float = kwargs.get("speed", 1.0)
        self.fail_fast: bool = kwargs.get("fail_fast", False)
        self.device: str = kwargs.get("device", "unknown")
        self.started_at: str = kwargs.get("started_at", "")
        self.total_steps: int = kwargs.get("total_steps", 0)
        self.all_steps: list[dict] = kwargs.get("all_steps", [])
        # 平台可自由附加属性
        self.extra: dict = kwargs.get("extra", {})


# ─── 执行引擎 ────────────────────────────────────────


def run_flow(
    flow_name: str,
    step_executor: StepExecutor,
    *,
    speed: float = 1.0,
    max_delay: Optional[float] = None,
    step_indices: list | None = None,
    fail_fast: bool = False,
    rerun: bool = False,
    device: str = "unknown",
    run_dir: Optional[Path] = None,
    notify_hook: Optional[NotifyHook] = None,
    report_hook: Optional[ReportHook] = None,
    tips_hook: Optional[TipsHook] = None,
    setup_hook: Optional["SetupHook"] = None,
    teardown_hook: Optional["TeardownHook"] = None,
    platform_hooks: Optional[PlatformHooks] = None,
    extra: Optional[dict] = None,
) -> dict:
    """执行指定 Flow（从全局仓库加载 + 递归展开 + 执行）"""
    flow = load_flow(flow_name)
    if not flow:
        print(f"❌ Flow「{flow_name}」不存在")
        return {"error": f"Flow 不存在: {flow_name}", "exit_code": 1}

    try:
        steps = resolve_flow_steps(flow)
    except ValueError as e:
        print(f"❌ {e}")
        return {"error": str(e), "exit_code": 1}

    if not steps:
        print("❌ Flow 中没有步骤")
        return {"error": "Flow 中没有步骤", "exit_code": 1}

    return run_steps(
        steps=steps,
        step_executor=step_executor,
        name=flow.get("name", flow_name),
        flow_data=flow,
        speed=speed,
        max_delay=max_delay,
        step_indices=step_indices,
        fail_fast=fail_fast,
        rerun=rerun,
        device=device,
        run_dir=run_dir,
        notify_hook=notify_hook,
        report_hook=report_hook,
        tips_hook=tips_hook,
        setup_hook=setup_hook,
        teardown_hook=teardown_hook,
        platform_hooks=platform_hooks,
        extra=extra,
    )


def run_steps(
    steps: list[dict],
    step_executor: StepExecutor,
    *,
    name: str = "",
    flow_data: Optional[dict] = None,
    speed: float = 1.0,
    max_delay: Optional[float] = None,
    step_indices: list | None = None,
    fail_fast: bool = False,
    rerun: bool = False,
    device: str = "unknown",
    run_dir: Optional[Path] = None,
    notify_hook: Optional[NotifyHook] = None,
    report_hook: Optional[ReportHook] = None,
    tips_hook: Optional[TipsHook] = None,
    setup_hook: Optional["SetupHook"] = None,
    teardown_hook: Optional["TeardownHook"] = None,
    platform_hooks: Optional[PlatformHooks] = None,
    extra: Optional[dict] = None,
) -> dict:
    """执行步骤列表（核心引擎，play 和 flow run 共享）

    - flow run：传入 resolve 后的步骤 + flow_data
    - play：传入 recording.events + flow_data=None
    - setup_hook：步骤循环开始前调用（初始化平台资源）
    - teardown_hook：步骤循环结束后调用（释放资源，保证调用）
    """
    flow = flow_data or {}

    # 补 _sub_total
    total = len(steps)
    for s in steps:
        s.setdefault("_sub_total", total)

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in (name or flow.get("name", "")))

    # ── 离散步骤选择 ──
    step_run_note = ""
    if step_indices:
        expanded = []
        for si in step_indices:
            if isinstance(si, tuple) and len(si) == 3 and si[0] == "range":
                start, end = si[1], si[2]
                if end is None:
                    end = len(steps)
                expanded.extend(range(start, end + 1))
            else:
                expanded.append(si)
        step_indices = sorted(set(expanded))
        for si in step_indices:
            if si < 1 or si > len(steps):
                print(f"❌ 步骤序号 {si} 超出范围（有效范围 1-{len(steps)}）")
                return {"error": f"步骤序号 {si} 超出范围", "exit_code": 1}
        steps_to_run = [steps[si - 1] for si in step_indices]
        total_steps = len(step_indices)
        step_labels = ",".join(f"#{si}" for si in step_indices)
        step_run_note = f"（仅步骤 {step_labels}）"
    else:
        steps_to_run = steps
        total_steps = len(steps)

    # ── 运行产物目录 ──
    if run_dir:
        run_dir = Path(run_dir)
    elif rerun and step_indices:
        # rerun 时复用最后一次运行目录
        runs = list_flow_runs(flow.get("name", ""))
        if not runs:
            print("❌ 没有历史运行记录，无法 --rerun")
            return {"error": "没有历史运行记录", "exit_code": 1}
        run_dir = Path(runs[0]["dir"])
        print(f"📂 复用上次运行目录: {run_dir.name}")
    else:
        FLOW_RUNS_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = FLOW_RUNS_DIR / f"{safe_name}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # ── 运行日志（print + 写 run.log）──
    _log_file = open(run_dir / "run.log", "a", encoding="utf-8")

    def _log(msg: str) -> None:
        """同时输出到 stdout 和 run.log（毫秒时间戳）。

        格式契约：时间戳统一为 `[HH:MM:SS.mmm]`。此格式被下游解析器依赖——
        procedures/mna/hg-replay-verify/scripts/timeline.py 的 STEP_RE 按此格式
        匹配 run.log 步骤标题行（`[ts] 📌 N/总数: 类型 [名称]`）。
        ⚠️ 改时间戳格式前必须先 grep 全仓 run.log 解析器并同步，否则时间轴解析会静默失效。
        """
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if msg.startswith("\n"):
            # 消息自带前置空行时，时间戳放到空行之后，避免独占一行
            line = f"\n[{ts}] {msg.lstrip(chr(10))}"
        else:
            line = f"[{ts}] {msg}"
        print(line)
        _log_file.write(line + "\n")
        _log_file.flush()

    started_at = datetime.now().isoformat(timespec="seconds")

    # ── 构建执行上下文 ──
    ctx = RunContext(
        flow=flow,
        flow_name=flow.get("name", ""),
        flow_id=flow.get("id", ""),
        run_dir=run_dir,
        speed=speed,
        fail_fast=fail_fast,
        device=device,
        started_at=started_at,
        total_steps=total_steps,
        all_steps=steps,
        extra=extra or {},
    )

    # ── setup_hook：初始化平台资源（在打印和通知之前，因为需要设备信息）──
    if setup_hook:
        try:
            setup_hook(ctx)
        except Exception as e:
            _log(f"❌ setup_hook 失败: {e}")
            _write_minimal_summary(run_dir, ctx, str(e))
            _log_file.close()
            return {"error": f"setup_hook 失败: {e}", "exit_code": 1}

    # ── 开始打印 ──
    _log(f"\n{'='*50}")
    _log(f"🚀 运行: {flow.get('name', '')} {step_run_note}")
    if flow.get("description"):
        _log(f"   {flow['description']}")
    _log(f"   设备: {ctx.device}")
    _log(f"   步骤数: {total_steps}")
    _log(f"   产物目录: {run_dir}")
    _log(f"{'='*50}\n")

    # ── 通知：开始 ──
    _skip_notify = os.environ.get("REPLAY_MIXED_MODE") == "1" or os.environ.get("REPLAY_NO_NOTIFY") == "1"
    if _skip_notify:
        _log("[skip notify] 开始通知已抑制（REPLAY_MIXED_MODE/REPLAY_NO_NOTIFY）")
    if notify_hook and not _skip_notify:
        try:
            notify_hook(
                f"🚀 【开始】{flow.get('name', '')}",
                f"{step_run_note}共 {total_steps} 步",
                "info",
            )
        except Exception:
            pass

    # ── 执行循环 ──
    step_results: list[dict] = []
    has_failure = False
    # mixed 平台切换状态
    _current_platform: str = ""
    _active_executor = step_executor
    # mixed 不可用平台集合：setup 失败或探测未通过的平台，其 step 全部 skipped
    _skipped_platforms: set[str] = set()

    def _gen_summary() -> dict:
        finished_at = datetime.now().isoformat(timespec="seconds")
        return {
            "flow": flow.get("name", ""),
            "flow_id": flow.get("id", ""),
            "device": ctx.device,
            "started_at": started_at,
            "finished_at": finished_at,
            "total_steps": total_steps,
            "completed_steps": sum(1 for r in step_results if r.get("status") == "success"),
            "failed_steps": sum(1 for r in step_results if r.get("status") == "failed"),
            "skipped_steps": sum(1 for r in step_results if r.get("status") == "skipped"),
            "skipped_platforms": sorted(_skipped_platforms),
            "steps": step_results,
        }

    try:
        for step_idx, step in enumerate(steps_to_run):
            actual_num = step_indices[step_idx] if step_indices else step_idx + 1
            stype = step.get("type", "event")
            fn = step.get("_flow_name", "")
            si = step.get("_sub_index", 0)
            st = step.get("_sub_total", 0)
            fl = f" [{fn} {si}/{st}]" if fn and si else (f" [{fn}]" if fn else "")

            # ── pause ──
            if stype == "pause":
                hint = step.get("hint", "请执行手动操作")
                _log(f"\n{'─'*40}")
                _log(f"📌 {actual_num}/{len(steps)}: ⏸ {hint}{fl}")
                _log(f"{'─'*40}")
                try:
                    input("按 Enter 继续...")
                except (EOFError, KeyboardInterrupt):
                    _log("\n⏹️  中断")
                    step_results.append({
                        "index": actual_num, "type": "pause", "status": "interrupted",
                        "flow_name": fn,
                    })
                    has_failure = True
                    break
                step_results.append({
                    "index": actual_num, "type": "pause", "status": "success",
                    "flow_name": fn,
                })
                continue

            # ── shell_cmd / adb_cmd ──
            if stype in ("shell_cmd", "adb_cmd"):
                cmd = step.get("command", "")
                _log(f"\n{'─'*40}")
                _log(f"📌 {actual_num}/{len(steps)}: 💻 {cmd}{fl}")
                _log(f"{'─'*40}")
                try:
                    result = subprocess.run(
                        cmd, shell=True, capture_output=True, text=True, timeout=30,
                    )
                    if result.returncode == 0:
                        _log(f"  ✅ 成功")
                        if result.stdout.strip():
                            _log(f"  {result.stdout.strip()}")
                        status = "success"
                    else:
                        _log(f"  ❌ 失败 (rc={result.returncode})")
                        status = "failed"
                        has_failure = True
                except subprocess.TimeoutExpired:
                    _log(f"  ❌ 超时")
                    status = "failed"
                    has_failure = True
                except OSError as e:
                    _log(f"  ❌ 异常: {e}")
                    status = "failed"
                    has_failure = True
                step_results.append({
                    "index": actual_num, "type": stype, "status": status,
                    "flow_name": fn,
                })
                if fail_fast and status == "failed":
                    break
                continue

            # ── event：交给平台 step_executor ──

            # mixed flow 平台切换：当 _platform 变化时切换 executor 和 setup/teardown
            step_platform = step.get("_platform", "")
            # 该平台此前已被标记不可用（探测未过 / setup 失败）→ 跳过本 step（不计失败）
            if step_platform and step_platform in _skipped_platforms:
                _log(f"  ⏭ 平台 {step_platform} 不可用，跳过：{actual_num}/{len(steps)}{fl}")
                step_results.append({
                    "name": step.get("action", "?"), "type": "event", "index": actual_num,
                    "status": "skipped", "flow_name": fn, "_platform": step_platform,
                })
                continue
            if platform_hooks and step_platform and step_platform != _current_platform:
                # teardown 上一个平台
                if _current_platform and _current_platform in platform_hooks:
                    _, td, _ = platform_hooks[_current_platform]
                    if td:
                        try:
                            _log(f"  🔄 切换平台：{_current_platform} → {step_platform}")
                            td(ctx)
                        except Exception as e:
                            _log(f"  ⚠️ teardown({_current_platform}) 失败: {e}")
                # setup 下一个平台
                if step_platform in platform_hooks:
                    su, _, ex = platform_hooks[step_platform]
                    _active_executor = ex
                    if su:
                        try:
                            su(ctx)
                        except Exception as e:
                            # 平台 setup 失败 → 标记该平台不可用，其后续 step 全部 skipped（不计失败）
                            _log(f"  ⏭ setup({step_platform}) 失败，跳过该平台所有步骤: {e}")
                            _skipped_platforms.add(step_platform)
                            _current_platform = step_platform
                            step_results.append({
                                "name": "setup", "type": "event", "index": actual_num,
                                "status": "skipped", "flow_name": fn, "_platform": step_platform,
                            })
                            continue
                else:
                    # 没有注册该平台的 hooks，回退到默认 executor
                    _active_executor = step_executor
                _current_platform = step_platform

            step_dir_name = f"{actual_num:04d}"
            step_dir = run_dir / step_dir_name
            step_dir.mkdir(parents=True, exist_ok=True)
            screenshot_dir = step_dir / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)

            is_critical = step.get("is_critical", False)
            critical_mark = " ⭐" if is_critical else ""
            action = step.get("action", "?")
            _log(f"\n{'─'*40}")
            _log(f"📌 {actual_num}/{len(steps)}: {action}{fl}{critical_mark}")
            _log(f"{'─'*40}")

            # 把执行必要上下文附到 step 元数据
            step_copy = dict(step)
            step_copy["_step_dir"] = str(step_dir)
            step_copy["_screenshot_dir"] = str(screenshot_dir)
            step_copy["_actual_num"] = actual_num

            # ── max_delay 上限截断：生效值 = min(原 delay, max_delay) ──
            if max_delay and max_delay > 0:
                _cap_ms = max_delay * 1000
                _clipped = [
                    _k for _k in ("delay_before_ms", "delay_after_ms")
                    if step_copy.get(_k) and step_copy[_k] > _cap_ms
                ]
                for _k in _clipped:
                    step_copy[_k] = _cap_ms
                if _clipped:
                    _log(f"  ⏳ 等待超上限，已截断到 {max_delay:.1f}s（{', '.join(_clipped)}）")

            step_status = "success"
            step_meta: dict = {}
            try:
                success, step_meta = _active_executor(ctx, step_copy)
                if not success:
                    step_status = "failed"
                    has_failure = True
            except KeyboardInterrupt:
                _log("\n  ⏹️  中断")
                step_status = "interrupted"
                has_failure = True
                step_results.append({
                    "name": action, "type": "event", "index": actual_num,
                    "status": "interrupted", "is_critical": is_critical,
                    "dir": step_dir_name, "flow_name": fn,
                    "flow_id": step.get("_flow_id", ""),
                    "sub_index": si, "sub_total": st,
                })
                break
            except Exception as e:
                _log(f"  ❌ 失败: {e}")
                step_status = "failed"
                has_failure = True

            step_results.append({
                "name": step_meta.get("name", action),
                "type": "event",
                "index": actual_num,
                "status": step_status,
                "event_count": 1,
                "is_critical": is_critical,
                "dir": step_dir_name,
                "critical_screenshots": step_meta.get("critical_screenshots", []),
                "flow_name": fn,
                "flow_id": step.get("_flow_id", ""),
                "sub_index": si,
                "sub_total": st,
                **{k: v for k, v in step_meta.items()
                   if k not in ("name", "critical_screenshots")},
            })

            if fail_fast and step_status == "failed":
                break

    finally:
        # ── mixed 平台最终 teardown ──
        if platform_hooks and _current_platform and _current_platform in platform_hooks:
            _, td, _ = platform_hooks[_current_platform]
            if td:
                try:
                    td(ctx)
                except Exception:
                    pass

        # ── 写 summary ──
        summary_file = run_dir / "summary.json"
        if rerun and summary_file.exists():
            old = json.loads(summary_file.read_text(encoding="utf-8"))
            old_steps = {s["index"]: s for s in old.get("steps", [])}
            for r in step_results:
                old_steps[r["index"]] = r
            old["steps"] = sorted(old_steps.values(), key=lambda x: x["index"])
            old["finished_at"] = datetime.now().isoformat(timespec="seconds")
            old["total_steps"] = len(steps)
            old["completed_steps"] = sum(1 for s in old["steps"] if s.get("status") == "success")
            old["failed_steps"] = sum(1 for s in old["steps"] if s.get("status") == "failed")
            summary = old
        else:
            summary = _gen_summary()

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # ── 报告 ──
        report_file = None
        if report_hook:
            try:
                report_file = report_hook(run_dir, summary)
            except Exception:
                pass

        # ── 结果打印 ──
        fail_count = summary.get("failed_steps", 0)
        interrupted_count = sum(1 for s in summary.get("steps", []) if s.get("status") == "interrupted")
        success_count = summary.get("completed_steps", 0)
        problem_count = fail_count + interrupted_count
        has_problem = problem_count > 0 or success_count < total_steps
        # ── 结果打印（标题仿 notify：状态 - 平台 · 执行时间 · 执行机器 · 运行设备）──
        if interrupted_count:
            status_label = "中断"
            icon = "⏹️"
            result_line = f"{success_count}/{total_steps} 已完成，{interrupted_count} 中断"
        elif fail_count:
            status_label = "失败"
            icon = "⚠️"
            result_line = f"{success_count}/{total_steps} 成功，{fail_count} 失败"
        else:
            status_label = "结束"
            icon = "✅"
            result_line = f"{success_count}/{total_steps} 成功"

        from core.report import _get_local_hostname, _format_started_at
        ts = _format_started_at({"started_at": started_at})
        host = _get_local_hostname()
        plat = device.upper() or "REPLAY"
        flow_name = flow.get("name", "") or name
        title = f"{icon}  【{status_label} - {plat}】{flow_name}    执行机器：{host}"
        if ctx.device and ctx.device != device:
            title += f"    运行设备：{ctx.device}"

        _flow_id = flow.get("id", "") or flow.get("name", "") or name
        _fid = _flow_id[:4] if len(_flow_id) > 4 else _flow_id

        # 任务耗时（开始 → 当前时间）
        duration_line = ""
        try:
            _start_dt = datetime.fromisoformat(started_at)
            _secs = int((datetime.now() - _start_dt).total_seconds())
            _m, _s = divmod(max(0, _secs), 60)
            _duration = f"{_m}分{_s}秒" if _m > 0 else f"{_s}秒"
            _end_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            duration_line = f"   任务耗时: {_duration}（{ts} - {_end_ts}）"
        except (ValueError, TypeError):
            pass

        _log(f"\n{'='*50}")
        _log(title)
        if _fid:
            _log(f"   执行命令：zk replay run {_fid}")
        _log(f"   任务情况: {result_line}")
        if duration_line:
            _log(duration_line)
        if report_file:
            _log(f"   报告: {report_file}")
        _log(f"   日志: {run_dir / 'run.log'}")
        snapshot_file = run_dir / "critical_after_snapshot.png"
        if snapshot_file.exists():
            _log(f"   快照: {snapshot_file} ({snapshot_file.stat().st_size / 1024 / 1024:.1f}MB)")
        _log(f"   目录: {run_dir}/")
        _log(f"{'='*50}")

        # ── 通知：结束 ──
        _skip_notify = os.environ.get("REPLAY_MIXED_MODE") == "1" or os.environ.get("REPLAY_NO_NOTIFY") == "1"
        if _skip_notify:
            _log("[skip notify] 结束通知已抑制（REPLAY_MIXED_MODE/REPLAY_NO_NOTIFY）")
        if notify_hook and not _skip_notify:
            try:
                if interrupted_count:
                    status_label = "中断"
                    icon = "⏹️"
                    level = "warning"
                elif fail_count:
                    status_label = "失败"
                    icon = "⚠️"
                    level = "warning"
                else:
                    status_label = "结束"
                    icon = "✅"
                    level = "info"
                notify_hook(
                    f"{icon} 【{status_label}】{flow.get('name', '')}",
                    f"{success_count}/{total_steps} 成功",
                    level,
                )
            except Exception:
                pass

        # ── 后续命令提示 ──
        if tips_hook:
            try:
                tips_hook(flow, run_dir)
            except Exception:
                pass

        # ── teardown_hook：释放平台资源 ──
        if teardown_hook:
            try:
                teardown_hook(ctx)
            except Exception as e:
                _log(f"⚠️ teardown_hook 异常: {e}")

    _log_file.close()
    summary["run_dir"] = str(run_dir)
    summary["exit_code"] = 0 if fail_count == 0 else 1
    return summary


# ─── 辅助函数 ────────────────────────────────────────


def _write_minimal_summary(run_dir: Path, ctx, error_msg: str) -> None:
    """setup_hook 失败时写最小化 summary.json，供 mixed flow 上层统计"""
    from datetime import datetime

    summary = {
        "status": "setup_failed",
        "error": error_msg,
        "device": getattr(ctx, "device", "unknown"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "total_steps": 0,
        "completed_steps": 0,
        "failed_steps": 0,
        "steps": [],
    }
    try:
        summary_file = run_dir / "summary.json"
        summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def list_flow_runs(flow_name: Optional[str] = None) -> list[dict]:
    """列出 Flow 运行记录（最新在前）"""
    if not FLOW_RUNS_DIR.exists():
        return []
    # 解析为 flow_id 做精确匹配
    resolved_id = ""
    if flow_name:
        f = load_flow(flow_name)
        if f:
            resolved_id = f.get("id", "")
    runs = []
    for d in sorted(FLOW_RUNS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        sf = d / "summary.json"
        if not sf.exists():
            continue
        try:
            s = json.loads(sf.read_text(encoding="utf-8"))
            if resolved_id and s.get("flow_id") != resolved_id:
                continue
            runs.append({
                "dir": str(d), "name": d.name, "flow": s.get("flow", "?"),
                "started_at": s.get("started_at", "?"),
                "total_steps": s.get("total_steps", 0),
                "failed_steps": s.get("failed_steps", 0),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return runs


def export_run(run_dir: Path, output_path: Path) -> Path:
    """导出 Flow 运行为 zip 压缩包"""
    import shutil
    output_path = Path(output_path)
    if output_path.suffix != ".zip":
        output_path = output_path.with_suffix(".zip")
    base_name = str(output_path).replace(".zip", "")
    root_dir = run_dir.parent
    base_dir = run_dir.name
    return Path(shutil.make_archive(base_name, "zip", root_dir, base_dir))
