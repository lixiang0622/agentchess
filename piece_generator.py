"""
棋子图片生成器 v3 — 使用 Lichess 官方 cburnett SVG 生成 PNG 棋子

支持两种模式：
1. (推荐) 从 Lichess GitHub 下载官方 cburnett SVG → 转换 PNG
2. (降级) 如果 SVG 不可用，使用内置 PIL 矢量绘制

用法: python piece_generator.py [--size 64]
"""

import sys
import math
from pathlib import Path
import urllib.request
import os

sys.stdout.reconfigure(encoding="utf-8")

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("❌ 需要 Pillow 库: pip install Pillow")
    sys.exit(1)

# Lichess cburnett SVG CDN 地址
LICHESS_SVG_BASE = "https://raw.githubusercontent.com/lichess-org/lila/master/public/piece/cburnett/"
PIECE_NAMES = ['wK', 'wQ', 'wR', 'wB', 'wN', 'wP', 'bK', 'bQ', 'bR', 'bB', 'bN', 'bP']


def download_lichess_svgs(svg_dir: Path) -> bool:
    """下载 Lichess cburnett SVG 文件，返回是否全部成功"""
    svg_dir.mkdir(parents=True, exist_ok=True)
    all_ok = True
    for name in PIECE_NAMES:
        svg_path = svg_dir / f"{name}.svg"
        if svg_path.exists():
            continue  # 已存在，跳过
        url = LICHESS_SVG_BASE + name + ".svg"
        try:
            urllib.request.urlretrieve(url, str(svg_path))
        except Exception as e:
            print(f"  ⚠ 下载 {name}.svg 失败: {e}")
            all_ok = False
    return all_ok


def convert_svg_to_png(svg_dir: Path, output_dir: Path, size: int = 256) -> bool:
    """使用 svglib + reportlab + PIL 将 SVG 转为高分辨率 PNG（透明背景）"""
    try:
        from svglib.svglib import svg2rlg
        from reportlab.graphics import renderPM
        from PIL import Image as PILImage
        import io
    except ImportError:
        print("  ⚠ 缺少依赖库，安装: pip install svglib Pillow")
        return False

    output_dir.mkdir(parents=True, exist_ok=True)
    success = True

    for name in PIECE_NAMES:
        svg_path = svg_dir / f"{name}.svg"
        if not svg_path.exists():
            print(f"  ⚠ SVG 缺失: {name}.svg")
            success = False
            continue
        try:
            drawing = svg2rlg(str(svg_path))
            # 渲染到内存（高 DPI）
            png_bytes = renderPM.drawToString(drawing, fmt='PNG', dpi=300)
            img = PILImage.open(io.BytesIO(png_bytes))
            # 缩放到目标尺寸
            img = img.resize((size, size), PILImage.LANCZOS)
            # 将白色背景转为透明
            img = _make_white_transparent(img)
            png_path = output_dir / f"{name}.png"
            img.save(str(png_path), 'PNG')
        except Exception as e:
            print(f"  ⚠ 转换 {name}.png 失败: {e}")
            success = False
    return success


