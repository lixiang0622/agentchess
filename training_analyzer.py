"""
训练点提炼模块
在棋局分析完成后，自动总结"本局暴露的3个问题"和"练习建议"

工作原理：
1. 从 analysis_result.json 提取所有错误/大错步骤
2. 按错误类型分类（王安全、战术盲点、开局理论等）
3. 生成 LLM 提示词，让 LLM 生成3个训练点和练习建议
4. 也可以使用规则系统做基础分类（降级方案）
"""

import sys
import json
from pathlib import Path
from collections import Counter, defaultdict
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")


# ---- 错误分类规则系统（降级方案，不依赖 LLM）----

ERROR_PATTERNS = {
    "王的安全": {
        "keywords": ["王", "将", "杀棋", "check", "mate", "h7", "h2", "g7", "g2", "f7", "f2",
                      "王翼", "易位", "王城", "通风口", "底线"],
        "themes": ["mate_threat"],
        "explanation": "这盘棋中多次出现王城通风口被利用或忽略王的安全的问题。建议加强对王城薄弱格的警觉。",
    },
    "战术盲点": {
        "keywords": ["击双", "牵制", "串击", "闪击", "引离", "中间着", "fork", "pin", "skewer",
                      "discovered", "战术", "威胁", "送子"],
        "themes": ["fork", "pin", "skewer", "discovered_attack", "discovered_check",
                   "deflection", "zwischenzug"],
        "explanation": "对局中出现了战术盲点，被对手利用击双/牵制等手段得子。建议加强战术训练，特别是_____题型的解题训练。",
    },
    "开局理论": {
        "keywords": ["开局", "出子", "中心", "发展", "Opening", "ECO"],
        "explanation": "开局阶段存在理论盲区，导致过早陷入被动。建议学习该开局的主要变化和典型计划。",
    },
    "残局技术": {
        "keywords": ["残局", "兵", "升变", "王", "通路兵", "endgame"],
        "explanation": "残局处理不够精确，错过了赢棋机会或未能把握和棋。建议练习基础残局定式。",
    },
    "局面对策": {
        "keywords": ["计划", "战略", "结构", "弱点"],
        "explanation": "中局缺乏明确的战略方向或未能识别局面的关键弱点。建议学习典型兵形结构的中局计划。",
    },
}


def classify_error_steps(steps: list) -> list[dict]:
    """
    对错误/大错步骤进行分类，同时标记是哪一方走出的

    返回: [
        {"move_number": 12, "move_san": "Nf6", "quality": "错误",
         "side": "黑方", "score_diff": -1.5, "themes": [...], "error_category": "战术盲点"},
        ...
    ]
    """
    error_steps = [s for s in steps if s.get("quality") in ("失误", "漏杀", "送子", "疑问")]

    classified = []
    for step in error_steps:
        themes = [t.get("type", "") for t in step.get("tactical_themes", [])]
        scores = {}

        for cat_name, pattern in ERROR_PATTERNS.items():
            score = 0
            # 检查战术主题匹配
            for t in themes:
                if t in pattern.get("themes", []):
                    score += 3
            # 检查关键词（通过 move_san 和周边信息）
            if step.get("move_number", 0) <= 12:
                score += 1  # 开局阶段的问题更容易是开局理论

            scores[cat_name] = score

        # 最佳匹配
        best_cat = max(scores, key=scores.get) if scores else "局面判断"
        if scores.get(best_cat, 0) == 0:
            best_cat = "局面判断"

        classified.append({**step, "error_category": best_cat})

    return classified


def split_errors_by_side(classified: list[dict]) -> dict:
    """
    将分类后的错误按走棋方拆分为白方和黑方。

    返回: {
        "白方": [{...}, ...],
        "黑方": [{...}, ...],
    }
    """
    white_errors = [s for s in classified if s.get("side") == "白方"]
    black_errors = [s for s in classified if s.get("side") == "黑方"]
    return {"白方": white_errors, "黑方": black_errors}


