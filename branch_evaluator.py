"""
分支讲解触发系统 (Branch Evaluator)
自动判断每一步是否需要在右下角小棋盘中展示支线变化。

7 种触发条件:
  MISTAKE          — 评分骤降（失误/疑问手）
  MULTICHOICE      — MultiPV 多个候选评分接近
  MASTERS_DEVIATION— 实战偏离大师主流
  TACTIC_DETECTED  — 检测到战术主题
  OPENING_DEVIATION— 开局阶段偏离理论
  TABLEBASE_CRITICAL— 残局表库关键位置
  STRATEGIC_MISTAKE — 局面型错误

抑制规则:
  - 每局支线 ≤ 5 处
  - 连续触发时只选评分波动最大的
  - 观众级别控制深度

用法:
    from branch_evaluator import evaluate_branch_trigger
    branch = evaluate_branch_trigger(step, board_before, audience="中级")
"""

import sys
import chess

sys.stdout.reconfigure(encoding="utf-8")

# ─── 观众级别阈值 ───
LEVEL_THRESHOLDS = {
    "初级": {
        "mistake_diff": 1.5,      # 评分差 > 1.5 才触发
        "multichoice_gap": 0.15,  # 候选间差距 < 0.15
        "max_lines": 1,           # 最多展示 1 个变化
    },
    "中级": {
        "mistake_diff": 0.8,
        "multichoice_gap": 0.3,
        "max_lines": 2,
    },
    "高级": {
        "mistake_diff": 0.5,
        "multichoice_gap": 0.5,
        "max_lines": 3,
    },
}

# ─── 全局限制 ───
MAX_BRANCHES_PER_GAME = 5        # 每局最多几处支线
CONSECUTIVE_WINDOW = 3           # 连续触发窗口
STRATEGIC_MISTAKE_TYPES = {
    "bad_bishop_for_knight", "pawn_structure_damage", "center_abandonment",
    "bishop_pair_loss", "king_shield_damage", "open_file_loss", "development_lag",
}