def _make_white_transparent(img: 'PILImage.Image') -> 'PILImage.Image':
    """
    将图像中的白色背景转为透明。
    使用 flood-fill 从四角出发 — 只去除背景区域的白色，
    不会影响棋子内部的白色填充（因为有轮廓线阻隔）。
    """
    from collections import deque
    img = img.convert('RGBA')
    pixels = img.load()
    w, h = img.size

    # 找到背景色：取四角的平均颜色（renderPM 渲染的背景色）
    corner_colors = [pixels[0, 0], pixels[w-1, 0], pixels[0, h-1], pixels[w-1, h-1]]
    bg_r = sum(c[0] for c in corner_colors) // 4
    bg_g = sum(c[1] for c in corner_colors) // 4
    bg_b = sum(c[2] for c in corner_colors) // 4

    # 判断一个像素是否为"背景色"（在阈值范围内）
    threshold = 30
    def is_bg(x, y):
        p = pixels[x, y]
        return (abs(p[0] - bg_r) <= threshold and
                abs(p[1] - bg_g) <= threshold and
                abs(p[2] - bg_b) <= threshold and
                p[3] > 0)  # 尚未处理

    # Flood fill 从四角开始
    visited = set()
    queue = deque()
    for sx, sy in [(0, 0), (w-1, 0), (0, h-1), (w-1, h-1)]:
        if is_bg(sx, sy):
            queue.append((sx, sy))
            visited.add((sx, sy))

    while queue:
        x, y = queue.popleft()
        pixels[x, y] = (0, 0, 0, 0)  # 设为透明
        for nx, ny in [(x+1,y), (x-1,y), (x,y+1), (x,y-1)]:
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                if is_bg(nx, ny):
                    visited.add((nx, ny))
                    queue.append((nx, ny))

    return img


def generate_pieces_from_lichess(output_dir: Path, size: int = 256) -> bool:
    """从 Lichess SVG 生成棋子 PNG"""
    svg_dir = output_dir.parent / "pieces_svg"
    print("  从 Lichess GitHub 下载官方 cburnett SVG...")
    if not download_lichess_svgs(svg_dir):
        print("  ⚠ 部分 SVG 下载失败，仍尝试转换已下载的...")

    print(f"  转换 SVG → PNG ({size}×{size})...")
    if convert_svg_to_png(svg_dir, output_dir, size):
        print(f"  ✅ 全部 12 枚 Lichess cburnett 棋子已生成")
        return True
    return False


# ===================== 降级方案：内置 PIL 矢量绘制 =====================

WHITE_FILL = (248, 244, 235)
WHITE_FILL_DARK = (228, 220, 205)
WHITE_OUTLINE = (30, 20, 10)
WHITE_HIGHLIGHT = (255, 252, 248)

BLACK_FILL = (65, 50, 35)
BLACK_FILL_DARK = (45, 32, 20)
BLACK_OUTLINE = (15, 10, 5)
BLACK_HIGHLIGHT = (105, 80, 55)

SHADOW_COLOR = (0, 0, 0, 70)
INTERNAL_SCALE = 4
C = 128
INTERNAL = 256


def colors(is_white: bool) -> dict:
    if is_white:
        return {'fill': WHITE_FILL, 'fill_dark': WHITE_FILL_DARK,
                'outline': WHITE_OUTLINE, 'highlight': WHITE_HIGHLIGHT}
    return {'fill': BLACK_FILL, 'fill_dark': BLACK_FILL_DARK,
            'outline': BLACK_OUTLINE, 'highlight': BLACK_HIGHLIGHT}


def draw_ellipse_outlined(draw, bbox, outline_color, fill_color,
                           outline_w: int = 5, fill_color2=None):
    x1, y1, x2, y2 = bbox
    draw.ellipse([x1 - outline_w, y1 - outline_w, x2 + outline_w, y2 + outline_w], fill=outline_color)
    draw.ellipse(bbox, fill=fill_color)
    if fill_color2:
        mid_y = (y1 + y2) / 2
        draw.ellipse([x1 + 2, mid_y, x2 - 2, y2], fill=fill_color2)


def draw_polygon_outlined(draw, points, outline_color, fill_color, outline_w: int = 5):
    draw.polygon(points, fill=outline_color)
    cx_p = sum(p[0] for p in points) / len(points)
    cy_p = sum(p[1] for p in points) / len(points)
    inner = []
    for x, y in points:
        dx, dy = x - cx_p, y - cy_p
        dist = math.sqrt(dx*dx + dy*dy)
        if dist > outline_w * 2:
            inner.append((int(x - dx/dist * outline_w), int(y - dy/dist * outline_w)))
        else:
            inner.append((int(x), int(y)))
    draw.polygon(inner, fill=fill_color)


