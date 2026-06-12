# ♟️ DeepBlue Chess · 国际象棋 AI 讲解视频生成器

一键将 Lichess PGN 自动转换为**AI 语音讲解视频 + 深度棋评文档 + 双方训练报告**。

> 深蓝国际象棋协会出品 · v1.0.0 · 仅供学习交流

---

## 👀 一分钟看懂

```
你只需要提供: PGN 棋谱（或 Lichess URL）
系统自动完成:
  Stockfish + Lc0 双引擎分析 → 15个知识库注入棋理 →
  AI讲解员生成5000-8000字讲解词 → TTS中文语音朗读 →
  棋盘动画渲染（高亮/箭头/支线小棋盘/动态镜头推拉） →
  合成1080×810视频 → Word棋评 → 双方训练要点
输出: final_video.mp4 + 棋评报告 + 训练报告
```

### 讲解效果对比

| | 之前 | 现在 |
|------|------|------|
| 评分变化 | "评分从 +0.3 跌到了 -1.8" | "中心控制力骤降50%，白方马在d5建立起铁马据点——叠加王前新开放线，评分瞬间倒向白方" |
| 错误分析 | "这是一步失误" | "典型的局面型错误——封闭局面下用象换马，马在兵多时比象灵活得多" |
| 知识深度 | 只报数字 | 引用80个开局理论 + 32条中局棋理 + 40条残局口诀 + 大师对局对比 |
| 视频画面 | 固定视角 | 动态摄像机：王翼激战时自动推近特写，平稳时恢复全局 |

---

## 快速开始

```bash
# 安装
pip install python-chess Pillow imageio-ffmpeg edge-tts openai python-docx flask playwright
playwright install chromium

# 配置 API Key
cp api_config.example.json api_config.json   # 填入你的 Key

# 一键生成
python pipeline.py
```

从 URL 直接抓取：
```bash
python fetch_game.py https://lichess.org/abc123XYZ
python pipeline.py
```

---

## 系统架构

```
输入: PGN / Lichess URL / Chess.com URL
  │
  ▼
┌─────────────────────────────────────────────────────┐
│  analyse.py · 双引擎棋局分析                          │
│                                                     │
│  Stockfish 17 (MultiPV=3)  +  Lc0 v0.32.1 (神经网络) │
│                                                     │
│  ┌──────────┬──────────┬──────────┬──────────────┐  │
│  │ 战术检测  │ 概念提取  │ 局面错误 │ 可解释性     │  │
│  │  7类     │  6维     │  7类    │ 诊断报告     │  │
│  ├──────────┼──────────┼──────────┼──────────────┤  │
│  │ 关键时刻  │ 分支触发  │ 残局知识 │ 大师对比     │  │
│  │ 6权重    │  7条件   │ 引擎vs表库│ 80+开局     │  │
│  ├──────────┼──────────┼──────────┼──────────────┤  │
│  │ 中局知识  │ 陷阱发现  │ 开局知识 │  Syzygy     │  │
│  │ 6类32条  │ 自动标记  │  80变例  │  残局库     │  │
│  └──────────┴──────────┴──────────┴──────────────┘  │
└──────────────────────┬──────────────────────────────┘
                       ▼ analysis_result.json
┌─────────────────────────────────────────────────────┐
│  pipeline.py · AI讲解词生成                           │
│  风格模板(4×3级) → 多维度上下文 → LLM API            │
│  四维度质量评估 + 自动重写                            │
└──────────────────────┬──────────────────────────────┘
                       ▼ commentary.txt
┌─────────────────────────────────────────────────────┐
│  音视频流水线                                        │
│  parse → TTS(SSML情感) → render_board(动态镜头)      │
│  → ffmpeg → final_video.mp4 + Word棋评               │
└─────────────────────────────────────────────────────┘
```

---

## 核心模块

### 分析引擎 (11个)

