"""
视频合成工具 — 使用 ffmpeg 合成棋盘动画和讲解音频为最终视频
字幕已直接嵌入视频帧中，此脚本只负责音视频混流。

合成时会在音频前添加片头时长的静音延迟，确保片头画面播放完毕后再开始讲解。
"""

import sys
import subprocess
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 片头时长（秒），需与 render_board.py 中 intro_secs 保持一致
INTRO_SECS = 5.0


def get_ffmpeg_path():
    """获取 ffmpeg 可执行文件路径"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, Exception):
        pass
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"], capture_output=True, timeout=5
        )
        if result.returncode == 0:
            return "ffmpeg"
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def synthesize(
    video_path: Path,
    audio_path: Path,
    output_path: Path
) -> bool:
    """
    使用 ffmpeg 合成最终视频 —— 纯音视频混流。

    Args:
        video_path: 棋盘动画视频（已含嵌入式字幕）
        audio_path: 讲解音频
        output_path: 输出视频路径

    Returns:
        是否成功
    """
    ffmpeg = get_ffmpeg_path()
    if ffmpeg is None:
        print("❌ 无法找到 ffmpeg")
        print("   请安装: pip install imageio-ffmpeg")
        return False

    # 检查输入文件
    if not video_path.exists():
        print(f"❌ 视频文件不存在: {video_path}")
        return False
    if not audio_path.exists():
        print(f"❌ 音频文件不存在: {audio_path}")
        return False

    print(f"视频文件: {video_path.name}")
    print(f"音频文件: {audio_path.name}")
    print(f"字幕已嵌入视频帧中 ✓")

    # 构建 ffmpeg 命令 — 音频加片头静音延迟，确保片头画面播完才开始讲解
    # 片头时长 (秒)
    intro_secs = 5.0

    cmd = [
        ffmpeg,
        "-i", str(video_path),
        "-i", str(audio_path),
        "-filter_complex",
        # 给音频添加静音延迟：片头期间静音，片头结束后音频正常播放
        f"[1:a]adelay={int(intro_secs * 1000)}|{int(intro_secs * 1000)}[delayed]",
        "-map", "0:v:0",         # 视频流
        "-map", "[delayed]",     # 延迟后的音频流
        "-c:v", "copy",          # 视频流直接复制（无需重编码）
        "-c:a", "aac",           # 音频编码
        "-b:a", "128k",
        "-shortest",             # 以较短流为准
        "-movflags", "+faststart",
        "-y",
        str(output_path)
    ]

    print(f"\n正在合成视频...")
    print("(视频流直接复制，速度很快)")

    try:
        result = subprocess.run(cmd, capture_output=False, timeout=600)
        if result.returncode == 0:
            print(f"\n✓ 视频已创建: {output_path}")
            return True
        else:
            print(f"\n❌ ffmpeg 合成失败 (returncode={result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print("\n❌ 视频合成超时")
        return False
    except FileNotFoundError:
        print(f"\n❌ 找不到 ffmpeg: {ffmpeg}")
        return False


def main():
    script_dir = Path(__file__).parent

    print("=" * 60)
    print("🎬 视频合成工具 (音视频混流)")
    print("=" * 60)

    video_file = script_dir / "board_animation.mp4"
    audio_file = script_dir / "commentary.mp3"

    missing_files = []
    if not video_file.exists():
        print(f"❌ 缺失: {video_file.name}")
        missing_files.append("video")
    else:
        print(f"✓ {video_file.name}")
        size_mb = video_file.stat().st_size / (1024 * 1024)
        print(f"  大小: {size_mb:.2f} MB, 分辨率: 1080×810")

    if not audio_file.exists():
        print(f"❌ 缺失: {audio_file.name}")
        missing_files.append("audio")
    else:
        print(f"✓ {audio_file.name}")
        size_mb = audio_file.stat().st_size / (1024 * 1024)
        print(f"  大小: {size_mb:.2f} MB")

    if missing_files:
        print(f"\n❌ 缺少必要文件: {', '.join(missing_files)}")
        print("请先运行 pipeline.py 生成所有中间文件")
        return

    output_file = script_dir / "final_video.mp4"
    if output_file.exists():
        output_file.unlink()

    if synthesize(video_file, audio_file, output_file):
        print("\n" + "=" * 60)
        print("✅ 视频合成成功！")
        print("=" * 60)
        print(f"\n📹 输出文件: {output_file}")
        if output_file.exists():
            file_size_mb = output_file.stat().st_size / (1024 * 1024)
            print(f"   大小: {file_size_mb:.2f} MB")
    else:
        print("\n❌ 视频合成失败")


if __name__ == "__main__":
    main()