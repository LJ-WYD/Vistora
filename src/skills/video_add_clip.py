import os
import uuid
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from .base import BaseSkill
from moviepy import VideoFileClip
from core.timeline_manager import TimelineManager
from core import timeline_manager
from core.timeline import ClipConfig
from material_production import MaterialCatalogStore

class VideoAddClipInput(BaseModel):
    """添加剪辑片段到时间线的输入契约"""
    source_path: str = Field(..., description="要添加到项目中的源视频物理路径")
    trim_in: Optional[float] = Field(0.0, description="在源视频中的裁剪起始时间(秒)。默认为 0.0")
    trim_out: Optional[float] = Field(None, description="在源视频中的裁剪结束时间(秒)。若不填，则一直到视频结尾")
    speed_factor: float = Field(1.0, description="加入时的变速倍数，1.0为原速")
    reverse: bool = Field(False, description="是否倒放")
    rotate: int = Field(0, description="旋转角度：支持 0, 90, 180, 270")
    keep_audio: bool = Field(True, description="是否保留原视频自带音频")

class VideoAddClipSkill(BaseSkill):
    """
    非破坏性基础技能：将源视频记录加入项目的时间线（支持一并附加初始修剪与特效属性）。
    """
    name = "VideoAddClipSkill"
    description = "将单个视频素材加入当前视频工程的时间线末尾（此操作为瞬间响应的软编辑，不会导致物理渲染）"
    input_model = VideoAddClipInput

    def run(self, params: VideoAddClipInput) -> Dict[str, Any]:
        timeline = TimelineManager.get_current_timeline()
        video_track = timeline.tracks.get("video")
        if video_track is None:
            raise ValueError(
                "Legacy add requires the compatibility video track"
            )
        if video_track.locked:
            raise ValueError("The compatibility video track is locked")
        source_path = params.source_path
        if source_path.startswith("material://"):
            resolved = MaterialCatalogStore.for_project_file(
                timeline_manager.PROJECT_FILE
            ).resolve_uri(source_path)
            if resolved is None:
                raise FileNotFoundError(
                    "Catalog material is missing, unaccepted, or tampered"
                )
            source_path = str(resolved)
        if not os.path.exists(source_path):
            raise FileNotFoundError(f"找不到视频素材: {source_path}")

        # 利用 moviepy 快速探测视频物理属性
        clip = VideoFileClip(source_path)
        duration = clip.duration
        w, h = clip.size
        clip.close()

        trim_in = max(0.0, params.trim_in or 0.0)
        trim_out = min(duration, params.trim_out if params.trim_out is not None else duration)

        if trim_in >= trim_out:
            raise ValueError(f"裁剪区间无效: 起始 {trim_in} 必须小于结束 {trim_out}")

        # 检查是否需要生成倒放代理
        clip_id = f"clip_{uuid.uuid4().hex[:8]}"
        reverse_flag = params.reverse
        
        if reverse_flag:
            from utils.proxy import generate_reverse_proxy
            # 瞬间通过显卡硬解硬编生成倒放好的代理视频文件
            proxy_path = generate_reverse_proxy(source_path, trim_in, trim_out, clip_id)
            source_path = proxy_path
            
            # 因为生成的代理视频已经是倒放并提取裁剪好的部分：
            # 1. 物理代理文件的起点为 0.0
            # 2. 时长即为其自身时长
            # 3. 在时间线属性中，倒放标志置为 False，交给最终渲染器作为普通顺序视频直接播放
            proxy_clip = VideoFileClip(proxy_path)
            proxy_duration = proxy_clip.duration
            proxy_clip.close()
            
            trim_in = 0.0
            trim_out = proxy_duration
            reverse_flag = False

        timeline = TimelineManager.get_current_timeline()
        video_track = timeline.tracks.get("video")
        if video_track is None:
            raise ValueError(
                "Legacy add requires the compatibility video track"
            )
        if video_track.locked:
            raise ValueError("The compatibility video track is locked")
        
        # 动态计算追加在时间轴的哪个时间点
        timeline_start = 0.0
        if video_track.clips:
            last_clip = video_track.clips[-1]
            last_duration = (last_clip.trim_out - last_clip.trim_in) / last_clip.speed_factor
            timeline_start = last_clip.timeline_start + last_duration
        else:
            # 如果是项目中的第一个视频，则默认将项目工程的分辨率设置为该视频的原生分辨率，防止画面被裁切
            timeline.width = w
            timeline.height = h

        new_clip = ClipConfig(
            id=clip_id,
            source=source_path,
            trim_in=trim_in,
            trim_out=trim_out,
            timeline_start=timeline_start,
            speed_factor=params.speed_factor,
            reverse=reverse_flag,
            rotate=params.rotate,
            keep_audio=params.keep_audio
        )

        video_track.clips.append(new_clip)
        TimelineManager.save_current_timeline(timeline)

        return {
            "status": "success",
            "message": "视频片段已以非破坏性模式成功追加至时间线",
            "clip_id": new_clip.id,
            "timeline_start": timeline_start,
            "effective_duration": (trim_out - trim_in) / params.speed_factor
        }
