"""开局知识库合并工具"""
import json, sys
from pathlib import Path

def merge(batch_file: str):
    base = Path(__file__).parent
    kb_path = base / "opening_knowledge.json"

    with kb_path.open("r", encoding="utf-8") as f:
        kb = json.load(f)
    with open(batch_file, "r", encoding="utf-8") as f:
        batch = json.load(f)

    ecos = {e["eco_code"] for e in kb}
    added = 0
    for e in batch:
        if e["eco_code"] not in ecos:
            kb.append(e)
            ecos.add(e["eco_code"])
            added += 1

    with kb_path.open("w", encoding="utf-8") as f:
        json.dump(kb, f, ensure_ascii=False, indent=2)

    print(f"OK: {len(kb)} total (+{added})")
    for e in kb:
        print(f"  {e['eco_code']:6s} {e['name']}")

if __name__ == "__main__":
    merge(sys.argv[1] if len(sys.argv) > 1 else "opening_batch3.json")