from typing import Dict, Any
from pydantic import BaseModel
from .base import BaseSkill
from core.timeline_manager import TimelineManager

class VideoClearTimelineInput(BaseModel):
    """清空时间线的输入契约，无需任何参数"""
    pass

class VideoClearTimelineSkill(BaseSkill):
    """
    非破坏性基础技能：一键清空重置当前工程的时间线
    """
    name = "VideoClearTimelineSkill"
    description = "【关键】清空并重置当前编辑工程的时间线，删除所有已添加的视频片段，重新开始新项目。"
    input_model = VideoClearTimelineInput

    def run(self, params: VideoClearTimelineInput) -> Dict[str, Any]:
        TimelineManager.reset_timeline()
        return {
            "status": "success",
            "message": "当前编辑工程的时间线已成功清空并重置！"
        }
