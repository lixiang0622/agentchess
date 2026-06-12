"""
局面特征可解释性模块 (Position Explainability)
从"是什么"到"为什么"——自动生成评分变化的棋理原因解释。

核心思路:
  走棋前 vs 走棋后提取"局面特征向量"，对比变化，
  自动生成中文诊断报告，解释为什么评分会变化。

用法:
  from position_explain import PositionExplainer
  explainer = PositionExplainer()
  analysis = explainer.analyze(board_before, board_after, move, score_diff, side)
  # analysis["explanation_zh"] = "黑方用位置很好的象换了白方防守型马..."
"""

import sys
import chess
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

# ─── 棋子价值 ───
PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

PIECE_NAMES = {
    chess.PAWN: "兵", chess.KNIGHT: "马", chess.BISHOP: "象",
    chess.ROOK: "车", chess.QUEEN: "后", chess.KING: "王",
}

CENTER_SQUARES = {chess.D4, chess.D5, chess.E4, chess.E5}


# ═══════════════════════════════════════════════════════════════
#  特征提取
# ═══════════════════════════════════════════════════════════════

def extract_features(board: chess.Board) -> dict:
    """从局面中提取完整的特征向量"""
    return {
        # === 子力 ===
        "material": _material_features(board),
        # === 王安全 ===
        "king_safety": _king_safety_features(board),
        # === 兵形 ===
        "pawn_structure": _pawn_features(board),
        # === 空间与机动性 ===
        "space_mobility": _space_mobility_features(board),
        # === 出子状态 ===
        "development": _development_features(board),
        # === 关键优势 ===
        "key_advantages": _key_advantages_features(board),
    }


# ─── 子力特征 ───
def _material_features(board: chess.Board) -> dict:
    w_material = 0
    b_material = 0
    w_count = {"后": 0, "车": 0, "象": 0, "马": 0, "兵": 0}
    b_count = {"后": 0, "车": 0, "象": 0, "马": 0, "兵": 0}

    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if not p:
            continue
        val = PIECE_VALUES.get(p.piece_type, 0)
        name = PIECE_NAMES.get(p.piece_type, "?")
        if p.color == chess.WHITE:
            w_material += val
            w_count[name] = w_count.get(name, 0) + 1
        else:
            b_material += val
            b_count[name] = b_count.get(name, 0) + 1

    return {
        "white_total": w_material,
        "black_total": b_material,
        "diff": w_material - b_material,
        "white_pieces": w_count,
        "black_pieces": b_count,
    }


# ─── 王安全特征 ───
def _king_safety_features(board: chess.Board) -> dict:
    result = {}
    for color, name in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        king_sq = board.king(color)
        if king_sq is None:
            result[name] = {"score": 0, "shield": 0, "nearby_attackers": 0, "open_files_near_king": 0}
            continue

        # 兵盾
        rank = chess.square_rank(king_sq)
        file = chess.square_file(king_sq)
        direction = 1 if color == chess.WHITE else -1
        shield_rank = rank + direction

        shield = 0
        if 1 <= shield_rank <= 6:
            for df in (-1, 0, 1):
                f = file + df
                if 0 <= f <= 7:
                    p = board.piece_at(chess.square(f, shield_rank))
                    if p and p.color == color and p.piece_type == chess.PAWN:
                        shield += 1

        # 附近攻子
        enemy = not color
        nearby_attackers = 0
        king_zone = set()
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                f, r = file + df, rank + dr
                if 0 <= f < 8 and 0 <= r < 8:
                    king_zone.add(chess.square(f, r))

        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == enemy:
                attacks = board.attacks(sq)
                if attacks & king_zone:
                    nearby_attackers += 1

        # 王周围开放线
        open_files_near = 0
        for df in (-1, 0, 1):
            f = file + df
            if 0 <= f <= 7:
                has_pawn = any(
                    board.piece_at(chess.square(f, r)) and
                    board.piece_at(chess.square(f, r)).piece_type == chess.PAWN
                    for r in range(8)
                )
                if not has_pawn:
                    open_files_near += 1

        score = max(0, 10 - (3 - shield) * 2 - nearby_attackers * 1 - open_files_near * 2)
        result[name] = {
            "score": score,
            "shield": shield,
            "nearby_attackers": nearby_attackers,
            "open_files_near_king": open_files_near,
        }
    return result


