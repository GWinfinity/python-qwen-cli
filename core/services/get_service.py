import asyncio
import os
import pathlib
import subprocess
from typing import Optional
from git import Repo, GitCommandError
from dataclasses import dataclass
from ..utils.path import GEMINI_DIR,get_project_hash


def is_node_error(error: Exception) -> bool:
    """检查是否为Node错误"""
    # 在Python中简化实现
    return hasattr(error, 'code')


class GitService:
    """Git服务类，提供项目版本控制相关功能"""

    def __init__(self, project_root: str):
        """初始化Git服务

        Args:
            project_root: 项目根目录路径
        """
        self.project_root = os.path.abspath(project_root)

    def get_history_dir(self) -> str:
        """获取历史记录目录路径"""
        hash_value = get_project_hash(self.project_root)
        home_dir = os.path.expanduser('~')
        return os.path.join(home_dir, GEMINI_DIR, 'history', hash_value)

    async def initialize(self) -> None:
        """初始化Git服务"""
        git_available = await self.verify_git_availability()
        if not git_available:
            raise ValueError(
                'Checkpointing is enabled, but Git is not installed. Please install Git or disable checkpointing to continue.'
            )
        await self.setup_shadow_git_repository()

    async def verify_git_availability(self) -> bool:
        """验证Git是否可用"""
        try:
            # 使用asyncio运行同步子进程命令
            process = await asyncio.create_subprocess_exec(
                'git', '--version',
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            await process.wait()
            return process.returncode == 0
        except FileNotFoundError:
            return False

    async def setup_shadow_git_repository(self) -> None:
        """在项目根目录创建一个隐藏的Git仓库"""
        repo_dir = self.get_history_dir()
        git_config_path = os.path.join(repo_dir, '.gitconfig')

        # 创建目录
        pathlib.Path(repo_dir).mkdir(parents=True, exist_ok=True)

        # 写入git配置
        git_config_content = (
            '[user]' +
            '  name = Gemini CLI' +
            '  email = gemini-cli@google.com' +
            '[commit]' +
            '  gpgsign = false'
        )
        with open(git_config_path, 'w', encoding='utf-8') as f:
            f.write(git_config_content)

        # 初始化仓库
        is_repo_defined = False
        try:
            # 检查是否已经是仓库
            Repo(repo_dir)
            is_repo_defined = True
        except Exception:
            pass

        if not is_repo_defined:
            # 初始化新仓库
            repo = Repo.init(repo_dir)
            # 创建初始提交
            with repo.config_writer() as writer:
                writer.set_value('user', 'name', 'Gemini CLI')
                writer.set_value('user', 'email', 'gemini-cli@google.com')
                writer.set_value('commit', 'gpgsign', 'false')
            repo.index.commit('Initial commit', allow_empty=True)

        # 处理.gitignore
        user_git_ignore_path = os.path.join(self.project_root, '.gitignore')
        shadow_git_ignore_path = os.path.join(repo_dir, '.gitignore')

        user_git_ignore_content = ''
        try:
            with open(user_git_ignore_path, 'r', encoding='utf-8') as f:
                user_git_ignore_content = f.read()
        except Exception as e:
            if not (is_node_error(e) and e.code == 'ENOENT'):
                raise e

        with open(shadow_git_ignore_path, 'w', encoding='utf-8') as f:
            f.write(user_git_ignore_content)

    @property
    def shadow_git_repository(self) -> Repo:
        """获取影子Git仓库对象"""
        repo_dir = self.get_history_dir()
        git_dir = os.path.join(repo_dir, '.git')

        # 设置环境变量
        env = os.environ.copy()
        env['GIT_DIR'] = git_dir
        env['GIT_WORK_TREE'] = self.project_root
        env['HOME'] = repo_dir
        env['XDG_CONFIG_HOME'] = repo_dir

        # 创建Repo对象时传递环境变量
        return Repo(self.project_root, env=env)

    async def get_current_commit_hash(self) -> str:
        """获取当前提交哈希值"""
        repo = self.shadow_git_repository
        return repo.head.commit.hexsha

    async def create_file_snapshot(self, message: str) -> str:
        """创建文件快照

        Args:
            message: 提交信息

        Returns:
            提交哈希值
        """
        repo = self.shadow_git_repository
        # 添加所有文件
        repo.git.add('.')
        # 提交
        commit = repo.index.commit(message)
        return commit.hexsha

    async def restore_project_from_snapshot(self, commit_hash: str) -> None:
        """从快照恢复项目

        Args:
            commit_hash: 提交哈希值
        """
        repo = self.shadow_git_repository
        # 恢复文件
        repo.git.restore('--source', commit_hash, '.')
        # 清理未跟踪的文件
        repo.git.clean('f', '-d')