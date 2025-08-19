import subprocess
import os
import platform
from typing import Optional, Union, Dict
import chardet

# 缓存系统编码以避免重复检测
# 使用 None 表示"尚未检查"，而不是 null 表示"检查但失败"
cached_system_encoding: Optional[Union[str, None]] = None


def reset_encoding_cache() -> None:
    """
    重置编码缓存 - 用于测试
    """
    global cached_system_encoding
    cached_system_encoding = None


def get_cached_encoding_for_buffer(buffer: bytes) -> str:
    """
    返回系统编码，缓存结果以避免重复系统调用。
    如果系统编码检测失败，则从提供的缓冲区中检测。
    注意：只有系统编码被缓存 - 基于缓冲区的检测对每个缓冲区运行一次，
    因为不同的缓冲区可能有不同的编码。

    参数:
        buffer: 如果系统检测失败，用于检测编码的缓冲区

    返回:
        检测到的编码
    """
    global cached_system_encoding
    # 缓存系统编码检测，因为它是系统范围的
    if cached_system_encoding is None:
        cached_system_encoding = get_system_encoding()

    # 如果我们有缓存的系统编码，则使用它
    if cached_system_encoding:
        return cached_system_encoding

    # 否则，从这个特定的缓冲区检测（不缓存此结果）
    return detect_encoding_from_buffer(buffer) or 'utf-8'


def get_system_encoding() -> Optional[str]:
    """
    基于平台检测系统编码。
    对于 Windows，它使用 'chcp' 命令获取当前代码页。
    对于类 Unix 系统，它检查环境变量如 LC_ALL、LC_CTYPE 和 LANG。
    如果未设置这些，它尝试运行 'locale charmap' 来获取编码。
    如果检测失败，它返回 None。

    返回:
        系统编码字符串，如果检测失败则返回 None
    """
    # Windows
    if platform.system() == 'Windows':
        try:
            result = subprocess.run(
                ['chcp'],
                capture_output=True,
                text=True,
                check=True
            )
            output = result.stdout
            match = output.match(r':\s*(\d+)')
            if match:
                code_page = int(match.group(1))
                if not isinstance(code_page, float):  # 检查是否为数字
                    return windows_code_page_to_encoding(code_page)
        except subprocess.CalledProcessError as e:
            print(f"使用 'chcp' 命令获取 Windows 代码页失败: {e.stderr}. 将尝试从命令输出检测编码。")
        except Exception as e:
            print(f"无法解析 'chcp' 输出: {str(e)}.")
        return None

    # 类 Unix
    # 使用环境变量 LC_ALL、LC_CTYPE 和 LANG 来确定系统编码。
    # 然而，这些环境变量可能并不总是设置或准确。处理这些变量都未设置的情况。
    env = os.environ
    locale = env.get('LC_ALL') or env.get('LC_CTYPE') or env.get('LANG') or ''

    # 当环境变量缺失时，回退到直接查询系统
    if not locale:
        try:
            result = subprocess.run(
                ['locale', 'charmap'],
                capture_output=True,
                text=True,
                check=True
            )
            locale = result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            print('无法获取 locale charmap。')
            return None

    match = locale.match(r'\.(.+)')  # 例如，"en_US.UTF-8"
    if match and match.group(1):
        return match.group(1).lower()

    # 处理 locale charmap 只返回编码名称的情况（例如，"UTF-8"）
    if locale and '.' not in locale:
        return locale.lower()

    return None


def windows_code_page_to_encoding(cp: int) -> Optional[str]:
    """
    将 Windows 代码页编号转换为相应的编码名称。

    参数:
        cp: Windows 代码页编号（例如，437、850 等）

    返回:
        相应的编码名称字符串，如果没有映射则返回 None
    """
    # 最常见的映射；根据需要扩展
    code_page_map: Dict[int, str] = {
        437: 'cp437',
        850: 'cp850',
        852: 'cp852',
        866: 'cp866',
        874: 'windows-874',
        932: 'shift_jis',
        936: 'gb2312',
        949: 'euc-kr',
        950: 'big5',
        1200: 'utf-16le',
        1201: 'utf-16be',
        1250: 'windows-1250',
        1251: 'windows-1251',
        1252: 'windows-1252',
        1253: 'windows-1253',
        1254: 'windows-1254',
        1255: 'windows-1255',
        1256: 'windows-1256',
        1257: 'windows-1257',
        1258: 'windows-1258',
        65001: 'utf-8',
    }

    if cp in code_page_map:
        return code_page_map[cp]

    print(f"无法确定 Windows 代码页 {cp} 的编码。")
    return None


def detect_encoding_from_buffer(buffer: bytes) -> Optional[str]:
    """
    尝试使用 chardet 从缓冲区检测编码。
    当系统编码检测失败时，这很有用。
    返回检测到的编码（小写），如果检测失败则返回 None。

    参数:
        buffer: 要分析编码的缓冲区

    返回:
        检测到的编码（小写字符串），如果检测失败则返回 None
    """
    try:
        result = chardet.detect(buffer)
        if result and 'encoding' in result and result['encoding']:
            return result['encoding'].lower()
    except Exception as e:
        print(f"使用 chardet 检测编码失败: {str(e)}")

    return None