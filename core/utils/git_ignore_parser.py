import os
from pathlib import Path
from typing import List, Optional
from ignore import Ignore  

from .git_utils import is_git_repository 


class GitIgnoreFilter:
    """Git 忽略文件过滤器接口"""
    def is_ignored(self, file_path: str) -> bool:
        """检查文件是否被忽略"""
        pass

    def get_patterns(self) -> List[str]:
        """获取所有忽略模式"""
        pass


class GitIgnoreParser(GitIgnoreFilter):
    """
    Git 忽略文件解析器
    解析 .gitignore 和 .git/info/exclude 文件中的忽略模式
    """
    def __init__(self, project_root: str) -> None:
        """
        初始化 GitIgnoreParser

        Args:
            project_root: 项目根目录路径
        """
        self.project_root = os.path.resolve(project_root)
        self.ig = Ignore()
        self.patterns: List[str] = []

    def load_git_repo_patterns(self) -> None:
        """加载 Git 仓库中的忽略模式"""
        if not is_git_repository(self.project_root):
            return

        # 无论 .gitignore 内容如何，始终忽略 .git 目录
        self.add_patterns(['.git'])

        pattern_files = ['.gitignore', os.path.join('.git', 'info', 'exclude')]
        for pf in pattern_files:
            self.load_patterns(pf)

    def load_patterns(self, patterns_file_name: str) -> None:
        """
        从指定文件加载忽略模式

        Args:
            patterns_file_name: 包含忽略模式的文件名
        """
        patterns_file_path = os.path.join(self.project_root, patterns_file_name)
        try:
            with open(patterns_file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            # 忽略文件不存在的情况
            return

        patterns = [
            p.strip()
            for p in content.split('\n')
            if p.strip() and not p.strip().startswith('#')
        ]
        self.add_patterns(patterns)

    def add_patterns(self, patterns: List[str]) -> None:
        """
        添加忽略模式

        Args:
            patterns: 忽略模式列表
        """
        self.ig.add(patterns)
        self.patterns.extend(patterns)

    def is_ignored(self, file_path: str) -> bool:
        """
        检查文件是否被忽略

        Args:
            file_path: 要检查的文件路径

        Returns:
            如果文件被忽略返回 True，否则返回 False
        """
        resolved = os.path.resolve(self.project_root, file_path)
        relative_path = os.path.relpath(resolved, self.project_root)

        if relative_path == '' or relative_path.startswith('..'):
            return False

        # 即使在 Windows 上，Ignore 也期望使用正斜杠
        normalized_path = relative_path.replace('\\', '/')
        return self.ig.ignores(normalized_path)

    def get_patterns(self) -> List[str]:
        """
        获取所有忽略模式

        Returns:
            忽略模式列表
        """
        return self.patterns