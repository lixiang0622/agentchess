import sys
import chess
import chess.engine
import chess.pgn
import json
from pathlib import Path
from collections import Counter

# Force UTF-8 output in Windows terminals
sys.stdout.reconfigure(encoding="utf-8")

# Import new modules
from tactical_detector import TacticalDetector
from opening_explorer import OpeningExplorer
from tablebase import count_pieces, query_tablebase, format_tablebase_verdict
from concept_extractor import extract_concepts, generate_concept_summary, extract_turn_concepts
from critical_moment_detector import detect_critical_moments, generate_focus_guide
from strategic_mistake_detector import StrategicMistakeDetector
from endgame_knowledge import analyze_endgame_move, generate_endgame_summary_for_prompt
from master_games_db import query_master_moves
from branch_evaluator import evaluate_branch_trigger, apply_suppression_rules, generate_branch_guide_for_prompt
from opening_knowledge import get_kb
from position_explain import analyze as position_explain_analyze

# 1. 设置引擎路径
STOCKFISH_PATH = r"D:\国际象棋社团\agentchess\stockfish-windows-x86-64-avx2\stockfish\stockfish-windows-x86-64-avx2.exe"

# 2. 读取棋谱
PGN_PATH = Path(r"D:\国际象棋社团\agentchess\lichess_pgn_2026.05.05_pjykk_vs_lixiang23.bEHmt9NK.pgn")
if not PGN_PATH.exists():
    raise FileNotFoundError(f"PGN 文件不存在: {PGN_PATH}")

with PGN_PATH.open("r", encoding="utf-8") as pgn:
    game = chess.pgn.read_game(pgn)
board = game.board()

# 3. 启动引擎 + 战术检测器 + 开局探索器 + Lc0（可选）
engine = chess.engine.SimpleEngine.popen_uci(STOCKFISH_PATH)
explorer = OpeningExplorer()

# ====== Lc0 交叉验证引擎配置 ======
# Lc0 可执行文件保留在原目录（需要同目录下的 CUDA DLL 运行时）
# 权重文件必须放在纯 ASCII 路径（C++ 引擎不支持中文路径）
LCO_EXE_PATH = Path(r"D:\国际象棋社团\agentchess\lc0-v0.32.1-windows-gpu-nvidia-cuda12\lc0.exe")
LCO_WEIGHTS_PATH = Path(r"D:\lc0_data\weights_run2_912983.lc0")
LCO_ENABLE = True  # ← 启用 Lc0 双引擎交叉验证

lc0_engine = None
LCO_AVAILABLE = False

# 检查 Lc0 可执行文件和权重文件
if LCO_ENABLE and LCO_EXE_PATH.exists():
    if LCO_WEIGHTS_PATH.exists():
        try:
            lc0_engine = chess.engine.SimpleEngine.popen_uci(str(LCO_EXE_PATH))
            lc0_engine.configure({
                "WeightsFile": str(LCO_WEIGHTS_PATH),
                "LogFile": "",         # 不写日志
            })
            # Warmup: 让 GPU 预热（首次推理很慢）
            print("  预热 Lc0 GPU...")
            _warmup_board = chess.Board()
            lc0_engine.analyse(_warmup_board, chess.engine.Limit(nodes=10))
            LCO_AVAILABLE = True
            print(f"✓ Lc0 神经网络引擎已加载（交叉验证模式）")
            print(f"  可执行文件: {LCO_EXE_PATH}")
            print(f"  权重文件: {LCO_WEIGHTS_PATH}")
        except Exception as e:
            print(f"⚠ Lc0 引擎加载失败: {e}")
            print(f"  将仅使用 Stockfish 进行分析（不影响功能）")
            LCO_AVAILABLE = False
            lc0_engine = None
    else:
        print(f"⚠ Lc0 权重文件不存在: {LCO_WEIGHTS_PATH}")
        print(f"  请下载权重文件放在: {LCO_WEIGHTS_PATH.parent}")
else:
    if not LCO_ENABLE:
        print(f"ℹ Lc0 交叉验证已禁用（设置 LCO_ENABLE=True 启用）")
    elif not LCO_EXE_PATH.exists():
        print(f"⚠ Lc0 可执行文件不存在: {LCO_EXE_PATH}")
        print(f"  将仅使用 Stockfish 进行分析（不影响功能）")

# 收集开局数据
board_seq = []       # 每步走棋前的 board 副本（前12步）
moves_san_list = []  # 前12步的 SAN
board_seq_full = []  # 所有步的 board 副本（用于 Lc0 重放）

# ====== MultiPV 动态分析配置 ======
# 注意: python-chess >= 1.0 自动管理 MultiPV，只需在 analyse() 时传 multipv= 参数即可
MULTIPV = 3   # 每步查看前 3 个候选走法


def get_analysis_limit(board, is_critical=False):
    """动态分析深度：普通步快速掠过，失误步深度挖掘"""
    if is_critical:
        return chess.engine.Limit(time=2.0)
    if board.fullmove_number <= 10:
        return chess.engine.Limit(time=0.5)
    return chess.engine.Limit(time=0.3)


# ---- PGN 时钟数据提取（每步剩余时间，检测长考，支持加秒制）----
import re as _re

increment_per_move = 0
tc_header = game.headers.get("TimeControl", "")
tc_match = _re.match(r'\d+\+(\d+)', tc_header)
if tc_match:
    increment_per_move = int(tc_match.group(1))

