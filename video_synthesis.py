"""
视频合成框架
使用 moviepy + chess 库生成棋盘动画，合成讲解视频
"""

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def install_dependencies():
    """检查并提示安装必要库"""
    required = {
        "moviepy": "moviepy",
        "chess": "python-chess",
        "PIL": "Pillow",
        "pygame": "pygame",  # 用于棋盘渲染（可选）
    }
    
    missing = []
    for lib, package in required.items():
        try:
            __import__(lib)
        except ImportError:
            missing.append(package)
    
    if missing:
        print("❌ 缺少必要库:")
        for pkg in missing:
            print(f"   pip install {pkg}")
        return False
    
    return True


def create_board_animation(pgn_path: Path, output_video: Path, fps: int = 30) -> bool:
    """
    从 PGN 创建棋盘动画
    
    每一步棋显示 2 秒，可与讲解词同步
    """
    try:
        import chess.pgn
        from moviepy.editor import ImageClip, concatenate_videoclips
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("❌ 缺少必要库，请运行:")
        print("   pip install python-chess moviepy Pillow")
        return False
    
    print(f"正在从 {pgn_path} 创建棋盘动画...")
    
    # 读取 PGN
    with pgn_path.open("r", encoding="utf-8") as f:
        game = chess.pgn.read_game(f)
    
    board = game.board()
    clips = []
    
    # 简单实现：每步生成一张棋盘图片
    # 实际项目中应该用专门的棋盘渲染库
    
    print("❌ 完整实现需要棋盘渲染库（如 chess-graphics 或自定义渲染）")
    print("\n推荐方案:")
    print("1. 使用 Lichess API 获取棋盘 PNG")
    print("2. 使用 chess-graphics 库生成棋盘图片")
    print("3. 手动渲染（使用 PIL/Pillow）")
    
    return False


def sync_audio_and_subtitles(video_path: Path, audio_path: Path, subtitle_path: Path, output_path: Path) -> bool:
    """
    合并视频、音频和字幕
    
    关键参数：
    - video_path: 棋盘动画视频
    - audio_path: TTS 音频（MP3）
    - subtitle_path: 字幕文件（SRT）
    - output_path: 输出视频
    """
    try:
        from moviepy.editor import VideoFileClip, AudioFileClip
        import subprocess
    except ImportError:
        print("❌ 缺少 moviepy")
        return False
    
    print(f"正在合成视频...")
    print(f"  视频: {video_path}")
    print(f"  音频: {audio_path}")
    print(f"  字幕: {subtitle_path}")
    
    try:
        # 加载视频和音频
        video = VideoFileClip(str(video_path))
        audio = AudioFileClip(str(audio_path))
        
        # 调整视频长度以匹配音频
        if video.duration < audio.duration:
            print("⚠ 视频时长短于音频，可能需要调整")
        
        # 合并音频
        video_with_audio = video.set_audio(audio)
        
        # 使用 ffmpeg 添加字幕
        # （moviepy 对字幕支持有限，这里用 ffmpeg）
        cmd = [
            "ffmpeg",
            "-i", str(video_path),
            "-i", str(audio_path),
            "-i", str(subtitle_path),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-c:s", "mov_text",
            "-disposition:s:0", "default",
            str(output_path)
        ]
        
        print("正在调用 ffmpeg...")
        result = subprocess.run(cmd, capture_output=True)
        
        if result.returncode == 0:
            print(f"✓ 视频合成成功: {output_path}")
            return True
        else:
            print(f"❌ ffmpeg 错误: {result.stderr.decode()}")
            return False
    
    except Exception as e:
        print(f"❌ 合成失败: {e}")
        return False


def quick_start_guide():
    """快速开始指南"""
    print("\n" + "="*60)
    print("视频合成 - 快速开始")
    print("="*60)
    
    print("""
【现在你有了以下文件】
- analysis_result.json      : 棋谱分析数据
- commentary.txt            : 讲解词文本
- commentary.mp3            : TTS 语音
- commentary.srt            : SRT 字幕
- merged_analysis_commentary.json : 完整数据
- video_script.tsv          : 视频剧本

【接下来的步骤】

1️⃣ 生成棋盘动画
   方案 A: 使用 Lichess API
   ------
   import requests
   for step_num in range(1, total_steps):
       fen = steps[step_num]["board_fen"]  # 需要在 analyse.py 中保存 FEN
       url = f"https://lichess.org/api/board/pgn?...{pgn}...&moves={step_num}"
       img = requests.get(url).content
       save_as_image(f"frame_{step_num}.png")
   
   方案 B: 使用棋盘库（推荐）
   ------
   pip install python-chess Pillow
   
   import chess
   from PIL import Image
   board = chess.Board()
   # 自定义渲染函数或使用现有库
   image = render_board(board)
   image.save(f"frame.png")
   
   方案 C: 调用现有工具
   ------
   使用 Stockfish 配套的 GUI（如 Arena）截图

2️⃣ 将所有帧合成视频
   ------
   from moviepy.editor import ImageSequenceClip
   
   images = sorted(glob.glob("frame_*.png"))
   clip = ImageSequenceClip(images, fps=30)
   clip.write_videofile("board_animation.mp4")

3️⃣ 合并视频、音频、字幕
   ------
   ffmpeg -i board_animation.mp4 \\
           -i commentary.mp3 \\
           -i commentary.srt \\
           -c:v libx264 \\
           -c:a aac \\
           -c:s mov_text \\
           final_video.mp4

4️⃣ 优化和渲染
   - 添加标题、字幕样式
   - 添加背景音乐、转场效果
   - 调整字幕位置、字体大小
   - 压缩并导出最终版本

【推荐工具】
- DaVinci Resolve: 专业视频编辑（免费版功能强大）
- Shotcut: 开源视频编辑
- FFmpeg: 命令行视频处理（强大）
- Python moviepy: 脚本自动化视频制作

【下一个任务】
请帮我创建棋盘渲染脚本（render_board.py）
或告诉我你想使用哪个方案。
""")


def main():
    print("\n" + "="*60)
    print("视频合成框架")
    print("="*60)
    
    # 检查依赖
    if not install_dependencies():
        print("\n请先安装必要库")
        return
    
    print("\n✓ 所有依赖库已安装\n")
    
    # 显示快速开始
    quick_start_guide()
    
    # 后续选项
    print("\n下一步:")
    print("1. 创建棋盘渲染脚本")
    print("2. 使用 FFmpeg 手动合成")
    print("3. 查看完整工作流")
    
    choice = input("\n请选择 (1/2/3): ").strip()
    
    if choice == "1":
        print("""
将创建 render_board.py，可以：
- 从棋盘位置生成 PNG 图片
- 支持高亮、标注
- 可自定义样式和分辨率

运行: python render_board.py
""")
    elif choice == "2":
        print("""
使用 FFmpeg 命令直接合成（如果已有棋盘视频）：

ffmpeg -i board_video.mp4 -i commentary.mp3 -i commentary.srt \\
  -c:v libx264 -c:a aac -c:s mov_text \\
  -disposition:s:0 default \\
  final_video.mp4

详见官方文档: https://ffmpeg.org/
""")


if __name__ == "__main__":
    main()
