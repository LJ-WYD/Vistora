import os
import json
from typing import Optional
from .timeline import TimelineConfig, TrackConfig

# 默认将时间线保存在项目根目录的 .workspace 文件夹中
WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".workspace"))
PROJECT_FILE = os.path.join(WORKSPACE_DIR, "current_timeline.json")

class TimelineManager:
    """
    非破坏性编辑架构的核心状态管理器。
    负责在磁盘上读写当前项目的时间线状态。
    """
    
    @staticmethod
    def get_current_timeline() -> TimelineConfig:
        """获取当前项目的 Timeline 配置，如果不存在则创建一个空的标准模板"""
        if os.path.exists(PROJECT_FILE):
            try:
                with open(PROJECT_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return TimelineConfig(**data)
            except Exception as e:
                print(f"读取时间线文件失败: {e}，将返回空项目。")
        
        # 返回一个包含基础主轨道的空项目
        timeline = TimelineConfig()
        timeline.tracks["video"] = TrackConfig(
            id="video",
            kind="video",
            role="primary",
            order=0,
        )
        timeline.tracks["audio"] = TrackConfig(
            id="audio",
            kind="audio",
            role="primary",
            order=1,
        )
        return timeline

    @staticmethod
    def save_current_timeline(timeline: TimelineConfig):
        """将最新的 Timeline 状态保存到磁盘"""
        os.makedirs(WORKSPACE_DIR, exist_ok=True)
        with open(PROJECT_FILE, "w", encoding="utf-8") as f:
            # 兼容 pydantic V1 和 V2
            if hasattr(timeline, "model_dump_json"):
                f.write(timeline.model_dump_json(indent=2))
            else:
                f.write(timeline.json(indent=2))

    @staticmethod
    def reset_timeline():
        """重置/清空当前时间线项目"""
        if os.path.exists(PROJECT_FILE):
            os.remove(PROJECT_FILE)
