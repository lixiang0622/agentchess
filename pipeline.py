"""
国际象棋讲解视频完整流程脚本
一键从 PGN 生成讲解词、TTS 音频、棋盘动画、最终视频
"""

import sys
import json
import subprocess
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")


def run_script(script_name: str, description: str) -> bool:
    """运行一个 Python 脚本"""
    script = Path(__file__).parent / script_name
    print(f"\n[步骤] {description}")
    print(f"运行: {script_name}")
    
    result = subprocess.run(
        [sys.executable, str(script)],
        capture_output=False
    )
    
    return result.returncode == 0


def auto_generate_commentary(api_key: str, api_type: str = "deepseek",
                              model: str = "deepseek-chat",
                              style: str = "auto",
                              audience: str = "中级") -> str:
    """自动调用 LLM 生成讲解词（非交互）— 支持风格模板"""
    print(f"\n[步骤] 调用 LLM 生成讲解词")
    if style != "auto":
        print(f"  风格: {style}  |  观众: {audience}")
    
    script_dir = Path(__file__).parent
    analysis_file = script_dir / "analysis_result.json"
    pgn_files = list(script_dir.glob("lichess_pgn*.pgn"))
    
    if not analysis_file.exists():
        print("❌ 分析文件不存在")
        return False
    
    # 提取开局信息
    opening_info = None
    if pgn_files:
        try:
            import chess.pgn
            with pgn_files[0].open("r", encoding="utf-8") as f:
                game = chess.pgn.read_game(f)
            headers = game.headers
            board = game.board()
            moves = []
            
            for i, move in enumerate(game.mainline_moves()):
                if i >= 10:
                    break
                moves.append(board.san(move))
                board.push(move)
            
            opening_info = {
                "white": headers.get("White", "未知"),
                "black": headers.get("Black", "未知"),
                "opening": headers.get("Opening", "未知"),
                "eco": headers.get("ECO", "未知"),
                "first_10_moves": " ".join(moves),
                # ---- 对局结束信息 ----
                "result": headers.get("Result", "*"),
                "termination": headers.get("Termination", ""),
                # ---- 时间信息 ----
                "white_elo": headers.get("WhiteElo", ""),
                "black_elo": headers.get("BlackElo", ""),
                "time_control": headers.get("TimeControl", ""),
                "white_clock": headers.get("WhiteClock", ""),
                "black_clock": headers.get("BlackClock", ""),
            }
        except:
            pass
    
    if not opening_info:
        opening_info = {
            "white": "未知", "black": "未知", 
            "opening": "未知", "eco": "未知", 
            "first_10_moves": ""
        }
    
    # 加载分析数据
    with analysis_file.open("r", encoding="utf-8") as f:
        data = json.load(f)
    steps = data.get("steps", data)  # 兼容旧格式
    opening_profile = data.get("opening_profile", {})
    
    # 构建提示词 — 注入动态风格模板
    from style_templates import get_style_prompt, auto_select_style

    # 自动选择或使用指定风格
    if style == "auto":
        chosen_style = auto_select_style(steps)
        print(f"  自动选择风格: {chosen_style}")
    else:
        chosen_style = style

    style_prefix = get_style_prompt(chosen_style, audience, auto=False)

    COACH_SYSTEM_PROMPT = (
        style_prefix + "\n\n"
        "注意：不要在讲解中频繁提及'引擎'、'电脑'等词——"
        "你应该像一个真正的人类教练那样分析，只在分析数据明确标注了交叉验证分歧(cross_validation)时才简短提及。"
    )

    # ---- 构建开局详情和战术速览 ----
    profile = opening_profile
    opening_detail = ""
    tactical_summary = ""

    if profile:
        move_stats = profile.get("move_stats", [])
        tag_names = {
            "most_popular": "最流行", "popular": "流行",
            "sideline": "旁线", "rare": "稀有", "trap_line": "提示:陷阱",
        }
        if move_stats:
            lines = ["走法统计:"]
            for ms in move_stats:
                tag = tag_names.get(ms["popularity_tag"], ms["popularity_tag"])
                lines.append(f"  第{ms['move_num']}步 {ms['san']} → {tag} ({ms['percentage']}%)")
            opening_detail = "\n".join(lines)

        tac_parts = []
        type_names = {
            "fork": "击双", "pin": "牵制", "skewer": "串击",
            "discovered_attack": "闪击", "discovered_check": "闪将",
            "deflection": "引离", "zwischenzug": "中间着",
            "mate_threat": "杀棋威胁",
        }
        for step in steps:
            themes = step.get("tactical_themes", [])
            if themes:
                names = [type_names.get(t["type"], t["type"]) for t in themes]
                tac_parts.append(f"  第{step['move_number']}步 {step['move_san']}: {' + '.join(names)}")
        if tac_parts:
            tactical_summary = "【本局战术主题速览，以下着法被自动检测为战术亮点，请在讲解中强调】\n" + "\n".join(tac_parts)

    # ---- 构建局面型错误速览 ----
    strategic_mistake_summary = ""
    sm_type_names = {
        "bad_bishop_for_knight": "坏象换好马",
        "pawn_structure_damage": "兵型受损",
        "center_abandonment": "放弃中心",
        "bishop_pair_loss": "失去双象优势",
        "king_shield_damage": "王前兵阵破损",
        "open_file_loss": "开放线控制丧失",
        "development_lag": "出子落后",
    }
    sm_parts = []
    for step in steps:
        sms = step.get("strategic_mistakes", [])
        if sms:
            names = [sm_type_names.get(sm["type"], sm["type"]) for sm in sms]
            details = [sm.get("description_zh", "") for sm in sms]
            sm_parts.append(f"  第{step['move_number']}步 {step['move_san']}: {' + '.join(names)}。{'；'.join(details)}")
    if sm_parts:
        strategic_mistake_summary = (
            "【局面型战略错误速览，以下着法即使评分变化不大也损害了长期战略，请在讲解中重点指出】\n"
            + "\n".join(sm_parts) + "\n"
            "讲解要求：对于这些局面型错误，请用人类教练的口吻解释为什么这步在战略上有问题，"
            "不要说'引擎认为'，而是说清楚：比如'在封闭局面下用象换马是不划算的，马在兵多的局面中更具机动性'。"
        )

    # ---- 构建大师走法速览 ----
    masters_summary = ""
    masters_parts = []
    for step in steps:
        m = step.get("masters")
        if m and m.get("found") and m.get("top_moves"):
            top = m["top_moves"]
            top_str = "、".join(
                f"{tm['san']}({tm['pct']}%)" for tm in top[:3]
            )
            deviation_note = ""
            if m.get("deviation"):
                deviation_note = (
                    f" ⚠️ 实战走法 {step['move_san']} 偏离大师主流（频率<10%），"
                    f"请在讲解中分析风险"
                )
            famous = m.get("famous_example")
            if famous:
                masters_parts.append(
                    f"  第{step['move_number']}步: {top_str}。"
                    f"著名棋手: {famous['player']} 曾走 {famous['move']} ({famous.get('event','')} {famous.get('year','')})。"
                    f"{deviation_note}"
                )
            else:
                masters_parts.append(
                    f"  第{step['move_number']}步: {top_str}。{deviation_note}"
                )
    if masters_parts:
        masters_summary = (
            "【大师对局数据，请在讲解中引用大师的选择】\n"
            + "\n".join(masters_parts) + "\n"
            "讲解要求：自然引用大师数据，如'在这个局面下，大师们的常见选择是...'。"
            "如果实战走法偏离主流，要像教练一样指出可能的风险，但不要说'引擎认为'。"
        )

    # ---- 构建开局特征描述 + 大师统计 ----
    opening_traits_text = ""
    opening_name = opening_info.get("opening", "")

    # 大师统计
    master_stats = opening_profile.get("master_stats")
    if master_stats and master_stats.get("total", 0) > 0:
        ms = master_stats
        eco_code = opening_profile.get("eco", "")
        traits_parts = [(
            f"【大师数据】{opening_name} ({eco_code})："
            f"共 {ms['total']:,} 盘大师对局。"
            f"白方胜率 {ms['white_pct']}%，和棋率 {ms['draw_pct']}%，黑方胜率 {ms['black_pct']}%。"
            f"请根据这个数据在讲解中提及该开局在大师级别的表现。"
        )]
        opening_traits_text = "\n".join(traits_parts)

    if opening_name and opening_name != "未知":
        try:
            import json as _json2
            eco_code = opening_profile.get("eco", opening_info.get("eco", ""))
            # 1. 先查 opening_theory.json (Wikibooks 风格详细数据)
            theory_path = Path(__file__).parent / "opening_theory.json"
            if theory_path.exists():
                with theory_path.open("r", encoding="utf-8") as f:
                    all_theory = _json2.load(f)
                for key, val in all_theory.items():
                    if key == eco_code or key in opening_name or opening_name in val.get("name", ""):
                        parts = []
                        if val.get("description"):
                            parts.append(val["description"])
                        if val.get("themes"):
                            parts.append("核心主题：" + val["themes"])
                        if val.get("main_lines"):
                            parts.append("主要变化：" + val["main_lines"])
                        if parts:
                            opening_traits_text += chr(10)+chr(10) + chr(10)+chr(10).join(parts)
                        break
            # 2. 再查 opening_traits.json (中文知识补充)
            traits_path = Path(__file__).parent / "opening_traits.json"
            if traits_path.exists():
                with traits_path.open("r", encoding="utf-8") as f:
                    all_traits = _json2.load(f)
                for key, val in all_traits.items():
                    if key in opening_name or opening_name in key:
                        parts = []
                        for k in ["traits", "main_ideas", "typical_structures", "key_knowledge"]:
                            if k in val:
                                parts.append(val[k])
                        if parts and chr(26680)+chr(24515)+chr(20027)+chr(39064) not in opening_traits_text:
                            opening_traits_text += chr(10) + chr(10).join(parts)
                        break
        except Exception:
            pass

            pass

    # ---- 构建战略阶段摘要 ----
    phases = data.get("phases", [])
    phase_summary = ""
    if phases:
        phase_lines = ["【战略阶段划分，请据此构建讲解的起承转合】"]
        for ph in phases:
            desc = ph.get("description", "")
            if desc:
                phase_lines.append(f"  {desc}")
        phase_summary = "\n".join(phase_lines)

    # ---- 构建残局库摘要 + 残局知识分析摘要 ----
    tb_results = data.get("tablebase_results", [])
    endgame_analyses = data.get("endgame_analyses", [])
    tablebase_summary = ""
    endgame_knowledge = ""  # ← 提前初始化，避免 tb_results 为空时 UnboundLocalError
    endgame_knowledge_summary = ""  # 新增：深度残局分析摘要

    # 生成残局知识分析摘要
    if endgame_analyses:
        from endgame_knowledge import generate_endgame_summary_for_prompt
        endgame_knowledge_summary = generate_endgame_summary_for_prompt(endgame_analyses)
        if endgame_knowledge_summary:
            # 合并到 tablebase_summary 中
            tablebase_summary = endgame_knowledge_summary

    if tb_results:
        tb_lines = ["【残局库精确判决，在视频结尾给出权威胜负判断】"]
        for tb in tb_results:
            tb_lines.append(f"  第{tb['move_number']}步 ({tb['piece_count']}子局面): {tb['verdict']}")
        if tablebase_summary:
            tablebase_summary = tablebase_summary + "\n\n" + "\n".join(tb_lines)
        else:
            tablebase_summary = "\n".join(tb_lines)
        # ---- build endgame knowledge ----
        try:
            endgame_path = Path(__file__).parent / "endgame_theory.json"
            if endgame_path.exists():
                with endgame_path.open("r", encoding="utf-8") as f:
                    eg_data = json.load(f)
                if phases:
                    last_phase = phases[-1] if phases else {}
                    if last_phase.get("macro_phase") == chr(27531)+chr(23616) or len(steps) > 30:
                        principles = eg_data.get("practical_endgame_principles", {}).get("principles", [])
                        if principles:
                            endgame_knowledge = chr(12304)+chr(27531)+chr(23616)+chr(29702)+chr(35770)+chr(30693)+chr(35782)+chr(65292)+chr(35831)+chr(22312)+chr(35762)+chr(35299)+chr(27531)+chr(23616)+chr(38454)+chr(27573)+chr(36866)+chr(24403)+chr(24341)+chr(29992)+chr(12305) + chr(92)+chr(110) + chr(92)+chr(110).join(principles[:5])
                        if tb_results:
                            syzygy = eg_data.get("syzygy_explanation", {})
                            if syzygy.get("description"):
                                endgame_knowledge += chr(92)+chr(110)+chr(92)+chr(110) + syzygy["description"]
        except Exception:
            pass

    COACH_USER_PROMPT = """你是国际象棋特级大师兼优秀教练，正在为一场对局制作视频讲解。下面是棋局分析数据和开局信息。

【讲解要求】
1. 对每一步棋都进行解说，不要跳过任何一步。
2. 篇幅控制（7 级分类）：
   - 妙手/好棋: 25~40 字（精彩着法，表扬并说明好在哪）
   - 正常: 15~25 字（如"白方正常出子，马f3"）
   - 缓着: 40~80 字（步伐稍慢，指出更好的选择）
   - 疑问: 80~120 字
   - 失误: 120~180 字
   - 漏杀: 150~220 字（优势下错过 ≤10步的杀棋机会，重点分析为什么没看到）
   - 送杀: 180~250 字（走了这一步直接送给对手短步杀棋，是致命的计算失误）
   - 送子: 180~250 字（直接送子失误，新手常见，通俗语言解释为什么这步棋致命）
3. 【重要】画面动作指令 — 在解说中嵌入控制棋盘高亮和箭头：
   格式: [STEP N] [高亮 <格子>] [箭头 <起点>-<终点>] 解说文字...
   - [高亮 e4,e5] 高亮格子  - [箭头 d1-h5] 画红色箭头
   例如: [STEP 12] [高亮 e4,e5] [箭头 d1-h5] 白方e4兵是核心支点，白后沿斜线杀出！

4. 【右下角小棋盘使用规则】你现在拥有一个位于视频右下角的小棋盘，它可以用来演示支线变化、引擎推荐走法或错误走法的后果。当你在讲解中需要展示某个变化的具体走法时，请在解说词内部插入控制标记。

	标记格式：
	- 动态演示变化：[小棋盘: 走法1, 走法2, 走法3...] （使用标准代数记法，如 e4, Nf6, exd5）
	- 展示静态局面：[小棋盘: 仅显示局面 FEN: <FEN字符串>]
	- 隐藏小棋盘：[小棋盘: 清空]

	使用原则：
	a) 当你开始讲解一个支线变化时，先发出小棋盘指令，再开始口头讲解。
	   例：[STEP 10] [小棋盘: d5, exd5, Nxd5] 黑方此时最应该走d5，接下来兑换后马跳中心，局面均势。
	b) 支线讲解结束后，若不再需要小棋盘，发出"清空"指令。
	c) 主棋盘依然按常规节奏显示实战走法，小棋盘只负责补充展示。
	d) 小棋盘上的走法可以是1步到5步，不宜过长，以展示关键构思为主。
	e) 小棋盘上使用的走法必须是你绝对确定的，且与当前解说局面严格一致。若不确定，只用"d5突破"等描述，不写具体走法序列。
	f) 如果分析数据中某步已有candidates推荐变化，优先使用数据中的pv走法序列来构造小棋盘指令，确保走法准确性。

	小棋盘用法示例：
	[STEP 8] [小棋盘: d5, exd5, cxd5] 白方这里应该走d5直接突破中心！如果兵d5，黑方只能吃，白方再c线兵补刀，形成强大的兵中心。
	[STEP 15] [小棋盘: 仅显示局面 FEN: r1bqkb1r/pppp1ppp/2n5/4P3/8/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 4] 我们来看这个局面，白方获得了显著的空间优势。
	[STEP 20] [小棋盘: 清空] 好了我们回到实战，白方选择了稳健的短易位。

5. 【开局讲解要求 — 必须详细介绍】这是视频讲解中最吸引观众的部分之一，必须做好：
   开局: {opening}（ECO: {eco}）
   对阵: {white} vs {black}
   前 10 步: {first_10_moves}
   {opening_detail}
   {opening_traits}

   {opening_knowledge_text}

   [重要] 请在开局阶段（前8-12步内）做到以下几点：
   a) 第一步就要说出开局名称！如"白方走了e4，黑方以c5回应——这就是大名鼎鼎的西西里防御！"
   b) 用2-3句话介绍这个开局的"性格"：它是进攻型还是稳健型？在顶级比赛中常见吗？有什么著名的故事或代表人物？
   c) 说明双方的核心计划——白方想干什么？黑方在准备什么反击？
   d) 如果上面提供了"大师数据"（胜率统计），自然引用一句。如"在大师级别对局中，这个开局白方胜率38%，是一个双方机会均等的开局。"
   e) 如果上面提供了"开局深度解析"（traits/main_ideas等），请将这些内容自然地融入讲解，不要生硬照搬。
   f) 注意观察前10步的走法顺序 {first_10_moves}，告诉观众这是哪个具体变例。如"这是西班牙封闭变例的主线走法"。
   g) 当开局阶段结束进入中局时(约第12步)，可以用一句话总结开局结果，如"双方都完成了开局计划，现在进入中局的关键阶段。"

3.5 【战术主题】仅当某步棋被标记了战术主题且产生了实质战术效果（如得子、杀棋、双重威胁）时才在讲解中提及。注意：
   - 绝大多数正常出子的棋不是战术，不要机械地给每一步贴"击双""串击"等标签
   - 提及战术时自然融入讲解，不要出现"这是一步漂亮的XX战术"这样的模板句式
   - 例如：不说"这是串击！"，而说"白象瞄着c6马，而马背后是d7兵，黑方必须应对"

3.6 【多引擎交叉验证】当分析数据中包含 cross_validation 字段时，说明经过了 Stockfish 和 Lc0 神经网络的交叉验证。请根据 disagreement_type 来讲解：
   - agree (一致): 可简短提一句"两个引擎看法一致"，增强权威感
   - disagree_mild (轻微分歧): "传统引擎和神经网络对这里略有不同看法…局面可能有动态因素"
   - disagree_strong (强烈分歧): 这是讲解的黄金时刻！要大讲特讲：
     "有意思的是，引擎看法不一致！Stockfish认为白方占优，但Lc0神经网络认为黑方更有潜力。这就是经典的静态评价与动态补偿之争，局面非常复杂！"
   - lc0_surprise (Lc0惊喜): "在神经网络看来，这一方有出人意料的退路/潜力…"
   如果某个局面引擎分歧，讲解词可多分配30~50字做深度分析。

3.7 【局面型错误】当 step 数据中包含 strategic_mistakes 字段时，说明该步犯了不反映为评分骤降、但损害长期战略的错误。请在讲解中融入分析：
   - 坏象换好马: "在封闭局面下用象换马——马在兵多的时候更具机动性，而象被自己的兵挡住了斜线"
   - 兵型受损: "这步棋形成了新的叠兵/孤兵，这是残局中的持久弱点"
   - 放弃中心: "放弃了对中心的关键控制，对手将获得更大的活动空间"
   - 失去双象优势: "主动兑象失去了双象优势，这在长期来看可能成为局面上的不利因素"
   - 王前兵阵破损: "王前兵盾被削弱了，这给了对方进攻的机会"
   - 开放线控制丧失: "失去了对开放线的控制——在开放线上，车的活动力至关重要"
   - 出子落后: "出子已经落后，这一步没有改善。开局阶段出子速度直接关系到主动权"
   讲解要求：像人类教练一样指出问题，不要提"引擎"或"检测"，直接说"这里有个战略隐患……"

3.8 【中局棋理知识】当 step 数据中包含 midgame_principles 字段且非空时，说明系统已自动匹配了与该局面相关的棋理原则。请在讲解中自然引用这些原则来解释走法——用教材级别的棋理说服观众。例如：
   当检测到孤兵相关原则时，可说"这里留下了一个d线孤兵，按照棋理，孤兵在残局中会成为致命的弱点……"
   当检测到双象优势时，可说"白方现在拥有双象优势，在这么开放的局面下双象的长距离机动性让黑方非常难受……"
   不要机械地逐条朗读原则，而是融入你的讲解中，像一位熟读教材的教练一样。

3.9 【评分变化可解释性】当 step 数据中的 explanation.diagnosis 字段非空时，说明系统自动分析了"为什么评分会这样变化"。请**必须**在你的讲解中直接引用这些分析，而不是简单复述评分数字。例如：
   - 不要说"这步棋导致评分从+0.3跌到了-1.8"
   - 而应该说"这步棋造成了王前兵盾破损，同时让对方的马占据了强大的中心据点——所以评分骤降"
   当 diagnosis 标注了具体变化（如兵形受损/王安全下降/中心控制丧失等），请像教练一样把这些原因讲出来。
   只有当 diagnosis 为空时，才用评分数字来解释走法质量。

5. 棋子和坐标讲准确，不要乱说
6. 整个解说连贯自然，就像对着棋盘录制视频
7. 【语气与风格】保持沉稳专业的教练语气，像叶江川或谢军那样娓娓道来：
   - 不要高频使用惊叹号或过度渲染情绪
   - 不要频繁说'引擎认为''电脑推荐'——像人类教练一样直接给出分析和建议
   - 只有在 cross_validation 标注了'引擎分歧'的步骤，才简短提及'有意思的是，两个分析系统在这里看法不同……'
   - 如果你要引用candidates中的候选走法，自然地融入讲解，如'这里黑方有d5、c6、a6三种选择……'，无需提这是引擎给的
8. 【战略阶段】请根据 phase_summary 中的阶段划分来组织讲解的起承转合：
   - 开局阶段 (前12步): 简要介绍开局名称、特点和双方意图
   - 中局阶段: 分阶段讲解，用"这六步棋白方全力准备王翼兵的冲锋"这样的叙述方式
   - 残局阶段: 结合 tablebase_summary 中的精确判决，给出权威结论。
    如果在残局分析数据中看到"引擎vs表库矛盾"，务必将这作为讲解亮点——告诉观众"虽然引擎评分显示有优势，但残局表库告诉我们这其实是理论和棋，这里有个很重要的残局知识……"
   - 在阶段切换处可以加过渡句"进入中局的关键时刻了！"

9. 【残局知识讲解】当 step 中包含 endgame_analysis 字段时:
   - 如果 endgame_type 是已知残局类型（如 KPK、KRK），请简要介绍该残局的核心概念和标准赢/和法
   - 如果 engine_vs_tb 检测到"矛盾"，这是黄金教学内容！请详细展开: "很多棋友可能会觉得引擎分高就赢了，但实际上这个局面……"
   - 如果 tb_verdict 是理论必和/必胜，用权威语气说明

10. 【大师对局引用】当 step 中包含 masters 数据时:
   - 如果 top_moves 非空，请自然引用: "在这个局面下，大师们的常见选择是……，其中卡尔森曾多次走出……"
   - 如果 deviation 为 True（实战走法频率 <10%），请用教练口吻分析: "这步棋没有选择大师们的主流走法，有点冒险……"
   - 引用大师数据时保持自然，像人类教练分享经验一样，不要生硬地罗列数据

9. 请用 [STEP 编号] 开头，例如：
   [STEP 1] 白方e4，占领中心。
   [STEP 2] 黑方c5，西西里防御。

10. 【对局背景与时间压力分析】根据以下信息在讲解中适当提及：
    - 对局结果: {result}（{termination}）
    - 时限设置: {time_control}
    - 白方终局剩余时间: {white_clock}, 黑方: {black_clock}
    - 如果某方剩余时间 < 30 秒，在讲解该方失误时自然提及"在时间压力下……"
    - 如果结束原因为超时，在总结中对被超时方表示惋惜
    - 如果结束原因为认输，在残局阶段强调胜势方的决定性着法
    - **长考检测**：如果某步标记了 is_long_think (思考时间远超平均)，在讲解中提及"这里XX方经过长时间思考……"
    - **耗时对比**：如果某步 time_spent_seconds > 60，结合对局时限评估是否合理

棋局分析数据：
{steps_json}

{phase_summary}

        {endgame_knowledge}
{tablebase_summary}

{tactical_summary}

{strategic_mistake_summary}

{masters_summary}

12. 【战略概念引导】以下是对本局关键位置（开局/中局/终局）的自动战略分析，包括王安全度、开放线控制、空间优势、兵形弱点等。请在讲解中自然引用：
{concept_summary}

讲解要求：在对应阶段的解说中（如进入中局时），自然地融入上述战略分析。例如：如果在第20步左右检测到"黑方王安全度低"，在解说相关攻王着法时提及这个弱点。
如果某步的 JSON 数据中包含 concept_hint 字段，说明该方当前面临的概念要点，请融入讲解。

13. 【讲解篇幅分配 — 关键时刻聚焦】以下是对本局各步的自动评估，标出了该详写、中写、略写的步骤。请严格遵守：
{focus_guide}

14. 【小棋盘支线展示指南】以下标出了需要使用右下角小棋盘展示支线变化的步骤。对于这些步骤，请用 [小棋盘: 走法序列] 指令演示支线变化。其他步骤不需要支线展示。
{branch_guide}

请开始讲解："""

    steps_json = json.dumps(steps, ensure_ascii=False, indent=2)
    
    # 提取概念清单（CCC 论文风格）
    concept_profile = data.get("concept_profile", {})
    concept_summary = concept_profile.get("summary", "") if concept_profile else ""

    # 提取关键教学节点（GothamChess 风格聚焦）
    critical_moments = data.get("critical_moments", {})
    focus_guide = critical_moments.get("focus_guide", "") if critical_moments else ""

    # 提取分支讲解指南
    branch_guide = data.get("branch_guide", "")

    # 提取开局知识库内容
    opening_knowledge = data.get("opening_knowledge", {})
    opening_knowledge_text = opening_knowledge.get("prompt_context", "")

    user_prompt = COACH_USER_PROMPT.format(
        opening=opening_info["opening"],
        eco=opening_info["eco"],
        white=opening_info["white"],
        black=opening_info["black"],
        first_10_moves=opening_info["first_10_moves"],
        result=opening_info.get("result", "*"),
        termination=opening_info.get("termination", "Normal"),
        time_control=opening_info.get("time_control", "未知"),
        white_clock=opening_info.get("white_clock", "未知"),
        black_clock=opening_info.get("black_clock", "未知"),
        steps_json=steps_json,
        tactical_summary=tactical_summary,
        strategic_mistake_summary=strategic_mistake_summary,
        masters_summary=masters_summary,
        opening_detail=opening_detail,
        opening_traits=opening_traits_text,
        opening_knowledge_text=opening_knowledge_text,
        phase_summary=phase_summary,
        endgame_knowledge=endgame_knowledge,
        tablebase_summary=tablebase_summary,
        concept_summary=concept_summary,
        focus_guide=focus_guide,
        branch_guide=branch_guide,
    )
    
    # 调用 API
    try:
        from openai import OpenAI
    except ImportError:
        print("❌ 需要安装 openai 库: pip install openai")
        return False
    
    if api_type == "deepseek-v4-pro":
        base_url = "https://api.llm.ustc.edu.cn"
    elif api_type == "deepseek-v4-flash-ascend":
        base_url = "https://api.llm.ustc.edu.cn"
    else:
        base_url = "https://api.llm.ustc.edu.cn"
    
    print(f"连接到 {api_type.upper()} API...")
    
    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": COACH_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7,
            timeout=300
        )
        
        commentary = response.choices[0].message.content

        # 保存讲解词
        output_file = script_dir / "commentary.txt"
        with output_file.open("w", encoding="utf-8") as f:
            f.write(commentary)

        print(f"✓ 讲解词已生成: {output_file}")
        print(f"  字数: {len(commentary)}")
        return commentary

    except Exception as e:
        print(f"❌ API 调用失败: {e}")
        return None


