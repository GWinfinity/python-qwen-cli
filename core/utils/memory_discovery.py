#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import os
import pathlib
from typing import List, Set, Dict, Optional, Union, Tuple

# 假设这些是我们需要导入的自定义模块
# 注意：在实际实现中，需要确保这些模块也已转换为Python
from .bfs_file_search import bfs_file_search
from ..tools.memory_tool import GEMINI_CONFIG_DIR, get_all_gemini_md_filenames
from ..services.file_discovery_service import FileDiscoveryService
from .memory_import_processor import process_imports
from ..config.config import DEFAULT_MEMORY_FILE_FILTERING_OPTIONS, FileFilteringOptions


# 简单的控制台日志记录器
class Logger:
    @staticmethod
    def debug(*args):
        print(f"[DEBUG] [MemoryDiscovery] {' '.join(map(str, args))}")

    @staticmethod
    def warn(*args):
        print(f"[WARN] [MemoryDiscovery] {' '.join(map(str, args))}")

    @staticmethod
    def error(*args):
        print(f"[ERROR] [MemoryDiscovery] {' '.join(map(str, args))}")

logger = Logger()


typing.Dict[str, Union[str, None]]
class GeminiFileContent(TypedDict):
    file_path: str
    content: Optional[str]


async def find_project_root(start_dir: str) -> Optional[str]:
    current_dir = os.path.resolve(start_dir)
    while True:
        git_path = os.path.join(current_dir, '.git')
        try:
            if os.path.isdir(git_path):
                return current_dir
        except Exception as error:
            # 处理非ENOENT错误
            is_enoent = hasattr(error, 'errno') and error.errno == 2  # ENOENT
            is_test_env = os.environ.get('NODE_ENV') == 'test' or os.environ.get('VITEST')

            if not is_enoent and not is_test_env:
                logger.warn(f"Error checking for .git directory at {git_path}: {str(error)}")

        parent_dir = os.path.dirname(current_dir)
        if parent_dir == current_dir:
            return None
        current_dir = parent_dir


async def get_gemini_md_file_paths_internal(
    current_working_directory: str,
    user_home_path: str,
    debug_mode: bool,
    file_service: FileDiscoveryService,
    extension_context_file_paths: List[str] = [],
    file_filtering_options: FileFilteringOptions = DEFAULT_MEMORY_FILE_FILTERING_OPTIONS,
    max_dirs: int = 200,
) -> List[str]:
    all_paths = set()
    gemini_md_filenames = get_all_gemini_md_filenames()

    for gemini_md_filename in gemini_md_filenames:
        resolved_home = os.path.resolve(user_home_path)
        global_memory_path = os.path.join(
            resolved_home,
            GEMINI_CONFIG_DIR,
            gemini_md_filename,
        )

        # 查找全局文件
        try:
            if os.access(global_memory_path, os.R_OK):
                all_paths.add(global_memory_path)
                if debug_mode:
                    logger.debug(f"Found readable global {gemini_md_filename}: {global_memory_path}")
        except Exception as e:
            pass

        # 仅当提供了有效的当前工作目录时才执行工作区搜索
        if current_working_directory:
            resolved_cwd = os.path.resolve(current_working_directory)
            if debug_mode:
                logger.debug(f"Searching for {gemini_md_filename} starting from CWD: {resolved_cwd}")

            project_root = await find_project_root(resolved_cwd)
            if debug_mode:
                logger.debug(f"Determined project root: {project_root or 'None'}")

            upward_paths = []
            current_dir = resolved_cwd
            ultimate_stop_dir = os.path.dirname(project_root) if project_root else os.path.dirname(resolved_home)

            while current_dir and current_dir != os.path.dirname(current_dir):
                if current_dir == os.path.join(resolved_home, GEMINI_CONFIG_DIR):
                    break

                potential_path = os.path.join(current_dir, gemini_md_filename)
                try:
                    if os.access(potential_path, os.R_OK) and potential_path != global_memory_path:
                        upward_paths.insert(0, potential_path)
                except Exception as e:
                    pass

                if current_dir == ultimate_stop_dir:
                    break

                current_dir = os.path.dirname(current_dir)

            for p in upward_paths:
                all_paths.add(p)

            merged_options = {
                **DEFAULT_MEMORY_FILE_FILTERING_OPTIONS,
                **file_filtering_options,
            }

            downward_paths = await bfs_file_search(
                resolved_cwd,
                {
                    'fileName': gemini_md_filename,
                    'maxDirs': max_dirs,
                    'debug': debug_mode,
                    'fileService': file_service,
                    'fileFilteringOptions': merged_options,
                }
            )
            downward_paths.sort()
            for d_path in downward_paths:
                all_paths.add(d_path)

    # 添加扩展上下文文件路径
    for extension_path in extension_context_file_paths:
        all_paths.add(extension_path)

    final_paths = list(all_paths)

    if debug_mode:
        logger.debug(f"Final ordered {get_all_gemini_md_filenames()} paths to read: {final_paths}")

    return final_paths


