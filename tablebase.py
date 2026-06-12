"""
残局库 (Syzygy Tablebase) 查询模块 v2
支持两种查询方式：
  1. 本地 Syzygy 文件(优先) — 通过 python-chess 内建 probing，毫秒级
  2. Lichess API(后备) — 在线查询，覆盖 <7 子局面

用法:
  from tablebase import SyzygyProber, get_prober
  prober = SyzygyProber()
  result = prober.probe(board)
"""

import sys, json, urllib.request, urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

TABLEBASE_PIECE_LIMIT = 7
SYZYGY_PATH = Path(__file__).parent / "syzygy"


# ==================== Syzygy 本地探测器 ====================

class SyzygyProber:
    """本地优先 + Lichess API 后备"""

    def __init__(self, local_path=None):
        self.local_path = local_path or SYZYGY_PATH
        self._tb = None
        self._local_ok = None
        self.local_n = 0
        self.api_n = 0

    def _init_local(self):
        if self._local_ok is not None:
            return self._local_ok
        if not self.local_path.exists():
            self._local_ok = False
            return False
        rtbw = list(self.local_path.glob("*.rtbw"))
        rtbz = list(self.local_path.glob("*.rtbz"))
        if not rtbw or not rtbz:
            self._local_ok = False
            return False
        try:
            import chess.syzygy
            self._tb = chess.syzygy.Tablebase()
            self._tb.open_directory(str(self.local_path))
            n = len(self._tb)
            self._local_ok = n > 0
            if self._local_ok:
                print(f"  本地 Syzygy 已加载: {n} 个表库 ({self.local_path})")
            return self._local_ok
        except Exception as e:
            print(f"  Syzygy 加载失败: {e}")
            self._local_ok = False
            return False

    def probe(self, board):
        """探测局面，返回 {category, wdl, dtz, dtm, source}"""
        # 本地优先
        if self._local_ok or self._local_ok is None:
            if self._init_local():
                try:
                    r = self._tb.probe_wdl(board)
                    self.local_n += 1
                    return self._parse_local(r, board)
                except Exception:
                    pass
        # API 后备
        r = query_tablebase(board)
        if r:
            self.api_n += 1
            r["source"] = "lichess_api"
        return r or {"category": "unknown", "wdl": None, "dtz": None, "dtm": None,
                      "source": "none"}

    def _parse_local(self, wdl, board):
        wdl_map = {-2: "loss", -1: "blessed_loss", 0: "draw", 1: "cursed_win", 2: "win"}
        dtz = dtm = None
        if self._tb:
            try:
                dtz = self._tb.probe_dtz(board)
                if hasattr(dtz, 'dtz'):
                    dtz = dtz.dtz
                dtm = self._tb.probe_dtm(board)
                if hasattr(dtm, 'dtm'):
                    dtm = dtm.dtm
            except Exception:
                pass
        return {
            "category": wdl_map.get(wdl, "unknown"), "wdl": wdl,
            "dtz": dtz, "dtm": dtm,
            "fen": board.fen(), "piece_count": count_pieces(board),
            "source": "local_syzygy",
        }

    def probe_moves(self, board):
        """探测所有合法走法，按 WDL 排序"""
        results = []
        for move in board.legal_moves:
            board.push(move)
            r = self.probe(board)
            board.pop()
            r["move"] = board.san(move)
            r["uci"] = move.uci()
            results.append(r)
        results.sort(key=lambda x: (x.get("wdl") or 0), reverse=True)
        return results


_prober = None


def get_prober(local_path=None):
    global _prober
    if _prober is None:
        _prober = SyzygyProber(local_path)
    return _prober


# ==================== 基础函数 ====================

def count_pieces(board):
    n = 0
    for sq in range(64):
        p = board.piece_at(sq)
        if p and p.piece_type != 6:
            n += 1
    if board.king(True): n += 1
    if board.king(False): n += 1
    return n


# 本地 API 结果缓存
_tb_cache = {}
_cache_file = Path(__file__).parent / "tablebase_cache.json"


def _load_cache():
    global _tb_cache
    if _cache_file.exists():
        try:
            with _cache_file.open("r", encoding="utf-8") as f:
                _tb_cache = json.load(f)
        except Exception:
            _tb_cache = {}
    return _tb_cache


def _save_cache():
    try:
        with _cache_file.open("w", encoding="utf-8") as f:
            json.dump(_tb_cache, f, ensure_ascii=False)
    except Exception:
        pass


