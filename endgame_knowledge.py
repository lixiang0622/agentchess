"""
残局知识分析模块 (Endgame Knowledge Analyzer)
在已有 tablebase.py 基础上深化残局分析：
  1. 判断是否进入残局阶段
  2. 分析残局走法是否为理论最佳着
  3. 对比引擎评分与表库判决（和棋/必胜）
  4. 生成教练式残局建议

用法:
    from endgame_knowledge import EndgameAnalyzer
    ea = EndgameAnalyzer()
    result = ea.analyze(board_before, board_after, move, tb_result, engine_score)
"""

import sys
import chess
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

# ─── 残局判断阈值 ───
ENDGAME_MAX_PIECES = 12       # 12子以下视为残局
TABLEBASE_MAX_PIECES = 7      # Syzygy 表库上限

# 棋子价值
PIECE_VALUES = {
    chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3,
    chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 0,
}

# 理论残局知识库
ENDGAME_THEORY = {
    "KPK": {
        "name": "王兵对王",
        "key_concepts": ["对王", "关键格", "正方形法则"],
        "win_condition": "进攻方王在兵前、占领关键格、有先手对王则为必胜",
        "draw_condition": "防守方王占据兵前方格、保持对王则为和棋",
    },
    "KRPKR": {
        "name": "车兵对车",
        "key_concepts": ["卢塞纳胜法", "菲利多尔守和法", "长侧面防守"],
        "win_condition": "强方用卢塞纳桥式建立掩体，迫使对方王离开底线",
        "draw_condition": "弱方用车从侧面/后方牵制、王守住底线",
    },
    "KQKP": {
        "name": "后对单兵",
        "key_concepts": ["后将军循环", "逼兵升变格"],
        "win_condition": "后在第七横排（对方底线前一排）的子力配合取胜",
        "draw_condition": "如果兵在c/f线第7横排且有王支持，有时可逼和",
    },
    "KBPK": {
        "name": "象兵对王",
        "key_concepts": ["象颜色", "角落封锁"],
        "win_condition": "通路兵升变格与象同色则必胜",
        "draw_condition": "升变格与象异色且防守方王占据升变格角落，则为理论必和",
    },
    "KRK": {
        "name": "车对单王",
        "key_concepts": ["限制范围", "逐步压缩", "底线将死"],
        "win_condition": "用车逐步限制对方王的活动范围，配合己方王推进将死",
        "draw_condition": "",
    },
    "KQK": {
        "name": "后对单王",
        "key_concepts": ["后-王配合将死", "避免逼和"],
        "win_condition": "后与王配合，逐步将对方王逼至底线/边线将死",
        "draw_condition": "注意避免逼和！后不能离对方王太近",
    },
}


def count_pieces(board: chess.Board) -> int:
    """计算棋盘上的棋子数（不包括王）"""
    n = 0
    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p and p.piece_type != chess.KING:
            n += 1
    # 加上两个王
    if board.king(chess.WHITE):
        n += 1
    if board.king(chess.BLACK):
        n += 1
    return n


def is_endgame(board: chess.Board) -> bool:
    """判断局面是否进入残局阶段（子力 ≤ 12 子）"""
    return count_pieces(board) <= ENDGAME_MAX_PIECES


def is_tablebase_range(board: chess.Board) -> bool:
    """判断局面是否在 Syzygy 表库范围内（≤ 7 子）"""
    return count_pieces(board) <= TABLEBASE_MAX_PIECES


