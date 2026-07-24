import os
from typing import List, Dict, Optional
from pydantic import BaseModel, Field
from moviepy import VideoFileClip, AudioFileClip, CompositeVideoClip, CompositeAudioClip

class ClipConfig(BaseModel):
    """
    剪辑片段配置
    """
    id: str = Field(..., description="片段唯一标识")
    source: str = Field(..., description="素材文件路径")
    trim_in: float = Field(0.0, description="在原素材中的裁剪开始时间（秒）")
    trim_out: float = Field(..., description="在原素材中的裁剪结束时间（秒）")
    timeline_start: float = Field(0.0, description="在最终时间线上的开始播放时间（秒）")
    volume: Optional[float] = Field(1.0, description="音量大小 (0.0 到 1.0)")
    keep_audio: bool = Field(True, description="是否保留视频自带的音频（仅对视频片段有效）")
    speed_factor: float = Field(1.0, description="变速播放速度倍数（如 2.0 表示两倍速，0.5 表示半速）")
    reverse: bool = Field(False, description="是否倒放")
    rotate: int = Field(0, description="画面旋转角度（支持 90, 180, 270）")

class TrackConfig(BaseModel):
    """
    轨道配置
    """
    id: str = Field(..., description="轨道唯一标识")
    clips: List[ClipConfig] = Field(default_factory=list, description="轨道中包含的片段列表")

class TimelineConfig(BaseModel):
    """
    声明式时间线配置
    """
    width: int = Field(1920, description="视频宽度")
    height: int = Field(1080, description="视频高度")
    fps: int = Field(30, description="视频帧率")
    tracks: Dict[str, TrackConfig] = Field(default_factory=dict, description="轨道映射字典，例如 {'video': video_track, 'audio': audio_track}")

