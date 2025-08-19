import os
import uuid
from pathlib import Path

# 假设 GEMINI_DIR 是从 paths 模块导入的常量
# 由于原代码中导入了 ./paths.js，这里假设它是一个相对路径常量
GEMINI_DIR = '.gemini'  # 实际值可能需要根据项目配置调整


def ensure_gemini_dir_exists(gemini_dir: str) -> None:
    """确保 Gemini 目录存在

    Args:
        gemini_dir: Gemini 目录路径
    """
    if not os.path.exists(gemini_dir):
        os.makedirs(gemini_dir, exist_ok=True)


def read_installation_id_from_file(installation_id_file: str) -> str or None:
    """从文件读取安装 ID

    Args:
        installation_id_file: 安装 ID 文件路径

    Returns:
        安装 ID 字符串，如果文件不存在或为空则返回 None
    """
    if os.path.exists(installation_id_file):
        with open(installation_id_file, 'r', encoding='utf-8') as f:
            installation_id = f.read().strip()
            return installation_id if installation_id else None
    return None


def write_installation_id_to_file(installation_id_file: str, installation_id: str) -> None:
    """将安装 ID 写入文件

    Args:
        installation_id_file: 安装 ID 文件路径
        installation_id: 要写入的安装 ID
    """
    with open(installation_id_file, 'w', encoding='utf-8') as f:
        f.write(installation_id)


def get_installation_id() -> str:
    """获取安装 ID，如果不存在则创建

    这个 ID 用于唯一标识用户安装。

    Returns:
        用户的 UUID 字符串
    """
    try:
        home_dir = os.path.expanduser('~')
        gemini_dir = os.path.join(home_dir, GEMINI_DIR)
        installation_id_file = os.path.join(gemini_dir, 'installation_id')

        ensure_gemini_dir_exists(gemini_dir)
        installation_id = read_installation_id_from_file(installation_id_file)

        if not installation_id:
            installation_id = str(uuid.uuid4())
            write_installation_id_to_file(installation_id_file, installation_id)

        return installation_id
    except Exception as error:
        print(f'Error accessing installation ID file, generating ephemeral ID: {error}')
        return '123456789'