def query_tablebase(board):
    if count_pieces(board) > TABLEBASE_PIECE_LIMIT:
        return None

    fen = board.fen()
    # 用 FEN 的简化 key（只取棋盘部分）做缓存
    cache_key = fen.split(" ")[0]

    # 检查缓存
    _load_cache()
    if cache_key in _tb_cache:
        cached = _tb_cache[cache_key]
        if cached and cached.get("category") != "unknown":
            return dict(cached)  # 返回副本

    url = f"https://tablebase.lichess.ovh/standard?fen={urllib.parse.quote(fen, safe='')}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "agentchess/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        data["fen"] = fen
        data["piece_count"] = count_pieces(board)
        # 缓存结果(仅当有效时)
        if data.get("category") and data["category"] != "unknown":
            _tb_cache[cache_key] = {k: v for k, v in data.items()
                                     if k not in ("moves", "topGames")}
            _save_cache()
        return data
    except Exception:
        return None


def format_tablebase_verdict(tb_data, side="白方"):
    if not tb_data:
        return ""
    cat = tb_data.get("category", "unknown")
    dtz = tb_data.get("dtz")
    dtm = tb_data.get("dtm")
    pc = tb_data.get("piece_count", 0)
    src = tb_data.get("source", "")

    v = {"win": f"{side}必胜", "loss": f"{side}已输", "draw": "必和局面",
         "blessed_loss": "理论必输(实战极难证明)", "cursed_win": "理论必胜(需>50步)",
         "unknown": ""}
    base = v.get(cat, "")

    if dtm and dtm > 0:
        base += f"，距离将死约 {(dtm+1)//2} 步"
    elif dtz and cat == "win" and dtz > 0:
        base += f"，约 {(abs(dtz)+1)//2} 步完成转换"

    if tb_data.get("insufficient_material"):
        base = "子力不足，理论必和"
    if tb_data.get("stalemate"):
        base = "无子可动！逼和。"

    note = _edu_note(cat, pc, dtz, dtm, src)
    if note:
        base += "。" + note
    return base


def _edu_note(cat, pc, dtz, dtm, src):
    if cat == "win" and dtz and dtz > 20:
        return "虽然必胜但着法需极高精度，建议学习此类残局的基本胜法"
    if cat == "win" and dtz and dtz <= 5:
        return "转换在即——下一步即可吃子或升变进入更简单的必胜残局"
    if cat == "draw" and pc <= 5:
        return "兵残局的和棋往往依赖于精确防守——对王、正方形法则和三角移动是核心技巧"
    if cat == "loss":
        return "唯一机会是制造复杂陷阱让对方犯错"
    if src == "local_syzygy":
        return "此判决来自本地 Syzygy 残局库，理论绝对精确"
    return ""


def get_endgame_knowledge(board):
    if count_pieces(board) > 12:
        return ""
    ps = board.fen().split(" ")[0]
    hasQ = "Q" in ps or "q" in ps
    rooks = ps.count("R") + ps.count("r")
    tips = []
    if not hasQ and rooks == 0 and count_pieces(board) <= 6:
        tips.append("【兵/轻子残局】注意对王、关键格、三角移动。卡帕布兰卡：'掌握了兵残局就掌握了国际象棋。'")
    if rooks >= 2 and not hasQ:
        tips.append("【车残局】车在通路兵后方最佳；卢塞纳(胜)和菲利多尔(守)是基石。")
    if hasQ and count_pieces(board) <= 7:
        tips.append("【后残局】王的安全第一——暴露的王可能被无限长将。通路兵价值最大化。")
    if "P" not in ps and "p" not in ps:
        tips.append("【无兵残局】必须直接杀王，注意避免逼和。")
    if count_pieces(board) <= 5:
        tips.append("【理论残局】已在 Syzygy 覆盖范围内。")
    return " ".join(tips) if tips else ""


# ===================== 自测 =====================

def main():
    import chess
    print("=" * 50)
    print("Syzygy Tablebase 测试")
    print("=" * 50)

    prober = SyzygyProber()
    print(f"本地可用: {prober._local_ok}")

    # 测试 K+P vs K
    board = chess.Board("8/8/8/8/5k2/8/4P3/6K1 w - - 0 1")
    r = prober.probe(board)
    print(f"K+P vs K: {format_tablebase_verdict(r, '白方')}")
    if prober._local_ok:
        moves = prober.probe_moves(board)
        print(f"  最佳走法: {moves[0]['move']} (WDL={moves[0].get('wdl')})")

    print(f"\n统计: 本地{prober.local_n}次, API{prober.api_n}次")
    print("OK")


if __name__ == "__main__":
    main()
