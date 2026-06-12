"""
棋盘动画渲染工具 - 不使用 moviepy（直接用 ffmpeg）
"""

import sys
import subprocess
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

try:
    import chess
    import chess.pgn
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ 缺少必要库")
    print("   pip install python-chess Pillow")
    sys.exit(1)


class ChessBoardRenderer:
    """棋盘渲染器"""
    
    def __init__(self, square_size: int = 60):
        self.square_size = square_size
        self.board_size = 8 * square_size
        self.width = 480
        self.height = 480
        
        self.colors = {
            "light": (240, 217, 181),
            "dark": (181, 136, 99),
            "highlight": (186, 202, 43),
            "border": (50, 50, 50),
        }
        
        self.pieces = {
            'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
            'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
        }

        # 加载包含国际象棋符号的字体
        self.font = None
        font_candidates = [
            ("seguisym.ttf", "Segoe UI Symbol"),
            ("seguiemj.ttf", "Segoe UI Emoji"),
            ("segoeui.ttf", "Segoe UI"),
            ("DejaVuSans.ttf", "DejaVu Sans"),
            ("arial.ttf", "Arial"),
        ]
        for font_name, _ in font_candidates:
            try:
                self.font = ImageFont.truetype(font_name, 40)
                break
            except (OSError, IOError):
                continue

        if self.font is None:
            self.font = ImageFont.load_default()

    def render_board(self, board: chess.Board, highlights: list = None) -> Image.Image:
        """渲染棋盘"""
        img = Image.new('RGB', (self.width, self.height), 'white')
        draw = ImageDraw.Draw(img)
        
        x_offset = (self.width - self.board_size) // 2
        y_offset = (self.height - self.board_size) // 2
        
        for rank in range(8):
            for file in range(8):
                x = x_offset + file * self.square_size
                y = y_offset + (7 - rank) * self.square_size
                
                square = chess.square(file, rank)
                if highlights and square in highlights:
                    color = self.colors["highlight"]
                else:
                    color = self.colors["light"] if (file + rank) % 2 == 0 else self.colors["dark"]
                
                draw.rectangle(
                    [x, y, x + self.square_size, y + self.square_size],
                    fill=color,
                    outline=self.colors["border"]
                )
                
                piece = board.piece_at(square)
                if piece:
                    piece_char = self.pieces.get(str(piece), str(piece))
                    text_x = x + self.square_size // 2
                    text_y = y + self.square_size // 2
                    draw.text((text_x, text_y), piece_char, fill='black', font=self.font, anchor='mm')
        
        return img
    
    def render_sequence(self, pgn_path: Path, output_dir: Path, delay: int = 2) -> int:
        """渲染棋盘序列到图片"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        with pgn_path.open("r", encoding="utf-8") as f:
            game = chess.pgn.read_game(f)
        
        if not game:
            print("❌ 无法读取 PGN 文件")
            return 0
        
        board = game.board()
        frame_count = 0
        
        # 初始棋盘
        img = self.render_board(board)
        frame_path = output_dir / f"frame_{frame_count:04d}.png"
        img.save(str(frame_path))
        frame_count += 1
        
        # 每一步棋的多个帧（用于延长显示时间）
        for move in game.mainline_moves():
            highlights = [move.from_square, move.to_square]
            
            # 显示走棋前的棋盘
            img = self.render_board(board, highlights)
            
            # 重复多个帧以延长显示时间
            for _ in range(delay):
                frame_path = output_dir / f"frame_{frame_count:04d}.png"
                img.save(str(frame_path))
                frame_count += 1
            
            board.push(move)
        
        # 最后的棋盘多重复几帧
        img = self.render_board(board)
        for _ in range(delay * 3):
            frame_path = output_dir / f"frame_{frame_count:04d}.png"
            img.save(str(frame_path))
            frame_count += 1
        
        return frame_count


def get_ffmpeg_path():
    """获取 ffmpeg 路径"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg()
    except:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            timeout=5
        )
        if result.returncode == 0:
            return "ffmpeg"
        return None


def create_video_from_frames(frame_dir: Path, output_video: Path, fps: int = 15) -> bool:
    """使用 ffmpeg 从图片序列创建视频"""
    ffmpeg = get_ffmpeg_path()
    
    if not ffmpeg:
        print("❌ 无法找到 ffmpeg")
        return False
    
    # 检查图片
    frame_files = sorted(frame_dir.glob("frame_*.png"))
    if not frame_files:
        print(f"❌ 找不到图片在 {frame_dir}")
        return False
    
    print(f"正在从 {len(frame_files)} 张图片创建视频（FPS={fps})...")
    
    # ffmpeg 命令
    input_pattern = str(frame_dir / "frame_%04d.png")
    
    cmd = [
        ffmpeg,
        "-framerate", str(fps),
        "-i", input_pattern,
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        "-y",
        str(output_video)
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=False)
        if result.returncode == 0:
            print(f"✓ 视频创建成功: {output_video}")
            return True
        else:
            print("❌ 视频创建失败")
            return False
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return False


def main():
    script_dir = Path(__file__).parent
    pgn_path = script_dir / "lichess_pgn_2026.05.05_pjykk_vs_lixiang23.bEHmt9NK.pgn"
    
    # 查找 PGN 文件
    pgn_files = list(script_dir.glob("lichess_pgn*.pgn"))
    if pgn_files:
        pgn_path = pgn_files[0]
    
    if not pgn_path.exists():
        print(f"❌ PGN 文件不存在: {pgn_path}")
        return
    
    print("="*60)
    print("🎨 棋盘渲染工具（无 moviepy）")
    print("="*60)
    
    renderer = ChessBoardRenderer(square_size=60)
    output_dir = script_dir / "board_frames"
    
    # 生成图片序列
    print(f"\n正在渲染棋盘...")
    frame_count = renderer.render_sequence(pgn_path, output_dir, delay=2)
    
    if frame_count == 0:
        print("❌ 渲染失败")
        return
    
    print(f"✓ 渲染完成: {frame_count} 帧")
    print(f"✓ 图片已保存到: {output_dir}")
    
    # 生成视频
    output_video = script_dir / "board_animation.mp4"
    print(f"\n正在创建视频...")
    
    if create_video_from_frames(output_dir, output_video, fps=15):
        print("\n✅ 棋盘动画生成成功！")
    else:
        print("\n❌ 视频生成失败")


if __name__ == "__main__":
    main()
