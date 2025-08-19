"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import json
from typing import Any, Optional, Union


def safe_json_stringify(
    obj: Any,
    space: Optional[Union[str, int]] = None
) -> str:
    """
    安全地将对象字符串化为 JSON，通过将循环引用替换为 [Circular] 来处理它们。

    参数:
        obj: 要字符串化的对象
        space: 可选的格式化空格参数（默认为无格式化）

    返回:
        循环引用被替换为 [Circular] 的 JSON 字符串
    """
    seen = set()

    def replacer(key: str, value: Any) -> Any:
        # 检查是否为对象且非空
        if isinstance(value, (dict, list)) and value is not None:
            # 使用 id 作为唯一标识符，因为对象可能不可哈希
            obj_id = id(value)
            if obj_id in seen:
                return "[Circular]"
            seen.add(obj_id)
        return value

    # 自定义 JSON 编码器，用于处理循环引用
    class SafeEncoder(json.JSONEncoder):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.seen = set()

        def default(self, o: Any) -> Any:
            # 处理自定义对象
            if hasattr(o, '__dict__'):
                obj_id = id(o)
                if obj_id in self.seen:
                    return "[Circular]"
                self.seen.add(obj_id)
                return o.__dict__
            # 处理其他不可序列化的类型
            return str(o)

    try:
        # 尝试使用标准 JSON 序列化
        return json.dumps(obj, indent=space, cls=SafeEncoder)
    except TypeError:
        # 如果失败，使用更严格的方式
        return json.dumps(obj, default=lambda x: str(x), indent=space)