def draw_pawn(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    draw.ellipse([C-55+so, 230+so, C+55+so, 256+so], fill=SHADOW_COLOR)
    draw.polygon([(C-40+so,230+so),(C+40+so,230+so),(C+24+so,124+so),(C-24+so,124+so)], fill=SHADOW_COLOR)
    draw.ellipse([C-28+so,54+so,C+28+so,110+so], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-54,228,C+54,254], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    body_outer = [(C-42,232),(C+42,232),(C+26,124),(C-26,124)]
    body_inner = [(C-36,230),(C+36,230),(C+21,128),(C-21,128)]
    draw.polygon(body_outer, fill=c['outline']); draw.polygon(body_inner, fill=c['fill'])
    draw.polygon([(C-36,190),(C+36,190),(C+28,230),(C-28,230)], fill=c['fill_dark'])
    draw_ellipse_outlined(draw, [C-24,118,C+24,136], c['outline'], c['highlight'], outline_w=4)
    draw_ellipse_outlined(draw, [C-26,52,C+26,104], c['outline'], c['fill'], outline_w=ow)
    draw.ellipse([C-14,58,C+14,82], fill=c['highlight'])
    return img


def draw_rook(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    draw.ellipse([C-58+so,232+so,C+58+so,258+so], fill=SHADOW_COLOR)
    draw.rectangle([C-46+so,120+so,C+46+so,234+so], fill=SHADOW_COLOR)
    draw.rectangle([C-50+so,96+so,C+50+so,124+so], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-56,230,C+56,256], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    draw.rectangle([C-48,122,C+48,234], fill=c['outline']); draw.rectangle([C-42,126,C+42,232], fill=c['fill'])
    draw.rectangle([C-42,190,C+42,232], fill=c['fill_dark'])
    draw.rectangle([C-52,96,C+52,126], fill=c['outline']); draw.rectangle([C-46,98,C+46,124], fill=c['highlight'])
    bw, bh, gap = 22, 40, 10
    for bx in [C-(bw+gap), C, C+(bw+gap)]:
        x1,y1,x2,y2 = bx-bw//2,56,bx+bw//2,98
        draw.rectangle([x1-4,y1-4,x2+4,y2+4], fill=c['outline']); draw.rectangle([x1,y1,x2,y2], fill=c['fill'])
        draw.rectangle([x1+2,y1+2,x2-2,y1+16], fill=c['highlight'])
    return img


def draw_bishop(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    draw.ellipse([C-52+so,232+so,C+52+so,256+so], fill=SHADOW_COLOR)
    draw.polygon([(C-34+so,232+so),(C+34+so,232+so),(C+20+so,130+so),(C-20+so,130+so)], fill=SHADOW_COLOR)
    draw.polygon([(C+so,20+so),(C-24+so,130+so),(C+24+so,130+so)], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-50,230,C+50,254], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    body_outer = [(C-36,232),(C+36,232),(C+22,128),(C-22,128)]
    body_inner = [(C-30,230),(C+30,230),(C+17,132),(C-17,132)]
    draw.polygon(body_outer, fill=c['outline']); draw.polygon(body_inner, fill=c['fill'])
    draw.polygon([(C-30,190),(C+30,190),(C+25,230),(C-25,230)], fill=c['fill_dark'])
    mitre_outer = [(C,14),(C-26,128),(C-10,108),(C+10,108),(C+26,128)]
    mitre_inner = [(C,20),(C-20,126),(C-6,108),(C+6,108),(C+20,126)]
    draw.polygon(mitre_outer, fill=c['outline']); draw.polygon(mitre_inner, fill=c['fill'])
    draw.polygon([(C,20),(C-14,90),(C+14,90)], fill=c['highlight'])
    draw.rectangle([C-7,2,C+7,18], fill=c['outline']); draw.rectangle([C-5,4,C+5,16], fill=c['fill'])
    draw.rectangle([C-14,6,C+14,12], fill=c['outline']); draw.rectangle([C-12,8,C+12,10], fill=c['highlight'])
    return img


def draw_knight(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    head = [(C-32,232),(C-36,170),(C-40,145),(C-44,120),(C-56,110),(C-64,94),(C-58,78),(C-46,62),(C-32,42),
            (C-22,32),(C-26,14),(C-20,4),(C-12,28),(C+2,28),(C+12,36),(C+20,52),(C+26,72),(C+28,98),
            (C+26,126),(C+28,160),(C+30,232)]
    head_inner = [(C-26,230),(C-30,170),(C-34,146),(C-38,122),(C-48,112),(C-54,96),(C-50,80),(C-42,64),
                  (C-30,46),(C-22,36),(C-22,20),(C-18,12),(C-14,28),(C-2,30),(C+6,34),(C+14,46),
                  (C+20,64),(C+22,90),(C+20,122),(C+22,158),(C+24,230)]
    draw.ellipse([C-52+so,232+so,C+52+so,258+so], fill=SHADOW_COLOR)
    draw.polygon([(x+so,y+so) for x,y in head], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-50,230,C+50,256], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    draw.polygon(head, fill=c['outline']); draw.polygon(head_inner, fill=c['fill'])
    eye_x, eye_y = C-28, 54
    draw.ellipse([eye_x-7,eye_y-7,eye_x+7,eye_y+7], fill=c['outline'])
    draw.ellipse([eye_x-4,eye_y-4,eye_x+4,eye_y+4], fill=c['highlight'])
    draw.ellipse([C-60,88,C-52,96], fill=c['outline'])
    for mx,my,sa,ea in [(C+18,52,200,310),(C+24,80,200,310),(C+26,108,210,300),(C+27,136,210,295)]:
        draw.arc([mx-10,my-10,mx+10,my+10], sa, ea, fill=c['outline'], width=3)
    return img


def draw_queen(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    draw.ellipse([C-58+so,232+so,C+58+so,258+so], fill=SHADOW_COLOR)
    draw.polygon([(C-40+so,232+so),(C+40+so,232+so),(C+30+so,120+so),(C-30+so,120+so)], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-56,230,C+56,256], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    body_outer = [(C-42,232),(C+42,232),(C+32,118),(C-32,118)]
    body_inner = [(C-36,230),(C+36,230),(C+27,122),(C-27,122)]
    draw.polygon(body_outer, fill=c['outline']); draw.polygon(body_inner, fill=c['fill'])
    draw.polygon([(C-36,195),(C+36,195),(C+31,230),(C-31,230)], fill=c['fill_dark'])
    draw_ellipse_outlined(draw, [C-30,110,C+30,128], c['outline'], c['highlight'], outline_w=4)
    draw.rectangle([C-38,54,C+38,112], fill=c['outline']); draw.rectangle([C-32,57,C+32,110], fill=c['fill'])
    for sx in [-34,-17,0,17,34]:
        tip_x = C+sx
        draw.polygon([(tip_x,14),(tip_x-18,56),(tip_x+18,56)], fill=c['outline'])
        draw.polygon([(tip_x,18),(tip_x-14,54),(tip_x+14,54)], fill=c['fill'])
        draw.ellipse([tip_x-4,16,tip_x+4,24], fill=c['highlight'])
    return img


def draw_king(is_white: bool) -> Image.Image:
    c = colors(is_white); img = Image.new('RGBA', (INTERNAL, INTERNAL), (0,0,0,0)); draw = ImageDraw.Draw(img); ow = 6; so = 6
    draw.ellipse([C-60+so,234+so,C+60+so,260+so], fill=SHADOW_COLOR)
    draw.polygon([(C-44+so,234+so),(C+44+so,234+so),(C+34+so,114+so),(C-34+so,114+so)], fill=SHADOW_COLOR)
    draw_ellipse_outlined(draw, [C-58,232,C+58,258], c['outline'], c['fill'], outline_w=ow, fill_color2=c['fill_dark'])
    body_outer = [(C-46,234),(C+46,234),(C+36,114),(C-36,114)]
    body_inner = [(C-40,232),(C+40,232),(C+31,118),(C-31,118)]
    draw.polygon(body_outer, fill=c['outline']); draw.polygon(body_inner, fill=c['fill'])
    draw.polygon([(C-40,195),(C+40,195),(C+35,232),(C-35,232)], fill=c['fill_dark'])
    draw_ellipse_outlined(draw, [C-34,106,C+34,122], c['outline'], c['highlight'], outline_w=4)
    draw.rectangle([C-34,52,C+34,108], fill=c['outline']); draw.rectangle([C-28,55,C+28,106], fill=c['fill'])
    for sx in [-20,0,20]:
        tip_x = C+sx
        draw.polygon([(tip_x,16),(tip_x-20,54),(tip_x+20,54)], fill=c['outline'])
        draw.polygon([(tip_x,20),(tip_x-16,52),(tip_x+16,52)], fill=c['fill'])
        draw.ellipse([tip_x-3,18,tip_x+3,25], fill=c['highlight'])
    draw.rectangle([C-7,2,C+7,28], fill=c['outline']); draw.rectangle([C-5,4,C+5,26], fill=c['fill'])
    draw.rectangle([C-20,8,C+20,18], fill=c['outline']); draw.rectangle([C-17,10,C+17,16], fill=c['fill'])
    draw.rectangle([C-17,10,C+17,14], fill=c['highlight'])
    return img


FALLBACK_DRAWERS = {
    'wK': (draw_king, True), 'wQ': (draw_queen, True), 'wR': (draw_rook, True),
    'wB': (draw_bishop, True), 'wN': (draw_knight, True), 'wP': (draw_pawn, True),
    'bK': (draw_king, False), 'bQ': (draw_queen, False), 'bR': (draw_rook, False),
    'bB': (draw_bishop, False), 'bN': (draw_knight, False), 'bP': (draw_pawn, False),
}


def generate_pieces_fallback(output_dir: Path, size: int = 64):
    """降级方案：内置 PIL 矢量绘制"""
    output_dir.mkdir(parents=True, exist_ok=True)
    for filename, (func, is_white) in FALLBACK_DRAWERS.items():
        img_large = func(is_white)
        img = img_large.resize((size, size), Image.LANCZOS)
        img.save(output_dir / f"{filename}.png")
        print(f"  OK {filename}.png (fallback vector)")
    print(f"\nDone: 12 pieces (PIL vector) → {output_dir}")


# ===================== 主函数 =====================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="生成 Lichess cburnett 风格棋子图片")
    parser.add_argument("--size", type=int, default=256, help="棋子图片尺寸 (默认: 256)")
    parser.add_argument("--output", type=str, default=None, help="输出目录 (默认: pieces/)")
    parser.add_argument("--svg", action="store_true", default=True, help="使用 Lichess SVG (默认)")
    parser.add_argument("--no-svg", action="store_true", help="使用内置 PIL 矢量绘制 (降级)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    output_dir = Path(args.output) if args.output else script_dir / "pieces"

    print("=" * 50)
    print("Lichess cburnett 棋子图片生成器 v3")
    print(f"  尺寸: {args.size}x{args.size}")
    print(f"  输出: {output_dir}")
    print("=" * 50)

    if args.no_svg:
        print("使用内置 PIL 矢量绘制 (降级方案)")
        generate_pieces_fallback(output_dir, args.size)
        return

    # 尝试使用 Lichess SVG
    print("尝试使用 Lichess 官方 cburnett SVG...")
    if generate_pieces_from_lichess(output_dir, args.size):
        return

    # 降级
    print("\nSVG 方案失败，降级到内置 PIL 矢量绘制...")
    generate_pieces_fallback(output_dir, args.size)


if __name__ == "__main__":
    main()
