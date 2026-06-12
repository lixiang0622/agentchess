"""
国际象棋讲解词生成 - 质量优化指南

本文件包含了优化讲解质量的技巧和改进的提示词模板。
"""

import sys
import json
from pathlib import Path
import chess.pgn

# Force UTF-8 output
sys.stdout.reconfigure(encoding="utf-8")

# ========== 优化技巧 1: 注入开局知识 ==========

def extract_opening_info(pgn_path: Path) -> dict:
    """
    从 PGN 文件中提取开局信息和基础棋局数据
    
    返回: {
        "event": "棋赛名称",
        "site": "地点",
        "date": "日期",
        "white": "白方",
        "black": "黑方",
        "opening": "开局名称",
        "opening_eco": "ECO 代码",
        "first_10_moves": "前 10 步"
    }
    """
    with pgn_path.open("r", encoding="utf-8") as f:
        game = chess.pgn.read_game(f)
    
    headers = game.headers
    board = game.board()
    moves = []
    
    for i, move in enumerate(game.mainline_moves()):
        if i >= 10:  # 取前 10 步
            break
        moves.append(board.san(move))
        board.push(move)
    
    return {
        "event": headers.get("Event", "未知"),
        "site": headers.get("Site", "未知"),
        "date": headers.get("Date", "未知"),
        "white": headers.get("White", "未知"),
        "black": headers.get("Black", "未知"),
        "opening": headers.get("Opening", "未知"),
        "eco": headers.get("ECO", "未知"),
        "first_10_moves": " ".join(moves),
    }


# ========== 优化技巧 2: 长度控制模板 ==========

OPTIMIZED_COACH_PROMPT = """你是国际象棋特级大师兼优秀教练，正在为一场对局制作视频讲解。下面是棋局分析数据和开局信息。

【讲解要求】
1. 对每一步棋都进行解说，不要跳过任何一步。
2. 篇幅控制：
   - 普通招法: 15~30 字（如"白方正常出子，马f3"）
   - 疑问手: 80~120 字（解释为什么不好、后果、正确走法）
   - 失误: 120~150 字（详细分析、推荐变化、评估差距）
3. 当某一步质量标记为"疑问手"或"失误"时，要重点展开：
   - 指出为什么不好
   - 白黑方都站在谁的角度分析
   - 讲引擎推荐的正确走法及其后续变化
   - 用通俗的语言说明局面评分变化（如"从这里开始，白方从均势掉到了接近败势"）
4. 开局识别：
   - 开局名称: {opening}（ECO: {eco}）
   - 前 10 步: {first_10_moves}
   - 请在解说开局阶段简单介绍一下这个开局的特点、白黑双方的意图
5. 棋子和坐标一定要讲准确，不要乱说。
6. 整个解说要连贯，就像你在对着棋盘录制视频一样。
7. 请用以下格式输出：每一步的解说放在单独一行，并以"[STEP 编号]"开头。例如：
   [STEP 1] 白方第一步走e4，这是最常见的王前兵开局，占领中心。
   [STEP 2] 黑方应以c5，西西里防御！意图从侧翼反击，避免对称。

下面是棋局分析数据（包含每一步的走法、引擎评分、质量判定和推荐走法）：

{steps_json}

请开始讲解，注意篇幅控制和讲解质量："""


# ========== 优化技巧 3: 多 PV 分析 ==========

def add_multiple_pv(steps: list, engine_analysis: dict) -> list:
    """
    为每个错误的步数添加多个推荐变化（如果有的话）
    
    这需要在 analyse.py 中修改引擎分析部分来支持
    这里只是示例函数，展示如何添加多 PV 数据
    """
    # 示例：如果在 analyse.py 中使用 engine.analyse(..., multipv=3)
    # 会返回 info["pv"] 包含前 3 个最优变化
    
    for step in steps:
        if step["quality"]:  # 只对有质量问题的步数
            # 这些数据应该来自 analyse.py 的 multipv 分析
            step["alternative_moves"] = [
                {"move": "d5", "eval": 0.8, "reason": "巩固中心"},
                {"move": "c5", "eval": 0.5, "reason": "侧翼反击"},
            ]
    return steps


# ========== 优化技巧 4: 事后验证规则 ==========

VALIDATION_RULES = {
    "棋子名称": {
        "白方": ["K", "Q", "R", "B", "N", "P"],  # 棋子符号不要乱说
        "黑方": ["k", "q", "r", "b", "n", "p"],
    },
    "坐标": {
        "file": ["a", "b", "c", "d", "e", "f", "g", "h"],  # 列
        "rank": ["1", "2", "3", "4", "5", "6", "7", "8"],  # 行
    },
    "评分": {
        "min": -10.0,
        "max": 10.0,
        "warning_threshold": 5.0,  # 评分跳跃超过 5 兵值得警惕
    }
}


