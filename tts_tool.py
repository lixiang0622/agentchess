"""
TTS 工具 v2 — 逐步生成音频 + 精确时长测量 + 音画字幕同步

新流程：
1. 解析讲解词为逐步文本（[STEP N] 分段）
2. 每步独立生成 TTS 音频（带 SSML 情感控制）
3. ffprobe 测量每段精确时长
4. 拼接全部音频 → commentary.mp3
5. 输出 timing.json（精确时间码）→ 供 render_board.py 帧分配
6. 输出 commentary.srt（精确字幕）
"""

import sys, json, re, os, subprocess, asyncio
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RE_HIGHLIGHT   = re.compile(r'\[高亮\s*[^\]]+\]')
RE_THREAT      = re.compile(r'\[威胁\s*[^\]]+\]')
RE_SELECTED    = re.compile(r'\[选中\s*[^\]]+\]')
RE_ARROW       = re.compile(r'\[箭头\s*[^\]]+\]')
RE_MINI_BOARD  = re.compile(r'\[小棋盘:\s*[^\]]+\]')
RE_WS          = re.compile(r'\s+')

QUALITY_SSML_MAP = {
    "妙手":   {"rate": "+18%", "pitch": "+10%", "volume": "loud"},
    "好棋":   {"rate": "+10%", "pitch": "+5%",  "volume": "loud"},
    "正常":   {"rate": "+0%",  "pitch": "+0%",  "volume": "medium"},
    "缓着":   {"rate": "-5%",  "pitch": "-2%",  "volume": "medium"},
    "疑问":   {"rate": "-10%", "pitch": "-3%",  "volume": "medium"},
    "失误":   {"rate": "-20%", "pitch": "-8%",  "volume": "medium"},
    "漏杀":   {"rate": "-15%", "pitch": "-5%",  "volume": "loud"},
    "送子":   {"rate": "-25%", "pitch": "-12%", "volume": "loud"},
}

# ---- 国际象棋走法拉丁符号 → 中文朗读翻译 ----
# 把 Nf3→马f3、Bb5+→象b5将军、exd5→e兵吃d5、O-O→王车易位 等转为 TTS 可朗读的中文

PIECE_CN = {'N': '马', 'B': '象', 'R': '车', 'Q': '后', 'K': '王'}

# 核心正则：匹配所有标准国际象棋走法记号
# 分组: \1=棋子字母, \2=消歧义/兵来源线, \3=吃子x, \4=目标格, \5=升变=Q, \6=升变棋子, \7=将军/将杀
RE_CHESS_MOVE = re.compile(
    r'([NBRQK])?'           # \1 棋子字母 (无=兵走法)
    r'([a-h]?[1-8]?)?'     # \2 消歧义或兵来源线
    r'(x)?'                 # \3 吃子标记
    r'([a-h][1-8])'         # \4 目标格 (必选)
    r'(=([NBRQK]))?'        # \5 升变标记, \6 升变棋子
    r'([+#])?'              # \7 将军/将杀
)

# 王车易位
RE_CASTLING_LONG  = re.compile(r'[O0]-[O0]-[O0]')
RE_CASTLING_SHORT = re.compile(r'[O0]-[O0]')


