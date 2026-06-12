"""
大师库动态更新模块 (Update Master DB)
每周自动从 TWIC (The Week in Chess) 下载最新比赛 PGN，更新大师对局索引。

数据来源:
  - TWIC: https://theweekinchess.com/zips/twic{g}.zip  (g = 1560+)
  - 备选: Lichess Masters 广播

用法:
  python update_master_db.py                     # 更新最新 5 期
  python update_master_db.py --from 1560 --to 1565  # 指定范围
  python update_master_db.py --auto               # 自动检测最新期号
  python update_master_db.py --stats              # 查看当前索引状态

与 master_games_db.py 集成:
  from update_master_db import update_from_twic
  db = MasterGamesDB()
  db.load_index()
  added = update_from_twic(db, start=1560, end=1565)
  db.save_index()
"""

import sys
import re
import io
import zipfile
import time
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

try:
    import chess
    import chess.pgn
except ImportError:
    print("需要 python-chess: pip install python-chess")
    sys.exit(1)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

SCRIPT_DIR = Path(__file__).parent
TWIC_BASE = "https://theweekinchess.com/zips/"
# TWIC 最新期号通常每周 +1，运行时可以自动探测
DEFAULT_START_TWIC = 1560
INDEX_FILE = SCRIPT_DIR / "master_games_index.pkl"
STATUS_FILE = SCRIPT_DIR / "master_db_status.json"


# ═══════════════════════════════════════════════════════════════
#  TWIC 下载与解析
# ═══════════════════════════════════════════════════════════════

def download_twic_zip(issue_num: int) -> Optional[zipfile.ZipFile]:
    """下载指定期号的 TWIC ZIP 文件"""
    url = f"{TWIC_BASE}twic{issue_num}.zip"

    if HAS_REQUESTS:
        try:
            resp = requests.get(url, timeout=60, stream=True)
            if resp.status_code == 200:
                content = resp.content
                return zipfile.ZipFile(io.BytesIO(content))
            elif resp.status_code == 404:
                print(f"  TWIC {issue_num}: 404 (不存在)")
                return None
            else:
                print(f"  TWIC {issue_num}: HTTP {resp.status_code}")
                return None
        except Exception as e:
            print(f"  TWIC {issue_num}: 下载失败 ({e})")
            return None
    else:
        import urllib.request
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "agentchess-updater/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                content = resp.read()
            return zipfile.ZipFile(io.BytesIO(content))
        except Exception as e:
            print(f"  TWIC {issue_num}: 下载失败 ({e})")
            return None


def parse_twic_games(zf: zipfile.ZipFile, max_games: int = 0) -> list[chess.pgn.Game]:
    """从 TWIC ZIP 中解析所有对局"""
    games = []
    pgn_files = [f for f in zf.namelist() if f.endswith('.pgn') or f.endswith('.PGN')]

    if not pgn_files:
        return games

    for pgn_name in pgn_files:
        try:
            with zf.open(pgn_name) as f:
                text = f.read().decode('utf-8', errors='replace')
        except Exception:
            continue

        pgn_io = io.StringIO(text)
        while True:
            game = chess.pgn.read_game(pgn_io)
            if game is None:
                break

            # 只收录大师级别对局（双2500+）
            try:
                w_elo = int(game.headers.get("WhiteElo", "0"))
                b_elo = int(game.headers.get("BlackElo", "0"))
            except ValueError:
                continue

            if w_elo >= 2400 and b_elo >= 2400:
                games.append(game)

            if max_games and len(games) >= max_games:
                break

    return games


# ═══════════════════════════════════════════════════════════════
#  自动检测最新期号
# ═══════════════════════════════════════════════════════════════

def find_latest_twic(base: int = 1560, max_probe: int = 20) -> int:
    """从 base 开始向上探测，找到最新可用的 TWIC 期号"""
    latest = base
    for issue in range(base, base + max_probe):
        url = f"{TWIC_BASE}twic{issue}.zip"
        try:
            if HAS_REQUESTS:
                resp = requests.head(url, timeout=10)
                if resp.status_code == 200:
                    latest = issue
                    print(f"  TWIC {issue}: 存在")
                elif resp.status_code == 404:
                    print(f"  TWIC {issue}: 404 (已到达最新)")
                    break
            else:
                import urllib.request
                req = urllib.request.Request(url, headers={"User-Agent": "agentchess/1.0"}, method="HEAD")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    latest = issue
        except Exception:
            break
    return latest


# ═══════════════════════════════════════════════════════════════
#  更新大师索引
# ═══════════════════════════════════════════════════════════════