def classify_endgame_material(board: chess.Board) -> list:
    """
    识别残局子力构成，返回匹配的理论残局类型列表。
    格式: ["KPK", "KRPKR", ...]
    """
    # 统计双方剩余子力
    pieces = {"Q": 0, "R": 0, "B": 0, "N": 0, "P": 0}
    w_pieces = {"Q": 0, "R": 0, "B": 0, "N": 0, "P": 0}
    b_pieces = {"Q": 0, "R": 0, "B": 0, "N": 0, "P": 0}

    for sq in chess.SQUARES:
        p = board.piece_at(sq)
        if p is None or p.piece_type == chess.KING:
            continue
        symbol = chess.piece_symbol(p.piece_type).upper()
        pieces[symbol] += 1
        if p.color == chess.WHITE:
            w_pieces[symbol] += 1
        else:
            b_pieces[symbol] += 1

    # 构建子力签名
    def material_sig(piece_dict):
        sig = "K"
        for sym in "QRBNP":
            n = piece_dict.get(sym, 0)
            if n > 0:
                sig += sym * n
        return sig

    result = []

    # 匹配已知残局类型
    # KPK: 只有兵
    if pieces == {"P": 1, "Q": 0, "R": 0, "B": 0, "N": 0}:
        result.append("KPK")

    # KRPKR: 各有1车，一方多1兵
    if (pieces.get("R", 0) == 2 and pieces.get("P", 0) == 1 and
        pieces.get("Q", 0) == 0 and pieces.get("B", 0) == 0 and pieces.get("N", 0) == 0):
        result.append("KRPKR")

    # KQKP: 一方有后，另一方有1兵
    if (pieces.get("Q", 0) == 1 and pieces.get("P", 0) == 1 and
        pieces.get("R", 0) == 0):
        result.append("KQKP")

    # KBPK: 一方有象+兵
    if (pieces.get("B", 0) == 1 and pieces.get("P", 0) == 1 and
        pieces.get("Q", 0) == 0 and pieces.get("R", 0) == 0 and pieces.get("N", 0) == 0):
        result.append("KBPK")

    # KRK: 一方只有车
    if (pieces.get("R", 0) == 1 and pieces.get("Q", 0) == 0 and pieces.get("B", 0) == 0 and
        pieces.get("N", 0) == 0 and pieces.get("P", 0) == 0):
        result.append("KRK")

    # KQK: 一方只有后
    if (pieces.get("Q", 0) == 1 and pieces.get("R", 0) == 0 and pieces.get("B", 0) == 0 and
        pieces.get("N", 0) == 0 and pieces.get("P", 0) == 0):
        result.append("KQK")

    # 对局未覆盖的特殊残局做描述
    sig_w = material_sig(w_pieces) + " vs " + material_sig(b_pieces)
    # 返回签名用于查找理论
    return result, sig_w


def get_endgame_theory(board: chess.Board) -> dict:
    """获取当前残局的已知理论知识"""
    types, sig = classify_endgame_material(board)
    theories = {}
    for t in types:
        if t in ENDGAME_THEORY:
            theories[t] = ENDGAME_THEORY[t]
    return {
        "matched_types": types,
        "material_signature": sig,
        "theories": theories,
        "total_pieces": count_pieces(board),
    }


def analyze_endgame_move(
    board_before: chess.Board,
    board_after: chess.Board,
    move: chess.Move,
    tb_result: dict = None,
    engine_score: float = None,
    is_white: bool = True,
) -> dict:
    """
    分析残局中的一步棋。

    Args:
        board_before: 走棋前局面
        board_after: 走棋后局面
        move: 实际走法
        tb_result: Syzygy 表库查询结果（如果有）
        engine_score: 引擎评分 (centipawn)
        is_white: 走棋方是否白方

    Returns:
        dict: {
            "is_endgame": bool,
            "is_tablebase_range": bool,
            "endgame_type": str,
            "theory_info": dict,
            "tb_verdict": str,
            "engine_vs_tb": str,  # 引擎与表库的对比
            "advice": str,        # 教练式建议
        }
    """
    result = {
        "is_endgame": is_endgame(board_before),
        "is_tablebase_range": is_tablebase_range(board_before),
        "endgame_type": "",
        "theory_info": {},
        "tb_verdict": "",
        "engine_vs_tb": "",
        "advice": "",
    }

    if not result["is_endgame"]:
        return result

    # 获取理论信息
    theory = get_endgame_theory(board_before)
    result["theory_info"] = theory
    types = theory.get("matched_types", [])
    if types:
        result["endgame_type"] = ", ".join(types)

    # 表库判决
    if tb_result:
        cat = tb_result.get("category", "unknown")
        side_name = "白方" if is_white else "黑方"

        if cat == "win" and is_white:
            result["tb_verdict"] = "白方理论必胜"
        elif cat == "loss" and is_white:
            result["tb_verdict"] = "白方理论必输"
        elif cat == "draw":
            result["tb_verdict"] = "理论必和"
        elif cat == "blessed_loss":
            result["tb_verdict"] = "理论必输（但实战极难证明，属于'受眷顾的败局'）"
        elif cat == "cursed_win":
            result["tb_verdict"] = "理论必胜（但需要超过50步不被吃子，实战中常被判和）"

        # 引擎 vs 表库对比
        if engine_score is not None and tb_result:
            result["engine_vs_tb"] = _compare_engine_vs_tb(engine_score, tb_result, is_white)

    # 生成教练式建议
    result["advice"] = _generate_endgame_advice(theory, tb_result, is_white)

    return result


