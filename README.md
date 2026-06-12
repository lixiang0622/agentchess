# 深蓝棋评 · 国际象棋 AI 讲解视频生成器 v5.2

一键将 Lichess PGN 棋谱自动转换为**带语音讲解的棋盘动画视频** + **深度棋评 Word 文档** + **双方训练要点报告**。

> 🏠 深蓝国际象棋协会出品 · 仅供学习交流使用

---

## 目录

- [快速开始](#快速开始)
- [系统架构](#系统架构)
- [核心模块](#核心模块)
- [设计理念](#设计理念)
- [运行方式](#运行方式)
- [风格模板](#风格模板)
- [配置指南](#配置指南)
- [项目结构](#项目结构)
- [常见问题](#常见问题)
- [扩展开发](#扩展开发)

---

## 快速开始

### 环境

| 组件 | 要求 |
|------|------|
| Python | 3.10+ |
| Stockfish | 已内置 |
| FFmpeg | `pip install imageio-ffmpeg` |
| API Key | DeepSeek 或 OpenAI |

### 安装

```bash
pip install python-chess Pillow imageio-ffmpeg edge-tts openai python-docx flask

# 可选：Lc0 神经网络交叉验证（需要 NVIDIA GPU + CUDA）
# 可选：Playwright 开局数据抓取
pip install playwright && playwright install chromium
```

### 运行

```bash
cd D:\国际象棋社团\agentchess
python pipeline.py
```

将 Lichess 下载的 PGN 文件放到项目目录下即可。

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│  输入: Lichess PGN                                            │
└──────────────────────────┬───────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│  analyse.py  棋局分析引擎                                      │
│                                                              │
│  ┌─────────┬──────────────┬─────────────┬─────────────────┐  │
│  │Stockfish│   Lc0 交叉验证 │  Syzygy 表库 │  战术检测器(7类) │  │
│  │MultiPV=3│   (关键位置)   │  (≤7子查询)  │  概念提取器(6维) │  │
│  └─────────┴──────────────┴─────────────┴─────────────────┘  │
│  ┌──────────────┬─────────────┬────────────┬──────────────┐  │
│  │关键时刻检测(6权重)│局面错误检测(7类)│残局知识分析  │局面可解释性   │  │
│  └──────────────┴─────────────┴────────────┴──────────────┘  │
│  ┌──────────────┬─────────────┬─────────────┐                │
│  │大师对局数据库  │分支讲解触发  │开局知识库匹配 │                │
│  └──────────────┴─────────────┴─────────────┘                │
└──────────────────────┬───────────────────────────────────────┘
                       ↓ analysis_result.json
┌──────────────────────────────────────────────────────────────┐
│  pipeline.py  讲解词生成                                       │
│  风格模板(4×3级) → 多维度上下文构建 → LLM API → commentary.txt │
└──────────────────────┬───────────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────────┐
│  音视频生产流水线                                              │
│  parse → TTS+SSML+timing.json → render_board → ffmpeg 合成   │
│                                        + Word 棋评文档         │
└──────────────────────┬───────────────────────────────────────┘
                       ↓
              final_video.mp4 + 训练报告 + 棋评文档
```

---

## 核心模块

### 棋局分析

| 模块 | 功能 |
|------|------|
| `analyse.py` | 主分析引擎：Stockfish MultiPV + 全部子模块调度 |
| `tactical_detector.py` | 7 类战术检测：击双/牵制/串击/闪击闪将/引离/中间着/杀棋 |
| `concept_extractor.py` | 6 维度战略概念：王安全/开放线/空间/兵形/机动性/子力 |
| `strategic_mistake_detector.py` | 7 类局面型错误：坏象换好马/兵型受损/放弃中心/失去双象/王盾破损/开放线丧失/出子落后 |
| `critical_moment_detector.py` | 关键时刻检测：6 维度评分 → 详写/中写/略写分配 |
| `branch_evaluator.py` | 分支讲解触发：7 种触发条件 + 连续抑制 + 每局上限 |
| **`position_explain.py`** | **局面可解释性：6 维特征提取 → 变化对比 → 中文诊断报告** |
| `endgame_knowledge.py` | 残局分析：理论类型识别(6种) + 引擎 vs 表库矛盾 |
| `tablebase.py` | Syzygy 残局库查询 (本地 + Lichess API) |
| `master_games_db.py` | 大师对局数据库：FEN 哈希 + Lichess API 后备 + 偏离检测 |
| `opening_knowledge.py` | 开局知识库：30 个主流开局的结构化知识（计划/陷阱/棋手） |

### 讲解与视频

| 模块 | 功能 |
|------|------|
| `pipeline.py` | 一键流水线主控 + LLM 讲解词生成 |
| `generate_commentary.py` | LLM 讲解词（交互式版本） |
| `style_templates.py` | 4 种风格 × 3 级观众 + 自动选择 |
| `tts_tool.py` | Edge TTS + SSML 情感控制 + timing.json 同步 |
| `render_board.py` | 棋盘动画渲染（主棋盘 + 小棋盘支线 + 高亮箭头） |
| `synthesize_video_python.py` | FFmpeg 音视频混流（片头静音延迟） |
| `parse_commentary.py` | 讲解词解析 + SRT 字幕 |
| `generate_report.py` | Word 棋评文档 |

### 数据与知识

| 模块 | 功能 |
|------|------|
| `training_analyzer.py` | 分别评价黑白双方 + 可量化练习建议 |
| `opening_explorer.py` | Lichess 开局数据库查询 + 本地 ECO 匹配 |
| `fetch_opening_data.py` | Playwright 自动抓取 Lichess 开局树 (BFS, 最多1000个) |
| `opening_knowledge.json` | 30 个开局结构化知识库 |
| `eco_table.json` | 80+ ECO 变例 FEN 表 |
| `endgame_theory.json` | 残局理论知识 |

### 工具

| 模块 | 功能 |
|------|------|
| `web_ui.py` | Web 控制台 (Flask + SSE) |
| `organize_project.py` | 输出归档 |
| `piece_generator.py` | Lichess SVG → PNG 棋子 |
| `merge_openings.py` | 开局 JSON 合并工具 |

---

## 设计理念

### 三层架构

```
事实层 → 概念层 → 语言层
(引擎)   (检测器)  (LLM)
```

LLM 拿到的不再是冷冰冰的评分数字，而是已经提取好的：战术主题、局面错误、概念变化、诊断报告、大师参考、开局知识。

### position_explain 模块：从"是什么"到"为什么"

```
原来: "白方走了 e5，评分从 -0.4 变成了 +1.2"
现在: "白方 e5 推进后，中心控制力显著增强(2→5)，
       同时黑方的马失去了 d6 据点，再加上 g 线半开放
       为白车提供了进攻通道——所以评分瞬间倒向白方"
```

每步棋自动提取 6 维特征向量（子力/王安全/兵形/空间/出子/关键优势），对比走棋前后变化，生成中文诊断报告，注入 LLM 提示词。

### 局面型错误：不止看评分

7 类不反映为评分骤降的战略错误：坏象换好马、兵型受损、放弃中心、失去双象、王盾破损、开放线丧失、出子落后。

### 关键时刻聚焦

GothamChess 风格：60 步只深度展开 5-8 个教学节点，其余精简带过。

---

## 运行方式

```bash
# 一键生成（推荐）
python pipeline.py

# 指定风格和观众
python pipeline.py --style 战术解析 --audience 中级
python pipeline.py --style 战略漫谈 --audience 高级
python pipeline.py --style 学院课堂 --audience 初级

# 分步运行
python analyse.py              # 棋局分析 → analysis_result.json
python generate_commentary.py  # LLM 讲解词 → commentary.txt
python tts_tool.py             # TTS 语音 → commentary.mp3
python render_board.py         # 棋盘动画 → board_animation.mp4
python synthesize_video_python.py  # 视频合成 → final_video.mp4
python generate_report.py      # Word 棋评 → chess_analysis_report.docx

# Web 控制台
python web_ui.py

# 开局数据抓取
python fetch_opening_data.py   # 从 Lichess 递归抓取开局树 (BFS深度6, 上限1000)
```

---

## 风格模板

| 风格 | 适用场景 | 自动触发条件 |
|------|----------|-------------|
| **战术解析** | 中局激战、战术频发 | 失误≥4 或 战术≥5 |
| **战略漫谈** | 封闭局面、长线对局 | 长局(≥30步)+少失误 |
| **快评速览** | 短视频、社交媒体 | 短局(≤25步)+多失误 |
| **学院课堂** | 新手教学、少儿课程 | 短局(≤20步) |
| **自动** | 日常使用 | 根据对局数据智能匹配 |

3 级观众：**初级**（术语解释）/ **中级** / **高级**

---

## 配置指南

### API Key

复制 `api_config.example.json` 为 `api_config.json`，填入 Key：

```json
{
    "api_key": "sk-你的Key",
    "api_type": "deepseek",
    "model": "deepseek-v4-pro"
}
```

`api_config.json` 已被 `.gitignore` 排除，不会泄露。

### 引擎

```python
# analyse.py
STOCKFISH_PATH = r"D:\...\stockfish.exe"
LCO_ENABLE = True      # Lc0 神经网络交叉验证
MULTIPV = 3            # 每步候选走法数
```

### 棋盘外观

```python
# render_board.py
square_size = 70       # 格子像素
fps = 15               # 帧率
width = 1080, height = 810   # 视频尺寸 (4:3)
```

---

## 项目结构

```
agentchess/
│
├── 🎯 主流程
│   ├── pipeline.py              # 一键流水线
│   ├── web_ui.py                # Web 控制台
│   ├── analyse.py               # 棋局分析核心
│   └── organize_project.py      # 输出归档
│
├── ♟️ 分析模块 (15个)
│   ├── tactical_detector.py     # 战术检测 (7类)
│   ├── concept_extractor.py     # 战略概念 (6维)
│   ├── strategic_mistake_detector.py  # 局面型错误 (7类)
│   ├── critical_moment_detector.py    # 关键时刻 (6权重)
│   ├── position_explain.py      # ★ 局面可解释性
│   ├── branch_evaluator.py      # 分支讲解触发
│   ├── endgame_knowledge.py     # 残局知识分析
│   ├── master_games_db.py       # 大师对局数据库
│   ├── tablebase.py             # Syzygy 表库
│   ├── opening_explorer.py      # 开局数据库
│   ├── opening_knowledge.py     # 开局知识库 (30个)
│   ├── fetch_opening_data.py    # Lichess 开局抓取
│   ├── training_analyzer.py     # 训练要点 (双方)
│   ├── style_templates.py       # 风格模板 (4×3)
│   └── coach_explainer.py       # 提示词构建
│
├── 🎤 音视频
│   ├── tts_tool.py              # TTS + SSML + timing
│   ├── render_board.py          # 棋盘动画
│   ├── synthesize_video_python.py  # FFmpeg 合成
│   ├── parse_commentary.py      # 字幕生成
│   └── piece_generator.py       # 棋子 PNG
│
├── 📝 文档
│   ├── generate_report.py       # Word 棋评
│   └── generate_commentary.py   # LLM 讲解词
│
├── 📚 数据文件
│   ├── opening_knowledge.json   # 30 个开局知识
│   ├── opening_traits.json      # 12 类开局特征
│   ├── opening_theory.json      # 开局理论
│   ├── eco_table.json           # 80+ ECO FEN 表
│   ├── endgame_theory.json      # 残局理论
│   ├── api_config.example.json  # API 配置模板
│   └── opening_knowledge_fetched.json  # 自动抓取的开局
│
├── 🔧 引擎
│   ├── stockfish-windows-x86-64-avx2/
│   └── lc0-v0.32.1-windows-gpu-nvidia-cuda12/
│
├── 📂 输出
│   └── output/                  # 按对局归档
│
└── 🎨 素材
    ├── pieces/                  # 棋子 PNG (12个)
    └── pieces_svg/              # SVG 源文件 (12个)
```

---

## 常见问题

**Q: Lc0 加载失败？** → 权重路径必须纯 ASCII。不可用时自动降级为仅 Stockfish。

**Q: TTS 断网？** → 内置 3 次重试，全失败时自动生成静默占位。

**Q: 音画不同步？** → 删除 `timing.json` + `board_frames/` + `commentary.mp3` 重新生成。

**Q: 讲解太机械？** → 尝试不同风格：`--style 战略漫谈 --audience 初级`。

**Q: 如何添加开局？** → 编辑 `opening_knowledge.json` 或运行 `python fetch_opening_data.py` 自动抓取。

**Q: Lichess 开局抓取 401？** → Lichess API 已关闭。使用 `python fetch_opening_data.py` (Playwright 浏览器方式)。

---

## 扩展开发

```python
# 添加新的战术检测
# 编辑 tactical_detector.py → _detect_new_tactic() → 注册到 detect()

# 添加新的局面错误规则
# 编辑 strategic_mistake_detector.py → _rule_xxx() → 注册到 detect()

# 添加新的风格
# 编辑 style_templates.py → STYLE_TEMPLATES["我的风格"] = "..."

# 调整关键时刻权重
# 编辑 critical_moment_detector.py → WEIGHTS 字典
```

---

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| python-chess | 棋局逻辑、UCI 引擎 |
| Stockfish 17 | α-β 引擎 MultiPV |
| Lc0 v0.32.1 | 神经网络交叉验证 |
| Pillow | 棋盘渲染 |
| Edge TTS | 语音合成 |
| OpenAI SDK | LLM API |
| Flask | Web 控制台 |
| python-docx | Word 文档 |
| FFmpeg | 视频编码 |
| Playwright | Lichess 数据抓取 |

---

深蓝国际象棋协会出品 · 仅供学习交流使用