def evaluate_branch_trigger(
    step: dict,
    board_before: chess.Board,
    audience: str = "中级",
) -> dict:
    """
    评估一步棋是否需要小棋盘支线展示。

    Args:
        step: 分析步骤数据
        board_before: 走棋前局面
        audience: 观众级别 ("初级" / "中级" / "高级")

    Returns:
        {
            "should_show": bool,
            "reasons": [str],
            "primary_trigger": str,   # 主要触发条件
            "lines": [ {label, moves, description}, ... ],
            "suppression_note": str,  # 如果被抑制，说明原因
        }
    """
    thresholds = LEVEL_THRESHOLDS.get(audience, LEVEL_THRESHOLDS["中级"])
    max_lines = thresholds.get("max_lines", 2)
    reasons = []
    triggers = []

    # ═══════════════════════════════════════════════
    #  条件 1: MISTAKE — 评分骤降
    # ═══════════════════════════════════════════════
    score_diff = abs(step.get("score_diff", 0))
    quality = step.get("quality", "正常")
    if quality in ("失误", "漏杀", "送杀", "送子") or score_diff > thresholds["mistake_diff"]:
        triggers.append({
            "code": "MISTAKE",
            "priority": 50,
            "reason": f"评分波动 {score_diff:+.1f} — {quality}",
        })

    # ═══════════════════════════════════════════════
    #  条件 2: MULTICHOICE — 多候选接近
    # ═══════════════════════════════════════════════
    candidates = step.get("candidates", [])
    if len(candidates) >= 2:
        s0 = abs(candidates[0].get("score_cp", 0))
        s1 = abs(candidates[1].get("score_cp", 0))
        if abs(s0 - s1) / 100.0 < thresholds["multichoice_gap"]:
            triggers.append({
                "code": "MULTICHOICE",
                "priority": 30,
                "reason": f"多个候选走法评分接近 ({candidates[0].get('move','?')}={s0/100:+.1f} vs {candidates[1].get('move','?')}={s1/100:+.1f})",
            })

    # ═══════════════════════════════════════════════
    #  条件 3: MASTERS_DEVIATION — 偏离大师主流
    # ═══════════════════════════════════════════════
    masters = step.get("masters")
    if masters and masters.get("deviation"):
        triggers.append({
            "code": "MASTERS_DEVIATION",
            "priority": 35,
            "reason": f"偏离大师主流走法（频率<10%）",
        })

    # ═══════════════════════════════════════════════
    #  条件 4: TACTIC_DETECTED — 战术主题
    # ═══════════════════════════════════════════════
    themes = step.get("tactical_themes", [])
    if themes:
        theme_types = [t.get("type", "?") for t in themes]
        # 高价值战术: 击双(fork)、闪击(discovered_attack)、杀棋(mate_threat)
        high_value = {"fork", "discovered_attack", "discovered_check", "mate_threat",
                      "deflection", "zwischenzug"}
        is_high = any(t in high_value for t in theme_types)
        triggers.append({
            "code": "TACTIC_DETECTED",
            "priority": 45 if is_high else 25,
            "reason": f"战术主题: {', '.join(theme_types)}",
        })

    # ═══════════════════════════════════════════════
    #  条件 5: OPENING_DEVIATION — 开局偏离理论
    # ═══════════════════════════════════════════════
    move_num = step.get("move_number", 0)
    if move_num <= 15:
        # 检查是否是有风险的走法（不在开局候选前3中）
        cands = step.get("candidates", [])
        move_san = step.get("move_san", "")
        if cands and move_san:
            top3 = [c["move"] for c in cands[:3]]
            if move_san not in top3:
                triggers.append({
                    "code": "OPENING_DEVIATION",
                    "priority": 25,
                    "reason": f"开局走法 {move_san} 不在引擎前3候选",
                })

    # ═══════════════════════════════════════════════
    #  条件 6: TABLEBASE_CRITICAL — 残局表库关键
    # ═══════════════════════════════════════════════
    tb = step.get("tablebase")
    eg = step.get("endgame_analysis", {})
    if tb and tb.get("category") in ("win", "loss"):
        triggers.append({
            "code": "TABLEBASE_CRITICAL",
            "priority": 40,
            "reason": f"表库关键位置: {tb.get('verdict_text', '')}",
        })
    if eg and eg.get("engine_vs_tb") and "矛盾" in eg.get("engine_vs_tb", ""):
        triggers.append({
            "code": "TABLEBASE_CRITICAL",
            "priority": 55,
            "reason": f"引擎vs表库矛盾: {eg['engine_vs_tb'][:60]}",
        })

    # ═══════════════════════════════════════════════
    #  条件 7: STRATEGIC_MISTAKE — 局面型错误
    # ═══════════════════════════════════════════════
    sms = step.get("strategic_mistakes", [])
    if sms:
        sm_types = [sm["type"] for sm in sms]
        is_moderate = any(sm.get("severity") == "moderate" for sm in sms)
        triggers.append({
            "code": "STRATEGIC_MISTAKE",
            "priority": 35 if is_moderate else 20,
            "reason": f"局面型错误: {', '.join(sm_types)}",
        })

    if not triggers:
        return {"should_show": False, "reasons": [], "primary_trigger": "",
                "lines": [], "suppression_note": ""}

    # 排序: 优先级最高的在前
    triggers.sort(key=lambda t: t["priority"], reverse=True)
    primary = triggers[0]

    # 构建支线走法
    lines = _build_branch_lines(step, max_lines)

    result = {
        "should_show": True,
        "reasons": [t["reason"] for t in triggers],
        "primary_trigger": primary["code"],
        "lines": lines,
        "suppression_note": "",
    }

    return result


def _build_branch_lines(step: dict, max_lines: int) -> list:
    """从 step 数据中提取支线走法序列"""
    lines = []
    move_san = step.get("move_san", "")

    # 1) 如果实战是失误，添加推荐走法
    recommended = step.get("recommended")
    if recommended:
        lines.append({
            "label": "引擎推荐",
            "moves": recommended.get("pv", recommended.get("move", "")),
            "description": f"推荐 {recommended['move']}（评分{recommended.get('score_cp',0)/100:+.1f}），实战走了{move_san}",
        })

    # 2) 添加候选走法
    candidates = step.get("candidates", [])
    for c in candidates[:max_lines]:
        if c.get("move") == move_san:
            continue  # 跳过实战走法（如果 already covered by recommended）
        if not recommended or c.get("move") != recommended.get("move"):
            lines.append({
                "label": f"候选: {c['move']}",
                "moves": c.get("pv", c.get("move", "")),
                "description": f"评分 {c.get('score_cp', 0)/100:+.1f}",
            })
        if len(lines) >= max_lines:
            break

    # 3) 如果有大师数据，添加大师流行走法
    masters = step.get("masters")
    if masters and masters.get("top_moves") and len(lines) < max_lines:
        for tm in masters["top_moves"][:1]:
            if tm["san"] != move_san and (not lines or tm["san"] != lines[0].get("move_uci", "")):
                lines.append({
                    "label": f"大师流行: {tm['san']}",
                    "moves": tm["san"],
                    "description": f"大师选择频率 {tm['pct']}%",
                })

    return lines[:max_lines]


