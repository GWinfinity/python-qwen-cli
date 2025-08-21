import os
from typing import Optional


def is_git_repository(directory: str) -> bool:
    """
    检查一个目录是否在 Git 仓库内

    Args:
        directory: 要检查的目录路径

    Returns:
        如果目录在 Git 仓库内返回 True，否则返回 False
    """
    try:
        current_dir = os.path.resolve(directory)

        while True:
            git_dir = os.path.join(current_dir, '.git')

            # 检查 .git 是否存在（可能是目录或工作树中的文件）
            if os.path.exists(git_dir):
                return True

            parent_dir = os.path.dirname(current_dir)

            # 如果到达根目录，停止搜索
            if parent_dir == current_dir:
                break

            current_dir = parent_dir

        return False
    except Exception:
        # 如果发生任何文件系统错误，假设不是 git 仓库
        return False


def find_git_root(directory: str) -> Optional[str]:
    """
    查找 Git 仓库的根目录

    Args:
        directory: 开始搜索的目录路径

    Returns:
        Git 仓库根目录路径，如果不在 Git 仓库内则返回 None
    """
    try:
        current_dir = os.path.resolve(directory)

        while True:
            git_dir = os.path.join(current_dir, '.git')

            if os.path.exists(git_dir):
                return current_dir

            parent_dir = os.path.dirname(current_dir)

            if parent_dir == current_dir:
                break

            current_dir = parent_dir

        return None
    except Exception:
        return None