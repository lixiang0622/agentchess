import sys
import json
from pathlib import Path
from typing import Optional
import chess.pgn

# Force UTF-8 output in Windows terminals
sys.stdout.reconfigure(encoding="utf-8")

# 风格模板系统
try:
    from style_templates import get_style_prompt, auto_select_style, list_styles
    HAS_STYLES = True
except ImportError:
    HAS_STYLES = False


def build_system_prompt(style: str = "战术解析", audience: str = "中级",
                        steps: list = None) -> str:
    """构建含风格模板的系统提示词"""
    if HAS_STYLES:
        if style == "auto" and steps:
            style = auto_select_style(steps)
        base = get_style_prompt(style, audience)
    else:
        base = "你是国际象棋特级大师兼优秀教练，正在为一场对局制作视频讲解。"

    return (
        base + "\n\n"
        "请用沉稳、专业、自然的口语化中文生成讲解词。"
        "不要频繁提及'引擎'、'电脑'等词——像人类教练一样直接分析。"
    )

COACH_USER_PROMPT_TEMPLATE = """你是国际象棋特级大师兼优秀教练，正在为一场对局制作视频讲解。下面是棋局分析数据和开局信息。

【讲解要求】
1. 对每一步棋都进行解说，不要跳过任何一步。
2. 篇幅控制：
   - 非常好: 25~40 字（精彩着法，表扬并简要说明好在哪）
   - 正常: 15~25 字（如"白方正常出子，马f3"）
   - 有疑问: 80~120 字（解释为什么不好、后果、正确走法）
   - 错误: 120~180 字（详细分析错误原因、推荐变化、评估差距）
   - 大错: 180~250 字（深入剖析败着，说明对局面的毁灭性影响，给出完整的变化）
3. 【重要】画面动作指令 — 在解说中嵌入画面指令来控制棋盘高亮和箭头：
   格式: [STEP N] [高亮 <格子>] [箭头 <起点>-<终点>] 解说文字...

   - [高亮 e4] 高亮一个格子
   - [高亮 e4,f7] 同时高亮多个格子（逗号分隔）
   - [箭头 d1-h5] 画出红色箭头（斜线/直线进攻路线）

   使用规则：
   - 每一步都可以加画面指令，也可以不加
   - 高亮走棋的起点和终点是基本要求
   - 提到关键威胁或弱点格时加高亮
   - 描述进攻路线时用箭头
   - 画面指令放在 [STEP N] 之后、解说文字之前
   例如: [STEP 12] [高亮 e4,e5] [箭头 d1-h5] 白方e4兵是核心支点，白后沿d1-h5斜线杀出！

4. 开局识别：
   - 开局名称: {opening}（ECO: {eco}）
   - 对阵: {white} vs {black}
   - 前 10 步: {first_10_moves}
   - 请在解说开局阶段简单介绍一下这个开局的特点、白黑双方的意图
5. 棋子和坐标一定要讲准确，不要乱说。
6. 整个解说要连贯，就像你在对着棋盘录制视频一样。
7. 【多引擎交叉验证】当步骤数据中包含 cross_validation 字段时，说明经过了 Stockfish 和 Lc0 神经网络的双重验证。请根据 disagreement_type 来讲解：
   - agree (一致): 简单提一句"两个引擎看法一致"，增强权威感
   - disagree_mild (轻微分歧): "传统引擎和神经网络对这里略有不同看法…局面可能有动态因素"
   - disagree_strong (强烈分歧): 这是讲解的黄金时刻！要大讲特讲：
     "有意思的是，引擎看法不一致！Stockfish认为白方占优，但Lc0神经网络认为黑方更有潜力。这就是经典的静态评价与动态补偿之争！"
   - lc0_surprise (Lc0惊喜): "在神经网络看来，这一方有出人意料的退路/潜力…"
   引擎分歧的步骤可多分配30~50字做深度分析。
8. 请用以下格式输出：每一步的解说放在单独一行，并以"[STEP 编号]"开头。例如：
   [STEP 1] 白方第一步走e4，这是最常见的王前兵开局，占领中心。
   [STEP 2] 黑方应以c5，西西里防御！意图从侧翼反击，避免对称。

下面是棋局分析数据（包含每一步的走法、引擎评分、质量判定和推荐走法）：

{steps_json}

请开始讲解，注意篇幅控制和讲解质量："""