clk_values = []
node = game
move_idx = 0
while node.variations:
    node = node.variations[0]
    move_idx += 1
    comment = node.comment if hasattr(node, 'comment') else ''
    clk_match = _re.search(r'\[%clk\s+([^\]]+)\]', comment)
    if clk_match:
        clk_str = clk_match.group(1).strip()
        parts = clk_str.split(':')
        try:
            if len(parts) == 3:
                secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(float(parts[2]))
            elif len(parts) == 2:
                secs = int(parts[0]) * 60 + int(float(parts[1]))
            else:
                secs = int(float(parts[0]))
            clk_values.append((secs, move_idx))
        except (ValueError, IndexError):
            pass

move_time_spent = {}
long_thinks = set()
if len(clk_values) >= 2:
    times = []
    for prev, curr in zip(clk_values[:-1], clk_values[1:]):
        spent = prev[0] - curr[0] + increment_per_move
        if spent > 0:
            move_time_spent[curr[1]] = spent
            times.append(spent)
    avg_time = sum(times) / len(times) if times else 0
    for mn, spent in move_time_spent.items():
        if spent > max(avg_time * 3, 30):
            long_thinks.add(mn)
    if long_thinks:
        print(f"  检测到 {len(long_thinks)} 步长考: {sorted(long_thinks)}")
    if increment_per_move > 0:
        print(f"  加秒制: +{increment_per_move}s/步, 平均耗时: {avg_time:.1f}s")

# 4. 主分析循环 — MultiPV 多变化分析
steps = []
prev_move = None
print("正在分析棋局（MultiPV=3，动态深度）...")

for move_number, move in enumerate(game.mainline_moves(), start=1):
    is_white_move = move_number % 2 == 1
    side = "白方" if is_white_move else "黑方"

    # ---- 第一步：走棋前浅度 MultiPV 分析 ----
    limit_before = get_analysis_limit(board, is_critical=False)
    multi_info = engine.analyse(board, limit_before, multipv=MULTIPV)

    best_info = multi_info[0]
    score_before = best_info["score"].white()
    score_before_cp = score_before.score()

    # 提取候选走法列表
    candidates = []
    best_move_san = ""
    for info in multi_info:
        if "pv" in info and len(info["pv"]) > 0:
            cand_san = board.san(info["pv"][0])
            if not best_move_san:
                best_move_san = cand_san
            # variation_san() 正确处理多步 PV，不会出现非法着法错误
            pv_str = board.variation_san(info["pv"][:5])
            candidates.append({
                "move": cand_san,
                "score_cp": info["score"].white().score(),
                "pv": pv_str,
            })

    # 实际走法
    move_san = board.san(move)

    # ---- 开局/战术/重放数据收集（走棋前）----
    if move_number <= 12:
        board_seq.append(board.copy())
        moves_san_list.append(move_san)
    board_before = board.copy()
    board_seq_full.append(board.copy())

    board.push(move)

    # ---- 第二步：走棋后浅度分析（只算评分差）----
    info_after = engine.analyse(board, chess.engine.Limit(time=0.15))
    score_after = info_after["score"].white()
    score_after_cp = score_after.score()
    score_diff = score_after_cp - score_before_cp

    # ---- 着法质量 7 级分类（借鉴 analyse-pgn 阈值体系）----
    # diff_from_perspective: 正值=本方的局面改善, 负值=恶化
    diff_from_perspective = score_diff if is_white_move else -score_diff
    abs_diff = abs(diff_from_perspective)
    
    # 检查己方是否处于明显劣势
    side_is_losing = (is_white_move and score_before_cp < -200) or (not is_white_move and score_before_cp > 200)
    
    if diff_from_perspective <= -300:
        # 评分暴跌 > 3.0
        if side_is_losing:
            quality = "送子"
        else:
            quality = "漏杀"
    elif diff_from_perspective <= -150:
        quality = "失误"
    elif diff_from_perspective <= -80:
        quality = "疑问"
    elif diff_from_perspective <= -20:
        quality = "缓着"
    elif diff_from_perspective <= 20:
        quality = "正常"
    elif diff_from_perspective <= 150:
        quality = "好棋"
    else:
        quality = "妙手"

    is_critical = quality in ("漏杀", "送子", "失误")

    # ---- 第三步：如果是失误，回退做深度 MultiPV 重分析 ----
    recommended = None
    if is_critical:
        board.pop()  # 撤销走法，回到走之前的状态
        deep_limit = get_analysis_limit(board, is_critical=True)
        try:
            deep_multi = engine.analyse(board, deep_limit, multipv=MULTIPV)

            # 找第一个不等于实际走法的推荐
            for info in deep_multi:
                if "pv" not in info or len(info["pv"]) == 0:
                    continue
                rec_san = board.san(info["pv"][0])
                if rec_san != move_san:
                    recommended = {
                        "move": rec_san,
                        "score_cp": info["score"].white().score(),
                        "pv": board.variation_san(info["pv"][:5]),
                    }
                    break

            if not recommended and deep_multi and "pv" in deep_multi[0]:
                rec_san = board.san(deep_multi[0]["pv"][0])
                recommended = {
                    "move": rec_san,
                    "score_cp": deep_multi[0]["score"].white().score(),
                    "pv": board.variation_san(deep_multi[0]["pv"][:5]),
                }

            # 同时更新走之前的候选（用深度分析结果）
            deep_candidates = []
            for info in deep_multi:
                if "pv" in info and len(info["pv"]) > 0:
                    deep_candidates.append({
                        "move": board.san(info["pv"][0]),
                        "score_cp": info["score"].white().score(),
                        "pv": board.variation_san(info["pv"][:5]),
                    })
            if deep_candidates:
                candidates = deep_candidates
                best_move_san = deep_candidates[0]["move"]

        except Exception:
            pass
        board.push(move)  # 恢复走法

    # ---- 战术主题检测 ----
    tactical_themes = TacticalDetector.detect(
        board_before=board_before,
        board_after=board,
        move=move,
        is_white=is_white_move,
        prev_move=prev_move,
        score_after=info_after["score"],
    )
    prev_move = move

    # ---- 局面型错误检测 ----
    strategic_mistakes = StrategicMistakeDetector.detect(
        board_before=board_before,
        board_after=board,
        move=move,
        is_white=is_white_move,
        move_number=move_number,
    )

    # ---- 大师对局数据库查询 ----
    masters_data = query_master_moves(board_before.fen(), move_san)
    if masters_data and masters_data.get("found"):
        masters_info = {
            "source": masters_data["source"],
            "total_games": masters_data["total_games"],
            "top_moves": masters_data.get("top_moves", [])[:3],
            "famous_example": masters_data.get("famous_example"),
            "deviation": masters_data.get("deviation", False),
        }
    else:
        masters_info = None

    # ---- 局面可解释性分析 ----
    explanation = position_explain_analyze(
        board_before=board_before,
        board_after=board,
        move=move,
        score_diff=score_diff/100,
        is_white=is_white_move,
    )

    # ---- 分支讲解触发评估 ----
    branch_result = evaluate_branch_trigger(
        {
            "move_number": move_number,
            "move_san": move_san,
            "score_diff": score_diff / 100,
            "quality": quality,
            "candidates": candidates,
            "recommended": recommended,
            "tactical_themes": tactical_themes,
            "masters": masters_info,
            "strategic_mistakes": strategic_mistakes,
        },
        board_before=board_before,
        audience="中级",
    )

    # ---- 组装数据 ----
    time_spent = move_time_spent.get(move_number, None)
    is_long_think = move_number in long_thinks
    step_data = {
        "move_number": move_number,
        "round": (move_number + 1) // 2,
        "side": side,
        "move_san": move_san,
        "score_before": score_before_cp / 100,
        "score_after": score_after_cp / 100,
        "score_diff": score_diff / 100,
        "quality": quality,
        "best_move_san": best_move_san,
        "is_best_move": (move_san == best_move_san),
        "candidates": candidates,
        "recommended": recommended,
        "tactical_themes": tactical_themes,
        "strategic_mistakes": strategic_mistakes,
        "masters": masters_info,
        "branch": branch_result,
        "explanation": {
            "diagnosis": explanation["diagnosis_zh"],
            "changes": explanation["changes"],
        },
        "time_spent_seconds": time_spent,
        "is_long_think": is_long_think,
    }
    steps.append(step_data)

    if move_number % 10 == 0:
        print(f"  已分析 {move_number} 步...")

