"""
开局数据库深度整合
接入 Lichess Opening Explorer API + 本地 ECO 后备表
提供走法统计、流行度标签、陷阱线识别、开局名称查询

用法:
    from opening_explorer import OpeningExplorer
    explorer = OpeningExplorer()
    profile = explorer.build_opening_profile(board_seq, moves_san)
"""

import sys
import json
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


class OpeningExplorer:
    """开局数据库查询器 — Lichess API + 本地缓存 + ECO 后备"""

    def __init__(self, cache_path: Path = None):
        self.cache_path = cache_path or Path(__file__).parent / "opening_cache.json"
        self.cache = self._load_cache()
        self.last_request_time = 0
        # 加载大师统计
        self.master_stats = self._load_master_stats()

    # ==================== 缓存 ====================
    def _load_cache(self) -> dict:
        if self.cache_path.exists():
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _load_master_stats(self) -> dict:
        """加载大师对局统计"""
        stats_path = Path(__file__).parent / "opening_stats.json"
        if stats_path.exists():
            try:
                with open(stats_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save_cache(self):
        try:
            with open(self.cache_path, "w", encoding="utf-8") as f:
                json.dump(self.cache, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ==================== Lichess API ====================
    def explore(self, fen: str, speed: str = "blitz") -> dict:
        """
        查询 Lichess Opening Explorer API。带缓存和限速。

        Args:
            fen: 棋盘 FEN
            speed: 游戏速度 (bullet, blitz, rapid, classical, all)

        Returns:
            dict: 解析后的开局数据，失败返回空 dict
        """
        cache_key = f"{fen}|{speed}"
        if cache_key in self.cache:
            return self.cache[cache_key]

        # 限速：至少间隔 1 秒
        elapsed = time.time() - self.last_request_time
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)

        try:
            import requests
        except ImportError:
            # 没有 requests 库，回退到本地 ECO
            result = self._local_eco_lookup(fen)
            self.cache[cache_key] = result
            self._save_cache()
            return result

        try:
            self.last_request_time = time.time()
            resp = requests.post(
                "https://explorer.lichess.ovh/lichess",
                json={"fen": fen, "speed": speed, "variant": "standard"},
                headers={"User-Agent": "AgentChess-Commentary/1.0"},
                timeout=5
            )
            if resp.status_code == 200:
                result = self._parse_response(resp.json())
                self.cache[cache_key] = result
                self._save_cache()
                return result
        except Exception:
            pass

        # API 失败，用本地后备
        result = self._local_eco_lookup(fen)
        self.cache[cache_key] = result
        self._save_cache()
        return result

    def _parse_response(self, data: dict) -> dict:
        """解析 Lichess API 响应"""
        opening = data.get("opening", {})
        moves_data = data.get("moves", [])
        total = data.get("white", 0) + data.get("draws", 0) + data.get("black", 0)

        candidates = []
        for m in moves_data:
            white = m.get("white", 0)
            draws = m.get("draws", 0)
            black = m.get("black", 0)
            move_total = white + draws + black
            pct = (move_total / total * 100) if total > 0 else 0

            # 胜率
            wr = (white / move_total * 100) if move_total > 0 else 0

            candidates.append({
                "san": m.get("san", "?"),
                "uci": m.get("uci", ""),
                "total": move_total,
                "percentage": round(pct, 1),
                "white_win_pct": round(wr, 1),
                "draw_pct": round(draws / move_total * 100, 1) if move_total > 0 else 0,
                "black_win_pct": round(black / move_total * 100, 1) if move_total > 0 else 0,
            })

        # 排序：按走法数量降序
        candidates.sort(key=lambda c: c["total"], reverse=True)

        return {
            "source": "lichess",
            "opening_name": opening.get("name", ""),
            "eco": opening.get("eco", ""),
            "total_games": total,
            "white_win_pct": round(data.get("white", 0), 1),
            "draw_pct": round(data.get("draws", 0), 1),
            "black_win_pct": round(data.get("black", 0) / 1 if total > 0 else 0, 1),
            "candidates": candidates,
        }

    # ==================== 本地 ECO 后备表 ====================
    def _local_eco_lookup(self, fen: str) -> dict:
        """基于 FEN 模式的本地开局名称查找。
        排除初始局面（A00），优先匹配更长的模式（更具体的开局）。
        """
        # 排除初始局面
        if fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w"):
            return {"source": "local_eco", "opening_name": "初始局面", "eco": "",
                    "total_games": 0, "candidates": []}

        # 从后往前遍历（后面的条目更具体）
        matches = []
        for eco_code, name_zh, fen_pattern in MINI_ECO_TABLE:
            if fen_pattern in fen:
                matches.append((len(fen_pattern), eco_code, name_zh))

        # 选最长匹配
        if matches:
            matches.sort(key=lambda m: m[0], reverse=True)
            _, eco_code, name_zh = matches[0]
            return {
                "source": "local_eco",
                "opening_name": f"{name_zh} ({eco_code})",
                "eco": eco_code,
                "total_games": 0,
                "candidates": [],
            }

        return {"source": "local_eco", "opening_name": "", "eco": "",
                "total_games": 0, "candidates": []}

    # ==================== 开局概要构建 ====================
    def build_opening_profile(self, board_seq: list, moves_san: list,
                               top_n: int = 12) -> dict:
        """
        遍历前 N 步，为每步贴上流行度标签，构建开局概要。

        Args:
            board_seq: 走棋前的板面列表（用于查询开局数据）
            moves_san: 对应的走法 SAN 列表
            top_n: 分析前 N 步

        Returns:
            dict: {opening_name, eco, total_games, move_stats[], summary}
        """
        n = min(top_n, len(board_seq), len(moves_san))
        print(f"  查询开局数据库 (前 {n} 步)...")

        move_stats = []
        opening_name = ""
        eco = ""
        total_games = 0

        for i in range(n):
            fen = board_seq[i].fen()
            result = self.explore(fen)

            # 取最深（最后）一个有名称的开局，而非第一步
            if result.get("opening_name") and result["opening_name"] not in ("", "初始局面", "不规则开局", "王前兵开局"):
                opening_name = result["opening_name"]
                eco = result.get("eco", "")
                total_games = result.get("total_games", 0)

            # 找到当前走法在候选中的位置
            san = moves_san[i]
            candidates = result.get("candidates", [])
            tag = "unknown"
            pct = 0
            wr = 0

            for c in candidates:
                if c["san"] == san:
                    pct = c["percentage"]
                    wr = c["white_win_pct"]

                    # 流行度标签
                    if pct >= 60:
                        tag = "most_popular"
                    elif pct >= 30:
                        tag = "popular"
                    elif pct >= 5:
                        tag = "sideline"
                    else:
                        tag = "rare"

                    # 陷阱线判定（对走棋方不利的高胜率+低概率）
                    # 从走棋方视角：如果是黑方走棋且白方胜率>55%且走法概率<15%
                    is_black_move = (i % 2 == 1)
                    if is_black_move and wr > 55 and pct < 15:
                        tag = "trap_line"
                    elif not is_black_move and (100 - wr) > 55 and pct < 15:
                        tag = "trap_line"

                    break

            # 如果走法不在候选列表中（极少见）
            if tag == "unknown" and result.get("source") == "lichess":
                tag = "rare"

            move_stats.append({
                "move_num": i + 1,
                "san": san,
                "popularity_tag": tag,
                "percentage": round(pct, 1),
                "white_win_pct": round(wr, 1),
                "candidate_count": len(candidates),
                "top_candidates": [
                    {"san": c["san"], "pct": c["percentage"]}
                    for c in candidates[:5]
                ],
            })

        # 构建摘要
        summary = self._build_summary(opening_name, eco, move_stats, total_games)

        # 查找大师统计
        master_stats = None
        if eco and eco in self.master_stats:
            ms = self.master_stats[eco]
            if ms.get("total", 0) > 0:
                master_stats = ms

        return {
            "opening_name": opening_name,
            "eco": eco,
            "total_games": total_games,
            "move_stats": move_stats,
            "master_stats": master_stats,
            "summary": summary,
        }

    def _build_summary(self, opening_name: str, eco: str,
                        move_stats: list, total_games: int) -> str:
        """构建中文开局摘要"""
        parts = []

        if opening_name:
            parts.append(f"开局: {opening_name} ({eco})")

        if total_games > 0:
            parts.append(f"数据库: {total_games:,} 盘对局")

        # 走法路线概览
        if move_stats:
            line = " → ".join(m["san"] for m in move_stats[:10])
            if len(move_stats) > 10:
                line += " ..."
            parts.append(f"主线: {line}")

        # 特殊标注
        traps = [m for m in move_stats if m["popularity_tag"] == "trap_line"]
        if traps:
            names = [f"第{t['move_num']}步 {t['san']}" for t in traps]
            parts.append(f"⚠ 陷阱: {', '.join(names)}")

        return "\n".join(parts)


# ==================== 本地 ECO 表（从 JSON 加载）====================
def _load_eco_table():
    """从 eco_table.json 加载开局表，失败则用内置最小表"""
    eco_path = Path(__file__).parent / "eco_table.json"
    if eco_path.exists():
        try:
            with open(eco_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    # 内置最小后备表
    return [
        ["A00", "不规则开局", "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w"],
        ["B00", "王前兵开局", "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b"],
        ["B20", "西西里防御", "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w"],
        ["C00", "法兰西防御", "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w"],
        ["C50", "意大利开局", "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b"],
        ["C60", "西班牙开局", "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b"],
        ["C77", "西班牙-莫菲防御", "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w"],
        ["C88", "西班牙-封闭变例", "r1bq1rk1/2ppbppp/p1n2n2/1p2p3/4P3/1B3N2/PPPP1PPP/RNBQR1K1 w"],
        ["D00", "后翼弃兵", "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b"],
        ["E00", "印度防御", "rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR w"],
        ["E20", "尼姆佐维奇防御", "rnbqk2r/pppp1ppp/4pn2/8/1bPP4/2N5/PP2PPPP/R1BQKBNR w"],
    ]

MINI_ECO_TABLE = _load_eco_table()



# ===================== 自测 =====================

if __name__ == "__main__":
    import chess

    print("=" * 60)
    print("开局数据库自测")
    print("=" * 60)

    explorer = OpeningExplorer()
    board = chess.Board()

    # 模拟 e4 e5 Nf3 Nc6 Bc4 的序列
    moves = ["e4", "e5", "Nf3", "Nc6", "Bc4"]
    boards = []

    print("\n推演: 意大利开局")
    for i, san in enumerate(moves):
        boards.append(board.copy())
        board.push_san(san)
        print(f"  第{i+1}步 {san:6s} -> FEN片段: {boards[-1].fen()[:50]}...")

    profile = explorer.build_opening_profile(boards, moves)
    print(f"\n开局概要:")
    print(f"  名称: {profile['opening_name']}")
    print(f"  ECO: {profile['eco']}")
    print(f"  总局数: {profile['total_games']}")
    print(f"  摘要:\n{profile['summary']}")
    print(f"  走法统计:")
    for ms in profile["move_stats"]:
        tag_map = {
            "most_popular": "⭐最流行",
            "popular": "✓流行",
            "sideline": "旁线",
            "rare": "稀有",
            "trap_line": "⚠陷阱",
            "unknown": "?",
        }
        print(f"    第{ms['move_num']}步 {ms['san']:6s} → {tag_map.get(ms['popularity_tag'], ms['popularity_tag'])} ({ms['percentage']:.1f}%)")

    # 测试本地 ECO 查找
    print(f"\n本地 ECO 查找测试:")
    for label, fen in [
        ("意大利开局", boards[4].fen()),
        ("后翼弃兵", "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 1"),
    ]:
        result = explorer._local_eco_lookup(fen)
        print(f"  {label}: {result.get('opening_name', '未找到')}")

    print(f"\n✅ 自测完成")