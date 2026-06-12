"""
Lichess 开局数据库自动抓取脚本

功能:
  1. 从 Lichess Opening Explorer API 抓取开局统计数据（胜率、流行度、常见走法）
  2. 从 Lichess 大师数据库抓取大师对局示例
  3. 可选: 从 Wikipedia/Wikibooks 抓取开局描述和计划
  4. 输出为 opening_knowledge.json 兼容格式

用法:
  python fetch_opening_data.py                          # 交互式查询
  python fetch_opening_data.py --batch e4 c5 Nf3 d6    # 查询特定序列
  python fetch_opening_data.py --batch-file eco_list.txt # 批量查询
  python fetch_opening_data.py --wiki C50               # 尝试获取 Wiki 描述
"""

import sys
import json
import time
import urllib.request
import urllib.parse
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# 优先使用 requests，回退到 urllib
try:
    import requests as _requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


def _api_get(url, timeout=10):
    """统一的 API GET 请求"""
    if HAS_REQUESTS:
        r = _requests.get(url, headers={"User-Agent": "agentchess-fetcher/1.0"}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return None
    else:
        req = urllib.request.Request(url, headers={"User-Agent": "agentchess-fetcher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


def _api_post(url, data, timeout=10):
    """统一的 API POST 请求"""
    if HAS_REQUESTS:
        r = _requests.post(url, json=data,
                          headers={"Content-Type": "application/json",
                                   "User-Agent": "agentchess-fetcher/1.0"},
                          timeout=timeout)
        if r.status_code == 200:
            return r.json()
        return None
    else:
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json",
                     "User-Agent": "agentchess-fetcher/1.0"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "opening_knowledge_fetched.json"


# ═══════════════════════════════════════════════════════════════
#  Lichess Opening Explorer API
# ═══════════════════════════════════════════════════════════════

def fetch_lichess_masters(fen: str, top_games: int = 5) -> dict:
    """
    从 Lichess Masters Database 获取大师对局数据。
    """
    url = (
        f"https://explorer.lichess.ovh/masters"
        f"?fen={urllib.parse.quote(fen, safe='')}"
        f"&topGames={top_games}"
    )
    try:
        data = _api_get(url)
        if data:
            total = data.get("white", 0) + data.get("draws", 0) + data.get("black", 0)
            print(f"  ✓ Lichess Masters: {total:,} 盘大师对局")
            return data
        else:
            print(f"  ✗ API 返回空/401")
            return None
    except Exception as e:
        print(f"  ✗ API 失败: {e}")
        return None


def fetch_lichess_opening_explorer(fen: str) -> dict:
    """
    从 Lichess Opening Explorer 获取全平台开局数据。
    """
    url = "https://explorer.lichess.ovh/lichess"
    payload = {
        "fen": fen,
        "variant": "standard",
        "speeds": ["blitz", "rapid", "classical"],
        "ratings": [1600, 1800, 2000, 2200, 2500],
    }
    try:
        data = _api_post(url, payload)
        if data:
            total = data.get("white", 0) + data.get("draws", 0) + data.get("black", 0)
            print(f"  ✓ Lichess Explorer: {total:,} 盘对局")
            return data
        else:
            print(f"  ✗ Explorer 返回空/401")
            return None
    except Exception as e:
        print(f"  ✗ Explorer 失败: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  Wikipedia / Wikibooks 爬取
# ═══════════════════════════════════════════════════════════════

WIKIBOOKS_BASE = "https://en.wikibooks.org/wiki/Chess_Opening_Theory"


def fetch_wikibooks_opening(eco_or_name: str) -> str:
    """
    尝试从 Wikibooks Chess Opening Theory 获取开局描述。
    """
    # 先尝试直接用名称
    name_encoded = urllib.parse.quote(eco_or_name.replace(" ", "_"))
    url = f"{WIKIBOOKS_BASE}/{name_encoded}"
    req = urllib.request.Request(url, headers={"User-Agent": "agentchess-fetcher/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8")
        # 简单提取正文
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text)
        # 找开局描述段落
        for keyword in ["opening", "Opening", "is a chess opening", "characterised by"]:
            idx = text.find(keyword)
            if idx > 0:
                snippet = text[max(0, idx-50):idx+500]
                print(f"  ✓ Wiki 找到描述片段")
                return snippet.strip()
        print(f"  ⚠ Wiki 页面存在但未找到描述段落")
        return ""
    except Exception as e:
        print(f"  ⚠ Wiki 获取失败: {e}")
        return ""


def fetch_wikipedia_summary(title: str) -> str:
    """
    从 Wikipedia API 获取摘要。
    使用 REST API (更简单) 或标准 API 回退。
    """
    # Method 1: REST API summary
    wiki_rest_url = (
        "https://en.wikipedia.org/api/rest_v1/page/summary/"
        f"{urllib.parse.quote(title.replace(' ', '_'))}"
    )
    try:
        data = _api_get(wiki_rest_url)
        if data:
            extract = data.get("extract", "")
            if extract:
                print(f"  ✓ Wikipedia 获取成功 ({len(extract)} 字符)")
                return extract
    except Exception:
        pass

    # Method 2: Standard API with extracts
    url = (
        "https://en.wikipedia.org/w/api.php"
        f"?action=query&format=json&prop=extracts&exintro=1"
        f"&explaintext=1&titles={urllib.parse.quote(title)}"
    )
    try:
        data = _api_get(url)
        if data:
            pages = data.get("query", {}).get("pages", {})
            for pid, page in pages.items():
                extract = page.get("extract", "")
                if extract and pid != "-1":
                    print(f"  ✓ Wikipedia 获取成功 ({len(extract)} 字符)")
                    return extract
    except Exception as e:
        print(f"  ⚠ Wikipedia 获取失败: {e}")
    return ""


# ═══════════════════════════════════════════════════════════════
#  数据整合
# ═══════════════════════════════════════════════════════════════

def build_opening_entry_from_api(
    moves_sequence: list,
    eco_code: str = "",
    name: str = "",
) -> dict:
    """
    根据走法序列，从 Lichess API 构建一个开局知识条目。

    Args:
        moves_sequence: SAN 走法列表
        eco_code: ECO 代码（可选，自动尝试获取）
        name: 开局名称（可选，自动尝试获取）

    Returns:
        opening_knowledge.json 格式的条目
    """
    # 推演到走法序列末尾，获取 FEN
    import chess
    board = chess.Board()
    for san in moves_sequence:
        try:
            board.push_san(san)
        except ValueError:
            print(f"  ✗ 非法走法: {san}")
            return None
    fen = board.fen()

    print(f"\n{'='*60}")
    print(f"查询: {' '.join(moves_sequence[:6])}")
    if len(moves_sequence) > 6:
        print(f"      ...{' '.join(moves_sequence[-4:])}")
    print(f"FEN:  {fen[:60]}...")
    print(f"{'='*60}")

    time.sleep(0.5)  # 限速

    # 1. 大师数据库
    masters = fetch_lichess_masters(fen, top_games=5)

    # 2. 全平台数据
    explorer = fetch_lichess_opening_explorer(fen)

    # 提取数据
    total_games = 0
    white_win_pct = 0
    draw_pct = 0
    black_win_pct = 0
    top_moves = []
    top_players = []

    if masters:
        w = masters.get("white", 0)
        d = masters.get("draws", 0)
        b = masters.get("black", 0)
        total_games = w + d + b
        white_win_pct = round(w / total_games * 100, 1) if total_games else 0
        draw_pct = round(d / total_games * 100, 1) if total_games else 0
        black_win_pct = round(b / total_games * 100, 1) if total_games else 0

        # 常见走法
        raw_moves = masters.get("moves", [])
        for m in sorted(raw_moves, key=lambda x: x.get("white", 0)+x.get("draws", 0)+x.get("black", 0), reverse=True)[:5]:
            mt = m.get("white", 0) + m.get("draws", 0) + m.get("black", 0)
            top_moves.append({
                "san": m.get("san", "?"),
                "count": mt,
                "pct": round(mt / total_games * 100, 1) if total_games else 0,
                "white_win": m.get("white", 0),
                "draw": m.get("draws", 0),
                "black_win": m.get("black", 0),
            })

        # 著名棋手
        top_games = masters.get("topGames", [])
        for g in top_games[:3]:
            w_name = (g.get("white") or {}).get("name", "?")
            b_name = (g.get("black") or {}).get("name", "?")
            winner = g.get("winner", "")
            year = g.get("year", "")
            top_players.append(f"{w_name} ({year})" if w_name else "")

    # 如果没有大师数据，用全平台数据
    if not total_games and explorer:
        w = explorer.get("white", 0)
        d = explorer.get("draws", 0)
        b = explorer.get("black", 0)
        total_games = w + d + b
        white_win_pct = round(w / total_games * 100, 1) if total_games else 0
        draw_pct = round(d / total_games * 100, 1) if total_games else 0
        black_win_pct = round(b / total_games * 100, 1) if total_games else 0

    # 自动获取名称
    if not name and explorer:
        opening_info = explorer.get("opening", {})
        name = opening_info.get("name", "")
    if not eco_code and explorer:
        opening_info = explorer.get("opening", {})
        eco_code = opening_info.get("eco", "")

    # 构建条目
    entry = {
        "eco_code": eco_code or "?",
        "name": name or f"未知开局: {' '.join(moves_sequence[2:6])}",
        "moves_sequence": moves_sequence,
        "fen_signature": fen,
        "stats": {
            "total_master_games": total_games,
            "white_win_pct": white_win_pct,
            "draw_pct": draw_pct,
            "black_win_pct": black_win_pct,
            "source": "master" if masters else "lichess",
        },
        "top_moves": top_moves,
        "recent_practitioners": top_players[:5],
        "typical_plans": {
            "white": ["(需手工补充 — 从开局百科或教练经验中获取)"],
            "black": ["(需手工补充 — 从开局百科或教练经验中获取)"],
        },
        "common_traps": [],
        "famous_practitioners": [],
        "_note": "统计数据自动获取于 Lichess，计划和陷阱需手工补充",
    }

    return entry


# ═══════════════════════════════════════════════════════════════
#  批量查询
# ═══════════════════════════════════════════════════════════════

def batch_query(lines: list, output_path: Path = None) -> list:
    """
    批量查询多个走法序列。

    Args:
        lines: 每行一个开局，格式 "e4 e5 Nf3 Nc6 Bc4|意大利开局|C50"
        output_path: 输出 JSON 路径

    Returns:
        条目列表
    """
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

        print(f"\n[{i+1}/{len(lines)}] {' '.join(moves[:4])}...")
        entry = build_opening_entry_from_api(moves, eco, name)
        if entry:
            results.append(entry)

        if i < len(lines) - 1:
            time.sleep(1)  # API 限速

    if output_path and results:
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n✓ 已保存 {len(results)} 个开局到 {output_path}")

    return results


# ═══════════════════════════════════════════════════════════════
#  Wiki 内容获取 & 自动填空
# ═══════════════════════════════════════════════════════════════

def fetch_wiki_descriptions(eco_codes_or_names: list) -> dict:
    """
    为多个 ECO 代码或开局名称尝试获取 Wiki 描述。

    Returns:
        {eco_code: description_text, ...}
    """
    results = {}
    for item in eco_codes_or_names:
        print(f"\n查询 Wiki: {item}...")
        # 先试 Wikibooks
        desc = fetch_wikibooks_opening(item)
        if not desc:
            # 再试 Wikipedia
            wiki_title = f"{item} (chess opening)"
            desc = fetch_wikipedia_summary(wiki_title)
        if not desc:
            desc = fetch_wikipedia_summary(item)
        results[item] = desc if desc else ""
        time.sleep(0.5)
    return results


# ═══════════════════════════════════════════════════════════════
#  预设开局列表
# ═══════════════════════════════════════════════════════════════

PRESET_OPENINGS = [
    "e4 e5 Nf3 Nc6 Bc4|意大利开局|C50",
    "e4 e5 Nf3 Nc6 Bb5|西班牙开局|C60",
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6|西班牙开局莫菲防御|C78",
    "e4 c5|西西里防御|B20",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6|西西里纳道尔夫|B90",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6|西西里龙式|B35",
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5|西西里斯韦什尼科夫|B33",
    "e4 e6 d4 d5|法兰西防御|C00",
    "e4 c6 d4 d5|卡罗康防御|B10",
    "e4 Nf6|阿廖欣防御|B03",
    "e4 g6|现代防御|B06",
    "e4 e5 Nc3|维也纳开局|C25",
    "e4 e5 f4|王翼弃兵|C30",
    "e4 e5 Nf3 Nf6|俄罗斯防御|C42",
    "e4 e5 Nf3 Nc6 d4|苏格兰开局|C45",
    "d4 d5 c4|后翼弃兵|D06",
    "d4 d5 c4 dxc4|后翼弃兵接受|D20",
    "d4 d5 c4 e6 Nc3 Nf6|后翼弃兵正统防御|D35",
    "d4 d5 c4 c6|斯拉夫防御|D10",
    "d4 Nf6 c4 e6 Nc3 Bb4|尼姆佐维奇防御|E20",
    "d4 Nf6 c4 g6 Nc3 d5|格林菲尔德防御|D85",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6|古印度防御|E60",
    "d4 Nf6 c4 e6 Nf3 b6|新印度防御|E12",
    "d4 f5|荷兰防御|A80",
    "Nf3 d5|列蒂开局|A04",
    "c4 e5|英国式开局|A10",
    "d4 d5 c4 e6 Nc3 Nf6 Nf3 c5 cxd5 Nxd5|半塔拉什防御|D41",
    "d4 d5 c4 c6 Nc3 Nf6 e3 e6 Nf3 Nbd7|半斯拉夫防御|D45",
    "d4 Nf6 c4 e6 g3|卡塔兰开局|E00",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 e6|西西里舍维宁根|B80",
    "e4 e5 Nf3 Nc6 Bc4 Bc5|意大利开局吉乌科钢琴|C54",
    "e4 e5 Nf3 Nc6 Bc4 Nf6|双马防御|C55",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5|后翼弃兵正统防御主变|D35",
    "d4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6|现代别诺尼|A60",
    "e4 e5 Nf3 Nc6 Bb5 Nf6|西班牙柏林防御|C65",
]


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lichess 开局数据抓取工具")
    parser.add_argument("--batch", nargs="+", help="走法序列，如 'e4 e5 Nf3 Nc6 Bc4'")
    parser.add_argument("--batch-file", type=str, help="批量查询文件路径（每行一个开局）")
    parser.add_argument("--preset", action="store_true", help="使用内置 35 个预设开局列表")
    parser.add_argument("--output", type=str, default="opening_knowledge_fetched.json",
                        help="输出 JSON 文件名")
    parser.add_argument("--wiki", type=str, help="获取指定 ECO 的 Wiki 描述")
    parser.add_argument("--stats-only", action="store_true",
                        help="仅获取统计数据，不获取 Wiki（快速模式）")
    args, remaining = parser.parse_known_args()

    output_path = SCRIPT_DIR / args.output

    if args.wiki:
        desc = fetch_wikibooks_opening(args.wiki)
        print(f"\nWiki 描述 ({args.wiki}):\n{desc[:500] if desc else '未找到'}")
        return

    if args.batch:
        lines = [" ".join(args.batch) + "||"]
    elif args.preset:
        lines = PRESET_OPENINGS
    elif args.batch_file:
        bf = Path(args.batch_file)
        if not bf.exists():
            print(f"文件不存在: {bf}")
            return
        with bf.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    else:
        print("使用方法:")
        print("  python fetch_opening_data.py --preset")
        print("  python fetch_opening_data.py --batch e4 e5 Nf3 Nc6 Bc4")
        print("  python fetch_opening_data.py --batch-file eco_list.txt")
        print("  python fetch_opening_data.py --wiki C50")
        return

    results = batch_query(lines, output_path)

    print(f"\n{'='*60}")
    print(f"✓ 完成。共获取 {len(results)} 个开局的数据。")
    print(f"  输出文件: {output_path}")
    print(f"\n提示: 获取到的计划(typical_plans)和陷阱(common_traps)字段为空，")
    print(f"      需要手工补充。也可以使用 --wiki 参数单独查询每个开局的描述。")


if __name__ == "__main__":
    main()