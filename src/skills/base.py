from abc import ABC, abstractmethod
from typing import Type, Any, Dict
from pydantic import BaseModel

class BaseSkill(ABC):
    """
    技能抽象基类。所有原子剪辑技能都应继承此类，
    并提供其参数的 Pydantic 模型，以实现自动 Schema 导出和参数校验。
    """
    name: str = ""
    description: str = ""
    input_model: Type[BaseModel] = BaseModel

    def get_schema(self) -> Dict[str, Any]:
        """
        获取该技能的输入参数 JSON Schema。
        上层 Agent 可以利用此 Schema 理解如何调用此技能。
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.input_model.model_json_schema()
        }

    def execute(self, params_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行入口，负责参数的反序列化与校验，并调用具体的 run 方法。
        """
        # 校验参数是否符合 input_model 定义
        params = self.input_model(**params_dict)
        return self.run(params)

    @abstractmethod
    def run(self, params: Any) -> Dict[str, Any]:
        """
        技能具体的执行逻辑，由子类实现。
        """
        pass
