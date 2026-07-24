import json
from typing import Dict, Any, List
from .llm_client import LLMClient
from skills.base import BaseSkill

class OperatorAgent:
    """
    Vistora 操作层 Agent。
    动态读取已注册的原子 Skill，利用 LLM 的 Tool Calling 机制自主规划剪辑步骤并调度物理层执行。
    """
    def __init__(self, skills: Dict[str, BaseSkill]):
        self.skills = skills
        self.llm = LLMClient()
        self.messages: List[Dict[str, Any]] = []

        # 将所有的 Skills 统一映射为符合 OpenAI 规范的 Tools 定义列表
        self.tools_def = []
        for skill in self.skills.values():
            self.tools_def.append({
                "type": "function",
                "function": skill.get_schema()
            })

        # 构建 Agent 的系统级提示词，设定其行为规范与智能人设
        self.system_prompt = (
            "你是 Vistora 视频智能操作系统的大脑助手（Agent）。\n"
            "你可以使用下方的各种视频处理技能（Skills）来帮助用户处理视频剪辑任务。\n"
            "当用户向你下达视频编辑、裁剪、拼接、变速、倒放、延时摄影合成等任务时，"
            "你需要根据当前已注册的 Skills 及其描述和参数定义，自主拆解用户意图，并规划调用这些工具。\n"
            "你可以链式调用多个工具（例如先裁剪，再旋转，最后变速）。\n"
            "如果在执行过程中底层工具返回了报错信息，你应该分析报错并向用户解释原因，或者调整参数重新尝试。\n"
            "注意：在调用参数中涉及输出路径（output_path）或源视频路径（source_path）时，你必须根据上下文给出合理的、不冲突的物理路径。\n"
            "请始终以友好、专业的中文与用户对话。"
        )
        self.messages.append({"role": "system", "content": self.system_prompt})

    def run(self, user_prompt: str) -> str:
        """
        接收用户的口语化剪辑命令，驱动 Tool Calling 循环直至大模型给出最终响应。
        """
        import re
        import os
        
        # --- 元数据上下文注入机制 (Metadata Context Injection) ---
        # 自动探测用户输入中的视频文件，并获取它们的真实物理时长附加给大模型，防止大模型在处理“后XX秒”时瞎猜
        file_paths = re.findall(r'[a-zA-Z]:\\[^\s]+\.(?:MOV|mp4|avi|mkv|mov|MP4|AVI|MKV)', user_prompt, re.IGNORECASE)
        # 支持相对路径或正斜杠
        file_paths.extend(re.findall(r'(?:/|\\|)[^\s]+\.(?:MOV|mp4|avi|mkv|mov|MP4|AVI|MKV)', user_prompt, re.IGNORECASE))
        
        context_str = ""
        for p in set(file_paths):
            if os.path.exists(p):
                try:
                    from moviepy import VideoFileClip
                    clip = VideoFileClip(p)
                    dur = clip.duration
                    clip.close()
                    context_str += f"\n- {p}: 总时长 {dur:.2f} 秒"
                except Exception:
                    pass
                    
        if context_str:
            enriched_prompt = user_prompt + "\n\n【系统自动附加上下文：探测到的视频素材元数据】" + context_str
        else:
            enriched_prompt = user_prompt

        # 记录用户的新指令 (携带可能被丰富过的上下文)
        self.messages.append({"role": "user", "content": enriched_prompt})

        # 循环步数限制，避免大模型因决策分歧陷入无限循环调用
        max_iterations = 10
        for _ in range(max_iterations):
            # 发起 LLM 通信
            response = self.llm.chat(self.messages, tools=self.tools_def)
            message = response.choices[0].message
            
            # 构建合法的 assistant 消息追加到历史中
            model_msg: Dict[str, Any] = {"role": "assistant"}
            if message.content is not None:
                model_msg["content"] = message.content
            if message.tool_calls:
                # 转换格式为标准的 Dict 列表，确保对各种第三方网关/本地 Ollama 的完全兼容性
                tool_calls_list = []
                for tc in message.tool_calls:
                    tool_calls_list.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
                model_msg["tool_calls"] = tool_calls_list
            
            self.messages.append(model_msg)

            # 如果没有工具调用，表明决策已经完成，直接返回 LLM 的回复
            if not message.tool_calls:
                return message.content or ""

            # 处理并发或顺序的 Skill 调用
            print(f"\n[Agent 决策] 大模型规划了 {len(message.tool_calls)} 个剪辑操作步骤：")
            for tool_call in message.tool_calls:
                skill_name = tool_call.function.name
                arguments_str = tool_call.function.arguments
                tool_call_id = tool_call.id

                print(f" -> 运行技能: {skill_name}")
                print(f"    参数定义: {arguments_str}")

                # 验证技能是否注册
                if skill_name not in self.skills:
                    result = {"status": "error", "message": f"系统中未注册名为 {skill_name} 的技能"}
                else:
                    skill = self.skills[skill_name]
                    try:
                        # 参数解析
                        params_dict = json.loads(arguments_str)
                        # 调用物理层执行
                        result = skill.execute(params_dict)
                    except Exception as e:
                        # 捕获物理层在剪辑/编解码时的物理报错，将其传给 LLM 让其知晓
                        result = {"status": "error", "message": f"物理层运行错误: {str(e)}"}

                print(f"     运行反馈: {result}")

                # 将工具执行结果以 tool 消息形式提交给上下文
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": skill_name,
                    "content": json.dumps(result, ensure_ascii=False)
                })

        return "决策深度超出限制，Agent 强行终止任务。"
