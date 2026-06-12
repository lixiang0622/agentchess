import sys
import json
import re
from pathlib import Path
from typing import Dict, Tuple

# Force UTF-8 output in Windows terminals
sys.stdout.reconfigure(encoding="utf-8")


def parse_commentary(commentary_text: str) -> Dict[int, str]:
    """
    从 LLM 生成的讲解词中提取每一步的内容
    
    输入格式：
    [STEP 1] 白方e4，占领中心...
    [STEP 2] 黑方选择西西里防御...
    
    返回: {1: "白方e4，占领中心...", 2: "黑方选择西西里防御..."}
    """
    pattern = r"\[STEP (\d+)\]\s*(.*?)(?=\[STEP \d+\]|$)"
    matches = re.findall(pattern, commentary_text, re.DOTALL)
    
    step_commentary = {int(num): text.strip() for num, text in matches}
    return step_commentary


def load_analysis_data(json_path: Path):
    """加载分析数据 — 兼容新旧格式"""
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    steps = data.get("steps", data)  # 新格式: {opening_profile, steps}, 旧格式: [...]
    return steps


def merge_data(steps_analysis: list, step_commentary: Dict[int, str]) -> list:
    """
    将分析数据和讲解词合并
    
    每个 step 对象会新增 "commentary" 字段
    """
    for step in steps_analysis:
        move_num = step["move_number"]
        step["commentary"] = step_commentary.get(move_num, "")
    return steps_analysis


def save_merged_data(merged_steps: list, output_path: Path):
    """保存合并后的数据到 JSON 文件"""
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(merged_steps, f, ensure_ascii=False, indent=2)
    print(f"✓ 合并数据已保存到: {output_path}")


def create_video_script(merged_steps: list, output_path: Path):
    """
    创建视频剧本（适合导入视频编辑软件）
    格式: 时间码 | 讲解词 | 走法 | 评分
    """
    lines = ["时间码\t讲解词\t走法\t评分变化"]
    
    for idx, step in enumerate(merged_steps, start=1):
        # 假设每一步讲解 3 秒
        minutes = (idx * 3) // 60
        seconds = (idx * 3) % 60
        timecode = f"00:{minutes:02d}:{seconds:02d}"
        
        move = step["move_san"]
        score_change = f"{step['score_diff']:+.1f}"
        commentary = step.get("commentary", "").replace("\n", " ")[:50]  # 限制长度
        
        lines.append(f"{timecode}\t{commentary}…\t{move}\t{score_change}")
    
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✓ 视频剧本已保存到: {output_path}")


def _generate_srt(step_commentary: dict, output_path: Path):
    """生成 SRT 字幕（按字数估算时长）"""
    lines = []
    current_time = 0.0
    idx = 1
    for step_num in sorted(step_commentary.keys()):
        text = step_commentary[step_num]
        # 清洗画面指令
        for tag in ['高亮', '威胁', '选中', '箭头', '小棋盘']:
            text = re.sub(rf'\[{tag}[：:\s]*[^\]]+\]', '', text)
        text = text.strip()
        if not text:
            continue
        dur = max(1.5, len(text) / 3.5)  # 中文 ~3.5字/秒
        start = current_time
        end = current_time + dur
        lines.append(str(idx))
        lines.append(f"{_srt_ts(start)} --> {_srt_ts(end)}")
        lines.append(text)
        lines.append("")
        current_time = end
        idx += 1
    with output_path.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✓ 字幕文件已生成: {output_path}")


def _srt_ts(sec: float) -> str:
    h, m = int(sec) // 3600, (int(sec) % 3600) // 60
    s, ms = int(sec) % 60, int((sec % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def main():
    script_dir = Path(__file__).parent
    commentary_file = script_dir / "commentary.txt"
    analysis_file = script_dir / "analysis_result.json"
    merged_file = script_dir / "merged_analysis_commentary.json"
    video_script_file = script_dir / "video_script.tsv"
    subtitle_file = script_dir / "commentary.srt"

    # 检查文件
    if not commentary_file.exists():
        print("❌ 错误: 找不到 commentary.txt")
        print("请先运行 generate_commentary.py 生成讲解词")
        return

    if not analysis_file.exists():
        print("❌ 错误: 找不到 analysis_result.json")
        print("请先运行 analyse.py 生成分析数据")
        return

    print("正在加载数据...")

    # 读取讲解词
    with commentary_file.open("r", encoding="utf-8") as f:
        commentary_text = f.read()

    # 解析讲解词
    print("正在解析讲解词...")
    step_commentary = parse_commentary(commentary_text)
    print(f"✓ 成功解析 {len(step_commentary)} 步讲解")

    # 加载分析数据
    print("正在加载分析数据...")
    steps_analysis = load_analysis_data(analysis_file)
    print(f"✓ 已加载 {len(steps_analysis)} 步分析")

    # 合并数据
    print("正在合并数据...")
    merged_steps = merge_data(steps_analysis, step_commentary)

    # 保存合并数据
    save_merged_data(merged_steps, merged_file)

    # 生成视频剧本
    print("正在生成视频剧本...")
    create_video_script(merged_steps, video_script_file)

    # 生成 SRT 字幕文件（不依赖 TTS）
    print("正在生成字幕文件...")
    try:
        _generate_srt(step_commentary, subtitle_file)
    except Exception as e:
        print(f"⚠ 字幕生成失败: {e}")

    # 显示摘要
    print("\n" + "="*60)
    print("解析完成！")
    print("="*60)
    print(f"\n生成的文件:")
    print(f"1. {merged_file.name}")
    print(f"   - 包含: 分析数据 + 讲解词")
    print(f"   - 用途: 后续视频制作 / 数据分析")
    print(f"\n2. {video_script_file.name}")
    print(f"   - 包含: 时间码 | 讲解词 | 走法 | 评分")
    print(f"   - 用途: 导入视频编辑软件（如 DaVinci Resolve）")
    print(f"\n3. {subtitle_file.name}")
    print(f"   - 包含: SRT 字幕（已去除画面指令）")
    print(f"   - 用途: 视频合成时嵌入字幕")

    # 显示示例
    print("\n" + "="*60)
    print("讲解词解析示例（前 5 步）:")
    print("="*60)
    for i in range(1, min(6, len(step_commentary) + 1)):
        text = step_commentary.get(i, "")[:100]
        print(f"[STEP {i}] {text}...")
    

if __name__ == "__main__":
    main()