def apply_suppression_rules(
    branch_results: list,
    audience: str = "中级",
    max_branches: int = None,
) -> list:
    """
    对所有 step 的 branch 结果应用抑制规则。

    Args:
        branch_results: [{move_number, branch_result}, ...]
        audience: 观众级别
        max_branches: 每局最多几处支线

    Returns:
        过滤后的 branch_results
    """
    if max_branches is None:
        max_branches = MAX_BRANCHES_PER_GAME

    # 收集需要展示的
    showing = [r for r in branch_results if r.get("branch_result", {}).get("should_show")]

    # 1) 超过上限，只保留优先级最高的
    if len(showing) > max_branches:
        # 按触发优先级排序
        priority_map = {
            "MISTAKE": 50, "TACTIC_DETECTED": 45, "TABLEBASE_CRITICAL": 40,
            "MASTERS_DEVIATION": 35, "STRATEGIC_MISTAKE": 35,
            "MULTICHOICE": 30, "OPENING_DEVIATION": 25,
        }
        showing.sort(
            key=lambda r: max(
                priority_map.get(r["branch_result"].get("primary_trigger", ""), 0),
                abs(r.get("step", {}).get("score_diff", 0)) * 10,
            ),
            reverse=True,
        )

        for r in showing[max_branches:]:
            r["branch_result"]["should_show"] = False
            r["branch_result"]["suppression_note"] = (
                f"超过每局支线上限 ({max_branches})，被抑制"
            )

    # 2) 连续触发抑制: 在连续窗口内只保留评分波动最大的
    if len(showing) >= 2:
        showing.sort(key=lambda r: r.get("move_number", 0))
        i = 0
        while i < len(showing) - 1:
            curr = showing[i]
            nxt = showing[i + 1]
            if nxt.get("move_number", 0) - curr.get("move_number", 0) <= CONSECUTIVE_WINDOW:
                # 比较评分波动
                curr_diff = abs(curr.get("step", {}).get("score_diff", 0))
                nxt_diff = abs(nxt.get("step", {}).get("score_diff", 0))
                if curr_diff >= nxt_diff:
                    # 抑制 next
                    nxt["branch_result"]["should_show"] = False
                    nxt["branch_result"]["suppression_note"] = "连续触发，被上一步更重要的波动替代"
                    showing.pop(i + 1)
                else:
                    # 抑制 curr
                    curr["branch_result"]["should_show"] = False
                    curr["branch_result"]["suppression_note"] = "连续触发，被下一步更重要的波动替代"
                    showing.pop(i)
                continue
            i += 1

    return branch_results