def extract_opening_info(pgn_path: Path) -> dict:
    """从 PGN 文件中提取开局信息"""
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
        "white": headers.get("White", "未知"),
        "black": headers.get("Black", "未知"),
        "opening": headers.get("Opening", "未知"),
        "eco": headers.get("ECO", "未知"),
        "first_10_moves": " ".join(moves),
    }


def load_analysis_data(json_path: Path) -> list:
    """从 JSON 文件加载分析数据"""
    if not json_path.exists():
        raise FileNotFoundError(f"分析数据文件不存在: {json_path}")
    
    with json_path.open("r", encoding="utf-8") as f:
        steps = json.load(f)
    return steps


def generate_with_openai(steps: list, api_key: str, model: str = "gpt-4o",
                          opening_info: dict = None,
                          style: str = "战术解析", audience: str = "中级") -> str:
    """使用 OpenAI API 生成讲解词"""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai 库: pip install openai")
    
    print(f"正在连接 OpenAI API (模型: {model})...")
    
    client = OpenAI(api_key=api_key, base_url="https://api.openai.com/v1")
    
    steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
    if opening_info is None:
        opening_info = {
            "white": "未知",
            "black": "未知",
            "opening": "未知",
            "eco": "未知",
            "first_10_moves": "",
        }
    
    user_prompt = COACH_USER_PROMPT_TEMPLATE.format(
        opening=opening_info["opening"],
        eco=opening_info["eco"],
        white=opening_info["white"],
        black=opening_info["black"],
        first_10_moves=opening_info["first_10_moves"],
        steps_json=steps_json
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(style, audience, steps)},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
    )
    
    return response.choices[0].message.content


def generate_with_deepseek(steps: list, api_key: str, model: str = "deepseek-chat",
                            opening_info: dict = None,
                            style: str = "战术解析", audience: str = "中级") -> str:
    """使用 DeepSeek API 生成讲解词"""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai 库: pip install openai")
    
    print(f"正在连接 DeepSeek API (模型: {model})...")
    
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com/v1")
    
    steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
    if opening_info is None:
        opening_info = {
            "white": "未知",
            "black": "未知",
            "opening": "未知",
            "eco": "未知",
            "first_10_moves": "",
        }
    
    user_prompt = COACH_USER_PROMPT_TEMPLATE.format(
        opening=opening_info["opening"],
        eco=opening_info["eco"],
        white=opening_info["white"],
        black=opening_info["black"],
        first_10_moves=opening_info["first_10_moves"],
        steps_json=steps_json
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(style, audience, steps)},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
    )
    
    return response.choices[0].message.content


def generate_with_ollama(steps: list, model: str = "qwen2.5:7b",
                          base_url: str = "http://localhost:11434/v1",
                          opening_info: dict = None,
                          style: str = "战术解析", audience: str = "中级") -> str:
    """使用 Ollama 本地模型生成讲解词"""
    try:
        from openai import OpenAI
    except ImportError:
        raise ImportError("请先安装 openai 库: pip install openai")
    
    print(f"正在连接本地 Ollama (模型: {model}, 地址: {base_url})...")
    
    client = OpenAI(api_key="ollama", base_url=base_url)
    
    steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
    if opening_info is None:
        opening_info = {
            "white": "未知",
            "black": "未知",
            "opening": "未知",
            "eco": "未知",
            "first_10_moves": "",
        }
    
    user_prompt = COACH_USER_PROMPT_TEMPLATE.format(
        opening=opening_info["opening"],
        eco=opening_info["eco"],
        white=opening_info["white"],
        black=opening_info["black"],
        first_10_moves=opening_info["first_10_moves"],
        steps_json=steps_json
    )
    
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": build_system_prompt(style, audience, steps)},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0.7,
    )
    
    return response.choices[0].message.content


