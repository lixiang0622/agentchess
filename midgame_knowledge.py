"""
中局知识库模块 (Midgame Knowledge)
根据局面特征标签自动匹配棋理原则，注入 LLM 提示词。

标签来源:
  - concept_extractor.py 的策略概念标签
  - strategic_mistake_detector.py 的局面错误类型
  - tactical_detector.py 的战术主题

用法:
    from midgame_knowledge import MidgameKnowledge
    mk = MidgameKnowledge()
    principles = mk.match(["ISOLATED_PAWN", "BISHOP_PAIR", "KING_IN_CENTER"])
    prompt_text = mk.build_prompt_context(principles)
"""

import sys
import json
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

PRINCIPLES_FILE = Path(__file__).parent / "midgame_principles.json"

# ─── 标签到分类的映射 ───
TAG_TO_CATEGORY = {
    # 兵型相关
    "ISOLATED_PAWN": "pawn_structure",
    "DOUBLED_PAWNS": "pawn_structure",
    "BACKWARD_PAWN": "pawn_structure",
    "PASSED_PAWN": "pawn_structure",
    "PAWN_STORM": "pawn_structure",
    "PAWN_ISLAND": "pawn_structure",
    # 中心控制
    "CENTER_CONTROL": "center_control",
    "CENTER_BREAK": "center_control",
    "SIDE_CONTROL": "center_control",
    # 子力运用
    "KNIGHT_OUTPOST": "piece_play",
    "GOOD_BISHOP_BAD_BISHOP": "piece_play",
    "BISHOP_PAIR": "piece_play",
    "FIANCHETTO": "piece_play",
    "ROOK_SEVENTH_RANK": "piece_play",
    "QUEEN_EARLY": "piece_play",
    "ROOKS_CONNECTED": "piece_play",
    "BISHOP_PAIR_LOSS": "piece_play",
    "BAD_BISHOP_FOR_KNIGHT": "piece_play",
    # 王安全
    "KING_SAFETY": "king_safety",
    "KING_IN_CENTER": "king_safety",
    "OPPOSITE_CASTLING": "king_safety",
    "KING_SHIELD": "king_safety",
    "KING_SHIELD_DAMAGE": "king_safety",
    "SACRIFICE_ATTACK": "king_safety",
    "LUFT": "king_safety",
    # 兑换策略
    "EXCHANGE": "exchange",
    "SIMPLIFICATION": "exchange",
    "GOOD_EXCHANGE": "exchange",
    "AVOID_EXCHANGE": "exchange",
    "QUEEN_EXCHANGE": "exchange",
    # 计划与战略
    "PLAN": "plan_and_strategy",
    "SPACE_ADVANTAGE": "plan_and_strategy",
    "TWO_WEAKNESSES": "plan_and_strategy",
    "INITIATIVE": "plan_and_strategy",
    "CENTER_ABANDONMENT": "plan_and_strategy",
    "DEVELOPMENT_LAG": "plan_and_strategy",
    "OPEN_FILE_CONTROL": "plan_and_strategy",
    "OPEN_FILE_LOSS": "plan_and_strategy",
}

# ─── 概念标签到中局知识的自动映射 ───
CONCEPT_TO_TAG = {
    "击双/捉双": ["PIECE_PLAY"],
    "牵制": ["PIECE_PLAY"],
    "串击/透视": ["PIECE_PLAY"],
    "闪击": ["PIECE_PLAY"],
    "弃子": ["SACRIFICE_ATTACK", "KING_SAFETY"],
    "底线弱点": ["KING_SAFETY", "LUFT"],
    "开放线控制": ["OPEN_FILE_CONTROL"],
    "兵型弱点": ["PAWN_STRUCTURE"],
    "象的好坏": ["GOOD_BISHOP_BAD_BISHOP"],
    "马的前哨据点": ["KNIGHT_OUTPOST"],
    "王的安全": ["KING_SAFETY"],
    "空间优势": ["SPACE_ADVANTAGE"],
    "出子领先": ["DEVELOPMENT"],
    "主动权": ["INITIATIVE"],
    "中心控制": ["CENTER_CONTROL"],
    "双象优势": ["BISHOP_PAIR"],
    "叠兵/孤兵": ["PAWN_STRUCTURE"],
    "通路兵": ["PASSED_PAWN"],
    "兵风暴": ["PAWN_STORM"],
    "弱格": ["PLAN"],
}