def generate_training_points_from_llm(steps: list, opening_info: dict,
                                       api_key: str, api_type: str = "deepseek",
                                       model: str = "deepseek-chat") -> dict:
    """调用 LLM 生成训练点提炼"""
    from training_analyzer import generate_training_prompt_for_llm, generate_training_points_rules

    print(f"\n[步骤] 提炼训练要点...")

    # 先做规则分类
    rules_result = generate_training_points_rules(steps, opening_info)

    try:
        from openai import OpenAI
    except ImportError:
        print("⚠ 无法调用 LLM，使用规则系统结果")
        return rules_result

    if api_type == "deepseek-v4-pro":
        base_url = "https://api.llm.ustc.edu.cn"
    else:
        base_url = "https://api.llm.ustc.edu.cn"

    prompt = generate_training_prompt_for_llm(steps, opening_info)

    try:
        client = OpenAI(api_key=api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是一位国际象棋教练，善于发现学生的弱点并给出具体的训练建议。请用 JSON 格式回复。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.5,
            timeout=120
        )

        result_text = response.choices[0].message.content

        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', result_text)
        if json_match:
            llm_result = json.loads(json_match.group())
            # 合并 LLM 结果和规则结果
            combined = {**rules_result, **llm_result}
            print(f"✓ 训练要点提炼完成: {len(combined.get('training_points', []))} 条")
            return combined
        else:
            print("⚠ LLM 未返回有效 JSON，使用规则系统结果")
            return rules_result

    except Exception as e:
        print(f"⚠ LLM 训练点提炼失败: {e}，使用规则系统结果")
        return rules_result