def _translate_move(m: re.Match) -> str:
    """将正则匹配到的国际象棋走法转为中文朗读文本"""
    parts = []
    piece = m.group(1)       # 棋子字母 N/B/R/Q/K 或 None
    disamb = m.group(2)      # 消歧义 (如 Nbd7 中的 b) 或兵来源线 (如 exd5 中的 e)
    capture = m.group(3)     # x 或 None
    dest = m.group(4)        # 目标格 (e4, d5, f3 等)
    promo_eq = m.group(5)    # 升变标记 (=Q, =R 等) 或 None
    promo_pc = m.group(6)    # 升变棋子字母 或 None
    check = m.group(7)       # + / # 或 None

    if piece:
        # 棋子走法: Nf3→马f3, Bb5+→象b5将军, Qxf7#→后吃f7将杀
        parts.append(PIECE_CN.get(piece, piece))
        if disamb:
            parts.append(disamb)               # 消歧义坐标 (如 Nbd7→马b到d7)
        if capture:
            parts.append('吃')
        parts.append(dest)
    else:
        # 兵走法
        if capture:
            # exd5→e兵吃d5, dxe8=Q→d兵吃e8升变为后
            if disamb:
                parts.append(f'{disamb}兵')
            else:
                parts.append('兵')
            parts.append('吃')
            parts.append(dest)
        else:
            # e4→e4, d5→d5 (简单兵走法，保留坐标)
            parts.append(dest)

    if promo_eq and promo_pc:
        parts.append('升变为')
        parts.append(PIECE_CN.get(promo_pc, promo_pc))

    if check:
        parts.append('将军' if check == '+' else '将杀')

    return ''.join(parts)


def _clean(text: str) -> str:
    """清理画面指令 + 翻译国际象棋走法为中文朗读文本"""
    # 第一步：去掉画面指令 [高亮 ...] [威胁 ...] [选中 ...] [箭头 ...] [小棋盘: ...]
    for r in [RE_HIGHLIGHT, RE_THREAT, RE_SELECTED, RE_ARROW, RE_MINI_BOARD]:
        text = r.sub('', text)
    # 第二步：王车易位 (先处理长的 O-O-O 再处理短的 O-O)
    text = RE_CASTLING_LONG.sub('长易位', text)
    text = RE_CASTLING_SHORT.sub('王车易位', text)
    # 第三步：走法符号翻译为中文 (Bb5→象b5, exd5→e兵吃d5 等)
    text = RE_CHESS_MOVE.sub(_translate_move, text)
    # 第四步：合并多余空白
    return RE_WS.sub(' ', text).strip()


def load_quality_map(analysis_json: Path) -> dict:
    if not analysis_json.exists():
        return {}
    try:
        with analysis_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
        steps = data.get("steps", data)
        return {s["move_number"]: s.get("quality", "正常") for s in steps}
    except Exception:
        return {}


def parse_steps(commentary_text: str, step_qualities: dict) -> list:
    """
    解析讲解词 → 逐步结构化数据
    返回: [{"step": 1, "text": "清理后的文字", "quality": "正常"}]
    """
    pattern = r"\[STEP\s*(\d+)\]\s*(.*?)(?=\[STEP\s*\d+\]|$)"
    steps = []
    for m in re.finditer(pattern, commentary_text, re.DOTALL):
        sn = int(m.group(1))
        raw = m.group(2).strip()
        clean = _clean(raw)
        if not clean:
            continue
        q = step_qualities.get(sn, "正常")
        steps.append({"step": sn, "text": clean, "quality": q})
    return steps


