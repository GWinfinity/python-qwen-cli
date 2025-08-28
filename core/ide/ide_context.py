from typing import Dict, List, Optional, Callable, Set, Any
from dataclasses import dataclass, field
from pydantic import BaseModel


class File(BaseModel):
    """表示来自IDE的文件上下文。"""
    path: str
    timestamp: int
    is_active: Optional[bool] = None
    selected_text: Optional[str] = None
    cursor: Optional[Dict[str, int]] = None


class WorkspaceState(BaseModel):
    """表示IDE的工作区状态。"""
    open_files: Optional[List[File]] = None


class IdeContext(BaseModel):
    """表示IDE的上下文信息。"""
    workspace_state: Optional[WorkspaceState] = None


class IdeContextNotification(BaseModel):
    """表示来自IDE的'ide/contextUpdate'通知。"""
    method: str = "ide/contextUpdate"
    params: IdeContext


# 定义订阅者类型
IdeContextSubscriber = Callable[[Optional[IdeContext]], None]


class IdeContextStore:
    """
    管理IDE上下文的存储类。
    替代TypeScript中的工厂函数，实现状态管理和订阅功能。
    """
    def __init__(self):
        """初始化IDE上下文存储。"""
        self._ide_context_state: Optional[IdeContext] = None
        self._subscribers: Set[IdeContextSubscriber] = set()
    
    def _notify_subscribers(self) -> None:
        """通知所有注册的订阅者关于当前的IDE上下文。"""
        for subscriber in self._subscribers:
            subscriber(self._ide_context_state)
    
    def set_ide_context(self, new_ide_context: IdeContext) -> None:
        """
        设置IDE上下文并通知所有注册的订阅者。
        
        Args:
            new_ide_context: 来自IDE的新上下文
        """
        self._ide_context_state = new_ide_context
        self._notify_subscribers()
    
    def clear_ide_context(self) -> None:
        """清除IDE上下文并通知所有注册的订阅者。"""
        self._ide_context_state = None
        self._notify_subscribers()
    
    def get_ide_context(self) -> Optional[IdeContext]:
        """
        获取当前的IDE上下文。
        
        Returns:
            如果有活动文件，则返回IdeContext对象；否则返回None
        """
        return self._ide_context_state
    
    def subscribe_to_ide_context(self, subscriber: IdeContextSubscriber) -> Callable[[], None]:
        """
        订阅IDE上下文的变化。
        
        当IDE上下文变化时，提供的subscriber函数将被调用。
        注意：订阅时不会立即使用当前值调用订阅者。
        
        Args:
            subscriber: 当IDE上下文变化时要调用的函数
            
        Returns:
            一个函数，调用它可以取消订阅
        """
        self._subscribers.add(subscriber)
        
        def unsubscribe() -> None:
            self._subscribers.remove(subscriber)
        
        return unsubscribe


def create_ide_context_store() -> IdeContextStore:
    """
    创建一个新的IDE上下文管理存储。
    这个工厂函数封装了状态和逻辑，允许创建隔离的实例，这在测试中特别有用。
    
    Returns:
        一个带有与IDE上下文交互的方法的对象
    """
    return IdeContextStore()


# 应用程序的默认共享IDE上下文存储实例\ide_context = create_ide_context_store()