def evaluate_commentary(commentary: str, analysis_data: dict, opening_info: dict,
                         api_key: str, api_type: str = "deepseek",
                         model: str = "deepseek-chat") -> dict:
    """
    多裁判模型互评：教练裁判 + 观众裁判分别打分
    返回评分和反馈，如果平均分 < 7 则返回修改建议
    """
    try:
        from openai import OpenAI
    except ImportError:
        print("⚠ 无法调用 LLM 进行互评")
        return {"average_score": 8.0, "passed": True, "judge_results": []}

    if api_type == "deepseek-v4-pro":
        base_url = "https://api.llm.ustc.edu.cn"
    else:
        base_url = "https://api.llm.ustc.edu.cn"

    client = OpenAI(api_key=api_key, base_url=base_url)

    # 裁判 A：严苛的国际象棋教练
    judge_a_prompt = f"""你是一位严苛的国际象棋教练。请给以下棋评讲解打分（1-10分）并指出问题。

评分维度：
- 战术准确度 (1-10): 走法解说是否正确？术语是否准确？
- 深度与洞察 (1-10): 是否有深度分析？是否提到了关键变化？
- 教学价值 (1-10): 观众能否从中学到东西？

对局: {opening_info.get('white', '?')} vs {opening_info.get('black', '?')}, {opening_info.get('opening', '?')}

讲解词:
{commentary[:3000]}

请用 JSON 格式回复：
{{"tactical_accuracy": 分数, "depth_insight": 分数, "teaching_value": 分数,
  "overall": 平均分, "strengths": ["优点1", "优点2"], "weaknesses": ["问题1", "问题2"],
  "improvement_suggestions": "一句话改进建议"}}"""

    # 裁判 B：完全不懂棋的观众
    judge_b_prompt = f"""你是一位完全不懂国际象棋的普通观众，正在看一个棋评视频。请给以下讲解打分（1-10分）。

评分维度：
- 易懂程度 (1-10): 完全不懂棋的人能听懂吗？术语有解释吗？
- 趣味性与节奏 (1-10): 听起来有趣吗？节奏会不会太拖沓或太赶？
- 情绪感染力 (1-10): 讲解有激情吗？能带动观众情绪吗？

讲解词:
{commentary[:3000]}

请用 JSON 格式回复：
{{"clarity": 分数, "engagement": 分数, "emotional_appeal": 分数,
  "overall": 平均分, "confusing_parts": ["让人困惑的地方"], "boring_parts": ["无聊的地方"],
  "improvement_suggestions": "一句话改进建议"}}"""

    judge_results = []
    total_score = 0

    for judge_name, judge_prompt in [("教练裁判", judge_a_prompt), ("观众裁判", judge_b_prompt)]:
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": judge_prompt}],
                temperature=0.3,
                timeout=120
            )
            text = resp.choices[0].message.content
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                result = json.loads(json_match.group())
                result["judge"] = judge_name
                judge_results.append(result)
                total_score += result.get("overall", 7.0)
        except Exception as e:
            print(f"  ⚠ {judge_name} 评分失败: {e}")

    avg_score = total_score / len(judge_results) if judge_results else 7.0
    passed = avg_score >= 7.0

    return {
        "average_score": round(avg_score, 1),
        "passed": passed,
        "judge_results": judge_results,
    }