def _compare_engine_vs_tb(engine_score: float, tb_result: dict, is_white: bool) -> str:
    """
    对比引擎评分与表库判决，检测"引擎看高分但表库说和棋"等矛盾。
    engine_score: 引擎评分（以白方视角的 centipawn 值）
    """
    cat = tb_result.get("category", "unknown")
    abs_score = abs(engine_score)

    # 引擎评分高但表库说是和棋
    if cat == "draw" and abs_score > 2.0:
        side = "白方" if engine_score > 0 else "黑方"
        return (
            f"⚠️ 重要矛盾！引擎评分显示{side}有{abs_score:+.1f}的优势，"
            f"但残局表库确认这是必和局面。{side}最有威胁的走法也只是表面优势，"
            f"只要对方精确防守，无法转化为胜利。"
        )

    # 引擎说劣势但表库说必胜
    if cat == "loss" and engine_score > 2.0 if is_white else engine_score < -2.0:
        return (
            "⚠️ 引擎和表库看法矛盾！表库认为此方理论可胜，"
            "但引擎没有看到获胜路径——这说明局面中存在深度赢棋路线。"
        )

    # 引擎和表库一致
    if (cat == "win" and engine_score > 0) or (cat == "draw" and abs_score < 1.5):
        return "引擎和表库判决一致 ✅"

    return ""


def _generate_endgame_advice(theory: dict, tb_result: dict, is_white: bool) -> str:
    """生成教练式残局建议"""
    parts = []
    side = "白方" if is_white else "黑方"
    enemy = "黑方" if is_white else "白方"

    # 理论建议
    theories = theory.get("theories", {})
    for t_name, t_info in theories.items():
        parts.append(f"【{t_info['name']}残局理论】")
        parts.append(f"核心概念: {', '.join(t_info['key_concepts'])}")
        if is_white:
            if tb_result and tb_result.get("category") == "win":
                parts.append(f"赢法: {t_info['win_condition']}")
            else:
                parts.append(f"白方: {t_info['win_condition']}")
                parts.append(f"黑方: {t_info['draw_condition']}")
        else:
            if tb_result and tb_result.get("category") == "loss":
                parts.append(f"输因: {t_info['win_condition']}")
            else:
                parts.append(f"白方: {t_info['win_condition']}")
                parts.append(f"黑方: {t_info['draw_condition']}")

    # 通用残局原则
    total = theory.get("total_pieces", 0)
    if total <= 6:
        parts.append("💡 已进入 6 子理论残局范围，每一步都可能决定胜负。")
        parts.append("   精确走法至关重要——此时不在乎'一般原则'而在乎'唯一正确着法'。")
    elif total <= 12:
        parts.append("💡 进入残局阶段，注意以下原则：")
        parts.append("   • 王的活动力 — 残局中王是最重要的进攻棋子")
        parts.append("   • 通路兵是金 — 创造并推进通路兵是第一要务")
        parts.append("   • 车的活跃 — 车在通路兵后方(己方)或侧翼最为活跃")

    # 表库精确判断
    if tb_result:
        dtz = tb_result.get("dtz")
        dtm = tb_result.get("dtm")
        if dtz is not None:
            parts.append(f"📊 DTZ (到转换步数): {dtz}")
        if dtm is not None:
            parts.append(f"🎯 DTM (到将死步数): {dtm}")

    return "\n".join(parts)


