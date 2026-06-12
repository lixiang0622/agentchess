"""
大师对局数据库 (Master Games Database)
基于 FEN 哈希表的快速查找，支持：
  1. 本地 PGN 文件索引（KingBase / Caissabase 等）
  2. Lichess Masters API 在线后备
  3. 离线缓存（Pickle 持久化）
  4. 偏离大师主流检测

用法:
    from master_games_db import MasterGamesDB
    db = MasterGamesDB()
    db.build_index("path/to/kingbase/*.pgn", max_moves=15)  # 首次构建
    result = db.query(board.fen())
"""

import sys
import json
import hashlib
import time
import pickle
from pathlib import Path
from collections import defaultdict
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

try:
    import chess
    import chess.pgn
except ImportError:
    print("❌ 需要 python-chess: pip install python-chess")
    sys.exit(1)

# ─── 常量 ───
MAX_MOVES_TO_INDEX = 15        # 只索引前 15 步
INDEX_FILE = Path(__file__).parent / "master_games_index.pkl"
CACHE_FILE = Path(__file__).parent / "master_games_cache.json"
MIN_PLAYER_ELO = 2600          # 大师最低等级分

# 知名棋手列表（用于筛选"著名"示例）
FAMOUS_PLAYERS = {
    "carlsen", "nakamura", "caruana", "ding", "liren", "nepomniachtchi",
    "firouzja", "so", "wesley", "giri", "anand", "kasparov", "karpov",
    "fischer", "tal", "capablanca", "alekhine", "botvinnik", "petrosian",
    "spassky", "kramnik", "topalov", "aronian", "mamedyarov", "grischuk",
    "radjabov", "karjakin", "mvl", "vachier-lagrave", " Rapport",
    "羂?羂?", "卡尔森", "中村光",
    "肖特", "华莱斯", "马格努斯",
}