engine.quit()
print(f"  分析完成: {len(steps)} 步")

# ---- 战略阶段分段识别 ----
# 以 4~6 步为窗口，根据评分趋势和战术密度将整盘棋分为战略阶段
print("\n" + "="*60)
print("📊 战略阶段分段识别")
print("="*60)

# 阶段边界检测算法：
# - 评分符号变化 → 优势转换点
# - 连续3步评分波动均值 > 1.0 → 战术激战区
# - 开局(前12步) / 中局 / 残局(棋子≤7) 大阶段

phases = []
current_phase = None
phase_counter = 0

for i, step in enumerate(steps):
    move_num = step["move_number"]
    score = step["score_after"]
    score_diff = step["score_diff"]
    themes = step.get("tactical_themes", [])

    # 大阶段判断
    if move_num <= 12:
        macro_phase = "开局"
    elif count_pieces(board_seq_full[i]) <= 12:
        macro_phase = "残局"
    else:
        macro_phase = "中局"

    # 评分趋势（相对于前一步）
    if i > 0:
        prev_score = steps[i-1]["score_after"]
        score_delta = score - prev_score
    else:
        score_delta = 0

    # 判断是否需要新阶段
    new_phase_needed = False
    reason = ""

    if current_phase is None:
        new_phase_needed = True
        reason = "对局开始"
    elif macro_phase != current_phase.get("macro_phase", ""):
        new_phase_needed = True
        reason = f"进入{macro_phase}阶段"
    elif i >= 1:
        # 检查评分符号变化
        prev_score_sign = 1 if steps[i-1]["score_after"] > 0.5 else (-1 if steps[i-1]["score_after"] < -0.5 else 0)
        curr_score_sign = 1 if score > 0.5 else (-1 if score < -0.5 else 0)
        if prev_score_sign != 0 and curr_score_sign != 0 and prev_score_sign != curr_score_sign:
            new_phase_needed = True
            reason = "优势转换"

        # 检查战术密度激增
        if i >= 2:
            recent_themes = sum(1 for s in steps[i-2:i+1] if s.get("tactical_themes"))
            if recent_themes >= 3:
                new_phase_needed = True
                reason = "战术密集区"

        # 连续评分波动超过阈值
        if i >= 3:
            recent_swings = [abs(steps[j]["score_diff"]) for j in range(i-2, i+1)]
            if sum(recent_swings) / 3 > 1.0:
                if current_phase is not None and current_phase.get("intensity") != "激战":
                    new_phase_needed = True
                    reason = "进入激战"

    if new_phase_needed:
        if current_phase is not None:
            current_phase["end_move"] = move_num - 1
            current_phase["steps_count"] = current_phase["end_move"] - current_phase["start_move"] + 1
            phases.append(current_phase)

        phase_counter += 1
        # 确定阶段强度
        intensity = "普通"
        if themes or abs(score_diff) > 1.0:
            intensity = "激战"
        elif macro_phase == "开局":
            intensity = "发展"

        current_phase = {
            "phase_id": phase_counter,
            "phase_name": f"第{phase_counter}阶段",
            "start_move": move_num,
            "end_move": None,
            "steps_count": 0,
            "macro_phase": macro_phase,
            "intensity": intensity,
            "start_reason": reason,
            "start_score": round(score, 1),
            "score_trend": [],
            "key_themes": [],
            "description": "",
        }

    # 更新当前阶段
    if current_phase is not None:
        current_phase["score_trend"].append(round(score, 1))
        for t in themes:
            t_type = t.get("type", "")
            if t_type and t_type not in current_phase["key_themes"]:
                current_phase["key_themes"].append(t_type)