def generate_endgame_summary_for_prompt(analysis_results: list) -> str:
    """
    为 pipeline.py 的提示词生成残局分析摘要。
    传入所有 step 的 endgame_analysis 字段（非 None 的）。
    """
    lines = []
    engine_vs_tb_found = False

    for ar in analysis_results:
        if not ar or not ar.get("is_endgame"):
            continue

        move_num = ar.get("move_number", "?")
        eg_type = ar.get("endgame_type", "")

        if eg_type:
            lines.append(f"  第{move_num}步: 进入 {eg_type} 残局")
        if ar.get("tb_verdict"):
            lines.append(f"    表库判决: {ar['tb_verdict']}")
        if ar.get("engine_vs_tb"):
            lines.append(f"    {ar['engine_vs_tb']}")
            if "矛盾" in ar["engine_vs_tb"]:
                engine_vs_tb_found = True

    if not lines:
        return ""

    summary = "【残局深度分析，请据此生成权威的残局讲解】\n" + "\n".join(lines)

    if engine_vs_tb_found:
        summary += (
            "\n⚠️ 重要：上方标注了引擎与表库矛盾的步骤，"
            "请在讲解中重点强调'虽然引擎显示优势，但理论表库确认这是必和/必胜'，"
            "这是观众学习残局理论的最佳时刻！"
        )

    return summary


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("残局知识分析模块 自测")
    print("=" * 60)

    # 测试 1: KPK 残局
    print("\n--- 测试 1: KPK 王兵对王 ---")
    board1 = chess.Board("8/8/8/8/5k2/8/4P3/6K1 w - - 0 1")
    print(f"  棋子数: {count_pieces(board1)}")
    print(f"  是残局: {is_endgame(board1)}")
    print(f"  表库范围: {is_tablebase_range(board1)}")
    theory = get_endgame_theory(board1)
    print(f"  匹配类型: {theory['matched_types']}")
    if theory['theories']:
        t = theory['theories'].get('KPK', {})
        print(f"  理论知识: {t.get('key_concepts', [])}")

    # 测试 2: KRK 车对单王
    print("\n--- 测试 2: KRK 车对单王 ---")
    board2 = chess.Board("8/8/8/8/1k6/8/1K6/1R6 w - - 0 1")
    print(f"  棋子数: {count_pieces(board2)}")
    types2, sig2 = classify_endgame_material(board2)
    print(f"  匹配类型: {types2}")
    print(f"  子力签名: {sig2}")

    # 测试 3: 非残局
    print("\n--- 测试 3: 中局局面（非残局）---")
    board3 = chess.Board()
    print(f"  棋子数: {count_pieces(board3)}")
    print(f"  是残局: {is_endgame(board3)}")

    # 测试 4: 引擎 vs 表库对比
    print("\n--- 测试 4: 引擎 vs 表库对比 ---")
    tb_draw = {"category": "draw", "dtz": 5}
    compared = _compare_engine_vs_tb(3.5, tb_draw, True)
    print(f"  引擎+3.5 vs 表库说和棋: {compared}")

    tb_win = {"category": "win", "dtz": 12}
    compared2 = _compare_engine_vs_tb(2.0, tb_win, True)
    print(f"  引擎+2.0 vs 表库说必胜(白): {compared2}")

    # 测试 5: 综合分析
    print("\n--- 测试 5: 综合残局分析 ---")
    board_before = chess.Board("8/8/8/8/5k2/8/4P3/6K1 w - - 0 1")
    board_after = chess.Board("8/8/8/8/5k2/4P3/8/6K1 b - - 0 1")
    move = chess.Move.from_uci("e2e3")
    tb_fake = {"category": "draw", "dtz": 5, "dtm": None}
    result = analyze_endgame_move(
        board_before, board_after, move,
        tb_result=tb_fake, engine_score=2.5, is_white=True
    )
    print(f"  表库判决: {result['tb_verdict']}")
    print(f"  引擎vs表库: {result['engine_vs_tb']}")
    print(f"  建议: {result['advice'][:200]}...")

    print(f"\n✅ 自测完成")