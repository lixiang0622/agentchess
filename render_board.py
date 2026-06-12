"""
棋盘渲染脚本
将 PGN 棋局转换为横屏 4:3 (1080×810) 视频帧序列
- 棋盘在左侧 (560×560)
- 讲解字幕在右侧面板 (520×810)
- 使用 lichess 风格棋子图片
"""

import sys
import json
import re
import math
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


# ===================== 片头片尾配置 =====================
INTRO_TITLE = "深蓝国际象棋协会"
INTRO_SUBTITLE = "深蓝棋评"

OUTRO_TITLE = "感谢观看"
OUTRO_SUBTITLE = "深蓝棋评 · 我们下期再见"
# =======================================================


class ChessBoardRenderer:
    """国际象棋棋盘渲染器 — 横屏 4:3，棋盘左 + 字幕右，lichess 风格棋子"""

    def __init__(self, square_size: int = 70, width: int = 1080, height: int = 810):
        self.square_size = square_size
        self.board_size = 8 * square_size  # 560
        self.width = width      # 1080
        self.height = height    # 810

        # ====== 布局常量 ======
        self.board_x = 0                              # 棋盘左对齐
        self.board_y = (height - self.board_size) // 2  # 垂直居中: 125
        self.panel_x = self.board_size                 # 560, 右侧面板起点
        self.panel_width = width - self.board_size     # 520
        self.panel_padding = 24
        self.panel_text_width = self.panel_width - 2 * self.panel_padding  # 472

        # 棋盘配色
        self.colors = {
            "light":       (240, 217, 181),   # 暖浅木色（接近 Lichess）
            "dark":        (181, 136, 99),    # 暖深木色（接近 Lichess）
            "highlight":   (255, 255, 0, 100),   # 高亮黄，半透明叠加
            "last_move":   (255, 255, 0, 80),    # 上一步走棋标记（浅黄）
            "selected":    (100, 200, 80, 100),  # 选中/推荐格子（绿色）
            "check":       (255, 80, 50, 100),   # 将军警告（红色）
            "threat":      (255, 160, 60, 80),   # 威胁标记（橙色）
            "arrow":       (220, 50, 50),     # 箭头红色
            "border":      (60, 40, 20),      # 边框深棕
            "bg":          (30, 30, 30),      # 深色背景
            # 右侧面板配色
            "panel_bg":    (22, 25, 32),      # 面板背景深蓝灰
            "panel_text":  (225, 220, 210),   # 面板正文
            "panel_accent":(180, 160, 120),   # 面板强调色
            "panel_muted": (120, 110, 100),   # 面板暗淡文字
            "separator":   (80, 70, 55),      # 分隔线
        }

        # Unicode 棋子映射（备用）
        self.pieces_unicode = {
            'K': '♔', 'Q': '♕', 'R': '♖', 'B': '♗', 'N': '♘', 'P': '♙',
            'k': '♚', 'q': '♛', 'r': '♜', 'b': '♝', 'n': '♞', 'p': '♟',
        }

        # 加载棋子图片
        self.piece_images = self._load_piece_images()

        # 加载社团 logo
        self.logo_img = self._load_logo()

        # 游戏信息（由 render_sequence 设置）
        self.game_info = {}
        self.step_qualities = {}  # {move_number: quality}

    # --------------- 字体加载 ---------------
    def _load_piece_font(self, size: int = 44):
        """备用：加载棋子 Unicode 字体"""
        candidates = [
            ("C:/Windows/Fonts/seguisym.ttf",),
            ("C:/Windows/Fonts/seguiemj.ttf",),
            ("C:/Windows/Fonts/segoeui.ttf",),
            ("seguisym.ttf",),
            ("seguiemj.ttf",),
            ("DejaVuSans.ttf",),
            ("NotoSans-Regular.ttf",),
            ("arial.ttf",),
        ]
        for (name,) in candidates:
            try:
                return ImageFont.truetype(name, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    def _load_chinese_font(self, size: int = 22):
        candidates = [
            ("C:/Windows/Fonts/msyh.ttc",),       # 微软雅黑
            ("C:/Windows/Fonts/simsun.ttc",),      # 宋体
            ("C:/Windows/Fonts/simhei.ttf",),       # 黑体
            ("msyh.ttc",),
            ("NotoSansCJK-Regular.ttc",),
            ("arial.ttf",),
        ]
        for (name,) in candidates:
            try:
                return ImageFont.truetype(name, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    # --------------- 棋子图片加载 ---------------
    def _load_piece_images(self) -> dict:
        """从 pieces/ 目录加载预生成的棋子 PNG 图片"""
        pieces_dir = Path(__file__).parent / "pieces"
        mapping = {
            'K': 'wK', 'Q': 'wQ', 'R': 'wR', 'B': 'wB', 'N': 'wN', 'P': 'wP',
            'k': 'bK', 'q': 'bQ', 'r': 'bR', 'b': 'bB', 'n': 'bN', 'p': 'bP',
        }
        images = {}
        for symbol, filename in mapping.items():
            filepath = pieces_dir / f"{filename}.png"
            if filepath.exists():
                try:
                    img = Image.open(filepath).convert('RGBA')
                    # 如果需要缩放
                    target = int(self.square_size * 0.9)
                    if img.width != target:
                        img = img.resize((target, target), Image.LANCZOS)
                    images[symbol] = img
                except Exception:
                    images[symbol] = None
            else:
                images[symbol] = None

        if any(v is not None for v in images.values()):
            loaded = sum(1 for v in images.values() if v is not None)
            print(f"   ♟  已加载 {loaded}/12 枚棋子图片")
        if any(v is None for v in images.values()):
            missing = [s for s, v in images.items() if v is None]
            print(f"   ⚠ 棋子图片缺失: {missing}，使用 Unicode 备用")
        return images

    def _load_logo(self):
        """加载社团 logo 图片"""
        logo_path = Path(__file__).parent.parent / "icon.png"
        if logo_path.exists():
            try:
                img = Image.open(logo_path).convert('RGBA')
                # 缩放到合适大小（约 100px 高）
                h = 120
                w = int(img.width * h / img.height)
                img = img.resize((w, h), Image.LANCZOS)
                print(f"   🏠 已加载社团 logo: {logo_path}")
                return img
            except Exception:
                pass
        return None

    # --------------- 棋盘绘制 ---------------
    def render_board(self, board: chess.Board,
                     highlights: list = None,
                     arrows: list = None,
                     subtitle_text: str = None,
                     step_number: int = None,
                     total_steps: int = None,
                     highlight_types: dict = None,
                     move_annotation: str = None,
                     annotation_square: int = None,
                     candidate_info: dict = None,
                     branch_instruction: dict = None) -> Image.Image:
        """
        渲染横屏棋盘画面
        - 左侧：棋盘 + 棋子 + 高亮 + 箭头 + 着法标注
        - 右侧：讲解字幕面板

        Args:
            board: 当前棋盘状态
            highlights: 高亮的格子列表（统一样式）或 backward-compat
            move_annotation: 着法标注符号 ("?", "?!", "??")
            annotation_square: 标注显示在哪个格子上
            arrows: 箭头列表 [(from_sq, to_sq), ...]
            subtitle_text: 当前步骤的讲解文字
            step_number: 当前步数编号
            total_steps: 总步数
            highlight_types: 按类型分组的高亮格子 {
                "last_move": [sq1, sq2],
                "check": [king_sq],
                "selected": [sq, ...],
                "threat": [sq, ...],
            }
        """
        img = Image.new('RGB', (self.width, self.height), self.colors["panel_bg"])
        draw = ImageDraw.Draw(img)

        # 1) 棋盘背景
        board_bg = Image.new('RGB', (self.board_size, self.board_size), self.colors["bg"])
        board_draw = ImageDraw.Draw(board_bg)
        self._draw_board_squares(board_draw)
        img.paste(board_bg, (self.board_x, self.board_y))

        # 2) 高亮格子 — 支持多种类型
        overlay = Image.new('RGBA', (self.board_size, self.board_size), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        has_overlay = False

        # 如果提供了 highlight_types，按类型绘制不同颜色
        if highlight_types:
            for hl_type, squares in highlight_types.items():
                if not squares:
                    continue
                color = self.colors.get(hl_type, self.colors["highlight"])
                for sq in squares:
                    file = chess.square_file(sq)
                    rank = chess.square_rank(sq)
                    x = file * self.square_size
                    y = (7 - rank) * self.square_size
                    overlay_draw.rectangle(
                        [x, y, x + self.square_size, y + self.square_size],
                        fill=color
                    )
                    has_overlay = True
                    # 如果是 check 类型，额外绘制外边框强调
                    if hl_type == "check":
                        overlay_draw.rectangle(
                            [x + 1, y + 1, x + self.square_size - 1, y + self.square_size - 1],
                            outline=(255, 20, 20, 200), width=3
                        )

        # 向后兼容：如果传了 highlights 列表，用默认高亮色
        elif highlights:
            for sq in highlights:
                file = chess.square_file(sq)
                rank = chess.square_rank(sq)
                x = file * self.square_size
                y = (7 - rank) * self.square_size
                overlay_draw.rectangle(
                    [x, y, x + self.square_size, y + self.square_size],
                    fill=self.colors["highlight"]
                )
                has_overlay = True

        # 合成到棋盘区域
        if has_overlay:
            board_area = img.crop((self.board_x, self.board_y,
                                   self.board_x + self.board_size,
                                   self.board_y + self.board_size))
            board_area = Image.alpha_composite(
                board_area.convert('RGBA'), overlay
            ).convert('RGB')
            img.paste(board_area, (self.board_x, self.board_y))
            draw = ImageDraw.Draw(img)

        # 3) 箭头
        if arrows:
            self._draw_arrows(draw, arrows)

        # 4) 棋子
        self._draw_pieces(img, board)

        # 4.5) 着法标注 (如 "?" "?!" "??")
        if move_annotation and annotation_square is not None:
            self._draw_annotation(img, draw, annotation_square, move_annotation)

        # 5) 坐标
        self._draw_coordinates(draw)

        # 6) 分隔线
        sep_x = self.board_x + self.board_size
        draw.line([(sep_x, 0), (sep_x, self.height)],
                  fill=self.colors["separator"], width=2)

        # 7) 右侧面板
        self._render_subtitle_panel(draw, img, subtitle_text, step_number, total_steps)

        # 8) 右下角小棋盘（引擎推荐 / 支线变化 / LLM指令）
        if branch_instruction:
            # branch_instruction 优先：LLM 显式指定的 [小棋盘: ...] 指令
            info_for_mini = dict(candidate_info or {})
            info_for_mini["_board"] = (candidate_info or {}).get("_board", board.copy())
            info_for_mini["_branch_instruction"] = branch_instruction
            self._draw_branch_mini_board(img, info_for_mini)
        elif candidate_info:
            # 引擎候选走法（自动模式）
            self._draw_branch_mini_board(img, candidate_info)

        return img

    def _draw_board_squares(self, draw):
        """在棋盘区域绘制格子（相对于棋盘左上角）— a1 必须是深色格"""
        for rank in range(8):
            for file in range(8):
                x = file * self.square_size
                y = (7 - rank) * self.square_size
                # a1=(file=0,rank=0): (0+0)%2=0 → DARK ✓
                if (file + rank) % 2 == 0:
                    color = self.colors["dark"]
                else:
                    color = self.colors["light"]
                draw.rectangle(
                    [x, y, x + self.square_size, y + self.square_size],
                    fill=color
                )

    def _draw_arrows(self, draw, arrows):
        """在棋盘上绘制箭头（使用全局坐标）"""
        for arrow in arrows:
            f_file, f_rank = chess.square_file(arrow[0]), chess.square_rank(arrow[0])
            t_file, t_rank = chess.square_file(arrow[1]), chess.square_rank(arrow[1])

            fx = self.board_x + f_file * self.square_size + self.square_size // 2
            fy = self.board_y + (7 - f_rank) * self.square_size + self.square_size // 2
            tx = self.board_x + t_file * self.square_size + self.square_size // 2
            ty = self.board_y + (7 - t_rank) * self.square_size + self.square_size // 2

            # 三角形箭头
            angle = math.atan2(ty - fy, tx - fx)
            tip_len = 14
            tip_angle = 0.5

            pts = [
                (tx, ty),
                (tx - tip_len * math.cos(angle - tip_angle),
                 ty - tip_len * math.sin(angle - tip_angle)),
                (tx - tip_len * 0.4 * math.cos(angle),
                 ty - tip_len * 0.4 * math.sin(angle)),
                (tx - tip_len * math.cos(angle + tip_angle),
                 ty - tip_len * math.sin(angle + tip_angle)),
            ]

            draw.line([(fx, fy), (tx, ty)], fill=self.colors["arrow"], width=4)
            draw.polygon(pts, fill=self.colors["arrow"])

    # --------------- 着法标注 ---------------
    def _draw_annotation(self, img, draw, square: int, annotation: str):
        """在格子上绘制着法标注（类似 lichess 的 ? / ?? 标记）"""
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        sq_x = self.board_x + file * self.square_size
        sq_y = self.board_y + (7 - rank) * self.square_size

        # 标注位置：格子右上角外侧
        badge_size = int(self.square_size * 0.35)
        margin = int(self.square_size * 0.05)
        bx = sq_x + self.square_size - badge_size + margin
        by = sq_y - margin

        # 背景圆
        draw.ellipse(
            [bx, by, bx + badge_size, by + badge_size],
            fill=(200, 50, 50), outline=(160, 30, 30), width=2
        )

        # 标注文字
        try:
            ann_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf",
                                          int(badge_size * 0.65))
        except Exception:
            try:
                ann_font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf",
                                              int(badge_size * 0.65))
            except Exception:
                ann_font = ImageFont.load_default()

        text = annotation if annotation in ("?", "?!", "??") else "?"
        tb = draw.textbbox((0, 0), text, font=ann_font)
        tw, th = tb[2] - tb[0], tb[3] - tb[1]
        tx = bx + (badge_size - tw) // 2
        ty = by + (badge_size - th) // 2 - 1
        draw.text((tx, ty), text, fill=(255, 255, 255), font=ann_font)

    # --------------- 棋子绘制 ---------------
    def _draw_pieces(self, img, board):
        """绘制棋子 — 优先使用 PNG 图片，否则用 Unicode 备用"""
        piece_img_size = int(self.square_size * 0.9)
        fallback_font = None

        for square in chess.SQUARES:
            piece = board.piece_at(square)
            if not piece:
                continue

            symbol = piece.symbol()
            file = chess.square_file(square)
            rank = chess.square_rank(square)
            cx = self.board_x + file * self.square_size + self.square_size // 2
            cy = self.board_y + (7 - rank) * self.square_size + self.square_size // 2

            piece_img = self.piece_images.get(symbol)

            if piece_img is not None:
                # 使用 PNG 棋子图片（带 Alpha 通道）
                px = cx - piece_img.width // 2
                py = cy - piece_img.height // 2
                # 使用 alpha 合成
                img.paste(piece_img, (px, py), piece_img)
            else:
                # Unicode 备用方案
                if fallback_font is None:
                    fallback_font = self._load_piece_font(
                        int(self.square_size * 0.65))
                self._draw_piece_unicode(img, symbol, cx, cy, fallback_font,
                                         piece, square)

    def _draw_piece_unicode(self, img, symbol, cx, cy, font, piece, square):
        """Unicode 备用棋子绘制"""
        draw = ImageDraw.Draw(img)
        char = self.pieces_unicode.get(symbol, '?')
        is_white = symbol.isupper()
        file = chess.square_file(square)
        rank = chess.square_rank(square)

        bbox = draw.textbbox((0, 0), char, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx, ty = cx - tw // 2, cy - th // 2

        if is_white:
            so = 2
            draw.text((tx + so, ty + so), char, fill=(100, 70, 30), font=font)
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((tx + dx, ty + dy), char, fill=(20, 15, 5), font=font)
            draw.text((tx, ty), char, fill=(252, 250, 245), font=font)
        else:
            so = 2
            draw.text((tx + so, ty + so), char, fill=(40, 25, 10), font=font)
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((tx + dx, ty + dy), char, fill=(10, 5, 0), font=font)
            is_light_sq = (file + rank) % 2 == 0
            piece_body = (130, 95, 50) if is_light_sq else (180, 140, 90)
            draw.text((tx, ty), char, fill=piece_body, font=font)

    # --------------- 坐标 ---------------
    def _draw_coordinates(self, draw):
        """绘制棋盘坐标标签"""
        try:
            font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 11)
        except Exception:
            font = ImageFont.load_default()

        for file in range(8):
            x = self.board_x + file * self.square_size + self.square_size // 2 - 3
            y = self.board_y + self.board_size + 4
            draw.text((x, y), chr(ord('a') + file),
                      fill=self.colors["panel_muted"], font=font)

        for rank in range(8):
            x = self.board_x - 13
            y = self.board_y + (7 - rank) * self.square_size + self.square_size // 2 - 5
            draw.text((x, y), str(rank + 1),
                      fill=self.colors["panel_muted"], font=font)

    # --------------- 右侧字幕面板 ---------------
    def _render_subtitle_panel(self, draw, img, subtitle_text, step_number, total_steps):
        """渲染右侧 400px 讲解面板"""
        px = self.panel_x + self.panel_padding
        py = 15
        usable_width = self.panel_text_width
        usable_height = self.height - 30

        # ---- 顶部：对局信息 ----
        if self.game_info:
            info_lines = []
            white = self.game_info.get('white', '')
            black = self.game_info.get('black', '')
            opening = self.game_info.get('opening', '')
            if white and black:
                info_lines.append(f"⚪ {white}  vs  ⚫ {black}")
            if opening:
                info_lines.append(f"开局: {opening}")

            info_font = self._load_chinese_font(14)
            for line in info_lines:
                tb = draw.textbbox((0, 0), line, font=info_font)
                draw.text((px, py), line, fill=self.colors["panel_muted"], font=info_font)
                py += tb[3] - tb[1] + 4

            # 对局结果 + 结束原因
            result = self.game_info.get('result', '')
            termination = self.game_info.get('termination', '')
            if result or termination:
                result_text = result if result else ""
                term_cn = {"time forfeit": "超时", "resignation": "认输",
                           "abandoned": "弃局", "rules infraction": "违规",
                           "agreement": "协议和棋"}.get(
                    termination.lower() if termination else "", termination)
                combined = f"结果: {result_text} ({term_cn})" if result_text else f"结束: {term_cn}"
                tb = draw.textbbox((0, 0), combined, font=info_font)
                draw.text((px, py), combined, fill=(200, 160, 100), font=info_font)
                py += tb[3] - tb[1] + 4

            # 时间控制 + 剩余时间 + 时间紧张判定
            tc = self.game_info.get('time_control', '')
            wc = self.game_info.get('white_clock', '')
            bc = self.game_info.get('black_clock', '')
            low_time_threshold = 30
            if tc or wc or bc:
                time_parts = []
                if tc:
                    time_parts.append(f"时限: {tc}")
                if wc:
                    w_sec = 0
                    try:
                        parts = wc.split(':')
                        if len(parts) == 2:
                            w_sec = int(parts[0]) * 60 + int(parts[1])
                        else:
                            w_sec = int(float(wc))
                    except (ValueError, IndexError):
                        pass
                    stress_mark = " ⏰ 紧张!" if 0 < w_sec <= low_time_threshold else ""
                    time_parts.append(f"白剩: {wc}{stress_mark}")
                if bc:
                    b_sec = 0
                    try:
                        parts = bc.split(':')
                        if len(parts) == 2:
                            b_sec = int(parts[0]) * 60 + int(parts[1])
                        else:
                            b_sec = int(float(bc))
                    except (ValueError, IndexError):
                        pass
                    stress_mark = " ⏰ 紧张!" if 0 < b_sec <= low_time_threshold else ""
                    time_parts.append(f"黑剩: {bc}{stress_mark}")
                time_line = " | ".join(time_parts)
                tb = draw.textbbox((0, 0), time_line, font=info_font)
                draw.text((px, py), time_line, fill=self.colors["panel_muted"], font=info_font)
                py += tb[3] - tb[1] + 4

        # 分隔线
        py += 5
        draw.line([(px, py), (px + usable_width, py)],
                  fill=self.colors["separator"], width=1)
        py += 10

        # ---- 步数徽章 ----
        if step_number is not None:
            badge_text = f"第 {step_number} 步"
            if total_steps:
                badge_text += f" / 共 {total_steps} 步"

            badge_font = self._load_chinese_font(16)
            badge_tb = draw.textbbox((0, 0), badge_text, font=badge_font)
            badge_w = badge_tb[2] - badge_tb[0] + 16
            badge_h = badge_tb[3] - badge_tb[1] + 8
            badge_x = px
            badge_y = py

            # 徽章背景
            draw.rounded_rectangle(
                [badge_x, badge_y, badge_x + badge_w, badge_y + badge_h],
                radius=6, fill=(45, 50, 65)
            )
            draw.text((badge_x + 8, badge_y + 4), badge_text,
                      fill=self.colors["panel_accent"], font=badge_font)
            py += badge_h + 18

        # ---- 讲解正文 ----
        if subtitle_text:
            # 动态字号：根据文本长度选择字号
            text_len = len(subtitle_text)
            if text_len <= 40:
                body_size = 24
            elif text_len <= 80:
                body_size = 22
            elif text_len <= 150:
                body_size = 20
            elif text_len <= 250:
                body_size = 18
            else:
                body_size = 16

            body_font = self._load_chinese_font(body_size)
            lines = self._wrap_text(draw, subtitle_text, body_font, usable_width)

            # 检查是否会超出可用空间
            max_lines = int(usable_height / (body_size + 6)) - 1
            if len(lines) > max_lines and body_size > 14:
                # 缩小字号重试
                body_size = max(14, body_size - 4)
                body_font = self._load_chinese_font(body_size)
                lines = self._wrap_text(draw, subtitle_text, body_font, usable_width)

            for line in lines:
                if py + body_size > self.height - 12:
                    break
                draw.text((px, py), line, fill=self.colors["panel_text"],
                          font=body_font)
                py += body_size + 6

    def _wrap_text(self, draw, text: str, font, max_width: int) -> list:
        """
        中文文本自动换行。
        逐字符测量宽度，超出 max_width 时换行。
        """
        lines = []
        current_line = ""

        for char in text:
            test_line = current_line + char
            bbox = draw.textbbox((0, 0), test_line, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines

    # --------------- 右下角小棋盘（支线变化演示）---------------
    def _draw_branch_mini_board(self, img, info: dict = None):
        """
        在右侧面板右下角绘制小棋盘，演示支线变化序列。

        支持三种模式：
        1. 引擎候选模式 (candidate_info): info 含 "pv", "move", "score_cp"
        2. 显式走法模式 (branch_instruction): info 含 "_branch_instruction" = {"type":"moves","moves":[...]}
        3. 静态 FEN 模式: info 含 "_branch_instruction" = {"type":"fen","fen":"..."}

        走法演示时：从 _board 出发，依次执行走法并绘制箭头动画。
        FEN 模式：直接加载指定局面。
        """
        if not info:
            return

        # 提取 branch_instruction（如果有）
        branch_instr = info.get("_branch_instruction", None)
        base_board = info.get("_board")  # 当前棋盘（走棋前状态）

        # ─── 清空模式：直接返回，不绘制小棋盘 ───
        if branch_instr and branch_instr.get("type") == "clear":
            return

        mini_size = 400
        mini_sq = mini_size // 8  # 50px 每格

        # 位置：右侧面板右下角
        mx = self.panel_x + self.panel_width - mini_size - 8
        my = self.height - mini_size - 8

        draw = ImageDraw.Draw(img)

        # ─── 模式判断与准备 ───
        pv_moves = []  # [(from_sq, to_sq, san), ...]
        display_board = None  # 最终展示的棋盘
        title = ""
        seq_text = ""

        if branch_instr and branch_instr.get("type") == "fen":
            # ─── FEN 模式：加载指定局面 ───
            fen_str = branch_instr.get("fen", "")
            try:
                display_board = chess.Board(fen_str)
                title = "指定局面"
            except ValueError:
                # FEN 无效，静默跳过
                return
        elif branch_instr and branch_instr.get("type") == "moves":
            # ─── 显式走法模式：从 LLM 标签解析 ───
            move_tokens = branch_instr.get("moves", [])
            if not base_board or not move_tokens:
                return
            branch_board = base_board.copy()
            for tok in move_tokens:
                tok = tok.rstrip('.')
                # 跳过纯数字标记（如 "2."）
                if tok and tok[0].isdigit() and len(tok) <= 3:
                    continue
                try:
                    move_obj = branch_board.parse_san(tok)
                    pv_moves.append((move_obj.from_square, move_obj.to_square, tok))
                    branch_board.push(move_obj)
                    if len(pv_moves) >= 5:
                        break
                except ValueError:
                    # 走法无效，跳过
                    continue
            if not pv_moves:
                return
            display_board = branch_board
            title = f"支线: {' → '.join(m[:10] for m in move_tokens[:3])}"
        else:
            # ─── 引擎候选模式（原逻辑）───
            pv_str = info.get("pv", "")
            if not base_board or not pv_str:
                return
            # 解析 PV 中的所有走法（最多4步）
            pv_tokens = pv_str.strip().split()
            branch_board = base_board.copy()
            for tok in pv_tokens:
                tok = tok.rstrip('.')
                if tok[0].isdigit():  # 跳过序号如 "2."
                    continue
                try:
                    move_obj = branch_board.parse_san(tok)
                    pv_moves.append((move_obj.from_square, move_obj.to_square, tok))
                    branch_board.push(move_obj)
                    if len(pv_moves) >= 4:
                        break
                except ValueError:
                    break
            if not pv_moves:
                return
            display_board = branch_board
            cand_move = info.get("move", "?")
            score = info.get("score_cp", 0)
            score_str = f"+{score/100:.1f}" if score >= 0 else f"{score/100:.1f}"
            title = f"支线: {cand_move} ({score_str})"

        # ─── 半透明深色背景 ───
        bg = Image.new('RGBA', (mini_size + 44, mini_size + 60), (0, 0, 0, 190))
        img.paste(bg, (mx - 22, my - 22), bg)

        # ─── 标题 ───
        try:
            title_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 13)
        except Exception:
            title_font = ImageFont.load_default()
        draw.text((mx + 5, my - 19), title, fill=(255, 200, 100), font=title_font)

        # ─── 绘制小棋盘格子 ───
        for rank in range(8):
            for file in range(8):
                x = mx + file * mini_sq
                y = my + (7 - rank) * mini_sq
                color = self.colors["dark"] if (file + rank) % 2 == 0 else self.colors["light"]
                draw.rectangle([x, y, x + mini_sq, y + mini_sq], fill=color)

        # ─── 绘制支线走法的箭头和高亮 ───
        arrow_colors = [(255, 200, 50), (100, 180, 255), (255, 150, 80), (80, 220, 120), (200, 120, 255)]
        highlight_colors = [
            (255, 200, 50, 130), (100, 180, 255, 130),
            (255, 150, 80, 130), (80, 220, 120, 130), (200, 120, 255, 130)
        ]

        for i, (f_sq, t_sq, san) in enumerate(pv_moves):
            ac = arrow_colors[i % len(arrow_colors)]
            hc = highlight_colors[i % len(highlight_colors)]

            # 高亮走棋的 from/to 格
            for sq in (f_sq, t_sq):
                file = chess.square_file(sq)
                rank = chess.square_rank(sq)
                x = mx + file * mini_sq
                y = my + (7 - rank) * mini_sq
                overlay = Image.new('RGBA', (mini_sq, mini_sq), hc)
                img.paste(overlay, (x, y), overlay)

            # 画箭头
            fx = mx + chess.square_file(f_sq) * mini_sq + mini_sq // 2
            fy = my + (7 - chess.square_rank(f_sq)) * mini_sq + mini_sq // 2
            tx = mx + chess.square_file(t_sq) * mini_sq + mini_sq // 2
            ty = my + (7 - chess.square_rank(t_sq)) * mini_sq + mini_sq // 2
            draw.line([(fx, fy), (tx, ty)], fill=ac, width=3)

        # ─── 绘制棋子 ───
        if display_board:
            for sq in chess.SQUARES:
                piece = display_board.piece_at(sq)
                if not piece:
                    continue
                symbol = piece.symbol()
                piece_img = self.piece_images.get(symbol)
                file = chess.square_file(sq)
                rank = chess.square_rank(sq)
                cx = mx + file * mini_sq + mini_sq // 2
                cy = my + (7 - rank) * mini_sq + mini_sq // 2

                if piece_img is not None:
                    target = int(mini_sq * 0.88)
                    if piece_img.width != target:
                        small_piece = piece_img.resize((target, target), Image.LANCZOS)
                    else:
                        small_piece = piece_img
                    px = cx - small_piece.width // 2
                    py = cy - small_piece.height // 2
                    img.paste(small_piece, (px, py), small_piece)
                else:
                    try:
                        pf = ImageFont.truetype("C:/Windows/Fonts/seguisym.ttf", int(mini_sq * 0.7))
                    except Exception:
                        pf = ImageFont.load_default()
                    char = self.pieces_unicode.get(symbol, '?')
                    tdraw = ImageDraw.Draw(img)
                    tb = tdraw.textbbox((0, 0), char, font=pf)
                    tw, th = tb[2] - tb[0], tb[3] - tb[1]
                    tdraw.text((cx - tw//2, cy - th//2), char, fill=(255,255,255,220), font=pf)

        # ─── 底部支线序列文字 ───
        if not seq_text:
            seq_parts = []
            for i, (_, _, san) in enumerate(pv_moves):
                side = "白" if i % 2 == 0 else "黑"
                seq_parts.append(f"{side}{san}")
            seq_text = " → ".join(seq_parts)

        try:
            seq_font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11)
        except Exception:
            seq_font = ImageFont.load_default()

        seq_y = my + mini_size + 6
        draw.text((mx + 5, seq_y), seq_text, fill=(180, 170, 150), font=seq_font)

    # --------------- 文字画面 ---------------
    def render_text_slide(self, title: str = "", subtitle: str = "",
                          bg_color: tuple = None, style: str = "intro") -> Image.Image:
        """
        渲染片头/片尾画面，支持渐变背景、大号标题、装饰元素。

        Args:
            title: 主标题
            subtitle: 副标题/描述文字
            bg_color: 背景基色（None=默认深蓝灰）
            style: "intro"(片头) 或 "outro"(片尾)
        """
        w, h = self.width, self.height
        img = Image.new('RGB', (w, h), (10, 12, 18))
        draw = ImageDraw.Draw(img)

        # ── 径向渐变背景（从中心向外渐变）──
        for y in range(h):
            t = y / h
            r = int(18 + (45 - 18) * t * 0.5)
            g = int(22 + (55 - 22) * t * 0.5)
            b = int(38 + (72 - 38) * t * 0.5)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        # ── 装饰性网格线 ──
        grid_color = (40, 42, 55, 80)
        for x in range(0, w, 80):
            draw.line([(x, 0), (x, h)], fill=grid_color[:3], width=1)
        for y in range(0, h, 80):
            draw.line([(0, y), (w, y)], fill=grid_color[:3], width=1)

        # ── 双棋盘装饰（左右各一个半透明棋盘）──
        self._draw_decorative_board(draw, 60, h // 2 - 130, 220, alpha=0.18)
        self._draw_decorative_board(draw, w - 280, h // 2 - 100, 180, alpha=0.12)

        # ── 社团 logo（放大）──
        if self.logo_img:
            logo_w = min(200, self.logo_img.width)
            logo_h = int(self.logo_img.height * logo_w / self.logo_img.width)
            logo_resized = self.logo_img.resize((logo_w, logo_h), Image.LANCZOS)
            logo_x = w // 2 - logo_w // 2
            logo_y = h // 2 - 230
            img.paste(logo_resized, (logo_x, logo_y), logo_resized)

        # ── 标题 ──
        font_title = self._load_chinese_font(52)
        font_subtitle = self._load_chinese_font(22)
        font_small = self._load_chinese_font(16)

        if style == "intro":
            # 主标题在 logo 下方
            title_y_pos = h // 2 + 20
            if title:
                tb = draw.textbbox((0, 0), title, font=font_title)
                tw = tb[2] - tb[0]
                draw.text((w // 2 - tw // 2, title_y_pos), title,
                          fill=(235, 215, 170), font=font_title)
                title_y_pos += tb[3] - tb[1] + 12

            if subtitle:
                tb = draw.textbbox((0, 0), subtitle, font=font_subtitle)
                sw = tb[2] - tb[0]
                draw.text((w // 2 - sw // 2, title_y_pos), subtitle,
                          fill=(175, 155, 130), font=font_subtitle)

            # 底部版本信息
            version_text = "v5 · AI 驱动的国际象棋讲解视频生成器"
            tb = draw.textbbox((0, 0), version_text, font=font_small)
            vw = tb[2] - tb[0]
            draw.text((w // 2 - vw // 2, h - 50), version_text,
                      fill=(90, 85, 75), font=font_small)

            # 装饰：标题下方的金色细线
            line_y = title_y_pos + 18 if not subtitle else title_y_pos + 30
            draw.line([(w // 3, line_y), (w * 2 // 3, line_y)],
                      fill=(180, 150, 100), width=2)

        else:  # outro
            title_y_pos = h // 2 - 60
            if title:
                tb = draw.textbbox((0, 0), title, font=font_title)
                tw = tb[2] - tb[0]
                draw.text((w // 2 - tw // 2, title_y_pos), title,
                          fill=(235, 215, 170), font=font_title)
                title_y_pos += tb[3] - tb[1] + 12

            if subtitle:
                tb = draw.textbbox((0, 0), subtitle, font=font_subtitle)
                sw = tb[2] - tb[0]
                draw.text((w // 2 - sw // 2, title_y_pos), subtitle,
                          fill=(175, 155, 130), font=font_subtitle)

            # 装饰线
            line_y = title_y_pos + 20 if not subtitle else title_y_pos + 40
            draw.line([(w // 3, line_y), (w * 2 // 3, line_y)],
                      fill=(180, 150, 100), width=2)

            # 底部文字
            credit = "深蓝国际象棋协会 · 深蓝棋评"
            tb = draw.textbbox((0, 0), credit, font=font_small)
            cw = tb[2] - tb[0]
            draw.text((w // 2 - cw // 2, h - 50), credit,
                      fill=(100, 95, 85), font=font_small)

        return img

    def _draw_decorative_board(self, draw, x, y, size, alpha=0.25):
        """绘制装饰性半透明棋盘轮廓"""
        sq = size // 8
        # 亮度随 alpha 调整
        light = tuple(int(45 * alpha) for _ in range(3))
        dark = tuple(int(35 * alpha) for _ in range(3))
        for r in range(8):
            for f in range(8):
                sx = x + f * sq
                sy = y + (7 - r) * sq
                color = light if (f + r) % 2 == 0 else dark
                draw.rectangle([sx, sy, sx + sq, sy + sq], fill=color)

    # --------------- 序列渲染 ---------------
    def render_sequence(self, pgn_path: Path, output_dir: Path,
                        frames_per_move: list = None,
                        fps: int = 15,
                        total_duration: float = None,
                        commentary_text: str = None) -> int:
        """
        渲染完整视频帧序列，包括片头、对局动画、片尾。
        每步帧数按讲解词字数比例分配。
        """
        import subprocess

        output_dir.mkdir(parents=True, exist_ok=True)

        # 读取 PGN
        try:
            with pgn_path.open("r", encoding="utf-8") as f:
                game = chess.pgn.read_game(f)
        except Exception as e:
            print(f"❌ 无法读取 PGN: {e}")
            return 0

        # 对局信息
        headers = game.headers
        white_player = headers.get("White", "白方")
        black_player = headers.get("Black", "黑方")
        opening = headers.get("Opening", "")

        self.game_info = {
            'white': white_player,
            'black': black_player,
            'opening': opening,
            'result': headers.get("Result", ""),
            'termination': headers.get("Termination", ""),
            'time_control': headers.get("TimeControl", ""),
            'white_clock': headers.get("WhiteClock", ""),
            'black_clock': headers.get("BlackClock", ""),
            'white_elo': headers.get("WhiteElo", ""),
            'black_elo': headers.get("BlackElo", ""),
        }

        # 加载着法质量数据（用于棋盘标注 ? / ?? / ?!）及候选分支
        self.step_candidates = {}  # {move_number: [candidate_dicts]}
        analysis_json = output_dir.parent / "analysis_result.json"
        if not analysis_json.exists():
            analysis_json = Path(__file__).parent / "analysis_result.json"
        if analysis_json.exists():
            try:
                import json as _json
                with analysis_json.open("r", encoding="utf-8") as f:
                    adata = _json.load(f)
                for s in adata.get("steps", adata):
                    mn = s["move_number"]
                    self.step_qualities[mn] = s.get("quality", "正常")
                    # 提取候选走法（最多 3 条，且排除与实战相同的）
                    cands = s.get("candidates", [])
                    actual_move = s.get("move_san", "")
                    filtered = []
                    for c in cands:
                        if c.get("move", "") != actual_move and len(filtered) < 3:
                            filtered.append(c)
                    if filtered:
                        self.step_candidates[mn] = filtered
            except Exception:
                pass

        board = game.board()
        moves = list(game.mainline_moves())
        total_steps = len(moves)

        # 解析画面指令（从讲解词中提取高亮和箭头）
        scene_instructions = {}
        if commentary_text:
            scene_instructions = self._parse_scene_instructions(commentary_text, moves)

        # 提取每步的纯净讲解文字（去除画面指令标签）
        step_texts = {}
        if commentary_text:
            step_texts = self._extract_step_texts(commentary_text)

        # 计算每步帧数：优先使用 timing.json 的精确时长
        if frames_per_move is None:
            timing_path = output_dir.parent / "timing.json"
            if not timing_path.exists():
                timing_path = Path(__file__).parent / "timing.json"
            if timing_path.exists():
                frames_per_move = self._calc_frames_from_timing(
                    timing_path, len(moves), fps
                )
            elif commentary_text and total_duration:
                frames_per_move = self._calc_frames_from_commentary(
                    commentary_text, len(moves), fps, total_duration
                )
            elif total_duration and total_duration > 60:
                intro_secs = 4.0
                game_secs = total_duration - intro_secs
                base = max(1, int(game_secs * fps / (len(moves) + 1)))
                frames_per_move = [base] * len(moves)
            else:
                frames_per_move = [30] * len(moves)

        frame_num = 0

        print(f"🎬 渲染视频帧序列 (横屏 4:3)")
        print(f"   对手: {white_player} vs {black_player}")
        if opening:
            print(f"   开局: {opening}")
        print(f"   步数: {len(moves)}, FPS: {fps}")
        print(f"   分辨率: {self.width}×{self.height}")
        print(f"   预计总帧: {sum(frames_per_move) + fps * 4 + fps * 3} (含片头片尾)")

        # ====== 片头 ======
        intro_secs = 5
        intro_frames = int(intro_secs * fps)

        # 片头画面 1：社团 logo + 标题（3秒，45帧）
        img_intro = self.render_text_slide(
            INTRO_TITLE, INTRO_SUBTITLE, style="intro"
        )
        for _ in range(int(intro_secs * 0.6 * fps)):
            img_intro.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        # 片头画面 2：对局信息简介（2秒，30帧）
        info_text = f"{self.game_info.get('white','白方')} vs {self.game_info.get('black','黑方')}"
        if self.game_info.get('opening'):
            info_text += f"\n开局：{self.game_info['opening']}"
        img_info = self.render_text_slide(
            info_text.split("\n")[0] if "\n" in info_text else info_text,
            "\n".join(info_text.split("\n")[1:]) if "\n" in info_text else "",
            style="intro"
        )
        for _ in range(int(intro_secs * 0.4 * fps)):
            img_info.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        # ====== 初始棋盘 ======
        init_text = step_texts.get(0, None)
        init_instructions = scene_instructions.get(0, {})
        init_highlights = init_instructions.get("highlights", [])
        init_arrows = init_instructions.get("arrows", [])
        init_hl_types = dict(init_instructions.get("highlight_types", {}))

        img = self.render_board(
            board,
            highlights=init_highlights,
            arrows=init_arrows,
            subtitle_text=init_text,
            step_number=0,
            total_steps=total_steps,
            highlight_types=init_hl_types if init_hl_types else None,
        )
        init_frames = max(1, frames_per_move[0] // 3)
        for _ in range(init_frames):
            img.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        # ====== 对局帧 ======
        for move_idx, move in enumerate(moves, 1):
            # ═══════════════════════════════════════════
            # 走棋前：捕获棋盘状态用于小棋盘演示
            # ═══════════════════════════════════════════
            board_before_push = board.copy()

            # 获取该步的画面指令（含小棋盘指令）
            instr = scene_instructions.get(move_idx, {})
            branch_instr = instr.get("mini_board")  # LLM 的 [小棋盘: ...] 标签

            # 获取该步的候选分支信息（引擎分析数据）
            cand_info = None
            if hasattr(self, 'step_candidates') and move_idx in self.step_candidates:
                cands = self.step_candidates[move_idx]
                if cands:
                    best = max(cands, key=lambda c: abs(c.get("score_cp", 0)))
                    cand_info = dict(best)
                    cand_info["_board"] = board_before_push

            # 如果 LLM 显式给了小棋盘指令但没有候选数据，创建最小 info
            if branch_instr and not cand_info:
                cand_info = {"_board": board_before_push}

            # 执行实战走法
            board.push(move)

            highlights = instr.get("highlights",
                                   [move.from_square, move.to_square])
            arrows = instr.get("arrows", [])

            # 构建 highlight_types：自动检测 check + 从指令提取
            hl_types = dict(instr.get("highlight_types", {}))

            # 自动检测将军：如果当前局面某一方处于被将军状态，高亮王所在的格子
            if board.is_check():
                king_sq = board.king(board.turn)
                if king_sq is not None:
                    hl_types["check"] = [king_sq]

            # 只有走棋的 from/to 作为 last_move 高亮
            if "last_move" not in hl_types:
                hl_types["last_move"] = [move.from_square, move.to_square]

            # 获取该步的讲解文字
            sub_text = step_texts.get(move_idx, None)

            # 着法标注：7级分类 → 标注符号
            move_ann = None
            if hasattr(self, 'step_qualities') and move_idx in self.step_qualities:
                q = self.step_qualities[move_idx]
                move_ann = {"妙手": "!!", "好棋": "!", "缓着": "?!",
                            "疑问": "?!", "失误": "?", "漏杀": "??", "送子": "?"}.get(q)

            img = self.render_board(
                board,
                highlights=highlights,
                arrows=arrows,
                subtitle_text=sub_text,
                step_number=move_idx,
                total_steps=total_steps,
                highlight_types=hl_types,
                move_annotation=move_ann,
                annotation_square=move.to_square if move_ann else None,
                candidate_info=cand_info,
                branch_instruction=branch_instr,
            )

            n_frames = frames_per_move[move_idx - 1]
            # 步骤1：扣除初始棋盘已消耗的帧数
            if move_idx == 1:
                n_frames = max(1, n_frames - init_frames)
            for _ in range(n_frames):
                img.save(output_dir / f"frame_{frame_num:06d}.png")
                frame_num += 1

            if move_idx % 10 == 0:
                print(f"  第 {move_idx} 步 ({frame_num} 帧)")

        # ====== 最终棋盘（多留几秒）=======
        final_frames = fps * 2
        final_text = "对局结束"
        result = headers.get("Result", "")
        if result == "1-0":
            final_text = f"白方 ({white_player}) 获胜！"
        elif result == "0-1":
            final_text = f"黑方 ({black_player}) 获胜！"
        elif result == "1/2-1/2":
            final_text = "双方和棋"

        img_final = self.render_board(
            board,
            subtitle_text=final_text,
            step_number=None,
            total_steps=None
        )
        for _ in range(final_frames):
            img_final.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        # ====== 片尾 ======
        outro_secs = 4
        outro_frames = int(outro_secs * fps)

        # 片尾画面 1：感谢观看（2秒，30帧）
        img_outro = self.render_text_slide(
            OUTRO_TITLE, OUTRO_SUBTITLE, style="outro"
        )
        for _ in range(outro_frames // 2):
            img_outro.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        # 片尾画面 2：最终棋盘定格（2秒，30帧）
        result_text = "对局结束"
        result = self.game_info.get("result", "")
        if result == "1-0":
            result_text = f"白方胜 · {self.game_info.get('white','')}"
        elif result == "0-1":
            result_text = f"黑方胜 · {self.game_info.get('black','')}"
        elif result == "1/2-1/2":
            result_text = "双方和棋"
        img_outro2 = self.render_text_slide(
            result_text, "感谢收看 · 我们下期再见", style="outro"
        )
        for _ in range(outro_frames // 2):
            img_outro2.save(output_dir / f"frame_{frame_num:06d}.png")
            frame_num += 1

        print(f"✓ 渲染完成: {frame_num} 帧 "
              f"({frame_num / fps:.0f} 秒 @ {fps}fps)")

        # ====== 音画同步验证 ======
        total_audio_dur = 0
        try:
            timing_path_check = output_dir.parent / "timing.json"
            if not timing_path_check.exists():
                timing_path_check = Path(__file__).parent / "timing.json"
            if timing_path_check.exists():
                import json as _json
                with timing_path_check.open("r", encoding="utf-8") as f:
                    total_audio_dur = _json.load(f).get("total_duration", 0)
        except Exception:
            pass
        if total_audio_dur > 0:
            # 纯游戏帧 vs 音频时长（init_frames 从 frames_per_move[0] 扣除，不额外加）
            game_portion_frames = sum(frames_per_move) + final_frames
            game_portion_dur = game_portion_frames / fps
            drift = game_portion_dur - total_audio_dur
            print(f"  音画同步检查: 对局画面 {game_portion_dur:.1f}s "
                  f"(初始{init_frames/fps:.1f}s+步{sum(frames_per_move)/fps:.1f}s+终{final_frames/fps:.1f}s), "
                  f"音频 {total_audio_dur:.1f}s, "
                  f"偏差 {drift:+.1f}s ({drift/total_audio_dur*100:+.3f}%)")
            if abs(drift) > 1.0:
                print(f"  ⚠ 偏差较大 ({drift:+.1f}s)，需检查 timing.json 与音频是否匹配")

        return frame_num

    # --------------- 画面指令解析 ---------------
    def _parse_scene_instructions(self, commentary: str, moves: list) -> dict:
        """
        从讲解词中提取画面指令
        格式: [STEP 12] [高亮 e4,f7] [威胁 e5] [箭头 e2-e4] [小棋盘: d5, exd5] 解说文字...

        返回: {step_num: {"highlights": [sq, ...], "arrows": [(from,to), ...],
                          "highlight_types": {...},
                          "mini_board": {"type": "moves"|"fen"|"clear",
                                         "moves": [san, ...], "fen": "..."}}}
        """
        instructions = {}
        step_pattern = r"\[STEP (\d+)\]\s*(.*?)(?=\[STEP \d+\]|$)"

        for match in re.finditer(step_pattern, commentary, re.DOTALL):
            step_num = int(match.group(1))
            step_text = match.group(2).strip()

            highlights = []
            arrows = []
            highlight_types = {}
            mini_board = None  # {"type": ..., "moves": [...], "fen": "..."}

            # ─── 小棋盘指令解析（优先处理，支持复杂格式）───
            mb_match = re.search(r"\[小棋盘:\s*(.+?)\]", step_text)
            if mb_match:
                mb_content = mb_match.group(1).strip()
                if mb_content == "清空":
                    mini_board = {"type": "clear"}
                elif mb_content.startswith("仅显示局面") or mb_content.startswith("FEN"):
                    # 提取 FEN 字符串
                    fen_match = re.search(r"FEN[：:]\s*(.+)", mb_content)
                    if fen_match:
                        fen_str = fen_match.group(1).strip()
                        mini_board = {"type": "fen", "fen": fen_str}
                else:
                    # 动态演示变化：逗号分隔的走法列表
                    move_tokens = re.split(r'[,，\s]+', mb_content)
                    move_tokens = [t.strip() for t in move_tokens if t.strip()]
                    if move_tokens:
                        mini_board = {"type": "moves", "moves": move_tokens}

            # 通用高亮: [高亮 e4,f7]
            hl_match = re.search(r"\[高亮\s+(.+?)\]", step_text)
            if hl_match:
                squares_str = hl_match.group(1)
                for sq_name in re.split(r'[,，\s]+', squares_str):
                    sq_name = sq_name.strip().lower()
                    try:
                        sq = chess.parse_square(sq_name)
                        highlights.append(sq)
                    except ValueError:
                        pass

            # 威胁高亮: [威胁 e5,d4]
            threat_match = re.search(r"\[威胁\s+(.+?)\]", step_text)
            if threat_match:
                squares_str = threat_match.group(1)
                threat_sqs = []
                for sq_name in re.split(r'[,，\s]+', squares_str):
                    sq_name = sq_name.strip().lower()
                    try:
                        threat_sqs.append(chess.parse_square(sq_name))
                    except ValueError:
                        pass
                if threat_sqs:
                    highlight_types["threat"] = threat_sqs

            # 选中高亮: [选中 e4]
            sel_match = re.search(r"\[选中\s+(.+?)\]", step_text)
            if sel_match:
                squares_str = sel_match.group(1)
                sel_sqs = []
                for sq_name in re.split(r'[,，\s]+', squares_str):
                    sq_name = sq_name.strip().lower()
                    try:
                        sel_sqs.append(chess.parse_square(sq_name))
                    except ValueError:
                        pass
                if sel_sqs:
                    highlight_types["selected"] = sel_sqs

            # 箭头: [箭头 e2-e4]
            arrow_match = re.findall(r"\[箭头\s+(.+?)\]", step_text)
            for arrow_str in arrow_match:
                arrow_str = arrow_str.strip().replace(" ", "")
                parts = re.split(r'[-—–]', arrow_str)
                if len(parts) == 2:
                    try:
                        f_sq = chess.parse_square(parts[0].strip().lower())
                        t_sq = chess.parse_square(parts[1].strip().lower())
                        arrows.append((f_sq, t_sq))
                    except ValueError:
                        pass

            instructions[step_num] = {
                "highlights": highlights,
                "arrows": arrows,
                "highlight_types": highlight_types,
                "mini_board": mini_board,
            }

        return instructions

    def _extract_step_texts(self, commentary: str) -> dict:
        """
        从讲解词中提取每步的纯净文字（去掉画面指令标签）。
        返回: {step_num: clean_text}
        """
        step_texts = {}
        step_pattern = r"\[STEP (\d+)\]\s*(.*?)(?=\[STEP \d+\]|$)"

        for match in re.finditer(step_pattern, commentary, re.DOTALL):
            step_num = int(match.group(1))
            text = match.group(2)
            # 移除画面指令标签
            text = re.sub(r'\[高亮\s*[^\]]+\]', '', text)
            text = re.sub(r'\[威胁\s*[^\]]+\]', '', text)
            text = re.sub(r'\[选中\s*[^\]]+\]', '', text)
            text = re.sub(r'\[箭头\s*[^\]]+\]', '', text)
            text = re.sub(r'\[小棋盘:\s*[^\]]+\]', '', text)
            text = text.strip()
            step_texts[step_num] = text

        return step_texts

    # --------------- 按精确 timing 逐帧分配 ---------------
    def _calc_frames_from_timing(self, timing_path: Path, n_moves: int,
                                  fps: int) -> list:
        """
        从 timing.json 读取精确时长。
        floor 分配 + 余数补到最长步骤 = 零偏差。
        """
        import json as _json
        with timing_path.open("r", encoding="utf-8") as f:
            tdata = _json.load(f)
        timing_steps = tdata.get("steps", [])
        total_audio_dur = tdata.get("total_duration", 0)

        dur_map = {ts["step"]: ts["duration"] for ts in timing_steps}
        target_frames = max(n_moves, round(total_audio_dur * fps))

        # floor 分配
        frames = []
        for move_idx in range(1, n_moves + 1):
            dur = dur_map.get(move_idx, 3.0)
            frames.append(max(1, int(dur * fps)))

        # 余数补到时长最长的步子
        remaining = target_frames - sum(frames)
        sorted_idxs = sorted(range(len(frames)), 
                            key=lambda i: dur_map.get(i + 1, 0) * fps - frames[i],
                            reverse=True)
        for i in range(min(abs(remaining), len(sorted_idxs))):
            idx = sorted_idxs[i % len(sorted_idxs)]
            frames[idx] += (1 if remaining > 0 else -1)

        total = sum(frames)
        print(f"  使用 timing.json 精确同步: {n_moves} 步, {total} 帧 "
              f"(目标 {target_frames}, 音频 {total_audio_dur:.1f}s, "
              f"偏差 {total - target_frames:+.0f} 帧)")
        return frames

    # --------------- 按讲解词字数逐帧分配（降级方案）------------
    def _calc_frames_from_commentary(self, commentary: str, n_moves: int,
                                      fps: int, total_duration: float) -> list:
        """
        按每步讲解词的字数比例分配帧数。
        字数多的步（错误/大错）分配更多帧，实现画面与讲解同步。
        """
        step_pattern = r"\[STEP (\d+)\]\s*(.*?)(?=\[STEP \d+\]|$)"
        step_texts = {}
        for match in re.finditer(step_pattern, commentary, re.DOTALL):
            step_num = int(match.group(1))
            text = match.group(2).strip()
            clean_text = re.sub(r'\[高亮\s*.+?\]', '', text)
            clean_text = re.sub(r'\[威胁\s*.+?\]', '', clean_text)
            clean_text = re.sub(r'\[选中\s*.+?\]', '', clean_text)
            clean_text = re.sub(r'\[箭头\s*.+?\]', '', clean_text)
            clean_text = re.sub(r'\[小棋盘:\s*[^\]]+\]', '', clean_text)
            step_texts[step_num] = clean_text

        intro_secs = 6.0
        outro_secs = 5.0
        final_secs = 3.0

        game_secs = total_duration - intro_secs - outro_secs - final_secs
        game_frames = max(n_moves, int(game_secs * fps))

        initial_chars = 30
        total_chars = initial_chars + sum(
            len(step_texts.get(i + 1, "")) for i in range(n_moves)
        )
        if total_chars == 0:
            total_chars = n_moves * 30

        frames_per_move = []
        for i in range(n_moves):
            chars = len(step_texts.get(i + 1, ""))
            alloc = max(15, int(game_frames * chars / total_chars))
            frames_per_move.append(alloc)

        actual = sum(frames_per_move)
        if actual > 0 and actual != game_frames:
            ratio = game_frames / actual
            frames_per_move = [max(10, int(f * ratio)) for f in frames_per_move]

        return frames_per_move


# ===================== 工具函数 =====================

def get_audio_duration(audio_path: Path) -> float:
    """获取音频时长（秒）"""
    import subprocess
    ffprobe = None
    try:
        import imageio_ffmpeg
        ffm = imageio_ffmpeg.get_ffmpeg_exe()
        ffprobe = str(Path(ffm).parent / "ffprobe.exe")
    except Exception:
        pass
    if ffprobe is None:
        try:
            subprocess.run(["ffprobe", "-version"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=5)
            ffprobe = "ffprobe"
        except Exception:
            pass

    if ffprobe and audio_path.exists():
        try:
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-print_format", "json",
                 "-show_format", str(audio_path)],
                capture_output=True, text=True, timeout=10
            )
            return float(json.loads(result.stdout)["format"]["duration"])
        except Exception:
            pass
    return 480.0


def create_video_from_frames(frame_dir: Path, output_video: Path, fps: int = 15) -> bool:
    """从帧序列创建视频"""
    import subprocess

    ffmpeg = None
    try:
        import imageio_ffmpeg
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, Exception):
        pass

    if ffmpeg is None:
        try:
            subprocess.run(["ffmpeg", "-version"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=5)
            ffmpeg = "ffmpeg"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    if ffmpeg is None:
        print("❌ 无法找到 ffmpeg")
        print("   请安装: pip install imageio-ffmpeg")
        return False

    frame_files = sorted(frame_dir.glob("frame_*.png"))
    if not frame_files:
        print(f"❌ 找不到帧文件: {frame_dir}")
        return False

    print(f"正在从 {len(frame_files)} 张图片创建视频（FPS={fps})...")

    # 使用相对路径模式避免 Windows 中文路径编码问题
    # ffmpeg 在 Windows 上可能无法正确解析 UTF-8 路径
    input_pattern = "frame_%06d.png"
    cmd = [
        ffmpeg, "-framerate", str(fps),
        "-i", input_pattern,
        "-c:v", "libx264", "-preset", "fast",
        "-pix_fmt", "yuv420p", "-y",
        str(output_video)
    ]
    try:
        r = subprocess.run(cmd, capture_output=False, timeout=600,
                          cwd=str(frame_dir))  # ← 关键：在帧目录中执行
        if r.returncode == 0:
            print(f"✓ 视频: {output_video}")
            return True
        print("❌ 视频创建失败")
        return False
    except Exception as e:
        print(f"❌ 异常: {e}")
        return False


# ===================== main =====================

def main():
    script_dir = Path(__file__).parent

    # 找到 PGN 文件
    pgn_files = list(script_dir.glob("lichess_pgn*.pgn"))
    pgn_path = pgn_files[0] if pgn_files else None
    if not pgn_path or not pgn_path.exists():
        print("❌ 找不到 PGN 文件")
        return

    print("=" * 60)
    print("🎨 棋盘渲染工具 (横屏 4:3)")
    print("=" * 60)

    # 检查棋子图片
    pieces_dir = script_dir / "pieces"
    if not pieces_dir.exists() or not list(pieces_dir.glob("*.png")):
        print("⚠ 棋子图片未生成，将使用 Unicode 备用方案")
        print("  运行: python piece_generator.py 来生成")
    else:
        print("✓ 已找到棋子图片")

    # 读取讲解词
    commentary_path = script_dir / "commentary.txt"
    commentary_text = None
    if commentary_path.exists():
        commentary_text = commentary_path.read_text(encoding="utf-8")
        print("✓ 已读取讲解词（用于画面同步）")

    # 读取音频时长
    audio_path = script_dir / "commentary.mp3"
    fps = 15
    total_duration = None
    if audio_path.exists():
        total_duration = get_audio_duration(audio_path)
        if total_duration:
            print(f"音频时长: {total_duration:.1f} 秒")

    if not total_duration and commentary_text:
        chars = len(commentary_text)
        total_duration = chars / 4.0
        print(f"根据讲解词估算时长: {int(total_duration)} 秒 ({chars} 字)")

    renderer = ChessBoardRenderer(square_size=70)
    output_dir = script_dir / "board_frames"

    # 清空旧帧（处理 Windows 文件占用问题）
    import shutil
    if output_dir.exists():
        for _attempt in range(3):
            try:
                shutil.rmtree(output_dir)
                break
            except OSError:
                import time as _time
                _time.sleep(1)
        if output_dir.exists():
            print("⚠ 无法清理旧帧目录，将写入新文件覆盖")

    frame_count = renderer.render_sequence(
        pgn_path, output_dir,
        fps=fps,
        total_duration=total_duration,
        commentary_text=commentary_text
    )

    if frame_count == 0:
        print("❌ 渲染失败")
        return

    print(f"✓ 棋盘图片已保存: {output_dir}")
    output_video = script_dir / "board_animation.mp4"
    create_video_from_frames(output_dir, output_video, fps)


if __name__ == "__main__":
    main()