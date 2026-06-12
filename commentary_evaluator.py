"""
解说词质量自动评估 + 重写模块 (Commentary Evaluator)

四维度评分: 准确性 / 趣味性 / 教学价值 / 术语适当性
低于阈值(默认6分)自动触发重写，最多重试2次。

用法:
  python commentary_evaluator.py commentary.txt --audience 中级
  python commentary_evaluator.py --evaluate commentary.txt --verbose

集成到 pipeline.py:
  from commentary_evaluator import evaluate_and_rewrite
  result = evaluate_and_rewrite(commentary, audience, api_key, model)
"""

import sys
import json
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from openai import OpenAI
except ImportError:
    print("需要 openai: pip install openai")
    OpenAI = None

SCRIPT_DIR = Path(__file__).parent
EVAL_FILE = SCRIPT_DIR / "commentary_evaluation.json"


# ═══════════════════════════════════════════════════════════════
#  裁判提示词
# ═══════════════════════════════════════════════════════════════

JUDGE_SYSTEM_PROMPT = """你是一位国际象棋教学评估专家。请对以下棋局解说词进行严格评分。"""

JUDGE_USER_TEMPLATE = """请根据以下标准，为这段棋局解说词打分（1-10分），并给出具体评语。

评分维度：
1. 准确性 (accuracy): 解说内容是否与引擎分析一致？是否存在走法错误、术语误用或评估偏差？
2. 趣味性 (entertainment): 语言是否生动吸睛？是否有恰当的比喻、教练口吻或精彩描述？
3. 教学价值 (education): 是否解释了走法的"为什么"？是否融入了棋理知识（兵型/王安全/出子等）？对业余棋手是否有启发？
4. 术语适当性 (terminology): 术语使用是否符合观众水平？是否有不必要的生僻词或过度简化？

目标观众: {audience}

解说词:
{commentary}

请以JSON格式回复（只返回JSON，不要其他文字）：
{{
  "accuracy": 8,
  "entertainment": 7,
  "education": 9,
  "terminology": 8,
  "overall": 8,
  "strengths": ["优点1", "优点2"],
  "weaknesses": ["缺点1", "缺点2"],
  "comment": "总体评价，100字以内"
}}"""

REWRITE_PROMPT_ADDON = """
【重写提示 — 上次解说被评为 {overall}/10 分】
主要问题: {weaknesses}
请重新生成解说词，特别注意改进以上问题。其他要求不变。
"""


# ═══════════════════════════════════════════════════════════════
#  评估函数
# ═══════════════════════════════════════════════════════════════

def _load_api_config() -> dict:
    config_path = SCRIPT_DIR / "api_config.json"
    if not config_path.exists():
        config_path = SCRIPT_DIR / "api_config.example.json"
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as f:
            return json.load(f)
    return {"api_key": "", "api_type": "deepseek", "model": "deepseek-v4-pro"}


def evaluate_commentary(commentary: str, audience: str = "中级",
                        api_key: str = "", model: str = "",
                        api_type: str = "deepseek") -> dict:
    """
    调用 LLM 裁判对解说词进行四维度评分。

    Returns:
        {accuracy, entertainment, education, terminology, overall, strengths, weaknesses, comment}
    """
    if OpenAI is None:
        return {"overall": 8, "comment": "OpenAI 库未安装", "error": True}

    cfg = _load_api_config()
    key = api_key or cfg.get("api_key", "")
    if not key or len(key) < 5:
        return {"overall": 8, "comment": "API Key 未配置", "error": True}

    m = model or cfg.get("model", "deepseek-v4-pro")
    t = api_type or cfg.get("api_type", "deepseek")

    base_url = "https://api.llm.ustc.edu.cn"

    try:
        client = OpenAI(api_key=key, base_url=base_url)

        # 只取前6000字评估（超长文本截断）
        text_to_eval = commentary[:6000] if len(commentary) > 6000 else commentary

        response = client.chat.completions.create(
            model=m,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": JUDGE_USER_TEMPLATE.format(
                    audience=audience, commentary=text_to_eval
                )}
            ],
            temperature=0.3,
            max_tokens=800,
            timeout=120
        )

        result_text = response.choices[0].message.content
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            result = json.loads(json_match.group())
            result["error"] = False
            return result
        else:
            return {"overall": 7, "comment": "裁判未返回有效JSON", "error": True}

    except Exception as e:
        return {"overall": 7, "comment": f"裁判调用失败: {e}", "error": True}


# ═══════════════════════════════════════════════════════════════
#  评估 + 自动重写
# ═══════════════════════════════════════════════════════════════

