"""
FFmpeg 视频合成脚本
将棋盘动画、讲解音频、字幕合成为最终视频
"""

import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def check_ffmpeg() -> bool:
    """检查 FFmpeg 是否已安装"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def synthesize_video(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path
) -> bool:
    """
    使用 FFmpeg 合成视频
    
    Args:
        video_path: 棋盘动画视频
        audio_path: 讲解音频
        subtitle_path: 字幕文件
        output_path: 输出视频
    
    Returns:
        是否成功
    """
    # FFmpeg 命令
    # -c:v copy: 视频流直接复制（不重新编码，快速）
    # -c:a aac: 音频编码为 AAC
    # -c:s mov_text: 字幕编码为 mov_text（MP4 兼容）
    cmd = [
        "ffmpeg",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-i", str(subtitle_path),
        "-c:v", "copy",           # 视频直接复制
        "-c:a", "aac",            # 音频 AAC 编码
        "-c:s", "mov_text",       # 字幕格式
        "-metadata:s:s:0", "language=zho",  # 字幕语言标记
        "-shortest",              # 以最短的流为准
        str(output_path)
    ]
    
    print("正在合成视频...")
    print(f"命令: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd, capture_output=False)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 合成失败: {e}")
        return False


def main():
    script_dir = Path(__file__).parent
    
    print("="*60)
    print("🎬 FFmpeg 视频合成工具")
    print("="*60)
    
    # 检查必要的文件
    video_file = script_dir / "board_animation.mp4"
    audio_file = script_dir / "commentary.mp3"
    subtitle_file = script_dir / "commentary.srt"
    
    print("\n检查输入文件...")
    missing_files = []
    
    if not video_file.exists():
        print(f"❌ 缺失: {video_file.name}")
        missing_files.append("video")
    else:
        print(f"✓ {video_file.name}")
    
    if not audio_file.exists():
        print(f"❌ 缺失: {audio_file.name}")
        missing_files.append("audio")
    else:
        print(f"✓ {audio_file.name}")
    
    if not subtitle_file.exists():
        print(f"❌ 缺失: {subtitle_file.name}")
        missing_files.append("subtitle")
    else:
        print(f"✓ {subtitle_file.name}")
    
    if missing_files:
        print(f"\n❌ 缺少必要文件: {', '.join(missing_files)}")
        print("请先运行 pipeline.py 生成所有中间文件")
        return
    
    # 检查 FFmpeg
    print("\n检查 FFmpeg...")
    if not check_ffmpeg():
        print("❌ FFmpeg 未安装或不在 PATH 中")
        print("\n安装方法:")
        print("  Windows: choco install ffmpeg")
        print("         或访问 https://ffmpeg.org/download.html")
        print("  或添加 FFmpeg 目录到系统 PATH")
        return
    
    print("✓ FFmpeg 已安装")
    
    # 开始合成
    print("\n" + "="*60)
    output_file = script_dir / "final_video.mp4"
    
    if synthesize_video(video_file, audio_file, subtitle_file, output_file):
        print("\n" + "="*60)
        print("✅ 视频合成成功！")
        print("="*60)
        print(f"\n📹 输出文件: {output_file}")
        print(f"   大小: {output_file.stat().st_size / (1024*1024):.2f} MB")
        print("\n✨ 视频已准备好！")
    else:
        print("\n❌ 视频合成失败")


if __name__ == "__main__":
    main()
