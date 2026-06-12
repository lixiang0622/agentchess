"""
战术主题自动检测器
纯 python-chess 检测，不调引擎。对每步棋检测 7 种战术主题：
击双、牵制、串击、闪击/闪将、引离、中间着、杀棋威胁

用法:
    from tactical_detector import TacticalDetector
    themes = TacticalDetector.detect(board_before, board_after, move, is_white)
"""

import sys
import chess

sys.stdout.reconfigure(encoding="utf-8")


# 棋子价值表
PIECE_VALUES = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}


class TacticalDetector:
    """战术主题检测器 — 全部为静态方法"""

    # ---- 检测入口 ----
    @staticmethod
    def detect(board_before: chess.Board,
               board_after: chess.Board,
               move: chess.Move,
               is_white: bool,
               prev_move: chess.Move = None,
               score_after=None) -> list:
        """
        对一步棋检测所有战术主题。

        Args:
            board_before: 走棋前局面
            board_after: 走棋后局面
            move: 实际走的着法
            is_white: 走棋方是否白方
            prev_move: 上一步着法（用于中间着检测）
            score_after: Stockfish 评分对象（用于杀棋威胁检测）

        Returns:
            list[dict]: [{type, description_zh, description_en, squares, pieces}, ...]
        """
        themes = []

        for detector in [
            TacticalDetector._detect_fork,
            TacticalDetector._detect_pin,
            TacticalDetector._detect_skewer,
            TacticalDetector._detect_discovered,
            TacticalDetector._detect_deflection,
            TacticalDetector._detect_zwischenzug,
            TacticalDetector._detect_mate_threat,
        ]:
            result = detector(board_before, board_after, move, is_white,
                              prev_move, score_after)
            if result:
                themes.append(result)

        return themes

    # ================================================================
    #  击双 (Fork / Double Attack)
    # ================================================================
    @staticmethod
    def _detect_fork(board_before, board_after, move, is_white, *args):
        """
        走棋后，走棋子同时攻击两个以上敌方棋子。
        仅当被攻击棋子中有价值 ≥3（轻子以上）时才视为击双（不报告"攻击两个兵"）。
        """
        piece = board_after.piece_at(move.to_square)
        if piece is None:
            return None

        color = chess.WHITE if is_white else chess.BLACK
        enemy = chess.BLACK if is_white else chess.WHITE

        attacked = board_after.attacks(move.to_square)
        targets = []
        for sq in attacked:
            p = board_after.piece_at(sq)
            if p and p.color == enemy and PIECE_VALUES.get(p.piece_type, 0) >= 3:
                targets.append((sq, p))

        if len(targets) >= 2:
            sq_names = [chess.square_name(s) for s, _ in targets]
            piece_names = [
                f"{'白' if p.color == chess.WHITE else '黑'}{_piece_name_zh(p)}{chess.square_name(s)}"
                for s, p in targets
            ]
            fork_piece_name = f"{'白' if is_white else '黑'}{_piece_name_zh(piece)}"
            return {
                "type": "fork",
                "description_zh": f"{fork_piece_name}{chess.square_name(move.to_square)}同时攻击{', '.join(piece_names)}",
                "description_en": f"Fork: {piece.symbol()}{chess.square_name(move.to_square)} attacks {', '.join(sq_names)}",
                "squares": [chess.square_name(move.to_square)] + sq_names,
                "pieces": [f"{piece.symbol()}{chess.square_name(move.to_square)}"] +
                          [f"{p.symbol()}{chess.square_name(s)}" for s, p in targets],
            }

        return None

    # ================================================================
    #  牵制 (Pin)
    # ================================================================
    @staticmethod
    def _detect_pin(board_before, board_after, move, is_white, *args):
        """
        检测走棋后是否新产生了牵制。
        用 python-chess 内置 board.is_pinned()，比较走棋前后的变化。
        """
        enemy = chess.BLACK if is_white else chess.WHITE

        new_pins = []
        for sq in chess.SQUARES:
            piece_after = board_after.piece_at(sq)
            if piece_after is None or piece_after.color != enemy:
                continue
            if board_before.is_pinned(enemy, sq):
                continue  # 之前就已经被牵制
            if board_after.is_pinned(enemy, sq):
                # 新产生的牵制
                pin_type, attacker_sq, behind_sq = TacticalDetector._pin_details(
                    board_after, enemy, sq)
                new_pins.append((sq, piece_after, pin_type, attacker_sq, behind_sq))

        if not new_pins:
            return None

        # 报告第一个（或最重要的）牵制
        sq, pinned_piece, pin_type, attacker_sq, behind_sq = new_pins[0]
        type_label = "绝对牵制" if pin_type == "absolute" else "相对牵制"
        attacker = board_after.piece_at(attacker_sq)
        behind = board_after.piece_at(behind_sq) if behind_sq is not None else None

        return {
            "type": "pin",
            "description_zh": f"{'白' if is_white else '黑'}方对{'黑' if is_white else '白'}{_piece_name_zh(pinned_piece)}{chess.square_name(sq)}制造了{type_label}（{_piece_name_zh(attacker)}牵制，后方是{_piece_name_zh(behind) if behind else '?'}）",
            "description_en": f"Pin: {attacker.symbol()}{chess.square_name(attacker_sq)} pins {pinned_piece.symbol()}{chess.square_name(sq)} ({pin_type})",
            "squares": [chess.square_name(sq), chess.square_name(attacker_sq)],
            "pieces": [f"{pinned_piece.symbol()}{chess.square_name(sq)}",
                       f"{attacker.symbol()}{chess.square_name(attacker_sq)}"],
        }

    @staticmethod
    def _pin_details(board, color, pinned_sq):
        """判断牵制类型：绝对（后方是王）vs 相对（后方是其他子）"""
        enemy = not color

        # 找到攻击者：沿 pinned_sq 的攻击线反向查找滑动棋子
        attackers = board.attackers(enemy, pinned_sq)
        for attacker_sq in attackers:
            attacker = board.piece_at(attacker_sq)
            if attacker and attacker.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                # 沿攻击方向继续找，看 pinned 棋子后面是什么
                dx = chess.square_file(attacker_sq) - chess.square_file(pinned_sq)
                dy = chess.square_rank(attacker_sq) - chess.square_rank(pinned_sq)

                # 归一化方向
                if dx != 0:
                    dx = dx // abs(dx)
                if dy != 0:
                    dy = dy // abs(dy)

                # 从 pinned_sq 往远离攻击者的方向找
                f = chess.square_file(pinned_sq) + dx
                r = chess.square_rank(pinned_sq) + dy
                while 0 <= f < 8 and 0 <= r < 8:
                    behind_sq = chess.square(f, r)
                    behind = board.piece_at(behind_sq)
                    if behind and behind.color == color:
                        if behind.piece_type == chess.KING:
                            return ("absolute", attacker_sq, behind_sq)
                        else:
                            return ("relative", attacker_sq, behind_sq)
                    f += dx
                    r += dy

                return ("absolute", attacker_sq, None)  # 默认视为绝对牵制

        return ("absolute", None, None)

    # ================================================================
    #  串击 (Skewer)
    # ================================================================
    @staticmethod
    def _detect_skewer(board_before, board_after, move, is_white, *args):
        """
        检测走棋后滑动棋子是否串击了两个敌方棋子。
        串击条件：同一条射线上有两个敌方棋子，且前面（靠近攻击者）的棋子价值更高。
        """
        piece = board_after.piece_at(move.to_square)
        if piece is None or piece.piece_type not in (chess.BISHOP, chess.ROOK, chess.QUEEN):
            return None

        enemy = chess.BLACK if is_white else chess.WHITE
        attacking_sq = move.to_square

        # B/R/Q 的滑动方向
        if piece.piece_type == chess.BISHOP:
            dirs = [(-1, -1), (-1, 1), (1, -1), (1, 1)]
        elif piece.piece_type == chess.ROOK:
            dirs = [(0, -1), (0, 1), (-1, 0), (1, 0)]
        else:
            dirs = [(-1, -1), (-1, 1), (1, -1), (1, 1),
                    (0, -1), (0, 1), (-1, 0), (1, 0)]

        for df, dr in dirs:
            enemy_on_line = []
            f = chess.square_file(attacking_sq) + df
            r = chess.square_rank(attacking_sq) + dr
            while 0 <= f < 8 and 0 <= r < 8:
                sq = chess.square(f, r)
                p = board_after.piece_at(sq)
                if p:
                    if p.color == enemy:
                        enemy_on_line.append((sq, p))
                        if len(enemy_on_line) >= 2:
                            break  # 找到两个了
                    else:
                        break  # 被己方棋子阻挡
                f += df
                r += dr

            if len(enemy_on_line) == 2:
                front_sq, front = enemy_on_line[0]
                back_sq, back = enemy_on_line[1]
                front_val = PIECE_VALUES.get(front.piece_type, 0)
                back_val = PIECE_VALUES.get(back.piece_type, 0)
                if front_val > back_val:
                    return {
                        "type": "skewer",
                        "description_zh": f"{'白' if is_white else '黑'}{_piece_name_zh(piece)}{chess.square_name(attacking_sq)}串击{chess.square_name(front_sq)}的{_piece_name_zh(front)}，背后是{chess.square_name(back_sq)}的{_piece_name_zh(back)}",
                        "description_en": f"Skewer: {piece.symbol()}{chess.square_name(attacking_sq)} skewers {front.symbol()}{chess.square_name(front_sq)} -> {back.symbol()}{chess.square_name(back_sq)}",
                        "squares": [chess.square_name(attacking_sq), chess.square_name(front_sq), chess.square_name(back_sq)],
                        "pieces": [f"{piece.symbol()}{chess.square_name(attacking_sq)}",
                                   f"{front.symbol()}{chess.square_name(front_sq)}",
                                   f"{back.symbol()}{chess.square_name(back_sq)}"],
                    }

        return None

    # ================================================================
    #  闪击/闪将 (Discovered Attack / Discovered Check)
    # ================================================================
    @staticmethod
    def _detect_discovered(board_before, board_after, move, is_white, *args):
        """
        检测走棋后是否暴露了后方滑动棋子的攻击线。
        从走子的原来格子（from_square）往所有方向找后方滑动棋子，
        比较走子前后它的攻击范围是否新增敌军目标。
        """
        color = chess.WHITE if is_white else chess.BLACK
        enemy = chess.BLACK if is_white else chess.WHITE

        from_sq = move.from_square

        # 方向列表
        all_dirs = [(-1, -1), (-1, 0), (-1, 1), (0, -1),
                     (0, 1), (1, -1), (1, 0), (1, 1)]

        for df, dr in all_dirs:
            # 从 from_sq 往反方向（后方）找滑动棋子
            f = chess.square_file(from_sq)
            r = chess.square_rank(from_sq)

            # 先确认后方有己方滑动棋子
            behind_f = f - df
            behind_r = r - dr
            found_slider = None
            while 0 <= behind_f < 8 and 0 <= behind_r < 8:
                behind_sq = chess.square(behind_f, behind_r)
                behind_piece = board_before.piece_at(behind_sq)
                if behind_piece is None:
                    behind_f -= df
                    behind_r -= dr
                    continue
                if behind_piece.color == color and behind_piece.piece_type in (chess.BISHOP, chess.ROOK, chess.QUEEN):
                    found_slider = behind_sq
                    break
                else:
                    break  # 有其他棋子阻挡

            if found_slider is None:
                continue

            # 比较走子前后该滑动棋子攻击范围的差异
            attacks_before = board_before.attacks(found_slider) if board_before.piece_at(from_sq) else set()
            attacks_after = board_after.attacks(found_slider)
            new_attacks = attacks_after - attacks_before  # 注意：需要正确的交集

            # 实际做法：走完后该滑动棋子沿 df,dr 方向能打到什么新目标？
            # 如果走完后的 from_sq 现在可以为空或被占据，该方向的攻击可能穿透
            # 检查 from_sq 方向上（走棋后）是否有新目标
            ahead_f = f + df
            ahead_r = r + dr
            while 0 <= ahead_f < 8 and 0 <= ahead_r < 8:
                ahead_sq = chess.square(ahead_f, ahead_r)
                ahead_piece = board_after.piece_at(ahead_sq)
                if ahead_piece:
                    if ahead_piece.color == enemy:
                        is_check = (ahead_piece.piece_type == chess.KING)
                        slider = board_after.piece_at(found_slider)
                        return {
                            "type": "discovered_check" if is_check else "discovered_attack",
                            "description_zh": f"{'白' if is_white else '黑'}方走出闪{'将' if is_check else '击'}！{_piece_name_zh(slider)}{chess.square_name(found_slider)}通过{chess.square_name(from_sq)}攻击{'黑王' if is_check else _piece_name_zh(ahead_piece) + chess.square_name(ahead_sq)}",
                            "description_en": f"Discovered {'check' if is_check else 'attack'}: {slider.symbol()}{chess.square_name(found_slider)} through {chess.square_name(from_sq)}",
                            "squares": [chess.square_name(found_slider), chess.square_name(from_sq), chess.square_name(ahead_sq)],
                            "pieces": [f"{slider.symbol()}{chess.square_name(found_slider)}",
                                       f"{ahead_piece.symbol()}{chess.square_name(ahead_sq)}"],
                        }
                    else:
                        break  # 被己方棋子阻挡
                ahead_f += df
                ahead_r += dr

        return None

    # ================================================================
    #  引离 (Deflection)
    # ================================================================
    @staticmethod
    def _detect_deflection(board_before, board_after, move, is_white, *args):
        """
        如果走子是吃子，检查被吃子在吃之前防守了哪些重要格子。
        如果这些格子在吃后失去所有防守，且是高分值目标格子（王、后、中心格），则为引离。
        """
        enemy = chess.BLACK if is_white else chess.WHITE

        captured_sq = move.to_square
        captured_piece = board_before.piece_at(captured_sq)

        # 必须是吃子
        if captured_piece is None:
            return None

        # 被吃子防守了哪些格子？
        defended_before = board_before.attacks(captured_sq)

        # 筛选敌方可能攻击的目标格子
        lost_defenses = []
        for target_sq in defended_before:
            target_piece = board_before.piece_at(target_sq)
            if target_piece is None or target_piece.color != enemy:
                continue

            # 检查 target_sq 在走子后是否失去全部防守
            attackers_before = board_before.attackers(enemy, target_sq)
            attackers_after = board_after.attackers(enemy, target_sq)

            if attackers_before and not attackers_after:
                # 完全失去了防守
                val = PIECE_VALUES.get(target_piece.piece_type, 0)
                # 只报告防守王、后，或中心要害格
                is_key = (target_piece.piece_type == chess.KING or
                          target_piece.piece_type == chess.QUEEN or
                          chess.square_name(target_sq) in ('d4', 'd5', 'e4', 'e5'))
                if is_key:
                    lost_defenses.append((target_sq, target_piece))

        if lost_defenses:
            target_sq, target_piece = lost_defenses[0]
            moving_piece = board_after.piece_at(captured_sq)
            return {
                "type": "deflection",
                "description_zh": f"引离战术！{'白' if is_white else '黑'}方吃掉防守{chess.square_name(target_sq)}的{_piece_name_zh(captured_piece)}，{_piece_name_zh(target_piece)}失去了保护",
                "description_en": f"Deflection: capturing {captured_piece.symbol()} removes defender of {target_piece.symbol()}{chess.square_name(target_sq)}",
                "squares": [chess.square_name(captured_sq), chess.square_name(target_sq)],
                "pieces": [f"{captured_piece.symbol()}(defender)",
                           f"{target_piece.symbol()}{chess.square_name(target_sq)}"],
            }

        return None

    # ================================================================
    #  中间着 (Zwischenzug / Intermediate Move)
    # ================================================================
    @staticmethod
    def _detect_zwischenzug(board_before, board_after, move, is_white,
                             prev_move, *args):
        """
        上一步是吃子，但当前步没有在同一个格子回吃，反而走了将军或吃高价值子。
        """
        if prev_move is None:
            return None

        # 上一步是吃子吗？
        if not board_before.is_capture(prev_move):
            return None

        prev_captured_sq = prev_move.to_square

        # 如果当前步在上一格的同一个格子回吃，就是正常交换，不是中间着
        if move.to_square == prev_captured_sq:
            return None

        # 当前步是将军或吃高价值子吗？
        if board_after.is_check():
            return {
                "type": "zwischenzug",
                "description_zh": f"中间着！{'白' if is_white else '黑'}方没有立即回吃，而是先走了{board_before.san(move)}（将军），打乱对方节奏",
                "description_en": f"Zwischenzug: {board_before.san(move)} before recapturing",
                "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
                "pieces": [],
            }

        # 当前步吃子且被吃子价值 >= 3
        captured = board_before.piece_at(move.to_square)
        if captured and PIECE_VALUES.get(captured.piece_type, 0) >= 3:
            return {
                "type": "zwischenzug",
                "description_zh": f"中间着！{'白' if is_white else '黑'}方先吃掉{_piece_name_zh(captured)}再回吃，抢占先机",
                "description_en": f"Zwischenzug: captures {captured.symbol()} before recapturing",
                "squares": [chess.square_name(move.from_square), chess.square_name(move.to_square)],
                "pieces": [f"{captured.symbol()}{chess.square_name(move.to_square)}"],
            }

        return None

    # ================================================================
    #  杀棋威胁 (Mate Threat)
    # ================================================================
    @staticmethod
    def _detect_mate_threat(board_before, board_after, move, is_white,
                             prev_move, score_after, *args):
        """
        利用已有的 Stockfish 评分检测杀棋（#1, #2）。
        不额外调引擎，纯解析评分对象。
        """
        if score_after is None:
            return None

        try:
            if score_after.is_mate():
                mate_in = score_after.mate()  # 正数=白方将杀，负数=黑方将杀
                if 1 <= mate_in <= 2:
                    side = "白方" if mate_in > 0 else "黑方"
                    return {
                        "type": "mate_threat",
                        "description_zh": f"{side}有{abs(mate_in)}步杀！",
                        "description_en": f"Mate in {abs(mate_in)} for {'White' if mate_in > 0 else 'Black'}",
                        "squares": [],
                        "pieces": [],
                    }
        except Exception:
            pass

        return None