# 关闭最后一个阶段
if current_phase is not None:
    current_phase["end_move"] = steps[-1]["move_number"] if steps else 0
    current_phase["steps_count"] = current_phase["end_move"] - current_phase["start_move"] + 1
    phases.append(current_phase)

# 为每个阶段生成描述
macro_labels = {"开局": "🏠 开局阶段", "中局": "⚔️ 中局阶段", "残局": "🏁 残局阶段"}
intensity_labels = {"发展": "平稳发展", "普通": "正常交锋", "激战": "激烈争夺"}

for ph in phases:
    start = ph["start_move"]
    end = ph["end_move"]
    macro = ph["macro_phase"]
    intensity = ph["intensity"]
    score_start = ph.get("start_score", 0)

    # 评分趋势
    trend = ph.get("score_trend", [])
    if len(trend) >= 2:
        if trend[-1] > trend[0] + 1.0:
            trend_desc = "白方优势扩大"
        elif trend[-1] < trend[0] - 1.0:
            trend_desc = "黑方获得主动权"
        else:
            trend_desc = "局面基本持平"
    else:
        trend_desc = ""

    # 战术主题
    themes_str = ""
    if ph.get("key_themes"):
        type_names = {"fork": "击双", "pin": "牵制", "skewer": "串击",
                      "discovered_attack": "闪击", "mate_threat": "杀棋威胁"}
        theme_labels = [type_names.get(t, t) for t in ph["key_themes"]]
        themes_str = f"，出现战术主题: {'、'.join(theme_labels)}"

    ph["description"] = (
        f"{macro_labels.get(macro, macro)}，{intensity_labels.get(intensity, intensity)}。"
        f"第{start}~{end}步，共{ph['steps_count']}步。{trend_desc}{themes_str}。"
    )

    # 将阶段信息写入对应的 step
    for step in steps:
        if ph["start_move"] <= step["move_number"] <= ph["end_move"]:
            step["phase"] = {
                "phase_id": ph["phase_id"],
                "phase_name": ph["phase_name"],
                "macro_phase": ph["macro_phase"],
                "intensity": ph["intensity"],
            }

    print(f"  {ph['description']}")

print(f"  共识别 {len(phases)} 个战略阶段")

# ---- 残局库查询 + 残局知识分析 ----
tb_results = []
endgame_analyses = []  # 收集用于生成摘要
if board_seq_full:
    print("\n" + "="*60)
    print("📚 Syzygy 残局库查询 + 残局知识分析")
    print("="*60)
    tb_count = 0
    eg_analysis_count = 0
    for i, step in enumerate(steps):
        b = board_seq_full[i] if i < len(board_seq_full) else None
        if b is None:
            continue
        is_white_move = step["move_number"] % 2 == 1

        # ---- 残局知识分析（≤12 子即触发）----
        from endgame_knowledge import is_endgame as eg_is_endgame
        if eg_is_endgame(b):
            tb_data = query_tablebase(b) if count_pieces(b) <= 7 else None
            eg_result = analyze_endgame_move(
                board_before=b,
                board_after=board_seq_full[i+1] if i+1 < len(board_seq_full) else b,
                move=chess.Move.from_uci("e2e4"),  # placeholder
                tb_result=tb_data,
                engine_score=step.get("score_before", 0) * 100,
                is_white=is_white_move,
            )
            step["endgame_analysis"] = eg_result
            eg_result_copy = dict(eg_result)
            eg_result_copy["move_number"] = step["move_number"]
            endgame_analyses.append(eg_result_copy)
            eg_analysis_count += 1

            # 仍保留原表库字段（兼容旧格式）
            if tb_data and tb_data.get("category") != "unknown":
                side = step["side"]
                verdict = format_tablebase_verdict(tb_data, side)
                step["tablebase"] = {
                    "category": tb_data.get("category"),
                    "dtz": tb_data.get("dtz"),
                    "dtm": tb_data.get("dtm"),
                    "verdict_text": verdict,
                }
                tb_count += 1
                tb_results.append({
                    "move_number": step["move_number"],
                    "piece_count": count_pieces(b),
                    "verdict": verdict,
                })

        # 保留原有的 ≤7 子非残局查询
        elif count_pieces(b) <= 7:
            tb_data = query_tablebase(b)
            if tb_data and tb_data.get("category") != "unknown":
                side = step["side"]
                verdict = format_tablebase_verdict(tb_data, side)
                step["tablebase"] = {
                    "category": tb_data.get("category"),
                    "dtz": tb_data.get("dtz"),
                    "dtm": tb_data.get("dtm"),
                    "verdict_text": verdict,
                }
                tb_count += 1
                print(f"  第{step['move_number']}步 {step['move_san']} ({count_pieces(b)}子): {verdict}")
                tb_results.append({
                    "move_number": step["move_number"],
                    "piece_count": count_pieces(b),
                    "verdict": verdict,
                })

    if tb_count == 0 and eg_analysis_count == 0:
        print("  对局未进入残局阶段")
    else:
        if tb_count > 0:
            print(f"  共查询 {tb_count} 个残局位置（表库）")
        if eg_analysis_count > 0:
            print(f"  共分析 {eg_analysis_count} 个残局步骤（知识库）")

