import os
import pathlib
import asyncio
from typing import List, Set, Optional, Dict, Any
from ..services.fileDiscoveryService import FileDiscoveryService
from ..config.config import FileFilteringOptions

# 简单控制台日志记录器
logger = {
    'debug': lambda *args: print(f"[DEBUG] [BfsFileSearch] {' '.join(map(str, args))}")
}

class BfsFileSearchOptions:
    def __init__(self,
                 file_name: str,
                 ignore_dirs: Optional[List[str]] = None,
                 max_dirs: int = float('inf'),
                 debug: bool = False,
                 file_service: Optional[FileDiscoveryService] = None,
                 file_filtering_options: Optional[FileFilteringOptions] = None):
        self.file_name = file_name
        self.ignore_dirs = ignore_dirs or []
        self.max_dirs = max_dirs
        self.debug = debug
        self.file_service = file_service
        self.file_filtering_options = file_filtering_options


async def bfs_file_search(
    root_dir: str,
    options: BfsFileSearchOptions
) -> List[str]:
    """
    在目录结构中执行广度优先搜索以查找特定文件。

    Args:
        root_dir: 开始搜索的目录。
        options: 搜索配置。

    Returns:
        找到文件的路径数组。
    """
    file_name = options.file_name
    ignore_dirs = options.ignore_dirs
    max_dirs = options.max_dirs
    debug = options.debug
    file_service = options.file_service

    found_files: List[str] = []
    queue: List[str] = [root_dir]
    visited: Set[str] = set()
    scanned_dir_count = 0
    queue_head = 0  # 基于指针的队列头，避免昂贵的切片操作

    # 将 ignore_dirs 数组转换为 Set 以提高查找性能
    ignore_dirs_set = set(ignore_dirs)

    # 并行处理目录的批次大小
    PARALLEL_BATCH_SIZE = 15

    while queue_head < len(queue) and scanned_dir_count < max_dirs:
        # 填充批次，最多到所需大小
        batch_size = min(PARALLEL_BATCH_SIZE, max_dirs - scanned_dir_count)
        current_batch = []
        while len(current_batch) < batch_size and queue_head < len(queue):
            current_dir = queue[queue_head]
            queue_head += 1
            if current_dir not in visited:
                visited.add(current_dir)
                current_batch.append(current_dir)
        scanned_dir_count += len(current_batch)

        if not current_batch:
            continue

        if debug:
            logger['debug'](
                f"Scanning [{scanned_dir_count}/{max_dirs}]: batch of {len(current_batch)}"
            )

        # 并行读取目录
        read_tasks = []
        for current_dir in current_batch:
            async def read_dir(dir_path: str) -> Dict[str, Any]:
                try:
                    entries = []
                    # 使用 pathlib 列出目录内容
                    for entry in pathlib.Path(dir_path).iterdir():
                        entries.append({
                            'name': entry.name,
                            'is_dir': entry.is_dir(),
                            'is_file': entry.is_file(),
                            'path': str(entry)
                        })
                    return {'current_dir': dir_path, 'entries': entries}
                except Exception as e:
                    # 警告用户无法读取目录
                    message = str(e) or 'Unknown error'
                    print(f"[WARN] Skipping unreadable directory: {dir_path} ({message})")
                    if debug:
                        logger['debug'](f"Full error for {dir_path}:", e)
                    return {'current_dir': dir_path, 'entries': []}

            read_tasks.append(read_dir(current_dir))

        results = await asyncio.gather(*read_tasks)

        for result in results:
            current_dir = result['current_dir']
            entries = result['entries']

            for entry in entries:
                full_path = entry['path']
                # 检查是否应该忽略此文件
                if file_service and file_service.should_ignore_file(
                    full_path,
                    {
                        'respectGitIgnore': options.file_filtering_options.respectGitIgnore
                            if options.file_filtering_options else False,
                        'respectGeminiIgnore': options.file_filtering_options.respectGeminiIgnore
                            if options.file_filtering_options else False
                    }
                ):
                    continue

                if entry['is_dir']:
                    if entry['name'] not in ignore_dirs_set:
                        queue.append(full_path)
                elif entry['is_file'] and entry['name'] == file_name:
                    found_files.append(full_path)

    return found_files