def evaluate_and_rewrite(
    commentary: str,
    audience: str = "中级",
    api_key: str = "",
    model: str = "",
    api_type: str = "deepseek",
    min_score: float = 6.0,
    max_rewrites: int = 2,
    rewrite_callback=None,
) -> dict:
    """
    评估解说词质量，如果不合格自动触发重写。

    Args:
        commentary: 原始解说词
        audience: 观众水平
        min_score: 最低合格分数（低于此分触发重写）
        max_rewrites: 最多重写次数
        rewrite_callback: 重写回调函数 f(commentary, feedback) -> new_commentary

    Returns:
        {commentary, score, evaluations, rewrites, passed}
    """
    results = {"evaluations": [], "rewrites": 0, "passed": True, "commentary": commentary}

    print(f"\n{'='*60}")
    print("👨‍⚖️ 解说词质量评估")
    print(f"{'='*60}")

    for attempt in range(max_rewrites + 1):
        current_text = results["commentary"]

        print(f"\n  [{attempt+1}/{max_rewrites+1}] 评估中...")
        eval_result = evaluate_commentary(current_text, audience, api_key, model, api_type)
        results["evaluations"].append(eval_result)

        if eval_result.get("error"):
            print(f"  ⚠ 评估失败: {eval_result.get('comment')}")
            results["passed"] = True
            results["score"] = eval_result.get("overall", 7)
            break

        overall = eval_result.get("overall", 7)
        strengths = eval_result.get("strengths", [])
        weaknesses = eval_result.get("weaknesses", [])

        print(f"  评分: {overall}/10")
        print(f"  准确:{eval_result.get('accuracy',0)} 趣味:{eval_result.get('entertainment',0)} "
              f"教学:{eval_result.get('education',0)} 术语:{eval_result.get('terminology',0)}")
        if strengths:
            print(f"  优点: {'; '.join(strengths[:2])}")
        if weaknesses:
            print(f"  问题: {'; '.join(weaknesses[:2])}")

        if overall >= min_score:
            print(f"\n  ✅ 合格 ({overall} ≥ {min_score})")
            results["score"] = overall
            results["passed"] = True
            break

        if attempt < max_rewrites and rewrite_callback:
            print(f"\n  ⚠ {overall} < {min_score}，触发重写...")
            feedback = f"评分 {overall}/10。问题: {'; '.join(weaknesses)}"
            new_text = rewrite_callback(current_text, feedback)
            if new_text:
                results["commentary"] = new_text
                results["rewrites"] += 1
            else:
                print(f"  重写回调返回空，终止。")
                results["score"] = overall
                results["passed"] = False
                break
        else:
            print(f"\n  ⚠ 已达最大重试次数，保留当前版本。")
            results["score"] = overall
            results["passed"] = overall >= min_score
            break

    # 保存评估结果
    save_eval = {
        "audience": audience,
        "score": results.get("score", 0),
        "evaluations": results["evaluations"],
        "rewrites": results["rewrites"],
        "passed": results["passed"],
    }
    with EVAL_FILE.open("w", encoding="utf-8") as f:
        json.dump(save_eval, f, ensure_ascii=False, indent=2)

    return results


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="解说词质量评估")
    parser.add_argument("file", nargs="?", default="commentary.txt",
                        help="解说词文件路径")
    parser.add_argument("--audience", default="中级", help="观众水平 (初级/中级/高级)")
    parser.add_argument("--verbose", action="store_true", help="详细输出")
    parser.add_argument("--test", action="store_true", help="自测")
    args = parser.parse_args()

    if args.test:
        print("=" * 60)
        print("解说词评估器 自测")
        print("=" * 60)

        mock = """
[STEP 1] 白方e4，占领中心，这是经典的开放开局第一步。
[STEP 2] 黑方c5，西西里防御！意图从侧翼反击。
[STEP 3] 白方马f3，标准的出子同时威胁e5。
"""
        result = evaluate_commentary(mock, args.audience)
        print(f"总分: {result.get('overall', '?')}")
        if not result.get("error"):
            print(f"  准确: {result.get('accuracy')}")
            print(f"  趣味: {result.get('entertainment')}")
            print(f"  教学: {result.get('education')}")
            print(f"  术语: {result.get('terminology')}")
        return

    cfile = Path(args.file)
    if not cfile.exists():
        print(f"文件不存在: {cfile}")
        return

    with cfile.open("r", encoding="utf-8") as f:
        commentary = f.read()

    result = evaluate_commentary(commentary, args.audience)
    print(f"\n总分: {result.get('overall', '?')}/10")
    print(f"评价: {result.get('comment', '')}")


if __name__ == "__main__":
    main()