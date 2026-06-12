"""
Lichess 开局数据库完整抓取脚本 (Playwright 版)

两阶段抓取:
  阶段1: 从 lichess.org/opening 抓取所有开局名称和链接
  阶段2: 逐个访问开局详情页，抓取走法统计数据

用法:
  python fetch_opening_data.py                    # 全量抓取(自动发现所有开局)
  python fetch_opening_data.py --eco-only          # 仅用内置ECO表抓取(100+)
  python fetch_opening_data.py --visible           # 可见浏览器(调试)
  python fetch_opening_data.py --batch e4 e5 Nf3   # 单独抓一个
  python fetch_opening_data.py --wiki "Italian Game"
"""

import sys
import json
import time
import asyncio
import re
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("pip install playwright && playwright install chromium")
    sys.exit(1)

SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "opening_knowledge_fetched.json"


# ═══════════════════════════════════════════════════════════════
#  阶段1: 从 lichess.org/opening 发现所有开局
# ═══════════════════════════════════════════════════════════════

async def discover_openings_from_lichess(headless: bool = True) -> list[dict]:
    """
    打开 lichess.org/opening，抓取开局浏览器中列出的所有开局。
    Lichess 开局页面按类别展示热门开局（如 King's Pawn, Queen's Pawn 等）。
    每个类别下列出具体开局名称、ECO 代码和链接。
    """
    openings = []
    seen = set()

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        page.set_default_timeout(30000)

        try:
            print("打开 lichess.org/opening ...")
            await page.goto("https://lichess.org/opening", wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # 获取页面中的所有开局链接
            # Lichess 开局页面链接格式: /opening/Italian_Game
            links = await page.query_selector_all("a[href^='/opening/']")

            for link in links:
                try:
                    href = await link.get_attribute("href")
                    if not href or href == "/opening":
                        continue
                    # 跳过搜索/杂项链接
                    slug = href.replace("/opening/", "").strip()
                    if not slug or any(s in slug.lower() for s in
                                       ["search", "masters", "database", "api", "about", "lichess"]):
                        continue

                    text = (await link.text_content()).strip()
                    if not text or len(text) < 2:
                        continue

                    # 去重
                    if slug in seen:
                        continue
                    seen.add(slug)

                    openings.append({
                        "slug": slug,
                        "name": text,
                        "url": f"https://lichess.org{href}",
                    })

                except Exception:
                    continue

            print(f"  发现 {len(openings)} 个开局链接")

            # 如果发现太少，尝试点击分类展开
            if len(openings) < 30:
                print("  开局数量偏少，尝试展开分类...")
                # 点击可能的展开按钮
                expand_btns = await page.query_selector_all(
                    "button[class*='expand'], .opening-category__toggle, details summary"
                )
                for btn in expand_btns:
                    try:
                        await btn.click()
                        await page.wait_for_timeout(500)
                    except Exception:
                        pass

                # 重新抓取
                links = await page.query_selector_all("a[href^='/opening/']")
                for link in links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or href == "/opening":
                            continue
                        slug = href.replace("/opening/", "").strip()
                        if not slug or slug in seen:
                            continue
                        text = (await link.text_content()).strip()
                        if not text or len(text) < 2:
                            continue
                        seen.add(slug)
                        openings.append({
                            "slug": slug,
                            "name": text,
                            "url": f"https://lichess.org{href}",
                        })
                    except Exception:
                        continue
                print(f"  展开后共发现 {len(openings)} 个开局")

        except Exception as e:
            print(f"  ✗ 发现阶段失败: {e}")
        finally:
            await browser.close()

    return openings


# ═══════════════════════════════════════════════════════════════
#  阶段2: 抓取单个开局详情页
# ═══════════════════════════════════════════════════════════════

async def scrape_opening_detail(slug: str, headless: bool = True) -> dict:
    """
    打开 lichess.org/opening/<slug> 详情页，抓取:
    - 开局名称 (从页面 h1 或 title，过滤掉泛化的 "Chess Opening")
    - ECO 代码
    - 走法树 (PGN moves)
    - 走法统计表
    """
    url = f"https://lichess.org/opening/{slug}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        page.set_default_timeout(25000)

        result = {
            "name": "",
            "eco_code": "",
            "moves_sequence": [],
            "fen_signature": "",
            "top_moves": [],
            "stats": {},
            "typical_plans": {"white": ["(需手工补充)"], "black": ["(需手工补充)"]},
            "common_traps": [],
            "famous_practitioners": [],
        }

        try:
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(3000)

            # === 提取开局名称 ===
            # 优先级: opening__title 类 > page title > h1(但排除泛化文本)
            name = ""
            try:
                title_el = await page.query_selector(
                    ".opening__title, .opening-title, [data-title]"
                )
                if title_el:
                    name = (await title_el.text_content()).strip()

                # fallback: page <title>
                if not name:
                    page_title = await page.title()
                    # 过滤掉 "Chess Opening" 泛化标题
                    if page_title and "lichess" not in page_title.lower():
                        name = page_title.replace("• lichess.org", "").strip()
            except Exception:
                pass

            # === 过滤无效名称 ===
            bad_names = [
                "chess opening", "chess openings", "Opening", "opening",
                "Chess Opening Explorer", "lichess.org", "",
            ]
            if name.lower() in bad_names or name.lower().startswith("lichess"):
                name = ""
                # 最后一次尝试: 从 URL slug 推断
                from_slug = slug.replace("_", " ").title()
                if from_slug.lower() not in bad_names:
                    name = from_slug

            if name and name.lower() != "chess opening":
                result["name"] = name

            # === 提取 ECO ===
            try:
                eco_el = await page.query_selector(
                    ".opening__eco, [data-eco], .eco-code, .opening-eco"
                )
                if eco_el:
                    eco = (await eco_el.text_content()).strip()
                    eco_match = re.search(r'[A-E]\d{2}', eco)
                    if eco_match:
                        result["eco_code"] = eco_match.group()
            except Exception:
                pass

            # 从名称中提取 ECO
            if not result["eco_code"]:
                eco_match = re.search(r'\(([A-E]\d{2})\)', name)
                if eco_match:
                    result["eco_code"] = eco_match.group(1)

            # === 提取走法序列 (PGN) ===
            try:
                move_elements = await page.query_selector_all(
                    ".opening__moves .move, .opening-moves a, [data-ply]"
                )
                moves = []
                for el in move_elements:
                    t = (await el.text_content()).strip()
                    if t and re.match(r'^[a-hKNQRBO0-]+', t):
                        moves.append(t)
                if moves:
                    result["moves_sequence"] = moves
            except Exception:
                pass

            # === 提取走法统计表 ===
            try:
                table_rows = await page.query_selector_all(
                    "table.explorer__moves tbody tr, .moves-table tr, [class*='explorer'] tr"
                )
                for row in table_rows:
                    cells = await row.query_selector_all("td, th")
                    texts = []
                    for cell in cells:
                        t = (await cell.text_content()).strip()
                        if t:
                            texts.append(t)
                    if len(texts) >= 3 and re.match(r'^[a-hKNQRBO0-]', texts[0]):
                        result["top_moves"].append({
                            "san": texts[0],
                            "count": _parse_int(texts[1]) if len(texts) > 1 else 0,
                            "pct": _parse_float(texts[2]) if len(texts) > 2 else 0,
                        })
            except Exception:
                pass

            # === 提取总统计 ===
            try:
                total_el = await page.query_selector(
                    ".explorer__total, [class*='total-games'], [class*='game-count']"
                )
                if total_el:
                    total_text = (await total_el.text_content()).strip()
                    result["stats"]["total_games"] = _parse_int(total_text)
            except Exception:
                pass

        except Exception as e:
            print(f"    ✗ 抓取失败: {e}")
        finally:
            await browser.close()

    return result


# ═══════════════════════════════════════════════════════════════
#  方案B: 用内置ECO表抓取 (更可靠, 覆盖100+开局)
# ═══════════════════════════════════════════════════════════════

# 从项目已有的 eco_table.json + opening_knowledge.json 中提取所有 ECO
def get_eco_from_local_files() -> list[dict]:
    """从本地 JSON 文件提取所有已知开局的 ECO 和走法序列"""
    import chess

    entries = []

    # 1. 从 eco_table.json
    eco_path = SCRIPT_DIR / "eco_table.json"
    if eco_path.exists():
        with eco_path.open("r", encoding="utf-8") as f:
            eco_table = json.load(f)
        for eco_code, name_zh, fen_pattern in eco_table:
            # 用 FEN pattern 推演出一个代表性走法序列
            board = chess.Board()
            try:
                # 尝试从 FEN 推导出 approximate 走法——这里用 FEN pattern 作为 signature
                entries.append({
                    "eco_code": eco_code,
                    "name": name_zh,
                    "fen_pattern": fen_pattern,
                    "moves_sequence": [],  # 将被 scrape_by_fen 填充
                })
            except Exception:
                pass

    # 2. 从 opening_knowledge.json 提取已有的
    kb_path = SCRIPT_DIR / "opening_knowledge.json"
    if kb_path.exists():
        with kb_path.open("r", encoding="utf-8") as f:
            kb_entries = json.load(f)
        for ke in kb_entries:
            eco = ke.get("eco_code", "")
            if eco and eco not in {e["eco_code"] for e in entries}:
                entries.append({
                    "eco_code": eco,
                    "name": ke.get("name", ""),
                    "fen_pattern": ke.get("fen_signature", ""),
                    "moves_sequence": ke.get("moves_sequence", []),
                })

    # 3. 根据走法序列构建 FEN 再抓取
    import chess
    for entry in entries:
        if entry["moves_sequence"]:
            board = chess.Board()
            for san in entry["moves_sequence"]:
                try:
                    board.push_san(san)
                except ValueError:
                    break
            entry["fen"] = board.fen()
        else:
            entry["fen"] = ""

    return entries


async def scrape_by_fen(fen: str, headless: bool = True) -> dict:
    """用 FEN URL 参数抓取开局页面（无需 slug）"""
    import urllib.parse

    fen_encoded = urllib.parse.quote(fen, safe="")
    url = f"https://lichess.org/opening?fen={fen_encoded}"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        page = await browser.new_page()
        page.set_default_timeout(20000)

        result = {
            "name": "", "eco_code": "", "top_moves": [], "stats": {},
            "typical_plans": {"white": ["(需手工补充)"], "black": ["(需手工补充)"]},
            "common_traps": [], "famous_practitioners": [],
        }

        try:
            await page.goto(url, wait_until="networkidle")
            await page.wait_for_timeout(2500)

            # 开局名称 — 找具体的 span/div，不要 h1
            try:
                name_selectors = [
                    "span.opening__name",
                    ".opening-box__title span",
                    "[data-opening]",
                ]
                name = ""
                for sel in name_selectors:
                    el = await page.query_selector(sel)
                    if el:
                        name = (await el.text_content()).strip()
                        break

                # fallback: 从 <title>
                if not name:
                    page_title = await page.title()
                    # 通常格式: "Italian Game - Chess Openings - lichess.org"
                    if " - " in page_title:
                        name = page_title.split(" - ")[0].strip()
                    elif "•" in page_title:
                        name = page_title.split("•")[0].strip()

                # 再次过滤无效名称
                bad = {"chess opening", "chess openings", "lichess.org", ""}
                if name and name.lower().strip("- ") not in bad:
                    result["name"] = name
                else:
                    # 从页面提取最具体的信息
                    h1 = await page.query_selector("h1")
                    if h1:
                        h1_text = (await h1.text_content()).strip()
                        # 只取冒号前或括号前的内容
                        h1_text = re.sub(r'\([^)]*chess[^)]*\)', '', h1_text, flags=re.I)
                        h1_text = re.sub(r'\s*[-–—].*$', '', h1_text).strip()
                        if h1_text.lower() not in bad and len(h1_text) > 2:
                            result["name"] = h1_text
            except Exception:
                pass

            # 统计表
            try:
                rows = await page.query_selector_all(
                    "table tbody tr, .explorer__moves tr, [class*='moves'] tr"
                )
                for row in rows:
                    cells = await row.query_selector_all("td, th, span")
                    texts = [((await c.text_content()).strip()) for c in cells if (await c.text_content()).strip()]
                    # 过滤: 第一列是合法走法
                    if texts and re.match(r'^[a-hKNQRBO0-]', texts[0]):
                        result["top_moves"].append({
                            "san": texts[0],
                            "count": _parse_int(texts[1]) if len(texts) > 1 else 0,
                            "pct": _parse_float(texts[2]) if len(texts) > 2 else 0,
                        })
            except Exception:
                pass

            if result["top_moves"]:
                result["stats"]["total_games"] = sum(
                    m.get("count", 0) for m in result["top_moves"]
                )

        except Exception as e:
            pass
        finally:
            await browser.close()

    return result


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _parse_int(s: str) -> int:
    if not s:
        return 0
    cleaned = re.sub(r"[^\d]", "", s)
    return int(cleaned) if cleaned else 0


def _parse_float(s: str) -> float:
    if not s:
        return 0.0
    cleaned = re.sub(r"[^\d.]", "", s)
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ═══════════════════════════════════════════════════════════════
#  主流程
# ═══════════════════════════════════════════════════════════════

async def main_discover_and_scrape(headless: bool = True):
    """方案A: 发现 + 详情抓取"""
    print("=" * 60)
    print("阶段1: 从 lichess.org/opening 发现所有开局")
    print("=" * 60)
    discovered = await discover_openings_from_lichess(headless=headless)

    if not discovered:
        print("⚠ 未发现开局，切换到内置 ECO 表方案")
        return await main_scrape_by_eco(headless)

    print(f"\n发现 {len(discovered)} 个开局，开始抓取详情...\n")

    results = []
    for i, op in enumerate(discovered):
        print(f"[{i+1}/{len(discovered)}] {op['name'][:50]} ({op['slug']})")
        detail = await scrape_opening_detail(op["slug"], headless=headless)

        merged = {
            "name": detail.get("name") or op.get("name", ""),
            "eco_code": detail.get("eco_code", ""),
            "moves_sequence": detail.get("moves_sequence", []),
            "fen_signature": detail.get("fen_signature", ""),
            "top_moves": detail.get("top_moves", []),
            "stats": detail.get("stats", {}),
            "typical_plans": detail.get("typical_plans", {"white": ["(需手工补充)"], "black": ["(需手工补充)"]}),
            "common_traps": [],
            "famous_practitioners": [],
        }
        results.append(merged)

        if i < len(discovered) - 1:
            time.sleep(0.5)

    return results


async def main_scrape_by_eco(headless: bool = True):
    """方案B: 用内置 ECO 表抓取"""
    print("=" * 60)
    print("方案B: 用内置 ECO 表抓取 (100+ 开局)")
    print("=" * 60)

    entries = get_eco_from_local_files()
    print(f"从本地 JSON 提取到 {len(entries)} 个开局")

    # 过滤掉没有 FEN 的
    valid = [e for e in entries if e.get("fen")]
    print(f"其中 {len(valid)} 个有可用的 FEN signature\n")

    results = []
    for i, entry in enumerate(valid):
        name = entry.get("name", "?")
        eco = entry.get("eco_code", "?")
        fen = entry["fen"]
        print(f"[{i+1}/{len(valid)}] {eco} — {name[:40]}")

        detail = await scrape_by_fen(fen, headless=headless)

        merged = {
            "name": detail.get("name") or name,
            "eco_code": detail.get("eco_code") or eco,
            "moves_sequence": entry.get("moves_sequence", []),
            "fen_signature": fen,
            "top_moves": detail.get("top_moves", []),
            "stats": detail.get("stats", {}),
            "typical_plans": {"white": ["(需手工补充)"], "black": ["(需手工补充)"]},
            "common_traps": [],
            "famous_practitioners": [],
        }
        results.append(merged)

        if i < len(valid) - 1:
            time.sleep(0.5)

    return results


# ═══════════════════════════════════════════════════════════════
#  Wikipedia
# ═══════════════════════════════════════════════════════════════

def fetch_wikipedia_summary(title: str) -> str:
    import urllib.request
    import urllib.parse
    api_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(title.replace(' ', '_'))}"
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": "agentchess/2.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
        extract = data.get("extract", "")
        if extract:
            print(f"  ✓ Wikipedia: {len(extract)} 字符")
            return extract
    except Exception as e:
        print(f"  ⚠ Wikipedia: {e}")
    return ""


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Lichess 开局数据完整抓取")
    parser.add_argument("--eco-only", action="store_true",
                        help="仅用内置 ECO 表抓取(快,100+开局)")
    parser.add_argument("--discover", action="store_true",
                        help="从 lichess 自动发现 + 抓取(可能50-200个)")
    parser.add_argument("--visible", action="store_true",
                        help="可见浏览器")
    parser.add_argument("--output", type=str, default="opening_knowledge_fetched.json")
    parser.add_argument("--wiki", type=str, help="Wikipedia 摘要")
    args = parser.parse_args()

    headless = not args.visible

    if args.wiki:
        print(fetch_wikipedia_summary(args.wiki))
        return

    # 默认: eco-only + discover 都做
    results = []

    if args.eco_only or (not args.discover):
        print("\n" + "=" * 60)
        print("🚀 阶段A: 内置 ECO 表抓取")
        print("=" * 60)
        eco_results = asyncio.run(main_scrape_by_eco(headless))
        results.extend(eco_results)

    if args.discover or (not args.eco_only):
        print("\n" + "=" * 60)
        print("🚀 阶段B: lichess 自动发现")
        print("=" * 60)
        discover_results = asyncio.run(main_discover_and_scrape(headless))

        # 合并去重 (按 name 去重)
        existing_names = {r["name"] for r in results}
        for dr in discover_results:
            if dr["name"] not in existing_names:
                results.append(dr)
                existing_names.add(dr["name"])

    # 过滤无效名称
    bad_name_starts = {"chess opening", "lichess"}
    results = [
        r for r in results
        if r.get("name", "").lower().strip() not in {"", "chess opening", "lichess.org"}
        and not any(r.get("name", "").lower().startswith(b) for b in bad_name_starts)
    ]

    # 保存
    output_path = SCRIPT_DIR / args.output
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"✓ 完成! 共抓取 {len(results)} 个开局")
    print(f"  输出: {output_path}")
    print(f"\n运行 python merge_openings.py 将结果合并到 opening_knowledge.json")


if __name__ == "__main__":
    main()