def validate_commentary(step_commentary: str, step_data: dict) -> dict:
    """
    对讲解词进行简单的合理性检查
    
    返回: {
        "is_valid": bool,
        "warnings": [list of warnings],
        "suggestions": [list of suggestions]
    }
    """
    warnings = []
    suggestions = []
    
    # 检查 1: 是否提到了正确的走法
    move_san = step_data.get("move_san", "")
    if move_san and move_san not in step_commentary:
        # 不一定要提，但对于重要步数可以检查
        if step_data.get("quality"):
            suggestions.append(f"考虑在讲解中提到实际走法: {move_san}")
    
    # 检查 2: 评分变化是否过大（可能是错误）
    score_diff = step_data.get("score_diff", 0)
    if abs(score_diff) > VALIDATION_RULES["评分"]["warning_threshold"]:
        warnings.append(f"评分跳跃很大 ({score_diff:+.1f} 兵)，请检查是否是真的失误")
    
    # 检查 3: 讲解词长度
    word_count = len(step_commentary)
    quality = step_data.get("quality", "")
    
    if quality == "失误" and word_count < 80:
        suggestions.append(f"失误讲解过短 ({word_count} 字)，建议扩展到 120~150 字")
    elif quality == "疑问手" and word_count < 60:
        suggestions.append(f"疑问手讲解过短 ({word_count} 字)，建议扩展到 80~120 字")
    elif not quality and word_count > 30:
        suggestions.append(f"普通招法讲解过长 ({word_count} 字)，建议精简到 15~30 字")
    
    return {
        "is_valid": len(warnings) == 0,
        "warnings": warnings,
        "suggestions": suggestions
    }


def batch_validate_commentary(merged_steps: list) -> dict:
    """对所有讲解词进行批量验证"""
    report = {
        "total_steps": len(merged_steps),
        "validation_results": [],
        "summary": {
            "valid_count": 0,
            "warning_count": 0,
            "suggestion_count": 0,
        }
    }
    
    for step in merged_steps:
        if step.get("commentary"):
            result = validate_commentary(step["commentary"], step)
            report["validation_results"].append({
                "step": step["move_number"],
                "move": step["move_san"],
                "result": result
            })
            
            if result["is_valid"]:
                report["summary"]["valid_count"] += 1
            if result["warnings"]:
                report["summary"]["warning_count"] += 1
            if result["suggestions"]:
                report["summary"]["suggestion_count"] += 1
    
    return report


def print_validation_report(report: dict):
    """打印验证报告"""
    print("\n" + "="*60)
    print("讲解词验证报告")
    print("="*60)
    
    summary = report["summary"]
    total = report["total_steps"]
    
    print(f"\n总步数: {total}")
    print(f"✓ 通过验证: {summary['valid_count']}")
    print(f"⚠ 有警告: {summary['warning_count']}")
    print(f"💡 有建议: {summary['suggestion_count']}")
    
    print("\n需要人工检查的步数:")
    for item in report["validation_results"]:
        if item["result"]["warnings"] or item["result"]["suggestions"]:
            step_num = item["step"]
            move = item["move"]
            print(f"\n[STEP {step_num}] {move}")
            
            for warning in item["result"]["warnings"]:
                print(f"  ⚠ {warning}")
            
            for suggestion in item["result"]["suggestions"]:
                print(f"  💡 {suggestion}")


# ========== 主函数示例 ==========

def main():
    script_dir = Path(__file__).parent
    pgn_path = script_dir / "lichess_pgn_2026.05.05_pjykk_vs_lixiang23.bEHmt9NK.pgn"
    merged_file = script_dir / "merged_analysis_commentary.json"
    
    print("【国际象棋讲解质量优化指南】\n")
    
    # 示例 1: 提取开局信息
    if pgn_path.exists():
        print("1. 提取开局信息...")
        opening_info = extract_opening_info(pgn_path)
        print(f"   开局: {opening_info['opening']} ({opening_info['eco']})")
        print(f"   对阵: {opening_info['white']} vs {opening_info['black']}\n")
    
    # 示例 2: 显示优化提示词
    print("2. 优化提示词示例:")
    print("-" * 60)
    if opening_info:
        sample_prompt = OPTIMIZED_COACH_PROMPT.format(
            opening=opening_info["opening"],
            eco=opening_info["eco"],
            first_10_moves=opening_info["first_10_moves"],
            steps_json="{steps_json}"
        )
        print(sample_prompt[:400] + "...\n")
    
    # 示例 3: 验证讲解词
    if merged_file.exists():
        print("3. 验证已生成的讲解词...")
        with merged_file.open("r", encoding="utf-8") as f:
            merged_steps = json.load(f)
        
        report = batch_validate_commentary(merged_steps)
        print_validation_report(report)
    else:
        print("3. 验证: 请先运行 parse_commentary.py 生成 merged_analysis_commentary.json\n")
    
    print("\n【优化建议总结】")
    print("✓ 使用优化提示词注入开局知识")
    print("✓ 控制讲解长度: 普通招法 15~30 字、疑问手 80~120 字、失误 120~150 字")
    print("✓ 在 analyse.py 中添加 multipv=3 参数获取多个推荐变化")
    print("✓ 使用本工具验证讲解词，确保准确性")
    print("✓ 人工预览生成的讲解词，特别是失误部分")


if __name__ == "__main__":
    main()