class MasterGamesDB:
    """大师对局数据库 — 本地 PGN 索引 + Lichess Masters API 后备"""

    def __init__(self, index_path: Path = None, use_api_fallback: bool = True):
        self.index_path = index_path or INDEX_FILE
        self.use_api_fallback = use_api_fallback
        self.index: dict = {}       # { fen_md5: [move_entries] }
        self.total_games = 0
        self.total_positions = 0
        self._loaded = False
        self.last_api_time = 0
        self.api_cache: dict = {}

    # ══════════════════════════════════════════════════════
    #  索引构建
    # ══════════════════════════════════════════════════════

    def build_index(self, pgn_paths: list = None, max_moves: int = None) -> int:
        """
        从 PGN 文件构建大师对局索引。

        Args:
            pgn_paths: PGN 文件路径列表或 glob 模式
            max_moves: 每个对局索引前 N 步（默认 MAX_MOVES_TO_INDEX）

        Returns:
            int: 索引的局面数
        """
        if max_moves is None:
            max_moves = MAX_MOVES_TO_INDEX

        self.index = defaultdict(list)
        self.total_games = 0
        self.total_positions = 0

        if pgn_paths is None:
            # 自动搜索项目目录下的 PGN 文件
            project_dir = Path(__file__).parent
            pgn_paths = list(project_dir.glob("*.pgn"))
            # 过滤掉 lichess_pgn（实战对局，不是大师库）
            pgn_paths = [p for p in pgn_paths if "lichess_pgn" not in p.name]

        if not pgn_paths:
            print("  ℹ 无本地大师 PGN 文件，将仅使用 Lichess API 后备")
            return 0

        print(f"  正在构建大师对局索引（最多 {max_moves} 步/局）...")
        games_read = 0

        for pgn_path in pgn_paths:
            pgn_path = Path(pgn_path)
            if not pgn_path.exists():
                print(f"  ⚠ 文件不存在: {pgn_path}")
                continue

            try:
                with pgn_path.open("r", encoding="utf-8", errors="replace") as f:
                    while True:
                        game = chess.pgn.read_game(f)
                        if game is None:
                            break

                        # 筛选大师对局
                        headers = game.headers
                        try:
                            w_elo = int(headers.get("WhiteElo", "0"))
                            b_elo = int(headers.get("BlackElo", "0"))
                        except ValueError:
                            w_elo = b_elo = 0

                        if w_elo < MIN_PLAYER_ELO and b_elo < MIN_PLAYER_ELO:
                            continue

                        # 遍历前 N 步
                        board = game.board()
                        white = headers.get("White", "?")
                        black = headers.get("Black", "?")
                        event = headers.get("Event", "?")
                        date = headers.get("Date", "?")
                        result = headers.get("Result", "*")

                        for i, move in enumerate(game.mainline_moves()):
                            if i >= max_moves:
                                break
                            fen = board.fen()
                            fen_hash = hashlib.md5(fen.encode()).hexdigest()
                            san = board.san(move)

                            # 检查是否已有此记录
                            existing = self.index.get(fen_hash, [])
                            found = False
                            for entry in existing:
                                if entry["san"] == san:
                                    entry["count"] = entry.get("count", 1) + 1
                                    entry["games"].append({
                                        "white": white, "black": black,
                                        "event": event, "date": date, "result": result,
                                    })
                                    found = True
                                    break
                            if not found:
                                self.index[fen_hash].append({
                                    "san": san,
                                    "uci": move.uci(),
                                    "count": 1,
                                    "white_win": 1 if result == "1-0" else 0,
                                    "draw": 1 if result == "1/2-1/2" else 0,
                                    "black_win": 1 if result == "0-1" else 0,
                                    "games": [{
                                        "white": white, "black": black,
                                        "event": event, "date": date, "result": result,
                                    }],
                                    "famous_player": white if any(
                                        fp in white.lower() for fp in FAMOUS_PLAYERS
                                    ) else (black if any(
                                        fp in black.lower() for fp in FAMOUS_PLAYERS
                                    ) else ""),
                                })

                            board.push(move)

                        games_read += 1
                        if games_read % 1000 == 0:
                            print(f"    已处理 {games_read} 盘对局...")

            except Exception as e:
                print(f"  ⚠ 读取 {pgn_path} 时出错: {e}")
                continue

        self.total_games = games_read
        self.total_positions = len(self.index)
        print(f"  ✓ 索引完成: {games_read} 盘对局, {self.total_positions} 个独立局面")
        return self.total_positions

    def save_index(self):
        """保存索引到文件"""
        data = {
            "total_games": self.total_games,
            "total_positions": self.total_positions,
            "index": dict(self.index),
        }
        with self.index_path.open("wb") as f:
            pickle.dump(data, f, protocol=pickle.HIGHEST_PROTOCOL)
        print(f"  ✓ 索引已保存: {self.index_path} "
              f"({self.index_path.stat().st_size / 1024 / 1024:.1f} MB)")

    def load_index(self) -> bool:
        """从文件加载索引"""
        if self._loaded:
            return True
        if not self.index_path.exists():
            return False
        try:
            with self.index_path.open("rb") as f:
                data = pickle.load(f)
            self.index = data.get("index", {})
            self.total_games = data.get("total_games", 0)
            self.total_positions = data.get("total_positions", 0)
            self._loaded = True
            print(f"  ✓ 大师对局索引已加载: {self.total_positions} 个局面, "
                  f"{self.total_games} 盘对局")
            return True
        except Exception as e:
            print(f"  ⚠ 加载索引失败: {e}")
            return False

    # ══════════════════════════════════════════════════════
    #  查询接口
    # ══════════════════════════════════════════════════════

    def query(self, fen: str) -> dict:
        """
        查询某个局面的大师走法统计。

        Returns:
            {
                "found": bool,
                "source": "local" | "lichess_masters" | "none",
                "total_games": int,
                "top_moves": [{san, count, pct, white_win_pct, draw_pct, black_win_pct}, ...],
                "famous_example": {player, move, event, year} or None,
                "actual_move_info": {san, pct, rank} or None,
                "deviation": bool,  # 实战走法频率 < 10% 为偏离
            }
        """
        fen_hash = hashlib.md5(fen.encode()).hexdigest()

        # 1) 先查本地索引
        if self.index and fen_hash in self.index:
            return self._build_result(fen, self.index[fen_hash], "local")

        # 2) API 后备
        if self.use_api_fallback:
            api_result = self._query_lichess_masters(fen)
            if api_result:
                return api_result

        # 3) 未找到
        return {"found": False, "source": "none", "total_games": 0,
                "top_moves": [], "famous_example": None, "deviation": False}

    def query_san(self, fen: str, move_san: str) -> dict:
        """查询某个具体走法在大师库中的统计数据"""
        result = self.query(fen)
        for m in result.get("top_moves", []):
            if m["san"] == move_san:
                result["actual_move_info"] = m
                result["deviation"] = m.get("pct", 0) < 10
                return result
        result["actual_move_info"] = None
        result["deviation"] = True  # 不在大师库中 = 偏离
        return result

    def get_top_moves(self, fen: str, top_n: int = 3) -> list:
        """获取最常见走法列表（简化）"""
        result = self.query(fen)
        return result.get("top_moves", [])[:top_n]

    def get_famous_example(self, fen: str) -> dict:
        """获取该局面最著名的棋手示例"""
        result = self.query(fen)
        return result.get("famous_example")

    # ══════════════════════════════════════════════════════
    #  内部方法
    # ══════════════════════════════════════════════════════

    def _build_result(self, fen: str, entries: list, source: str) -> dict:
        """从本地索引条目构建查询结果"""
        total = sum(e.get("count", 1) for e in entries)

        # 按出现次数排序
        sorted_entries = sorted(entries, key=lambda e: e.get("count", 0), reverse=True)

        top_moves = []
        for e in sorted_entries[:5]:
            c = e.get("count", 1)
            ww = e.get("white_win", 0)
            dd = e.get("draw", 0)
            bw = e.get("black_win", 0)
            total_games_for_move = ww + dd + bw or c
            top_moves.append({
                "san": e["san"],
                "uci": e.get("uci", ""),
                "count": c,
                "pct": round(c / total * 100, 1) if total else 0,
                "white_win_pct": round(ww / total_games_for_move * 100, 1),
                "draw_pct": round(dd / total_games_for_move * 100, 1),
                "black_win_pct": round(bw / total_games_for_move * 100, 1),
            })

        # 找著名棋手示例
        famous = None
        for e in sorted_entries:
            fp = e.get("famous_player", "")
            games = e.get("games", [])
            if fp and games:
                famous = {
                    "player": fp,
                    "move": e["san"],
                    "event": games[0].get("event", ""),
                    "year": games[0].get("date", "")[:4] if games[0].get("date") else "",
                }
                break
        if not famous and sorted_entries and sorted_entries[0].get("games"):
            g = sorted_entries[0]["games"][0]
            famous = {
                "player": g.get("white", "?"),
                "move": sorted_entries[0]["san"],
                "event": g.get("event", ""),
                "year": g.get("date", "")[:4] if g.get("date") else "",
            }

        return {
            "found": True,
            "source": source,
            "total_games": total,
            "top_moves": top_moves,
            "famous_example": famous,
            "deviation": False,
        }

    def _query_lichess_masters(self, fen: str) -> dict:
        """查询 Lichess Masters Database API"""
        # 检查缓存
        if fen in self.api_cache:
            return self.api_cache[fen]

        # 限速
        elapsed = time.time() - self.last_api_time
        if elapsed < 0.5:
            time.sleep(0.5 - elapsed)

        try:
            import urllib.request
            import urllib.parse

            url = (
                "https://explorer.lichess.ovh/masters"
                f"?fen={urllib.parse.quote(fen, safe='')}&topGames=3"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "AgentChess/2.0"})
            self.last_api_time = time.time()

            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            moves = data.get("moves", [])
            total = data.get("white", 0) + data.get("draws", 0) + data.get("black", 0)
            if total == 0:
                self.api_cache[fen] = None
                return None

            top_moves = []
            for m in sorted(moves, key=lambda x: x.get("white", 0) +
                            x.get("draws", 0) + x.get("black", 0), reverse=True)[:5]:
                w = m.get("white", 0)
                d = m.get("draws", 0)
                b = m.get("black", 0)
                mt = w + d + b
                top_moves.append({
                    "san": m.get("san", "?"),
                    "uci": m.get("uci", ""),
                    "count": mt,
                    "pct": round(mt / total * 100, 1),
                    "white_win_pct": round(w / mt * 100, 1) if mt > 0 else 0,
                    "draw_pct": round(d / mt * 100, 1) if mt > 0 else 0,
                    "black_win_pct": round(b / mt * 100, 1) if mt > 0 else 0,
                })

            # 找著名对局
            top_games = data.get("topGames", [])
            famous = None
            if top_games:
                g = top_games[0]
                famous = {
                    "player": f"{g.get('white', {}).get('name', '?')} vs {g.get('black', {}).get('name', '?')}",
                    "move": top_moves[0]["san"] if top_moves else "",
                    "event": g.get("event", ""),
                    "year": str(g.get("year", "")),
                }

            result = {
                "found": True,
                "source": "lichess_masters",
                "total_games": total,
                "top_moves": top_moves,
                "famous_example": famous,
                "deviation": False,
            }
            self.api_cache[fen] = result
            return result

        except Exception as e:
            self.api_cache[fen] = None
            return None


