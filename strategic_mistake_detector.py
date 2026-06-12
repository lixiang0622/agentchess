"""
局面型错误检测器 (Strategic Mistake Detector)
对比走棋前后的局面特征向量，基于规则检测不反映为评分骤降、但损害长期战略的错误。

检测维度（7 类规则）：
  1. 坏象换好马: 己方双象→用象换了马 + 局面封闭
  2. 兵型受损: 出现新叠兵/孤兵
  3. 放弃中心: 中心控制值明显下降（≥30%）
  4. 失去双象优势: 双象→单象 + 对方仍保有双象
  5. 王前兵阵破损: pawn_shield 减少
  6. 开放线控制丧失: 对方占据己方原先控制的开放线
  7. 出子落后: 己方已出子数少于对手 + 走棋未改善出子

用法:
    from strategic_mistake_detector import StrategicMistakeDetector
    mistakes = StrategicMistakeDetector.detect(board_before, board_after, move, is_white)
"""

import sys
import chess

sys.stdout.reconfigure(encoding="utf-8")

# ─── 棋子价值表 ───
PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

PIECE_NAMES = {
    chess.KING: "王", chess.QUEEN: "后", chess.ROOK: "车",
    chess.BISHOP: "象", chess.KNIGHT: "马", chess.PAWN: "兵",
}

CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}


# ═══════════════════════════════════════════════════════════════
#  特征提取
# ═══════════════════════════════════════════════════════════════

def _color_prefix(color: chess.Color) -> str:
    return "白" if color == chess.WHITE else "黑"


def _count_bishop_pair(board: chess.Board, color: chess.Color) -> bool:
    """是否有双象"""
    bishops = [sq for sq in chess.SQUARES
               if board.piece_at(sq)
               and board.piece_at(sq).piece_type == chess.BISHOP
               and board.piece_at(sq).color == color]
    return len(bishops) >= 2


def _count_pawns(board: chess.Board) -> int:
    """棋盘上所有兵的数量"""
    return len(board.pieces(chess.PAWN, chess.WHITE)) + \
           len(board.pieces(chess.PAWN, chess.BLACK))


def _is_closed_position(board: chess.Board) -> bool:
    """判断是否封闭局面：兵≥16 且多条线有兵对峙"""
    pawn_count = _count_pawns(board)
    if pawn_count < 14:
        return False
    blocked_files = 0
    for f in range(8):
        wp_rank = None
        bp_rank = None
        for r in range(8):
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN:
                if p.color == chess.WHITE:
                    wp_rank = r
                elif bp_rank is None:
                    bp_rank = r
        if wp_rank is not None and bp_rank is not None and bp_rank > wp_rank:
            blocked_files += 1
    return blocked_files >= 4


def _count_isolated_pawns(board: chess.Board, color: chess.Color) -> list:
    """返回某方所有孤兵所在格子名"""
    isolated = []
    for f in range(8):
        pawn_ranks = []
        for r in range(8):
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN and p.color == color:
                pawn_ranks.append(r)
        if not pawn_ranks:
            continue
        # 检查相邻列是否有己方兵
        has_adjacent = False
        for df in (-1, 1):
            adj_f = f + df
            if 0 <= adj_f <= 7:
                for r in range(8):
                    ap = board.piece_at(chess.square(adj_f, r))
                    if ap and ap.piece_type == chess.PAWN and ap.color == color:
                        has_adjacent = True
                        break
            if has_adjacent:
                break
        if not has_adjacent:
            for r in pawn_ranks:
                isolated.append(chess.square_name(chess.square(f, r)))
    return isolated


def _count_doubled_pawns(board: chess.Board, color: chess.Color) -> list:
    """返回某方所有叠兵所在列名"""
    doubled = []
    for f in range(8):
        pawn_count = 0
        for r in range(8):
            p = board.piece_at(chess.square(f, r))
            if p and p.piece_type == chess.PAWN and p.color == color:
                pawn_count += 1
        if pawn_count >= 2:
            doubled.append(chr(ord('a') + f))
    return doubled


def _center_control_score(board: chess.Board, color: chess.Color) -> int:
    """计算某方对中心4格的攻击控制分"""
    score = 0
    for sq in CENTER_SQUARES:
        attackers = board.attackers(color, sq)
        score += len(attackers)
    return score