def save_commentary(commentary: str, output_path: Path):
    """保存讲解词到文件"""
    with output_path.open("w", encoding="utf-8") as f:
        f.write(commentary)
    print(f"\n✓ 讲解词已保存到: {output_path}\n")


def main():
    script_dir = Path(__file__).parent
    analysis_file = script_dir / "analysis_result.json"
    
    # 检查分析数据是否存在
    if not analysis_file.exists():
        print("❌ 错误: 找不到 analysis_result.json")
        print("请先运行 analyse.py 生成分析数据")
        return
    
    # 加载分析数据
    print("正在加载分析数据...")
    steps = load_analysis_data(analysis_file)
    print(f"✓ 加载成功，共 {len(steps)} 步\n")
    
    # 提取开局信息
    print("正在提取开局信息...")
    pgn_files = list(Path(analysis_file.parent).glob("lichess_pgn*.pgn"))
    opening_info = None
    if pgn_files:
        try:
            opening_info = extract_opening_info(pgn_files[0])
            print(f"✓ 开局: {opening_info['opening']} ({opening_info['eco']})\n")
        except Exception as e:
            print(f"⚠ 无法提取开局信息: {e}\n")
    
    # 选择 LLM 方案
    print("="*60)
    print("选择 LLM 方案:")
    print("1. OpenAI API (需要 API Key)")
    print("2. DeepSeek API (需要 API Key)")
    print("3. Ollama 本地模型 (需要本地运行 Ollama)")
    print("="*60)
    
    choice = input("\n请选择 (1/2/3): ").strip()
    
    try:
        if choice == "1":
            api_key = input("请输入 OpenAI API Key: ").strip()
            if not api_key:
                print("❌ API Key 不能为空")
                return
            
            model = input("请输入模型名称 (默认: gpt-4o): ").strip()
            if not model:
                model = "gpt-4o"
            
            print("\n开始生成讲解词...")
            commentary = generate_with_openai(steps, api_key, model, opening_info, style=style, audience=audience)
        
        elif choice == "2":
            api_key = input("请输入 DeepSeek API Key: ").strip()
            if not api_key:
                print("❌ API Key 不能为空")
                return
            
            model = input("请输入模型名称 (默认: deepseek-chat): ").strip()
            if not model:
                model = "deepseek-chat"
            
            print("\n开始生成讲解词...")
            commentary = generate_with_deepseek(steps, api_key, model, opening_info, style=style, audience=audience)
        
        elif choice == "3":
            model = input("请输入模型名称 (默认: qwen2.5:7b): ").strip()
            if not model:
                model = "qwen2.5:7b"
            
            base_url = input("请输入 Ollama 地址 (默认: http://localhost:11434/v1): ").strip()
            if not base_url:
                base_url = "http://localhost:11434/v1"
            
            print("\n开始生成讲解词...")
            commentary = generate_with_ollama(steps, model, base_url, opening_info, style=style, audience=audience)
        
        else:
            print("❌ 无效的选择")
            return
        
        # 保存讲解词
        output_file = script_dir / "commentary.txt"
        save_commentary(commentary, output_file)
        
        # 显示摘要
        print("="*60)
        print("讲解词摘要（前 800 字）:")
        print("="*60)
        print(commentary[:800] + "\n...\n")
        
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        print("\n排查建议:")
        print("- 如果选择 OpenAI: 确认 API Key 有效")
        print("- 如果选择 DeepSeek: 确认 API Key 有效")
        print("- 如果选择 Ollama: 确认已运行 `ollama serve`，并可访问 http://localhost:11434")


if __name__ == "__main__":
    main()
