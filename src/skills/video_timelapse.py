import os
import subprocess
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from .base import BaseSkill
from moviepy import VideoFileClip
from utils.hardware import get_ffmpeg_hw_args

class VideoTimelapseInput(BaseModel):
    """
    延时摄影技能输入参数契约
    """
    source_path: str = Field(..., description="要进行抽帧合成的源视频路径")
    output_path: str = Field(..., description="合成后的目标延时视频输出路径")
    frame_interval: float = Field(1.0, description="抽样时间间隔（秒），例如每隔 0.5 秒提取 1 帧")
    target_fps: Optional[int] = Field(None, description="合成新视频时的目标帧率。默认为空（继承原视频的帧率）。注意：为了保持视频流畅，如果有指定此值，绝对不允许低于 24！")

class VideoTimelapseSkill(BaseSkill):
    """
    延时摄影技能：在原视频中以一定时间步长抽取静态图像帧，
    随后将这些帧以指定帧率合成为一个全新的、无声的延时摄影（Time-lapse）视频。
    """
    name = "VideoTimelapseSkill"
    description = "通过等间隔抽帧，并以新的帧率合成无声的延时摄影视频"
    input_model = VideoTimelapseInput

    def run(self, params: VideoTimelapseInput) -> Dict[str, Any]:
        if params.frame_interval <= 0:
            raise ValueError("抽样间隔 frame_interval 必须为正数")
        if params.target_fps is not None and params.target_fps <= 0:
            raise ValueError("目标帧率 target_fps 必须为正整数")
        if not os.path.exists(params.source_path):
            raise FileNotFoundError(f"找不到源视频文件: {params.source_path}")

        # 1. 探测源视频的物理属性，决定继承的帧率
        try:
            clip = VideoFileClip(params.source_path)
            source_fps = clip.fps or 30.0
            clip.close()
        except Exception as e:
            source_fps = 30.0

        final_fps = params.target_fps if params.target_fps is not None else int(round(source_fps))

        # 计算大致时长用于展示
        print(f"[Timelapse] 启动工业级延时抽样管道...")
        print(f"[Timelapse] 抽样步长: {params.frame_interval}s, 目标出片帧率: {final_fps} FPS")

        # 2. 确保输出目录存在
        output_dir = os.path.dirname(params.output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        # 计算出跨越的帧数
        step = int(round(params.frame_interval * source_fps))
        if step < 1:
            step = 1

        # 3. 构建纯 FFmpeg 极速渲染指令
        # 核心滤镜链：
        # - framestep={step}: 物理级别丢弃帧。这是杜绝一切补帧/复制帧鬼畜的最强方法，它直接在输入流里每隔 step 帧抓一张。
        # - setpts=N/({final_fps}*TB): 将这些被抽取的孤立画面在时间轴上靠拢，以 final_fps 的密度重新排列时间戳
        vf_expr = f"framestep={step},setpts=N/({final_fps}*TB)"

        cmd = [
            "ffmpeg", "-y",
            "-hwaccel", "auto",  # 尝试开启全局硬件解码，解放 CPU
            "-i", params.source_path,
            "-vf", vf_expr,
            "-r", str(final_fps), # 由于上游 framestep 完美保留了原画属性并且不触发补帧，这里安全设定封装帧率
            "-an"  # 延时摄影强制剥离音轨，因为音频无法这样极端压缩
        ]

        # 动态获取针对源视频色彩空间的最佳硬件编码参数 (包含 HDR 透传)
        hw_args = get_ffmpeg_hw_args(params.source_path)
        cmd.extend(hw_args)

        cmd.append(params.output_path)

        # 执行 FFmpeg 命令
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)

        return {
            "status": "success",
            "message": "视频已通过 FFmpeg 底层管道极速完成延时摄影渲染",
            "output_path": params.output_path,
            "target_fps": final_fps
        }