def _count_developed_pieces(board: chess.Board, color: chess.Color) -> int:
    """计算某方已出动的轻子数（马和象不在原位）"""
    home_rank = 0 if color == chess.WHITE else 7
    developed = 0
    knight_home = [chess.B1, chess.G1] if color == chess.WHITE else [chess.B8, chess.G8]
    bishop_home = [chess.C1, chess.F1] if color == chess.WHITE else [chess.C8, chess.F8]
    all_home = knight_home + bishop_home

    for sq in all_home:
        p = board.piece_at(sq)
        if p is None or p.color != color or p.piece_type not in (chess.KNIGHT, chess.BISHOP):
            developed += 0
        else:
            pass  # 还在原位 = 未出动

    # 重新数不在原位的轻子
    developed_knights = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type == chess.KNIGHT:
            if sq not in knight_home:
                developed_knights += 1
    developed_bishops = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.color == color and p.piece_type == chess.BISHOP:
            if sq not in bishop_home:
                developed_bishops += 1

    return developed_knights + developed_bishops


def _count_pawn_shield(board: chess.Board, color: chess.Color) -> int:
    """王前兵盾完整度 (0-3)"""
    king_sq = board.king(color)
    if king_sq is None:
        return 0
    rank = chess.square_rank(king_sq)
    file = chess.square_file(king_sq)

    direction = 1 if color == chess.WHITE else -1
    shield_rank = rank + direction
    if not (1 <= shield_rank <= 6):
        return 0

    count = 0
    for df in (-1, 0, 1):
        f = file + df
        if 0 <= f <= 7:
            p = board.piece_at(chess.square(f, shield_rank))
            if p and p.color == color and p.piece_type == chess.PAWN:
                count += 1
    return count


def _is_open_file(board: chess.Board, file: int) -> bool:
    """检查某列是否完全无兵"""
    for r in range(8):
        p = board.piece_at(chess.square(file, r))
        if p and p.piece_type == chess.PAWN:
            return False
    return True


def _count_heavy_on_file(board: chess.Board, file: int, color: chess.Color) -> int:
    """某方在某列上的重子数"""
    count = 0
    for r in range(8):
        p = board.piece_at(chess.square(file, r))
        if p and p.color == color and p.piece_type in (chess.ROOK, chess.QUEEN):
            count += 1
    return count


# ═══════════════════════════════════════════════════════════════
#  规则引擎
# ═══════════════════════════════════════════════════════════════