def update_from_twic(db, start: int, end: int) -> dict:
    """
    从 TWIC 下载并更新大师对局索引。

    Args:
        db: MasterGamesDB 实例
        start: 起始期号
        end: 结束期号（包含）

    Returns:
        {issues_downloaded, total_games_added, errors}
    """
    stats = {"issues_downloaded": 0, "total_games_added": 0, "errors": []}

    load_status()
    status = _status
    completed = set(status.get("completed_issues", []))

    for issue in range(start, end + 1):
        if issue in completed:
            print(f"  TWIC {issue}: 已处理，跳过")
            continue

        print(f"\n  TWIC {issue}: 下载中...")
        zf = download_twic_zip(issue)
        if not zf:
            stats["errors"].append(f"Issue {issue}: 下载失败")
            continue

        games = parse_twic_games(zf)
        print(f"    解析到 {len(games)} 盘大师对局")

        added = 0
        for game in games:
            if _add_game_to_db(db, game):
                added += 1

        stats["issues_downloaded"] += 1
        stats["total_games_added"] += added
        completed.add(issue)
        print(f"    新增 {added} 个局面索引")

        time.sleep(1)  # 温和限速

    status["completed_issues"] = list(sorted(completed))
    status["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    status["total_positions"] = len(db.index) if hasattr(db, 'index') else 0
    save_status()

    return stats


def _add_game_to_db(db, game) -> bool:
    """
    将一盘对局的前15步加入大师数据库索引。
    返回是否新增了任何局面。
    """
    board = game.board()
    white = game.headers.get("White", "?")
    black = game.headers.get("Black", "?")
    event = game.headers.get("Event", "?")
    date = game.headers.get("Date", "?")
    result = game.headers.get("Result", "*")

    added_any = False
    import hashlib

    for i, move in enumerate(game.mainline_moves()):
        if i >= 15:
            break
        fen = board.fen()
        fen_hash = hashlib.md5(fen.encode()).hexdigest()
        san = board.san(move)

        if not hasattr(db, 'index'):
            db.index = {}

        existing = db.index.get(fen_hash, [])
        found = False
        for entry in existing:
            if entry.get("san") == san:
                entry["count"] = entry.get("count", 1) + 1
                if white.lower() in ["carlsen", "nakamura"] or black.lower() in ["carlsen", "nakamura"]:
                    entry["famous_player"] = white if white.lower() in ["carlsen"] else black
                found = True
                added_any = True
                break

        if not found:
            db.index[fen_hash] = existing + [{
                "san": san,
                "uci": move.uci(),
                "count": 1,
                "famous_player": white if any(
                    p in white.lower() for p in ["carlsen", "nakamura", "caruana"]
                ) else "",
                "games": [{"white": white, "black": black, "event": event, "date": date, "result": result}],
            }]
            added_any = True

        board.push(move)

    return added_any


# ═══════════════════════════════════════════════════════════════
#  状态管理
# ═══════════════════════════════════════════════════════════════

_status = {"completed_issues": [], "last_update": "", "total_positions": 0}


def load_status():
    global _status
    if STATUS_FILE.exists():
        try:
            with STATUS_FILE.open("r", encoding="utf-8") as f:
                _status = json.load(f)
        except Exception:
            pass


def save_status():
    with STATUS_FILE.open("w", encoding="utf-8") as f:
        json.dump(_status, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse, json as _j
    parser = argparse.ArgumentParser(description="大师库动态更新")
    parser.add_argument("--from", dest="start", type=int, help="起始 TWIC 期号")
    parser.add_argument("--to", dest="end", type=int, help="结束 TWIC 期号")
    parser.add_argument("--auto", action="store_true", help="自动探测最新期号并增量更新")
    parser.add_argument("--stats", action="store_true", help="显示当前状态")
    parser.add_argument("--count", type=int, default=5, help="增量更新最近N期 (默认5)")
    args = parser.parse_args()

    if args.stats:
        load_status()
        print("大师库状态:")
        print(f"  上次更新: {_status.get('last_update', '从未')}")
        print(f"  已完成期号: {_status.get('completed_issues', [])}")
        print(f"  总局面数: {_status.get('total_positions', 0)}")
        if INDEX_FILE.exists():
            import os
            size_mb = os.path.getsize(INDEX_FILE) / 1024 / 1024
            print(f"  索引文件: {size_mb:.1f} MB")
        return

    # 懒加载 master_games_db
    try:
        from master_games_db import MasterGamesDB
        db = MasterGamesDB()
        db.load_index()
        print(f"大师库: {db.total_positions} 个局面, {db.total_games} 盘对局")
    except ImportError:
        print("✗ 找不到 master_games_db 模块")
        return

    if args.start and args.end:
        start, end = args.start, args.end
    elif args.auto:
        latest = find_latest_twic(DEFAULT_START_TWIC)
        start = max(DEFAULT_START_TWIC, latest - args.count + 1)
        end = latest
        print(f"自动范围: TWIC {start} ~ {end}")
    else:
        load_status()
        completed = _status.get("completed_issues", [])
        last = max(completed) if completed else DEFAULT_START_TWIC - 1
        start = last + 1
        latest = find_latest_twic(start)
        end = min(latest, start + args.count - 1)
        print(f"增量更新: TWIC {start} ~ {end}")

    stats = update_from_twic(db, start, end)
    db.total_positions = len(db.index) if hasattr(db, 'index') else 0
    if hasattr(db, 'save_index'):
        db.save_index()
    else:
        import pickle
        with INDEX_FILE.open("wb") as f:
            pickle.dump({
                "total_games": db.total_games,
                "total_positions": db.total_positions,
                "index": db.index if hasattr(db, 'index') else {},
            }, f)
        print(f"✓ 索引已保存: {INDEX_FILE}")

    print(f"\n完成: {stats['issues_downloaded']} 期, {stats['total_games_added']} 新索引")
    if stats["errors"]:
        print(f"错误: {stats['errors']}")


if __name__ == "__main__":
    main()