def _build_side_training_points(
    side: str, steps_in_cat: list, by_category: dict
) -> list[dict]:
    """为一方生成训练要点列表"""
    if not steps_in_cat:
        return []

    # 各类别严重度
    category_severity = {}
    for cat, cat_steps in by_category.items():
        total_loss = sum(abs(s.get("score_diff", 0)) for s in cat_steps)
        quality_score = sum(
            4 if s["quality"] == "送子" else
            3 if s["quality"] in ("漏杀", "失误") else
            2
            for s in cat_steps
        )
        category_severity[cat] = {
            "count": len(cat_steps),
            "total_score_loss": round(total_loss, 1),
            "quality_score": quality_score,
            "steps": [s["move_number"] for s in cat_steps],
            "worst_step": max(cat_steps, key=lambda s: abs(s.get("score_diff", 0))),
        }

    # 取前 3 个最严重的类别
    sorted_cats = sorted(category_severity.items(),
                         key=lambda x: x[1]["quality_score"], reverse=True)[:3]

    practice_suggestions = {
        "王的安全": f"建议{side}每天做5道'王翼攻防'战术题，特别关注h7/h2/f7/f2的弱点。养成每步棋检查王的安全的习惯。",
        "战术盲点": f"建议{side}使用 ChessTempo 或 lichess.org 的战术训练模块，每天做20道战术题，重点关注击双和牵制题型。",
        "开局理论": f"推荐{side}使用 lichess 开局浏览器研究该开局的主要变例，观看特级大师在该开局中的经典对局。",
        "残局技术": f"建议{side}练习100个基础残局定式（如单车杀王、单后杀王、兵残局的方形法则和关键格）。Silman的《残局手册》是很好的参考。",
        "局面对策": f"推荐{side}阅读Nimzowitsch的《我的体系》或学习典型兵形结构的中局计划，如Carlsbad兵形、Hedgehog结构等。",
        "局面判断": f"建议{side}多复盘自己的对局，在关键节点停下思考'如果我是特级大师，我会怎么走？'，培养局面嗅觉。",
    }

    training_points = []
    for cat, info in sorted_cats:
        pattern = ERROR_PATTERNS.get(cat, ERROR_PATTERNS.get("局面对策", {}))
        base_explanation = pattern.get("explanation", "需要加强这一方面的训练。")
        explanation = base_explanation.replace("_____", cat.lower())
        explanation += f" 具体表现为第{', '.join(map(str, info['steps']))}步。"

        training_points.append({
            "issue": cat,
            "side": side,
            "steps": info["steps"],
            "severity": "高" if info["quality_score"] >= 6 else ("中" if info["quality_score"] >= 3 else "低"),
            "score_loss": info["total_score_loss"],
            "detail": explanation,
            "practice": practice_suggestions.get(cat, practice_suggestions["局面判断"]),
        })

    return training_points


def generate_training_points_rules(steps: list, opening_info: dict = None) -> dict:
    """
    基于规则系统提炼训练点（不调用 LLM），分别评价黑白双方。

    返回: {
        "white_player": "白方选手名",
        "black_player": "黑方选手名",
        "summary": "总述",
        "white_summary": "白方表现总结",
        "black_summary": "黑方表现总结",
        "white_training_points": [...],
        "black_training_points": [...],
        "training_points": [...],          # 合并后的训练要点（兼容旧接口）
        "recommended_exercises": [...],
    }
    """
    # 提取选手名称
    white_name = "白方"
    black_name = "黑方"
    if opening_info:
        white_name = opening_info.get("white", "白方")
        black_name = opening_info.get("black", "黑方")

    classified = classify_error_steps(steps)
    by_side = split_errors_by_side(classified)

    white_errors = by_side["白方"]
    black_errors = by_side["黑方"]

    # 按类别分组（分方）
    w_by_category = defaultdict(list)
    b_by_category = defaultdict(list)
    for step in white_errors:
        w_by_category[step["error_category"]].append(step)
    for step in black_errors:
        b_by_category[step["error_category"]].append(step)

    # 生成各方的训练要点
    white_tps = _build_side_training_points("白方", white_errors, w_by_category)
    black_tps = _build_side_training_points("黑方", black_errors, b_by_category)

    # 统计各方总失误步数
    white_worst = [s for s in white_errors if s.get("quality") in ("送子", "漏杀", "失误")]
    black_worst = [s for s in black_errors if s.get("quality") in ("送子", "漏杀", "失误")]

    # 各方总结
    def _build_side_summary(name, errors, worst_errors, tps):
        if not errors:
            return f"{name}本局发挥稳定，没有明显的重复性错误，每一步都保持了较高的质量。继续保持！"
        main_issue = tps[0]["issue"] if tps else ""
        error_count = len(errors)
        worst_count = len(worst_errors)
        parts = [f"{name}共出现{error_count}处需要改进的着法"]
        if worst_count > 0:
            parts.append(f"其中{worst_count}步为严重失误（失误/漏杀/送子）")
        parts.append(f"最突出的问题是**{main_issue}**。")
        return "，".join(parts) + "。"

    white_summary = _build_side_summary(white_name, white_errors, white_worst, white_tps)
    black_summary = _build_side_summary(black_name, black_errors, black_worst, black_tps)

    # 总述
    total_errors = len(classified)
    if total_errors == 0:
        summary = "本局双方发挥都十分稳定，没有出现明显的错误或疑问手。这是一盘高质量的对局！"
    elif len(white_errors) > len(black_errors):
        summary = (
            f"本局中{white_name}出现的失误较多（{len(white_errors)}处 vs {black_name}的{len(black_errors)}处），"
            f"需要在训练中重点加强。{black_name}表现相对稳健。"
        )
    elif len(black_errors) > len(white_errors):
        summary = (
            f"本局中{black_name}出现的失误较多（{len(black_errors)}处 vs {white_name}的{len(white_errors)}处），"
            f"需要在训练中重点加强。{white_name}表现相对稳健。"
        )
    else:
        summary = (
            f"本局双方各有{len(white_errors)}处需要改进的着法，"
            f"以下是给双方各自的训练建议。"
        )

    # 合并训练要点
    all_tps = white_tps + black_tps
    exercises = [tp["practice"] for tp in all_tps]

    return {
        "white_player": white_name,
        "black_player": black_name,
        "summary": summary,
        "white_summary": white_summary,
        "black_summary": black_summary,
        "white_training_points": white_tps,
        "black_training_points": black_tps,
        "training_points": all_tps,
        "recommended_exercises": exercises,
    }


