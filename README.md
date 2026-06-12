# 深蓝棋评 · 国际象棋 AI 讲解视频生成器 v5.1

一键将 Lichess PGN 棋谱自动转换为**带语音讲解的棋盘动画视频** + **深度棋评 Word 文档** + **双方训练要点报告**。

> 🏠 深蓝国际象棋协会出品 · 仅供学习交流使用

---

## 目录

- [项目概述](#项目概述)
- [快速开始](#快速开始)
- [运行方式](#运行方式)
  - [命令行一键生成](#命令行一键生成)
  - [分步运行](#分步运行)
  - [Web 控制台](#web-控制台)
  - [Python API](#python-api)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [数据流](#数据流)
- [模块详解](#模块详解)
  - [棋局分析引擎 (analyse.py)](#棋局分析引擎-analyzepy)
  - [战术检测器 (tactical_detector.py)](#战术检测器-tactical_detectorpy)
  - [战略概念提取器 (concept_extractor.py)](#战略概念提取器-concept_extractorpy)
  - [局面型错误检测器 (strategic_mistake_detector.py)](#局面型错误检测器-strategic_mistake_detectorpy)
  - [关键时刻检测器 (critical_moment_detector.py)](#关键时刻检测器-critical_moment_detectorpy)
  - [分支讲解触发系统 (branch_evaluator.py)](#分支讲解触发系统-branch_evaluatorpy)
  - [残局知识分析 (endgame_knowledge.py)](#残局知识分析-endgame_knowledgepy)
  - [大师对局数据库 (master_games_db.py)](#大师对局数据库-master_games_dbpy)
  - [开局数据库 (opening_explorer.py)](#开局数据库-opening_explorerpy)
  - [讲解词生成 (pipeline.py + generate_commentary.py)](#讲解词生成-pipelinepy--generate_commentarypy)
  - [风格模板系统 (style_templates.py)](#风格模板系统-style_templatespy)
  - [TTS 语音合成 (tts_tool.py)](#tts-语音合成-tts_toolpy)
  - [棋盘动画渲染 (render_board.py)](#棋盘动画渲染-render_boardpy)
  - [视频合成 (synthesize_video_python.py)](#视频合成-synthesize_video_pythonpy)
  - [棋评文档生成 (generate_report.py)](#棋评文档生成-generate_reportpy)
  - [训练要点提炼 (training_analyzer.py)](#训练要点提炼-training_analyzerpy)
- [设计理念](#设计理念)
- [配置指南](#配置指南)
- [常见问题](#常见问题)
- [扩展开发](#扩展开发)
- [项目结构](#项目结构)
- [技术栈](#技术栈)
- [更新日志](#更新日志)
- [许可](#许可)

---

## 项目概述

**深蓝棋评** 是一个全自动的国际象棋对局讲解生成系统。你只需要提供一份 Lichess PGN 棋谱，系统会自动完成从分析到视频的全流程。

```
PGN 棋谱
  → Stockfish MultiPV 分析（3 候选 + 动态深度）
  → Lc0 神经网络交叉验证（关键位置）
  → 战术主题检测（击双/牵制/闪击/引离 等 7 类）
  → 局面型错误检测（坏象换好马/兵型受损/放弃中心 等 7 类）
  → 战略概念提取（王安全/开放线/空间/兵形/机动性/子力 6 维度）
  → 关键时刻检测（评分剧变/战术爆发/阶段转换 6 权重评分）
  → 战略阶段分段识别（开局/中局/残局 + 转折点）
  → 残局知识分析（引擎 vs 表库对比 + 理论残局识别）
  → 大师对局数据库查询（FEN 哈希 + Lichess API 后备）
  → 分支讲解触发评估（7 种条件 + 连续抑制 + 上限控制）
  → Syzygy 残局库查询（棋子 ≤ 7）
  → 开局数据库匹配（80+ ECO 变例 + 深度特征注入）
  → 风格模板选择（4 种风格 × 3 级观众，含自动推荐）
  → LLM 讲解词生成（含主棋盘 + 小棋盘双轨画面指令）
  → 训练要点提炼（分别评价黑白双方 + 可量化练习建议）
  → 多裁判互评（教练 + 观众双视角评分）
  → 逐步 TTS 语音合成（SSML 情感控制）
  → 精确音画同步（timing.json + ffprobe 实测）
  → 棋盘动画渲染（Lichess 棋子 + 多类型高亮 + 小棋盘支线演示）
  → 音视频合成 → final_video.mp4（横屏 4:3，字幕嵌入）
  → 棋评 Word 文档（微信公众号风格，含棋盘插图）
  → 项目归档到 output/
```

---

## 快速开始

### 环境要求

| 组件 | 最低要求 | 说明 |
|------|----------|------|
| Python | 3.10+ | 需支持 `str \| None` 类型注解 |
| Stockfish | 已内置 | `stockfish-windows-x86-64-avx2/` 目录 |
| FFmpeg | 5.0+ | 通过 `imageio-ffmpeg` 自动安装 |
| API Key | — | DeepSeek / OpenAI 用于 LLM 讲解词生成 |
| 中文字体 | 微软雅黑 | Windows 自带 |
| 内存 | 8 GB | Lc0 神经网络推理占资源 |

### 安装依赖

```bash
pip install python-chess Pillow imageio-ffmpeg edge-tts openai python-docx flask
```

### 获取 PGN 棋谱

在 Lichess 上完成对局后，点击"下载"按钮获取 PGN 文件，将其放到项目目录下：

```
agentchess/
└── lichess_pgn_2026.05.05_xxx_vs_xxx.xxxxxxxx.pgn
```

### 运行

```bash
cd D:\国际象棋社团\agentchess
python pipeline.py
```

---

## 运行方式

### 命令行一键生成

```bash
# 自动选择最佳风格
python pipeline.py

# 指定风格和观众水平
python pipeline.py --style 战术解析 --audience 中级
python pipeline.py --style 战略漫谈 --audience 高级
python pipeline.py --style 学院课堂 --audience 初级
```

| 参数 | 可选值 | 默认值 | 说明 |
|------|--------|--------|------|
| `--style` | `auto`, `战术解析`, `战略漫谈`, `快评速览`, `学院课堂` | `auto` | 讲解风格 |
| `--audience` | `初级`, `中级`, `高级` | `中级` | 观众水平 |

### 分步运行

```bash
python analyse.py              # 第1步：棋局分析
python generate_commentary.py  # 第2步：LLM 讲解词
python parse_commentary.py     # 第3步：解析 + SRT 字幕
python tts_tool.py             # 第4步：TTS 语音合成
python render_board.py         # 第5步：棋盘动画渲染
python synthesize_video_python.py  # 第6步：视频合成
python generate_report.py      # 第7步：棋评 Word 文档
python organize_project.py     # 第8步：项目归档
```

### Web 控制台

```bash
python web_ui.py
# 浏览器打开 http://localhost:5000
```

可视化选择 PGN / 风格 / 水平，一键生成。SSE 实时日志推送。

### Python API

```python
from pipeline import auto_generate_commentary
import json

with open("analysis_result.json", "r", encoding="utf-8") as f:
    analysis_data = json.load(f)

commentary = auto_generate_commentary(
    api_key="sk-xxx",
    api_type="deepseek",
    model="deepseek-v4-pro",
    style="战术解析",
    audience="中级"
)
```

---

## 核心特性

| 特性 | 技术实现 |
|------|----------|
| ♟️ **Lichess 同款棋子** | cburnett SVG → 256×256 RGBA PNG |
| 🔬 **双引擎交叉验证** | Stockfish + Lc0 神经网络，4 级分歧分类 |
| 📊 **MultiPV=3 分析** | 每步 3 个候选走法 + PV 主线，失误自动深分析 |
| 🎯 **战术检测** | 7 类战术：击双/牵制/串击/闪击/引离/中间着/杀棋 |
| 🧠 **局面型错误检测** | 7 类战略错误：坏象换好马/兵型受损/放弃中心/失去双象/王盾破损/开放线丧失/出子落后 |
| 🗺️ **战略概念提取** | 6 维度：王安全/开放线/空间/兵形/机动性/子力 |
| 🎬 **关键时刻检测** | 6 维度评分模型，自动识别 5-8 个教学节点 |
| 🌿 **分支讲解触发** | 7 种触发条件 + 连续抑制 + 每局上限控制 |
| 📚 **残局知识分析** | 理论残局类型识别 + 引擎 vs 表库矛盾检测 |
| 🏆 **大师对局参考** | FEN 哈希索引 + Lichess Masters API 后备 + 偏离检测 |
| 🎭 **4 种风格 + 3 级观众** | 战术解析 / 战略漫谈 / 快评速览 / 学院课堂 |
| 🎤 **SSML 情感语音** | 8 级情感映射，好棋加速/失误减速 |
| 📺 **小棋盘支线演示** | LLM 可显式控制右下角小棋盘 |
| 🎨 **多类型棋盘高亮** | 黄色(上步)/红色(将军)/绿色(推荐)/橙色(威胁) |
| 🏋️ **双方训练要点** | 分别评价黑白双方，可量化练习建议 |
| 👨‍⚖️ **多裁判互评** | 教练(战术准确度) + 观众(易懂度)双视角评分 |
| 📝 **Word 棋评文档** | 微信公众号风格，每段 PGN 配棋盘图 |
| 🌐 **Web 控制台** | Flask 界面，实时日志 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│  用户入口: web_ui.py / pipeline.py / Python API             │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│                    analyse.py (棋局分析核心)                  │
│                                                             │
│  ┌─────────┬──────────┬──────────┬──────────┬──────────┐    │
│  │Stockfish│   Lc0    │Syzygy表库│ 战术检测器│ 概念提取器│    │
│  │MultiPV=3│ 神经网络  │  (本地)  │ (7类战术)│ (6维度)  │    │
│  └─────────┴──────────┴──────────┴──────────┴──────────┘    │
│  ┌────────┬──────────┬──────────┬──────────┬──────────┐     │
│  │开局探索器│关键时刻检测│局面错误检测│残局知识器│分支触发器│     │
│  │(ECO匹配)│(6权重评分)│(7类规则)  │(引擎vs表库)│(7条件) │     │
│  └────────┴──────────┴──────────┴──────────┴──────────┘     │
│  ┌──────────┐                                               │
│  │大师对局查询│  (FEN哈希 + API后备)                          │
│  └──────────┘                                               │
└──────────────────────┬──────────────────────────────────────┘
                       │ analysis_result.json
                       │ (含 concept_profile + critical_moments
                       │  + endgame_analyses + branch_guide)
                       │
┌──────────────────────▼──────────────────────────────────────┐
│                   pipeline.py (讲解词生成)                    │
│  风格模板选择 → 上下文构建 → LLM API 调用 → commentary.txt   │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│              音视频生成流水线                                 │
│  parse → TTS+timing.json → render_board → ffmpeg 合成       │
│                            + Word 文档                        │
└──────────────────────┬──────────────────────────────────────┘
                       │
              final_video.mp4 + 训练报告 + 棋评文档
```

**设计理念**: 三层架构

```
事实层 (Fact Layer)     Stockfish + Lc0 → 评分、候选走法
         ↓
概念层 (Concept Layer)   战术检测 + 战略提取 + 局面错误 + 残局知识
                         + 大师对比 + 分支触发
         ↓
语言层 (Language Layer)  LLM 风格化讲解词生成
```

---

## 数据流

### 第一阶段：棋局分析

`analyse.py` 是核心分析引擎，逐步遍历棋谱并并行执行多维度分析。

每步棋生成的数据结构 (`step_data`):

```python
{
    "move_number": 12,
    "round": 6,
    "side": "白方",
    "move_san": "Nf3",
    "score_before": 0.3,
    "score_after": 0.2,
    "score_diff": -0.1,
    "quality": "正常",              # 7 级着法质量
    "best_move_san": "Nf3",         # 引擎最佳走法
    "is_best_move": true,
    "candidates": [...],            # MultiPV 候选走法 (前3)
    "recommended": null,            # 失误时的推荐走法
    "tactical_themes": [...],       # 战术主题
    "strategic_mistakes": [...],    # 局面型错误
    "masters": {...},               # 大师对局数据
    "endgame_analysis": {...},      # 残局知识分析
    "branch": {...},                # 分支讲解触发
    "tablebase": {...},             # 表库判决
    "cross_validation": {...},      # Lc0 交叉验证
    "phase": {...},                 # 所属战略阶段
    "concept_hint": "...",          # 概念提示
    "time_spent_seconds": 12.3,     # 耗时
    "is_long_think": false,         # 是否长考
}
```

### 第二阶段：讲解词生成

`pipeline.py` 的 `auto_generate_commentary()` 函数构建约 3000+ token 的提示词，包含：

- 风格模板（4 选 1 × 3 级观众水平）
- 开局深度信息（ECO 匹配 + 特征库 + 大师统计数据）
- 战术速览 + 局面型错误速览 + 大师走法速览
- 战略阶段划分 + 概念提取结果
- 关键时刻聚焦指南（详写/中写/略写分配）
- 残局知识分析 + 表库判决
- 小棋盘支线展示指南
- 对局时间压力分析

### 第三阶段：音视频生成

```
commentary.txt → parse → TTS (SSML) → timing.json
                                      → commentary.mp3
                                      → commentary.srt

timing.json → render_board → board_frames/
                            → board_animation.mp4

board_animation.mp4 + commentary.mp3 → ffmpeg → final_video.mp4
```

---

## 模块详解

### 棋局分析引擎 (analyse.py)

**输入**: Lichess PGN 文件  
**输出**: `analysis_result.json`

**分析流程**:

1. **Stockfish MultiPV**: 每步走棋前做 MultiPV=3 分析，获取 3 个候选走法及 PV 主线
2. **动态分析深度**: 正常步 0.3s，开局步 0.5s，失误步 2.0s 深层重分析
3. **着法质量 7 级分类**: 基于走棋方视角的评分变化判定妙手/好棋/正常/缓着/疑问/失误/漏杀/送子
4. **Lc0 交叉验证**: 对关键位置（评分剧变/战术主题/密集波动/交替失误）用 Lc0 做 10s 神经网络重分析
5. **Syzygy 残局库**: 棋子 ≤ 7 时查询精确胜/负/和判决
6. **战略阶段分段**: 开局(≤12步) / 中局 / 残局(≤12子) + 子阶段转折点识别

### 战术检测器 (tactical_detector.py)

纯 python-chess 检测，不调引擎，7 类战术:

| 战术 | 检测方法 |
|------|----------|
| 击双 (fork) | 走子后同时攻击 2+ 个敌方轻子以上 |
| 牵制 (pin) | `board.is_pinned()` 比较走棋前后变化 |
| 串击 (skewer) | 滑动棋子射线上前高后低价值的两个敌子 |
| 闪击/闪将 (discovered) | 移走遮挡棋子，后方滑动棋子攻击新目标 |
| 引离 (deflection) | 吃子后目标格失去全部防守（敌方王/后/中心格） |
| 中间着 (zwischenzug) | 上步吃子，当前步不立即回吃而将军或吃高价值子 |
| 杀棋威胁 (mate) | 利用 Stockfish 评分的 `#1` / `#2` 检测 |

### 战略概念提取器 (concept_extractor.py)

对标 chess-sandbox 概念层，6 维度纯 python-chess 启发式检测:

| 维度 | 检测内容 |
|------|----------|
| 王安全度 | 兵盾完整性 + 开放线威胁 + 重子瞄准（0-10 分） |
| 开放线 | 8 条线逐一检测 + 控制权归属 |
| 空间优势 | 中心控制 + 兵线推进 |
| 子力机动性 | 合法走法数 + 坏子检测 |
| 兵形结构 | 孤兵/叠兵/通路兵 |
| 子力对比 | 差异量化 + 不平衡描述 |

对开局(第10步)、中局(半程)、终局(最后一步)三个关键位置分别提取概念，每步附 `concept_hint`。

### 局面型错误检测器 (strategic_mistake_detector.py) ★ v5

7 类基于规则的检测，捕捉不反映为评分骤降但损害长期战略的错误:

| 检测规则 | 触发条件 |
|----------|----------|
| 坏象换好马 | 己方双象 → 用象换了马 + 局面封闭（兵≥14 且多条兵线对峙） |
| 兵型受损 | 走棋后出现新叠兵或孤兵 |
| 放弃中心 | 中心控制值下降 ≥ 30% |
| 失去双象优势 | 走棋前有双象，走棋后无双象（主动兑象） |
| 王前兵阵破损 | pawn_shield 计数减少 |
| 开放线控制丧失 | 走棋前己方控制开放线，走棋后对方重子数 ≥ 己方 |
| 出子落后 | 已出动轻子数 < 对方 + 走棋后差距未改善 |

### 关键时刻检测器 (critical_moment_detector.py)

GothamChess 风格：60 步的对局只深度展开 5-8 个教学节点。

**6 维度加权评分模型:**

| 维度 | 权重 | 触发条件 |
|------|------|----------|
| 评分剧变 | 30 | cp 差 > 1.5 (明显) / > 3.0 (剧烈) |
| 战术爆发 | 25 | 单一战术 / 多重组合 / 杀棋威胁 |
| 着法质量 | 20 | 送子/漏杀(满分) / 失误 / 妙手 |
| 阶段转换 | 10 | 开局→中局→残局过渡 |
| 引擎分歧 | 10 | Stockfish vs Lc0 强烈分歧 |
| 弃子检测 | 5 | 吃子 + 评分大幅变化 |

输出 `focus_guide`（讲解聚焦指南），直接嵌入 LLM 提示词，告诉 AI:
- **详写**(120-250字): 关键时刻，需深度展开 + 小棋盘支线
- **中写**(40-80字): 值得注意，简要分析 + 可选小棋盘
- **略写**(15-30字): 常规走法，一句话带过

### 分支讲解触发系统 (branch_evaluator.py) ★ v5

7 种触发条件自动判断每步是否需要小棋盘展示支线:

| 条件代码 | 触发规则 | 优先级 |
|----------|----------|--------|
| `MISTAKE` | 评分差 > 0.8 (中级) 或 quality 为失误/漏杀/送子 | 50 |
| `TACTIC_DETECTED` | 检测到战术主题（高价值战术如击双/闪击/杀棋优先） | 45/25 |
| `TABLEBASE_CRITICAL` | 表库关键位置 + 引擎 vs 表库矛盾 | 55/40 |
| `MASTERS_DEVIATION` | 实战偏离大师主流（频率 < 10%） | 35 |
| `STRATEGIC_MISTAKE` | 检测到局面型错误 | 35/20 |
| `MULTICHOICE` | MultiPV 候选间评分差 < 0.3 | 30 |
| `OPENING_DEVIATION` | ≤15步 + 不在引擎前3候选 | 25 |

**抑制规则**: 每局 ≤ 5 处支线；连续 3 步内只保留评分波动最大的

### 残局知识分析 (endgame_knowledge.py) ★ v5

深化 tablebase.py 的集成:

- **残局类型识别**: KPK/KRK/KQK/KRPKR/KBPK/KQKP 6 种理论残局
- **引擎 vs 表库对比**: 检测"引擎评分+2.5 但表库说和棋"等矛盾
- **教练式建议**: 根据残局类型自动生成核心概念和赢/和法说明
- **触发阈值**: ≤12 子即开始分析（而非等到 ≤7 子）

### 大师对局数据库 (master_games_db.py) ★ v5

双模式查询:

1. **本地 PGN 索引**: 读取 KingBase/Caissabase 等大师对局 PGN，构建 FEN MD5 哈希表。前 15 步索引，Pickle 持久化
2. **Lichess Masters API**: `https://explorer.lichess.ovh/masters` 在线后备，含 topGames 著名棋手示例

查询返回:
- 该局面下大师的常见走法（按频率排序 + 胜率）
- 著名棋手示例（卡尔森等在该局面下的走法）
- 实战偏离检测（频率 < 10% 标记为偏离）

### 开局数据库 (opening_explorer.py)

- Lichess Opening Explorer API 查询走法统计（流行度/胜率/陷阱线）
- 本地 ECO 后备表 `eco_table.json`（80+ 变例 FEN 匹配）
- `opening_traits.json`: 12 类开局深度解析 (traits/main_ideas/typical_structures/key_knowledge)
- `opening_theory.json`: Wikibooks 风格理论 (description/themes/main_lines)
- 查询结果缓存至 `opening_cache.json`

### 讲解词生成 (pipeline.py + generate_commentary.py)

`generate_commentary.py` 是交互式入口，`pipeline.py` 是自动化入口。

**提示词组成** (~3000+ tokens):

1. **系统提示词**: 风格模板 + 教练角色 + 观众水平
2. **开局信息**: 选手/ECO/前10步/大师统计/开局特征注入
3. **分析摘要**: 战术速览 + 局面型错误速览 + 大师走法速览 + 战略阶段 + 残局分析 + 表库判决
4. **概念引导**: 战略概念摘要（开局/中局/终局）+ 每步 concept_hint
5. **篇幅分配**: 关键时刻聚焦指南（详写/中写/略写）/ 分支展示指南
6. **对局背景**: 时限/终局时钟/结果/长考检测

**画面控制指令**: LLM 在解说文本中嵌入 `[高亮 e4] [箭头 d1-h5] [小棋盘: d5, exd5, Nxd5]` 等标签

### 风格模板系统 (style_templates.py)

| 风格 | 角色设定 | 适用场景 |
|------|----------|----------|
| 战术解析 | 复盘室里的特级大师，用激光笔指着棋盘步步紧逼 | 中局激战、战术频发 |
| 战略漫谈 | 公园长椅上和朋友下完棋闲聊的哲学大师 | 封闭局面、长线对局 |
| 快评速览 | 吐槽大会嘉宾，电竞解说风格 | 短视频、社交媒体 |
| 学院课堂 | 黑板前的耐心教练 | 新手教学、少儿课程 |
| 自动 | 根据对局数据智能匹配 | 日常使用（推荐） |

**自动选择规则**: 短局多误 → 快评速览 | 失误多战术多 → 战术解析 | 长局少误 → 战略漫谈 | 短局 → 学院课堂

3 级观众水平叠加控制: 初级(术语解释+打比方) / 中级 / 高级

### TTS 语音合成 (tts_tool.py)

Edge TTS 逐步合成 + SSML 情感控制 + 精确音画同步:

- **SSML 情感映射**: 妙手(+18%语速/+10%音调)、送子(-25%语速/-12%音调)等 8 级
- **精确同步**: ffprobe 逐段测量 → `timing.json` → 每步帧数 = duration × fps
- **走法翻译**: Nf3→马f3、exd5→e兵吃d5、O-O-O→长易位
- **画面指令清理**: 自动移除 `[高亮...]` `[箭头...]` `[小棋盘:...]` 等标签

### 棋盘动画渲染 (render_board.py)

**布局设计（1080 × 810）:**

```
┌──────────────────────┬──────────────────────────────────┐
│                      │                                  │
│   棋盘区域 (左)       │     右侧字幕面板 (右)             │
│   560 × 560          │     520 × 810                    │
│                      │                                  │
│   · Lichess 木色     │     · 对局信息 + 时限             │
│   · 棋子贴图         │     · 步数徽章                   │
│   · 多类型高亮:       │     · 解说正文（自动换行）        │
│     上步黄/将军红/   │     · 社团 logo                 │
│     推荐绿/威胁橙    │     ┌──────────────────┐        │
│   · 着法 ?!?? 标注   │     │  小棋盘 (支线演示) │        │
│   · 箭头指示         │     │  右下角 280×280*  │        │
│                      │     └──────────────────┘        │
└──────────────────────┴──────────────────────────────────┘
```

- 片头片尾自动嵌入社团 logo 和信息
- 读取 `timing.json` 确定每步持续帧数
- 支持 `[小棋盘: ...]` / `[小棋盘: FEN: ...]` / `[小棋盘: 清空]` 三种标签

### 视频合成 (synthesize_video_python.py)

FFmpeg 合并棋盘视频 + 语音音频 → `final_video.mp4`

### 棋评文档生成 (generate_report.py)

python-docx 生成微信公众号风格棋评:
- 每 3~5 步一组: PGN + 讲解 + 棋盘插图
- 关键局面展开详析
- 完整 PGN 附于文末

### 训练要点提炼 (training_analyzer.py)

**分别评价黑白双方**，规则系统 + LLM 协作:

每条训练要点包含:
- `side`: 白方或黑方
- `issue`: 问题名称
- `severity`: 严重度（高/中/低）
- `steps`: 涉及步号
- `score_loss`: 评分损失
- `practice`: 具体可量化的练习建议

---

## 设计理念

1. **三层架构**: 事实层(引擎) → 概念层(检测器) → 语言层(LLM)
2. **概念驱动**: 先提取棋理概念再生成语言，而非报引擎评分数字
3. **关键时刻聚焦**: 5-8 个教学节点深度展开，其余精简带过
4. **多方视角**: 分别评价黑白双方，教练+观众双裁判互评
5. **战略深度**: 不仅检测战术错误，还检测不反映为评分骤降的局面型错误
6. **理论与实践结合**: 残局知识库 + 大师对局引用 + 开局理论注入
7. **模块化设计**: 每个步骤可独立运行、单独调试

---

## 配置指南

### analyse.py 核心配置

```python
STOCKFISH_PATH = r"D:\国际象棋社团\agentchess\stockfish-xxx\stockfish.exe"
LCO_ENABLE = True                              # 是否启用 Lc0 交叉验证
LCO_WEIGHTS_PATH = Path(r"D:\lc0_data\weights.lc0")  # 必须纯 ASCII 路径！
MULTIPV = 3                                    # 每步候选走法数
```

### pipeline.py API 配置

```python
API_KEY = "sk-你的API-Key"
API_TYPE = "deepseek"          # "deepseek" 或 "openai"
MODEL = "deepseek-v4-pro"
```

### render_board.py 外观配置

```python
square_size = 70     # 格子像素
fps = 15             # 视频帧率
width = 1080         # 视频宽度
height = 810         # 视频高度
```

### tts_tool.py 语音配置

```python
voice = "zh-CN-XiaoxiaoNeural"   # 中文女声
# QUALITY_SSML_MAP 字典自定义语速/音调/音量
```

---

## 常见问题

**Q: Lc0 引擎加载失败？**  
→ 权重路径必须纯 ASCII，CUDA 12 可选。不可用时自动降级为仅 Stockfish，不影响功能。

**Q: TTS 中途断网？**  
→ 内置 3 次递增重试（3s/6s），全失败时自动生成静默占位。

**Q: 画面和语音不同步？**  
→ 删除 `timing.json` + `board_frames/` + `commentary.mp3`，重新运行 tts_tool + render_board + synthesize。

**Q: 讲解词太机械？**  
→ 尝试不同风格（`--style 战略漫谈`）+ 调整观众水平。

**Q: 如何添加新开局变例？**  
→ 编辑 `eco_table.json`，按格式添加 FEN 特征子串。

**Q: 如何构建大师对局索引？**  
→ 下载 KingBase/Caissabase PGN，运行:
```python
from master_games_db import MasterGamesDB
db = MasterGamesDB()
db.build_index(["path/to/kingbase/*.pgn"], max_moves=15)
db.save_index()
```

---

## 扩展开发

### 添加新的战术检测

编辑 `tactical_detector.py`，实现 `_detect_new_tactic()` 并注册到 `detect()`。

### 添加新的局面型错误检测规则

编辑 `strategic_mistake_detector.py`，实现 `_rule_xxx()` 并注册到 `detect()`。

### 添加新的讲解风格

编辑 `style_templates.py`:
```python
STYLE_TEMPLATES["我的风格"] = """【本期风格：...】"""
```

### 调整关键时刻权重

编辑 `critical_moment_detector.py` 中的 `WEIGHTS` 字典。

---

## 项目结构

```
agentchess/
│
├── 🎯 主流程
│   ├── pipeline.py                 # 命令行一键生成入口
│   ├── web_ui.py                   # Web 控制台 (Flask + SSE)
│   ├── analyse.py                  # 棋局分析核心 ★
│   ├── generate_commentary.py      # LLM 讲解词（交互式）
│   └── organize_project.py         # 项目归档
│
├── ♟️ 棋局分析模块 ★
│   ├── tactical_detector.py        # 战术检测（7 类）
│   ├── concept_extractor.py        # 战略概念提取（6 维度）
│   ├── strategic_mistake_detector.py  # ★ 局面型错误检测（7 类）
│   ├── critical_moment_detector.py # 关键时刻检测（6 权重）
│   ├── branch_evaluator.py         # ★ 分支讲解触发系统
│   ├── endgame_knowledge.py        # ★ 残局知识分析
│   ├── master_games_db.py          # ★ 大师对局数据库
│   ├── opening_explorer.py         # 开局数据库
│   ├── eco_table.json              # 80+ ECO 变例 FEN 表
│   ├── opening_traits.json         # 12 类开局深度解析
│   ├── opening_theory.json         # 开局理论
│   ├── endgame_theory.json         # 残局理论知识
│   ├── tablebase.py                # Syzygy 残局库查询
│   ├── training_analyzer.py        # 训练要点提炼 ★
│   └── quality_optimization.py     # 质量优化
│
├── 🎤 TTS & 同步
│   └── tts_tool.py                 # 逐步 TTS + SSML + timing.json
│
├── 🎨 渲染 & 视频
│   ├── render_board.py             # PIL 棋盘渲染（主+小棋盘）
│   ├── piece_generator.py          # SVG → PNG 棋子生成
│   ├── synthesize_video_python.py  # FFmpeg 音视频混流
│   └── pieces/                     # 生成的棋子 PNG (12个)
│
├── 📝 文档生成
│   ├── generate_report.py          # Word 棋评
│   └── parse_commentary.py         # 讲解词解析 + SRT 字幕
│
├── 🤖 AI 提示词
│   ├── style_templates.py          # 4 种风格 + 3 级观众 + 自动选择
│   ├── coach_explainer.py          # 提示词构建工具
│   └── coach_prompt.txt            # 生成的提示词文本
│
├── 📂 输出
│   └── output/                     # 按对局归档的项目文件夹
│
├── 🔧 引擎
│   ├── stockfish-windows-x86-64-avx2/  # Stockfish 17
│   └── lc0-v0.32.1-windows-gpu-nvidia-cuda12/  # Lc0 v0.32.1
│
└── 📥 输入
    └── lichess_pgn_*.pgn           # PGN 棋谱
```

---

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| python-chess ≥ 1.0 | 棋局逻辑、PGN 解析、UCI 引擎通信 |
| Stockfish 17 | 传统 α-β 引擎 MultiPV 分析 |
| Lc0 v0.32.1 (CUDA 12) | 神经网络引擎交叉验证 |
| Pillow | 棋盘渲染、棋子生成、图像处理 |
| Edge TTS | 语音合成（免费在线） |
| OpenAI SDK | LLM API 调用 |
| Flask | Web 控制台 |
| python-docx | Word 文档生成 |
| FFmpeg | 视频编码、音频拼接 |
| Lichess API | 开局 Explorer + Masters 数据库 + Syzygy 残局库 |

---

## 更新日志

### v5.1 (2026.06)

- ✨ **局面型错误检测器**: 7 类规则检测坏象换好马/兵型受损/放弃中心等战略错误
- ✨ **残局知识分析**: 理论残局类型识别 + 引擎 vs 表库矛盾检测
- ✨ **大师对局数据库**: FEN 哈希索引 + Lichess API 后备 + 偏离检测
- ✨ **分支讲解触发系统**: 7 种触发条件 + 连续抑制 + 每局上限
- ✨ **训练要点分方评价**: 分别给黑白双方生成独立的训练建议
- 🔧 提示词大幅增强: 4 个新讲解维度（局面型错误/残局理论/大师引用/分支指南）

### v5 (2026.06)

- ✨ 战略概念提取器 (6 维度) + 关键时刻检测器 (6 权重)
- ✨ 小棋盘指令系统 + 三层架构落地

### v4 (2026.06)

- ✨ 精确音画同步 + 多裁判互评 + 训练要点提炼 + 7 级着法质量

---

## 许可

深蓝国际象棋协会出品 · 仅供学习交流使用

---

> 💡 **提示**: `python web_ui.py` 获得最友好的使用体验。`python pipeline.py` 一键走完所有流程。