| 模块 | 功能 |
|------|------|
| `analyse.py` | 主引擎：双引擎分析 + 全部子模块调度 |
| `tactical_detector.py` | 7类战术：击双/牵制/串击/闪击/引离/中间着/杀棋 |
| `concept_extractor.py` | 6维战略概念：王安全/开放线/空间/兵形/机动性/子力 |
| `strategic_mistake_detector.py` | 7类局面型错误：坏象换好马/兵型受损/放弃中心等 |
| `critical_moment_detector.py` | 关键时刻检测：6权重 → 详写/中写/略写 |
| `position_explain.py` | **局面可解释性**：6维特征 → 变化对比 → 诊断报告 |
| `branch_evaluator.py` | 分支触发：7条件 + 连续抑制 + 上限控制 |
| `endgame_knowledge.py` | 残局分析：类型识别 + 引擎vs表库矛盾 |
| `tablebase.py` | Syzygy残局库 (本地 + Lichess API) |
| `master_games_db.py` | 大师对局库：FEN哈希 + Lichess API |
| `opening_knowledge.py` | 开局知识库：80个变例的计划/陷阱/棋手 |

### 知识大脑 (4个)

| 模块 | 内容 |
|------|------|
| `opening_knowledge.json` | 开局百科：**80个**变例 |
| `midgame_principles.json` | 中局棋理：**6类32条**原则 |
| `endgame_principles.json` | 残局口诀：**7类40+条**原则 |
| `midgame_knowledge.py` | 中局匹配引擎：自动标签→棋理注入 |

### 服务化 (4个)

| 模块 | 功能 |
|------|------|
| `fetch_game.py` | Lichess/Chess.com URL → PGN |
| `fetch_opening_data.py` | Playwright BFS递归抓取Lichess开局树 |
| `trap_discoverer.py` | 自动发现新陷阱 → 审核 → 合并 |
| `update_master_db.py` | TWIC每周更新大师索引 |

### 画质与评估 (3个)

| 模块 | 功能 |
|------|------|
| `render_board.py` | 棋盘动画 + **动态摄像机推拉** + 小棋盘 + 片头片尾 |
| `commentary_evaluator.py` | **四维度评分** (准确/趣味/教学/术语) + 自动重写 |
| `celery_tasks.py` | **分布式队列** (Celery+Redis) + 批量处理 |

### 流水线 & 工具 (8个)

| 模块 | 功能 |
|------|------|
| `pipeline.py` | 一键流水线主控 |
| `style_templates.py` | 4种风格×3级观众 + 自动选择 |
| `tts_tool.py` | Edge TTS + SSML情感控制 |
| `synthesize_video_python.py` | FFmpeg 音视频混流 |
| `generate_report.py` | Word 棋评文档 |
| `training_analyzer.py` | **分别评价黑白双方** + 可量化练习 |
| `parse_commentary.py` | 讲解词解析 + SRT字幕 |
| `web_ui.py` | Web控制台 (Flask + SSE) |

---

## 运行方式

```bash
# 一键生成
python pipeline.py

# 指定风格和观众
python pipeline.py --style 战术解析 --audience 中级

# 开启质量评估+自动重写
python pipeline.py --enable-evaluation

# 分步调试
python analyse.py                    # 1.棋局分析
python pipeline.py                   # 2.讲解词+视频
python generate_report.py            # 3.Word文档

# 从URL开始
python fetch_game.py https://lichess.org/abc123

# Web界面
python web_ui.py                     # http://localhost:5000

# 大师库维护
python update_master_db.py --auto    # 每周更新

# 开局数据抓取
python fetch_opening_data.py         # Lichess递归BFS

# 陷阱发现
python trap_discoverer.py --discover # 自动检测候选陷阱
python trap_discoverer.py --review   # 交互式审核

# 分布式处理
celery -A celery_tasks worker -l info  # 后台worker
```

### 风格模板

| 风格 | 适用场景 |
|------|----------|
| 战术解析 | 中局激战、战术频发 |
| 战略漫谈 | 封闭局面、长线对局 |
| 快评速览 | 短视频、社交媒体 |
| 学院课堂 | 新手教学、少儿课程 |
| 自动 | 根据对局数据智能匹配 |

---

## 配置

```json
// api_config.json (从 api_config.example.json 复制)
{
    "api_key": "sk-你的Key",
    "api_type": "deepseek",
    "model": "deepseek-v4-pro"
}
```

`api_config.json` 已被 `.gitignore` 排除。

---

## 项目结构

