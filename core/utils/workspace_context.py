import os
from pathlib import Path
from typing import Set, List, Optional, Union


class WorkspaceContext:
    """管理多个工作区目录并验证路径是否在这些目录内。
    这允许 CLI 在单个会话中操作来自多个目录的文件。"""

    def __init__(self, initial_directory: str, additional_directories: List[str] = None):
        """创建一个新的 WorkspaceContext 实例

        Args:
            initial_directory: 初始工作目录（通常是当前工作目录）
            additional_directories: 可选的要包含的其他目录数组
        """
        self.directories: Set[str] = set()

        self._add_directory_internal(initial_directory)

        if additional_directories:
            for dir_path in additional_directories:
                self._add_directory_internal(dir_path)

    def add_directory(self, directory: str, base_path: str = None) -> None:
        """将目录添加到工作区

        Args:
            directory: 要添加的目录路径（可以是相对路径或绝对路径）
            base_path: 解析相对路径的可选基础路径（默认为当前工作目录）
        """
        if base_path is None:
            base_path = os.getcwd()
        self._add_directory_internal(directory, base_path)

    def _add_directory_internal(self, directory: str, base_path: str = None) -> None:
        """添加目录的内部方法，包含验证

        Args:
            directory: 要添加的目录路径
            base_path: 解析相对路径的基础路径
        """
        if base_path is None:
            base_path = os.getcwd()

        # 解析绝对路径
        if os.path.isabs(directory):
            absolute_path = directory
        else:
            absolute_path = os.path.resolve(base_path, directory)

        # 验证目录是否存在
        if not os.path.exists(absolute_path):
            raise FileNotFoundError(f"Directory does not exist: {absolute_path}")

        # 验证是否是目录
        if not os.path.isdir(absolute_path):
            raise NotADirectoryError(f"Path is not a directory: {absolute_path}")

        # 解析真实路径
        try:
            real_path = os.path.realpath(absolute_path)
        except OSError as e:
            raise OSError(f"Failed to resolve path: {absolute_path}") from e

        self.directories.add(real_path)

    def get_directories(self) -> List[str]:
        """获取所有工作区目录的副本

        Returns:
            绝对目录路径数组
        """
        return list(self.directories)

    def is_path_within_workspace(self, path_to_check: str) -> bool:
        """检查给定路径是否在任何工作区目录内

        Args:
            path_to_check: 要验证的路径

        Returns:
            如果路径在工作区内则返回 True，否则返回 False
        """
        try:
            absolute_path = os.path.resolve(path_to_check)

            resolved_path = absolute_path
            if os.path.exists(absolute_path):
                try:
                    resolved_path = os.path.realpath(absolute_path)
                except OSError:
                    return False

            for dir_path in self.directories:
                if self._is_path_within_root(resolved_path, dir_path):
                    return True

            return False
        except OSError:
            return False

    def _is_path_within_root(self, path_to_check: str, root_directory: str) -> bool:
        """检查路径是否在给定的根目录内

        Args:
            path_to_check: 要检查的绝对路径
            root_directory: 绝对根目录

        Returns:
            如果路径在根目录内则返回 True，否则返回 False
        """
        relative = os.path.relpath(path_to_check, root_directory)
        # 检查相对路径是否以 ../ 开头，或者是 ..，或者是绝对路径
        return not (
            relative.startswith(f"..{os.path.sep}") or
            relative == ".." or
            os.path.isabs(relative)
        )