# ─── 兵形特征 ───
def _pawn_features(board: chess.Board) -> dict:
    result = {}
    for color, name in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        isolated = 0
        doubled = 0
        passed = 0

        for f in range(8):
            file_pawns = []
            for r in range(8):
                p = board.piece_at(chess.square(f, r))
                if p and p.piece_type == chess.PAWN and p.color == color:
                    file_pawns.append(r)

            if len(file_pawns) >= 2:
                doubled += len(file_pawns) - 1

            for r in file_pawns:
                # 孤兵
                adj_has_pawn = False
                for df in (-1, 1):
                    af = f + df
                    if 0 <= af <= 7:
                        for ar in range(8):
                            ap = board.piece_at(chess.square(af, ar))
                            if ap and ap.piece_type == chess.PAWN and ap.color == color:
                                adj_has_pawn = True
                if not adj_has_pawn:
                    isolated += 1

                # 通路兵
                enemy = not color
                direction = 1 if color == chess.WHITE else -1
                blocked = False
                cr = r + direction
                while 0 <= cr <= 7:
                    for df in (-1, 0, 1):
                        cf = f + df
                        if 0 <= cf <= 7:
                            bp = board.piece_at(chess.square(cf, cr))
                            if bp and bp.piece_type == chess.PAWN and bp.color == enemy:
                                blocked = True
                    cr += direction
                if not blocked:
                    passed += 1

        result[name] = {"isolated": isolated, "doubled": doubled, "passed": passed}
    return result


# ─── 空间机动性 ───
def _space_mobility_features(board: chess.Board) -> dict:
    result = {}
    for color, name in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        # 机动性：合法走法数
        board_copy = board.copy()
        board_copy.turn = color
        mobility = len(list(board_copy.legal_moves))

        # 中心控制
        center_control = 0
        for sq in CENTER_SQUARES:
            center_control += len(board.attackers(color, sq))

        # 兵在对方半场数
        advanced_pawns = sum(
            1 for sq in chess.SQUARES
            if (chess.square_rank(sq) >= 5 if color == chess.WHITE else chess.square_rank(sq) <= 2)
            and board.piece_at(sq)
            and board.piece_at(sq).color == color
            and board.piece_at(sq).piece_type == chess.PAWN
        )

        result[name] = {
            "mobility": mobility,
            "center_control": center_control,
            "advanced_pawns": advanced_pawns,
        }
    return result


# ─── 出子状态 ───
def _development_features(board: chess.Board) -> dict:
    result = {}
    for color, name in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        home_rank = 0 if color == chess.WHITE else 7
        knight_home = [chess.B1, chess.G1] if color == chess.WHITE else [chess.B8, chess.G8]
        bishop_home = [chess.C1, chess.F1] if color == chess.WHITE else [chess.C8, chess.F8]

        # 已出动轻子
        developed = 0
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color:
                if p.piece_type == chess.KNIGHT and sq not in knight_home:
                    developed += 1
                if p.piece_type == chess.BISHOP and sq not in bishop_home:
                    developed += 1

        # 是否易位
        king_sq = board.king(color)
        castled = king_sq is not None and (
            (color == chess.WHITE and king_sq in (chess.G1, chess.C1)) or
            (color == chess.BLACK and king_sq in (chess.G8, chess.C8))
        )

        # 后是否过早出动（前8步内后离开原位）
        queen_home = chess.D1 if color == chess.WHITE else chess.D8
        queen_out_early = False
        queen_piece = board.piece_at(queen_home)
        if queen_piece is None or queen_piece.color != color or queen_piece.piece_type != chess.QUEEN:
            queen_out_early = True

        # 车是否连通
        rook1 = chess.A1 if color == chess.WHITE else chess.A8
        rook2 = chess.H1 if color == chess.WHITE else chess.H8
        rooks_connected = (
            board.piece_at(rook1) is None and board.piece_at(rook2) is None
        )

        result[name] = {
            "developed": developed,
            "castled": castled,
            "queen_out_early": queen_out_early,
            "rooks_connected": rooks_connected,
        }
    return result


