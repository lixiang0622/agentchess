"""
Lichess 开局数据库抓取脚本 (Playwright 版)
使用无头浏览器模拟真实用户访问 lichess.org/opening，抓取 JS 渲染后的统计数据。

用法:
  python fetch_opening_data.py --batch e4 e5 Nf3 Nc6 Bb5
  python fetch_opening_data.py --preset              # 批量抓取预设列表
  python fetch_opening_data.py --preset --headless   # 无头模式(后台运行)
  python fetch_opening_data.py --wiki "Italian Game" # Wikipedia 摘要
"""

import sys
import json
import time
import asyncio
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("请先安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)

try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "opening_knowledge_fetched.json"


# ═══════════════════════════════════════════════════════════════
#  Playwright 抓取 Lichess Opening Explorer
# ═══════════════════════════════════════════════════════════════

def moves_to_fen(moves_san: list) -> str:
    """将 SAN 走法列表转为 FEN"""
    import chess
    board = chess.Board()
    for san in moves_san:
        try:
            board.push_san(san)
        except ValueError:
            print(f"  ⚠ 非法走法: {san}")
            break
    return board.fen()


async def scrape_lichess_opening(moves_san: list, headless: bool = True) -> dict:
    """
    用 Playwright 打开 lichess.org/opening 页面并抓取开局统计数据。

    页面结构: Lichess 开局浏览器在 FEN 棋盘下方有一个走法统计表格。
    每一行格式: 走法名称 | 盘数 | 百分比 | 白方胜率 | 和棋率 | 黑方胜率
    """
    fen = moves_to_fen(moves_san)
    url = f"https://lichess.org/opening?fen={fen}"
    move_sequence_str = " ".join(moves_san)

    print(f"\n{'='*60}")
    print(f"抓取: {move_sequence_str[:50]}")
    print(f"URL:  {url}")
    print(f"{'='*60}")

    moves_data = []
    opening_name = ""
    eco_code = ""
    entry = None

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        page = await context.new_page()

        try:
            # 访问页面
            await page.goto(url, wait_until="networkidle", timeout=30000)
            # 额外等待渲染
            await page.wait_for_timeout(3000)

            # 获取开局名称
            try:
                name_el = await page.query_selector("h1.opening__title, .opening-name, [data-opening-name]")
                if not name_el:
                    name_el = await page.query_selector("h1")
                if name_el:
                    opening_name = (await name_el.text_content()).strip()
                    print(f"  ✓ 开局名称: {opening_name}")
            except Exception:
                pass

            # 提取 ECO 代码
            try:
                eco_el = await page.query_selector(".opening__eco, [data-eco]")
                if eco_el:
                    eco_code = (await eco_el.text_content()).strip()
                    print(f"  ✓ ECO: {eco_code}")
            except Exception:
                # 尝试从名称中提取
                eco_match = re.search(r'\(([A-E]\d{2})\)', opening_name)
                if eco_match:
                    eco_code = eco_match.group(1)

            # 方法 A: 获取走法统计表格
            # Lichess 在 opening explorer 中显示了两个 tab:
            #   "Lichess" (全平台数据) 和 "Masters" (大师数据)
            # 我们先取全平台数据，再取大师数据

            for tab_name, tab_selector in [
                ("lichess", "div.explorer__title:has-text('Lichess')"),
                ("masters", "div.explorer__title:has-text('Masters')"),
            ]:
                try:
                    # 点击对应 tab（Masters tab）
                    if tab_name == "masters":
                        tab_btn = await page.query_selector("span:has-text('Masters')")
                        if tab_btn:
                            await tab_btn.click()
                            await page.wait_for_timeout(1500)

                    # 提取表格行
                    rows = await page.query_selector_all("table.explorer__moves tr, .explorer__moves .moves tbody tr")
                    if not rows:
                        # 备用选择器
                        rows = await page.query_selector_all("[data-move]")

                    tab_moves = []
                    for row in rows:
                        try:
                            cells = await row.query_selector_all("td, th, span")
                            texts = []
                            for cell in cells:
                                t = (await cell.text_content()).strip()
                                if t:
                                    texts.append(t)

                            if len(texts) >= 3:
                                san = texts[0]
                                count_str = texts[1] if len(texts) > 1 else "0"
                                pct_str = texts[2] if len(texts) > 2 else "0"

                                # 解析数字
                                count = int(re.sub(r'[^\d]', '', count_str)) if re.sub(r'[^\d]', '', count_str) else 0
                                pct = float(re.sub(r'[^\d.]', '', pct_str)) if re.sub(r'[^\d.]', '', pct_str).replace('.', '', 1).isdigit() else 0

                                tab_moves.append({
                                    "san": san,
                                    "count": count,
                                    "pct": pct,
                                    "source": tab_name,
                                })
                        except Exception:
                            continue

                    if tab_moves:
                        moves_data.extend(tab_moves)
                        print(f"  ✓ {tab_name} tab: {len(tab_moves)} 个走法")

                except Exception as e:
                    print(f"  ⚠ {tab_name} tab 抓取失败: {e}")

            # 方法 B: 如果表格抓不到，找嵌入的 JSON 数据
            if not moves_data:
                try:
                    html = await page.content()
                    # 找 <script> 中的 opening 数据
                    json_match = re.search(r'lichess\.opening\s*=\s*({.+?});', html, re.DOTALL)
                    if not json_match:
                        json_match = re.search(r'"moves"\s*:\s*\[.+?\]', html, re.DOTALL)
                    if json_match:
                        print(f"  ℹ 找到嵌入 JSON 数据")
                except Exception:
                    pass

            if not opening_name:
                try:
                    title = await page.title()
                    if title:
                        opening_name = title.split("•")[0].strip()
                except Exception:
                    pass

        except Exception as e:
            print(f"  ✗ 页面抓取失败: {e}")
        finally:
            await browser.close()

    # 构建结果
    total = sum(m.get("count", 0) for m in moves_data) if moves_data else 0

    entry = {
        "eco_code": eco_code or "?",
        "name": opening_name or f"未知: {' '.join(moves_san[:4])}",
        "moves_sequence": moves_san,
        "fen_signature": fen,
        "stats": {
            "total_games": total,
            "source": "lichess_playwright",
        },
        "top_moves": sorted(moves_data, key=lambda m: m.get("count", 0), reverse=True)[:5],
        "typical_plans": {
            "white": ["(需手工补充)"],
            "black": ["(需手工补充)"],
        },
        "common_traps": [],
        "famous_practitioners": [],
    }

    return entry


# ═══════════════════════════════════════════════════════════════
#  批量抓取
# ═══════════════════════════════════════════════════════════════

async def batch_scrape(lines: list, output_path: Path, headless: bool = True):
    results = []
    for i, line in enumerate(lines):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        parts = line.split("|")
        moves_str = parts[0].strip()
        name = parts[1].strip() if len(parts) > 1 else ""
        eco = parts[2].strip() if len(parts) > 2 else ""
        moves = moves_str.split()
        if not moves:
            continue

        entry = await scrape_lichess_opening(moves, headless=headless)
        if entry:
            if name and "未知" in entry.get("name", ""):
                entry["name"] = name
            if eco and entry.get("eco_code") in ("?", ""):
                entry["eco_code"] = eco
            results.append(entry)

        # 限速
        if i < len(lines) - 1:
            time.sleep(1)

    # 保存
    if results and output_path:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 已保存 {len(results)} 个开局到 {output_path}")

    return results


# ═══════════════════════════════════════════════════════════════
#  Wikipedia (保持不变)
# ═══════════════════════════════════════════════════════════════

def fetch_wikipedia_summary(title: str) -> str:
    """从 Wikipedia REST API 获取摘要"""
    try:
        import urllib.request
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
        req = urllib.request.Request(url, headers={"User-Agent": "agentchess/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        extract = data.get("extract", "")
        if extract:
            print(f"  ✓ Wikipedia: {len(extract)} 字符")
            return extract
    except Exception as e:
        print(f"  ⚠ Wikipedia: {e}")
    return ""


# ═══════════════════════════════════════════════════════════════
#  预设
# ═══════════════════════════════════════════════════════════════

PRESET_OPENINGS = [
    "# === 王兵开局 ===",
    "e4 e5 Nf3 Nc6 Bc4|意大利开局|C50",
    "e4 e5 Nf3 Nc6 Bb5|西班牙开局|C60",
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6|西班牙莫菲防御|C78",
    "e4 e5 Nf3 Nc6 Bc4 Bc5|意大利吉乌科钢琴|C54",
    "e4 e5 Nf3 Nc6 Bc4 Nf6|双马防御|C55",
    "e4 e5 Nf3 Nf6|俄罗斯防御|C42",
    "e4 e5 Nf3 Nc6 d4|苏格兰开局|C45",
    "e4 e5 f4|王翼弃兵|C30",
    "e4 e5 Nc3|维也纳开局|C25",
    "# === 西西里防御体系 ===",
    "e4 c5|西西里防御|B20",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6|纳道尔夫变例|B90",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6|龙式变例|B35",
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5|斯韦什尼科夫变例|B33",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6|舍维宁根变例|B80",
    "# === 半开放防御 ===",
    "e4 e6 d4 d5|法兰西防御|C00",
    "e4 c6 d4 d5|卡罗康防御|B10",
    "e4 Nf6|阿廖欣防御|B03",
    "e4 g6|现代防御|B06",
    "# === 后兵开局 ===",
    "d4 d5 c4|后翼弃兵|D06",
    "d4 d5 c4 dxc4|后翼弃兵接受|D20",
    "d4 d5 c4 e6 Nc3 Nf6|后翼弃兵正统|D35",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5|后翼弃兵正统主变|D35",
    "d4 d5 c4 c6|斯拉夫防御|D10",
    "d4 d5 c4 c6 Nc3 Nf6 e3 e6 Nf3 Nbd7|半斯拉夫|D45",
    "d4 d5 c4 e6 Nc3 Nf6 Nf3 c5 cxd5 Nxd5|半塔拉什|D41",
    "# === 印度防御体系 ===",
    "d4 Nf6 c4 e6 Nc3 Bb4|尼姆佐维奇防御|E20",
    "d4 Nf6 c4 g6 Nc3 d5|格林菲尔德防御|D85",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6|古印度防御|E60",
    "d4 Nf6 c4 e6 Nf3 b6|新印度防御|E12",
    "d4 Nf6 c4 e6 g3|卡塔兰开局|E00",
    "d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6|现代别诺尼|A60",
    "# === 其他体系 ===",
    "d4 f5|荷兰防御|A80",
    "Nf3 d5|列蒂开局|A04",
    "c4 e5|英国式开局|A10",
    "e4 e5 Nf3 Nc6 Bb5 Nf6|西班牙柏林防御|C65",
]


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lichess 开局数据抓取 (Playwright)")
    parser.add_argument("--batch", nargs="+", help="走法序列 'e4 e5 Nf3 Nc6 Bb5'")
    parser.add_argument("--preset", action="store_true", help="批量抓取预设 35 个开局")
    parser.add_argument("--headless", action="store_true", default=True,
                        help="无头模式 (默认)")
    parser.add_argument("--visible", action="store_true", help="显示浏览器窗口")
    parser.add_argument("--output", type=str, default="opening_knowledge_fetched.json")
    parser.add_argument("--wiki", type=str, help="Wikipedia 摘要")
    args = parser.parse_args()

    headless = not args.visible

    if args.wiki:
        desc = fetch_wikipedia_summary(args.wiki)
        print(f"\nWikipedia ({args.wiki}):\n{desc[:800] if desc else '未找到'}")
        return

    output_path = SCRIPT_DIR / args.output

    if args.batch:
        lines = [" ".join(args.batch) + "||"]
    elif args.preset:
        lines = PRESET_OPENINGS
    else:
        print("用法:")
        print("  python fetch_opening_data.py --preset")
        print("  python fetch_opening_data.py --preset --visible   # 可见浏览器")
        print("  python fetch_opening_data.py --batch e4 e5 Nf3 Nc6 Bb5")
        print("  python fetch_opening_data.py --wiki 'Italian Game'")
        return

    asyncio.run(batch_scrape(lines, output_path, headless=headless))


if __name__ == "__main__":
    main()