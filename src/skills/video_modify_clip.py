from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from .base import BaseSkill
from core.timeline_manager import TimelineManager

class VideoModifyClipInput(BaseModel):
    """修改时间线片段属性的输入契约"""
    target_index: int = Field(-1, description="要修改的视频片段在时间轴中的索引。0是第一个，-1是最后加入的一个。默认 -1")
    speed_factor: Optional[float] = Field(None, description="要更新的倍速参数。不填表示不修改。")
    reverse: Optional[bool] = Field(None, description="要更新的倒放属性开关。")
    rotate: Optional[int] = Field(None, description="要更新的旋转角度参数。")

class VideoModifyClipSkill(BaseSkill):
    """
    非破坏性基础技能：在时间线项目中修改特定已存在片段的特效参数。
    """
    name = "VideoModifyClipSkill"
    description = "修改当前时间线内某个视频片段的各项属性（如将其加速、变倒放等，纯状态更新，无物理开销）"
    input_model = VideoModifyClipInput

    def run(self, params: VideoModifyClipInput) -> Dict[str, Any]:
        timeline = TimelineManager.get_current_timeline()
        video_track = timeline.tracks.get("video")
        if video_track is None:
            raise ValueError("The compatibility video track is unavailable")
        if video_track.locked:
            raise ValueError("The compatibility video track is locked")
        
        if not video_track.clips:
            raise ValueError("当前时间线为空，没有任何视频可供修改。请先添加视频片段。")
            
        try:
            target_clip = video_track.clips[params.target_index]
        except IndexError:
            raise IndexError(f"片段索引越界: {params.target_index}，当前时间线仅有 {len(video_track.clips)} 个片段。")

        # 更新属性
        updated = []
        if params.speed_factor is not None:
            target_clip.speed_factor = params.speed_factor
            updated.append("speed_factor")
            
        # 特殊处理倒放：如果从正放修改为倒放，则触发代理生成
        if params.reverse is True and not target_clip.reverse:
            from utils.proxy import generate_reverse_proxy
            from moviepy import VideoFileClip
            
            # 使用原片段的裁剪区间生成倒放代理
            proxy_path = generate_reverse_proxy(
                target_clip.source,
                target_clip.trim_in,
                target_clip.trim_out,
                target_clip.id
            )
            
            proxy_clip = VideoFileClip(proxy_path)
            proxy_duration = proxy_clip.duration
            proxy_clip.close()
            
            # 更新片段属性为代理属性
            target_clip.source = proxy_path
            target_clip.trim_in = 0.0
            target_clip.trim_out = proxy_duration
            target_clip.reverse = False  # 代理本身已经是物理倒放，时间线设为 False
            updated.append("reverse_proxy_generated")
        elif params.reverse is not None:
            target_clip.reverse = params.reverse
            updated.append("reverse")
            
        if params.rotate is not None:
            target_clip.rotate = params.rotate
            updated.append("rotate")

        if updated:
            TimelineManager.save_current_timeline(timeline)

        return {
            "status": "success",
            "message": "非破坏性修改已生效",
            "modified_clip_id": target_clip.id,
            "updated_properties": updated
        }