def generate_branch_guide_for_prompt(branch_results: list) -> str:
    """
    生成 LLM 提示词中关于分支展示的指南。
    告诉 LLM 哪些步应该用小棋盘展示支线。
    """
    showing = [r for r in branch_results
               if r.get("branch_result", {}).get("should_show")]

    if not showing:
        return "本局无需支线展示（无触发的分支条件）"

    lines = ["【分支展示指南 — 在以下步骤使用小棋盘展示支线变化】"]
    for r in showing:
        mn = r.get("move_number", "?")
        br = r.get("branch_result", {})
        trigger = br.get("primary_trigger", "?")
        reasons = "；".join(br.get("reasons", []))
        branch_lines = br.get("lines", [])
        bl_str = ""
        if branch_lines:
            bl_parts = []
            for bl in branch_lines:
                bl_parts.append(f"{bl['label']}: {bl['moves']}")
            bl_str = " | ".join(bl_parts)

        lines.append(
            f"  第{mn}步 [{trigger}]: {reasons}"
            f"{' → 可用支线: ' + bl_str if bl_str else ''}"
        )

    lines.append(
        f"\n共 {len(showing)} 处支线展示。"
        f"请在这些步骤的解说中使用 [小棋盘: 走法序列] 指令展示支线变化。"
        f"其余步骤不需要支线展示。"
    )

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("分支讲解触发系统 自测")
    print("=" * 60)

    # 测试 1: 失误触发
    print("\n--- 测试 1: 失误触发 ---")
    step1 = {
        "move_number": 12,
        "move_san": "Ne5",
        "score_diff": -2.5,
        "quality": "失误",
        "candidates": [
            {"move": "d5", "score_cp": 30, "pv": "d5 exd5 Nxd5"},
            {"move": "c6", "score_cp": 15, "pv": "c6 d4 exd4"},
        ],
        "recommended": {"move": "d5", "score_cp": 30, "pv": "d5 exd5 Nxd5"},
        "tactical_themes": [],
        "masters": None,
        "strategic_mistakes": [],
    }
    result = evaluate_branch_trigger(step1, chess.Board(), "中级")
    print(f"  展示: {result['should_show']}")
    print(f"  触发: {result['primary_trigger']}")
    print(f"  原因: {'; '.join(result['reasons'])}")
    print(f"  支线数: {len(result['lines'])}")
    for line in result["lines"]:
        print(f"    - {line['label']}: {line['moves']}")

    # 测试 2: 多候选接近
    print("\n--- 测试 2: 多候选接近 ---")
    step2 = {
        "move_number": 8,
        "move_san": "O-O",
        "score_diff": 0.1,
        "quality": "正常",
        "candidates": [
            {"move": "O-O", "score_cp": 25, "pv": "O-O d5 exd5"},
            {"move": "d4", "score_cp": 23, "pv": "d4 exd4 Nxd4"},
        ],
        "recommended": None,
        "tactical_themes": [],
        "masters": None,
        "strategic_mistakes": [],
    }
    result2 = evaluate_branch_trigger(step2, chess.Board(), "中级")
    print(f"  展示: {result2['should_show']}")
    print(f"  触发: {result2['primary_trigger']}")
    for line in result2["lines"]:
        print(f"    - {line['label']}: {line['moves']}")

    # 测试 3: 战术触发
    print("\n--- 测试 3: 战术触发 ---")
    step3 = {
        "move_number": 20,
        "move_san": "Nf7+",
        "score_diff": 4.0,
        "quality": "妙手",
        "candidates": [
            {"move": "Nf7+", "score_cp": 400, "pv": "Nf7+ Kg8 Nh6#"},
        ],
        "recommended": None,
        "tactical_themes": [
            {"type": "fork", "description_zh": "击双"},
            {"type": "mate_threat", "description_zh": "杀棋"},
        ],
        "masters": None,
        "strategic_mistakes": [],
    }
    result3 = evaluate_branch_trigger(step3, chess.Board(), "中级")
    print(f"  展示: {result3['should_show']}")
    print(f"  触发: {result3['primary_trigger']}")

    # 测试 4: 抑制规则 — 超过上限
    print("\n--- 测试 4: 抑制规则 ---")
    fake_results = []
    for i in range(8):
        fake_step = {
            "move_number": i + 1,
            "move_san": f"e{i}",
            "score_diff": -2.0 + i * 0.1,
            "quality": "失误" if i < 5 else "正常",
            "candidates": [],
            "tactical_themes": [{"type": "fork"}] if i == 3 else [],
        }
        br = evaluate_branch_trigger(fake_step, chess.Board(), "中级")
        fake_results.append({
            "move_number": i + 1,
            "branch_result": br,
            "step": fake_step,
        })

    filtered = apply_suppression_rules(fake_results, "中级", max_branches=5)
    showing_count = sum(
        1 for r in filtered if r["branch_result"]["should_show"]
    )
    suppressed = [r for r in filtered
                  if r["branch_result"].get("suppression_note")]
    print(f"  原始触发: 8 处")
    print(f"  抑制后: {showing_count} 处")
    for r in suppressed:
        print(f"    第{r['move_number']}步: {r['branch_result']['suppression_note']}")

    # 测试 5: 生成 LLM 指南
    print("\n--- 测试 5: 生成 LLM 指南 ---")
    guide = generate_branch_guide_for_prompt(filtered)
    print(guide[:500])

    print(f"\n✅ 自测完成")