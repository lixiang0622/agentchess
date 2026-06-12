"""
视频合成工具 - 使用 imageio-ffmpeg 直接调用（不依赖 moviepy）
"""

import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def get_ffmpeg_path():
    """获取 ffmpeg 执行文件路径"""
    try:
        import imageio_ffmpeg
        ffmpeg_path = imageio_ffmpeg.get_ffmpeg()
        return ffmpeg_path
    except:
        # 尝试直接调用 ffmpeg
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return "ffmpeg"
        return None


def synthesize_video_ffmpeg(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path
) -> bool:
    """
    使用 ffmpeg 直接合成视频
    
    Args:
        video_path: 棋盘动画视频
        audio_path: 讲解音频
        subtitle_path: 字幕文件
        output_path: 输出视频
    
    Returns:
        是否成功
    """
    # 获取 ffmpeg 路径
    ffmpeg = get_ffmpeg_path()
    
    if not ffmpeg:
        print("❌ 无法找到 ffmpeg")
        print("   尝试其他方案...")
        return False
    
    print(f"使用 FFmpeg: {ffmpeg}")
    print(f"\n正在合成视频...")
    print(f"  视频: {video_path.name}")
    print(f"  音频: {audio_path.name}")
    print(f"  字幕: {subtitle_path.name}")
    print(f"  输出: {output_path.name}\n")
    
    # FFmpeg 命令
    cmd = [
        ffmpeg,
        "-i", str(video_path),
        "-i", str(audio_path),
        "-i", str(subtitle_path),
        "-c:v", "copy",
        "-c:a", "aac",
        "-c:s", "mov_text",
        "-metadata:s:s:0", "language=zho",
        "-shortest",
        "-y",  # 覆盖输出文件
        str(output_path)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=False)
        return result.returncode == 0
    except Exception as e:
        print(f"❌ 合成失败: {e}")
        return False


def synthesize_with_imageio(
    video_path: Path,
    audio_path: Path,
    subtitle_path: Path,
    output_path: Path
) -> bool:
    """
    使用 imageio + ffmpeg 合成视频
    """
    print("正在使用 imageio 读取视频...")
    
    try:
        import imageio
        import numpy as np
    except ImportError:
        print("❌ 需要 imageio: pip install imageio")
        return False
    
    try:
        # 读取输入视频的信息
        reader = imageio.get_reader(str(video_path))
        fps = reader.get_meta_data()['fps']
        
        print(f"视频信息: FPS={fps}")
        
        # 使用 ffmpeg 直接处理（最稳定）
        ffmpeg = get_ffmpeg_path()
        if not ffmpeg:
            print("❌ 无法找到 ffmpeg")
            return False
        
        # 构建 ffmpeg 命令
        cmd = [
            ffmpeg,
            "-i", str(video_path),
            "-i", str(audio_path),
            "-vf", "subtitles=" + str(subtitle_path).replace("\\", "/"),
            "-c:v", "libx264",
            "-preset", "fast",
            "-c:a", "aac",
            "-shortest",
            "-y",
            str(output_path)
        ]
        
        print("正在合成视频（包含字幕）...")
        result = subprocess.run(cmd, capture_output=False)
        return result.returncode == 0
        
    except Exception as e:
        print(f"❌ 合成失败: {e}")
        return False


def main():
    script_dir = Path(__file__).parent
    
    print("="*60)
    print("🎬 视频合成工具 (FFmpeg 直接调用)")
    print("="*60)
    
    # 检查输入文件
    video_file = script_dir / "board_animation.mp4"
    audio_file = script_dir / "commentary.mp3"
    subtitle_file = script_dir / "commentary.srt"
    
    print("\n检查输入文件...")
    
    missing = []
    if not video_file.exists():
        print(f"❌ {video_file.name}")
        missing.append("video")
    else:
        print(f"✓ {video_file.name}")
    
    if not audio_file.exists():
        print(f"❌ {audio_file.name}")
        missing.append("audio")
    else:
        print(f"✓ {audio_file.name}")
    
    if not subtitle_file.exists():
        print(f"❌ {subtitle_file.name}")
        missing.append("subtitle")
    else:
        print(f"✓ {subtitle_file.name}")
    
    if missing:
        print(f"\n❌ 缺少文件: {', '.join(missing)}")
        return
    
    # 合成视频
    output_file = script_dir / "final_video.mp4"
    
    print("\n" + "="*60)
    
    # 先尝试 ffmpeg 方法
    success = synthesize_video_ffmpeg(video_file, audio_file, subtitle_file, output_file)
    
    if success and output_file.exists():
        print("\n" + "="*60)
        print("✅ 视频合成成功！")
        print("="*60)
        size_mb = output_file.stat().st_size / (1024*1024)
        print(f"\n📹 输出: {output_file.name}")
        print(f"   大小: {size_mb:.2f} MB")
        print("\n✨ 完成！")
    else:
        print("\n⚠ FFmpeg 方法失败，尝试 imageio 方法...")
        success = synthesize_with_imageio(video_file, audio_file, subtitle_file, output_file)
        
        if success and output_file.exists():
            print("\n✅ 视频合成成功！")
            size_mb = output_file.stat().st_size / (1024*1024)
            print(f"\n📹 输出: {output_file.name}")
            print(f"   大小: {size_mb:.2f} MB")
        else:
            print("\n❌ 所有合成方法都失败了")
            print("\n排查建议:")
            print("  1. 检查 ffmpeg 是否正确安装")
            print("  2. 检查输入文件是否完整")
            print("  3. 尝试手动运行 ffmpeg 命令")


if __name__ == "__main__":
    main()
