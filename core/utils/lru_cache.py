from typing import Dict, TypeVar, Generic, Optional
from collections import OrderedDict

K = TypeVar('K')  # 键的类型变量
V = TypeVar('V')  # 值的类型变量


class LruCache(Generic[K, V]):
    """
    最小最近使用 (LRU) 缓存实现。
    当缓存达到最大容量时，会删除最久未使用的项。
    
    Args:
        max_size (int): 缓存的最大容量
    """
    def __init__(self, max_size: int) -> None:
        self.cache: OrderedDict[K, V] = OrderedDict()
        self.max_size = max_size

    def get(self, key: K) -> Optional[V]:
        """
        获取缓存中的值，并将其标记为最近使用。
        
        Args:
            key: 要获取的值的键
        
        Returns:
            与键关联的值，如果键不存在则返回 None
        """
        if key in self.cache:
            # 移动到末尾以标记为最近使用
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        return None

    def set(self, key: K, value: V) -> None:
        """
        设置缓存中的值，如果达到最大容量则删除最久未使用的项。
        
        Args:
            key: 要设置的值的键
            value: 要存储的值
        """
        if key in self.cache:
            # 如果键已存在，先删除
            self.cache.pop(key)
        elif len(self.cache) >= self.max_size:
            # 如果达到最大容量，删除最久未使用的项
            self.cache.popitem(last=False)
        # 添加新项到末尾（最近使用）
        self.cache[key] = value

    def clear(self) -> None:
        """清空缓存"""
        self.cache.clear()