def generate_training_prompt_for_llm(steps: list, opening_info: dict = None) -> str:
    """
    生成 LLM 训练点提炼提示词 — 分别评价黑白双方

    可将此提示词发送给 LLM 获取更细致、人性化的训练建议
    """
    # 先做规则分类作为上下文
    rules_result = generate_training_points_rules(steps, opening_info)

    white_name = rules_result.get("white_player", "白方")
    black_name = rules_result.get("black_player", "黑方")

    # 按方分组整理错误
    def _side_error_summary(side, errors):
        lines = []
        for s in errors[:10]:
            themes = [t.get("type", "") for t in s.get("tactical_themes", [])]
            lines.append(
                f"  第{s['move_number']}步 {s['move_san']} [{s['quality']}] "
                f"评分变化{s['score_diff']:+.1f} 主题: {', '.join(themes) if themes else '无'}"
            )
        return "\n".join(lines) if lines else "无重大错误"

    classified = classify_error_steps(steps)
    by_side = split_errors_by_side(classified)
    white_error_summary = _side_error_summary("白方", by_side["白方"])
    black_error_summary = _side_error_summary("黑方", by_side["黑方"])

    prompt = f"""你是一位国际象棋教练，刚刚陪两位学员复盘了一盘对局。请**分别**分析黑白双方在这盘棋中的表现，为每一方总结出各自暴露的问题和具体练习建议。

【对局信息】
白方: {white_name}
黑方: {black_name}
开局: {opening_info.get('opening', '未知') if opening_info else '未知'}

【{white_name}的关键失误】
{white_error_summary}

【{black_name}的关键失误】
{black_error_summary}

【规则系统的初步分析】
{rules_result['summary']}

请以 JSON 格式输出，**分别评价双方**，格式如下：
{{
  "summary": "一段200字以内的总述，客观概括本局双方的表现差异",
  "white_summary": "一段100字以内的总结，评价{white_name}的表现",
  "black_summary": "一段100字以内的总结，评价{black_name}的表现",
  "white_training_points": [
    {{
      "issue": "问题名称",
      "steps": [相关步号列表],
      "severity": "高/中/低",
      "detail": "100字以内的问题描述",
      "practice": "150字以内的具体练习建议（可操作、可量化）"
    }}
  ],
  "black_training_points": [
    {{
      "issue": "问题名称",
      "steps": [相关步号列表],
      "severity": "高/中/低",
      "detail": "100字以内的问题描述",
      "practice": "150字以内的具体练习建议（可操作、可量化）"
    }}
  ],
  "recommended_books": ["推荐1-2本相关书籍"],
  "encouragement": "一句鼓励的话，激励双方继续努力"
}}

请确保建议具体、可操作、有量化目标。例如不说'多做题'，而说'每天在 lichess 做10道战术题，持续2周'。
如果某一方没有明显错误，在 training_points 中说明该方发挥稳定即可。"""

    return prompt


# ===================== 自测 =====================

def main():
    script_dir = Path(__file__).parent
    analysis_file = script_dir / "analysis_result.json"

    print("=" * 50)
    print("训练点提炼模块测试")
    print("=" * 50)

    if not analysis_file.exists():
        print("⚠ analysis_result.json 不存在，使用模拟数据测试")
        # 模拟数据
        mock_steps = [
            {"move_number": 8, "move_san": "Ng5", "quality": "错误", "score_diff": -2.0,
             "tactical_themes": [{"type": "fork"}]},
            {"move_number": 12, "move_san": "O-O", "quality": "大错", "score_diff": -4.5,
             "tactical_themes": [{"type": "mate_threat"}]},
            {"move_number": 18, "move_san": "Bxf7", "quality": "错误", "score_diff": -1.8,
             "tactical_themes": []},
        ]
        result = generate_training_points_rules(mock_steps)
    else:
        with analysis_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
        steps = data.get("steps", data)
        result = generate_training_points_rules(steps)

    print(f"\n总述: {result['summary']}")
    print(f"\n训练点 ({len(result['training_points'])} 条):")
    for i, tp in enumerate(result["training_points"], 1):
        print(f"  {i}. [{tp['severity']}严重度] {tp['issue']}")
        print(f"     涉及步数: {tp['steps']} (评分损失: {tp['score_loss']})")
        print(f"     详情: {tp['detail'][:80]}...")
        print(f"     练习: {tp['practice'][:80]}...")
        print()

    # 生成 LLM 提示词示例
    print("=" * 50)
    print("LLM 提示词示例 (前500字):")
    print("=" * 50)
    prompt = generate_training_prompt_for_llm(
        result.get("steps", []),
        {"white": "测试白方", "black": "测试黑方", "opening": "西西里防御"}
    )
    print(prompt[:500] + "...")


if __name__ == "__main__":
    main()
