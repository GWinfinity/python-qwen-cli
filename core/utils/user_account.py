import os
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

# 假设 GEMINI_DIR 和 GOOGLE_ACCOUNTS_FILENAME 从 paths 模块导入
# 在实际使用中，需要确保这些常量已定义
from .paths import GEMINI_DIR, GOOGLE_ACCOUNTS_FILENAME


class UserAccounts:
    def __init__(self, active: Optional[str] = None, old: List[str] = None):
        self.active = active
        self.old = old or []


def get_google_accounts_cache_path() -> str:
    home_dir = os.path.expanduser('~')
    return os.path.join(home_dir, GEMINI_DIR, GOOGLE_ACCOUNTS_FILENAME)


async def read_accounts(file_path: str) -> UserAccounts:
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            return UserAccounts()

        # 异步读取文件
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        if not content.strip():
            return UserAccounts()

        data = json.loads(content)
        return UserAccounts(active=data.get('active'), old=data.get('old', []))
    except json.JSONDecodeError:
        # 文件损坏或不是有效的 JSON，返回空对象
        print('Could not parse accounts file, starting fresh.')
        return UserAccounts()
    except Exception as e:
        print(f'Error reading accounts file: {e}')
        return UserAccounts()


async def cache_google_account(email: str) -> None:
    file_path = get_google_accounts_cache_path()

    # 确保目录存在
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    accounts = await read_accounts(file_path)

    if accounts.active and accounts.active != email:
        if accounts.active not in accounts.old:
            accounts.old.append(accounts.active)

    # 如果新邮箱在旧列表中，将其移除
    accounts.old = [old_email for old_email in accounts.old if old_email != email]

    accounts.active = email

    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({
            'active': accounts.active,
            'old': accounts.old
        }, f, indent=2)


def get_cached_google_account() -> Optional[str]:
    try:
        file_path = get_google_accounts_cache_path()
        if not os.path.exists(file_path):
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        if not content:
            return None

        accounts = json.loads(content)
        return accounts.get('active')
    except Exception as e:
        print(f'Error reading cached Google Account: {e}')
        return None


def get_lifetime_google_accounts() -> int:
    try:
        file_path = get_google_accounts_cache_path()
        if not os.path.exists(file_path):
            return 0

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        if not content:
            return 0

        accounts = json.loads(content)
        count = len(accounts.get('old', []))
        if accounts.get('active'):
            count += 1
        return count
    except Exception as e:
        print(f'Error reading lifetime Google Accounts: {e}')
        return 0


async def clear_cached_google_account() -> None:
    file_path = get_google_accounts_cache_path()
    if not os.path.exists(file_path):
        return

    accounts = await read_accounts(file_path)

    if accounts.active:
        if accounts.active not in accounts.old:
            accounts.old.append(accounts.active)
        accounts.active = None

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({
            'active': accounts.active,
            'old': accounts.old
        }, f, indent=2)