# ===================== 辅助函数 =====================

def _piece_name_zh(piece) -> str:
    """棋子中文名"""
    if piece is None:
        return "?"
    names = {
        chess.KING: "王",
        chess.QUEEN: "后",
        chess.ROOK: "车",
        chess.BISHOP: "象",
        chess.KNIGHT: "马",
        chess.PAWN: "兵",
    }
    color = "白" if piece.color == chess.WHITE else "黑"
    return f"{color}{names.get(piece.piece_type, '?')}"


# ===================== 自测 =====================

if __name__ == "__main__":
    print("=" * 50)
    print("战术检测器自测")
    print("=" * 50)

    # 测试 1: 击双 - 马在 d5 同时攻击 e7 王和 a8 车
    print("\n--- 测试击双 (Knight Fork) ---")
    board_before = chess.Board("r1bqkb1r/pppp1ppp/2n5/4p3/4P3/3N4/PPPP1PPP/R1BQKBNR w KQkq - 0 1")
    board_after = chess.Board("r1bqkb1r/pppp1ppp/2n5/3Np3/4P3/8/PPPP1PPP/R1BQKBNR b KQkq - 0 1")
    move = chess.Move.from_uci("d3d5")
    themes = TacticalDetector.detect(board_before, board_after, move, True)
    for t in themes:
        print(f"  ✓ {t['type']}: {t['description_zh']}")

    # 测试 2: 牵制 - Bb5 牵制 Nc6
    print("\n--- 测试牵制 (Pin) ---")
    board_before = chess.Board("r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1")
    board_after = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1")
    move = chess.Move.from_uci("f1b5")
    themes = TacticalDetector.detect(board_before, board_after, move, True)
    for t in themes:
        print(f"  ✓ {t['type']}: {t['description_zh']}")

    # 测试 3: 闪将
    print("\n--- 测试闪将 (Discovered Check) ---")
    board_before = chess.Board("r1bqkb1r/pppp1ppp/2n5/4P3/8/5N2/PPPPBPPP/RNBQK2R b KQkq - 0 1")
    board_after = chess.Board("r1bqkb1r/pppp1ppp/2n5/4P3/8/5N2/PPPPBPPP/RNBQ1RK1 b kq - 0 1")
    move = chess.Move.from_uci("e1g1")
    themes = TacticalDetector.detect(board_before, board_after, move, True)
    for t in themes:
        print(f"  ✓ {t['type']}: {t['description_zh']}")

    # 测试 4: 串击
    print("\n--- 测试串击 (Skewer) ---")
    board_before = chess.Board("4k3/8/8/8/8/8/4q3/4B2K w - - 0 1")
    board_after = chess.Board("4k3/8/8/8/4B3/8/4q3/7K b - - 0 1")
    move = chess.Move.from_uci("e1e4")
    themes = TacticalDetector.detect(board_before, board_after, move, True)
    for t in themes:
        print(f"  ✓ {t['type']}: {t['description_zh']}")

    # 测试 5: 中间着
    print("\n--- 测试中间着 (Zwischenzug) ---")
    board_before = chess.Board("r1bqkb1r/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1")
    prev = chess.Move.from_uci("b1c3")  # not a capture, won't trigger
    # Need a better test: prev was a capture, current is check
    # Set up: e4xd5 capture, then instead of recapturing, play check
    board = chess.Board("rnbqkb1r/ppp1pppp/3p4/3N4/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 1")
    # Black's queen was on d8, white captured d5 with N — black plays Bg4+ instead of recapturing
    prev_move = chess.Move.from_uci("f3d5")  # pretend prev was capture on d5
    board_before2 = chess.Board("rnbqkb1r/ppp1pppp/3P4/8/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 1")
    board_after2 = chess.Board("rnbqkb1r/ppp1pppp/3P4/8/4P1b1/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1")
    move2 = chess.Move.from_uci("c8g4")
    themes = TacticalDetector.detect(board_before2, board_after2, move2, False, prev_move)
    for t in themes:
        print(f"  ✓ {t['type']}: {t['description_zh']}")

    print(f"\n✅ 自测完成")