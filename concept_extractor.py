"""
战略概念提取器 — 纯 python-chess 启发式检测
对标 chess-sandbox 的概念层：王安全度、开放线、空间优势、子力机动性、兵形结构

用法:
    from concept_extractor import extract_concepts, generate_concept_summary
    profile = extract_concepts(board)
    summary = generate_concept_summary(profile)
"""

import sys
import chess
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

# 中心格子
CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}
EXTENDED_CENTER = {chess.C3, chess.C4, chess.C5, chess.C6,
                   chess.D3, chess.D4, chess.D5, chess.D6,
                   chess.E3, chess.E4, chess.E5, chess.E6,
                   chess.F3, chess.F4, chess.F5, chess.F6}

# 王翼格子（按颜色）
KINGSIDE_WHITE = {chess.F2, chess.G2, chess.H2, chess.F3, chess.G3, chess.H3}
KINGSIDE_BLACK = {chess.F7, chess.G7, chess.H7, chess.F6, chess.G6, chess.H6}
QUEENSIDE_WHITE = {chess.A2, chess.B2, chess.C2, chess.A3, chess.B3, chess.C3}
QUEENSIDE_BLACK = {chess.A7, chess.B7, chess.C7, chess.A6, chess.B6, chess.C6}


def _piece_name(piece: chess.Piece) -> str:
    """单字符棋子名"""
    names = {chess.KING: "王", chess.QUEEN: "后", chess.ROOK: "车",
             chess.BISHOP: "象", chess.KNIGHT: "马", chess.PAWN: "兵"}
    color = "白" if piece.color == chess.WHITE else "黑"
    return f"{color}{names.get(piece.piece_type, '?')}"


# ═══════════════════════════════════════════════════════════════
#  1. 王安全度 (King Safety)
# ═══════════════════════════════════════════════════════════════

def _king_safety(board: chess.Board) -> dict:
    """评估双方王的安全程度，返回 0-10 分数和描述"""
    result = {}
    for color, name in [(chess.WHITE, "白方"), (chess.BLACK, "黑方")]:
        king_sq = board.king(color)
        if king_sq is None:
            result[name] = {"score": 0, "issues": ["王已被吃掉"]}
            continue

        enemy = not color
        issues = []
        score = 10  # 满分

        # 1) 兵盾完整性
        pawn_shield = _count_pawn_shield(board, color, king_sq)
        missing = 3 - pawn_shield
        if missing >= 2:
            score -= missing * 3
            issues.append(f"兵盾严重破损（缺{missing}个护卫兵）")
        elif missing == 1:
            score -= 1
            issues.append(f"兵盾轻微破损")

        # 2) 王前开放线
        king_file = chess.square_file(king_sq)
        open_files_near_king = 0
        for df in [-1, 0, 1]:
            f = king_file + df
            if 0 <= f <= 7 and _is_open_file(board, f):
                open_files_near_king += 1
        if open_files_near_king >= 2:
            score -= 3
            issues.append(f"王前有{open_files_near_king}条开放线，极度危险")
        elif open_files_near_king == 1:
            score -= 1
            issues.append("王前有一条开放线")

        # 3) 敌方重子瞄准王翼
        king_zone = _king_zone(board, color)
        heavy_aiming = 0
        for sq in chess.SQUARES:
            piece = board.piece_at(sq)
            if piece and piece.color == enemy and piece.piece_type in (chess.QUEEN, chess.ROOK):
                attacks = board.attacks(sq)
                if attacks & king_zone:
                    heavy_aiming += 1
        if heavy_aiming >= 2:
            score -= 2
            issues.append(f"敌方{heavy_aiming}个重子瞄准王翼")

        # 4) 是否易位
        if not _has_castled(board, color):
            # 检查是否还有易位权
            has_rights = bool(board.castling_rights & (
                chess.BB_H1 if color == chess.WHITE else chess.BB_H8 |
                chess.BB_A1 if color == chess.WHITE else chess.BB_A8
            ))
            if not has_rights and not _has_castled(board, color):
                score -= 1
                issues.append("王未易位且失去易位权，位置暴露")

        result[name] = {
            "score": max(0, score),
            "issues": issues,
            "pawn_shield": pawn_shield,
            "open_files_near": open_files_near_king,
            "heavy_aiming": heavy_aiming,
        }
    return result