# ─── 关键优势 ───
def _key_advantages_features(board: chess.Board) -> dict:
    result = {}
    for color, name in [(chess.WHITE, "white"), (chess.BLACK, "black")]:
        enemy = not color

        # 双象
        bishops = [sq for sq in chess.SQUARES
                   if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.BISHOP
                   and board.piece_at(sq).color == color]
        bishop_pair = len(bishops) >= 2
        enemy_bishop_pair = len([sq for sq in chess.SQUARES
                                if board.piece_at(sq) and board.piece_at(sq).piece_type == chess.BISHOP
                                and board.piece_at(sq).color == enemy]) >= 2

        # 开放线控制
        open_files_controlled = 0
        for f in range(8):
            has_pawn = any(
                board.piece_at(chess.square(f, r))
                and board.piece_at(chess.square(f, r)).piece_type == chess.PAWN
                for r in range(8)
            )
            if not has_pawn:
                own_heavy = sum(1 for r in range(8)
                               if (p := board.piece_at(chess.square(f, r)))
                               and p.color == color and p.piece_type in (chess.ROOK, chess.QUEEN))
                enemy_heavy = sum(1 for r in range(8)
                                 if (p := board.piece_at(chess.square(f, r)))
                                 and p.color == enemy and p.piece_type in (chess.ROOK, chess.QUEEN))
                if own_heavy > enemy_heavy:
                    open_files_controlled += 1

        # 马的前哨（深入敌阵且被兵保护）
        knight_outposts = 0
        for sq in chess.SQUARES:
            p = board.piece_at(sq)
            if p and p.color == color and p.piece_type == chess.KNIGHT:
                rank = chess.square_rank(sq)
                is_advanced = (rank >= 5) if color == chess.WHITE else (rank <= 2)
                if is_advanced:
                    # 检查是否有己方兵保护
                    protected = False
                    for protector_sq in board.attackers(color, sq):
                        pp = board.piece_at(protector_sq)
                        if pp and pp.piece_type == chess.PAWN:
                            protected = True
                    if protected:
                        knight_outposts += 1

        result[name] = {
            "bishop_pair": bishop_pair,
            "enemy_bishop_pair": enemy_bishop_pair,
            "open_files_controlled": open_files_controlled,
            "knight_outposts": knight_outposts,
        }
    return result


# ═══════════════════════════════════════════════════════════════
#  特征对比 + 诊断生成
# ═══════════════════════════════════════════════════════════════

def _side_name(is_white: bool) -> str:
    return "白方" if is_white else "黑方"


def _player_key(is_white: bool) -> str:
    return "white" if is_white else "black"


def _enemy_key(is_white: bool) -> str:
    return "black" if is_white else "white"


