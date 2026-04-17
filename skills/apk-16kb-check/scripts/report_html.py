#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
report_html.py
HTML 报告生成：generate_html_report
"""

import os
import re
import html
from typing import List, Dict, Tuple
from pathlib import Path

from models import CheckResult, ZipalignEntry
from checker_common import find_check_elf_script, find_tool
from report_terminal import classify_zipalign_bad_entries


def _format_ndk_version_html(ndk_text: str) -> str:
    """将 NDK 版本字符串格式化为两行 HTML 显示
    
    例如：
    - "Clang 19.0.0 (NDK r25+, r53056)" → "Clang 19.0.0<br>NDK r25+, r53056"
    - "Clang 18.0.1 (NDK r25, r522817)" → "Clang 18.0.1<br>NDK r25, r522817"
    - "NDK r25 (25.1.8937393)" → "NDK r25<br>25.1.8937393"
    - "Clang 19.0.0" → "Clang 19.0.0"（无括号则单行）
    - "未知" → "未知"
    """
    escaped = html.escape(ndk_text)
    
    # 匹配 "主信息 (括号内信息)" 格式
    match = re.match(r'^(.+?)\s*\((.+)\)$', escaped)
    if match:
        line1 = match.group(1).strip()
        line2 = match.group(2).strip()
        return f'{line1}<br><span style="color:#9ca3af;">{line2}</span>'
    
    return escaped


def generate_html_report(result: CheckResult, html_path: str) -> None:
    """生成 HTML 报告"""
    is_aar = bool(result.source_aar_paths)
    file_name = Path(result.file_path).name

    # 整体状态
    zipalign_ok = result.zipalign.status != "fail"
    elf_ok = result.elf_failed == 0
    has_compressed = result.has_compressed_so

    if not zipalign_ok or result.elf_failed > 0:
        overall_color = "#ef4444"
        overall_text = "❌ 存在未对齐问题"
    elif has_compressed:
        overall_color = "#f59e0b"
        overall_text = "⚠️ 有 .so 被压缩存储"
    else:
        overall_color = "#10b981"
        overall_text = "✅ 全部通过"

    # HTML 模板
    html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>APK 16KB 对齐检查报告</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: #f0f2f5; color: #1f2937; line-height: 1.6; padding: 20px;
  }}
  .container {{ max-width: 1400px; margin: 0 auto; }}
  .header {{
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white; border-radius: 16px; padding: 32px; margin-bottom: 24px;
    box-shadow: 0 4px 20px rgba(102, 126, 234, 0.3);
  }}
  .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
  .header .subtitle {{ opacity: 0.85; font-size: 14px; }}
  .meta-grid {{
    display: grid; grid-template-columns: repeat(3, 1fr);
    gap: 12px; margin-top: 20px;
  }}
  .meta-item {{
    background: rgba(255,255,255,0.15); border-radius: 8px; padding: 12px 16px;
    min-width: 0;
  }}
  .meta-item .label {{ font-size: 12px; opacity: 0.75; margin-bottom: 4px; }}
  .meta-item .value {{
    font-size: 15px; font-weight: 600;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }}
  .tab-nav {{
    display: flex; gap: 0; margin-bottom: 24px; background: white;
    border-radius: 12px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
  }}
  .tab-btn {{
    flex: 1; padding: 14px 20px; border: none; background: white;
    font-size: 14px; font-weight: 600; color: #6b7280; cursor: pointer;
    transition: all 0.2s; border-bottom: 3px solid transparent;
    white-space: nowrap;
  }}
  .tab-btn:hover {{ background: #f9fafb; color: #374151; }}
  .tab-btn.active {{ color: #667eea; border-bottom-color: #667eea; background: #f8f7ff; }}
  .tab-pane {{ display: none; }}
  .tab-pane.active {{ display: block; }}
  .mono {{ font-family: "SF Mono", "Fira Code", monospace; font-size: 13px; }}
  /* 压缩存储提示 */
  .compressed-note {{
    background: white; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #8b5cf6;
    overflow: hidden;
  }}
  .compressed-note-header {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 16px 20px; background: #faf5ff;
  }}
  .compressed-note-icon {{ font-size: 24px; flex-shrink: 0; }}
  .compressed-note-header strong {{ font-size: 14px; color: #5b21b6; }}
  .compressed-note-body {{
    padding: 12px 20px 16px; font-size: 13px; color: #374151; line-height: 1.7;
  }}
  .compressed-note-body p {{ margin: 0 0 8px; }}
  .compressed-note-body code {{
    background: #f3f4f6; padding: 1px 5px; border-radius: 3px;
    font-family: monospace; font-size: 12px;
  }}
  .tips {{
    background: white; border-radius: 12px; padding: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px;
  }}
  .tips h2 {{ font-size: 18px; margin-bottom: 12px; }}
  .tips ul {{ padding-left: 20px; }}
  .tips li {{ margin-bottom: 8px; color: #4b5563; font-size: 14px; }}
  .tips code {{
    background: #f3f4f6; padding: 2px 6px; border-radius: 4px;
    font-family: monospace; font-size: 13px; color: #e11d48;
  }}
  .footer {{ text-align: center; color: #9ca3af; font-size: 12px; padding: 16px; }}
  /* 重放命令面板 */
  .replay-panel {{
    background: #1e1e2e; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 2px 8px rgba(0,0,0,.1);
  }}
  .replay-panel > summary {{
    padding: 12px 20px; font-size: 13px; font-weight: 600; color: #a5b4fc;
    display: flex; align-items: center; gap: 6px; cursor: pointer;
    user-select: none; list-style: none;
  }}
  .replay-panel > summary::-webkit-details-marker {{ display: none; }}
  .replay-panel > summary::before {{
    content: '▶'; font-size: 10px; color: #94a3b8;
    transition: transform .2s; flex-shrink: 0;
  }}
  .replay-panel[open] > summary::before {{ transform: rotate(90deg); }}
  .replay-panel .replay-body {{ padding: 0 20px 16px; }}
  .replay-panel .replay-cmd {{
    display: flex; align-items: center; justify-content: space-between;
    background: #2d2d3f; border-radius: 8px; padding: 10px 14px; margin-bottom: 8px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px; color: #e2e8f0; line-height: 1.5;
  }}
  .replay-panel .replay-cmd:last-child {{ margin-bottom: 0; }}
  .replay-panel .replay-cmd .cmd-label {{
    color: #94a3b8; font-size: 11px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    white-space: nowrap; margin-right: 12px; min-width: 80px;
  }}
  .replay-panel .replay-cmd code {{ flex: 1; word-break: break-all; }}
  .replay-panel .replay-cmd .copy-btn {{
    background: none; border: 1px solid #4a4a6a; border-radius: 4px;
    color: #94a3b8; font-size: 11px; padding: 2px 8px; cursor: pointer;
    white-space: nowrap; margin-left: 10px; transition: all .2s;
  }}
  .replay-panel .replay-cmd .copy-btn:hover {{ border-color: #a5b4fc; color: #a5b4fc; }}
  /* 官方验证结果区块 */
  .official-verify {{
    background: white; border-radius: 12px; margin-bottom: 24px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden;
  }}
  .official-verify .verify-header {{
    padding: 16px 24px; border-bottom: 1px solid #e5e7eb;
    display: flex; justify-content: space-between; align-items: center;
  }}
  .official-verify .verify-header h2 {{ font-size: 18px; margin: 0; }}
  .official-verify .verify-status {{
    padding: 4px 12px; border-radius: 9999px; font-size: 13px; font-weight: 600;
  }}
  .official-verify .verify-status.pass {{ background: #d1fae5; color: #065f46; }}
  .official-verify .verify-status.fail {{ background: #fee2e2; color: #991b1b; }}
  .official-verify .verify-status.unavailable {{ background: #fef3c7; color: #92400e; }}
  .official-verify .verify-status.skipped {{ background: #e0e7ff; color: #3730a3; }}
  .official-verify .verify-stats {{
    display: flex; gap: 16px; padding: 16px 24px; border-bottom: 1px solid #e5e7eb;
  }}
  .official-verify .verify-stat-card {{
    flex: 1; text-align: center; padding: 12px; background: #f8fafc; border-radius: 8px;
  }}
  .official-verify .verify-stat-card.pass {{ background: #ecfdf5; }}
  .official-verify .verify-stat-card.fail {{ background: #fef2f2; }}
  .official-verify .verify-stat-num {{
    display: block; font-size: 28px; font-weight: 700; color: #1e293b;
  }}
  .official-verify .verify-stat-card.pass .verify-stat-num {{ color: #059669; }}
  .official-verify .verify-stat-card.fail .verify-stat-num {{ color: #dc2626; }}
  .official-verify .verify-stat-label {{ font-size: 12px; color: #64748b; }}
  .official-verify .verify-details-open {{
    border-top: 1px solid #e5e7eb;
  }}
  .official-verify .verify-details-open summary.verify-details-title {{
    list-style: none; cursor: pointer; user-select: none;
  }}
  .official-verify .verify-details-open summary.verify-details-title::-webkit-details-marker {{
    display: none;
  }}
  .official-verify .verify-details-open summary.verify-details-title::before {{
    content: '▶'; display: inline-block; margin-right: 8px;
    font-size: 11px; color: #9ca3af; transition: transform 0.2s;
  }}
  .official-verify .verify-details-open[open] summary.verify-details-title::before {{
    transform: rotate(90deg);
  }}
  .official-verify .verify-details-title {{
    padding: 12px 24px; font-size: 14px; color: #6366f1;
    font-weight: 600; background: #f8fafc; border-bottom: 1px solid #e5e7eb;
  }}
  .official-verify .verify-output {{
    background: #1e1e2e; color: #e2e8f0; padding: 16px 20px;
    font-family: "SF Mono", "Fira Code", Consolas, monospace;
    font-size: 12px; line-height: 1.6; max-height: 400px; overflow: auto;
    white-space: pre-wrap; word-break: break-all;
  }}
  .official-verify .verify-output .line-pass {{ color: #10b981; }}
  .official-verify .verify-output .line-fail {{ color: #ef4444; }}
  .official-verify .verify-output .line-info {{ color: #94a3b8; }}
  /* 表格样式 */
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    background: #f9fafb; padding: 12px 16px; text-align: left;
    font-size: 12px; text-transform: uppercase; color: #6b7280;
    font-weight: 600; letter-spacing: 0.05em; border-bottom: 1px solid #e5e7eb;
    white-space: nowrap;
  }}
  tbody td {{
    padding: 10px 16px; border-bottom: 1px solid #f3f4f6; font-size: 14px;
  }}
  tbody tr:hover {{ background: #f9fafb; }}
  .badge {{
    display: inline-block; padding: 2px 10px; border-radius: 9999px;
    font-size: 12px; font-weight: 600;
  }}
  .badge-pass {{ background: #d1fae5; color: #065f46; }}
  .badge-fail {{ background: #fee2e2; color: #991b1b; }}
  .badge-warn {{ background: #fef3c7; color: #92400e; }}
  .badge-exempt {{ background: #dbeafe; color: #1e40af; }}
  .arch-tag {{
    display: inline-block; padding: 2px 8px; border-radius: 4px;
    font-size: 11px; font-weight: 500; font-family: monospace;
  }}
  .arch-arm64 {{ background: #dbeafe; color: #1e40af; }}
  .arch-armv7 {{ background: #fce7f3; color: #9d174d; }}
  .arch-x86 {{ background: #e0e7ff; color: #3730a3; }}
  .arch-other {{ background: #f3f4f6; color: #374151; }}
  @media (max-width: 768px) {{
    body {{ padding: 12px; }}
    .header {{ padding: 20px; }}
    .meta-grid {{ grid-template-columns: 1fr; }}
    .tab-nav {{ flex-direction: column; }}
    .tab-btn {{ font-size: 13px; padding: 10px 16px; }}
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📦 APK 16KB 对齐检查报告</h1>
    <div class="subtitle">官方 zipalign 验证 + 官方 check_elf_alignment.sh ELF LOAD 段对齐检查</div>
    <div class="meta-grid">
      <div class="meta-item">
        <div class="label">{'AAR 文件' if is_aar else 'APK 文件'}</div>
        <div class="value" title="{html.escape(', '.join(result.source_aar_paths)) if is_aar else html.escape(result.file_path)}">{html.escape(', '.join(Path(p).name for p in result.source_aar_paths)) if is_aar else html.escape(file_name)}</div>
      </div>
      <div class="meta-item">
        <div class="label">检查时间</div>
        <div class="value">{result.check_time}</div>
      </div>
      <div class="meta-item">
        <div class="label">整体状态</div>
        <div class="value" style="color: {overall_color}">{overall_text}</div>
      </div>'''

    # AAR 模式：额外显示构建 APK 路径
    if is_aar:
        html_content += f'''
      <div class="meta-item" style="grid-column: 1 / -1;">
        <div class="label">构建 APK</div>
        <div class="value mono" style="font-size: 13px; word-break: break-all;">{html.escape(result.file_path)}</div>
      </div>'''

    html_content += '''
    </div>
  </div>

'''

    # 重放命令面板
    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), 'check_alignment.py'))
    elf_script_path = find_check_elf_script()
    zipalign_cmd = find_tool('zipalign')
    zipalign_replay = html.escape(zipalign_cmd) if zipalign_cmd else "$ANDROID_HOME/build-tools/&lt;VERSION&gt;/zipalign"
    elf_script_replay = html.escape(elf_script_path) if elf_script_path else "check_elf_alignment.sh"

    if is_aar:
        aar_args = ' '.join(f'"{html.escape(p)}"' for p in result.source_aar_paths)
        python_replay_cmd = f'python3 {html.escape(script_path)} {aar_args}'
    else:
        python_replay_cmd = f'python3 {html.escape(script_path)} "{html.escape(result.file_path)}"'

    html_content += f'''
  <details class="replay-panel">
    <summary>🔄 重放命令</summary>
    <div class="replay-body">
      <div class="replay-cmd">
        <span class="cmd-label">{'AAR 检查' if is_aar else 'Python 检查'}</span>
        <code>{python_replay_cmd}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
      <div class="replay-cmd">
        <span class="cmd-label">官方 zipalign</span>
        <code>{zipalign_replay} -c -P 16 -v 4 {html.escape(result.file_path)}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
      <div class="replay-cmd">
        <span class="cmd-label">官方 ELF 检查</span>
        <code>bash {elf_script_replay} {html.escape(result.file_path)}</code>
        <button class="copy-btn" onclick="copyCmd(this)">复制</button>
      </div>
    </div>
  </details>

  <div class="tab-nav">
    <button class="tab-btn{'' if is_aar else ' active'}" onclick="switchTab('tab-zipalign')">🔍 zipalign 验证</button>
    <button class="tab-btn{' active' if is_aar else ''}" onclick="switchTab('tab-elf')">🔬 ELF 对齐检查</button>
<button class="tab-btn" onclick="switchTab('tab-tips')">💡 修复方案&参考资料</button>
  </div>

  <div id="tab-zipalign" class="tab-pane{'' if is_aar else ' active'}">
'''

    # 官方 zipalign 验证结果
    verify_status_class = result.zipalign.status
    html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔍 官方 zipalign 验证结果</h2>
      <span class="verify-status {verify_status_class}">{html.escape(result.zipalign.summary)}</span>
    </div>
'''

    if result.zipalign.available:
        html_content += f'''    <div class="verify-stats">
      <div class="verify-stat-card">
        <span class="verify-stat-num">{result.zipalign.total_count}</span>
        <span class="verify-stat-label">检查项总计</span>
      </div>
      <div class="verify-stat-card pass">
        <span class="verify-stat-num">{result.zipalign.ok_count}</span>
        <span class="verify-stat-label">通过</span>
      </div>
      <div class="verify-stat-card fail">
        <span class="verify-stat-num">{result.zipalign.fail_count}</span>
        <span class="verify-stat-label">未通过 (BAD)</span>
      </div>
      <div class="verify-stat-card" style="background: #fffbeb;">
        <span class="verify-stat-num" style="color: #d97706;">{result.zipalign.compressed_count}</span>
        <span class="verify-stat-label">SO 压缩存储</span>
      </div>
    </div>
'''

        # 问题条目表格
        issue_entries = [
            e for e in result.zipalign.entries
            if e.status == "fail" or (e.status == "compressed" and e.file_path.endswith('.so'))
        ]

        fixable_set, unfixable_set, _ = classify_zipalign_bad_entries(result)
        fixable_paths = {e.file_path for e in fixable_set}
        unfixable_paths = {e.file_path for e in unfixable_set}

        if issue_entries:
            issue_entries_sorted = sorted(issue_entries, key=lambda x: (0 if x.status == "fail" else 1, Path(x.file_path).name, x.file_path))
            details_open_attr = ' open' if verify_status_class != 'pass' else ''
            html_content += f'''    <details class="verify-details-open"{details_open_attr}>
      <summary class="verify-details-title">⚠️ 未通过 / SO 压缩存储条目</summary>
      <div style="padding: 0;">
        <table>
          <thead>
            <tr>
              <th style="width: 50px;">#</th>
              <th>文件路径</th>
              <th>偏移量</th>
              <th>状态</th>
              <th>修复方式</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
'''
            for idx, entry in enumerate(issue_entries_sorted, 1):
                if entry.status == "fail":
                    badge_class = "badge-fail"
                    badge_text = "❌ BAD"
                    note = html.escape(entry.detail) if entry.detail else "未对齐"
                    if entry.file_path in unfixable_paths:
                        fix_badge = '<span class="badge badge-fail" style="font-size:11px;">需重新编译</span>'
                        so_name = Path(entry.file_path).name
                        if so_name in result.so_source_map:
                            info = result.so_source_map[so_name]
                            note += f' ← {html.escape(info.get("module", ""))}'
                    elif entry.file_path in fixable_paths:
                        fix_badge = '<span class="badge badge-pass" style="font-size:11px;">zipalign 可修复</span>'
                    else:
                        fix_badge = '<span class="badge" style="background:#f3f4f6;color:#374151;font-size:11px;">zipalign 可修复</span>'
                else:
                    badge_class = "badge-warn"
                    badge_text = "⚠️ compressed"
                    note = "压缩存储，无法验证对齐"
                    fix_badge = '<span class="badge badge-warn" style="font-size:11px;">需改 stored</span>'

                html_content += f'''            <tr>
              <td>{idx}</td>
              <td class="mono" style="word-break: break-all;">{html.escape(entry.file_path)}</td>
              <td class="mono">{html.escape(entry.offset)}</td>
              <td><span class="badge {badge_class}">{badge_text}</span></td>
              <td>{fix_badge}</td>
              <td style="font-size: 13px; color: #6b7280;">{note}</td>
            </tr>
'''
            html_content += '''          </tbody>
        </table>
      </div>
'''
        # 如果有 not_configured 类型的 SO，在表格下方加备注
        has_not_configured = any(r.source_type == 'not_configured' for r in result.elf_results)
        if has_not_configured:
            html_content += '      <div style="padding: 8px 16px; margin-top: 4px; font-size: 12px; color: #9ca3af;">⚠️ 未找到有效的 Gradle User Home，.so 来源将显示为未设置。可在项目 gradle.properties 中配置 gradle.user.home 或设置 GRADLE_USER_HOME 环境变量。</div>\n'
        html_content += '''    </details>
'''

        # 自动修复对比结果
        fix = result.fix_result
        if fix and fix.attempted:
            if fix.verify_result:
                vr = fix.verify_result
                orig_fail = result.zipalign.fail_count
                fixed_fail = vr.zipalign.fail_count
                fixed_count = orig_fail - fixed_fail

                if fix.success:
                    fix_status_class = "pass"
                    fix_status_text = "✅ 修复成功"
                elif fixed_fail == 0:
                    fix_status_class = "pass"
                    fix_status_text = "✅ zipalign 偏移已全部修复"
                elif fixed_count > 0:
                    fix_status_class = "unavailable"
                    fix_status_text = "⚠️ 部分修复"
                else:
                    fix_status_class = "fail"
                    fix_status_text = "❌ 修复失败"

                html_content += f'''
    <div style="border-top: 1px solid #e5e7eb; margin-top: 16px;">
      <div style="padding: 16px 24px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e5e7eb;">
        <h3 style="margin: 0; font-size: 16px;">🔧 zipalign -P 16 自动修复结果</h3>
        <span class="verify-status {fix_status_class}">{fix_status_text}</span>
      </div>
      <div class="verify-stats">
        <div class="verify-stat-card">
          <span class="verify-stat-num" style="font-size: 14px; color: #64748b;">修复前</span>
          <span class="verify-stat-label" style="font-size: 13px; margin-top: 4px;">
            通过 <strong>{result.zipalign.ok_count}</strong>&nbsp;&nbsp;失败 <strong style="color:#dc2626;">{orig_fail}</strong>
          </span>
        </div>
        <div class="verify-stat-card" style="background: #f0fdf4;">
          <span class="verify-stat-num" style="font-size: 14px; color: #16a34a;">修复后</span>
          <span class="verify-stat-label" style="font-size: 13px; margin-top: 4px;">
            通过 <strong>{vr.zipalign.ok_count}</strong>&nbsp;&nbsp;失败 <strong style="color:{"#dc2626" if fixed_fail > 0 else "#16a34a"};">{fixed_fail}</strong>
          </span>
        </div>
        <div class="verify-stat-card" style="background: #ecfdf5;">
          <span class="verify-stat-num" style="color: #059669;">{fixed_count}</span>
          <span class="verify-stat-label">修复数量</span>
        </div>
      </div>
'''
                notes = []
                if fixed_fail == 0 and vr.elf_failed > 0:
                    notes.append(f'zipalign 偏移已全部修复，但仍有 <strong>{vr.elf_failed}</strong> 个 SO 的 ELF LOAD 段未对齐（需重新编译，见 ELF 检查 Tab）')
                if fix.aligned_path:
                    notes.append(f'修复后文件：<code style="font-size:12px;">{html.escape(Path(fix.aligned_path).name)}</code>（未签名，仅用于验证）')

                if notes:
                    html_content += '      <div style="padding: 12px 24px; background: #fffbeb; border-top: 1px solid #fef3c7; font-size: 13px; color: #92400e;">\n'
                    for note_text in notes:
                        html_content += f'        <p style="margin: 4px 0;">⚠️ {note_text}</p>\n'
                    html_content += '      </div>\n'

                html_content += '    </div>\n'
            elif fix.error:
                html_content += f'''
    <div style="border-top: 1px solid #e5e7eb; margin-top: 16px; padding: 16px 24px;">
      <h3 style="margin: 0 0 8px; font-size: 16px;">🔧 zipalign -P 16 自动修复</h3>
      <span class="badge badge-fail">❌ 修复失败</span>
      <p style="margin: 8px 0 0; font-size: 13px; color: #991b1b;">{html.escape(fix.error)}</p>
    </div>
'''

        if result.zipalign.output:
            escaped_output = html.escape(result.zipalign.output)
            escaped_output = escaped_output.replace(
                '(OK)', '<span class="line-pass">(OK)</span>'
            ).replace(
                '(OK - compressed)', '<span class="line-pass">(OK - compressed)</span>'
            )
            escaped_output = re.sub(
                r'\(BAD - (\d+)\)',
                r'<span class="line-fail">(BAD - \1)</span>',
                escaped_output
            )
            escaped_output = escaped_output.replace(
                'Verification successful',
                '<span class="line-pass">Verification successful</span>'
            ).replace(
                'Verification FAILED',
                '<span class="line-fail">Verification FAILED</span>'
            )

            html_content += f'''    <details class="verify-details-open">
      <summary class="verify-details-title">📝 详细输出</summary>
      <div class="verify-output">{escaped_output}</div>
    </details>
'''
    else:
        html_content += '''    <div class="verify-output"><span class="line-info">zipalign 工具不可用。请确保：
1. ANDROID_HOME 环境变量已设置
2. Build-Tools 35.0.0+ 已安装
3. $ANDROID_HOME/build-tools/XX.0.0/zipalign 可执行</span></div>
'''

    html_content += '  </div>\n'

    # 压缩存储提示
    if result.has_compressed_so:
        compressed_list_html = ", ".join(
            f'<code>{html.escape(name)}</code>' for name in sorted(result.compressed_so_names)
        )
        html_content += f'''
  <div class="compressed-note">
    <div class="compressed-note-header">
      <span class="compressed-note-icon">📦</span>
      <div>
        <strong>关于官方 zipalign 验证通过但仍可能存在问题</strong>
        <p style="margin: 4px 0 0; font-size: 13px; color: #6b7280;">检测到 {len(result.compressed_so_names)} 个 .so 文件以压缩（deflated）方式存储</p>
      </div>
    </div>
    <div class="compressed-note-body">
      <p>官方 <code>zipalign -c</code> 对压缩存储的文件直接判定为 <code>(OK - compressed)</code>，<strong>但这并不意味着 16KB 对齐通过</strong>。</p>
      <p>Android 要求 .so 必须以 <strong>stored（未压缩）</strong> 方式存储，系统才能直接从 APK 中 mmap 加载，这是 16KB 页面对齐的<strong>前提条件</strong>。</p>
      <p style="margin-bottom: 4px;"><strong>受影响的 SO 文件：</strong>{compressed_list_html}</p>
      <div style="margin-top: 8px;">
        <div style="color: #6366f1; font-size: 13px; font-weight: 600; margin-bottom: 8px;">🔧 修复方法</div>
        <div style="background: #f5f3ff; border: 1px solid #ddd6fe; border-radius: 6px; padding: 12px;">
          <code style="font-size: 13px; color: #5b21b6;">// build.gradle (Module)<br>
android {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;packagingOptions {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;jniLibs {{<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;useLegacyPackaging = false<br>
&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;}}<br>
&nbsp;&nbsp;&nbsp;&nbsp;}}<br>
}}</code>
        </div>
        <p style="margin: 8px 0 0; color: #6b7280; font-size: 12px;">
          📌 AGP 8.5.1+ 已默认设置此选项，低版本需手动配置。
        </p>
      </div>
    </div>
  </div>
'''

    # ---- tab-zipalign 内的修复建议 ----
    fix = result.fix_result
    fix_zipalign_all_pass = (
        fix and fix.attempted and fix.verify_result
        and fix.verify_result.zipalign.fail_count == 0
    )
    has_zipalign_tips = not zipalign_ok or result.has_compressed_so
    if has_zipalign_tips:
        html_content += '  <div class="tips" style="margin-top: 20px;">\n'
        html_content += '    <h2>💡 解决方案</h2>\n'

        if not zipalign_ok:
            if fix_zipalign_all_pass:
                orig_fail = result.zipalign.fail_count
                html_content += f'''
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 12px;">
        <span style="font-size: 20px;">✅</span>
        <strong style="font-size: 15px; color: #15803d;">zipalign 对齐问题可通过构建配置修复（已验证）</strong>
      </div>
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">
        原始 APK 有 <strong>{orig_fail}</strong> 个文件 ZIP 偏移未按 16KB 对齐。
        我们使用 <code>zipalign -P 16</code> 重新对齐后，<strong>zipalign 验证全部通过</strong>。
        这说明 SO 文件自身的 ELF 段对齐没有问题，只需在构建流程中启用 16KB 对齐即可。
      </p>
    </div>

    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #1e293b;">🔧 在构建流程中启用 16KB 对齐</h3>
    <p style="margin: 0 0 12px; font-size: 13px; color: #6b7280;">选择以下任一方案，重新构建后 zipalign 即可通过：</p>

    <div style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px; font-size: 14px; color: #1e293b;">方案一：升级 AGP ≥ 8.5.1（推荐）</h4>
      <p style="margin: 0 0 8px; font-size: 13px; color: #6b7280;">AGP 8.5.1+ 构建时自动执行 <code>zipalign -P 16</code>，无需额外配置。</p>
      <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle (project) 或 libs.versions.toml
classpath 'com.android.tools.build:gradle:8.5.1'  // 或更高</code></pre>
    </div>

    <div style="margin-bottom: 16px;">
      <h4 style="margin: 0 0 8px; font-size: 14px; color: #1e293b;">方案二：手动 zipalign（低版本 AGP 或自定义构建）</h4>
      <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># ⚠️ 注意顺序：先 zipalign → 再 apksigner 签名
# 需要 Build-Tools 35.0.0+
zipalign -P 16 -f 4 app-unsigned.apk app-aligned.apk
apksigner sign --ks keystore.jks app-aligned.apk

# 验证
zipalign -c -P 16 -v 4 app-aligned.apk</code></pre>
    </div>

    <div style="background: #eff6ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 12px 16px; font-size: 13px; color: #1e40af;">
      <strong>📌 注意：</strong>同时确保 <code>useLegacyPackaging = false</code>（AGP 8.5.1+ 默认开启），让 .so 以 stored 方式存储：
      <pre style="background:rgba(255,255,255,0.6); padding:8px 12px; border-radius:6px; margin:8px 0 0; font-size:13px;"><code>// app/build.gradle
android {{
    packaging {{
        jniLibs {{
            useLegacyPackaging = false
        }}
    }}
}}</code></pre>
    </div>
'''
            else:
                html_content += '''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #1e293b;">📦 APK 未通过 zipalign 16KB 对齐验证</h3>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li><strong>确保 AGP &ge; 8.5.1</strong>：Android Gradle Plugin 8.5.1+ 构建时自动执行 16KB zipalign，低版本需手动处理
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle (project)
classpath 'com.android.tools.build:gradle:8.5.1'  // 或更高</code></pre>
      </li>
      <li><strong>设置 <code>useLegacyPackaging = false</code></strong>：让 .so 以未压缩方式存储在 APK 中
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// app/build.gradle
android {
    packaging {
        jniLibs {
            useLegacyPackaging = false
        }
    }
}</code></pre>
      </li>
      <li><strong>手动 zipalign（低版本 AGP 或自定义构建流程）</strong>：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># ⚠️ 注意顺序：先 zipalign → 再 apksigner 签名
# Build-Tools 35.0.0+
zipalign -P 16 -f 4 input.apk output_aligned.apk
apksigner sign --ks keystore.jks output_aligned.apk

# 验证
zipalign -c -P 16 -v 4 output_aligned.apk</code></pre>
      </li>
    </ol>
'''

        if result.has_compressed_so:
            compressed_names_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in result.compressed_so_names[:5])
            if len(result.compressed_so_names) > 5:
                compressed_names_html += f' 等 {len(result.compressed_so_names)} 个'
            html_content += f'''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #d97706;">⚠️ SO 文件被压缩存储</h3>
    <p style="margin: 4px 0 8px; color: #92400e; font-size: 13px;">
      {compressed_names_html} — 压缩存储的 .so 无法利用 16KB 页面对齐优势。
    </p>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li>在 <code>build.gradle</code> 中设置 <code>useLegacyPackaging = false</code>（见上方）</li>
      <li>确保 <code>AndroidManifest.xml</code> 中 <strong>没有</strong> <code>android:extractNativeLibs="true"</code>（AGP 默认为 false）</li>
    </ol>
'''

        html_content += '  </div>\n'

    # 关闭 tab-zipalign
    html_content += '  </div>\n\n'

    # ==================== Tab 2: ELF LOAD 段对齐检查 ====================
    elf_tab_active = ' active' if is_aar else ''
    html_content += f'  <div id="tab-elf" class="tab-pane{elf_tab_active}">\n'

    if result.elf_results:
        elf_failed_list = [r for r in result.elf_results if r.status == "fail"]
        elf_passed_list = [r for r in result.elf_results if r.status == "pass"]
        elf_warn_list = [r for r in result.elf_results if r.status == "warn"]

        if elf_failed_list:
            elf_status_class = "fail"
            elf_status_text = f"❌ {len(elf_failed_list)} 个 SO 未对齐"
        elif elf_warn_list:
            elf_status_class = "unavailable"
            elf_status_text = f"⚠️ {len(elf_warn_list)} 个无法检查"
        else:
            elf_status_class = "pass"
            elf_status_text = "✅ 全部通过"

        html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查（官方 check_elf_alignment.sh）</h2>
      <span class="verify-status {elf_status_class}">{elf_status_text}</span>
    </div>
    <div class="verify-stats">
      <div class="verify-stat-card">
        <span class="verify-stat-num">{result.elf_total}</span>
        <span class="verify-stat-label">SO 文件总计 (仅 64 位架构)</span>
      </div>
      <div class="verify-stat-card pass">
        <span class="verify-stat-num">{result.elf_passed}</span>
        <span class="verify-stat-label">ALIGNED (≥ 16KB)</span>
      </div>
      <div class="verify-stat-card fail">
        <span class="verify-stat-num">{result.elf_failed}</span>
        <span class="verify-stat-label">UNALIGNED</span>
      </div>
      {f"""<div class="verify-stat-card" style="background-color: #f0f9ff;">
        <span class="verify-stat-num" style="color: #0284c7;">{result.elf_exempt()}</span>
        <span class="verify-stat-label">豁免检查 (32 位架构)</span>
      </div>""" if result.elf_exempt() > 0 else ''}
    </div>
'''
        has_source_info = any(r.source_module or r.source_type == 'not_configured' for r in result.elf_results)
        source_col_header = '<th>来源模块</th>' if has_source_info else ''
        elf_details_open_attr = ' open' if result.elf_failed > 0 else ''
        html_content += f'''    <details class="verify-details-open"{elf_details_open_attr}>
      <summary class="verify-details-title">📝 各 SO 文件 ELF 对齐详情</summary>
      <div style="padding: 0;">
        <table>
          <thead>
            <tr>
              <th style="width: 50px;">#</th>
              <th>SO 文件名</th>
              <th>架构</th>
              <th>对齐值</th>
              <th>状态</th>
              <th>NDK 版本</th>
              {source_col_header}
            </tr>
          </thead>
          <tbody>
'''
        sorted_elf_results = sorted(result.elf_results, key=lambda x: (0 if x.status == "fail" else (1 if x.status == "warn" else 2), x.name))
        for i, elf_r in enumerate(sorted_elf_results, 1):
            if elf_r.arch == "arm64-v8a":
                arch_class = "arch-arm64"
            elif elf_r.arch == "armeabi-v7a":
                arch_class = "arch-armv7"
            elif elf_r.arch.startswith("x86"):
                arch_class = "arch-x86"
            else:
                arch_class = "arch-other"

            if elf_r.status == "pass":
                badge_class = "badge-pass"
                badge_text = "✅ ALIGNED"
            elif elf_r.status == "fail":
                badge_class = "badge-fail"
                badge_text = "❌ UNALIGNED"
            elif elf_r.status == "exempt":
                badge_class = "badge-exempt"
                badge_text = "ℹ️ 豁免 (32位)"
            else:
                badge_class = "badge-warn"
                badge_text = f"⚠️ {html.escape(elf_r.error)}" if elf_r.error else "⚠️ 未知"

            source_col = ''
            if has_source_info:
                if elf_r.source_module:
                    if elf_r.source_type == 'project':
                        source_tag = f'<span class="badge" style="background:#dbeafe;color:#1e40af;">项目</span> {html.escape(elf_r.source_module)}'
                    elif elf_r.source_type == 'external':
                        source_tag = f'<span class="badge" style="background:#fce7f3;color:#9d174d;">外部</span> <span class="mono" style="font-size:12px;">{html.escape(elf_r.source_module)}</span>'
                    else:
                        source_tag = html.escape(elf_r.source_module)
                else:
                    if elf_r.source_type == 'not_configured':
                        source_tag = '<span style="color:#9ca3af;">未设置</span>'
                    else:
                        source_tag = '<span style="color:#9ca3af;">未知</span>'
                source_col = f'<td>{source_tag}</td>'

            ndk_version_text = elf_r.ndk_version if elf_r.ndk_version else "未知"
            # NDK 版本分两行显示：编译器版本 + NDK 版本号
            ndk_display = _format_ndk_version_html(ndk_version_text)
            
            html_content += f'''            <tr>
              <td>{i}</td>
              <td class="mono">{html.escape(elf_r.name)}</td>
              <td><span class="arch-tag {arch_class}">{html.escape(elf_r.arch)}</span></td>
              <td class="mono">{html.escape(elf_r.align_value)}</td>
              <td><span class="badge {badge_class}">{badge_text}</span></td>
              <td class="mono" style="font-size: 12px; color: #6b7280; line-height: 1.6;">{ndk_display}</td>
              {source_col}
            </tr>
'''
        html_content += '''          </tbody>
        </table>
      </div>
    </details>
'''
        if elf_failed_list:
            html_content += '''    <div style="padding: 12px 24px; background: #fef2f2; border-top: 1px solid #fecaca; font-size: 13px; color: #991b1b;">
      💡 <strong>ELF 对齐问题需重新编译</strong>：升级 NDK r28+ 或添加链接参数 <code style="background:#fee2e2;padding:1px 4px;border-radius:3px;">-Wl,-z,max-page-size=16384</code>。第三方 SDK 需联系供应商更新。
    </div>
'''

        if result.elf_script_output:
            escaped_elf_output = html.escape(result.elf_script_output)
            escaped_elf_output = escaped_elf_output.replace(
                'ALIGNED', '<span class="line-pass">ALIGNED</span>'
            ).replace(
                'UNALIGNED', '<span class="line-fail">UNALIGNED</span>'
            ).replace(
                'ELF Verification Successful',
                '<span class="line-pass">ELF Verification Successful</span>'
            )
            elf_script_open_attr = ' open' if result.elf_failed > 0 else ''
            html_content += f'''    <details class="verify-details-open"{elf_script_open_attr}>
      <summary class="verify-details-title">📝 check_elf_alignment.sh 原始输出</summary>
      <div class="verify-output">{escaped_elf_output}</div>
    </details>
'''

        html_content += '  </div>\n'
    elif not find_check_elf_script():
        html_content += '''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查</h2>
      <span class="verify-status unavailable">⚠️ check_elf_alignment.sh 不可用</span>
    </div>
    <div class="verify-output"><span class="line-info">官方 check_elf_alignment.sh 脚本不可用。请确保：
1. 脚本文件存在于 scripts/ 目录下
2. 脚本具有执行权限 (chmod +x)
3. 系统已安装 objdump 或 llvm-objdump</span></div>
  </div>
'''
    else:
        html_content += f'''
  <div class="official-verify">
    <div class="verify-header">
      <h2>🔬 ELF LOAD 段对齐检查</h2>
      <span class="verify-status unavailable">⚠️ 未找到 .so 文件</span>
    </div>
    <div class="verify-output"><span class="line-info">APK 中未找到 .so 文件，无需检查 ELF 对齐。</span></div>
  </div>
'''

    # ---- tab-elf 内的修复建议 ----
    if result.elf_failed > 0:
        elf_failed_list_tips = [r for r in result.elf_results if r.status == "fail"]
        failed_so_names = sorted(set(r.name for r in elf_failed_list_tips))
        failed_so_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in failed_so_names)

        project_failed = [r for r in elf_failed_list_tips if r.source_type == "project"]
        external_failed = [r for r in elf_failed_list_tips if r.source_type == "external"]
        unknown_failed = [r for r in elf_failed_list_tips if not r.source_type or r.source_type == 'not_configured']

        html_content += '  <div class="tips" style="margin-top: 20px;">\n'
        html_content += '    <h2>💡 修复建议</h2>\n'
        html_content += f'''
    <h3 style="margin: 16px 0 8px; font-size: 15px; color: #dc2626;">🔧 ELF LOAD 段未对齐（需重新编译 .so）</h3>
    <p style="margin: 4px 0 8px; color: #991b1b; font-size: 13px;">
      以下 SO 的 ELF LOAD segment 对齐值 &lt; 16KB，<strong>无法通过 zipalign 修复</strong>，必须重新编译：{failed_so_html}
    </p>
    <ol style="padding-left: 24px; line-height: 1.8;">
      <li><strong>区分 SO 来源</strong>：
'''
        if project_failed or external_failed:
            html_content += '        <div style="margin: 8px 0; padding: 12px; background: #f8fafc; border-radius: 8px; font-size: 13px;">\n'
            if project_failed:
                project_names = sorted(set(f'{r.name} ← {r.source_module}' for r in project_failed))
                html_content += '          <div style="margin-bottom: 8px;"><span class="badge" style="background:#dbeafe;color:#1e40af;">项目模块</span> 修改 CMake / ndk-build 参数后重新编译：</div>\n'
                html_content += '          <ul style="margin: 4px 0 8px; padding-left: 20px;">\n'
                for item in project_names:
                    html_content += f'            <li><code>{html.escape(item)}</code></li>\n'
                html_content += '          </ul>\n'
            if external_failed:
                ext_by_module: Dict[str, List[str]] = {}
                for r in external_failed:
                    module = r.source_module or '未知'
                    ext_by_module.setdefault(module, []).append(r.name)
                html_content += '          <div style="margin-bottom: 8px;"><span class="badge" style="background:#fce7f3;color:#9d174d;">外部依赖</span> 联系供应商获取 16KB 对齐版本：</div>\n'
                html_content += '          <ul style="margin: 4px 0 8px; padding-left: 20px;">\n'
                for module, so_names_list in sorted(ext_by_module.items()):
                    names_str = ', '.join(f'<code>{html.escape(n)}</code>' for n in sorted(set(so_names_list)))
                    html_content += f'            <li><strong>{html.escape(module)}</strong> → {names_str}</li>\n'
                html_content += '          </ul>\n'
            if unknown_failed:
                unknown_names = sorted(set(r.name for r in unknown_failed))
                unknown_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in unknown_names)
                html_content += f'          <div><span class="badge" style="background:#f3f4f6;color:#374151;">来源未知</span> 需手动确认：{unknown_html}</div>\n'
            html_content += '        </div>\n'
        else:
            html_content += '''        <ul style="margin: 4px 0; padding-left: 20px;">
          <li><strong>自己编译的 SO</strong> → 修改 CMake / ndk-build 参数后重新编译（见下方步骤 2-3）</li>
          <li><strong>第三方 SDK 预编译的 SO</strong> → 联系 SDK 供应商获取 16KB 对齐版本，或在其 GitHub 仓库提 Issue</li>
        </ul>
'''
        html_content += '''      </li>
      <li><strong>CMake 项目</strong> — 在 <code>CMakeLists.txt</code> 中添加链接参数：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># CMakeLists.txt
target_link_options(${TARGET} PRIVATE "-Wl,-z,max-page-size=16384")</code></pre>
        或在 <code>build.gradle</code> 中通过 <code>externalNativeBuild</code> 传递：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// app/build.gradle
android {
    defaultConfig {
        externalNativeBuild {
            cmake {
                // 方式 1：通过 cFlags/cppFlags + ldFlags
                arguments "-DANDROID_SUPPORT_FLEXIBLE_PAGE_SIZES=ON"
                // 方式 2：直接传 ldFlags
                cppFlags "-fPIC"
            }
        }
    }
}</code></pre>
      </li>
      <li><strong>ndk-build 项目</strong> — 在 <code>Android.mk</code> 或 <code>Application.mk</code> 中添加：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># Android.mk
LOCAL_LDFLAGS += -Wl,-z,max-page-size=16384

# 或者在 Application.mk
APP_LDFLAGS += -Wl,-z,max-page-size=16384</code></pre>
      </li>
      <li><strong>推荐升级 NDK r28+</strong>：NDK r28 及以上版本默认使用 16KB 页面对齐编译，无需手动添加参数
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code>// build.gradle — 指定 NDK 版本
android {
    ndkVersion "28.0.12674087"  // 或更高
}</code></pre>
      </li>
      <li><strong>验证 SO 文件对齐</strong>：编译完成后，可用以下命令单独检查 .so 文件：
        <pre style="background:#f1f5f9; padding:8px 12px; border-radius:6px; margin:4px 0; font-size:13px; overflow-x:auto;"><code># 检查 ELF LOAD 段对齐值（应为 2**14 = 16384）
llvm-objdump -p libXxx.so | grep -A1 LOAD
# 或
readelf -l libXxx.so | grep -A1 LOAD</code></pre>
      </li>
    </ol>
'''
        html_content += '  </div>\n'

    # 关闭 tab-elf
    html_content += '  </div>\n\n'

    # ==================== Tab 3: 修复方案&参考资料 ====================
    html_content += '  <div id="tab-tips" class="tab-pane">\n'
    html_content += '  <div class="tips">\n'

    if zipalign_ok and result.elf_failed == 0 and not result.has_compressed_so:
        html_content += '''
    <p style="color: #16a34a; font-size: 14px;">🎉 当前 APK 已通过所有 16KB 对齐检查，无需额外修复。以下为通用参考信息。</p>
'''

    has_any_issue = not zipalign_ok or result.elf_failed > 0 or result.has_compressed_so
    if has_any_issue:
        html_content += '    <h2 style="margin-bottom: 16px;">🔧 修复方案总览</h2>\n'
        html_content += '    <p style="margin: 0 0 16px; font-size: 13px; color: #6b7280;">以下汇总了当前 APK 所有 16KB 对齐问题的修复方案，详细检查结果请查看前两个 Tab。</p>\n'

        if not zipalign_ok:
            fix_ref = result.fix_result
            fix_all_pass = (
                fix_ref and fix_ref.attempted and fix_ref.verify_result
                and fix_ref.verify_result.zipalign.fail_count == 0
            )
            html_content += '''
    <div style="background: #f0fdf4; border: 1px solid #bbf7d0; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #15803d;">📦 方案一：修复 ZIP 偏移对齐（zipalign）</h3>
'''
            if fix_all_pass:
                html_content += f'''
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">
        ✅ <strong>已验证可修复</strong> — 使用 <code>zipalign -P 16</code> 重新对齐后 zipalign 验证全部通过。
      </p>
'''
            html_content += '''
      <p style="margin: 0 0 8px; font-size: 13px; color: #166534;">选择以下任一方式：</p>
      <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom: 8px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold; width: 160px;">升级 AGP ≥ 8.5.1<br><span style="font-weight:normal;color:#6b7280;">（推荐）</span></td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">AGP 8.5.1+ 构建时自动执行 <code>zipalign -P 16</code>，无需额外配置</td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold;">手动 zipalign</td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">
            <code style="font-size:12px;">zipalign -P 16 -f 4 input.apk output.apk</code><br>
            <span style="color:#6b7280;">⚠️ 顺序：先 zipalign → 再 apksigner 签名（Build-Tools 35.0.0+）</span>
          </td>
        </tr>
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0; font-weight: bold;">useLegacyPackaging</td>
          <td style="padding: 8px 12px; border: 1px solid #bbf7d0;">确保 <code>packaging.jniLibs.useLegacyPackaging = false</code>（AGP 8.5.1+ 默认开启）</td>
        </tr>
      </table>
    </div>
'''

        if result.elf_failed > 0:
            elf_failed_list_ref = [r for r in result.elf_results if r.status == "fail"]
            project_failed_ref = [r for r in elf_failed_list_ref if r.source_type == "project"]
            external_failed_ref = [r for r in elf_failed_list_ref if r.source_type == "external"]

            html_content += '''
    <div style="background: #fef2f2; border: 1px solid #fecaca; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #dc2626;">🔬 方案二：修复 ELF LOAD 段对齐（需重新编译）</h3>
      <p style="margin: 0 0 8px; font-size: 13px; color: #991b1b;">
        ⚠️ <strong>zipalign 无法修复此问题</strong> — 需要从源码重新编译 SO 文件。
      </p>
      <table style="width:100%; border-collapse:collapse; font-size:13px; margin-bottom: 8px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold; width: 160px;">升级 NDK r28+<br><span style="font-weight:normal;color:#6b7280;">（推荐）</span></td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;">NDK r28+ 默认以 16KB 页面对齐编译，无需手动参数<br><code style="font-size:12px;">android { ndkVersion "28.0.12674087" }</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">CMake 项目</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">target_link_options(${TARGET} PRIVATE "-Wl,-z,max-page-size=16384")</code></td>
        </tr>
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">ndk-build 项目</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">LOCAL_LDFLAGS += -Wl,-z,max-page-size=16384</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fecaca; font-weight: bold;">验证命令</td>
          <td style="padding: 8px 12px; border: 1px solid #fecaca;"><code style="font-size:12px;">llvm-objdump -p lib.so | grep -A1 LOAD</code>（应为 2**14 = 16384）</td>
        </tr>
      </table>
'''
            if external_failed_ref:
                ext_modules: Dict[str, List[str]] = {}
                for r in external_failed_ref:
                    module = r.source_module or '未知'
                    ext_modules.setdefault(module, []).append(r.name)
                html_content += '      <div style="background:rgba(255,255,255,0.6); border-radius:6px; padding:10px 14px; margin-top:8px; font-size:13px;">\n'
                html_content += '        <strong style="color:#9d174d;">📦 外部依赖需联系供应商升级：</strong>\n'
                html_content += '        <ul style="margin:4px 0 0; padding-left:20px;">\n'
                for module, so_list in sorted(ext_modules.items()):
                    names_str = ', '.join(f'<code>{html.escape(n)}</code>' for n in sorted(set(so_list)))
                    html_content += f'          <li><strong>{html.escape(module)}</strong> → {names_str}</li>\n'
                html_content += '        </ul>\n'
                html_content += '      </div>\n'
            if project_failed_ref:
                proj_names = sorted(set(r.name for r in project_failed_ref))
                proj_html = ', '.join(f'<code>{html.escape(n)}</code>' for n in proj_names)
                html_content += f'      <div style="background:rgba(255,255,255,0.6); border-radius:6px; padding:10px 14px; margin-top:8px; font-size:13px;">\n'
                html_content += f'        <strong style="color:#1e40af;">📦 项目模块需重新编译：</strong> {proj_html}\n'
                html_content += '      </div>\n'
            html_content += '    </div>\n'

        if result.has_compressed_so:
            html_content += '''
    <div style="background: #fffbeb; border: 1px solid #fde68a; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px;">
      <h3 style="margin: 0 0 12px; font-size: 15px; color: #d97706;">📦 修复压缩存储的 SO 文件</h3>
      <p style="margin: 0 0 8px; font-size: 13px; color: #92400e;">
        压缩存储的 .so 无法被系统 mmap，也无法利用 16KB 页面对齐优势。
      </p>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <tr style="background: rgba(255,255,255,0.6);">
          <td style="padding: 8px 12px; border: 1px solid #fde68a; font-weight: bold; width: 160px;">build.gradle</td>
          <td style="padding: 8px 12px; border: 1px solid #fde68a;"><code>android.packaging.jniLibs.useLegacyPackaging = false</code></td>
        </tr>
        <tr>
          <td style="padding: 8px 12px; border: 1px solid #fde68a; font-weight: bold;">AndroidManifest</td>
          <td style="padding: 8px 12px; border: 1px solid #fde68a;">确保 <strong>没有</strong> <code>android:extractNativeLibs="true"</code></td>
        </tr>
      </table>
    </div>
'''

    # ---- 通用参考资料 ----
    html_content += '''
<h2 style="margin: 24px 0 12px;">📚 修复方案&参考资料</h2>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">🔗 官方文档</h3>
      <ul style="line-height: 2; margin: 0; padding-left: 24px;">
        <li><a href="https://developer.android.com/guide/practices/page-sizes?hl=zh-cn" style="color: #667eea;" target="_blank">Google 官方：支持 16KB 的页面大小</a>（<strong>2025 年 11 月 1 日起强制执行</strong>）</li>
        <li><a href="https://developer.android.com/build/releases/gradle-plugin?hl=zh-cn" style="color: #667eea;" target="_blank">Android Gradle Plugin 版本说明</a></li>
        <li><a href="https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh" style="color: #667eea;" target="_blank">AOSP 官方 check_elf_alignment.sh 脚本</a></li>
      </ul>
    </div>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">🛠️ 工具版本要求</h3>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background: #f1f5f9;">
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">工具</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">最低版本</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">说明</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">Android Gradle Plugin</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>8.5.1+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">构建时自动执行 <code>zipalign -P 16</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">NDK</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>r28+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">默认以 16KB 页面对齐编译 .so</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">Build-Tools</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><strong>35.0.0+</strong></td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign <code>-P</code> 参数支持</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div style="margin-bottom: 16px;">
      <h3 style="margin: 0 0 8px; font-size: 14px; color: #475569;">📋 常用命令</h3>
      <table style="width:100%; border-collapse:collapse; font-size:13px;">
        <thead>
          <tr style="background: #f1f5f9;">
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">用途</th>
            <th style="padding: 8px 12px; border: 1px solid #e2e8f0; text-align:left;">命令</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign 对齐</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">zipalign -P 16 -f 4 input.apk output.apk</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">zipalign 验证</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">zipalign -c -P 16 -v 4 app.apk</code></td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">APK 签名</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">apksigner sign --ks keystore.jks output.apk</code></td>
          </tr>
          <tr style="background: #f8fafc;">
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">ELF 对齐检查</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">llvm-objdump -p lib.so | grep -A1 LOAD</code></td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;">readelf 检查</td>
            <td style="padding: 8px 12px; border: 1px solid #e2e8f0;"><code style="font-size:12px;">readelf -l lib.so | grep -A1 LOAD</code></td>
          </tr>
        </tbody>
      </table>
    </div>
'''

    html_content += '  </div>\n'
    html_content += '  </div>\n\n'

    html_content += '''
  <div class="footer">
    Generated by check_alignment.py · 16KB Page Alignment Checker · Author: <a href="https://blog.bihe0832.com/" style="color: #667eea;">zixie</a><br>
    ELF check powered by <a href="https://cs.android.com/android/platform/superproject/main/+/main:system/extras/tools/check_elf_alignment.sh" style="color: #667eea;">AOSP check_elf_alignment.sh</a>
  </div>
</div>

<script>
function switchTab(tabId) {
  document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(tabId).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(b => {
    if (b.getAttribute('onclick').includes(tabId)) b.classList.add('active');
  });
}

function copyCmd(btn) {
  const code = btn.parentElement.querySelector('code').textContent;
  navigator.clipboard.writeText(code).then(() => {
    const original = btn.textContent;
    btn.textContent = '已复制';
    btn.style.borderColor = '#10b981';
    btn.style.color = '#10b981';
    setTimeout(() => {
      btn.textContent = original;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 1500);
  });
}
</script>
</body>
</html>
'''

    with open(html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
