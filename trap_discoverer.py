"""
开局陷阱自动发现模块 (Trap Discoverer)
从实战分析中自动检测"冷门但致命"的走法，标记为候选陷阱。

判定标准:
  1. 走法发生在开局阶段（第3~12步）
  2. 评分波动 ≥ 2.0（失误/漏杀级别）
  3. 大师库中出现频率 ≤ 5 次（冷门走法）
  4. 不在已知开局知识库的 common_traps 中

输出:
  discovered_traps.json — 待人工审核的候选陷阱列表

用法:
  python trap_discoverer.py                    # 从 analysis_result.json 提取
  python trap_discoverer.py --review           # 交互式审核
  python trap_discoverer.py --accept 3         # 接受第3条并合并到知识库
"""

import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
DISCOVERED_FILE = SCRIPT_DIR / "discovered_traps.json"


# ═══════════════════════════════════════════════════════════════
#  陷阱发现
# ═══════════════════════════════════════════════════════════════

def discover_traps_from_analysis(analysis_file: Path = None) -> list[dict]:
    """
    从 analysis_result.json 中自动检测候选陷阱。

    Returns:
        [{name, eco_code, trigger_moves, description, refutation, score_diff,
          move_number, move_san, source_game_id, status}, ...]
    """
    if analysis_file is None:
        analysis_file = SCRIPT_DIR / "analysis_result.json"
    if not analysis_file.exists():
        print(f"✗ 分析文件不存在: {analysis_file}")
        return []

    with analysis_file.open("r", encoding="utf-8") as f:
        data = json.load(f)

    steps = data.get("steps", data)
    opening_profile = data.get("opening_profile", {})
    opening_eco = opening_profile.get("eco", "?")
    opening_name = opening_profile.get("opening_name", "?")

    # 加载已知陷阱
    known_traps = _load_known_traps(opening_eco)

    candidates = []

    for step in steps:
        move_num = step.get("move_number", 0)
        move_san = step.get("move_san", "")

        # 条件1: 开局阶段 (3~12)
        if not (3 <= move_num <= 12):
            continue

        # 条件2: 评分波动 ≥ 2.0
        score_diff = abs(step.get("score_diff", 0))
        if score_diff < 2.0:
            continue

        # 条件3: 大师库频率
        masters = step.get("masters", {}) or {}
        total_masters = masters.get("total_games", 0)
        if total_masters > 5:
            continue  # 常见走法，不是陷阱

        # 条件4: 不在已知陷阱中
        if _is_known_trap(move_san, known_traps):
            continue

        # 构建触发序列（前几步 + 当前步）
        prev_moves = []
        for s in steps:
            if s["move_number"] < move_num and s["move_number"] >= max(1, move_num - 4):
                prev_moves.append(s["move_san"])
        trigger_moves = prev_moves + [move_san]

        # 推荐走法
        refutation = []
        recommended = step.get("recommended", {})
        if recommended:
            refutation.append(recommended.get("move", ""))

        candidates.append({
            "name": f"自动发现陷阱_{opening_eco}_{move_num}",
            "eco_code": opening_eco,
            "opening_name": opening_name,
            "move_number": move_num,
            "move_san": move_san,
            "trigger_moves": trigger_moves[-5:],  # 最多5步
            "description": (
                f"{step.get('side','一方')}走了{move_san}，导致评分从"
                f"{step.get('score_before',0):.1f}骤降至{step.get('score_after',0):.1f}"
                f"（变化{score_diff:+.1f}）。大师对局中此走法仅出现{total_masters}次。"
                f"推荐走{refutation[0] if refutation else '其他'}。"
            ),
            "refutation": refutation,
            "score_diff": score_diff,
            "status": "pending",  # pending / accepted / rejected
            "quality": step.get("quality", ""),
        })

    print(f"发现 {len(candidates)} 个候选陷阱")
    return candidates


def _load_known_traps(eco_code: str) -> list:
    """从 opening_knowledge.json 加载指定 ECO 的已知陷阱"""
    kb_path = SCRIPT_DIR / "opening_knowledge.json"
    if not kb_path.exists():
        return []

    try:
        with kb_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)
        for entry in entries:
            if entry.get("eco_code") == eco_code:
                traps = entry.get("common_traps", [])
                return [t.get("name", "") for t in traps] + [
                    m for t in traps for m in t.get("trigger_moves", [])
                ]
    except Exception:
        pass
    return []


