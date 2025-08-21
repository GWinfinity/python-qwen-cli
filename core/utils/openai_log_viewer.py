import os
import pathlib
import json
import argparse
from datetime import datetime
from typing import List, Optional, Dict, Any

# 假设我们有一个 openai_logger 模块提供日志功能
# 如果没有，这些类型需要根据实际情况调整或模拟
from openai_logger import OpenAIRequestLog, OpenAIRequestType  # 假设的导入


class OpenAILogViewer:
    @staticmethod
    def list_logs(log_dir: str) -> None:
        """列出所有 OpenAI 日志文件"""
        log_path = pathlib.Path(log_dir)
        if not log_path.exists():
            print(f"Log directory not found: {log_dir}")
            return

        log_files = list(log_path.glob("*.json"))
        if not log_files:
            print('No OpenAI logs found')
            return

        print("OpenAI Logs:")
        print("=" * 80)
        print(f"{'Index':<6} {'Filename':<40} {'Date':<20} {'Request Type'}")
        print("=" * 80)

        for i, log_file in enumerate(sorted(log_files), 1):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    log_data = json.load(f)
                    request_type = OpenAILogViewer._get_request_type(log_data)
                    timestamp = log_data.get('timestamp', '')
                    if timestamp:
                        # 假设 timestamp 是 ISO 格式字符串
                        date_str = datetime.fromisoformat(timestamp).strftime('%Y-%m-%d %H:%M:%S')
                    else:
                        date_str = 'Unknown'

                    print(f"{i:<6} {log_file.name:<40} {date_str:<20} {request_type}")
            except (json.JSONDecodeError, KeyError) as e:
                print(f"{i:<6} {log_file.name:<40} {'Error reading log':<20} {str(e)}")

    @staticmethod
    def view_log(log_dir: str, log_index: int) -> None:
        """查看特定索引的日志文件"""
        log_path = pathlib.Path(log_dir)
        if not log_path.exists():
            print(f"Log directory not found: {log_dir}")
            return

        log_files = list(log_path.glob("*.json"))
        if not log_files:
            print('No OpenAI logs found')
            return

        if log_index < 1 or log_index > len(log_files):
            print(f"Invalid log index: {log_index}. Must be between 1 and {len(log_files)}")
            return

        log_file = sorted(log_files)[log_index - 1]
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                log_data = json.load(f)
                print(f"\nLog: {log_file.name}")
                print("=" * 80)
                print(json.dumps(log_data, indent=2, ensure_ascii=False))
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error reading log file {log_file.name}: {str(e)}")

    @staticmethod
    def cleanup_logs(log_dir: str, keep_recent: int = 5) -> None:
        """清理日志文件，保留最近的指定数量"""
        log_path = pathlib.Path(log_dir)
        if not log_path.exists():
            print(f"Log directory not found: {log_dir}")
            return

        log_files = list(log_path.glob("*.json"))
        if not log_files:
            print('No OpenAI logs to clean up')
            return

        # 按修改时间排序（最新的在前）
        sorted_logs = sorted(log_files, key=lambda x: x.stat().st_mtime, reverse=True)

        # 保留最近的 keep_recent 个日志
        logs_to_delete = sorted_logs[keep_recent:]

        if not logs_to_delete:
            print(f"No logs to delete. Keeping all {len(log_files)} logs.")
            return

        print(f"Deleting {len(logs_to_delete)} old logs...")
        for log_file in logs_to_delete:
            try:
                log_file.unlink()
                print(f"Deleted: {log_file.name}")
            except Exception as e:
                print(f"Error deleting {log_file.name}: {str(e)}")

        print("Cleanup complete.")

    @staticmethod
    def _get_request_type(log_data: Dict[str, Any]) -> str:
        """获取请求类型"""
        if not log_data:
            return 'Unknown'

        # 从 log_data 中提取请求类型的逻辑
        # 这里根据原始 TypeScript 代码的逻辑实现
        if 'request' in log_data:
            request = log_data['request']
            if 'messages' in request and request['messages']:
                return 'ChatCompletion'
            elif 'prompt' in request:
                return 'Completion'
            elif 'image' in request:
                return 'Image'
            elif 'embedding' in request:
                return 'Embedding'

        return 'Unknown'


def main():
    parser = argparse.ArgumentParser(description='OpenAI Log Viewer')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # 列出日志命令
    list_parser = subparsers.add_parser('list', help='List all OpenAI logs')
    list_parser.add_argument('--log-dir', type=str, default='./logs/openai',
                            help='Directory where OpenAI logs are stored')

    # 查看日志命令
    view_parser = subparsers.add_parser('view', help='View a specific OpenAI log')
    view_parser.add_argument('--log-dir', type=str, default='./logs/openai',
                            help='Directory where OpenAI logs are stored')
    view_parser.add_argument('index', type=int, help='Index of the log to view')

    # 清理日志命令
    cleanup_parser = subparsers.add_parser('cleanup', help='Clean up old OpenAI logs')
    cleanup_parser.add_argument('--log-dir', type=str, default='./logs/openai',
                              help='Directory where OpenAI logs are stored')
    cleanup_parser.add_argument('--keep-recent', type=int, default=5,
                              help='Number of recent logs to keep')

    args = parser.parse_args()

    if args.command == 'list':
        OpenAILogViewer.list_logs(args.log_dir)
    elif args.command == 'view':
        OpenAILogViewer.view_log(args.log_dir, args.index)
    elif args.command == 'cleanup':
        OpenAILogViewer.cleanup_logs(args.log_dir, args.keep_recent)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()