"""
关键教学节点检测器 (Critical Moment Detector)
—— GothamChess 风格：不是逐步讲解，而是只讲"值得讲"的关键时刻

核心理念：
  一盘 60 步的对局，观众真正需要深度讲解的只有 5-8 个关键时刻。
  其余步骤用 1-2 句带过，把篇幅留给真正的教学点。

检测维度：
  1. 评分剧变 (Score Swing) — cp 差值 > 1.5 的剧烈波动
  2. 战术爆发 (Tactical Strike) — 出现击双/牵制/闪击等战术
  3. 失误/妙手 (Quality Spike) — 送子/漏杀/妙手
  4. 阶段转换 (Phase Transition) — 开局→中局→残局
  5. 引擎分歧 (Engine Disagreement) — Stockfish vs Lc0 意见不一
  6. 弃子 (Sacrifice) — 弃兵/弃子换取补偿

用法:
    from critical_moment_detector import detect_critical_moments
    moments = detect_critical_moments(steps, opening_profile, phases)
"""

import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════
#  权重配置
# ═══════════════════════════════════════════════════════════════

WEIGHTS = {
    "score_swing": 30,       # 评分剧变权重
    "tactical": 25,          # 战术主题权重
    "quality": 20,           # 着法质量权重
    "phase_transition": 10,  # 阶段转换权重
    "engine_disagree": 10,   # 引擎分歧权重
    "sacrifice": 5,          # 弃子权重
}

# 分数阈值
HIGH_THRESHOLD = 60   # >= 此分数视为 "关键时刻"
MEDIUM_THRESHOLD = 30 # >= 此分数视为 "值得注意"
# < 30 视为 "常规走法"