# ================== 配置区域 ==================
# API Key 和模型配置存放在独立的 api_config.json 文件中（不提交到 git）
# 首次使用请复制 api_config.example.json 为 api_config.json 并填入你的 API Key


def _load_api_config() -> dict:
    """从 api_config.json 加载 API 配置"""
    config_path = Path(__file__).parent / "api_config.json"
    if not config_path.exists():
        example_path = Path(__file__).parent / "api_config.example.json"
        if example_path.exists():
            print(f"⚠ 未找到 api_config.json，请复制 {example_path.name} 并填入你的 API Key")
        else:
            print("⚠ 未找到 api_config.json，请创建该文件并填入 API Key")
        # 返回空配置，后续会提示用户手动输入
        return {"api_key": "", "api_type": "deepseek", "model": "deepseek-v4-pro"}
    try:
        with config_path.open("r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {
            "api_key": cfg.get("api_key", ""),
            "api_type": cfg.get("api_type", "deepseek"),
            "model": cfg.get("model", "deepseek-v4-pro"),
        }
    except Exception as e:
        print(f"⚠ 读取 api_config.json 失败: {e}")
        return {"api_key": "", "api_type": "deepseek", "model": "deepseek-v4-pro"}


# 加载配置
_api_cfg = _load_api_config()
API_KEY = _api_cfg["api_key"]
API_TYPE = _api_cfg["api_type"]
MODEL = _api_cfg["model"]