class MidgameKnowledge:
    """中局知识库 — 加载 + 标签匹配 + 提示词生成"""

    def __init__(self, principles_path: Path = None):
        self.principles_path = principles_path or PRINCIPLES_FILE
        self.entries: list = []
        self._load()

    def _load(self):
        if not self.principles_path.exists():
            print(f"  ⚠ 中局知识库文件不存在: {self.principles_path}")
            return
        try:
            with self.principles_path.open("r", encoding="utf-8") as f:
                self.entries = json.load(f)
            print(f"  ✓ 中局知识库已加载: {len(self.entries)} 个分类")
        except Exception as e:
            print(f"  ⚠ 中局知识库加载失败: {e}")

    def match(self, tags: list[str]) -> list[dict]:
        """
        根据标签列表匹配相关知识条目。

        Args:
            tags: 标签列表，如 ["ISOLATED_PAWN", "BISHOP_PAIR", "KNIGHT_OUTPOST"]

        Returns:
            匹配到的条目列表
        """
        if not self.entries or not tags:
            return []

        # 将标签映射到分类
        categories = set()
        for tag in tags:
            cat = TAG_TO_CATEGORY.get(tag.upper(), "")
            if cat:
                categories.add(cat)

        # 如果没有精确匹配，尝试模糊匹配
        if not categories:
            for tag in tags:
                tag_upper = tag.upper()
                for key, cat in TAG_TO_CATEGORY.items():
                    if key in tag_upper or tag_upper in key:
                        categories.add(cat)

        # 从库中提取对应条目
        result = []
        for entry in self.entries:
            if entry["category"] in categories:
                result.append(entry)

        return result

    def match_from_step(self, step: dict) -> list[dict]:
        """
        从 step 数据中自动提取标签并匹配知识。
        会检查 concept_hint, strategic_mistakes, tactical_themes 等字段。
        """
        tags = set()

        # 1) 从 concept_hint 提取
        hint = step.get("concept_hint", "")
        if hint:
            for concept, tag_list in CONCEPT_TO_TAG.items():
                if concept in hint:
                    tags.update(tag_list)

        # 2) 从 strategic_mistakes 提取
        sms = step.get("strategic_mistakes", [])
        for sm in sms:
            sm_type = sm.get("type", "")
            tag = TAG_TO_CATEGORY.get(sm_type.upper(), "")
            if tag:
                tags.add(tag)
            # 特殊映射
            sm_tag_map = {
                "bad_bishop_for_knight": "BAD_BISHOP_FOR_KNIGHT",
                "pawn_structure_damage": "PAWN_STRUCTURE",
                "center_abandonment": "CENTER_ABANDONMENT",
                "bishop_pair_loss": "BISHOP_PAIR_LOSS",
                "king_shield_damage": "KING_SHIELD_DAMAGE",
                "open_file_loss": "OPEN_FILE_LOSS",
                "development_lag": "DEVELOPMENT_LAG",
            }
            mapped = sm_tag_map.get(sm_type, "")
            if mapped:
                tags.add(mapped)

        # 3) 从 tactical_themes 提取
        themes = step.get("tactical_themes", [])
        theme_tag_map = {
            "fork": "PIECE_PLAY",
            "pin": "PIECE_PLAY",
            "skewer": "PIECE_PLAY",
            "discovered_attack": "PIECE_PLAY",
            "deflection": "PIECE_PLAY",
            "zwischenzug": "PIECE_PLAY",
            "mate_threat": "KING_SAFETY",
        }
        for t in themes:
            tt = t.get("type", "")
            mapped = theme_tag_map.get(tt, "")
            if mapped:
                tags.add(mapped)

        # 4) 从 phase 提取
        phase = step.get("phase", {})
        if phase.get("macro_phase") == "中局":
            tags.add("PLAN")  # 中局通常都需要战略规划

        # 5) 从 expression 的 changes 提取
        explanation = step.get("explanation", {})
        changes = explanation.get("changes", [])
        change_cat_map = {
            "王安全": "KING_SAFETY",
            "兵形": "PAWN_STRUCTURE",
            "子力配置": "PIECE_PLAY",
            "中心": "CENTER_CONTROL",
            "出子": "DEVELOPMENT_LAG",
            "机动性": "PIECE_PLAY",
            "线路控制": "OPEN_FILE_CONTROL",
        }
        for c in changes:
            cat = c.get("category", "")
            mapped = change_cat_map.get(cat, "")
            if mapped:
                tags.add(mapped)

        return self.match(list(tags))

    def build_prompt_context(self, matched: list[dict], max_principles: int = 5) -> str:
        """
        将匹配到的中局知识转换为提示词片段。

        Args:
            matched: match() 或 match_from_step() 返回的条目列表
            max_principles: 每步最多注入多少条原则
        """
        if not matched:
            return ""

        lines = []
        total = 0

        for entry in matched:
            name = entry.get("name", "")
            principles = entry.get("principles", [])

            for p in principles:
                if total >= max_principles:
                    break
                lines.append(p)
                total += 1

            if total >= max_principles:
                break

        if not lines:
            return ""

        return (
            "【中局棋理提示 — 请在讲解中自然引用相关原则来解释走法背后的棋理】\n"
            + "\n".join(lines)
        )


# ═══════════════════════════════════════════════════════════════
#  便捷函数
# ═══════════════════════════════════════════════════════════════

_mk_instance = None


def get_mk() -> MidgameKnowledge:
    global _mk_instance
    if _mk_instance is None:
        _mk_instance = MidgameKnowledge()
    return _mk_instance


# ═══════════════════════════════════════════════════════════════
#  自测
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("中局知识库 自测")
    print("=" * 60)

    mk = MidgameKnowledge()

    # 测试1: 简单标签匹配
    print("\n--- 测试1: 标签匹配 ---")
    result = mk.match(["ISOLATED_PAWN", "BISHOP_PAIR", "PAWN_STORM"])
    print(f"  匹配到 {len(result)} 个分类:")
    for r in result:
        print(f"    - {r['name']} ({len(r['principles'])} 条原则)")

    # 测试2: 从 step 数据自动提取
    print("\n--- 测试2: 从 step 自动提取 ---")
    mock_step = {
        "concept_hint": "白方有空间优势；白方双象优势",
        "strategic_mistakes": [{"type": "center_abandonment", "severity": "warning"}],
        "tactical_themes": [{"type": "fork"}, {"type": "pin"}],
        "phase": {"macro_phase": "中局"},
        "explanation": {
            "changes": [{"category": "王安全", "change_type": "恶化", "description": "王安全度下降"}]
        },
    }
    result2 = mk.match_from_step(mock_step)
    print(f"  从 step 提取到 {len(result2)} 个分类:")
    for r in result2:
        print(f"    - {r['name']}")

    # 测试3: 生成提示词
    print("\n--- 测试3: 生成提示词 ---")
    prompt = mk.build_prompt_context(result2, max_principles=3)
    print(prompt[:400])

    print(f"\n✅ 自测完成")