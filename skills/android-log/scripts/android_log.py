#!/usr/bin/env python3
"""Android 日志抓取工具（Python 版本）

import sys
from pathlib import Path
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
from bootstrap import load_env  # noqa: E402

load_env()

基于公共 adb_tools 模块，提供更可靠的 adb 路径查找和错误处理。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# 导入公共 adb 工具库：优先 skill 内部分发副本（部署环境），否则回退运行时部署路径（源环境）
import sys
from pathlib import Path
for _p in Path(__file__).resolve().parents:
    if (_p / "scripts").is_dir():
        sys.path.insert(0, str(_p / "scripts"))
        break
sys.path.insert(1, str(Path.home() / ".zixiekit" / "scripts"))
from adb_tools import get_adb_cmd, diagnose_adb_status


class AndroidLogManager:
    """Android 日志管理器"""
    
    def __init__(self, device: Optional[str] = None):
        self.device = device
        self.debug_dir = Path(os.environ.get('WORK_ROOT', os.path.expanduser('~/zixie'))) / 'temp' / 'cache' / 'debug'
        self.history_file = self.debug_dir / 'history.log'
        self.corrections_file = self.debug_dir / 'corrections.log'
        self.debug_dir.mkdir(parents=True, exist_ok=True)
    
    def logcat_debug(self, tag: str = "APP_DEBUG") -> str:
        """抓取调试日志"""
        adb = get_adb_cmd(self.device)
        result = subprocess.run(
            adb + ["logcat", "-d", "-v", "time"],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            return f"❌ ADB 命令执行失败: {result.stderr}"
        
        lines = result.stdout.splitlines()
        filtered = [line for line in lines if tag in line]
        
        if not filtered:
            return f"# 调试日志 (TAG={tag})\n(无匹配日志)"
        
        return f"# 调试日志 (TAG={tag})\n" + "\n".join(filtered)
    
    def logcat_errors(self, tag: str = "APP_DEBUG") -> str:
        """抓取调试日志 + 异常"""
        adb = get_adb_cmd(self.device)
        result = subprocess.run(
            adb + ["logcat", "-d", "-v", "time"],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            return f"❌ ADB 命令执行失败: {result.stderr}"
        
        lines = result.stdout.splitlines()
        # 匹配调试标签或异常/错误信息
        pattern = re.compile(f"({tag}|Exception|Error|FATAL)", re.IGNORECASE)
        filtered = [line for line in lines if pattern.search(line)]
        
        if not filtered:
            return f"# 调试日志 + 异常 (TAG={tag})\n(无匹配日志)"
        
        return f"# 调试日志 + 异常 (TAG={tag})\n" + "\n".join(filtered)
    
    def logcat_raw(self, filter_pattern: str = "") -> str:
        """抓取原始 logcat"""
        adb = get_adb_cmd(self.device)
        result = subprocess.run(
            adb + ["logcat", "-d", "-v", "time"],
            capture_output=True, text=True, timeout=30
        )
        
        if result.returncode != 0:
            return f"❌ ADB 命令执行失败: {result.stderr}"
        
        lines = result.stdout.splitlines()
        
        if filter_pattern:
            pattern = re.compile(filter_pattern, re.IGNORECASE)
            filtered = [line for line in lines if pattern.search(line)]
            if not filtered:
                return f"# 原始 logcat (过滤: {filter_pattern})\n(无匹配日志)"
            return f"# 原始 logcat (过滤: {filter_pattern})\n" + "\n".join(filtered)
        else:
            return f"# 原始 logcat (最近 200 行)\n" + "\n".join(lines[-200:])
    
    def clear_logcat(self) -> str:
        """清空 logcat 缓冲区"""
        adb = get_adb_cmd(self.device)
        result = subprocess.run(
            adb + ["logcat", "-c"],
            capture_output=True, text=True, timeout=10
        )
        
        if result.returncode == 0:
            return "✅ 已清空 logcat 缓冲区"
        else:
            return f"❌ 清空失败: {result.stderr}"
    
    def show_history(self) -> str:
        """查看调试历史"""
        if not self.history_file.exists():
            return "(无调试历史)"
        
        with open(self.history_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        recent = lines[-10:] if len(lines) > 10 else lines
        return "# 调试历史（最近 10 条）\n" + "".join(recent)
    
    def show_corrections(self) -> str:
        """查看纠正记录"""
        if not self.corrections_file.exists():
            return "(无纠正记录)"
        
        with open(self.corrections_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 按 "---" 分隔记录
        records = content.strip().split('---\n')
        recent = records[-5:] if len(records) > 5 else records
        
        return "# 纠正记录（最近 5 条）\n" + "\n---\n".join(recent)
    
    def record_history(self, summary: str) -> str:
        """记录调试历史"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        entry = f"[{timestamp}] {summary}\n"
        
        # 保持最近 10 条记录
        if self.history_file.exists():
            with open(self.history_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            if len(lines) >= 10:
                lines = lines[-9:]  # 保留最后 9 条
                with open(self.history_file, 'w', encoding='utf-8') as f:
                    f.writelines(lines)
        
        with open(self.history_file, 'a', encoding='utf-8') as f:
            f.write(entry)
        
        return "✅ 已记录调试历史"
    
    def record_correction(self, correction_type: str, module: str, 
                         ai_judgment: str, user_feedback: str) -> str:
        """记录纠正"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M')
        entry = f"""[{timestamp}] 类型: {correction_type}
模块: {module}
AI判断: {ai_judgment}
用户反馈: {user_feedback}
---
"""
        
        with open(self.corrections_file, 'a', encoding='utf-8') as f:
            f.write(entry)
        
        return "✅ 已记录纠正"


def main():
    parser = argparse.ArgumentParser(
        prog="android_log.py",
        description="Android 日志抓取工具（Python 版本）"
    )
    
    subparsers = parser.add_subparsers(dest='command', help='命令')
    
    # logcat 命令
    logcat_parser = subparsers.add_parser('logcat', help='抓取调试日志')
    logcat_parser.add_argument('tag', nargs='?', default='APP_DEBUG', help='日志标签')
    
    # logcat-errors 命令
    errors_parser = subparsers.add_parser('logcat-errors', help='抓取调试日志 + 异常')
    errors_parser.add_argument('tag', nargs='?', default='APP_DEBUG', help='日志标签')
    
    # logcat-raw 命令
    raw_parser = subparsers.add_parser('logcat-raw', help='抓取原始 logcat')
    raw_parser.add_argument('filter', nargs='?', default='', help='过滤模式（正则表达式）')
    
    # 其他命令
    subparsers.add_parser('clear', help='清空 logcat 缓冲区')
    subparsers.add_parser('history', help='查看调试历史')
    subparsers.add_parser('corrections', help='查看纠正记录')
    
    # record 命令
    record_parser = subparsers.add_parser('record', help='记录调试历史')
    record_parser.add_argument('summary', help='摘要信息')
    
    # correct 命令
    correct_parser = subparsers.add_parser('correct', help='记录纠正')
    correct_parser.add_argument('type', help='纠正类型')
    correct_parser.add_argument('module', help='模块名')
    correct_parser.add_argument('ai_judgment', help='AI判断')
    correct_parser.add_argument('user_feedback', help='用户反馈')
    
    # 设备参数
    parser.add_argument('--device', '-s', help='指定设备序列号')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    manager = AndroidLogManager(args.device)
    
    try:
        # 先执行 adb 诊断
        diagnose_adb_status(args.device)
        
        if args.command == 'logcat':
            print(manager.logcat_debug(args.tag))
        elif args.command == 'logcat-errors':
            print(manager.logcat_errors(args.tag))
        elif args.command == 'logcat-raw':
            print(manager.logcat_raw(args.filter))
        elif args.command == 'clear':
            print(manager.clear_logcat())
        elif args.command == 'history':
            print(manager.show_history())
        elif args.command == 'corrections':
            print(manager.show_corrections())
        elif args.command == 'record':
            print(manager.record_history(args.summary))
        elif args.command == 'correct':
            print(manager.record_correction(args.type, args.module, args.ai_judgment, args.user_feedback))
        
        return 0
        
    except FileNotFoundError as e:
        print(f"❌ {e}", file=sys.stderr)
        return 1
    except subprocess.TimeoutExpired:
        print("❌ ADB 命令执行超时", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"❌ 执行失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
