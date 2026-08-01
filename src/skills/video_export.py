import os
from typing import Dict, Any
from pydantic import BaseModel, Field
from .base import BaseSkill
from core.timeline_manager import TimelineManager
from core.timeline import TimelineRenderer

class VideoExportInput(BaseModel):
    """导出合成视频的输入契约"""
    output_path: str = Field(..., description="要导出合成的最终物理视频绝对路径，必须以 .mp4, .mov 等结尾")
    clear_timeline_after: bool = Field(False, description="是否在导出成功后清空整个时间线，准备下一个项目")

class VideoExportSkill(BaseSkill):
    """
    终结技：将整个时间线（包含了所有裁切、变速、倒放等参数配置的视频流）进行一次性的最终硬件渲染。
    """
    name = "VideoExportSkill"
    description = "【关键】当用户要求最终导出、生成、渲染视频时调用。系统将按照非破坏性编辑积累的项目状态进行一次性的 GPU 极速物理写盘！"
    input_model = VideoExportInput

    def run(self, params: VideoExportInput) -> Dict[str, Any]:
        timeline = TimelineManager.get_current_timeline()
        video_clip_count = sum(
            len(track.clips)
            for track in timeline.tracks.values()
            if track.kind == "video" and track.enabled
        )
        if not video_clip_count:
            raise ValueError("当前时间线为空，请先添加剪辑片段！")
            
        print(
            "[Export] 准备物理渲染时间线，"
            f"启用的视频片段数: {video_clip_count}"
        )
        
        # 使用 TimelineRenderer 引擎进行渲染
        renderer = TimelineRenderer(timeline)
        renderer.render(params.output_path)
        
        # 导出后若需清空
        if params.clear_timeline_after:
            TimelineManager.reset_timeline()
            print("[Export] 时间线已重置。")
            
        return {
            "status": "success",
            "message": "所有复杂剪辑特效已通过全局 GPU 加速合成完毕！画质保持 4K 恒定原生！",
            "output_path": params.output_path
        }