class TimelineRenderer:
    """
    时间线渲染器，基于 MoviePy 将声明式时间线渲染输出为视频文件
    """
    def __init__(self, config: TimelineConfig):
        self.config = config
        self._opened_clips = []  # 记录所有打开的 MoviePy Clip 实例，便于渲染结束后统一关闭释放资源

    def render(self, output_path: str) -> str:
        """
        开始渲染时间线，并输出到指定路径
        """
        # --- Fast-Path 极速渲染通道判断 ---
        video_track = self.config.tracks.get("video")
        audio_track = self.config.tracks.get("audio")
        
        is_fast_path = False
        is_multi_fast_path = False
        
        if video_track and len(video_track.clips) > 0:
            if not audio_track or len(audio_track.clips) == 0:
                if len(video_track.clips) == 1:
                    is_fast_path = True
                else:
                    is_multi_fast_path = True
                
        if is_fast_path:
            try:
                return self._render_fast_path(output_path)
            except Exception as e:
                print(f"[Fast-Path] 极速渲染失败，降级到标准 MoviePy 渲染通道: {e}")
                
        if is_multi_fast_path:
            try:
                return self._render_multi_fast_path(output_path)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[Multi-Fast-Path] 多片段极速并发拼接失败，降级到标准 MoviePy 渲染通道: {e}")

        video_clips = []
        audio_clips = []

        # 1. 解析视频轨
        if "video" in self.config.tracks:
            video_track = self.config.tracks["video"]
            for clip_cfg in video_track.clips:
                if not os.path.exists(clip_cfg.source):
                    raise FileNotFoundError(f"视频素材文件不存在: {clip_cfg.source}")
                
                # 加载视频剪辑
                clip = VideoFileClip(clip_cfg.source)
                self._opened_clips.append(clip)

                # 如果不保留音频，清除音轨
                if not clip_cfg.keep_audio:
                    clip = clip.without_audio()

                # 限制裁剪范围
                duration = clip.duration
                trim_out = min(clip_cfg.trim_out, duration)
                trim_in = max(0.0, clip_cfg.trim_in)
                if trim_in >= trim_out:
                    raise ValueError(f"视频片段 {clip_cfg.id} 的 trim_in ({trim_in}) 必须小于 trim_out ({trim_out})")

                # 进行裁剪
                trimmed = clip.subclipped(trim_in, trim_out)
                
                # 应用视频特效链（变速、倒放、旋转）
                effects = []
                if clip_cfg.speed_factor != 1.0:
                    from moviepy.video.fx import MultiplySpeed
                    effects.append(MultiplySpeed(clip_cfg.speed_factor))
                
                if clip_cfg.reverse:
                    if trimmed.fps is None:
                        trimmed = trimmed.with_fps(clip.fps or 30)
                    orig_duration = trimmed.duration
                    if orig_duration is not None:
                        # 显式保留时长参数，防止 time_transform 将 duration 丢失为 None
                        trimmed = trimmed.time_transform(
                            lambda t: max(0.0, min(orig_duration - 0.0001, orig_duration - t)),
                            keep_duration=True
                        )
                        trimmed.duration = orig_duration
                    else:
                        from moviepy.video.fx import TimeMirror
                        effects.append(TimeMirror())
                
                if clip_cfg.rotate in (90, 180, 270):
                    from moviepy.video.fx import Rotate
                    effects.append(Rotate(clip_cfg.rotate))
                
                if effects:
                    trimmed = trimmed.with_effects(effects)
                
                # 设置在时间线上的起始播放时间
                positioned = trimmed.with_start(clip_cfg.timeline_start)
                video_clips.append(positioned)

        # 2. 解析音频轨（如背景音乐等）
        if "audio" in self.config.tracks:
            audio_track = self.config.tracks["audio"]
            for clip_cfg in audio_track.clips:
                if not os.path.exists(clip_cfg.source):
                    raise FileNotFoundError(f"音频素材文件不存在: {clip_cfg.source}")
                
                # 加载音频剪辑
                clip = AudioFileClip(clip_cfg.source)
                self._opened_clips.append(clip)

                # 限制裁剪范围
                duration = clip.duration
                trim_out = min(clip_cfg.trim_out, duration)
                trim_in = max(0.0, clip_cfg.trim_in)
                if trim_in >= trim_out:
                    raise ValueError(f"音频片段 {clip_cfg.id} 的 trim_in ({trim_in}) 必须小于 trim_out ({trim_out})")

                # 进行裁剪
                trimmed = clip.subclipped(trim_in, trim_out)
                
                # 设置音量和起始时间
                positioned = trimmed.with_start(clip_cfg.timeline_start)
                if clip_cfg.volume is not None:
                    positioned = positioned.with_volume_scaled(clip_cfg.volume)
                
                audio_clips.append(positioned)

        if not video_clips:
            raise ValueError("时间线中未包含任何有效的视频轨道，无法进行渲染。")

        # 3. 合成视频
        # 使用 CompositeVideoClip 将所有视频片段层叠/顺序播放
        final_video = CompositeVideoClip(video_clips, size=(self.config.width, self.config.height))

        # 4. 合成音频并混音
        if audio_clips:
            # 如果视频本身有音轨，需要进行混音
            # MoviePy 中 CompositeVideoClip 默认会把子 clip 的声音也带上。
            # 我们将音频轨的 clip 与 final_video 自带的音轨混音
            extra_audio = CompositeAudioClip(audio_clips)
            if final_video.audio is not None:
                mixed_audio = CompositeAudioClip([final_video.audio, extra_audio])
                final_video = final_video.with_audio(mixed_audio)
            else:
                final_video = final_video.with_audio(extra_audio)

        # 5. 导出视频文件
        output_dir = os.path.dirname(output_path)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir, exist_ok=True)

        try:
            # 导出视频文件（动态识别 GPU 加速或软编）
            from utils.hardware import get_optimal_export_kwargs
            kwargs = get_optimal_export_kwargs(keep_audio=True, fps=self.config.fps)
            kwargs["temp_audiofile"] = "temp-audio.m4a"
            kwargs["remove_temp"] = True
            
            final_video.write_videofile(output_path, **kwargs)
        finally:
            # 6. 关闭所有打开的文件句柄，释放内存和文件锁
            final_video.close()
            for c in self._opened_clips:
                try:
                    c.close()
                except Exception:
                    pass
            self._opened_clips.clear()

        return output_path

    def _render_fast_path(self, output_path: str) -> str:
        """
        极速直通渲染引擎：
        当时间轴非常纯净（只有一个主视频，无叠加图层或混音）时，
        绕过 MoviePy 内存交换流，直接将操作转化为纯 FFmpeg 底层滤镜进行原生渲染，性能提升最高可达上百倍！
        """
        import subprocess
        from moviepy import VideoFileClip
        from utils.hardware import _detect_hardware_encoder
        
        clip_cfg = self.config.tracks["video"].clips[0]
        
        # 探测是否有音频轨
        has_audio = False
        try:
            probe = VideoFileClip(clip_cfg.source)
            has_audio = probe.audio is not None
            probe.close()
        except:
            pass

        v_filters = []
        a_filters = []
        input_args = []
        
        # 截取 (前置截取效率最高)
        if clip_cfg.trim_in > 0:
            input_args.extend(["-ss", str(clip_cfg.trim_in)])
            
        if clip_cfg.trim_out < 999999.0:
            duration_to_cut = clip_cfg.trim_out - clip_cfg.trim_in
            input_args.extend(["-t", str(duration_to_cut)])

        # 变速
        if clip_cfg.speed_factor != 1.0:
            pts_factor = 1.0 / clip_cfg.speed_factor
            v_filters.append(f"setpts={pts_factor}*PTS")
            
            # FFmpeg atempo 限制 0.5 到 2.0，超过则需要级联
            temp_speed = clip_cfg.speed_factor
            while temp_speed > 2.0:
                a_filters.append("atempo=2.0")
                temp_speed /= 2.0
            while temp_speed < 0.5:
                a_filters.append("atempo=0.5")
                temp_speed /= 0.5
            if temp_speed != 1.0:
                a_filters.append(f"atempo={temp_speed}")
            
        # 旋转
        if clip_cfg.rotate == 90:
            v_filters.append("transpose=1")
        elif clip_cfg.rotate == 180:
            v_filters.append("transpose=2,transpose=2")
        elif clip_cfg.rotate == 270:
            v_filters.append("transpose=2")
            
        # 倒放
        if clip_cfg.reverse:
            v_filters.append("reverse")
            a_filters.append("areverse")
            
        cmd = ["ffmpeg", "-y"]
        cmd.extend(input_args)
        cmd.extend(["-i", clip_cfg.source])
        
        use_audio = clip_cfg.keep_audio and has_audio
        
        if v_filters or a_filters:
            filter_complex = ""
            if v_filters:
                filter_complex += f"[0:v]{','.join(v_filters)}[v];"
            if use_audio and a_filters:
                filter_complex += f"[0:a]{','.join(a_filters)}[a];"
            
            if filter_complex:
                filter_complex = filter_complex.rstrip(";")
                cmd.extend(["-filter_complex", filter_complex])
                
                if v_filters:
                    cmd.extend(["-map", "[v]"])
                else:
                    cmd.extend(["-map", "0:v"])
                    
                if use_audio:
                    if a_filters:
                        cmd.extend(["-map", "[a]"])
                    else:
                        cmd.extend(["-map", "0:a"])
        else:
            if not use_audio:
                cmd.append("-an")
        
        # 编码参数
        gpu_encoder = _detect_hardware_encoder()
        if gpu_encoder:
            cmd.extend(["-c:v", gpu_encoder, "-cq", "18", "-pix_fmt", "yuv420p"])
        else:
            cmd.extend(["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
            
        if use_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            
        cmd.append(output_path)
        
        print(f"[Fast-Path] 探测到单轴纯净场景，已启用 FFmpeg 底层极速直通渲染通道！")
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return output_path

    def _render_multi_fast_path(self, output_path: str) -> str:
        """
        多片段极速并发拼接引擎 (Multi-Fast-Path):
        将时间线上多个含有各自属性（裁切/倍速/旋转/倒放）的视频，并发执行“标准化转码”，
        并强制填充黑边对齐工程分辨率。最后使用 concat demuxer 进行无损缝合，全过程抛弃 MoviePy。
        """
        import uuid
        import subprocess
        from concurrent.futures import ThreadPoolExecutor
        from moviepy import VideoFileClip
        from utils.hardware import _detect_hardware_encoder
        
        WORKSPACE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".workspace"))
        CACHE_DIR = os.path.join(WORKSPACE_DIR, "fast_concat_cache")
        os.makedirs(CACHE_DIR, exist_ok=True)
        
        clips = self.config.tracks["video"].clips
        target_w = self.config.width
        target_h = self.config.height
        target_fps = self.config.fps
        
        temp_files = []
        futures = []
        
        gpu_encoder = _detect_hardware_encoder()
        
        def _normalize_clip(clip_cfg, out_path, idx):
            # 探测是否有音频轨
            has_audio = False
            try:
                probe = VideoFileClip(clip_cfg.source)
                has_audio = probe.audio is not None
                probe.close()
            except:
                pass

            v_filters = []
            a_filters = []
            input_args = []
            
            # 截取
            if clip_cfg.trim_in > 0:
                input_args.extend(["-ss", str(clip_cfg.trim_in)])
            if clip_cfg.trim_out < 999999.0:
                duration_to_cut = clip_cfg.trim_out - clip_cfg.trim_in
                input_args.extend(["-t", str(duration_to_cut)])

            # 变速
            if clip_cfg.speed_factor != 1.0:
                pts_factor = 1.0 / clip_cfg.speed_factor
                v_filters.append(f"setpts={pts_factor}*PTS")
                
                temp_speed = clip_cfg.speed_factor
                while temp_speed > 2.0:
                    a_filters.append("atempo=2.0")
                    temp_speed /= 2.0
                while temp_speed < 0.5:
                    a_filters.append("atempo=0.5")
                    temp_speed /= 0.5
                if temp_speed != 1.0:
                    a_filters.append(f"atempo={temp_speed}")
                
            # 旋转
            if clip_cfg.rotate == 90:
                v_filters.append("transpose=1")
            elif clip_cfg.rotate == 180:
                v_filters.append("transpose=2,transpose=2")
            elif clip_cfg.rotate == 270:
                v_filters.append("transpose=2")
                
            # 倒放
            if clip_cfg.reverse:
                v_filters.append("reverse")
                a_filters.append("areverse")
                
            # --- 核心：画面与音频归一化滤镜 ---
            norm_v = f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2,fps={target_fps},format=yuv420p"
            v_filters.append(norm_v)
            a_filters.append("aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo")
            
            cmd = ["ffmpeg", "-y"]
            cmd.extend(input_args)
            cmd.extend(["-i", clip_cfg.source])
            
            use_audio = clip_cfg.keep_audio and has_audio
            
            filter_complex = ""
            if not use_audio:
                # 为了 concat 不出错，为无声视频自动补齐静音轨
                filter_complex += f"anullsrc=r=48000:cl=stereo[null_a];"
                
            if v_filters:
                filter_complex += f"[0:v]{','.join(v_filters)}[v];"
            else:
                filter_complex += f"[0:v]{norm_v}[v];"
                
            if use_audio:
                if a_filters:
                    filter_complex += f"[0:a]{','.join(a_filters)}[a];"
                else:
                    filter_complex += f"[0:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a];"
            
            if filter_complex:
                filter_complex = filter_complex.rstrip(";")
                cmd.extend(["-filter_complex", filter_complex])
                cmd.extend(["-map", "[v]"])
                if use_audio:
                    cmd.extend(["-map", "[a]"])
                else:
                    cmd.extend(["-map", "[null_a]"])
            
            # 编码参数
            if gpu_encoder:
                cmd.extend(["-c:v", gpu_encoder, "-cq", "18", "-pix_fmt", "yuv420p"])
            else:
                cmd.extend(["-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p"])
                
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])
            
            if not use_audio:
                cmd.extend(["-shortest"])

            cmd.append(out_path)
            
            startupinfo = None
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)
            return out_path
        
        session_id = uuid.uuid4().hex[:8]
        print(f"\n[Multi-Fast-Path] 侦测到多片段串接场景！启动并发归一化流水线 (片段数: {len(clips)})...")
        
        max_workers = min(len(clips), 4)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for idx, clip_cfg in enumerate(clips):
                out_p = os.path.join(CACHE_DIR, f"norm_{session_id}_{idx}.mp4")
                temp_files.append(out_p)
                futures.append(executor.submit(_normalize_clip, clip_cfg, out_p, idx))
                
            for f in futures:
                f.result() 
                
        print("[Multi-Fast-Path] 标准化分片出线，启动毫秒级物理缝合...")
        
        concat_txt_path = os.path.join(CACHE_DIR, f"concat_list_{session_id}.txt")
        with open(concat_txt_path, "w", encoding="utf-8") as f:
            for tf in temp_files:
                f.write(f"file '{tf.replace(chr(92), '/')}'\n")
                
        concat_cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_txt_path,
            "-c", "copy",
            output_path
        ]
        
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
        subprocess.run(concat_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, check=True)
        
        print(f"[Multi-Fast-Path] 多片段极速缝合完毕！")
        
        for tf in temp_files:
            try:
                os.remove(tf)
            except:
                pass
        try:
            os.remove(concat_txt_path)
        except:
            pass
            
        return output_path