def _count_pawn_shield(board: chess.Board, color: chess.Color, king_sq: int) -> int:
    """计算王前兵盾数量（f/g/h 或 a/b/c 前方的兵）"""
    rank = chess.square_rank(king_sq)
    file = chess.square_file(king_sq)

    # 王在底线（0或7）= 已易位，检查前一排
    shield_squares = []
    target_rank = rank + (1 if color == chess.WHITE else -1)
    if 1 <= target_rank <= 6:
        for df in [-1, 0, 1]:
            f = file + df
            if 0 <= f <= 7:
                shield_squares.append(chess.square(f, target_rank))

    count = 0
    for sq in shield_squares:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type == chess.PAWN:
            count += 1
    return count


def _king_zone(board: chess.Board, color: chess.Color) -> set:
    """国王周围 3x3 格子"""
    king_sq = board.king(color)
    if king_sq is None:
        return set()
    zone = set()
    fr, rr = chess.square_file(king_sq), chess.square_rank(king_sq)
    for df in (-1, 0, 1):
        for dr in (-1, 0, 1):
            f, r = fr + df, rr + dr
            if 0 <= f < 8 and 0 <= r < 8:
                zone.add(chess.square(f, r))
    return zone


def _has_castled(board: chess.Board, color: chess.Color) -> bool:
    """王是否已经移动过（简易判断：王不在原位）"""
    home_sq = chess.E1 if color == chess.WHITE else chess.E8
    return board.king(color) != home_sq


# ═══════════════════════════════════════════════════════════════
#  2. 开放线 (Open Files)
# ═══════════════════════════════════════════════════════════════

def _is_open_file(board: chess.Board, file: int) -> bool:
    """检查某列是否完全无兵"""
    for rank in range(8):
        p = board.piece_at(chess.square(file, rank))
        if p and p.piece_type == chess.PAWN:
            return False
    return True


def _is_half_open_file(board: chess.Board, file: int, color: chess.Color) -> bool:
    """检查某列是否对 color 方半开放（对手有兵，己方无兵）"""
    enemy = not color
    has_enemy_pawn = False
    has_own_pawn = False
    for rank in range(8):
        p = board.piece_at(chess.square(file, rank))
        if p and p.piece_type == chess.PAWN:
            if p.color == enemy:
                has_enemy_pawn = True
            else:
                has_own_pawn = True
    return has_enemy_pawn and not has_own_pawn


def _open_files(board: chess.Board) -> dict:
    """分析每条线的开放状态及控制权"""
    files_status = {}
    for f in range(8):
        fname = chr(ord('a') + f)
        if _is_open_file(board, f):
            # 谁控制了这条开放线（有车/后在上面）
            white_control = _count_heavy_on_file(board, f, chess.WHITE)
            black_control = _count_heavy_on_file(board, f, chess.BLACK)
            controller = None
            if white_control > black_control:
                controller = "白方"
            elif black_control > white_control:
                controller = "黑方"
            files_status[fname] = {"type": "开放线", "controller": controller,
                                   "white_heavy": white_control, "black_heavy": black_control}
        elif _is_half_open_file(board, f, chess.WHITE):
            files_status[fname] = {"type": "白方半开放"}
        elif _is_half_open_file(board, f, chess.BLACK):
            files_status[fname] = {"type": "黑方半开放"}
        else:
            files_status[fname] = {"type": "封闭"}

    # 汇总
    open_count = sum(1 for v in files_status.values() if v["type"] == "开放线")
    white_half = sum(1 for v in files_status.values() if v["type"] == "白方半开放")
    black_half = sum(1 for v in files_status.values() if v["type"] == "黑方半开放")

    return {
        "files": files_status,
        "open_count": open_count,
        "white_half_open": white_half,
        "black_half_open": black_half,
    }


def _count_heavy_on_file(board: chess.Board, file: int, color: chess.Color) -> int:
    """某方在某条线上有多少重子（车/后）"""
    count = 0
    for rank in range(8):
        p = board.piece_at(chess.square(file, rank))
        if p and p.color == color and p.piece_type in (chess.ROOK, chess.QUEEN):
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════
#  3. 空间优势 (Space & Control)
# ═══════════════════════════════════════════════════════════════

