import sys
import json
from pathlib import Path

# Force UTF-8 output in Windows terminals
sys.stdout.reconfigure(encoding="utf-8")

# 教练提示词模板
COACH_PROMPT_TEMPLATE = """你是一位国际象棋特级大师兼优秀教练，正在为一场对局制作视频讲解。下面我将给你一盘棋的详细分析数据（JSON数组），包含每一步的走法、评分变化、着法质量判定和推荐变化。

请根据这些数据，生成一份沉稳、专业、口语化的中文讲解词，不要频繁提及引擎。要求：
1. 对每一步棋都进行解说，不要跳过任何一步。
2. 篇幅按着法质量调整：
   - 非常好: 25~40 字（精彩着法，表扬并说明好在哪）
   - 正常: 15~25 字（如"白方正常出子，马f3"）
   - 有疑问: 80~120 字（解释为什么不好、正确走法）
   - 错误: 120~180 字（详细分析、推荐变化、评估差距）
   - 大错: 180~250 字（深入剖析败着，说明对局面毁灭性影响）
3. 引用数据中的评分变化，用通俗的语言解释。
4. 【重要】画面动作指令 — 在解说中嵌入画面指令来控制棋盘高亮和箭头：
   格式: [STEP N] [高亮 <格子>] [箭头 <起点>-<终点>] 解说文字...
   - [高亮 e4] 高亮一个格子  - [高亮 e4,f7] 同时高亮多个
   - [箭头 d1-h5] 画出红色箭头表示进攻路线
   例如: [STEP 12] [高亮 e4,e5] [箭头 d1-h5] 白方e4兵是核心支点！
5. 如果出现了开局名称或典型结构，你可以适当科普一两句。
6. 整个解说要连贯，就像你在对着棋盘录制视频一样。
7. 【多引擎交叉验证】当步骤数据中包含 cross_validation 字段时，说明经过了 Stockfish 和 Lc0 神经网络的双重验证。请根据 disagreement_type 来讲解：
   - agree: 简单提一句"两个引擎看法一致"
   - disagree_mild: "传统引擎和神经网络对这里略有不同看法…"
   - disagree_strong: 大讲特讲！"有意思的是，引擎看法不一致！Stockfish认为白方占优，但Lc0神经网络认为黑方更有潜力。这就是经典的静态评价与动态补偿之争！"
   - lc0_surprise: "在神经网络看来，这一方有出人意料的退路/潜力…"
   引擎分歧的步骤可多分配一些字数做深度分析。
8. 请用以下格式输出：每一步的解说放在单独一行，并以"[STEP 编号]"开头。例如：
   [STEP 1] 白方第一步走e4，这是最常见的王前兵开局，占领中心。
   [STEP 2] 黑方应以c5，西西里防御！意图从侧翼反击，避免对称。
   ...

下面是棋局分析数据：

{steps_json}

请开始讲解："""


def load_analysis_data(json_path):
    """从 JSON 文件加载分析数据 — 兼容新旧格式"""
    if not json_path.exists():
        raise FileNotFoundError(f"分析数据文件不存在: {json_path}")

    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("steps", data)


def build_coach_prompt(steps):
    """构建教练提示词"""
    steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
    prompt = COACH_PROMPT_TEMPLATE.format(steps_json=steps_json)
    return prompt


def save_prompt_to_file(prompt, output_path):
    """保存提示词到文件"""
    with output_path.open("w", encoding="utf-8") as f:
        f.write(prompt)
    print(f"✓ 教练提示词已保存到: {output_path}")


def main():
    # 确定文件路径
    script_dir = Path(__file__).parent
    analysis_file = script_dir / "analysis_result.json"
    prompt_file = script_dir / "coach_prompt.txt"
    
    # 加载分析数据
    print("正在加载分析数据...")
    steps = load_analysis_data(analysis_file)
    print(f"✓ 加载成功，共 {len(steps)} 步")
    
    # 构建提示词
    print("\n正在构建教练提示词...")
    prompt = build_coach_prompt(steps)
    
    # 保存提示词
    save_prompt_to_file(prompt, prompt_file)
    
    # 显示提示词摘要
    print("\n" + "="*60)
    print("提示词摘要（前 500 字）:")
    print("="*60)
    print(prompt[:500] + "...\n")
    
    print("完整提示词已保存。")
    print("\n下一步：")
    print("1. 复制 coach_prompt.txt 的内容")
    print("2. 粘贴到你的 AI（如 ChatGPT、Claude 等）")
    print("3. AI 会生成完整的讲解词")
    

if __name__ == "__main__":
    main()
