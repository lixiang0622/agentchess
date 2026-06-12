"""
开局知识库加载与匹配模块
从 opening_knowledge.json 加载 10 个主流开局的结构化知识，
根据前 N 步走法序列匹配具体变例，提取典型计划、常见陷阱和著名棋手。

匹配逻辑: 由长到短回溯匹配，先从 10 步开始，若无则回溯到 8、6、4 步。

用法:
    from opening_knowledge import OpeningKnowledgeBase
    kb = OpeningKnowledgeBase()
    result = kb.match(moves_sequence)  # 返回匹配到的开局知识
    prompt_text = kb.build_prompt_context(result)  # 生成提示词注入文本
"""

import sys
import json
from pathlib import Path
from typing import Optional

sys.stdout.reconfigure(encoding="utf-8")

KNOWLEDGE_FILE = Path(__file__).parent / "opening_knowledge.json"


class OpeningKnowledgeBase:
    """开局知识库 — 加载 + 匹配 + 提示词生成"""

    def __init__(self, knowledge_path: Path = None):
        self.knowledge_path = knowledge_path or KNOWLEDGE_FILE
        self.entries: list = []
        self._loaded = False
        self._load()

    def _load(self):
        if not self.knowledge_path.exists():
            print(f"  ⚠ 开局知识库文件不存在: {self.knowledge_path}")
            self._loaded = True
            return
        try:
            with self.knowledge_path.open("r", encoding="utf-8") as f:
                self.entries = json.load(f)
            self._loaded = True
            print(f"  ✓ 开局知识库已加载: {len(self.entries)} 个变例")
        except Exception as e:
            print(f"  ⚠ 开局知识库加载失败: {e}")
            self._loaded = True

    def match(self, moves_sequence: list, max_moves: int = 12) -> Optional[dict]:
        """
        根据走法序列匹配开局变例。
        从 max_moves 步开始回溯，找到最长匹配。

        Args:
            moves_sequence: SAN 走法列表，如 ["e4", "c5", "Nf3", ...]
            max_moves: 最大匹配步数

        Returns:
            匹配到的条目 dict 或 None
        """
        if not self.entries or not moves_sequence:
            return None

        for depth in range(min(len(moves_sequence), max_moves), 2, -1):
            partial = moves_sequence[:depth]
            for entry in self.entries:
                entry_moves = entry.get("moves_sequence", [])
                if len(entry_moves) <= depth and entry_moves == partial[:len(entry_moves)]:
                    return dict(entry)  # 返回副本
                # 也尝试从开始匹配到 entry 的最后一步
                if len(partial) >= len(entry_moves):
                    if partial[:len(entry_moves)] == entry_moves:
                        return dict(entry)

        return None

    def match_by_fen(self, fen: str) -> Optional[dict]:
        """根据 FEN 签名匹配开局"""
        if not self.entries:
            return None
        # 取 FEN 棋盘部分（第一个空格之前）
        board_part = fen.split(" ")[0]
        for entry in self.entries:
            entry_fen = entry.get("fen_signature", "")
            entry_board = entry_fen.split(" ")[0] if entry_fen else ""
            if entry_board and entry_board in board_part:
                return dict(entry)
        return None

    def build_prompt_context(self, entry: Optional[dict]) -> str:
        """
        将匹配到的开局知识转换为可直接注入 LLM 提示词的文本。

        Args:
            entry: match() 返回的条目

        Returns:
            格式化的提示词片段字符串
        """
        if not entry:
            return ""

        parts = []
        name = entry.get("name", "")
        eco = entry.get("eco_code", "")

        parts.append(f"【开局深度知识】当前对局已识别为：{name} (ECO {eco})。")

        # 白方计划
        plans = entry.get("typical_plans", {})
        white_plans = plans.get("white", [])
        if white_plans:
            parts.append(f"\n白方主要计划：")
            for i, plan in enumerate(white_plans, 1):
                parts.append(f"  {i}. {plan}")

        # 黑方计划
        black_plans = plans.get("black", [])
        if black_plans:
            parts.append(f"\n黑方主要计划：")
            for i, plan in enumerate(black_plans, 1):
                parts.append(f"  {i}. {plan}")

        # 陷阱
        traps = entry.get("common_traps", [])
        if traps:
            parts.append(f"\n⚠️ 该变例的经典陷阱：")
            for trap in traps:
                parts.append(f"  • {trap.get('name', '陷阱')}: {trap.get('description', '')}")
                trigger = " → ".join(trap.get("trigger_moves", []))
                if trigger:
                    parts.append(f"    触发序列: {trigger}")
                refutation = " → ".join(trap.get("refutation", []))
                if refutation:
                    parts.append(f"    正确应对: {refutation}")

        # 著名棋手
        practitioners = entry.get("famous_practitioners", [])
        if practitioners:
            parts.append(f"\n历史上擅长此开局的棋手：{'、'.join(practitioners)}。")

        parts.append(
            "\n讲解要求：请结合上述开局知识来评判每一步是否'符合开局原则'。"
            "在开局阶段（前12步），适时向观众介绍该开局的核心思想和经典陷阱。"
            "当实战走法偏离上述典型计划时，指出偏差并说明可能的风险。"
        )

        return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════════

_kb_instance = None


def get_kb() -> OpeningKnowledgeBase:
    global _kb_instance
    if _kb_instance is None:
        _kb_instance = OpeningKnowledgeBase()
    return _kb_instance


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("开局知识库 自测")
    print("=" * 60)

    kb = OpeningKnowledgeBase()
    print(f"  加载条目数: {len(kb.entries)}")

    # 测试 1: 精确匹配西班牙开局
    print("\n--- 测试 1: 西班牙开局 ---")
    moves = ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "Ba4", "Nf6"]
    result = kb.match(moves)
    if result:
        print(f"  ✓ 匹配: {result['name']} ({result['eco_code']})")
        print(f"    白方计划: {result['typical_plans']['white'][0][:50]}...")
    else:
        print(f"  ✗ 未匹配")

    # 测试 2: 西西里纳道尔夫
    print("\n--- 测试 2: 西西里纳道尔夫 ---")
    moves2 = ["e4", "c5", "Nf3", "d6", "d4", "cxd4", "Nxd4", "Nf6", "Nc3", "a6"]
    result2 = kb.match(moves2)
    if result2:
        print(f"  ✓ 匹配: {result2['name']} ({result2['eco_code']})")
        print(f"    陷阱: {result2['common_traps'][0]['name']}")
    else:
        print(f"  ✗ 未匹配")

    # 测试 3: 后翼弃兵接受
    print("\n--- 测试 3: 后翼弃兵接受 ---")
    moves3 = ["d4", "d5", "c4", "dxc4", "e3", "e5"]
    result3 = kb.match(moves3)
    if result3:
        print(f"  ✓ 匹配: {result3['name']} ({result3['eco_code']})")
    else:
        print(f"  ✗ 未匹配")

    # 测试 4: 生成提示词
    print("\n--- 测试 4: 生成提示词 ---")
    if result2:
        prompt = kb.build_prompt_context(result2)
        print(prompt[:500])

    # 测试 5: FEN 匹配
    print("\n--- 测试 5: FEN 匹配 ---")
    fen = "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
    result5 = kb.match_by_fen(fen)
    if result5:
        print(f"  ✓ FEN 匹配: {result5['name']}")
    else:
        print(f"  ✗ FEN 未匹配")

    print(f"\n✅ 自测完成")