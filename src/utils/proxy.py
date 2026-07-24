import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from imageio_ffmpeg import get_ffmpeg_exe
from moviepy import VideoFileClip
from utils.hardware import _detect_hardware_encoder

WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".workspace"))
CACHE_DIR = os.path.join(WORKSPACE_DIR, "reverse_cache")

def _convert_segment_reverse(
    source_path: str,
    start: float,
    end: float,
    out_seg_path: str,
    encoder: str,
    preset_params: list,
    quality_params: list,
    has_audio: bool,
    ffmpeg_exe: str
):
    """
    单线程执行单个小视频分片的倒放与转码
    """
    if has_audio:
        cmd = [
            ffmpeg_exe, "-y",
            "-ss", f"{start:.4f}",
            "-to", f"{end:.4f}",
            "-i", source_path,
            "-filter_complex", "[0:v]reverse[v];[0:a]areverse[a]",
            "-map", "[v]",
            "-map", "[a]",
            "-c:v", encoder,
        ] + preset_params + quality_params + [
            "-c:a", "aac",
            out_seg_path
        ]
    else:
        cmd = [
            ffmpeg_exe, "-y",
            "-ss", f"{start:.4f}",
            "-to", f"{end:.4f}",
            "-i", source_path,
            "-vf", "reverse",
            "-an",
            "-c:v", encoder,
        ] + preset_params + quality_params + [
            out_seg_path
        ]

    # 在 Windows 上隐藏子窗口运行
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=startupinfo,
        check=True
    )


def generate_reverse_proxy(source_path: str, trim_in: float, trim_out: float, clip_id: str) -> str:
    """
    商业级分片倒放算法：
    将长视频切分为多个 30 秒以内的安全小段，利用多线程并发调用 FFmpeg GPU 加速转码倒放，
    最后进行无损拼接。彻底解决超长 4K 视频倒放时的 Cannot allocate memory (OOM) 崩溃。
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    output_path = os.path.join(CACHE_DIR, f"{clip_id}_reversed.mp4")

    # 1. 缓存命中检测
    if os.path.exists(output_path):
        print(f"[Proxy] 倒放代理缓存命中: {output_path}")
        return output_path

    print(f"\n[Proxy] 启动分片倒放算法引擎 (区间: {trim_in}s 到 {trim_out}s)...")
    
    # 2. 探测音轨属性和分辨率
    try:
        clip = VideoFileClip(source_path)
        has_audio = clip.audio is not None
        v_width, v_height = clip.size
        clip.close()
    except Exception as e:
        print(f"[Warning] 探测视频属性失败: {e}，默认按 1080P 处理")
        has_audio = False
        v_width, v_height = 1920, 1080

    # 3. 探测 GPU 编码器
    encoder = _detect_hardware_encoder()
    if encoder:
        print(f"[Proxy] 转码将使用 GPU 加速编码器: {encoder}")
        quality_params = ["-cq", "18", "-pix_fmt", "yuv420p"] if "nvenc" in encoder else ["-crf", "18", "-pix_fmt", "yuv420p"]
        preset_params = ["-preset", "fast"]
    else:
        print("[Proxy] 未找到 GPU 编码器，使用 CPU 软解软编倒放...")
        encoder = "libx264"
        quality_params = ["-crf", "18", "-pix_fmt", "yuv420p"]
        preset_params = ["-preset", "ultrafast"]

    ffmpeg_exe = get_ffmpeg_exe()
    total_duration = trim_out - trim_in

    # 4. 智能自适应切片与并发调度：防止 4K 撑爆内存和显存 (OOM)
    # 根据像素总数动态调节安全长度和并发数
    total_pixels = v_width * v_height
    if total_pixels >= 3840 * 2160:  # 4K
        SEGMENT_DURATION = 5.0
        target_workers = 2
    elif total_pixels >= 1920 * 1080: # 1080P
        SEGMENT_DURATION = 15.0
        target_workers = 3
    else: # 720P 以下
        SEGMENT_DURATION = 30.0
        target_workers = 4

    segments = []
    current_start = trim_in
    while current_start < trim_out:
        current_end = min(current_start + SEGMENT_DURATION, trim_out)
        segments.append((current_start, current_end))
        current_start = current_end

    # 逆序排列分片（确保合并后的视频是倒序的）
    segments.reverse()
    print(f"[Proxy] 视频已切分为 {len(segments)} 个分片，开始进行多线程并发倒放处理...")

    # 5. 多线程并发执行分片倒放转码
    temp_files = []
    futures = []
    
    # 限制并发线程数，压榨 GPU 但防止过多子进程打爆系统
    max_workers = min(len(segments), target_workers) 
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        for idx, (start, end) in enumerate(segments):
            temp_seg_path = os.path.join(CACHE_DIR, f"temp_{clip_id}_seg_{idx}.mp4")
            temp_files.append(temp_seg_path)
            
            # 提交到线程池
            f = executor.submit(
                _convert_segment_reverse,
                source_path, start, end, temp_seg_path,
                encoder, preset_params, quality_params,
                has_audio, ffmpeg_exe
            )
            futures.append(f)
            
        # 等待所有线程完成，抛出异常阻断
        for f in futures:
            f.result()

    print("[Proxy] 所有分片倒放转码完成。正在进行无损合并 (Concat)...")

    # 6. 使用 FFmpeg concat 协议进行无损拼接（几毫秒内完成且零画质损耗）
    concat_txt_path = os.path.join(CACHE_DIR, f"list_{clip_id}.txt")
    with open(concat_txt_path, "w", encoding="utf-8") as f:
        for tf in temp_files:
            # 必须将路径中的反斜杠替换为正斜杠，以防 FFmpeg 在 Windows 路径下解析出错
            normalized_path = tf.replace("\\", "/")
            f.write(f"file '{normalized_path}'\n")

    # 拼接命令
    concat_cmd = [
        ffmpeg_exe, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_txt_path,
        "-c", "copy",  # 纯数据流拷贝，不重编码，速度极快
        output_path
    ]

    try:
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        subprocess.run(
            concat_cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=startupinfo,
            check=True
        )
        print(f"[Proxy] 倒放代理无损拼装成功: {output_path}")
    except subprocess.CalledProcessError as e:
        print(f"[Error] Concat 拼装失败: {e}")
        raise RuntimeError(f"Concat 拼装失败: {e}")
    finally:
        # 7. 清理临时分片文件
        for tf in temp_files:
            if os.path.exists(tf):
                try:
                    os.remove(tf)
                except Exception:
                    pass
        if os.path.exists(concat_txt_path):
            try:
                os.remove(concat_txt_path)
            except Exception:
                pass

    return output_path