def _space_advantage(board: chess.Board) -> dict:
    """评估双方的空间控制力"""
    white_center = 0
    black_center = 0
    white_extended = 0
    black_extended = 0

    for sq in chess.SQUARES:
        w_attackers = board.attackers(chess.WHITE, sq)
        b_attackers = board.attackers(chess.BLACK, sq)

        if sq in CENTER_SQUARES:
            white_center += len(w_attackers)
            black_center += len(b_attackers)
        if sq in EXTENDED_CENTER:
            white_extended += len(w_attackers)
            black_extended += len(b_attackers)

    # 兵在对方半场
    white_advanced = sum(1 for sq in chess.SQUARES
                         if chess.square_rank(sq) >= 5
                         and board.piece_at(sq)
                         and board.piece_at(sq).color == chess.WHITE
                         and board.piece_at(sq).piece_type == chess.PAWN)
    black_advanced = sum(1 for sq in chess.SQUARES
                         if chess.square_rank(sq) <= 2
                         and board.piece_at(sq)
                         and board.piece_at(sq).color == chess.BLACK
                         and board.piece_at(sq).piece_type == chess.PAWN)

    # 判断哪方有空间优势
    total_white = white_center + white_extended + white_advanced * 2
    total_black = black_center + black_extended + black_advanced * 2

    diff = total_white - total_black
    if diff > 8:
        advantage = "白方明显空间优势"
    elif diff > 3:
        advantage = "白方略有空间优势"
    elif diff < -8:
        advantage = "黑方明显空间优势"
    elif diff < -3:
        advantage = "黑方略有空间优势"
    else:
        advantage = "空间大致均衡"

    return {
        "advantage": advantage,
        "white_score": total_white,
        "black_score": total_black,
        "white_center": white_center,
        "black_center": black_center,
        "white_advanced_pawns": white_advanced,
        "black_advanced_pawns": black_advanced,
    }


# ═══════════════════════════════════════════════════════════════
#  4. 子力机动性 (Piece Mobility)
# ═══════════════════════════════════════════════════════════════

def _piece_mobility(board: chess.Board) -> dict:
    """评估双方各棋子的机动性"""
    white_legal = 0
    black_legal = 0

    # 使用 push/pop 方式统计（turn 顺序）
    board_copy = board.copy()
    board_copy.turn = chess.WHITE
    white_legal = len(list(board_copy.legal_moves))
    board_copy.turn = chess.BLACK
    black_legal = len(list(board_copy.legal_moves))

    # 找出"坏子"（活动范围极小的棋子）
    white_bad_pieces = []
    black_bad_pieces = []
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p:
            continue
        moves_from_sq = []
        for m in board.legal_moves:
            if m.from_square == sq:
                moves_from_sq.append(m)
        if len(moves_from_sq) <= 1 and p.piece_type != chess.KING:
            name = f"{_piece_name(p)}{chess.square_name(sq)}"
            if p.color == chess.WHITE:
                white_bad_pieces.append(name)
            else:
                black_bad_pieces.append(name)

    return {
        "white_legal_moves": white_legal,
        "black_legal_moves": black_legal,
        "white_bad_pieces": white_bad_pieces,
        "black_bad_pieces": black_bad_pieces,
    }


# ═══════════════════════════════════════════════════════════════
#  5. 兵形结构 (Pawn Structure)
# ═══════════════════════════════════════════════════════════════

def _pawn_structure(board: chess.Board) -> dict:
    """分析兵形：孤兵、叠兵、通路兵"""
    white_isolated = []
    black_isolated = []
    white_doubled = []
    black_doubled = []
    white_passed = []
    black_passed = []

    for f in range(8):
        white_pawns_on_file = []
        black_pawns_on_file = []
        for r in range(8):
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN:
                if p.color == chess.WHITE:
                    white_pawns_on_file.append(r)
                else:
                    black_pawns_on_file.append(r)

        # 叠兵
        if len(white_pawns_on_file) >= 2:
            white_doubled.append(chr(ord('a') + f))
        if len(black_pawns_on_file) >= 2:
            black_doubled.append(chr(ord('a') + f))

        # 孤兵（相邻两列无己方兵）
        for r in white_pawns_on_file:
            if not _has_friendly_pawn_on_adjacent(board, f, r, chess.WHITE):
                white_isolated.append(f"{chr(ord('a')+f)}{r+1}")
        for r in black_pawns_on_file:
            if not _has_friendly_pawn_on_adjacent(board, f, r, chess.BLACK):
                black_isolated.append(f"{chr(ord('a')+f)}{r+1}")

        # 通路兵（前方和相邻列无对方兵阻挡）
        for r in white_pawns_on_file:
            if _is_passed_pawn(board, f, r, chess.WHITE):
                white_passed.append(f"{chr(ord('a')+f)}{r+1}")
        for r in black_pawns_on_file:
            if _is_passed_pawn(board, f, r, chess.BLACK):
                black_passed.append(f"{chr(ord('a')+f)}{r+1}")

    return {
        "white_isolated": white_isolated,
        "black_isolated": black_isolated,
        "white_doubled": white_doubled,
        "black_doubled": black_doubled,
        "white_passed": white_passed,
        "black_passed": black_passed,
    }