def compare_features(before: dict, after: dict, is_white: bool) -> list[dict]:
    """
    对比走棋前后的特征向量，检测所有有意义的变化。
    返回变化列表，每条有: {category, change_type, description, severity}
    """
    changes = []
    own = _player_key(is_white)
    enemy = _enemy_key(is_white)

    # === 1. 子力变化 ===
    mat_before = before["material"]
    mat_after = after["material"]
    mat_diff = mat_after[f"{own}_total"] - mat_before[f"{own}_total"]
    if mat_diff != 0:
        kind = "得子" if mat_diff > 0 else "弃子/丢子"
        changes.append({
            "category": "子力",
            "change_type": kind,
            "description": f"子力变化 {mat_diff:+d} 分",
            "severity": "high" if abs(mat_diff) >= 3 else ("medium" if abs(mat_diff) >= 1 else "low"),
        })

    # 检查具体兑换
    own_before = mat_before[f"{own}_pieces"]
    own_after = mat_after[f"{own}_pieces"]
    enemy_before = mat_before[f"{enemy}_pieces"]
    enemy_after = mat_after[f"{enemy}_pieces"]

    for piece_type in ["马", "象", "车", "后"]:
        own_loss = own_before.get(piece_type, 0) - own_after.get(piece_type, 0)
        enemy_loss = enemy_before.get(piece_type, 0) - enemy_after.get(piece_type, 0)
        if own_loss > 0 and enemy_loss > 0:
            if piece_type != enemy_loss:
                pass  # 不对等兑换不特别标注

    # === 2. 王安全变化 ===
    ks_before = before["king_safety"][own]
    ks_after = after["king_safety"][own]
    if ks_after["score"] < ks_before["score"]:
        reason_parts = []
        if ks_after["shield"] < ks_before["shield"]:
            reason_parts.append(f"兵盾从{ks_before['shield']}减为{ks_after['shield']}")
        if ks_after["nearby_attackers"] > ks_before["nearby_attackers"]:
            reason_parts.append(f"附近攻子增多({ks_before['nearby_attackers']}→{ks_after['nearby_attackers']})")
        if ks_after["open_files_near_king"] > ks_before["open_files_near_king"]:
            reason_parts.append("王前出现新开放线")
        changes.append({
            "category": "王安全",
            "change_type": "恶化",
            "description": f"王安全度下降 ({ks_before['score']}/10 → {ks_after['score']}/10): {'; '.join(reason_parts)}",
            "severity": "high" if ks_after["score"] <= 5 else "medium",
        })

    # 敌方王安全改善
    ks_enemy_before = before["king_safety"][enemy]
    ks_enemy_after = after["king_safety"][enemy]
    if ks_enemy_after["score"] > ks_enemy_before["score"] + 1:
        changes.append({
            "category": "王安全",
            "change_type": "对方改善",
            "description": f"对方王安全度提升 ({ks_enemy_before['score']}/10 → {ks_enemy_after['score']}/10)，削弱了我方进攻前景",
            "severity": "medium",
        })

    # === 3. 兵形变化 ===
    ps_before = before["pawn_structure"][own]
    ps_after = after["pawn_structure"][own]
    issues = []
    if ps_after["isolated"] > ps_before["isolated"]:
        issues.append(f"新增 {ps_after['isolated'] - ps_before['isolated']} 个孤兵")
    if ps_after["doubled"] > ps_before["doubled"]:
        issues.append(f"新增 {ps_after['doubled'] - ps_before['doubled']} 个叠兵")
    if ps_after["passed"] < ps_before["passed"]:
        issues.append("失去通路兵")
    if issues:
        changes.append({
            "category": "兵形",
            "change_type": "受损",
            "description": f"兵型恶化: {'; '.join(issues)}",
            "severity": "medium",
        })

    # 敌方兵形恶化
    enemy_ps_before = before["pawn_structure"][enemy]
    enemy_ps_after = after["pawn_structure"][enemy]
    enemy_ps_issues = []
    if enemy_ps_after["isolated"] < enemy_ps_before["isolated"]:
        enemy_ps_issues.append("对方孤兵被消除")
    if enemy_ps_after["doubled"] > enemy_ps_before["doubled"]:
        enemy_ps_issues.append(f"对方出现叠兵")
    if enemy_ps_issues:
        changes.append({
            "category": "兵形",
            "change_type": "对方变故",
            "description": f"对方兵型变化: {'; '.join(enemy_ps_issues)}",
            "severity": "low",
        })

    # === 4. 空间机动性变化 ===
    sm_before = before["space_mobility"]
    sm_after = after["space_mobility"]
    own_mob_before = sm_before[own]["mobility"]
    own_mob_after = sm_after[own]["mobility"]
    if own_mob_before > 0 and (own_mob_after - own_mob_before) / own_mob_before < -0.15:
        changes.append({
            "category": "机动性",
            "change_type": "下降",
            "description": f"己方机动性显著下降 ({own_mob_before} → {own_mob_after} 合法走法)",
            "severity": "medium",
        })

    own_cc_before = sm_before[own]["center_control"]
    own_cc_after = sm_after[own]["center_control"]
    if own_cc_before > 0 and (own_cc_after - own_cc_before) / own_cc_before < -0.25:
        changes.append({
            "category": "中心",
            "change_type": "放弃",
            "description": f"中心控制力明显下降 ({own_cc_before} → {own_cc_after})",
            "severity": "medium",
        })

    enemy_cc_after = sm_after[enemy]["center_control"]
    enemy_cc_before = sm_before[enemy]["center_control"]
    if enemy_cc_before > 0 and (enemy_cc_after - enemy_cc_before) / enemy_cc_before > 0.25:
        changes.append({
            "category": "中心",
            "change_type": "对方增强",
            "description": f"对方中心控制力增强 ({enemy_cc_before} → {enemy_cc_after})",
            "severity": "low",
        })

    # === 5. 出子变化 ===
    dev_before = before["development"][own]
    dev_after = after["development"][own]
    if dev_after["developed"] < dev_before["developed"]:
        changes.append({
            "category": "出子",
            "change_type": "回退",
            "description": "己方已出动轻子数减少（可能是不合时宜的子力调动）",
            "severity": "medium",
        })

    enemy_dev_before = before["development"][enemy]
    enemy_dev_after = after["development"][enemy]
    if enemy_dev_after["developed"] > enemy_dev_before["developed"]:
        changes.append({
            "category": "出子",
            "change_type": "对方领先",
            "description": f"对方出子进度领先 ({enemy_dev_before['developed']}→{enemy_dev_after['developed']} 个轻子)",
            "severity": "low",
        })

    if dev_before.get("castled") and not dev_after.get("castled"):
        changes.append({
            "category": "出子",
            "change_type": "失去易位权",
            "description": "失去易位权，王的位置暴露",
            "severity": "high",
        })

    if not dev_before.get("castled") and dev_after.get("castled"):
        changes.append({
            "category": "出子",
            "change_type": "完成易位",
            "description": "完成易位，王安全得到保障",
            "severity": "low",
        })

    # === 6. 关键优势变化 ===
    ka_before = before["key_advantages"][own]
    ka_after = after["key_advantages"][own]

    if ka_before.get("bishop_pair") and not ka_after.get("bishop_pair"):
        changes.append({
            "category": "子力配置",
            "change_type": "失去双象",
            "description": "失去双象优势，残局潜力下降",
            "severity": "medium",
        })

    if ka_before.get("open_files_controlled", 0) > ka_after.get("open_files_controlled", 0):
        changes.append({
            "category": "线路控制",
            "change_type": "丧失",
            "description": f"失去 {ka_before['open_files_controlled'] - ka_after['open_files_controlled']} 条开放线的控制权",
            "severity": "medium",
        })

    if ka_before.get("knight_outposts", 0) > ka_after.get("knight_outposts", 0):
        changes.append({
            "category": "子力配置",
            "change_type": "失去据点",
            "description": "失去马的前哨据点",
            "severity": "medium",
        })

    if ka_after.get("knight_outposts", 0) > ka_before.get("knight_outposts", 0):
        changes.append({
            "category": "子力配置",
            "change_type": "建立据点",
            "description": "马建立了强大的前哨据点！这在残局中价值巨大",
            "severity": "medium",
        })

    if ka_after.get("enemy_bishop_pair") and not ka_before.get("enemy_bishop_pair"):
        changes.append({
            "category": "子力配置",
            "change_type": "对方双象",
            "description": "让对方获得了双象优势，长期来看对己方不利",
            "severity": "medium",
        })

    return changes


