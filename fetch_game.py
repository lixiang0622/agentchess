"""
对局 PGN 自动抓取模块 (Fetch Game)
支持从 Lichess 和 Chess.com 直接获取 PGN 并保存为本地文件。

用法:
  python fetch_game.py https://lichess.org/abc123XYZ
  python fetch_game.py https://www.chess.com/game/live/123456
  python fetch_game.py  --batch urls.txt

也可作为模块导入:
  from fetch_game import fetch_pgn, save_pgn
  pgn_text = fetch_pgn("https://lichess.org/abc123XYZ")
"""

import sys
import re
import json
import time
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


# ═══════════════════════════════════════════════════════════════
#  Lichess
# ═══════════════════════════════════════════════════════════════

def fetch_pgn_from_lichess(url_or_id: str, with_evals: bool = False,
                           with_clocks: bool = False) -> Optional[str]:
    """
    从 Lichess 获取 PGN。

    Lichess Game Export API:
      GET https://lichess.org/game/export/{gameId}?evals=0&clocks=0
      Accept: application/x-chess-pgn

    支持格式:
      - https://lichess.org/abc123XYZ
      - https://lichess.org/abc123XYZ/white
      - abc123XYZ (纯 ID)
    """
    # 提取 ID
    match = re.search(r'lichess\.org/([a-zA-Z0-9]{8,12})', url_or_id)
    game_id = match.group(1) if match else url_or_id.strip()

    api_url = (
        f"https://lichess.org/game/export/{game_id}"
        f"?evals={'1' if with_evals else '0'}"
        f"&clocks={'1' if with_clocks else '0'}"
    )
    headers = {
        "Accept": "application/x-chess-pgn",
        "User-Agent": "agentchess-fetcher/2.0"}

    if HAS_REQUESTS:
        try:
            resp = requests.get(api_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                print(f"  ✓ Lichess: {game_id} ({len(resp.text)} 字符)")
                return resp.text
            elif resp.status_code == 404:
                print(f"  ✗ Lichess 404: 对局 {game_id} 不存在")
                return None
            else:
                print(f"  ✗ Lichess {resp.status_code}: {resp.text[:100]}")
                return None
        except Exception as e:
            print(f"  ✗ Lichess 请求失败: {e}")
            return None
    else:
        import urllib.request
        try:
            req = urllib.request.Request(api_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                text = resp.read().decode("utf-8")
                print(f"  ✓ Lichess: {game_id} ({len(text)} 字符)")
                return text
        except Exception as e:
            print(f"  ✗ Lichess 请求失败: {e}")
            return None


# ═══════════════════════════════════════════════════════════════
#  Chess.com
# ═══════════════════════════════════════════════════════════════

def fetch_pgn_from_chesscom(url: str, headless: bool = True) -> Optional[str]:
    """
    从 Chess.com 获取 PGN。

    Chess.com 的公开 API 不直接提供单局 PGN。这里用 Playwright:
      1. 打开对局页面 (game/live/123456 或 game/daily/123456)
      2. 查找页面内嵌的 PGN 数据
      3. 或者点击 Share/Download → PGN 按钮获取

    如果 Playwright 不可用，尝试通过 Public API 获取归档:
      https://api.chess.com/pub/player/{username}/games/{year}/{month}/pgn
    """
    # 提取用户名和对局信息
    match = re.search(r'chess\.com/(?:game/|live/|daily/)(\d+)', url)
    if not match:
        match = re.search(r'chess\.com/.*?(?:game|live|daily)/(\d+)', url)
    game_id = match.group(1) if match else ""

    print(f"  Chess.com 对局 ID: {game_id}")

    # 方法1: 尝试 Playwright
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            page = browser.new_page()
            page.set_default_timeout(20000)

            try:
                page.goto(url, wait_until="networkidle")
                page.wait_for_timeout(3000)

                # 尝试找 PGN 按钮并点击
                pgn_btns = [
                    'button[data-cy="pgn-button"]',
                    'button:has-text("PGN")',
                    'button:has-text("Download")',
                    '[class*="share"] button',
                ]
                for selector in pgn_btns:
                    try:
                        btn = page.query_selector(selector)
                        if btn:
                            btn.click()
                            page.wait_for_timeout(1000)
                            break
                    except Exception:
                        continue

                # 获取 PGN 文本
                pgn_selectors = [
                    '.pgn-viewer textarea',
                    '[class*="pgn"] textarea',
                    '.pgn-text',
                    'pre:has-text("1.")',
                ]
                pgn_text = ""
                for sel in pgn_selectors:
                    try:
                        el = page.query_selector(sel)
                        if el:
                            pgn_text = el.inner_text()
                            break
                    except Exception:
                        continue

                # 如果还没找到，尝试从页面提取内嵌数据
                if not pgn_text:
                    page_content = page.content()
                    # Chess.com 有时在 script 标签中内嵌 PGN
                    import re as _re
                    pgn_match = _re.search(
                        r'"pgn"\s*:\s*"([^"]+(?:1\.\s*[a-zA-Z][^"]+)+)"',
                        page_content
                    )
                    if pgn_match:
                        pgn_text = pgn_match.group(1).replace('\\n', '\n')

                browser.close()

                if pgn_text and "1." in pgn_text:
                    print(f"  ✓ Chess.com: {game_id} ({len(pgn_text)} 字符)")
                    return pgn_text
                else:
                    print(f"  ✗ Chess.com: 未找到 PGN 数据")
                    return None

            except Exception as e:
                browser.close()
                print(f"  ✗ Chess.com Playwright 失败: {e}")
                return None

    except ImportError:
        pass

    # 方法2: Public API（需要知道用户名）
    print("  ⚠ Playwright 不可用且无法通过 Public API 获取 PGN")
    print("    提示: pip install playwright && playwright install chromium")
    return None


# ═══════════════════════════════════════════════════════════════
#  统一入口
# ═══════════════════════════════════════════════════════════════

def fetch_pgn(source: str) -> Optional[str]:
    """
    自动识别来源（Lichess/Chess.com/本地文件）并获取 PGN。

    Args:
        source: URL 或本地文件路径

    Returns:
        PGN 文本字符串
    """
    if "lichess.org" in source.lower():
        return fetch_pgn_from_lichess(source)
    elif "chess.com" in source.lower():
        return fetch_pgn_from_chesscom(source)
    else:
        # 假定本地文件
        p = Path(source)
        if p.exists():
            with p.open("r", encoding="utf-8") as f:
                text = f.read()
            print(f"  ✓ 本地文件: {p.name} ({len(text)} 字符)")
            return text
        else:
            print(f"  ✗ 找不到: {source}")
            return None


def save_pgn(pgn_text: str, output_dir: Path = None) -> Path:
    """
    保存 PGN 到项目目录，自动提取选手名和对局日期命名。

    Returns:
        保存的文件路径
    """
    import chess.pgn

    try:
        game = chess.pgn.read_game(
            __import__('io').StringIO(pgn_text) if isinstance(pgn_text, str)
            else pgn_text
        )
    except Exception:
        # 简单写入
        import io as _io
        game = chess.pgn.read_game(_io.StringIO(pgn_text))

    if game is None:
        raise ValueError("无法解析 PGN")

    headers = game.headers
    white = headers.get("White", "white").replace(" ", "_")
    black = headers.get("Black", "black").replace(" ", "_")
    date = headers.get("Date", "????.??.??").replace(".", "")

    filename = f"lichess_pgn_{date}_{white}_vs_{black}.pgn"
    if output_dir is None:
        output_dir = Path(__file__).parent

    filepath = output_dir / filename
    with filepath.open("w", encoding="utf-8") as f:
        f.write(pgn_text)

    print(f"  ✓ 已保存: {filepath}")
    return filepath


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="对局 PGN 抓取工具")
    parser.add_argument("source", nargs="?", help="Lichess/Chess.com URL 或本地文件路径")
    parser.add_argument("--batch", type=str, help="批量抓取 URL 列表文件")
    parser.add_argument("--output-dir", type=str, help="输出目录")
    parser.add_argument("--test", action="store_true", help="自测模式")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else Path(__file__).parent

    if args.test:
        print("=" * 60)
        print("fetch_game 自测")
        print("=" * 60)

        # 测试 Lichess
        print("\n测试 Lichess:")
        pgn = fetch_pgn_from_lichess("https://lichess.org/abc123TEST")
        if pgn:
            print(f"  获取到 {len(pgn)} 字符")

        # 测试本地
        local_pgns = list(Path(__file__).parent.glob("lichess_pgn*.pgn"))
        if local_pgns:
            print(f"\n测试本地 PGN: {local_pgns[0].name}")
            pgn = fetch_pgn(str(local_pgns[0]))
            print(f"  获取到 {len(pgn)} 字符")
        return

    if args.batch:
        urls = Path(args.batch)
        if not urls.exists():
            print(f"文件不存在: {args.batch}")
            return
        with urls.open("r") as f:
            lines = [l.strip() for l in f if l.strip()]
        print(f"批量抓取 {len(lines)} 个对局...")
        for line in lines:
            print(f"\n--- {line[:60]} ---")
            pgn = fetch_pgn(line)
            if pgn:
                save_pgn(pgn, output_dir)
            time.sleep(1)
    elif args.source:
        pgn = fetch_pgn(args.source)
        if pgn:
            save_pgn(pgn, output_dir)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()