# ---- 概念清单构建（chess-sandbox 12 概念体系 + 规则增强）----
CONCEPT_BANK = {
    "战术": {"击双/捉双": False, "牵制": False, "串击/透视": False,
             "闪击": False, "引离": False, "消除防御": False, "过门/中间着": False,
             "弃子": False, "底线弱点": False},
    "战略": {"开放线控制": False, "兵型弱点": False, "象的好坏": False,
             "马的前哨据点": False, "王的安全": False, "空间优势": False,
             "出子领先": False, "主动权": False},
    "局面": {"中心控制": False, "双象优势": False, "叠兵/孤兵": False,
             "通路兵": False, "兵风暴": False, "弱格": False},
}
type_to_concept = {
    "fork": "击双/捉双", "pin": "牵制", "skewer": "串击/透视",
    "discovered_attack": "闪击", "discovered_check": "闪击",
    "deflection": "引离", "zwischenzug": "过门/中间着", "mate_threat": "王的安全",
}
tactic_used, strategic_used, positional_used = set(), set(), set()

for i, step in enumerate(steps):
    for t in step.get("tactical_themes", []):
        c = type_to_concept.get(t.get("type", ""))
        if c:
            CONCEPT_BANK["战术"][c] = True; tactic_used.add(c)

    phase = step.get("phase", {})
    score, quality = step["score_after"], step["quality"]
    board_before = board_seq_full[i] if i < len(board_seq_full) else None

    # 出子领先 / 空间优势 / 王的安全 / 主动权 / 通路兵
    if phase.get("macro_phase") == "开局" and score > 0.8:
        CONCEPT_BANK["战略"]["出子领先"] = True; strategic_used.add("出子领先")
    if phase.get("macro_phase") == "中局" and score > 1.5:
        CONCEPT_BANK["战略"]["空间优势"] = True; CONCEPT_BANK["局面"]["中心控制"] = True
        strategic_used.add("空间优势"); positional_used.add("中心控制")
    if abs(step["score_diff"]) > 2.0:
        CONCEPT_BANK["战略"]["王的安全"] = True; strategic_used.add("王的安全")
    if i >= 2:
        scores = [steps[j]["score_after"] for j in range(i-2, i+1)]
        if len(set(1 if s > 0 else -1 for s in scores)) == 1 and abs(scores[-1] - scores[0]) > 1.0:
            CONCEPT_BANK["战略"]["主动权"] = True; strategic_used.add("主动权")
    if phase.get("macro_phase") == "残局":
        CONCEPT_BANK["局面"]["通路兵"] = True; positional_used.add("通路兵")

    # 弃子：材枓失衡 + 评分补偿
    if board_before and step.get("tactical_themes"):
        material_diff = 0
        for sq in chess.SQUARES:
            p = board_before.piece_at(sq)
            if p:
                v = {chess.PAWN:1, chess.KNIGHT:3, chess.BISHOP:3, chess.ROOK:5, chess.QUEEN:9}.get(p.piece_type, 0)
                material_diff += v if p.color == chess.WHITE else -v
        if abs(material_diff) >= 2 and abs(score) < 2.0:
            CONCEPT_BANK["战术"]["弃子"] = True; tactic_used.add("弃子")

    # 底线弱点：底线王且前无逃脱格
    if board_before:
        for color in [chess.WHITE, chess.BLACK]:
            king_sq = board_before.king(color)
            if king_sq and chess.square_rank(king_sq) == (0 if color == chess.WHITE else 7):
                could_escape = any(
                    board_before.piece_at(chess.square(f, chess.square_rank(king_sq)+(1 if color==chess.WHITE else -1))) is None
                    for f in range(max(0, chess.square_file(king_sq)-1), min(8, chess.square_file(king_sq)+2))
                )
                if not could_escape and score > 1.5:
                    CONCEPT_BANK["战术"]["底线弱点"] = True; tactic_used.add("底线弱点")

    # 马的前哨据点
    if board_before:
        for color in [chess.WHITE, chess.BLACK]:
            for sq in chess.SQUARES:
                p = board_before.piece_at(sq)
                if p and p.piece_type == chess.KNIGHT and p.color == color:
                    rank = chess.square_rank(sq)
                    if (rank >= 4 and color == chess.WHITE) or (rank <= 3 and color == chess.BLACK):
                        CONCEPT_BANK["战略"]["马的前哨据点"] = True; strategic_used.add("马的前哨据点")
                        break
            if "马的前哨据点" in strategic_used: break

    if quality in ("送子", "漏杀"):
        CONCEPT_BANK["战术"]["消除防御"] = True; tactic_used.add("消除防御")

concept_parts = ["【本局涉及的关键棋局概念，自然融入讲解】"]
if tactic_used: concept_parts.append(f"战术: {', '.join(sorted(tactic_used))}")
if strategic_used: concept_parts.append(f"战略: {', '.join(sorted(strategic_used))}")
if positional_used: concept_parts.append(f"局面: {', '.join(sorted(positional_used))}")

concept_profile = {
    "tactic_concepts": sorted(tactic_used),
    "strategic_concepts": sorted(strategic_used),
    "positional_concepts": sorted(positional_used),
    "summary": "\n".join(concept_parts),
}

# ---- 战略概念提取（chess-sandbox 风格：王安全、开放线、空间、兵形）----
print("\n" + "="*60)
print("🧠 战略概念提取 — 中局 & 终局关键位置")
print("="*60)