# ═══════════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════════

_db_instance = None


def get_master_db() -> MasterGamesDB:
    """获取全局单例"""
    global _db_instance
    if _db_instance is None:
        _db_instance = MasterGamesDB()
        _db_instance.load_index()
    return _db_instance


def query_master_moves(fen: str, move_san: str = None) -> dict:
    """快速查询"""
    db = get_master_db()
    if move_san:
        return db.query_san(fen, move_san)
    return db.query(fen)


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("大师对局数据库 自测")
    print("=" * 60)

    # 测试 1: 初始化
    print("\n--- 测试 1: 初始化 ---")
    db = MasterGamesDB()
    loaded = db.load_index()
    print(f"  索引已加载: {loaded}")
    print(f"  总局面数: {db.total_positions}")
    print(f"  总对局数: {db.total_games}")

    # 测试 2: 本地查询（如果有索引）
    if loaded:
        print("\n--- 测试 2: 本地查询 ---")
        board = chess.Board()
        moves = ["e4", "e5", "Nf3", "Nc6", "Bb5"]
        for san in moves:
            board.push_san(san)
        result = db.query(board.fen())
        print(f"  局面: {board.fen()[:60]}...")
        print(f"  找到: {result['found']}")
        print(f"  来源: {result['source']}")
        if result["top_moves"]:
            print(f"  最佳走法:")
            for tm in result["top_moves"][:3]:
                print(f"    {tm['san']}: {tm['pct']}% (白胜{tm['white_win_pct']}%)")
        if result.get("famous_example"):
            fe = result["famous_example"]
            print(f"  著名示例: {fe['player']} 走了 {fe['move']} ({fe.get('event', '')} {fe.get('year', '')})")

    # 测试 3: Lichess Masters API 后备
    print("\n--- 测试 3: Lichess Masters API ---")
    board = chess.Board()
    board.push_san("e4")
    board.push_san("c5")

    result = db.query(board.fen())
    print(f"  局面: 西西里防御, 第 2 步后")
    print(f"  找到: {result['found']}")
    print(f"  来源: {result['source']}")
    if result["top_moves"]:
        print(f"  最佳走法:")
        for tm in result["top_moves"][:3]:
            print(f"    {tm['san']}: {tm['pct']}% (白胜 {tm['white_win_pct']}%)")

    # 测试 4: 偏离检测
    print("\n--- 测试 4: 偏离检测 ---")
    board = chess.Board()
    board.push_san("e4")
    board.push_san("e5")
    board.push_san("Nf3")
    board.push_san("Nc6")
    board.push_san("Bb5")
    board.push_san("a6")
    board.push_san("Ba4")
    board.push_san("Nf6")
    # 西班牙开局主变
    result = db.query_san(board.fen(), "O-O")
    print(f"  FEN: {board.fen()[:50]}...")
    print(f"  来源: {result['source']}")
    if result.get("actual_move_info"):
        info = result["actual_move_info"]
        print(f"  O-O 走法频率: {info['pct']}%")
        print(f"  偏离主流: {result['deviation']}")
    if result["top_moves"]:
        print(f"  最佳走法: {result['top_moves'][0]['san']} ({result['top_moves'][0]['pct']}%)")

    print(f"\n✅ 自测完成")