def generate_diagnosis(
    changes: list[dict],
    score_diff: float,
    is_white: bool,
    move_san: str,
) -> str:
    """
    根据特征变化生成中文诊断报告。
    score_diff: 走棋方视角的评分变化（正值=改善，负值=恶化）
    """
    if not changes:
        return ""

    side = _side_name(is_white)
    direction = "恶化" if score_diff < 0 else "改善"
    abs_diff = abs(score_diff)

    # 按严重程度排序
    severity_order = {"high": 0, "medium": 1, "low": 2}
    changes_sorted = sorted(changes, key=lambda c: severity_order.get(c["severity"], 2))

    # 头部总结
    if abs_diff > 2.0:
        head = f"{side}走{move_san}后局面显著{direction}（评分变化 {score_diff:+.1f}），原因如下："
    elif abs_diff > 1.0:
        head = f"{side}走{move_san}后局面明显{direction}（{score_diff:+.1f}），主要因素："
    elif abs_diff > 0.3:
        head = f"{side}走{move_san}后局面略有{direction}（{score_diff:+.1f}）："
    else:
        head = f"{side}走{move_san}后局面基本持平（{score_diff:+.1f}）："

    # 逐条变化
    body_parts = []
    for change in changes_sorted:
        body_parts.append(f"• [{change['category']}] {change['description']}")

    return head + "\n" + "\n".join(body_parts)


