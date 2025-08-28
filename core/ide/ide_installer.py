import subprocess
import sys
import glob
import os
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

from .detect_ide import DetectedIde

VSCODE_COMMAND = 'code.cmd' if sys.platform == 'win32' else 'code'
VSCODE_COMPANION_EXTENSION_FOLDER = 'vscode-ide-companion'


class InstallResult:
    def __init__(self, success: bool, message: str):
        self.success = success
        self.message = message


class IdeInstaller:
    def install(self) -> InstallResult:
        raise NotImplementedError("Subclasses must implement install method")


async def find_vscode_command() -> Optional[str]:
    # 1. 首先检查 PATH 环境变量
    try:
        if sys.platform == 'win32':
            subprocess.run(['where.exe', VSCODE_COMMAND], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        else:
            subprocess.run(['command', '-v', VSCODE_COMMAND], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
        return VSCODE_COMMAND
    except (subprocess.CalledProcessError, FileNotFoundError):
        # 不在 PATH 中，继续检查常见位置
        pass

    # 2. 检查常见安装位置
    locations = []
    platform = sys.platform
    home_dir = os.path.expanduser('~')

    if platform == 'darwin':
        # macOS
        locations.extend([
            '/Applications/Visual Studio Code.app/Contents/Resources/app/bin/code',
            os.path.join(home_dir, 'Library/Application Support/Code/bin/code'),
        ])
    elif platform == 'linux':
        # Linux
        locations.extend([
            '/usr/share/code/bin/code',
            '/snap/bin/code',
            os.path.join(home_dir, '.local/share/code/bin/code'),
        ])
    elif platform == 'win32':
        # Windows
        program_files = os.environ.get('ProgramFiles', 'C:\\Program Files')
        locations.extend([
            os.path.join(
                program_files,
                'Microsoft VS Code',
                'bin',
                'code.cmd',
            ),
            os.path.join(
                home_dir,
                'AppData',
                'Local',
                'Programs',
                'Microsoft VS Code',
                'bin',
                'code.cmd',
            ),
        ])

    for location in locations:
        if os.path.exists(location):
            return location

    return None


class VsCodeInstaller(IdeInstaller):
    def __init__(self):
        # 在 Python 中，我们不直接存储异步结果，而是在需要时调用异步函数
        self._command_path = None

    async def _get_command_path(self) -> Optional[str]:
        if self._command_path is None:
            self._command_path = await find_vscode_command()
        return self._command_path

    async def install(self) -> InstallResult:
        command_path = await self._get_command_path()
        if not command_path:
            return InstallResult(
                success=False,
                message="VS Code CLI not found. Please ensure 'code' is in your system's PATH. For help, see https://code.visualstudio.com/docs/configure/command-line#_code-is-not-recognized-as-an-internal-or-external-command. You can also install the companion extension manually from the VS Code marketplace."
            )

        # 获取当前文件所在目录
        bundle_dir = os.path.dirname(os.path.abspath(__file__))
        # VSIX 文件在构建过程中被复制到 bundle 目录
        vsix_files = glob.glob(os.path.join(bundle_dir, '*.vsix'))
        if len(vsix_files) == 0:
            # 如果 VSIX 文件不在 bundle 中，可能是开发环境
            # 从原始包位置查找
            dev_path = os.path.join(
                bundle_dir,  # .../packages/core/dist/src/ide
                '..',  # .../packages/core/dist/src
                '..',  # .../packages/core/dist
                '..',  # .../packages/core
                '..',  # .../packages
                VSCODE_COMPANION_EXTENSION_FOLDER,
                '*.vsix',
            )
            vsix_files = glob.glob(dev_path)
        
        if len(vsix_files) == 0:
            return InstallResult(
                success=False,
                message="Could not find the required VS Code companion extension. Please file a bug via /bug."
            )

        vsix_path = vsix_files[0]
        # 构建安装命令
        if sys.platform == 'win32':
            command = f'"{command_path}" --install-extension "{vsix_path}" --force'
        else:
            command = f'{command_path} --install-extension "{vsix_path}" --force'

        try:
            subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
            return InstallResult(
                success=True,
                message="VS Code companion extension was installed successfully. Please restart your terminal to complete the setup."
            )
        except subprocess.CalledProcessError:
            return InstallResult(
                success=False,
                message="Failed to install VS Code companion extension. Please try installing it manually from the VS Code marketplace."
            )


def get_ide_installer(ide: DetectedIde) -> Optional[IdeInstaller]:
    if ide == DetectedIde.VSCode:
        return VsCodeInstaller()
    return None