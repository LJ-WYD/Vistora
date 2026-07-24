import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from openai import OpenAI

# 自动加载项目根目录下的 .env 配置文件
# 无论我们在何处启动 Python 程序，该方法均能自动加载对应配置
load_dotenv()

class LLMClient:
    """
    基于 OpenAI 兼容协议的大模型底层通信客户端。
    负责与 Ollama、vLLM、LM Studio 或云端大模型接口通信。
    """
    def __init__(self):
        # 默认获取环境变量，若获取失败则使用备用默认值
        self.api_key = os.getenv("LLM_API_KEY", "your_api_key_here")
        self.base_url = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
        self.model = os.getenv("LLM_MODEL", "gpt-4o")

        # 实例化标准 OpenAI 客户端
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )

    def chat(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Any:
        """
        向大模型发送对话上下文。如果提供了 tools 列表，将触发 Tool Calling 机制。
        """
        try:
            params = {
                "model": self.model,
                "messages": messages,
            }
            # 如果存在注册的原子技能工具
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"

            # 发送 API 请求
            response = self.client.chat.completions.create(**params)
            return response
        except Exception as e:
            # 输出清晰的中文报错信息，便于用户排查网络或配置问题
            print(f"【LLM 异常】与大模型交互失败！请检查根目录下 .env 配置文件是否正确。错误详情: {e}")
            raise e