def _find_ffmpeg():
    """查找 ffmpeg 可执行文件"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    for cand in ["ffmpeg", "ffmpeg.exe"]:
        try:
            subprocess.run([cand, "-version"],
                           stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           timeout=5)
            return cand
        except Exception:
            continue
    return None


def get_audio_duration(filepath: Path) -> float:
    """用 ffmpeg 获取音频精确时长；用 UTF-8 编码避免 Windows GBK 乱码"""
    if filepath.stat().st_size == 0:
        return 1.5
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        try:
            r = subprocess.run(
                [ffmpeg, "-i", str(filepath)],
                capture_output=True, text=True, timeout=15,
                encoding="utf-8", errors="replace"
            )
            out = r.stderr if r.stderr else r.stdout
            for line in out.split('\n'):
                if 'Duration' in line:
                    time_str = line.strip().split('Duration:')[1].split(',')[0].strip()
                    h, m, s = time_str.split(':')
                    return float(h)*3600 + float(m)*60 + float(s)
        except Exception:
            pass
    try:
        file_size_kb = filepath.stat().st_size / 1024
        return max(1.0, file_size_kb / 6.0)
    except Exception:
        return 2.0


async def generate_step_audio_async(text: str, output_path: Path,
                                     voice: str = "zh-CN-YunxiNeural"):
    """生成单步音频 — 纯文本，不包装 SSML"""
    from edge_tts import Communicate
    comm = Communicate(text=text, voice=voice)
    await comm.save(str(output_path))


def build_timing_and_concat(steps_data: list, work_dir: Path,
                             output_mp3: Path, voice: str = "zh-CN-YunxiNeural"):
    """
    核心同步函数：
    1. 每步生成独立 MP3
    2. 测量时长
    3. 拼接
    4. 生成 timing.json + SRT
    """
    steps_dir = work_dir / "step_audio"
    steps_dir.mkdir(parents=True, exist_ok=True)

    print(f"  逐步生成 TTS 音频 ({len(steps_data)} 步)...")

    # 生成每步音频（带重试 + 请求间隔防止限流 + 长文本截断）
    import time as _time
    last_success_time = 0
    for i, sd in enumerate(steps_data):
        mp3_path = steps_dir / f"step_{sd['step']:03d}.mp3"
        if mp3_path.exists():
            mp3_path.unlink()

        text = sd["text"]
        # Edge TTS 单次文本不宜过长，超过 500 字截断
        if len(text) > 500:
            text = text[:497] + "..."

        # 请求间隔至少 0.5 秒，避免触发限流
        elapsed = _time.time() - last_success_time
        if elapsed < 0.5:
            _time.sleep(0.5 - elapsed)

        # 重试最多 4 次，间隔递增
        success = False
        for attempt in range(4):
            try:
                asyncio.run(generate_step_audio_async(text, mp3_path, voice))
                success = True
                last_success_time = _time.time()
                break
            except Exception as e:
                if attempt < 3:
                    wait = (attempt + 1) * 4  # 4s, 8s, 12s
                    print(f"    ⚠ 第{sd['step']}步 第{attempt+1}次失败, {wait}s后重试...")
                    _time.sleep(wait)
                else:
                    print(f"    ⚠ 第{sd['step']}步 TTS 失败(已重试4次): {e}")

        if not success:
            # 生成静默占位 — 使用 imageio_ffmpeg 的 ffmpeg
            silence_wav = steps_dir / f"step_{sd['step']:03d}.wav"
            try:
                import wave as _wave
                wf = _wave.open(str(silence_wav), 'w')
                wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(24000)
                dur_sec = max(1, len(sd['text']) // 3)
                wf.writeframes(b'\x00' * 24000 * dur_sec)
                wf.close()
                # 用已探测到的 ffmpeg 转换
                _ff = _find_ffmpeg()
                if _ff:
                    subprocess.run([_ff, "-y", "-i", str(silence_wav),
                                   "-codec:a", "libmp3lame", "-b:a", "64k",
                                   str(mp3_path)],
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL,
                                   timeout=30)
            except Exception:
                pass

        sd["mp3_path"] = str(mp3_path)
        if (i + 1) % 5 == 0:
            print(f"    {i+1}/{len(steps_data)} 步...")

    # 测量每段时长
    print("  测量每段精确时长...")
    current_time = 0.0
    timing = []
    for sd in steps_data:
        mp3 = Path(sd["mp3_path"])
        dur = get_audio_duration(mp3) if mp3.exists() else 1.0
        dur = max(dur, 0.5)
        timing.append({
            "step": sd["step"],
            "start": round(current_time, 3),
            "duration": round(dur, 3),
            "end": round(current_time + dur, 3),
            "text": sd["text"],
            "quality": sd["quality"],
        })
        current_time += dur

    total_duration = current_time
    print(f"  总时长: {total_duration:.1f} 秒")

    # 保存 timing.json
    timing_path = work_dir / "timing.json"
    with timing_path.open("w", encoding="utf-8") as f:
        json.dump({"steps": timing, "total_duration": round(total_duration, 1)},
                  f, ensure_ascii=False, indent=2)
    print(f"  timing.json 已保存: {timing_path}")

    # 拼接所有 MP3（跳过 0 字节文件）
    print("  拼接音频...")
    concat_list = work_dir / "concat_list.txt"
    skipped = []
    with concat_list.open("w", encoding="utf-8") as f:
        for sd in steps_data:
            mp3 = Path(sd["mp3_path"])
            if mp3.exists() and mp3.stat().st_size > 0:
                f.write(f"file '{mp3.as_posix()}'\n")
            else:
                skipped.append(sd["step"])
                print(f"    ⚠ 跳过空文件: step_{sd['step']:03d}.mp3")
    if skipped:
        print(f"  ⚠ 跳过 {len(skipped)} 个空文件: {skipped}")

    # 查找 ffmpeg
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        try:
            # 使用 Popen + communicate 避免 capture_output 管道死锁
            # ffmpeg 拼接 52 个文件时 stderr 输出非常多，直接用 PIPE 会填满缓冲区死锁
            proc = subprocess.Popen(
                [ffmpeg, "-y", "-f", "concat", "-safe", "0",
                 "-i", str(concat_list), "-codec", "copy",
                 str(output_mp3)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace"
            )
            # communicate() 在内部线程中读取管道，不会死锁
            _stdout, _stderr = proc.communicate(timeout=180)
            if proc.returncode != 0:
                # 截取最后 500 字符的错误信息
                err_tail = (_stderr or "").strip()[-500:]
                print(f"⚠ ffmpeg 返回非零状态码 ({proc.returncode}): {err_tail}")
            else:
                print(f"✓ 拼接完成: {output_mp3}")
        except subprocess.TimeoutExpired:
            proc.kill()
            _stdout, _stderr = proc.communicate()
            print(f"⚠ ffmpeg 拼接超时 (180s)，已终止")
        except Exception as e:
            print(f"⚠ 拼接失败: {e}")
    else:
        print("⚠ 未找到 ffmpeg，跳过音频拼接（可手动用 audacity 拼接 step_audio/ 中的文件）")

    # 生成 SRT
    generate_srt_from_timing(timing, work_dir / "commentary.srt")

    return timing_path


def generate_srt_from_timing(timing: list, output_path: Path):
    """从精确 timing 生成 SRT 字幕"""
    lines = []
    for i, t in enumerate(timing, 1):
        start = t["start"]
        end = t["end"]
        lines.append(str(i))
        lines.append(f"{_srt_ts(start)} --> {_srt_ts(end)}")
        lines.append(t["text"])
        lines.append("")
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✓ SRT 字幕: {output_path} ({len(timing)} 条)")


def _srt_ts(sec: float) -> str:
    h = int(sec) // 3600
    m = (int(sec) % 3600) // 60
    s = int(sec) % 60
    ms = int((sec % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    script_dir = Path(__file__).parent
    commentary_file = script_dir / "commentary.txt"
    analysis_json = script_dir / "analysis_result.json"

    if not commentary_file.exists():
        print(f"❌ 讲解词文件不存在: {commentary_file}")
        return

    print("=" * 60)
    print("TTS 工具 v2 — 逐步精确同步")
    print("=" * 60)

    commentary = commentary_file.read_text(encoding="utf-8")
    step_qualities = load_quality_map(analysis_json)
    steps_data = parse_steps(commentary, step_qualities)

    if not steps_data:
        print("❌ 未能从讲解词解析出任何步骤")
        return

    print(f"  解析到 {len(steps_data)} 步")

    output_mp3 = script_dir / "commentary.mp3"
    build_timing_and_concat(steps_data, script_dir, output_mp3)

    print("\n✓ 完成 — timing.json 可供 render_board.py 精确同步")


if __name__ == "__main__":
    main()
