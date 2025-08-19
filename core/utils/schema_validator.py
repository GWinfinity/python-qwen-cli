"""
@license
Copyright 2025 Google LLC
SPDX-License-Identifier: Apache-2.0
"""

import jsonschema
from typing import Any, Dict, List, Optional, Union, TypeVar
from google.genai import Schema


class SchemaValidator:
    """
    简单的工具类，用于根据 JSON 模式验证对象
    """

    @staticmethod
    def validate(schema: Optional[Schema], data: Any) -> Optional[str]:
        """
        如果数据符合模式描述（或模式为 None），则返回 None。
        否则，返回描述错误的字符串。

        参数:
            schema: JSON 模式或 None
            data: 要验证的数据

        返回:
            str 或 None: 错误描述或 None（如果验证通过）
        """
        if schema is None:
            return None

        if not isinstance(data, dict):
            return 'params 的值必须是一个对象'

        try:
            # 转换 schema 为 jsonschema 兼容格式
            jsonschema.validate(instance=data, schema=SchemaValidator.to_object_schema(schema))
            return None
        except jsonschema.exceptions.ValidationError as e:
            # 构建友好的错误消息
            return f"参数验证失败: {e.message}"
        except Exception as e:
            return f"验证过程中发生错误: {str(e)}"

    @staticmethod
    def to_object_schema(schema: Schema) -> Dict[str, Any]:
        """
        将 Google GenAI 的 Schema 转换为 jsonschema 兼容的对象。
        这是必要的，因为它将类型表示为枚举（大写值），
        并将 minItems 和 minLength 表示为字符串，而它们应该是数字。

        参数:
            schema: Google GenAI Schema 对象

        返回:
            dict: jsonschema 兼容的模式对象
        """
        new_schema: Dict[str, Any] = {**schema}

        # 递归处理 anyOf
        if 'anyOf' in new_schema and isinstance(new_schema['anyOf'], list):
            new_schema['anyOf'] = [SchemaValidator.to_object_schema(v) for v in new_schema['anyOf']]

        # 递归处理 items
        if 'items' in new_schema:
            new_schema['items'] = SchemaValidator.to_object_schema(new_schema['items'])

        # 递归处理 properties
        if 'properties' in new_schema and isinstance(new_schema['properties'], dict):
            new_properties: Dict[str, Any] = {}
            for key, value in new_schema['properties'].items():
                new_properties[key] = SchemaValidator.to_object_schema(value)
            new_schema['properties'] = new_properties

        # 转换类型为小写
        if 'type' in new_schema:
            new_schema['type'] = str(new_schema['type']).lower()

        # 转换 minItems 为数字
        if 'minItems' in new_schema:
            new_schema['minItems'] = int(new_schema['minItems'])

        # 转换 minLength 为数字
        if 'minLength' in new_schema:
            new_schema['minLength'] = int(new_schema['minLength'])

        return new_schema