try:
    # 取几个关键位置进行战略分析
    total_moves = len(steps)
    key_positions = {}

    # 开局后（约第 10-12 步）
    if total_moves >= 10:
        mid_board = board_seq_full[min(10, len(board_seq_full) - 1)]
        prof = extract_concepts(mid_board)
        key_positions["opening"] = {
            "move_number": 10,
            "fen": mid_board.fen(),
            "summary": generate_concept_summary(prof),
            "space": prof["space"]["advantage"],
        }

    # 中局（约半程位置）
    if total_moves >= 20:
        mid_idx = total_moves // 2
        if mid_idx < len(board_seq_full):
            mid_board = board_seq_full[mid_idx]
            prof = extract_concepts(mid_board)
            key_positions["middlegame"] = {
                "move_number": mid_idx + 1,
                "fen": mid_board.fen(),
                "summary": generate_concept_summary(prof),
                "space": prof["space"]["advantage"],
            }

    # 终局（最后几步）
    if len(board_seq_full) > 0:
        end_board = board_seq_full[-1]
        prof = extract_concepts(end_board)
        key_positions["endgame"] = {
            "move_number": total_moves,
            "fen": end_board.fen(),
            "summary": generate_concept_summary(prof),
            "space": prof["space"]["advantage"],
            "material": prof["material"]["imbalance"],
        }

    # 合并到 concept_profile
    concept_profile["key_positions"] = key_positions

    # 追加战略概念到 summary
    all_summaries = [s["summary"] for s in key_positions.values()
                     if s["summary"] != "局面大致均衡，无明显战略特征。"]
    if all_summaries:
        concept_profile["summary"] += "\n\n" + "\n\n".join(
            f"【第{s['move_number']}步】\n{s['summary']}"
            for s in key_positions.values()
            if s["summary"] != "局面大致均衡，无明显战略特征。"
        )

    # 每步附加走棋方的概念提示
    step_concept_hints = []
    for idx, step in enumerate(steps):
        if idx < len(board_seq_full):
            turn_concepts = extract_turn_concepts(board_seq_full[idx])
            if turn_concepts["key_points"]:
                step["concept_hint"] = "；".join(turn_concepts["key_points"])
    print(f"  ✓ 已为 {len(step_concept_hints)} 步添加概念提示")
    print(f"  ✓ 关键局面: {list(key_positions.keys())}")
except Exception as e:
    print(f"  ⚠ 战略概念提取失败: {e}")
    concept_profile["key_positions"] = {}

