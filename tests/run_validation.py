import os
import sys
import json

# 将 src 目录加入 Python 路径，以方便导入
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "src"))

from skills.video_add_clip import VideoAddClipSkill
from skills.video_modify_clip import VideoModifyClipSkill
from skills.video_export import VideoExportSkill
from core.timeline_manager import TimelineManager

def main():
    print("--- 正在验证非破坏性软编辑架构 ---")
    
    test_dir = os.path.join(os.path.dirname(__file__), "test_data")
    os.makedirs(test_dir, exist_ok=True)
    source_path = os.path.join(test_dir, "source.mp4")
    
    if not os.path.exists(source_path):
        from moviepy import ColorClip
        c = ColorClip(size=(640, 360), color=(255, 0, 0), duration=5.0).with_fps(30)
        c.write_videofile(source_path, codec="libx264", logger=None)
        c.close()

    # 清空之前可能残留的项目状态
    TimelineManager.reset_timeline()
    
    # 1. 测试添加片段 (无缝软操作)
    add_skill = VideoAddClipSkill()
    res1 = add_skill.execute({
        "source_path": source_path,
        "trim_in": 1.0,
        "trim_out": 4.0,
        "speed_factor": 1.0,
        "reverse": False,
        "rotate": 0,
        "keep_audio": False
    })
    print("添加片段 1:", res1)
    
    res2 = add_skill.execute({
        "source_path": source_path,
        "trim_in": 0.0,
        "trim_out": 2.0,
        "speed_factor": 1.0,
        "reverse": False,
        "rotate": 0,
        "keep_audio": False
    })
    print("添加片段 2:", res2)

    # 2. 测试修改片段属性 (倍速与旋转)
    mod_skill = VideoModifyClipSkill()
    res3 = mod_skill.execute({
        "target_index": -1, # 修改最后加入的那个
        "speed_factor": 2.0,
        "reverse": True,
        "rotate": 90
    })
    print("修改属性:", res3)
    
    # 3. 验证 JSON 落盘
    tl = TimelineManager.get_current_timeline()
    assert len(tl.tracks["video"].clips) == 2, "时间线上必须有两个片段"
    assert tl.tracks["video"].clips[-1].speed_factor == 2.0, "参数未正确落盘"
    assert tl.tracks["video"].clips[-1].rotate == 90, "参数未正确落盘"
    assert tl.tracks["video"].clips[-1].reverse is False, "使用代理文件后时间线 reverse 应为 False"
    assert "reverse_cache" in tl.tracks["video"].clips[-1].source, "源视频应被重写为代理视频路径"
    print("[Success] 项目配置数据状态树验证成功！")

    # 4. 测试最终物理导出
    output_path = os.path.join(test_dir, "non_destructive_export.mp4")
    exp_skill = VideoExportSkill()
    res4 = exp_skill.execute({
        "output_path": output_path,
        "clear_timeline_after": True
    })
    print("最终渲染导出:", res4)
    
    assert os.path.exists(output_path), "最终渲染文件必须存在"
    print("[Success] 全局极致 GPU 渲染验证成功！")

    print("\n=================================================")
    print("[Congratulations] 非破坏性时间线编辑流程测试完全通过！")
    print("=================================================")

if __name__ == "__main__":
    main()