def _has_friendly_pawn_on_adjacent(board: chess.Board, file: int, rank: int,
                                   color: chess.Color) -> bool:
    """检查相邻列是否有己方兵"""
    for df in (-1, 1):
        f = file + df
        if 0 <= f <= 7:
            for r in range(8):
                p = board.piece_at(chess.square(f, r))
                if p and p.piece_type == chess.PAWN and p.color == color:
                    return True
    return False


def _is_passed_pawn(board: chess.Board, file: int, rank: int,
                    color: chess.Color) -> bool:
    """检查某兵是否为通路兵"""
    enemy = not color
    direction = 1 if color == chess.WHITE else -1
    for df in (-1, 0, 1):
        f = file + df
        r = rank + direction
        while 0 <= f <= 7 and 0 <= r <= 7:
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN and p.color == enemy:
                return False
            r += direction
    return True


# ═══════════════════════════════════════════════════════════════
#  6. 子力对比 (Material Balance)
# ═══════════════════════════════════════════════════════════════

PIECE_VALUES = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
                chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0}


def _material_balance(board: chess.Board) -> dict:
    """计算双方子力对比"""
    white_material = 0
    black_material = 0
    white_pieces = defaultdict(int)
    black_pieces = defaultdict(int)

    piece_names = {chess.PAWN: "兵", chess.KNIGHT: "马", chess.BISHOP: "象",
                   chess.ROOK: "车", chess.QUEEN: "后"}

    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p:
            continue
        val = PIECE_VALUES[p.piece_type]
        name = piece_names.get(p.piece_type, "?")
        if p.color == chess.WHITE:
            white_material += val
            white_pieces[name] += 1
        else:
            black_material += val
            black_pieces[name] += 1

    diff = white_material - black_material
    if diff > 0:
        imbalance = f"白方多{diff}分（约{'、'.join(_diff_pieces(white_pieces, black_pieces))}）"
    elif diff < 0:
        imbalance = f"黑方多{abs(diff)}分（约{'、'.join(_diff_pieces(black_pieces, white_pieces))}）"
    else:
        imbalance = "子力均等"

    return {
        "white_material": white_material,
        "black_material": black_material,
        "difference": diff,
        "imbalance": imbalance,
    }


def _diff_pieces(more: dict, less: dict) -> list:
    """计算子力差异的具体项目"""
    parts = []
    all_types = ["后", "车", "象", "马", "兵"]
    for t in all_types:
        d = more.get(t, 0) - less.get(t, 0)
        if d > 0:
            parts.append(f"多{d}个{t}")
    return parts if parts else ["子力优势"]


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def extract_concepts(board: chess.Board) -> dict:
    """
    对单个局面提取所有战略概念。

    Returns:
        {
            "king_safety": {...},
            "open_files": {...},
            "space": {...},
            "mobility": {...},
            "pawns": {...},
            "material": {...},
            "summary": "一句话总结",
        }
    """
    return {
        "king_safety": _king_safety(board),
        "open_files": _open_files(board),
        "space": _space_advantage(board),
        "mobility": _piece_mobility(board),
        "pawns": _pawn_structure(board),
        "material": _material_balance(board),
    }


