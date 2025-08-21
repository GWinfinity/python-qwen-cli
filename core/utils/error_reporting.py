import os
import json
import tempfile
from datetime import datetime
from typing import Dict, Any, Optional, Union, List
from google.genai.types import Content

class ErrorReportData:
    def __init__(
        self,
        error: Dict[str, Any],
        context: Optional[Union[List[Content], Dict[str, Any], List[Any]]] = None,
        additional_info: Optional[Dict[str, Any]] = None
    ):
        self.error = error
        self.context = context
        self.additional_info = additional_info


async def report_error(
    error: Union[Exception, Any],
    base_message: str,
    context: Optional[Union[List[Content], Dict[str, Any], List[Any]]] = None,
    error_type: str = 'general',
    reporting_dir: Optional[str] = None
) -> None:
    # 确定报告目录，如果未提供则使用系统临时目录
    if reporting_dir is None:
        reporting_dir = tempfile.gettempdir()

    # 生成时间戳和报告文件名
    timestamp = datetime.now().isoformat().replace(':', '-').replace('.', '-')
    report_file_name = f'gemini-client-error-{error_type}-{timestamp}.json'
    report_path = os.path.join(reporting_dir, report_file_name)

    # 准备错误报告数据
    if isinstance(error, Exception):
        error_to_report = {
            'message': str(error),
            'stack': str(error.__traceback__)
        }
    elif isinstance(error, object) and hasattr(error, 'message'):
        error_to_report = {
            'message': str(error.message)
        }
    else:
        error_to_report = {
            'message': str(error)
        }

    report_content = {
        'error': error_to_report
    }

    if context is not None:
        report_content['context'] = context

    # 尝试序列化报告内容
    try:
        stringified_report_content = json.dumps(report_content, indent=2)
    except Exception as stringify_error:
        # 序列化失败的处理
        print(f'{baseMessage} Could not stringify report content (likely due to context):', stringify_error, file=sys.stderr)
        print('Original error that triggered report generation:', error, file=sys.stderr)
        if context:
            print('Original context could not be stringified or included in report.', file=sys.stderr)

        # 尝试写入仅包含错误的最小报告
        try:
            minimal_report_content = {'error': error_to_report}
            stringified_minimal_content = json.dumps(minimal_report_content, indent=2)
            with open(report_path, 'w') as f:
                f.write(stringified_minimal_content)
            print(f'{base_message} Partial report (excluding context) available at: {report_path}', file=sys.stderr)
        except Exception as minimal_write_error:
            print(f'{base_message} Failed to write even a minimal error report:', minimal_write_error, file=sys.stderr)
        return

    # 尝试写入完整报告
    try:
        with open(report_path, 'w') as f:
            f.write(stringified_report_content)
        print(f'{base_message} Full report available at: {report_path}', file=sys.stderr)
    except Exception as write_error:
        # 写入失败的处理
        print(f'{base_message} Additionally, failed to write detailed error report:', write_error, file=sys.stderr)
        print('Original error that triggered report generation:', error, file=sys.stderr)

        if context:
            # 尝试记录原始上下文
            try:
                print('Original context:', context, file=sys.stderr)
            except Exception:
                try:
                    # 尝试序列化并截断上下文
                    truncated_context = json.dumps(context)[:1000]
                    print(f'Original context (stringified, truncated): {truncated_context}', file=sys.stderr)
                except Exception:
                    print('Original context could not be logged or stringified.', file=sys.stderr)