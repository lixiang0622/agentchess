# ♟️ DeepBlue Chess · 国际象棋 AI 讲解视频生成器

一键将 Lichess PGN 自动转换为**AI 语音讲解视频 + 深度棋评文档 + 双方训练报告**。

> 深蓝国际象棋协会出品 · 仅供学习交流

---

## 快速开始

```bash
pip install python-chess Pillow imageio-ffmpeg edge-tts openai python-docx flask playwright
playwright install chromium

cd agentchess
python pipeline.py
```

将 Lichess 对局 PGN 文件放入项目目录，或直接使用 URL 抓取：

```bash
python fetch_game.py https://lichess.org/abc123XYZ
```

[![GitHub](https://img.shields.io/badge/GitHub-lixiang0622%2Fagentchess-blue)](https://github.com/lixiang0622/agentchess)

---

## 一分钟看懂

```
你提供: PGN 棋谱（或 Lichess URL）
系统自动:
  1. Stockfish + Lc0 双引擎分析每一步
  2. 15 个知识库模块提取棋理（开局/中局/残局/战术/战略/大师对比）
  3. AI 讲解员（深蓝）用教练口吻写出 5000-8000 字讲解词
  4. TTS 中文语音朗读（带情感控制）
  5. 棋盘动画渲染（高亮 + 箭头 + 右下角支线小棋盘）
  6. 合成横屏 1080×810 视频
  7. 生成 Word 棋评文档 + 双方训练要点
输出: final_video.mp4 + 棋评报告 + 训练要点
```

### 效果对比

| | 之前 | 现在 |
|------|------|------|
| 讲解方式 | "黑方走了 e5，评分从 -0.4 变成了 +1.2" | "黑方 e5 推进后中心控制力骤降，同时让白方马在 d5 建立了铁马据点——这就是评分倒向白方的原因" |
| 知识深度 | 只报评分数字 | 引用开局理论、中局棋理、残局口诀、大师对比 |
| 错误分析 | "这步是失误" | "这是一步典型的局面型错误——在封闭局面下用象换马，马在兵多的局面中比象灵活得多" |

---

## 系统架构

```
┌──────────────────────────────────────────────────────────────┐
│  输入: PGN 文件 或 Lichess/Chess.com URL                      │
│        fetch_game.py                                          │
└──────────────────────────┬───────────────────────────────────┘
                           ↓
┌──────────────────────────────────────────────────────────────┐
│  analyse.py · 棋局分析引擎                                     │
│                                                              │
│  ┌──────────┬──────────┬──────────┬───────────┬────────────┐ │
│  │Stockfish │   Lc0    │  Syzygy  │战术检测器  │概念提取器   │ │
│  │MultiPV=3 │ 神经网络  │  残局库  │   (7类)   │   (6维)    │ │
│  └──────────┴──────────┴──────────┴───────────┴────────────┘ │
│  ┌──────────┬──────────┬──────────┬───────────┬────────────┐ │
│  │关键时刻  │局面型错误│可解释性  │残局知识   │分支触发器   │ │
│  │(6权重)   │  (7类)   │(诊断报告) │(引擎vs表库)│  (7条件)  │ │
│  └──────────┴──────────┴──────────┴───────────┴────────────┘ │
│  ┌──────────┬──────────┬──────────┬───────────┐              │
│  │大师对局库│开局知识库│中局知识库│陷阱发现器  │              │
│  │(80开局)  │(6类32条) │(7类40条) │(自动标记)  │              │
│  └──────────┴──────────┴──────────┴───────────┘              │
└──────────────────────┬───────────────────────────────────────┘
                       ↓ analysis_result.json
┌──────────────────────────────────────────────────────────────┐
│  pipeline.py · 讲解词生成                                     │
│  风格模板(4×3级) → 多维度上下文 → 大模型 API → commentary.txt │
└──────────────────────┬───────────────────────────────────────┘
                       ↓
┌──────────────────────────────────────────────────────────────┐
│  音视频流水线                                                 │
│  parse → TTS(SSML情感) → render_board → ffmpeg 合成          │
│                                       + Word 棋评             │
└──────────────────────┬───────────────────────────────────────┘
                       ↓
          final_video.mp4 + 训练报告 + 棋评文档
```

---

## 核心模块 (19 个)

### 分析引擎

| # | 模块 | 功能 |
|---|------|------|
| 1 | `analyse.py` | 主引擎：Stockfish MultiPV + 全部子模块调度 |
| 2 | `tactical_detector.py` | 7 类战术：击双/牵制/串击/闪击/引离/中间着/杀棋 |
| 3 | `concept_extractor.py` | 6 维战略概念：王安全/开放线/空间/兵形/机动性/子力 |
| 4 | `strategic_mistake_detector.py` | 7 类局面型错误：坏象换好马/兵型受损/放弃中心等 |
| 5 | `critical_moment_detector.py` | 关键时刻检测：6 权重评分 → 详写/中写/略写分配 |
| 6 | **`position_explain.py`** | **局面可解释性：6 维特征 → 变化对比 → 诊断报告** |
| 7 | `branch_evaluator.py` | 分支讲解触发：7 条件 + 连续抑制 + 上限控制 |
| 8 | `endgame_knowledge.py` | 残局分析：类型识别 + 引擎 vs 表库矛盾 |
| 9 | `tablebase.py` | Syzygy 残局库 (本地 + Lichess API) |
| 10 | `master_games_db.py` | 大师对局库：FEN 哈希 + Lichess API 后备 |
| 11 | `opening_knowledge.py` | 开局知识库：**80 个**主流开局的计划/陷阱/棋手 |

### 知识库

| # | 模块 | 内容 |
|---|------|------|
| 12 | `midgame_knowledge.py` | 中局棋理：**6 类 32 条**原则，自动匹配注入 |
| 13 | `endgame_principles.json` | 残局口诀：**7 类 40+ 条**教材级原则 |
| 14 | `opening_knowledge.json` | 开局百科：**80 个**变例的结构化知识 |
| 15 | `midgame_principles.json` | 中局原则：兵型/中心/子力/王安全/兑换/计划 |

### 服务化

| # | 模块 | 功能 |
|---|------|------|
| 16 | `fetch_game.py` | Lichess/Chess.com URL 自动下载 PGN |
| 17 | `trap_discoverer.py` | 从实战中发现新陷阱 → 审核 → 合并到知识库 |
| 18 | `update_master_db.py` | TWIC 每周更新大师对局索引 |
| 19 | `fetch_opening_data.py` | Playwright 递归抓取 Lichess 开局树 (BFS 深度6) |

### 音视频 & 工具

| 模块 | 功能 |
|------|------|
| `pipeline.py` | 一键流水线主控 |
| `style_templates.py` | 4 种讲解风格 × 3 级观众 |
| `tts_tool.py` | Edge TTS + SSML 情感语音 |
| `render_board.py` | 棋盘动画（主棋盘 + 小棋盘 + 高亮/箭头/片头片尾） |
| `synthesize_video_python.py` | FFmpeg 音视频混流 |
| `generate_report.py` | Word 棋评文档 |
| `training_analyzer.py` | 分别给黑白双方出训练建议 |
| `web_ui.py` | Web 控制台 (Flask + SSE) |

---

## 运行方式

```bash
# 一键生成
python pipeline.py --style 战术解析 --audience 中级

# 从 URL 开始
python fetch_game.py https://lichess.org/abc123
python pipeline.py

# 分步调试
python analyse.py                     # 1.棋局分析
python pipeline.py                    # 2.讲解词+音视频
python generate_report.py             # 3.Word 文档

# Web 界面
python web_ui.py                      # http://localhost:5000

# 大师库维护
python update_master_db.py --auto     # 每周更新
python fetch_opening_data.py          # 抓取开局数据
```

### 风格模板

| 风格 | 适用场景 | 触发条件 |
|------|----------|----------|
| 战术解析 | 中局激战 | 失误≥4 / 战术≥5 |
| 战略漫谈 | 封闭局面 | 长局+少失误 |
| 快评速览 | 短视频 | 短局+多失误 |
| 学院课堂 | 新手教学 | 短局 |
| 自动 | 日常推荐 | 智能匹配 |

---

## 配置

复制 `api_config.example.json` → `api_config.json` 填入 Key：

```json
{
    "api_key": "sk-你的Key",
    "api_type": "deepseek",
    "model": "deepseek-v4-pro"
}
```

---

## 项目结构

```
agentchess/
├── 🎯 流水线入口
│   ├── pipeline.py                   # 一键生成
│   ├── web_ui.py                     # Web 控制台
│   └── analyse.py                    # 棋局分析核心
│
├── ♟️ 19 个分析/知识模块
│   ├── tactical_detector.py          # 战术检测
│   ├── concept_extractor.py          # 战略概念
│   ├── strategic_mistake_detector.py # 局面型错误
│   ├── critical_moment_detector.py   # 关键时刻
│   ├── position_explain.py           # 可解释性
│   ├── branch_evaluator.py           # 分支触发
│   ├── endgame_knowledge.py          # 残局分析
│   ├── tablebase.py                  # Syzygy 表库
│   ├── master_games_db.py            # 大师对局库
│   ├── opening_knowledge.py          # 开局知识库
│   ├── midgame_knowledge.py          # 中局知识库
│   ├── fetch_game.py                 # API PGN 抓取
│   ├── trap_discoverer.py            # 陷阱发现
│   ├── update_master_db.py           # 大师库更新
│   ├── fetch_opening_data.py         # 开局抓取
│   ├── training_analyzer.py          # 训练要点
│   ├── style_templates.py            # 风格模板
│   └── coach_explainer.py            # 提示词构建
│
├── 📚 知识库文件
│   ├── opening_knowledge.json        # 80 个开局
│   ├── midgame_principles.json       # 32 条中局原则
│   ├── endgame_principles.json       # 40+ 条残局原则
│   ├── opening_traits.json           # 12 类开局特征
│   ├── opening_theory.json           # 开局理论
│   ├── eco_table.json                # 80+ ECO FEN 表
│   └── endgame_theory.json           # 残局理论
│
├── 🎤 音视频
│   ├── tts_tool.py                   # TTS + SSML + timing
│   ├── render_board.py               # 棋盘动画渲染
│   ├── synthesize_video_python.py    # FFmpeg 合成
│   ├── parse_commentary.py           # 字幕生成
│   └── piece_generator.py            # 棋子 PNG
│
├── 🔧 引擎
│   ├── stockfish-windows-x86-64-avx2/
│   └── lc0-v0.32.1-windows-gpu-nvidia-cuda12/
│
├── 📂 输出
│   └── output/
│       └── <日期_白方_vs_黑方_ECO>/
│           ├── final_video.mp4
│           ├── chess_analysis_report.docx
│           ├── commentary.mp3 / .srt
│           ├── training_points.json
│           └── ...
│
└── 📄 配置
    ├── api_config.example.json        # API 模板
    └── api_config.json               # 你的 Key（git忽略）
```

---

## 设计理念

**三层架构**：事实层(引擎) → 概念层(检测器) → 语言层(LLM)。LLM 不直接看棋盘，而是看到已经提取好的棋理概念。

**从"是什么"到"为什么"**：`position_explain.py` 自动对比走棋前后的 6 维特征向量（子力/王安全/兵形/空间/出子/关键优势），生成诊断报告，解释评分变化背后的棋理原因。

**知识大脑**：80 个开局 + 32 条中局原则 + 40 条残局口诀 → 像特级大师一样讲解。

**自生长**：`trap_discoverer.py` 自动发现新陷阱，`update_master_db.py` 每周更新大师库。

---

## 技术栈

| 组件 | 用途 |
|------|------|
| Python 3.10+ | 运行环境 |
| python-chess | 棋局逻辑 |
| Stockfish 17 | α-β 引擎 MultiPV |
| Lc0 v0.32.1 | 神经网络交叉验证 |
| Pillow | 棋盘渲染 |
| Edge TTS | 中文语音合成 |
| OpenAI SDK | 大模型 API |
| Playwright | Lichess 数据抓取 |
| FFmpeg | 视频编码 |

---

## 常见问题

**Q: Lc0 加载失败？** → 权重路径必须纯 ASCII。不可用时自动降级。

**Q: TTS 断网？** → 3 次重试，全失败自动静默占位。

**Q: 音画不同步？** → 删除 `timing.json`、`board_frames/`、`commentary.mp3` 重新生成。

**Q: 如何添加开局？** → 编辑 `opening_knowledge.json` 或运行 `python fetch_opening_data.py`。

**Q: 如何更新大师库？** → `python update_master_db.py --auto` 每周运行。

---

深蓝国际象棋协会 · v1.0.0 · 仅供学习交流