def _is_known_trap(move_san: str, known: list) -> bool:
    """检查这个走法是否已存在于已知陷阱中"""
    return move_san in known


# ═══════════════════════════════════════════════════════════════
#  保存与审核
# ═══════════════════════════════════════════════════════════════

def save_discovered_traps(traps: list, output_file: Path = None):
    """保存候选陷阱到 JSON 文件"""
    if output_file is None:
        output_file = DISCOVERED_FILE

    # 合并已有记录（去重）
    existing = []
    if output_file.exists():
        try:
            with output_file.open("r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            pass

    # 按 trigger_moves 去重
    seen = {tuple(t.get("trigger_moves", [])) for t in existing}
    new_count = 0
    for trap in traps:
        key = tuple(trap.get("trigger_moves", []))
        if key not in seen:
            existing.append(trap)
            seen.add(key)
            new_count += 1

    with output_file.open("w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"  新增 {new_count} 条，总共 {len(existing)} 条候选陷阱 → {output_file}")


def review_traps():
    """交互式审核候选陷阱"""
    if not DISCOVERED_FILE.exists():
        print("没有待审核的陷阱")
        return

    with DISCOVERED_FILE.open("r", encoding="utf-8") as f:
        traps = json.load(f)

    pending = [t for t in traps if t.get("status") == "pending"]
    print(f"共 {len(pending)} 条待审核陷阱\n")

    for i, trap in enumerate(pending):
        print(f"[{i+1}] {trap['name']}")
        print(f"    ECO: {trap.get('eco_code','?')}  第{trap['move_number']}步 {trap['move_san']}")
        print(f"    触发序列: {' → '.join(trap.get('trigger_moves',[]))}")
        print(f"    描述: {trap.get('description','')}")
        print(f"    应着: {', '.join(trap.get('refutation',[]))}")
        print()


def accept_trap(index: int):
    """接受指定陷阱并合并到 opening_knowledge.json"""
    if not DISCOVERED_FILE.exists():
        print("没有候选陷阱")
        return

    with DISCOVERED_FILE.open("r", encoding="utf-8") as f:
        traps = json.load(f)

    pending = [t for t in traps if t.get("status") == "pending"]
    if index < 1 or index > len(pending):
        print(f"无效序号: {index} (共 {len(pending)} 条)")
        return

    trap = pending[index - 1]
    trap["status"] = "accepted"

    # 合并到知识库
    kb_path = SCRIPT_DIR / "opening_knowledge.json"
    if kb_path.exists():
        with kb_path.open("r", encoding="utf-8") as f:
            kb = json.load(f)

        eco = trap.get("eco_code", "")
        for entry in kb:
            if entry.get("eco_code") == eco:
                entry.setdefault("common_traps", [])
                entry["common_traps"].append({
                    "name": trap["name"],
                    "trigger_moves": trap["trigger_moves"],
                    "description": trap["description"],
                    "refutation": trap["refutation"],
                })
                break

        with kb_path.open("w", encoding="utf-8") as f:
            json.dump(kb, f, ensure_ascii=False, indent=2)
        print(f"✓ 已合并到 opening_knowledge.json → {eco}")

    # 更新 discovered_traps.json
    for t in traps:
        if t == trap:
            t["status"] = "accepted"
    with DISCOVERED_FILE.open("w", encoding="utf-8") as f:
        json.dump(traps, f, ensure_ascii=False, indent=2)


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="开局陷阱自动发现")
    parser.add_argument("--discover", action="store_true",
                        help="从 analysis_result.json 发现陷阱")
    parser.add_argument("--review", action="store_true",
                        help="审核候选陷阱")
    parser.add_argument("--accept", type=int, help="接受第N条陷阱")
    parser.add_argument("--analysis", type=str, help="指定分析文件路径")
    args = parser.parse_args()

    analysis_file = Path(args.analysis) if args.analysis else None

    if args.discover or (not args.review and args.accept is None):
        traps = discover_traps_from_analysis(analysis_file)
        save_discovered_traps(traps)
    elif args.review:
        review_traps()
    elif args.accept:
        accept_trap(args.accept)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()