def detect_critical_moments(
    steps: list,
    opening_profile: dict = None,
    phases: list = None,
    top_n: int = 8,
) -> dict:
    """
    从分析步骤中检测教学关键时刻。

    Args:
        steps: analyse.py 输出的步骤列表
        opening_profile: 开局统计
        phases: 阶段划分
        top_n: 返回多少个最关键时刻

    Returns:
        {
            "moments": [ {move_number, score, category, reasons, summary}, ... ],
            "total_significant": N,
            "distribution": { "critical": N, "notable": N, "routine": N },
            "teaching_arc": "建议的讲解主线描述",
        }
    """
    n = len(steps)
    if n == 0:
        return {"moments": [], "total_significant": 0,
                "distribution": {}, "teaching_arc": ""}

    # 1) 计算全局统计（用于归一化）
    all_score_diffs = [abs(s.get("score_diff", 0)) for s in steps]
    max_diff = max(all_score_diffs) if all_score_diffs else 1
    avg_diff = sum(all_score_diffs) / len(all_score_diffs) if all_score_diffs else 1

    # 2) 逐步打分
    scored = []
    for i, step in enumerate(steps):
        score = 0
        reasons = []
        categories = []

        move_num = step.get("move_number", i + 1)

        # ---- 评分剧变 ----
        diff = abs(step.get("score_diff", 0))
        if diff > 3.0:
            s = WEIGHTS["score_swing"]
            reasons.append(f"评分剧烈波动 ({step['score_diff']:+.1f})")
            categories.append("critical_swing")
        elif diff > 1.5:
            s = int(WEIGHTS["score_swing"] * 0.7)
            reasons.append(f"评分明显变化 ({step['score_diff']:+.1f})")
            categories.append("notable_swing")
        elif diff > 0.8:
            s = int(WEIGHTS["score_swing"] * 0.35)
        else:
            s = 0
        score += s

        # ---- 战术主题 ----
        themes = step.get("tactical_themes", [])
        if themes:
            theme_types = {t["type"] for t in themes}
            n_themes = len(theme_types)
            if n_themes >= 2:
                s = WEIGHTS["tactical"]
                reasons.append(f"多重战术: {', '.join(sorted(theme_types))}")
                categories.append("tactical_combo")
            elif "mate_threat" in theme_types:
                s = WEIGHTS["tactical"]
                reasons.append("杀棋威胁!")
                categories.append("mate_threat")
            elif "fork" in theme_types:
                s = int(WEIGHTS["tactical"] * 0.85)
                reasons.append("击双战术")
                categories.append("tactical")
            elif "pin" in theme_types or "skewer" in theme_types:
                s = int(WEIGHTS["tactical"] * 0.7)
                reasons.append(f"牵制/串击")
                categories.append("tactical")
            else:
                s = int(WEIGHTS["tactical"] * 0.5)
                reasons.append(f"战术: {', '.join(sorted(theme_types))}")
                categories.append("tactical")
            score += s

        # ---- 着法质量 ----
        quality = step.get("quality", "正常")
        if quality in ("送子", "漏杀"):
            score += WEIGHTS["quality"]
            reasons.append(f"严重失误 ({quality})")
            categories.append("critical_blunder")
        elif quality == "失误":
            score += int(WEIGHTS["quality"] * 0.75)
            reasons.append("失误")
            categories.append("blunder")
        elif quality == "妙手":
            score += int(WEIGHTS["quality"] * 0.7)
            reasons.append("精彩妙手!")
            categories.append("brilliant")
        elif quality == "好棋":
            score += int(WEIGHTS["quality"] * 0.35)
            categories.append("good_move")

        # ---- 阶段转换 ----
        if phases:
            phase_transition = _detect_phase_transition(i, steps, phases)
            if phase_transition:
                score += WEIGHTS["phase_transition"]
                reasons.append(phase_transition)
                categories.append("phase_transition")

        # ---- 引擎分歧 ----
        cv = step.get("cross_validation", {})
        if cv:
            dtype = cv.get("disagreement_type", "")
            if dtype in ("disagree_strong",):
                score += WEIGHTS["engine_disagree"]
                reasons.append("Stockfish vs Lc0 强烈分歧")
                categories.append("engine_dispute")
            elif dtype in ("disagree_mild", "lc0_surprise"):
                score += int(WEIGHTS["engine_disagree"] * 0.5)
                reasons.append("引擎看法略有分歧")
                categories.append("engine_dispute")

        # ---- 弃子判断 ----
        san = step.get("move_san", "")
        is_capture = "x" in san
        score_before = step.get("score_before", 0)
        score_after = step.get("score_after", 0)
        if is_capture and abs(score_after - score_before) > 2.0:
            score += WEIGHTS["sacrifice"]
            reasons.append("可能涉及弃子/弃兵")
            categories.append("sacrifice")

        # 如果前一步是大漏着（对方送子），当前步可能是惩罚招
        if i > 0:
            prev_quality = steps[i - 1].get("quality", "")
            if prev_quality in ("送子", "漏杀"):
                score += 5  # 小幅加分，因为观众想知道"怎么惩罚"
                if "惩罚对手失误" not in reasons:
                    reasons.append("惩罚对手失误的关键应着")
                    categories.append("punishment")

        scored.append({
            "move_number": move_num,
            "score": min(100, score),
            "move_san": san,
            "quality": quality,
            "categories": categories,
            "reasons": reasons,
            "score_diff": diff,
            "has_tactics": len(themes) > 0,
        })

    # 3) 排序 + 分类
    scored.sort(key=lambda x: x["score"], reverse=True)

    critical = [m for m in scored if m["score"] >= HIGH_THRESHOLD]
    notable = [m for m in scored if MEDIUM_THRESHOLD <= m["score"] < HIGH_THRESHOLD]
    routine = [m for m in scored if m["score"] < MEDIUM_THRESHOLD]

    # 4) 生成讲解主线
    teaching_arc = _build_teaching_arc(critical[:top_n], steps, phases)

    return {
        "moments": scored[:top_n],
        "all_scored": scored,
        "total_significant": len(critical) + len(notable),
        "distribution": {
            "critical": len(critical),
            "notable": len(notable),
            "routine": len(routine),
        },
        "critical_moves": [m["move_number"] for m in critical],
        "notable_moves": [m["move_number"] for m in notable],
        "teaching_arc": teaching_arc,
    }


def _detect_phase_transition(idx: int, steps: list, phases: list) -> str:
    """检测当前步是否处于阶段转换点"""
    move_num = steps[idx].get("move_number", idx + 1)
    for ph in phases:
        desc = ph.get("description", "")
        phase_range = ph.get("range", "")
        # 阶段开头几步
        if phase_range:
            parts = phase_range.split("-")
            if len(parts) == 2:
                try:
                    start = int(parts[0])
                    if move_num == start:
                        return f"进入新阶段: {desc}"
                    if move_num == start + 1:
                        return f"新阶段初期: {desc}"
                except ValueError:
                    pass
    return ""


def _build_teaching_arc(critical_moments: list, steps: list, phases: list) -> str:
    """根据关键时刻构建讲解主线"""
    if not critical_moments:
        return "本局节奏平稳，无特别剧烈的攻防转换。"

    lines = ["本局建议重点讲解以下关键时刻："]
    for i, m in enumerate(critical_moments[:8], 1):
        reasons_str = "；".join(m["reasons"]) if m["reasons"] else "关键时刻"
        lines.append(
            f"  {i}. 第{m['move_number']}步 "
            f"({m['move_san']}, {m['quality']}, 评分{m['score']}) — {reasons_str}"
        )

    # 统计各类的分布
    cats = {}
    for m in critical_moments:
        for c in m.get("categories", []):
            cats[c] = cats.get(c, 0) + 1

    if cats:
        cat_summary = "；".join(f"{k}({v}次)" for k, v in
                               sorted(cats.items(), key=lambda x: -x[1])[:5])
        lines.append(f"  类型分布: {cat_summary}")

    lines.append(f"  讲解建议: 对上述 {len(critical_moments)} 个关键时刻深度展开(每个120-250字)，其余步骤精简(15-40字)。")
    return "\n".join(lines)