def generate_concept_summary(profile: dict) -> str:
    """将概念字典转为一段可嵌入 LLM 提示词的文本摘要"""
    parts = []

    # 1. 王安全
    ks = profile.get("king_safety", {})
    w_ks = ks.get("白方", {})
    b_ks = ks.get("黑方", {})
    if w_ks.get("score", 10) <= 5:
        parts.append(f"⚠ 白方王安全度仅{w_ks['score']}/10：{'；'.join(w_ks.get('issues', []))}")
    if b_ks.get("score", 10) <= 5:
        parts.append(f"⚠ 黑方王安全度仅{b_ks['score']}/10：{'；'.join(b_ks.get('issues', []))}")

    # 2. 开放线
    of = profile.get("open_files", {})
    if of.get("open_count", 0) > 0:
        controlled = [(k, v) for k, v in of.get("files", {}).items()
                      if v["type"] == "开放线" and v["controller"]]
        if controlled:
            c_str = "；".join(f"{v['controller']}控制{fn}线" for fn, v in controlled)
            parts.append(f"开放线：{of['open_count']}条（{c_str}）")

    # 3. 空间
    sp = profile.get("space", {})
    if sp.get("advantage", "") != "空间大致均衡":
        parts.append(sp["advantage"])

    # 4. 兵形
    ps = profile.get("pawns", {})
    issues = []
    if ps.get("white_isolated"):
        issues.append(f"白孤兵：{','.join(ps['white_isolated'])}")
    if ps.get("black_isolated"):
        issues.append(f"黑孤兵：{','.join(ps['black_isolated'])}")
    if ps.get("white_doubled"):
        issues.append(f"白叠兵在{','.join(ps['white_doubled'])}线")
    if ps.get("black_doubled"):
        issues.append(f"黑叠兵在{','.join(ps['black_doubled'])}线")
    if ps.get("white_passed"):
        issues.append(f"白通路兵：{','.join(ps['white_passed'])}（优势！）")
    if ps.get("black_passed"):
        issues.append(f"黑通路兵：{','.join(ps['black_passed'])}（优势！）")
    if issues:
        parts.append(f"兵形：{'；'.join(issues)}")

    # 5. 机动性
    mob = profile.get("mobility", {})
    w_mob = mob.get("white_legal_moves", 0)
    b_mob = mob.get("black_legal_moves", 0)
    if w_mob and b_mob:
        ratio = w_mob / max(b_mob, 1)
        if ratio > 1.4:
            parts.append(f"白方机动性明显占优（{w_mob} vs {b_mob}合法走法）")
        elif ratio < 0.7:
            parts.append(f"黑方机动性明显占优（{b_mob} vs {w_mob}合法走法）")

    # 6. 子力
    mat = profile.get("material", {})
    if mat.get("imbalance", "") != "子力均等":
        parts.append(mat["imbalance"])

    if not parts:
        return "局面大致均衡，无明显战略特征。"

    return "【局面战略特征】\n" + "\n".join(f"  • {p}" for p in parts)


def extract_turn_concepts(board: chess.Board) -> dict:
    """
    针对当前轮到走棋的一方，提取"该方视角"的关键概念。
    返回更精简的、适合嵌入单步提示词的特征字典。
    """
    turn = board.turn
    turn_name = "白方" if turn == chess.WHITE else "黑方"
    enemy_name = "黑方" if turn == chess.WHITE else "白方"

    profile = extract_concepts(board)

    # 提取该方最相关的 3-5 条特征
    key_points = []

    # 该方的王安全
    ks = profile["king_safety"].get(turn_name, {})
    if ks.get("score", 10) <= 6:
        key_points.append(f"{turn_name}王安全度低({ks['score']}/10)")

    # 空间
    sp = profile["space"]
    if turn == chess.WHITE and sp["advantage"].startswith("白方"):
        key_points.append(f"白方空间优势(+{sp['white_score'] - sp['black_score']})")
    elif turn == chess.BLACK and sp["advantage"].startswith("黑方"):
        key_points.append(f"黑方空间优势(+{sp['black_score'] - sp['white_score']})")

    # 兵形弱点
    ps = profile["pawns"]
    own_isolated = ps.get(f"{'white' if turn == chess.WHITE else 'black'}_isolated", [])
    if own_isolated:
        key_points.append(f"{turn_name}有孤兵：{','.join(own_isolated)}")
    own_passed = ps.get(f"{'white' if turn == chess.WHITE else 'black'}_passed", [])
    if own_passed:
        key_points.append(f"{turn_name}有通路兵：{','.join(own_passed)}")

    # 开放线
    of = profile["open_files"]
    own_half = of.get(f"{'white' if turn == chess.WHITE else 'black'}_half_open", 0)
    if own_half >= 2:
        key_points.append(f"{turn_name}有{own_half}条半开放线，利于进攻")

    return {
        "turn": turn_name,
        "key_points": key_points,
        "king_safety": ks.get("score", 10),
        "space_advantage": sp["advantage"],
    }


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("战略概念提取器 自测")
    print("=" * 60)

    # 测试开局局面
    board = chess.Board()
    print("\n--- 初始局面 ---")
    profile = extract_concepts(board)
    print(generate_concept_summary(profile))

    # 测试中局局面
    midgame_fen = "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 6 4"
    board2 = chess.Board(midgame_fen)
    print("\n--- 意大利开局中局 ---")
    profile2 = extract_concepts(board2)
    print(generate_concept_summary(profile2))

    # 测试残局
    endgame_fen = "4k3/8/8/8/8/8/4P3/4K3 w - - 0 1"
    board3 = chess.Board(endgame_fen)
    print("\n--- 王兵残局 ---")
    profile3 = extract_concepts(board3)
    print(generate_concept_summary(profile3))

    print("\n✅ 自测完成")
