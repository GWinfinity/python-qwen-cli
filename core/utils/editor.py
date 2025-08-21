import os
import platform
import subprocess
from typing import List, Dict, Tuple, Optional, Union, Any


EditorType = Union[
    'vscode',
    'vscodium',
    'windsurf',
    'cursor',
    'vim',
    'neovim',
    'zed',
    'emacs'
]


class DiffCommand:
    def __init__(self, command: str, args: List[str]):
        self.command = command
        self.args = args


def is_valid_editor_type(editor: str) -> bool:
    return editor in [
        'vscode',
        'vscodium',
        'windsurf',
        'cursor',
        'vim',
        'neovim',
        'zed',
        'emacs'
    ]


def command_exists(cmd: str) -> bool:
    try:
        if platform.system() == 'Windows':
            subprocess.run(
                ['where.exe', cmd],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
        else:
            subprocess.run(
                ['command', '-v', cmd],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=True
            )
        return True
    except (subprocess.SubprocessError, FileNotFoundError):
        return False


# 不同平台上的编辑器命令配置
editor_commands: Dict[EditorType, Dict[str, List[str]]] = {
    'vscode': {'win32': ['code.cmd'], 'default': ['code']},
    'vscodium': {'win32': ['codium.cmd'], 'default': ['codium']},
    'windsurf': {'win32': ['windsurf'], 'default': ['windsurf']},
    'cursor': {'win32': ['cursor'], 'default': ['cursor']},
    'vim': {'win32': ['vim'], 'default': ['vim']},
    'neovim': {'win32': ['nvim'], 'default': ['nvim']},
    'zed': {'win32': ['zed'], 'default': ['zed', 'zeditor']},
    'emacs': {'win32': ['emacs.exe'], 'default': ['emacs']},
}


def check_has_editor_type(editor: EditorType) -> bool:
    command_config = editor_commands[editor]
    commands = command_config['win32'] if platform.system() == 'Windows' else command_config['default']
    return any(command_exists(cmd) for cmd in commands)


def allow_editor_type_in_sandbox(editor: EditorType) -> bool:
    not_using_sandbox = not os.environ.get('SANDBOX')
    if editor in ['vscode', 'vscodium', 'windsurf', 'cursor', 'zed']:
        return not_using_sandbox
    # 对于基于终端的编辑器如 vim 和 emacs，允许在沙箱中使用
    return True


def is_editor_available(editor: Optional[str]) -> bool:
    if editor and is_valid_editor_type(editor):
        return check_has_editor_type(editor) and allow_editor_type_in_sandbox(editor)
    return False


def get_diff_command(
    old_path: str,
    new_path: str,
    editor: EditorType
) -> Optional[DiffCommand]:
    if not is_valid_editor_type(editor):
        return None
    
    command_config = editor_commands[editor]
    commands = command_config['win32'] if platform.system() == 'Windows' else command_config['default']
    
    # 找到第一个可用的命令
    command = None
    for cmd in commands:
        if command_exists(cmd):
            command = cmd
            break
    if not command:
        command = commands[-1]  # 默认使用最后一个命令

    if editor in ['vscode', 'vscodium', 'windsurf', 'cursor', 'zed']:
        return DiffCommand(command, ['--wait', '--diff', old_path, new_path])
    elif editor in ['vim', 'neovim']:
        args = [
            '-d',
            '-i', 'NONE',  # 跳过 viminfo 文件以避免 E138 错误
            '-c', 'wincmd h | set readonly | wincmd l',  # 左窗口只读，右窗口可编辑
            '-c', 'highlight DiffAdd cterm=bold ctermbg=22 guibg=#005f00 | highlight DiffChange cterm=bold ctermbg=24 guibg=#005f87 | highlight DiffText ctermbg=21 guibg=#0000af | highlight DiffDelete ctermbg=52 guibg=#5f0000',
            '-c', 'set showtabline=2 | set tabline=[Instructions]\ :wqa(save\ &\ quit)\ \|\ i/esc(toggle\ edit\ mode)',
            '-c', 'wincmd h | setlocal statusline=OLD\ FILE',
            '-c', 'wincmd l | setlocal statusline=%#StatusBold#NEW\ FILE\ :wqa(save\ &\ quit)\ \|\ i/esc(toggle\ edit\ mode)',
            '-c', 'autocmd WinClosed * wqa',  # 当一个窗口关闭时自动关闭所有窗口
            old_path,
            new_path
        ]
        return DiffCommand(command, args)
    elif editor == 'emacs':
        return DiffCommand('emacs', ['--eval', f'(ediff 