# ---- Lc0 交叉验证（对关键步骤重分析）----
if LCO_AVAILABLE and lc0_engine and steps:
    print("\n" + "="*60)
    print("🔬 Lc0 交叉验证 — 对关键位置进行神经网络重分析")
    print("="*60)

    # ---- 识别关键位置 ----
    # 算法：标记满足以下任一条件的步骤为关键位置：
    # 1. 评分波动大: |score_diff| > 1.5 (相当于 150 centipawns)
    # 2. 战术主题: 有 detection 主题
    # 3. 关键转折: 相邻 3 步内评分波动超过 2 次
    # 4. 交替失误: 同一回合双方先后出现"错误"级走法

    critical_indices = set()

    for i, step in enumerate(steps):
        # 条件 1: 大评分波动
        if abs(step["score_diff"]) > 1.5:
            critical_indices.add(i)

        # 条件 2: 有战术主题
        if step.get("tactical_themes"):
            critical_indices.add(i)

    # 条件 3: 关键转折点 — 滑动窗口检测密集评分波动
    for i in range(len(steps) - 2):
        window = steps[i:i+3]
        swings = sum(1 for s in window if abs(s["score_diff"]) > 1.0)
        if swings >= 2:
            for j in range(i, i+3):
                critical_indices.add(j)

    # 条件 4: 交替失误 — 同一回合双方先后失误
    for i in range(len(steps) - 1):
        curr = steps[i]
        next_s = steps[i+1]
        if (curr["round"] == next_s["round"] and
            curr["quality"] in ("漏杀", "送子", "失误") and
            next_s["quality"] in ("漏杀", "送子", "失误")):
            critical_indices.add(i)
            critical_indices.add(i+1)

    # 按步号排序
    critical_steps = sorted([steps[i] for i in critical_indices], key=lambda s: s["move_number"])

    print(f"  识别到 {len(critical_steps)} 个关键位置需要交叉验证：")
    for cs in critical_steps:
        reasons = []
        if abs(cs["score_diff"]) > 1.5:
            reasons.append(f"评分波动 {cs['score_diff']:+.1f}")
        if cs.get("tactical_themes"):
            names = [t["type"] for t in cs["tactical_themes"]]
            reasons.append(f"战术: {', '.join(names)}")
        if cs["quality"] in ("漏杀", "送子", "失误"):
            reasons.append(f"着法质量: {cs['quality']}")
        print(f"    第{cs['move_number']}步 {cs['move_san']} — {'; '.join(reasons)}")

    lc0_analysis_count = 0
    lc0_crashed = False  # 跟踪引擎是否已崩溃
    
    for step in critical_steps:
        if lc0_crashed:
            break  # 引擎已崩溃，跳过后续分析
            
        idx = step["move_number"] - 1  # 0-indexed
        if idx >= len(board_seq_full):
            continue

        bboard = board_seq_full[idx]

        # Lc0 分析 (10 秒)
        lc0_time = 10.0
        print(f"  Lc0 第{step['move_number']}步 {step['move_san']}... ", end="", flush=True)
        try:
            lc0_info = lc0_engine.analyse(bboard, chess.engine.Limit(time=lc0_time))
            if "score" not in lc0_info:
                print(f"Lc0 无分数 (keys: {list(lc0_info.keys())[:5]})")
                continue

            lc0_score = lc0_info["score"].white()
            lc0_score_cp = lc0_score.score() / 100.0
            sf_score = step["score_after"]
            diff_cp = abs(sf_score - lc0_score_cp)

            # ---- 分歧类型分类 ----
            sf_sign = 1 if sf_score > 0 else (-1 if sf_score < 0 else 0)
            lc0_sign = 1 if lc0_score_cp > 0 else (-1 if lc0_score_cp < 0 else 0)

            if sf_sign != lc0_sign or diff_cp > 2.0:
                disagree_type = "disagree_strong"
            elif diff_cp > 1.0:
                disagree_type = "disagree_mild"
            elif lc0_score_cp > sf_score + 2.0:
                disagree_type = "lc0_surprise"
            else:
                disagree_type = "agree"

            # ---- 生成中文分歧描述 ----
            type_descriptions = {
                "agree": (
                    f"Stockfish 和 Lc0 一致认为局面评分为 {sf_score:+.1f}，"
                    f"两个引擎都同意这一评估。"
                ),
                "disagree_mild": (
                    f"传统引擎 Stockfish 和神经网络 Lc0 对局面看法略有不同："
                    f"Stockfish 认为评分为 {sf_score:+.1f}，"
                    f"而 Lc0 认为评分为 {lc0_score_cp:+.1f}，"
                    f"相差 {diff_cp:.1f} 分。这在复杂中局中很常见，"
                    f"意味着局面有动态因素存在。"
                ),
                "disagree_strong": (
                    f"⚠️ 引擎分歧！Stockfish 认为白方评分为 {sf_score:+.1f}，"
                    f"而 Lc0 神经网络认为评分为 {lc0_score_cp:+.1f}，"
                    f"相差 {diff_cp:.1f} 分！两个引擎的看法完全不同，"
                    f"这说明局面非常复杂，适合深入讨论。"
                    f"这往往是经典的静态评价与动态补偿之争！"
                ),
                "lc0_surprise": (
                    f"有意思！Lc0 神经网络比 Stockfish 更看好当前局面："
                    f"Stockfish 评分为 {sf_score:+.1f}，"
                    f"但 Lc0 认为评分为 {lc0_score_cp:+.1f}。"
                    f"神经网络可能看到了 Stockfish 忽略的动态补偿或隐藏潜力。"
                ),
            }
            dis_desc = type_descriptions.get(disagree_type, type_descriptions["agree"])

            step["cross_validation"] = {
                "stockfish_score": round(sf_score, 1),
                "lc0_score": round(lc0_score_cp, 1),
                "lc0_analysis_time": f"{lc0_time:.1f}s",
                "disagreement_type": disagree_type,
                "disagreement_description": dis_desc,
            }

            lc0_analysis_count += 1
            disagree_label = {
                "agree": "一致",
                "disagree_mild": "轻微分歧",
                "disagree_strong": "强烈分歧",
                "lc0_surprise": "Lc0 惊喜",
            }.get(disagree_type, "未知")
            print(f"SF={sf_score:+.1f} vs Lc0={lc0_score_cp:+.1f} [{disagree_label}]")

        except (chess.engine.EngineTerminatedError, ConnectionError, TimeoutError) as e:
            print(f"Lc0 引擎已终止: {e}")
            lc0_crashed = True
            try:
                lc0_engine.quit()
            except Exception:
                pass
            lc0_engine = None
            break
        except Exception as e:
            print(f"分析失败: {e}")

    if lc0_engine:
        try:
            lc0_engine.quit()
        except Exception:
            pass
        lc0_engine = None

    if lc0_crashed:
        print(f"\n  ⚠ Lc0 引擎中途崩溃，仅完成 {lc0_analysis_count}/{len(critical_steps)} 个关键位置")
    else:
        print(f"\n  Lc0 交叉验证完成: {lc0_analysis_count}/{len(critical_steps)} 个关键位置已分析")
elif not LCO_AVAILABLE:
    print("\n⚠ Lc0 不可用，跳过交叉验证")

# ---- 开局数据库深度分析 ----
opening_profile = {}
if board_seq:
    opening_profile = explorer.build_opening_profile(
        board_seq, moves_san_list, top_n=min(12, len(board_seq))
    )

# 5. 输出结构化数据
print("\n" + "="*60)
print("分析结果（结构化数据）")
print("="*60)

# ---- 开局概要 ----
if opening_profile.get("opening_name"):
    print(f"\n开局: {opening_profile['opening_name']}")
    print(f"  ECO: {opening_profile['eco']}")
    if opening_profile.get("total_games", 0) > 0:
        print(f"  数据库: {opening_profile['total_games']:,} 盘对局")

# ---- 着法质量统计 ----
quality_counts = Counter(s["quality"] for s in steps)
print("\n着法质量统计:")
for q in ["妙手", "好棋", "正常", "缓着", "疑问", "失误", "漏杀", "送子"]:
    count = quality_counts.get(q, 0)
    bar = "█" * count
    print(f"  {q}: {count:>3} {bar}")

# ---- 战术主题统计 ----
tactical_counts = Counter()
for step in steps:
    for theme in step.get("tactical_themes", []):
        tactical_counts[theme["type"]] += 1
if tactical_counts:
    print("\n战术主题统计:")
    type_names = {
        "fork": "击双", "pin": "牵制", "skewer": "串击",
        "discovered_attack": "闪击", "discovered_check": "闪将",
        "deflection": "引离", "zwischenzug": "中间着",
        "mate_threat": "杀棋威胁",
    }
    for t, count in tactical_counts.most_common():
        name = type_names.get(t, t)
        print(f"  {name}: {count} 次")
print()