```
agentchess/
│
├── 🎯 流水线
│   ├── pipeline.py              # 一键生成主入口
│   ├── web_ui.py                # Web控制台
│   ├── analyse.py               # 棋局分析核心引擎
│   └── generate_commentary.py   # 交互式讲解词生成
│
├── ♟️ 分析引擎 (11个)
│   ├── tactical_detector.py     # 战术检测 (7类)
│   ├── concept_extractor.py     # 战略概念 (6维)
│   ├── strategic_mistake_detector.py  # 局面型错误 (7类)
│   ├── critical_moment_detector.py    # 关键时刻 (6权重)
│   ├── position_explain.py      # 局面可解释性
│   ├── branch_evaluator.py      # 分支讲解触发
│   ├── endgame_knowledge.py     # 残局知识分析
│   ├── tablebase.py             # Syzygy残局库
│   ├── master_games_db.py       # 大师对局库
│   ├── opening_knowledge.py     # 开局知识库
│   └── opening_explorer.py      # 开局数据库
│
├── 📚 知识大脑 (4个)
│   ├── opening_knowledge.json   # 80个开局
│   ├── midgame_principles.json  # 32条中局原则
│   ├── endgame_principles.json  # 40+条残局原则
│   └── midgame_knowledge.py     # 中局匹配引擎
│
├── 🚀 服务化 (4个)
│   ├── fetch_game.py            # URL→PGN
│   ├── fetch_opening_data.py    # Lichess开局抓取
│   ├── trap_discoverer.py       # 陷阱自动发现
│   └── update_master_db.py      # 大师库更新
│
├── 📺 画质与评估 (3个)
│   ├── render_board.py          # 棋盘动画+动态镜头
│   ├── commentary_evaluator.py  # 四维度质量评估
│   └── celery_tasks.py          # 分布式任务队列
│
├── 🎤 音视频
│   ├── tts_tool.py              # TTS+SSML+timing
│   ├── synthesize_video_python.py  # FFmpeg合成
│   ├── parse_commentary.py      # 字幕生成
│   └── piece_generator.py       # 棋子PNG
│
├── 📝 文档
│   ├── generate_report.py       # Word棋评
│   ├── training_analyzer.py     # 训练要点(双方)
│   ├── style_templates.py       # 风格模板(4×3)
│   └── coach_explainer.py       # 提示词构建
│
├── 📚 数据文件
│   ├── eco_table.json           # 80+ ECO FEN表
│   ├── opening_traits.json      # 12类开局特征
│   ├── opening_theory.json      # 开局理论
│   └── endgame_theory.json      # 残局理论
│
├── 🔧 引擎
│   ├── stockfish-windows-x86-64-avx2/
│   └── lc0-v0.32.1-windows-gpu-nvidia-cuda12/
│
├── 📄 配置
│   ├── api_config.example.json
│   └── api_config.json (你的Key，git忽略)
│
└── 📂 输出
    └── output/
        └── <日期_白方_vs_黑方_ECO>/
            ├── final_video.mp4
            ├── chess_analysis_report.docx
            ├── commentary.mp3 / .srt
            ├── training_points.json
            └── ...
```

---

## 常见问题

| 问题 | 解决 |
|------|------|
| Lc0 加载失败 | 权重路径必须纯ASCII。不可用时自动降级为仅Stockfish |
| TTS断网 | 3次重试，全失败自动静默占位 |
| 音画不同步 | 删除 `timing.json`、`board_frames/`、`commentary.mp3` 重新生成 |
| 讲解太机械 | `--style 战略漫谈 --audience 初级` 或 `--enable-evaluation` 自动优化 |
| 如何添加开局 | 编辑 `opening_knowledge.json` 或 `python fetch_opening_data.py` |
| 如何更新大师库 | `python update_master_db.py --auto` 每周运行 |
| Redis不可用 | Celery自动回退到线程模式 |

---

## 技术栈

Python 3.10+ · python-chess · Stockfish 17 · Lc0 v0.32.1 · Pillow · Edge TTS · OpenAI SDK · Playwright · FFmpeg · Flask · Celery · Redis

---

深蓝国际象棋协会 · v1.0.0 · 仅供学习交流