import os
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

# 假设这些类和函数来自于对应的Python模块
from ..utils.git_ignore_parser import GitIgnoreParser, GitIgnoreFilter
from ..utils.git_utils import is_git_repository

GEMINI_IGNORE_FILE_NAME = '.geminiignore'


@dataclass
class FilterFilesOptions:
    """过滤文件选项"""
    respect_git_ignore: bool = True
    respect_gemini_ignore: bool = True


class FileDiscoveryService:
    """文件发现服务，用于根据忽略规则过滤文件路径"""

    def __init__(self, project_root: str):
        """初始化文件发现服务

        Args:
            project_root: 项目根目录路径
        """
        self.project_root = os.path.abspath(project_root)
        self.git_ignore_filter: Optional[GitIgnoreFilter] = None
        self.gemini_ignore_filter: Optional[GitIgnoreFilter] = None

        # 初始化git忽略过滤器
        if is_git_repository(self.project_root):
            parser = GitIgnoreParser(self.project_root)
            try:
                parser.load_git_repo_patterns()
                self.git_ignore_filter = parser
            except Exception:
                # 忽略文件未找到的错误
                pass

        # 初始化gemini忽略过滤器
        g_parser = GitIgnoreParser(self.project_root)
        try:
            g_parser.load_patterns(GEMINI_IGNORE_FILE_NAME)
            self.gemini_ignore_filter = g_parser
        except Exception:
            # 忽略文件未找到的错误
            pass

    def filter_files(
        self, file_paths: List[str], options: Optional[FilterFilesOptions] = None
    ) -> List[str]:
        """根据git忽略规则过滤文件路径列表

        Args:
            file_paths: 要过滤的文件路径列表
            options: 过滤选项

        Returns:
            过滤后的文件路径列表
        """
        if options is None:
            options = FilterFilesOptions()

        return [
            file_path
            for file_path in file_paths
            if not (
                (options.respect_git_ignore and self.should_git_ignore_file(file_path))
                or (
                    options.respect_gemini_ignore
                    and self.should_gemini_ignore_file(file_path)
                )
            )
        ]

    def should_git_ignore_file(self, file_path: str) -> bool:
        """检查单个文件是否应该被git忽略

        Args:
            file_path: 要检查的文件路径

        Returns:
            如果文件应该被忽略，则返回True，否则返回False
        """
        if self.git_ignore_filter:
            return self.git_ignore_filter.is_ignored(file_path)
        return False

    def should_gemini_ignore_file(self, file_path: str) -> bool:
        """检查单个文件是否应该被gemini忽略

        Args:
            file_path: 要检查的文件路径

        Returns:
            如果文件应该被忽略，则返回True，否则返回False
        """
        if self.gemini_ignore_filter:
            return self.gemini_ignore_filter.is_ignored(file_path)
        return False

    def should_ignore_file(
        self, file_path: str, options: Optional[Dict[str, Any]] = None
    ) -> bool:
        """统一方法检查文件是否应该被忽略

        Args:
            file_path: 要检查的文件路径
            options: 过滤选项字典

        Returns:
            如果文件应该被忽略，则返回True，否则返回False
        """
        if options is None:
            options = {}

        respect_git_ignore = options.get('respectGitIgnore', True)
        respect_gemini_ignore = options.get('respectGeminiIgnore', True)

        if respect_git_ignore and self.should_git_ignore_file(file_path):
            return True
        if respect_gemini_ignore and self.should_gemini_ignore_file(file_path):
            return True
        return False

    def get_gemini_ignore_patterns(self) -> List[str]:
        """获取从.geminiignore加载的模式

        Returns:
            忽略模式列表
        """
        if self.gemini_ignore_filter:
            return self.gemini_ignore_filter.get_patterns()
        return []