# ---- 打印所有着法（含战术标注）----
for step in steps:
    quality = step["quality"]
    round_num = step["round"]
    side = step["side"]
    move = step["move_san"]
    before = step["score_before"]
    after = step["score_after"]
    diff = step["score_diff"]
    best = step["best_move_san"]
    themes = step.get("tactical_themes", [])

    icon = {"妙手": "⭐", "好棋": "👍", "正常": "  ", "缓着": "➖",
            "疑问": "❓", "失误": "⚠️", "漏杀": "🔍", "送子": "💀"}

    # 战术标注
    tactical_label = ""
    if themes:
        type_names_short = {
            "fork": "击双", "pin": "牵制", "skewer": "串击",
            "discovered_attack": "闪击", "discovered_check": "闪将",
            "deflection": "引离", "zwischenzug": "中间着",
            "mate_threat": "杀棋",
        }
        labels = [type_names_short.get(t["type"], t["type"]) for t in themes]
        tactical_label = f"  🎯 {' + '.join(labels)}"

    # 交叉验证标记
    cv = step.get("cross_validation")
    cv_label = ""
    if cv:
        dtype = cv["disagreement_type"]
        if dtype == "disagree_strong":
            cv_label = f"  🔴 Lc0分歧 (SF={cv['stockfish_score']:+.1f} vs Lc0={cv['lc0_score']:+.1f})"
        elif dtype == "disagree_mild":
            cv_label = f"  🟡 Lc0微歧 (SF={cv['stockfish_score']:+.1f} vs Lc0={cv['lc0_score']:+.1f})"
        elif dtype == "lc0_surprise":
            cv_label = f"  🟢 Lc0惊喜 (SF={cv['stockfish_score']:+.1f} vs Lc0={cv['lc0_score']:+.1f})"

    print(f"{icon.get(quality, '  ')} 第{round_num:>2}回合 {side}: {move:<10s}  "
          f"{before:+6.1f}→{after:+6.1f} ({diff:+6.1f})  [{quality}]{tactical_label}{cv_label}")
    if best and best != move:
        print(f"     推荐: {best}")
    # 显示候选走法
    candidates = step.get("candidates", [])
    if candidates and len(candidates) > 1:
        cand_str = " ".join(
            f"{c['move']}({c['score_cp']/100:+.1f})" for c in candidates[:3]
        )
        print(f"     候选: {cand_str}")

# ---- 关键教学节点检测 ----
print("\n" + "="*60)
print("🎯 关键教学节点检测 — GothamChess 风格聚焦")
print("="*60)
critical_result = detect_critical_moments(steps, opening_profile, phases, top_n=8)
print(f"  关键时刻 ({critical_result['distribution']['critical']} 步): "
      f"{', '.join(str(m) for m in critical_result['critical_moves'])}")
print(f"  值得注意 ({critical_result['distribution']['notable']} 步): "
      f"{', '.join(str(m) for m in critical_result['notable_moves'])}")
print(f"  常规走法: {critical_result['distribution']['routine']} 步")

# ---- 分支讲解触发评估 & 抑制规则 ----
print("\n" + "="*60)
print("🌿 分支讲解触发评估")
print("="*60)
branch_results_all = []
for step in steps:
    branch_results_all.append({
        "move_number": step["move_number"],
        "branch_result": step.get("branch", {"should_show": False}),
        "step": step,
    })
branch_results_all = apply_suppression_rules(branch_results_all, "中级")
# 将抑制后的结果写回 steps
for br_item in branch_results_all:
    mn = br_item["move_number"]
    for step in steps:
        if step["move_number"] == mn:
            step["branch"] = br_item["branch_result"]
            break
showing_count = sum(
    1 for s in steps if s.get("branch", {}).get("should_show")
)
print(f"  分支展示: {showing_count} 处")
branch_guide = generate_branch_guide_for_prompt(branch_results_all)
if showing_count > 0:
    # 打印前几处
    for s in steps:
        br = s.get("branch", {})
        if br.get("should_show"):
            print(f"    第{s['move_number']}步 [{br.get('primary_trigger', '?')}]: {'; '.join(br.get('reasons', []))}")
print()

# ---- 开局知识库匹配 ----
opening_knowledge_entry = None
opening_knowledge_text = ""
if moves_san_list:
    try:
        kb = get_kb()
        opening_knowledge_entry = kb.match(moves_san_list)
        if opening_knowledge_entry:
            opening_knowledge_text = kb.build_prompt_context(opening_knowledge_entry)
            print(f"\n📖 开局知识库匹配: {opening_knowledge_entry.get('name', '')} ({opening_knowledge_entry.get('eco_code', '')})")
    except Exception as e:
        print(f"\n  ⚠ 开局知识库匹配失败: {e}")

# ---- 保存为 JSON（新结构）----
output_path = Path(__file__).with_stem("analysis_result").with_suffix(".json")
output = {
    "opening_profile": opening_profile,
    "opening_knowledge": {
        "entry": opening_knowledge_entry,
        "prompt_context": opening_knowledge_text,
    },
    "phases": phases,
    "tablebase_results": tb_results,
    "endgame_analyses": endgame_analyses,
    "branch_guide": branch_guide,
    "concept_profile": concept_profile,
    "critical_moments": {
        "distribution": critical_result["distribution"],
        "critical_moves": critical_result["critical_moves"],
        "notable_moves": critical_result["notable_moves"],
        "teaching_arc": critical_result["teaching_arc"],
        "focus_guide": generate_focus_guide(critical_result),
    },
    "steps": steps,
}
with output_path.open("w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)
print(f"\n完整数据已保存到: {output_path}")
print(f"  结构: {{opening_profile, steps[{len(steps)} 步]}}")