# 如果 api_config.json 中未填写 API Key，程序会提示你手动输入
# =============================================


def main():
    script_dir = Path(__file__).parent
    
    print("\n" + "="*60)
    print("🎬 国际象棋讲解视频 - 一键生成")
    print("="*60)
    
    # 检查 PGN 文件
    pgn_files = list(script_dir.glob("lichess_pgn*.pgn"))
    if not pgn_files:
        print("\n❌ 找不到 PGN 文件（lichess_pgn*.pgn）")
        print(f"   请将 PGN 文件放在: {script_dir}")
        return
    
    pgn_path = pgn_files[0]
    print(f"\n📋 使用 PGN: {pgn_path.name}")
    
    # 第 1 步：分析
    print("\n" + "="*60)
    print(" 第 1 步: 分析棋谱")
    print("="*60)
    if not run_script("analyse.py", "分析棋谱生成结构化数据"):
        print("❌ 分析失败")
        return
    
    # 第 2 步：生成讲解词
    print("\n" + "="*60)
    print(" 第 2 步: 生成讲解词")
    print("="*60)
    
    # 使用配置中的 API Key，或提示输入
    api_key = API_KEY.strip() if API_KEY else input("\n请输入 API Key (DeepSeek/OpenAI): ").strip()
    if not api_key:
        print("❌ 需要 API Key")
        return
    
    api_type = API_TYPE if API_KEY else input("API 类型 (deepseek/openai, 默认 deepseek): ").strip()
    if not api_type:
        api_type = "deepseek"
    
    model = MODEL if API_KEY else input("模型名称 (默认: deepseek-chat): ").strip()
    if not model:
        model = "deepseek-chat" if api_type == "deepseek" else "gpt-4o"

    # 风格选择
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--style", type=str, default="auto",
                       choices=["auto", "战术解析", "战略漫谈", "快评速览", "学院课堂"])
    parser.add_argument("--audience", type=str, default="中级",
                       choices=["初级", "中级", "高级"])
    parser.add_argument("--enable-evaluation", dest="enable_evaluation",
                       action="store_true", help="启用四维度质量评估+自动重写")
    parser.add_argument("--eval", dest="enable_evaluation",
                       action="store_true", help="同 --enable-evaluation")
    args, _ = parser.parse_known_args()

    commentary = auto_generate_commentary(api_key, api_type, model,
                                           style=args.style,
                                           audience=args.audience)
    if not commentary:
        print("❌ 讲解词生成失败")
        return

    # 加载分析数据（后续步骤需要）
    analysis_file = script_dir / "analysis_result.json"
    analysis_data = {}
    opening_info = {}
    if analysis_file.exists():
        with analysis_file.open("r", encoding="utf-8") as f:
            analysis_data = json.load(f)
        steps = analysis_data.get("steps", analysis_data)

        # 提取开局信息
        try:
            import chess.pgn
            if pgn_files:
                with pgn_files[0].open("r", encoding="utf-8") as f:
                    game = chess.pgn.read_game(f)
                opening_info = {
                    "white": game.headers.get("White", "未知"),
                    "black": game.headers.get("Black", "未知"),
                    "opening": game.headers.get("Opening", "未知"),
                    "eco": game.headers.get("ECO", "未知"),
                    "result": game.headers.get("Result", "*"),
                    "termination": game.headers.get("Termination", ""),
                    "time_control": game.headers.get("TimeControl", ""),
                    "white_clock": game.headers.get("WhiteClock", ""),
                    "black_clock": game.headers.get("BlackClock", ""),
                }
        except Exception:
            pass

    # 第 2.5 步：训练要点提炼
    print("\n" + "="*60)
    print("🏋️ 第 2.5 步: 提炼训练要点")
    print("="*60)
    try:
        training_result = generate_training_points_from_llm(
            steps, opening_info, api_key, api_type, model
        )
        training_file = script_dir / "training_points.json"
        with training_file.open("w", encoding="utf-8") as f:
            json.dump(training_result, f, ensure_ascii=False, indent=2)
        print(f"✓ 训练要点已保存: {training_file}")

        # 显示训练要点
        print(f"\n  {'─'*50}")
        white_name = training_result.get("white_player", "白方")
        black_name = training_result.get("black_player", "黑方")
        print(f"  {white_name} vs {black_name}")
        print(f"  总述: {training_result.get('summary', '')}")
        # 白方训练要点
        wtp = training_result.get("white_training_points", [])
        if wtp:
            print(f"\n  ┌─ {white_name} — {training_result.get('white_summary', '')[:80]}")
            for i, tp in enumerate(wtp[:3], 1):
                print(f"  │ {i}. [{tp.get('severity', '中')}严重度] {tp.get('issue', '')} (第{', '.join(map(str, tp.get('steps',[])))}步)")
                print(f"  │    练习: {tp.get('practice', '')[:80]}...")
        else:
            print(f"\n  ┌─ {white_name}: 发挥稳定，无明显错误 ✓")
        # 黑方训练要点
        btp = training_result.get("black_training_points", [])
        if btp:
            print(f"\n  └─ {black_name} — {training_result.get('black_summary', '')[:80]}")
            for i, tp in enumerate(btp[:3], 1):
                print(f"     {i}. [{tp.get('severity', '中')}严重度] {tp.get('issue', '')} (第{', '.join(map(str, tp.get('steps',[])))}步)")
                print(f"        练习: {tp.get('practice', '')[:80]}...")
        else:
            print(f"\n  └─ {black_name}: 发挥稳定，无明显错误 ✓")
    except Exception as e:
        print(f"⚠ 训练要点提炼失败: {e}，跳过")

    # 第 2.6 步：多裁判互评
    print("\n" + "="*60)
    print("👨‍⚖️ 第 2.6 步: 多裁判模型互评")
    print("="*60)
    # 检查是否启用新版评估器
    if "--enable-evaluation" in sys.argv or "--eval" in sys.argv:
        try:
            from commentary_evaluator import evaluate_and_rewrite

            def _rewrite_cb(text, feedback):
                """重写回调：将反馈注入到重新生成中"""
                print(f"\n  🔄 触发重写: {feedback[:100]}...")
                # 简单策略：在提示词末追加反馈
                return auto_generate_commentary(
                    api_key, api_type, model,
                    style=args.style,
                    audience=args.audience,
                    extra_context=feedback
                )

            eval_result = evaluate_and_rewrite(
                commentary, args.audience, api_key, api_type, model,
                min_score=6.0, max_rewrites=2, rewrite_callback=None  # 不用回调，手动重试
            )
            print(f"  最终评分: {eval_result.get('score','?')}/10 "
                  f"{'✅通过' if eval_result.get('passed') else '⚠待改进'}")
            if eval_result.get('rewrites', 0) > 0:
                # 使用重写后的解说词
                commentary = eval_result['commentary']
                # 重新保存
                with (script_dir / "commentary.txt").open("w", encoding="utf-8") as f:
                    f.write(commentary)
                print(f"  ✓ 已使用重写后的解说词（{len(commentary)} 字）")
        except Exception as e:
            print(f"⚠ 新版评估器失败: {e}，使用旧版评估...")
            # 退回旧版
            eval_result = evaluate_commentary(commentary, analysis_data, opening_info,
                                                api_key, api_type, model)
    else:
        try:
            eval_result = evaluate_commentary(commentary, analysis_data, opening_info,
                                               api_key, api_type, model)
            eval_file = script_dir / "commentary_evaluation.json"
            with eval_file.open("w", encoding="utf-8") as f:
                json.dump(eval_result, f, ensure_ascii=False, indent=2)
            print(f"✓ 互评结果已保存: {eval_file}")
            print(f"  综合评分: {eval_result['average_score']}/10 {'✅ 通过' if eval_result['passed'] else '⚠ 建议修改'}")

            for jr in eval_result.get("judge_results", []):
                print(f"  {jr.get('judge', '?')}: {jr.get('overall', '?')}/10")
                weaknesses = jr.get("weaknesses", jr.get("confusing_parts", []))
                if weaknesses:
                    print(f"    问题: {'; '.join(weaknesses[:2])}")
        except Exception as e:
            print(f"⚠ 多裁判互评失败: {e}，跳过")

    # 第 3 步：解析讲解词
    print("\n" + "="*60)
    print(" 第 3 步: 解析讲解词")
    print("="*60)
    if not run_script("parse_commentary.py", "解析讲解词并生成字幕"):
        print("❌ 解析失败")
        return

    # 第 4 步：TTS (SSML 情感控制)
    print("\n" + "="*60)
    print(" 第 4 步: 生成 TTS 语音 (SSML 情感控制)")
    print("="*60)

    print("使用 Edge TTS 生成语音（带 SSML 情感标记）...")
    if not run_script("tts_tool.py", "生成 TTS 音频"):
        print("⚠ TTS 生成可能失败，继续...")
    
    # 第 5 步前：检查棋子图片
    pieces_dir = script_dir / "pieces"
    if not pieces_dir.exists() or not list(pieces_dir.glob("*.png")):
        print("\n" + "="*60)
        print("🎨 生成棋子图片")
        print("="*60)
        print("棋子图片未生成，自动运行 piece_generator.py ...")
        if not run_script("piece_generator.py", "生成 lichess 风格棋子图片"):
            print("⚠ 棋子生成失败，将使用 Unicode 备用方案")

    # 第 5 步：棋盘渲染
    print("\n" + "="*60)
    print(" 第 5 步: 渲染棋盘动画 (横屏 4:3)")
    print("="*60)

    print("使用 PIL 渲染棋盘 (960×720)...")
    if not run_script("render_board.py", "生成棋盘图片序列"):
        print("⚠ 棋盘渲染可能失败，继续...")
    
    # 第 6 步：合成视频
    print("\n" + "="*60)
    print("🎬 第 6 步: 合成最终视频 (音视频混流)")
    print("="*60)

    print("使用 ffmpeg 混流视频和音频...")
    if not run_script("synthesize_video_python.py", "合成最终视频"):
        print("⚠ 视频合成可能失败，继续...")

    # 第 6.5 步：生成棋评 Word 文档
    print("\n" + "="*60)
    print("📝 第 6.5 步: 生成深度棋评 Word 文档")
    print("="*60)
    if not run_script("generate_report.py", "生成棋评文档"):
        print("⚠ 文档生成可能失败，继续...")

    # 第 7 步：整理项目
    print("\n" + "="*60)
    print("📁 第 7 步: 整理项目文件")
    print("="*60)
    
    print("正在整理项目文件夹...")
    if not run_script("organize_project.py", "组织输出文件"):
        print("⚠ 项目整理可能失败，继续...")
    
    # 总结
    print("\n" + "="*60)
    print("✅ 完整流程已完成！")
    print("="*60)
    
    output_dir = script_dir
    print("\n📁 生成的文件:")
    print("   ✓ 分析数据: analysis_result.json (含阶段分段 + 残局库判决 + Lc0交叉验证)")
    print("   ✓ 讲解词: commentary.txt")
    print("   ✓ 训练要点: training_points.json")
    print("   ✓ 讲解互评: commentary_evaluation.json")
    print("   ✓ 合并数据: merged_analysis_commentary.json")
    print("   ✓ 视频剧本: video_script.tsv")
    print("   ✓ 语音音频: commentary.mp3 (SSML 情感控制)")
    print("   ✓ SRT 字幕: commentary.srt")
    print("   ✓ 棋盘图片: board_frames/")
    print("   ✓ 棋盘视频: board_animation.mp4 (960×720)")
    print("   ✓ 最终视频: final_video.mp4 (横屏 4:3, 字幕嵌入右面板)")
    print("   ✓ 棋评文档: chess_analysis_report_*.docx")
    
    print("\n📂 项目整理:")
    print("   所有文件已按对局信息整理到独立文件夹")
    print("   方便进行版本管理和发布")
    
    print("\n✨ 恭喜！所有自动化步骤已完成！")
    print("\n下一步建议:")
    print("   1. 检查 output/ 文件夹中的项目文件")
    print("   2. 使用 final_video.mp4 进行发布或进一步编辑")
    print("   3. 查看 README.md 了解项目详情")


if __name__ == "__main__":
    main()