def generate_focus_guide(result: dict) -> str:
    """
    生成可直接嵌入 LLM 提示词的"讲解聚焦指南"。
    LLM 据此知道哪些步该详、哪些步该略。
    """
    dist = result.get("distribution", {})
    critical = dist.get("critical", 0)
    notable = dist.get("notable", 0)
    routine = dist.get("routine", 0)
    critical_moves = result.get("critical_moves", [])
    notable_moves = result.get("notable_moves", [])

    lines = [
        "【讲解聚焦指南 — 自动检测的关键教学节点】",
        f"本局共 {critical + notable + routine} 步: "
        f"⭐关键时刻 {critical} 步 | "
        f"🔶值得注意 {notable} 步 | "
        f"➖常规走法 {routine} 步",
        "",
        "详写 (120-250字, 深度分析, 推荐使用小棋盘演示支线):",
        f"  第 {', '.join(str(m) for m in critical_moves) if critical_moves else '无'} 步",
        "",
        "中写 (40-80字, 简要分析, 可选小棋盘):",
        f"  第 {', '.join(str(m) for m in notable_moves) if notable_moves else '无'} 步",
        "",
        "略写 (15-30字, 一句话带过, 不需要小棋盘):",
        f"  其余所有步",
        "",
        result.get("teaching_arc", ""),
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("关键教学节点检测器 自测")
    print("=" * 60)

    # 模拟分析数据
    mock_steps = [
        {"move_number": 1, "move_san": "e4", "quality": "正常",
         "score_diff": 0.1, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 2, "move_san": "e5", "quality": "正常",
         "score_diff": 0.0, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 3, "move_san": "Nf3", "quality": "正常",
         "score_diff": 0.1, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 4, "move_san": "Nc6", "quality": "正常",
         "score_diff": 0.0, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 5, "move_san": "Nc3", "quality": "好棋",
         "score_diff": 0.3, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 10, "move_san": "d5", "quality": "妙手",
         "score_diff": 1.8, "tactical_themes": [
             {"type": "fork", "description_zh": "马在d5击双"}
         ], "cross_validation": {"disagreement_type": "disagree_strong"}},
        {"move_number": 11, "move_san": "Qd7", "quality": "失误",
         "score_diff": -2.5, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 15, "move_san": "Bxh7+", "quality": "妙手",
         "score_diff": 3.2, "tactical_themes": [
             {"type": "discovered_attack", "description_zh": "闪击"},
             {"type": "mate_threat", "description_zh": "杀棋"}
         ], "cross_validation": {}},
        {"move_number": 20, "move_san": "O-O", "quality": "正常",
         "score_diff": 0.1, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 25, "move_san": "Rae1", "quality": "正常",
         "score_diff": 0.2, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 30, "move_san": "h3", "quality": "缓着",
         "score_diff": -0.9, "tactical_themes": [], "cross_validation": {}},
        {"move_number": 35, "move_san": "Nxd5", "quality": "妙手",
         "score_diff": 4.0, "tactical_themes": [
             {"type": "fork", "description_zh": "击双"},
             {"type": "pin", "description_zh": "牵制"}
         ], "cross_validation": {"disagreement_type": "disagree_strong"}},
        {"move_number": 42, "move_san": "Qh3", "quality": "送子",
         "score_diff": -8.5, "tactical_themes": [], "cross_validation": {}},
    ]

    # 填充默认字段
    for s in mock_steps:
        s.setdefault("score_before", 0)
        s.setdefault("score_after", s["score_diff"])

    result = detect_critical_moments(mock_steps, top_n=6)

    print("\n--- 检测结果 ---")
    print(f'关键时刻: {result["distribution"]["critical"]} 步')
    print(f'值得注意: {result["distribution"]["notable"]} 步')
    print(f'常规走法: {result["distribution"]["routine"]} 步')

    print("\n--- Top 6 关键时刻 ---")
    for i, m in enumerate(result["moments"], 1):
        print(f'  {i}. 第{m["move_number"]}步 {m["move_san"]} '
              f'(评分: {m["score"]}, {m["quality"]})')
        if m["reasons"]:
            print(f'     原因: {"; ".join(m["reasons"])}')

    print("\n--- 讲解聚焦指南 ---")
    print(generate_focus_guide(result))

    print("\n✅ 自测完成")
