from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Callable, TypeVar
from google.genai import FunctionDeclaration, PartListUnion, Schema
from .tools.tool_error import ToolErrorType


# 假设这些类型在 Python 中有对应的实现
# 这里我们定义一些模拟的类型以确保代码结构完整

# 定义 Icon 枚举
class Icon(Enum):
    FILE_SEARCH = "fileSearch"
    FOLDER = "folder"
    GLOBE = "globe"
    HAMMER = "hammer"
    LIGHT_BULB = "lightBulb"
    PENCIL = "pencil"
    REGEX = "regex"
    TERMINAL = "terminal"

# 定义 ToolConfirmationOutcome 枚举
class ToolConfirmationOutcome(Enum):
    PROCEED_ONCE = "proceed_once"
    PROCEED_ALWAYS = "proceed_always"
    PROCEED_ALWAYS_SERVER = "proceed_always_server"
    PROCEED_ALWAYS_TOOL = "proceed_always_tool"
    MODIFY_WITH_EDITOR = "modify_with_editor"
    CANCEL = "cancel"

# 定义 ToolLocation 接口
class ToolLocation:
    def __init__(self, path: str, line: Optional[int] = None):
        self.path = path
        self.line = line

# 定义 FileDiff 接口
class FileDiff:
    def __init__(
        self,
        file_diff: str,
        file_name: str,
        original_content: Optional[str],
        new_content: str
    ):
        self.file_diff = file_diff
        self.file_name = file_name
        self.original_content = original_content
        self.new_content = new_content

# 定义 ToolResultDisplay 类型
ToolResultDisplay = Union[str, FileDiff]

# 定义 ToolResult 接口
class ToolResult:
    def __init__(
        self,
        llm_content: PartListUnion,
        return_display: ToolResultDisplay,
        summary: Optional[str] = None,
        error: Optional[Dict[str, ToolErrorType]] = None
    ):
        self.summary = summary
        self.llm_content = llm_content
        self.return_display = return_display
        self.error = error

# 定义 ToolConfirmationPayload 接口
class ToolConfirmationPayload:
    def __init__(self, new_content: str):
        self.new_content = new_content

# 定义各种确认详情类
class ToolEditConfirmationDetails:
    def __init__(
        self,
        title: str,
        on_confirm: Callable,
        file_name: str,
        file_diff: str,
        original_content: Optional[str],
        new_content: str,
        is_modifying: Optional[bool] = None
    ):
        self.type = "edit"
        self.title = title
        self.on_confirm = on_confirm
        self.file_name = file_name
        self.file_diff = file_diff
        self.original_content = original_content
        self.new_content = new_content
        self.is_modifying = is_modifying

class ToolExecuteConfirmationDetails:
    def __init__(
        self,
        title: str,
        on_confirm: Callable,
        command: str,
        root_command: str
    ):
        self.type = "exec"
        self.title = title
        self.on_confirm = on_confirm
        self.command = command
        self.root_command = root_command

class ToolMcpConfirmationDetails:
    def __init__(
        self,
        title: str,
        server_name: str,
        tool_name: str,
        tool_display_name: str,
        on_confirm: Callable
    ):
        self.type = "mcp"
        self.title = title
        self.server_name = server_name
        self.tool_name = tool_name
        self.tool_display_name = tool_display_name
        self.on_confirm = on_confirm

class ToolInfoConfirmationDetails:
    def __init__(
        self,
        title: str,
        on_confirm: Callable,
        prompt: str,
        urls: Optional[List[str]] = None
    ):
        self.type = "info"
        self.title = title
        self.on_confirm = on_confirm
        self.prompt = prompt
        self.urls = urls

# 定义 ToolCallConfirmationDetails 类型
ToolCallConfirmationDetails = Union[
    ToolEditConfirmationDetails,
    ToolExecuteConfirmationDetails,
    ToolMcpConfirmationDetails,
    ToolInfoConfirmationDetails
]

# 定义泛型类型变量
TParams = TypeVar('TParams')
TResult = TypeVar('TResult', bound=ToolResult)

# 定义 Tool 接口对应的抽象基类
class Tool(ABC, Generic[TParams, TResult]):
    @property
    @abstractmethod
    def name(self) -> str:
        pass

    @property
    @abstractmethod
    def display_name(self) -> str:
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        pass

    @property
    @abstractmethod
    def icon(self) -> Icon:
        pass

    @property
    @abstractmethod
    def schema(self) -> FunctionDeclaration:
        pass

    @property
    @abstractmethod
    def is_output_markdown(self) -> bool:
        pass

    @property
    @abstractmethod
    def can_update_output(self) -> bool:
        pass

    @abstractmethod
    def validate_tool_params(self, params: TParams) -> Optional[str]:
        pass

    @abstractmethod
    def get_description(self, params: TParams) -> str:
        pass

    @abstractmethod
    def tool_locations(self, params: TParams) -> List[ToolLocation]:
        pass

    @abstractmethod
    async def should_confirm_execute(
        self,
        params: TParams,
        abort_signal: Any
    ) -> Union[ToolCallConfirmationDetails, bool]:
        pass

    @abstractmethod
    async def execute(
        self,
        params: TParams,
        signal: Any,
        update_output: Optional[Callable[[str], None]] = None
    ) -> TResult:
        pass

# 实现 BaseTool 抽象类
class BaseTool(Tool[TParams, TResult]):
    def __init__(
        self,
        name: str,
        display_name: str,
        description: str,
        icon: Icon,
        parameter_schema: Schema,
        is_output_markdown: bool = True,
        can_update_output: bool = False
    ):
        self._name = name
        self._display_name = display_name
        self._description = description
        self._icon = icon
        self._parameter_schema = parameter_schema
        self._is_output_markdown = is_output_markdown
        self._can_update_output = can_update_output

    @property
    def name(self) -> str:
        return self._name

    @property
    def display_name(self) -> str:
        return self._display_name

    @property
    def description(self) -> str:
        return self._description

    @property
    def icon(self) -> Icon:
        return self._icon

    @property
    def schema(self) -> FunctionDeclaration:
        return FunctionDeclaration(
            name=self._name,
            description=self._description,
            parameters=self._parameter_schema
        )

    @property
    def is_output_markdown(self) -> bool:
        return self._is_output_markdown

    @property
    def can_update_output(self) -> bool:
        return self._can_update_output

    def validate_tool_params(self, params: TParams) -> Optional[str]:
        # 这是一个占位实现，应该由派生类重写
        return None

    def get_description(self, params: TParams) -> str:
        return str(params)

    async def should_confirm_execute(
        self,
        params: TParams,
        abort_signal: Any
    ) -> Union[ToolCallConfirmationDetails, bool]:
        return False

    def tool_locations(self, params: TParams) -> List[ToolLocation]:
        return []

    @abstractmethod
    async def execute(
        self,
        params: TParams,
        signal: Any,
        update_output: Optional[Callable[[str], None]] = None
    ) -> TResult:
        pass