async def read_gemini_md_files(
    file_paths: List[str],
    debug_mode: bool,
    import_format: str = 'tree',
) -> List[GeminiFileContent]:
    results = []
    for file_path in file_paths:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 处理内容中的导入
            processed_result = await process_imports(
                content,
                os.path.dirname(file_path),
                debug_mode,
                import_format=import_format,
            )

            results.append({'file_path': file_path, 'content': processed_result['content']})
            if debug_mode:
                logger.debug(f"Successfully read and processed imports: {file_path} (Length: {len(processed_result['content'])})")
        except Exception as error:
            is_test_env = os.environ.get('NODE_ENV') == 'test' or os.environ.get('VITEST')
            if not is_test_env:
                logger.warn(f"Warning: Could not read {get_all_gemini_md_filenames()} file at {file_path}. Error: {str(error)}")
            results.append({'file_path': file_path, 'content': None})
            if debug_mode:
                logger.debug(f"Failed to read: {file_path}")

    return results


def concatenate_instructions(
    instruction_contents: List[GeminiFileContent],
    current_working_directory_for_display: str,
) -> str:
    blocks = []
    for item in instruction_contents:
        if item['content'] is None:
            continue

        trimmed_content = item['content'].strip()
        if not trimmed_content:
            continue

        file_path = item['file_path']
        if os.path.isabs(file_path):
            display_path = os.path.relpath(file_path, current_working_directory_for_display)
        else:
            display_path = file_path

        blocks.append(f"--- Context from: {display_path} ---{trimmed_content}--- End of Context from: {display_path} ---")

    return '\n\n'.join(blocks)


async def load_server_hierarchical_memory(
    current_working_directory: str,
    debug_mode: bool,
    file_service: FileDiscoveryService,
    extension_context_file_paths: List[str] = [],
    import_format: str = 'tree',
    file_filtering_options: Optional[FileFilteringOptions] = None,
    max_dirs: int = 200,
) -> Dict[str, Union[str, int]]:
    if debug_mode:
        logger.debug(f"Loading server hierarchical memory for CWD: {current_working_directory} (importFormat: {import_format})")

    # 获取用户主目录
    user_home_path = os.path.expanduser('~')

    file_paths = await get_gemini_md_file_paths_internal(
        current_working_directory,
        user_home_path,
        debug_mode,
        file_service,
        extension_context_file_paths,
        file_filtering_options or DEFAULT_MEMORY_FILE_FILTERING_OPTIONS,
        max_dirs,
    )

    if not file_paths:
        if debug_mode:
            logger.debug('No QWEN.md files found in hierarchy.')
        return {'memory_content': '', 'file_count': 0}

    contents_with_paths = await read_gemini_md_files(
        file_paths,
        debug_mode,
        import_format,
    )

    # 合并指令内容
    combined_instructions = concatenate_instructions(
        contents_with_paths,
        current_working_directory,
    )

    if debug_mode:
        logger.debug(f"Combined instructions length: {len(combined_instructions)}")
        if combined_instructions:
            snippet = combined_instructions[:500] + ('...' if len(combined_instructions) > 500 else '')
            logger.debug(f"Combined instructions (snippet): {snippet}")

    return {
        'memory_content': combined_instructions,
        'file_count': len(file_paths)
    }