def analyze(
    board_before: chess.Board,
    board_after: chess.Board,
    move: chess.Move,
    score_diff: float,
    is_white: bool,
) -> dict:
    """
    完整分析: 提取前后特征 → 对比变化 → 生成诊断。

    Returns:
        {
            "features_before": {...},
            "features_after": {...},
            "changes": [{...}],
            "diagnosis_zh": "...",
        }
    """
    move_san = board_before.san(move)
    features_before = extract_features(board_before)
    features_after = extract_features(board_after)
    changes = compare_features(features_before, features_after, is_white)
    diagnosis = generate_diagnosis(changes, score_diff, is_white, move_san)

    return {
        "features_before": features_before,
        "features_after": features_after,
        "changes": changes,
        "diagnosis_zh": diagnosis,
    }


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("局面特征可解释性模块 自测")
    print("=" * 60)

    # 测试1: 正常出子
    print("\n--- 测试1: 西班牙开局第3步 ---")
    board_before = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2")
    board_after = chess.Board("r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3")
    move = chess.Move.from_uci("f1b5")
    result = analyze(board_before, board_after, move, score_diff=0.1, is_white=True)
    print(f"诊断:\n{result['diagnosis_zh']}")
    print(f"变化条数: {len(result['changes'])}")

    # 测试2: 严重失误
    print("\n--- 测试2: 黑方送后 ---")
    bb2 = chess.Board("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1")
    ba2 = chess.Board("rnbqkbnr/ppppQppp/8/4p3/4P3/8/PPPP1PPP/RNB1KBNR b KQkq - 0 1")
    result2 = analyze(bb2, ba2, chess.Move.from_uci("d1h5"), score_diff=-9.0, is_white=True)
    print(f"诊断:\n{result2['diagnosis_zh']}")
    print(f"变化条数: {len(result2['changes'])}")

    # 测试3: 兵型受损
    print("\n--- 测试3: 形成叠兵 ---")
    bb3 = chess.Board("rnbqkb1r/pppp1ppp/4pn2/8/2PP4/2b5/PP2PPPP/R1BQKBNR w KQkq - 0 4")
    ba3 = chess.Board("rnbqkb1r/pppp1ppp/4pn2/8/2PP4/2P5/P3PPPP/R1BQKBNR b KQkq - 0 4")
    result3 = analyze(bb3, ba3, chess.Move.from_uci("b2c3"), score_diff=-0.6, is_white=True)
    print(f"诊断:\n{result3['diagnosis_zh']}")
    print(f"变化条数: {len(result3['changes'])}")

    # 测试4: 失去双象
    print("\n--- 测试4: 主动兑象失去双象 ---")
    bb4 = chess.Board("rnbqkb1r/pppp1ppp/4pn2/6B1/4P3/8/PPPP1PPP/RN1QKBNR w KQkq - 2 3")
    ba4 = chess.Board("rnbqkb1r/pppp1ppp/4pB2/8/4P3/8/PPPP1PPP/RN1QKBNR b KQkq - 0 3")
    result4 = analyze(bb4, ba4, chess.Move.from_uci("g5f6"), score_diff=-0.3, is_white=True)
    print(f"诊断:\n{result4['diagnosis_zh']}")
    print(f"变化条数: {len(result4['changes'])}")

    print(f"\n✅ 自测完成")