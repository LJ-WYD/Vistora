import subprocess
from imageio_ffmpeg import get_ffmpeg_exe

# 全局缓存，避免每次渲染都调用子进程探测
_OPTIMAL_KWARGS_CACHE = None

def _detect_hardware_encoder():
    """
    通过底层 FFmpeg 执行探测，自动识别支持的硬件加速芯片。
    """
    try:
        exe = get_ffmpeg_exe()
        result = subprocess.run([exe, "-encoders"], capture_output=True, text=True, check=True)
        stdout = result.stdout.lower()

        # 优先检测 NVIDIA NVENC (对于 RTX 40 系列最佳)
        if "h264_nvenc" in stdout:
            return "h264_nvenc"
        
        # 其次检测 AMD AMF
        if "h264_amf" in stdout:
            return "h264_amf"

        # 最后检测 Intel QSV
        if "h264_qsv" in stdout:
            return "h264_qsv"

        # macOS VideoToolbox 硬件加速
        if "h264_videotoolbox" in stdout:
            return "h264_videotoolbox"
    
    except Exception as e:
        print(f"[Warning] Failed to detect hardware encoder: {e}")
    
    return None

def get_optimal_export_kwargs(keep_audio: bool = True, fps: int = 24):
    """
    获取针对当前系统最优的视频导出参数字典。
    包含了硬件加速、预设和多线程配置。
    """
    global _OPTIMAL_KWARGS_CACHE

    if _OPTIMAL_KWARGS_CACHE is None:
        encoder = _detect_hardware_encoder()
        if encoder:
            print(f"\n[Hardware Accel] 探测到 GPU 硬件编码器: {encoder}，已开启秒级极速导出！")
            _OPTIMAL_KWARGS_CACHE = {
                "codec": encoder,
                "preset": "fast",   # nvenc / qsv 等硬件加速支持 fast 预设
                "threads": 16,      # 使用较多线程最大化读取解压能力
                "logger": "bar",    # 保持命令行进度条
                "ffmpeg_params": ["-cq", "18"] # 恒定无损级画质，防止4K崩溃
            }
        else:
            print("\n[Hardware Accel] 未探测到支持的 GPU 硬件编码器，使用软编码回退...")
            _OPTIMAL_KWARGS_CACHE = {
                "codec": "libx264",
                "preset": "ultrafast", # 在纯 CPU 情况下尽量提升渲染速度
                "threads": 8,
                "logger": "bar",
                "ffmpeg_params": ["-crf", "18"] # CPU软编码无损画质参数
            }
    
    # 动态组装当前的特定的动态参数，如 fps 和音频
    # 注意：每次调用都返回一个新的字典，以防外界修改缓存
    kwargs = _OPTIMAL_KWARGS_CACHE.copy()
    kwargs["audio_codec"] = "aac" if keep_audio else None
    kwargs["fps"] = fps

    return kwargs

import json

def probe_video_color_info(source_path: str) -> dict:
    """
    侦听视频流的色彩 DNA (Color Primaries, Transfer Characteristics, Matrix Coefficients).
    """
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=pix_fmt,color_space,color_transfer,color_primaries",
        "-of", "json",
        source_path
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        if streams:
            return streams[0]
    except Exception as e:
        print(f"[Warning] HDR Probing failed: {e}")
    return {}

def get_ffmpeg_hw_args(source_path: str = None) -> list:
    """
    提供给各个工业管线的 FFmpeg 硬件加速参数数组。
    支持 HDR (10-bit HLG/PQ) 无损透传保护。
    """
    args = []
    
    is_hdr = False
    color_info = {}
    if source_path:
        color_info = probe_video_color_info(source_path)
        pix_fmt = color_info.get("pix_fmt", "").lower()
        color_transfer = color_info.get("color_transfer", "").lower()
        color_primaries = color_info.get("color_primaries", "").lower()

        # 典型的 HDR 签名
        if "10" in pix_fmt or "bt2020" in color_primaries or "smpte2084" in color_transfer or "arib-std-b67" in color_transfer:
            is_hdr = True

    gpu_encoder = _detect_hardware_encoder()
    
    if is_hdr:
        print("\n[Color Matrix] 侦测到高动态范围 (HDR) 素材，自动开启 H.265(HEVC) 硬件编码及无损色彩透传！")
        # 针对 HDR 必须采用 H.265 (hevc)
        if gpu_encoder and "nvenc" in gpu_encoder:
            args.extend(["-c:v", "hevc_nvenc", "-cq", "18"])
        else:
            args.extend(["-c:v", "libx265", "-crf", "18"])
            
        # 强制继承像素格式 (nvenc 支持 p010le 或 yuv420p10le)
        # 为确保兼容性，对于 10-bit 统一输出 yuv420p10le
        args.extend(["-pix_fmt", "yuv420p10le"])

        # 透传色彩标签 (如果源有，则直接复用；如果没有则做个万能兜底，如 bt2020)
        primaries = color_info.get("color_primaries", "bt2020")
        transfer = color_info.get("color_transfer", "arib-std-b67")
        matrix = color_info.get("color_space", "bt2020nc")
        
        # 预防 ffprobe 返回 "unknown"
        if primaries == "unknown": primaries = "bt2020"
        if transfer == "unknown": transfer = "arib-std-b67"
        if matrix == "unknown": matrix = "bt2020nc"

        args.extend([
            "-color_primaries", primaries,
            "-color_trc", transfer,
            "-colorspace", matrix
        ])
    else:
        # SDR 常规路径 (H.264)
        print("\n[Color Matrix] 常规 SDR 素材，沿用 H.264 高兼容通道。")
        if gpu_encoder:
            args.extend(["-c:v", gpu_encoder, "-cq", "18", "-pix_fmt", "yuv420p"])
        else:
            args.extend(["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
            
    return args
