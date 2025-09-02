from typing import Union, List, Dict, Any
from core.core.turn import PartListUnion
from core.utils.part_utils import part_to_string


# 类型别名，相当于TypeScript中的type定义
gemini_code_request = PartListUnion


def part_list_union_to_string(value: PartListUnion) -> str:
    """将PartListUnion转换为字符串
    
    Args:
        value: 要转换的PartListUnion值
        
    Returns:
        转换后的字符串表示
    """
    return part_to_string(value, {"verbose": True})


# 为了与TypeScript的导出风格保持一致，可以使用__all__指定公共API
__all__ = ["gemini_code_request", "part_list_union_to_string"]