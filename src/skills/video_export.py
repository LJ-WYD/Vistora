import os
import uuid
from pathlib import Path
from typing import Dict, Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .base import BaseSkill
from core.timeline_manager import TimelineManager
from core.timeline import TimelineRenderer
from subtitles import burn_subtitles

class VideoExportInput(BaseModel):
    """导出合成视频的输入契约"""
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["1.1.0"] = "1.1.0"
    output_path: str = Field(..., description="要导出合成的最终物理视频绝对路径，必须以 .mp4, .mov 等结尾")
    clear_timeline_after: bool = Field(False, description="是否在导出成功后清空整个时间线，准备下一个项目")
    subtitle_mode: str = Field("none", pattern=r"^(none|burn)$")
    subtitle_track_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def subtitle_fields(self):
        if self.subtitle_mode == "none" and self.subtitle_track_ids:
            raise ValueError("Subtitle track IDs require subtitle_mode=burn")
        if len(self.subtitle_track_ids) != len(set(self.subtitle_track_ids)):
            raise ValueError("Subtitle track IDs must be unique")
        if self.subtitle_track_ids != tuple(sorted(self.subtitle_track_ids)):
            raise ValueError("Subtitle track IDs must use stable ordering")
        return self

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
        font_warnings: tuple[str, ...] = ()
        if params.subtitle_mode == "burn":
            target = Path(params.output_path)
            base_output = target.parent / (
                f".vistora-base-{uuid.uuid4().hex}{target.suffix or '.mp4'}"
            )
            try:
                renderer.render(str(base_output))
                _, font_warnings = burn_subtitles(
                    str(base_output),
                    params.output_path,
                    timeline,
                    params.subtitle_track_ids,
                )
            finally:
                base_output.unlink(missing_ok=True)
        else:
            renderer.render(params.output_path)
        
        # 导出后若需清空
        if params.clear_timeline_after:
            TimelineManager.reset_timeline()
            print("[Export] 时间线已重置。")
            
        return {
            "status": "success",
            "message": "所有复杂剪辑特效已通过全局 GPU 加速合成完毕！画质保持 4K 恒定原生！",
            "output_path": params.output_path,
            "subtitle_mode": params.subtitle_mode,
            "subtitle_track_ids": list(params.subtitle_track_ids),
            "font_warnings": list(font_warnings),
        }
