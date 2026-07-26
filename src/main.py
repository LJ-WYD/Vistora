import argparse
import json
import os
import sys

# 将当前 src 目录加入 Python 搜索路径，以确保在任何工作目录下运行皆能正常导入
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.timeline import TimelineConfig, TimelineRenderer
from skills.video_add_clip import VideoAddClipSkill
from skills.video_modify_clip import VideoModifyClipSkill
from skills.video_export import VideoExportSkill
from skills.video_timelapse import VideoTimelapseSkill
from skills.video_clear_timeline import VideoClearTimelineSkill
from skills.video_apply_manual_edits import VideoApplyManualEditsSkill
from skills.video_restore_timeline_checkpoint import (
    VideoRestoreTimelineCheckpointSkill,
)

# 注册非破坏性编辑原子技能
SKILLS = {
    "VideoAddClipSkill": VideoAddClipSkill(),
    "VideoModifyClipSkill": VideoModifyClipSkill(),
    "VideoExportSkill": VideoExportSkill(),
    "VideoTimelapseSkill": VideoTimelapseSkill(),
    "VideoClearTimelineSkill": VideoClearTimelineSkill(),
    "VideoApplyManualEditsSkill": VideoApplyManualEditsSkill(),
    "VideoRestoreTimelineCheckpointSkill": (
        VideoRestoreTimelineCheckpointSkill()
    ),
}

def list_skills():
    """
    列出所有已注册的技能及其 Schema 信息。
    这允许上层 Agent 动态查询并获取每个 Skill 的调用协议规范。
    """
    schemas = []
    for skill in SKILLS.values():
        schemas.append(skill.get_schema())
    print(json.dumps(schemas, indent=2, ensure_ascii=False))

def render_timeline(timeline_json_path: str, output_path: str):
    """
    读取时间线配置文件并调用渲染器进行渲染输出。
    """
    with open(timeline_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    config = TimelineConfig(**data)
    renderer = TimelineRenderer(config)
    print(f"正在读取声明式时间线: {timeline_json_path}")
    print(f"开始渲染视频 -> {output_path}")
    renderer.render(output_path)
    print("渲染操作完成！")

def run_skill(skill_name: str, params_json: str):
    """
    直接通过命令行运行某个特定 Skill。
    这是操作层 Agent 通过终端调用 Skill 的主要接口形式。
    """
    if skill_name not in SKILLS:
        print(f"错误: 未找到该技能 '{skill_name}'", file=sys.stderr)
        sys.exit(1)
        
    skill = SKILLS[skill_name]
    try:
        params_dict = json.loads(params_json)
    except json.JSONDecodeError as e:
        print(f"错误: 参数 JSON 字符串格式非法: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"正在执行技能: {skill_name}...")
    try:
        result = skill.execute(params_dict)
        print(f"执行成功！返回数据:\n{json.dumps(result, indent=2, ensure_ascii=False)}")
    except Exception as e:
        print(f"执行失败，抛出异常: {e}", file=sys.stderr)
        sys.exit(1)

def chat_loop():
    """
    启动交互式对话循环，允许用户用自然语言命令 Agent 剪辑视频
    """
    from agent.operator_agent import OperatorAgent
    agent = OperatorAgent(SKILLS)
    print("==========================================================")
    print("🎬 Vistora AI 操作层 Agent 对话交互终端启动成功！")
    print("您可以直接使用口语指令控制视频进行裁剪、拼接、倒放、变速或延时合成。")
    print("输入 'exit' 或 'quit' 可随时退出。")
    print("==========================================================")

    while True:
        try:
            prompt = input("\n👤 创作者: ")
            if not prompt.strip():
                continue
            if prompt.strip().lower() in ("exit", "quit", "q"):
                print("退出成功。感谢使用 Vistora！")
                break
            
            response = agent.run(prompt)
            print(f"\n🤖 Agent:\n{response}")
        except KeyboardInterrupt:
            print("\n退出成功。")
            break
        except Exception as e:
            print(f"\n❌ 对话执行异常: {e}")


def preview_timeline(
    timeline_path: str | None,
    media_roots: list[str],
    host: str,
    port: int,
    plan_review_path: str | None,
):
    """Start Vistora's local snapshot-first visual timeline preview."""
    from timeline_preview import run_preview_server

    run_preview_server(
        timeline_path=timeline_path,
        media_roots=media_roots,
        host=host,
        port=port,
        skill_registry=SKILLS,
        plan_review_path=plan_review_path,
    )


def main():
    parser = argparse.ArgumentParser(description="Vistora 命令行交互入口")
    subparsers = parser.add_subparsers(dest="command", help="可选子命令")
    
    # 1. list-skills 子命令
    subparsers.add_parser("list-skills", help="获取所有原子剪辑技能描述及其 JSON Schema")
    
    # 2. render 子命令
    render_parser = subparsers.add_parser("render", help="根据声明式时间线配置 JSON 渲染并导出视频")
    render_parser.add_argument("--config", required=True, help="时间线 JSON 配置文件的路径")
    render_parser.add_argument("--output", required=True, help="输出的目标视频路径 (.mp4)")
    
    # 3. run-skill 子命令
    run_parser = subparsers.add_parser("run-skill", help="直接调用执行某个原子剪辑技能")
    run_parser.add_argument("--name", required=True, help="要调用的技能名称")
    run_parser.add_argument("--params", required=True, help="符合该技能 Schema 的参数 JSON 字符串")
    
    # 4. chat 子命令
    subparsers.add_parser("chat", help="启动人机交互式 Agent 视频剪辑对话")

    preview_parser = subparsers.add_parser(
        "preview",
        help="Start the local snapshot-first visual timeline preview",
    )
    preview_parser.add_argument(
        "--timeline",
        help=(
            "Optional legacy or versioned timeline JSON path. "
            "Defaults to the current TimelineManager state."
        ),
    )
    preview_parser.add_argument(
        "--media-root",
        action="append",
        default=[],
        help=(
            "Explicit directory allowed to serve media from. "
            "Repeat for multiple roots; omit to disable media serving."
        ),
    )
    preview_parser.add_argument(
        "--host",
        default="127.0.0.1",
        choices=["127.0.0.1", "::1", "localhost"],
        help="Loopback interface to bind (default: 127.0.0.1).",
    )
    preview_parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Local TCP port (default: 8765).",
    )
    preview_parser.add_argument(
        "--plan-review",
        help=(
            "Optional versioned plan-diff request JSON. It is previewed "
            "read-only; this command never confirms or executes the plan."
        ),
    )

    args = parser.parse_args()
    
    # 根据指令调用对应逻辑
    if args.command == "list-skills":
        list_skills()
    elif args.command == "render":
        render_timeline(args.config, args.output)
    elif args.command == "run-skill":
        run_skill(args.name, args.params)
    elif args.command == "chat":
        chat_loop()
    elif args.command == "preview":
        preview_timeline(
            args.timeline,
            args.media_root,
            args.host,
            args.port,
            args.plan_review,
        )
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
