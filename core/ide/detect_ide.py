from enum import Enum
import os
from typing import Optional, Never


class DetectedIde(Enum):
    VSCode = 'vscode'


def get_ide_display_name(ide: DetectedIde) -> str:
    if ide == DetectedIde.VSCode:
        return 'VS Code'
    
    # 在 Python 中，我们通过类型提示和运行时检查来模拟 TypeScript 的 exhaustive check
    # 这确保了如果有新的 IDE 添加到枚举中，我们会得到运行时错误
    exhaustive_check: Never = ide
    return exhaustive_check


def detect_ide() -> Optional[DetectedIde]:
    if os.environ.get('TERM_PROGRAM') == 'vscode':
        return DetectedIde.VSCode
    return None