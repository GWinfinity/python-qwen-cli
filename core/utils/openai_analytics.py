import os
import pathlib
import json
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Union, List

# 假设已存在对应的openai_logger模块
from .openai_logger import openai_logger


class OpenAIAnalytics:
    """
    OpenAI API使用分析工具

    该工具分析OpenAI API日志，提供API使用模式、成本和性能的洞察
    """

    @staticmethod
    async def calculate_stats(days: int = 7) -> Dict[str, Any]:
        """
        计算OpenAI API使用统计数据
        :param days: 分析的天数（默认：7）
        :return: 包含统计数据的字典
        """
        logs = await openai_logger.get_log_files()
        now = datetime.now()
        cutoff_date = now - timedelta(days=days)

        total_requests = 0
        successful_requests = 0
        total_response_time = 0
        requests_by_model: Dict[str, int] = {}
        token_usage = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0}
        error_types: Dict[str, int] = {}
        hour_distribution: Dict[str, int] = {}

        # 初始化小时分布（0-23）
        for i in range(24):
            hour = f"{i:02d}"
            hour_distribution[hour] = 0

        # 模型定价估算（每1000个token）
        pricing: Dict[str, Dict[str, float]] = {
            'gpt-4': {'input': 0.03, 'output': 0.06},
            'gpt-4-32k': {'input': 0.06, 'output': 0.12},
            'gpt-4-1106-preview': {'input': 0.01, 'output': 0.03},
            'gpt-4-0125-preview': {'input': 0.01, 'output': 0.03},
            'gpt-4-0613': {'input': 0.03, 'output': 0.06},
            'gpt-4-32k-0613': {'input': 0.06, 'output': 0.12},
            'gpt-3.5-turbo': {'input': 0.0015, 'output': 0.002},
            'gpt-3.5-turbo-16k': {'input': 0.003, 'output': 0.004},
            'gpt-3.5-turbo-0613': {'input': 0.0015, 'output': 0.002},
            'gpt-3.5-turbo-16k-0613': {'input': 0.003, 'output': 0.004},
        }

        # 未知模型的默认定价
        default_pricing = {'input': 0.01, 'output': 0.03}

        estimated_cost = 0

        for log_file in logs:
            try:
                log_data = await openai_logger.read_log_file(log_file)

                # 检查日志数据是否有预期的结构
                if not isinstance(log_data, dict) or 'timestamp' not in log_data:
                    continue  # 跳过格式错误的日志

                log_date = datetime.fromisoformat(log_data['timestamp'])

                # 如果日志早于截止日期，则跳过
                if log_date < cutoff_date:
                    continue

                total_requests += 1
                hour = f"{log_date.hour:02d}"
                hour_distribution[hour] += 1

                # 检查请求是否成功
                if ('response' in log_data and log_data['response'] and
                        'error' not in log_data):
                    successful_requests += 1

                    # 提取模型（如果可用）
                    model = OpenAIAnalytics._get_model_from_log(log_data)
                    if model:
                        requests_by_model[model] = requests_by_model.get(model, 0) + 1

                    # 提取token使用情况（如果可用）
                    usage = OpenAIAnalytics._get_token_usage_from_log(log_data)
                    if usage:
                        token_usage['promptTokens'] += usage.get('prompt_tokens', 0)
                        token_usage['completionTokens'] += usage.get('completion_tokens', 0)
                        token_usage['totalTokens'] += usage.get('total_tokens', 0)

                        # 计算成本（如果模型已知）
                        model_name = model or 'unknown'
                        model_pricing = pricing.get(model_name, default_pricing)

                        input_cost = (usage.get('prompt_tokens', 0) / 1000) * model_pricing['input']
                        output_cost = (usage.get('completion_tokens', 0) / 1000) * model_pricing['output']
                        estimated_cost += input_cost + output_cost
                elif 'error' in log_data and log_data['error']:
                    # 分类错误
                    error_type = OpenAIAnalytics._get_error_type_from_log(log_data)
                    error_types[error_type] = error_types.get(error_type, 0) + 1
            except Exception as e:
                print(f"处理日志文件 {log_file} 时出错: {e}")

        # 计算成功率和平均响应时间
        success_rate = (successful_requests / total_requests * 100) if total_requests > 0 else 0
        avg_response_time = total_response_time / total_requests if total_requests > 0 else 0

        # 计算错误率（百分比）
        error_rates: Dict[str, float] = {}
        for error_type, count in error_types.items():
            error_rates[error_type] = (count / total_requests * 100) if total_requests > 0 else 0

        return {
            'totalRequests': total_requests,
            'successRate': success_rate,
            'avgResponseTime': avg_response_time,
            'requestsByModel': requests_by_model,
            'tokenUsage': token_usage,
            'estimatedCost': estimated_cost,
            'errorRates': error_rates,
            'timeDistribution': hour_distribution
        }

    @staticmethod
    async def generate_report(days: int = 7) -> str:
        """
        生成OpenAI API使用的可读报告
        :param days: 报告中包含的天数
        :return: 报告字符串
        """
        stats = await OpenAIAnalytics.calculate_stats(days)

        report = f"# OpenAI API使用报告\n"
        report += f"## 过去 {days} 天 ({datetime.now().strftime('%Y-%m-%d')})\n\n"

        report += "### 概览\n"
        report += f"- 总请求数: {stats['totalRequests']}\n"
        report += f"- 成功率: {stats['successRate']:.2f}%\n"
        report += f"- 估计成本: ${stats['estimatedCost']:.2f}\n\n"

        report += "### Token使用情况\n"
        report += f"- 提示Tokens: {stats['tokenUsage']['promptTokens']:,}\n"
        report += f"- 完成Tokens: {stats['tokenUsage']['completionTokens']:,}\n"
        report += f"- 总Tokens: {stats['tokenUsage']['totalTokens']:,}\n\n"

        report += "### 使用的模型\n"
        sorted_models = sorted(stats['requestsByModel'].items(), key=lambda x: x[1], reverse=True)

        for model, count in sorted_models:
            percentage = (count / stats['totalRequests'] * 100) if stats['totalRequests'] > 0 else 0
            report += f"- {model}: {count} 请求 ({percentage:.1f}%)\n"

        if stats['errorRates']:
            report += "\n### 错误类型\n"
            sorted_errors = sorted(stats['errorRates'].items(), key=lambda x: x[1], reverse=True)

            for error_type, rate in sorted_errors:
                report += f"- {error_type}: {rate:.1f}%\n"

        report += "\n### 按小时使用情况 (UTC)\n"
        report += "```\n"
        max_requests = max(stats['timeDistribution'].values()) if stats['timeDistribution'] else 0
        scale = 40  # 最大条形长度

        for i in range(24):
            hour = f"{i:02d}"
            requests = stats['timeDistribution'].get(hour, 0)
            bar_length = round((requests / max_requests) * scale) if max_requests > 0 else 0
            bar = '█' * bar_length
            report += f"{hour}:00 {bar.ljust(scale)} {requests}\n"
        report += "```\n"

        return report

    @staticmethod
    async def save_report(days: int = 7, output_path: Optional[str] = None) -> str:
        """
        将分析报告保存到文件
        :param days: 报告中包含的天数
        :param output_path: 报告的文件路径（默认为logs/openai/analytics.md）
        :return: 报告文件路径
        """
        report = await OpenAIAnalytics.generate_report(days)
        report_path = output_path or os.path.join(os.getcwd(), 'logs', 'openai', 'analytics.md')

        # 确保目录存在
        os.makedirs(os.path.dirname(report_path), exist_ok=True)

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write(report)
        return report_path

    @staticmethod
    def _get_model_from_log(log_data: Dict[str, Any]) -> Optional[str]:
        """
        从日志条目中提取模型名称
        :param log_data: 日志数据
        :return: 模型名称或None
        """
        if isinstance(log_data.get('request'), dict) and 'model' in log_data['request']:
            return log_data['request']['model']
        if isinstance(log_data.get('response'), dict):
            if 'model' in log_data['response']:
                return log_data['response']['model']
            if 'modelVersion' in log_data['response']:
                return log_data['response']['modelVersion']
        return None

    @staticmethod
    def _get_token_usage_from_log(log_data: Dict[str, Any]) -> Optional[Dict[str, int]]:
        """
        从日志条目中提取token使用信息
        :param log_data: 日志数据
        :return: 包含token使用信息的字典或None
        """
        if isinstance(log_data.get('response'), dict):
            response = log_data['response']
            if 'usage' in response and isinstance(response['usage'], dict):
                return response['usage']
            if 'usageMetadata' in response and isinstance(response['usageMetadata'], dict):
                metadata = response['usageMetadata']
                return {
                    'prompt_tokens': metadata.get('promptTokenCount'),
                    'completion_tokens': metadata.get('candidatesTokenCount'),
                    'total_tokens': metadata.get('totalTokenCount')
                }
        return None

    @staticmethod
    def _get_error_type_from_log(log_data: Dict[str, Any]) -> str:
        """
        从日志条目中提取并分类错误类型
        :param log_data: 日志数据
        :return: 错误类型
        """
        if isinstance(log_data.get('error'), dict):
            error = log_data['error']
            error_msg = error.get('message', '')
            if 'rate limit' in error_msg.lower():
                return 'rate_limit'
            if 'timeout' in error_msg.lower():
                return 'timeout'
            if 'authentication' in error_msg.lower():
                return 'authentication'
            if 'quota' in error_msg.lower():
                return 'quota_exceeded'
            if 'invalid' in error_msg.lower():
                return 'invalid_request'
            if 'not available' in error_msg.lower():
                return 'model_unavailable'
            if 'content filter' in error_msg.lower():
                return 'content_filtered'
            return 'other'
        return 'unknown'


# 当脚本直接运行时的CLI接口
if __name__ == '__main__':
    import sys
    import asyncio

    async def main():
        args = sys.argv[1:]
        days = int(args[0]) if args else 7

        try:
            report_path = await OpenAIAnalytics.save_report(days)
            print(f"分析报告已保存到: {report_path}")

            # 同时打印到控制台
            report = await OpenAIAnalytics.generate_report(days)
            print(report)
        except Exception as e:
            print(f"生成分析报告时出错: {e}")

    asyncio.run(main())


default = OpenAIAnalytics