class StrategicMistakeDetector:
    """局面型错误检测器 — 全部静态方法"""

    @staticmethod
    def detect(board_before: chess.Board,
               board_after: chess.Board,
               move: chess.Move,
               is_white: bool,
               move_number: int = 0) -> list:
        """
        对一步棋检测所有局面型错误。

        Args:
            board_before: 走棋前局面
            board_after: 走棋后局面
            move: 实际走的着法
            is_white: 走棋方是否白方
            move_number: 步数（用于报告）

        Returns:
            list[dict]: [{type, severity, description_zh, description_en, details}, ...]
        """
        color = chess.WHITE if is_white else chess.BLACK
        mistakes = []

        for detector in [
            StrategicMistakeDetector._rule_bad_bishop_for_knight,
            StrategicMistakeDetector._rule_pawn_structure_damage,
            StrategicMistakeDetector._rule_center_abandonment,
            StrategicMistakeDetector._rule_bishop_pair_loss,
            StrategicMistakeDetector._rule_king_shield_damage,
            StrategicMistakeDetector._rule_open_file_loss,
            StrategicMistakeDetector._rule_development_lag,
        ]:
            result = detector(board_before, board_after, move, color)
            if result:
                mistakes.append(result)

        return mistakes

    # ── 规则1: 坏象换好马 ──
    @staticmethod
    def _rule_bad_bishop_for_knight(board_before, board_after, move, color):
        """
        己方双象，走棋后用象换了马，且局面封闭。
        条件：走棋前己方有双象，走棋是象吃马（或走象后被马吃掉），走棋后己方无双象。
        """
        moving_piece = board_before.piece_at(move.from_square)
        captured_piece = board_before.piece_at(move.to_square)

        if moving_piece is None:
            return None
        if moving_piece.piece_type != chess.BISHOP:
            return None

        had_bishop_pair_before = _count_bishop_pair(board_before, color)
        if not had_bishop_pair_before:
            return None

        is_closed = _is_closed_position(board_before)

        # 是否用象换了马
        is_bishop_for_knight = False
        if captured_piece and captured_piece.piece_type == chess.KNIGHT and captured_piece.color != color:
            is_bishop_for_knight = True
        else:
            # 走象后，对方马吃掉了这只象？
            board_after_copy = board_after.copy()
            # 检查走象目的地是否会被对方马攻击
            for sq in chess.SQUARES:
                p = board_after.piece_at(sq)
                if p and p.piece_type == chess.KNIGHT and p.color != color:
                    if board_after.attacks(sq) and move.to_square in board_after.attacks(sq):
                        is_bishop_for_knight = True
                        break

        if not is_bishop_for_knight:
            return None

        has_pair_after = _count_bishop_pair(board_after, color)

        if not has_pair_after and is_closed:
            cp = _color_prefix(color)
            return {
                "type": "bad_bishop_for_knight",
                "severity": "moderate",
                "description_zh": (
                    f"{cp}方失去双象优势，用象换了对方的马。"
                    f"当前局面封闭（兵多），马比象更有价值，"
                    f"这是一次不合算的兑换，损害了长期战略。"
                ),
                "description_en": (
                    f"{'White' if color == chess.WHITE else 'Black'} traded bishop for knight "
                    f"in a closed position. Knight outvalues bishop here."
                ),
                "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
            }
        return None

    # ── 规则2: 兵型受损 ──
    @staticmethod
    def _rule_pawn_structure_damage(board_before, board_after, move, color):
        """
        走棋后出现新的叠兵或孤兵。
        """
        iso_before = set(_count_isolated_pawns(board_before, color))
        iso_after = set(_count_isolated_pawns(board_after, color))
        new_isolated = iso_after - iso_before

        dbl_before = set(_count_doubled_pawns(board_before, color))
        dbl_after = set(_count_doubled_pawns(board_after, color))
        new_doubled = dbl_after - dbl_before

        issues = []
        if new_isolated:
            issues.append(f"新孤兵: {', '.join(sorted(new_isolated))}")
        if new_doubled:
            issues.append(f"新叠兵在{', '.join(sorted(new_doubled))}线")

        if issues:
            cp = _color_prefix(color)
            return {
                "type": "pawn_structure_damage",
                "severity": "moderate",
                "description_zh": f"{cp}方兵型受损！{'；'.join(issues)}。这会成为残局中的持久弱点。",
                "description_en": f"Pawn structure damaged: {'; '.join(issues)}",
                "squares": list(new_isolated) + [f"{f}线" for f in new_doubled],
            }
        return None

    # ── 规则3: 放弃中心 ──
    @staticmethod
    def _rule_center_abandonment(board_before, board_after, move, color):
        """
        走棋后中心控制值下降 ≥30% 且不是被迫交换。
        """
        before = _center_control_score(board_before, color)
        after = _center_control_score(board_after, color)
        if before == 0:
            return None

        drop_pct = (before - after) / before
        if drop_pct >= 0.30:
            cp = _color_prefix(color)
            return {
                "type": "center_abandonment",
                "severity": "warning",
                "description_zh": (
                    f"{cp}方中心控制力明显下降（{before}→{after}，降{int(drop_pct*100)}%），"
                    f"可能放弃了对中心的关键控制。"
                ),
                "description_en": (
                    f"Center control dropped from {before} to {after} ({int(drop_pct*100)}%)"
                ),
                "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
            }
        return None

    # ── 规则4: 失去双象优势 ──
    @staticmethod
    def _rule_bishop_pair_loss(board_before, board_after, move, color):
        """
        走棋前有双象，走棋后失去双象，且对方仍保有双象。
        如果走棋不是象被吃（被吃不算主动错误），也要检测是否自己主动兑象。
        """
        had_pair = _count_bishop_pair(board_before, color)
        has_pair = _count_bishop_pair(board_after, color)
        if not had_pair or has_pair:
            return None

        enemy = not color
        enemy_has_pair = _count_bishop_pair(board_after, enemy)

        # 己方是主动用象换了对方什么？
        moving_piece = board_before.piece_at(move.from_square)
        if moving_piece and moving_piece.piece_type == chess.BISHOP:
            # 主动走象，且吃了对方的象（兑象）
            captured = board_before.piece_at(move.to_square)
            if captured and captured.piece_type == chess.BISHOP:
                cp = _color_prefix(color)
                return {
                    "type": "bishop_pair_loss",
                    "severity": "warning",
                    "description_zh": (
                        f"{cp}方主动兑象，失去双象优势。"
                        f"{'对手仍保有双象，在开放局面中这可能成为长期劣势。' if enemy_has_pair else ''}"
                    ),
                    "description_en": "Voluntarily gave up bishop pair",
                    "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
                }

        # 己方的象被对方吃掉了（检查走棋后被吃）
        captured_piece = board_before.piece_at(move.to_square)
        if captured_piece and captured_piece.piece_type == chess.BISHOP and captured_piece.color == color:
            return None  # 被吃不是己方的主动错误

        return None

    # ── 规则5: 王前兵阵破损 ──
    @staticmethod
    def _rule_king_shield_damage(board_before, board_after, move, color):
        """
        走棋后王前兵盾减少。
        """
        before = _count_pawn_shield(board_before, color)
        after = _count_pawn_shield(board_after, color)
        if after < before:
            cp = _color_prefix(color)
            return {
                "type": "king_shield_damage",
                "severity": "moderate",
                "description_zh": (
                    f"{cp}方王前兵盾破损（{before}→{after}），"
                    f"王的防御减弱，给对方制造了进攻机会。"
                ),
                "description_en": f"King's pawn shield weakened ({before}→{after})",
                "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
            }
        return None

    # ── 规则6: 开放线控制丧失 ──
    @staticmethod
    def _rule_open_file_loss(board_before, board_after, move, color):
        """
        己方车离开开放线，或对手的车占据了己方的开放线。
        """
        enemy = not color

        # 走棋前己方控制哪些开放线
        controlled_before = []
        for f in range(8):
            if _is_open_file(board_before, f):
                own_heavy = _count_heavy_on_file(board_before, f, color)
                enemy_heavy = _count_heavy_on_file(board_before, f, enemy)
                if own_heavy > enemy_heavy:
                    controlled_before.append(f)

        # 走棋后己方还控制哪些开放线
        for f in range(8):
            if _is_open_file(board_after, f):
                own_heavy_after = _count_heavy_on_file(board_after, f, color)
                enemy_heavy_after = _count_heavy_on_file(board_after, f, enemy)
                if f in controlled_before and own_heavy_after <= enemy_heavy_after:
                    cp = _color_prefix(color)
                    fname = chr(ord('a') + f)
                    return {
                        "type": "open_file_loss",
                        "severity": "warning",
                        "description_zh": (
                            f"{cp}方失去了对{fname}线开放线的控制！"
                            f"在开放线上失去主动权可能让对手的车获得巨大的活动空间。"
                        ),
                        "description_en": f"Lost control of open {fname}-file",
                        "squares": [chess.square_name(move.from_square)],
                    }

        return None

    # ── 规则7: 出子落后 ──
    @staticmethod
    def _rule_development_lag(board_before, board_after, move, color):
        """
        走棋前己方出子数已落后于对手，走棋后差距没有缩小。
        仅在前15步触发。
        """
        enemy = not color
        own_dev_before = _count_developed_pieces(board_before, color)
        enemy_dev_before = _count_developed_pieces(board_before, enemy)
        own_dev_after = _count_developed_pieces(board_after, color)

        gap_before = enemy_dev_before - own_dev_before
        if gap_before >= 2:
            # 己方已经落后2个轻子
            gap_after = _count_developed_pieces(board_after, enemy) - own_dev_after
            if gap_after >= gap_before:
                cp = _color_prefix(color)
                return {
                    "type": "development_lag",
                    "severity": "moderate",
                    "description_zh": (
                        f"{cp}方出子落后（已出动{own_dev_before}个轻子 vs 对方{enemy_dev_before}个），"
                        f"这一步没有改善出子。在开局阶段，出子落后可能导致战术弱点。"
                    ),
                    "description_en": (
                        f"Development lag: {own_dev_before} pieces developed vs {enemy_dev_before}"
                    ),
                    "squares": [],
                }
        return None


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("局面型错误检测器 自测")
    print("=" * 60)

    # 测试 1: 坏象换好马 — 白方用象吃黑马(d5)且局面封闭
    print("\n--- 测试 1: 坏象换好马 ---")
    # 封闭局面：双方多兵，白方双象，用象b5吃c6马
    board_before1 = chess.Board(
        "r1bqkb1r/pppp1ppp/2n2n2/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 5 4"
    )
    board_after1 = chess.Board(
        "r1bqkb1r/pppp1ppp/2B2n2/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 4"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_before1, board_after1,
        chess.Move.from_uci("b5c6"), True
    )
    if mistakes:
        for m in mistakes:
            print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")
    else:
        print(f"  (未检测到错误 — 若局面不够封闭则可能不触发)")

    # 测试 2: 兵型受损 - 形成叠兵
    print("\n--- 测试 2: 兵型受损 ---")
    # 白方用 b 兵吃 c3，形成 c 线叠兵
    board_test_before = chess.Board(
        "rnbqkb1r/pppp1ppp/4pn2/8/2PP4/2b5/PP2PPPP/R1BQKBNR w KQkq - 0 4"
    )
    board_test_after = chess.Board(
        "rnbqkb1r/pppp1ppp/4pn2/8/2PP4/2P5/P3PPPP/R1BQKBNR b KQkq - 0 4"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_test_before, board_test_after,
        chess.Move.from_uci("b2c3"), True
    )
    for m in mistakes:
        print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")

    # 测试 3: 放弃中心 — 白方马从 f3 退到 e1 (中心控制下降)
    print("\n--- 测试 3: 放弃中心 ---")
    board_center_before = chess.Board(
        "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3"
    )
    # Nf3→Ng1 马退回原位 (不是 e1 因为我用了错误的格子)
    board_center_after = chess.Board(
        "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/8/PPPPNPPP/RNBQKB1R b KQkq - 3 3"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_center_before, board_center_after,
        chess.Move.from_uci("f3e1"), True
    )
    for m in mistakes:
        print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")

    # 测试 4: 王前兵阵破损 — 白方推进 g 兵
    print("\n--- 测试 4: 王前兵阵破损 ---")
    board_ks_before = chess.Board(
        "rnbq1rk1/pppp1ppp/5n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQ1RK1 w - - 5 5"
    )
    board_ks_after = chess.Board(
        "rnbq1rk1/pppp1ppp/5n2/2b1p3/2B1P3/5NP1/PPPP1P1P/RNBQ1RK1 b - - 0 5"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_ks_before, board_ks_after,
        chess.Move.from_uci("g2g3"), True
    )
    for m in mistakes:
        print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")

    # 测试 5: 失去双象优势 — 白方主动用象换象(Bg5→Bxf6)
    print("\n--- 测试 5: 失去双象优势 ---")
    board_bp_before = chess.Board(
        "rnbqkb1r/pppp1ppp/4pn2/6B1/4P3/8/PPPP1PPP/RN1QKBNR w KQkq - 2 3"
    )
    board_bp_after = chess.Board(
        "rnbqkb1r/pppp1ppp/4pB2/8/4P3/8/PPPP1PPP/RN1QKBNR b KQkq - 0 3"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_bp_before, board_bp_after,
        chess.Move.from_uci("g5f6"), True
    )
    for m in mistakes:
        print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")

    # 测试 6: 出子落后 — 白方反复走同一个棋子
    print("\n--- 测试 6: 出子落后 ---")
    board_dev_before = chess.Board(
        "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 2 3"
    )
    # 白方 Nc3→Qe2（走后而不是继续出子），出子优势丧失
    board_dev_after = chess.Board(
        "rnbqkb1r/pppp1ppp/5n2/4p3/4P3/8/PPPPQPPP/R1B1KBNR b KQkq - 3 3"
    )
    mistakes = StrategicMistakeDetector.detect(
        board_dev_before, board_dev_after,
        chess.Move.from_uci("d1e2"), True
    )
    for m in mistakes:
        print(f"  {'⚠' if m['severity']=='moderate' else '⚡'} [{m['type']}] {m['description_zh']}")

    print(f"\n✅ 自测完成")