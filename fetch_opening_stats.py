"""
开局大师统计抓取器
从 Lichess Masters Database 获取各开局变例的胜率和
用法: python fetch_opening_stats.py
"""

import sys, json, time, urllib.request, urllib.parse
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent
STATS_FILE = SCRIPT_DIR / "opening_stats.json"

# 各 ECO 代码对应的关键 FEN（走完开局特征步后的局面）
ECO_FENS = {
    # ===== A 系列 =====
    "A00": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",  # 初始
    "A01": "rnbqkbnr/pppppppp/8/8/8/1P6/P1PPPPPP/RNBQKBNR b KQkq - 0 1",  # 尼姆佐维奇-拉尔森
    "A04": "rnbqkbnr/pppppppp/8/8/8/5N2/PPPPPPPP/RNBQKB1R b KQkq - 0 1",  # 列蒂
    "A10": "rnbqkbnr/pppppppp/8/8/2P5/8/PP1PPPPP/RNBQKBNR b KQkq - 0 1",  # 英国式
    "A13": "rnbqkbnr/pp1ppppp/8/2p5/2P5/8/PP1PPPPP/RNBQKBNR w KQkq - 0 1",  # 英国式对称
    "A15": "rnbqkbnr/pppppppp/8/8/2P5/5N2/PP1PPPPP/RNBQKB1R b KQkq - 0 1",  # 英国式-列蒂
    "A20": "rnbqkbnr/pp1ppppp/8/2p5/2P5/5N2/PP1PPPPP/RNBQKB1R b KQkq - 0 1",  # 英国式-西西里转置
    "A25": "rnbqkbnr/pp1ppppp/8/2p5/2P5/2N5/PP1PPPPP/R1BQKBNR b KQkq - 0 1",  # 英国式-封闭
    "A28": "rnbqkbnr/pp1ppppp/8/2p5/2P5/P4N2/1P1PPPPP/RNBQKB1R b KQkq - 0 1",  # 英国式-四马
    "A30": "rnbqkb1r/pppppppp/5n2/8/2P5/5N2/PP1PPPPP/RNBQKB1R b KQkq - 0 1",  # 英国式-对称
    "A34": "rnbqkb1r/pppppppp/5n2/8/2P5/2N5/PP1PPPPP/R1BQKBNR b KQkq - 0 1",  # 英国式-对称主线
    "A40": "rnbqkb1r/pppppppp/5n2/8/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 1",  # 后翼印度侧翼
    "A45": "rnbqkb1r/pppppppp/5n2/6B1/3P4/8/PPP1PPPP/RN1QKBNR b KQkq - 0 1",  # 特龙普斯基
    "A46": "rnbqkb1r/pppppppp/5n2/8/3P4/5N2/PPP1PPPP/RNBQKB1R b KQkq - 0 1",  # 伦敦体系起点
    "A48": "rnbqkb1r/pppppppp/5n2/6B1/3P4/5N2/PPP1PPPP/RN1QKB1R b KQkq - 0 1",  # 伦敦体系
    "A50": "rnbqkb1r/pppppppp/5n2/8/3P4/2P5/PP2PPPP/RNBQKBNR b KQkq - 0 1",  # 印度防御
    "A53": "rnbqkb1r/pppppp1p/5np1/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 古印度防御
    "A56": "rnbqkb1r/pp1ppppp/5n2/2p5/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 贝诺尼防御
    "A60": "rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 现代贝诺尼
    "A70": "rnbqkb1r/pp1p1ppp/4pn2/2pP4/2P5/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 1",  # 现代贝诺尼主线
    "A80": "rnbqkbnr/ppppp1pp/8/5p2/3P4/8/PPP1PPPP/RNBQKBNR w KQkq - 0 1",  # 荷兰防御
    "A85": "rnbqkb1r/ppppp1pp/5n2/5p2/3P4/5N2/PPP1PPPP/RNBQKB1R w KQkq - 0 1",  # 荷兰-列宁格勒
    "A90": "rnbqkb1r/ppppp2p/5np1/5p2/2PP4/5N2/PP2PPPP/RNBQKB1R w KQkq - 0 1",  # 荷兰-列宁格勒主线

    # ===== B 系列 (半开放性开局) =====
    "B00": "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",  # 王前兵
    "B01": "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1",  # 斯堪的纳维亚
    "B06": "rnbqkbnr/pp1pp1pp/2p2p2/8/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 现代防御
    "B07": "rnbqkbnr/pp1ppp1p/6p1/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 皮尔茨
    "B08": "rnbqkb1r/pp1ppp1p/5np1/2p5/3PP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 1",  # 皮尔茨-古典
    "B10": "rnbqkbnr/pp1ppppp/2p5/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1",  # 卡罗康
    "B12": "rnbqkbnr/pp2pppp/2p5/3p4/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 1",  # 卡罗康-推进
    "B13": "rnbqkbnr/pp2pppp/2p5/3P4/3P4/8/PPP2PPP/RNBQKBNR b KQkq - 0 1",  # 卡罗康-交换
    "B15": "rnbqkbnr/pp2pppp/2p5/3p4/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 0 1",  # 卡罗康-古典
    "B17": "rnbqkb1r/pp2pppp/2p2n2/3p4/4P3/2N2N2/PPPP1PPP/R1BQKB1R w KQkq - 0 1",  # 卡罗康-斯米斯洛夫
    "B20": "rnbqkbnr/pp1ppppp/8/2p5/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1",  # 西西里防御
    "B22": "rnbqkbnr/pp1ppppp/8/2p5/4P3/2P5/PP1P1PPP/RNBQKBNR b KQkq - 0 1",  # 西西里-阿拉平
    "B23": "rnbqkbnr/pp1ppppp/8/2p5/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 0 1",  # 西西里-封闭
    "B30": "rnbqkbnr/pp1ppppp/8/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 0 1",  # 西西里-开放
    "B33": "r1bqkbnr/pp1ppppp/2n5/1N2p3/4P3/8/PPPP1PPP/RNBQKB1R b KQkq - 0 1",  # 西西里-斯维什尼科夫
    "B40": "rnbqkbnr/pp1p1ppp/4p3/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 西西里-保尔逊
    "B50": "rnbqkb1r/pp1ppp1p/5np1/2p5/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 西西里-纳道尔夫起点
    "B70": "rnbqkb1r/pp2pp1p/3p1np1/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 1",  # 西西里-龙式
    "B80": "rnbqkb1r/1p2pppp/p2p1n2/8/3NP3/2N5/PPP2PPP/R1BQKB1R w KQkq - 0 1",  # 西西里-舍维宁根
    "B90": "rnbqkb1r/1p2pppp/p2p1n2/6B1/3NP3/2N5/PPP2PPP/R2QKB1R b KQkq - 0 1",  # 西西里-纳道尔夫

    # ===== C 系列 (开放性开局) =====
    "C00": "rnbqkbnr/pppp1ppp/4p3/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 1",  # 法兰西
    "C02": "rnbqkbnr/ppp2ppp/4p3/3p4/3PP3/8/PPP2PPP/RNBQKBNR b KQkq - 0 1",  # 法兰西-推进
    "C10": "rnbqkb1r/ppp2ppp/4pn2/3p4/4P3/2N5/PPPP1PPP/R1BQKBNR w KQkq - 0 1",  # 法兰西-鲁宾斯坦
    "C11": "rnbqkb1r/ppp2ppp/4pn2/3p4/4P3/2N2N2/PPPP1PPP/R1BQKB1R b KQkq - 0 1",  # 法兰西-古典
    "C15": "rnbqkb1r/pppn1ppp/4p3/3p2B1/3PP3/2N2N2/PPP2PPP/R2QKB1R b KQkq - 0 1",  # 法兰西-维纳维尔
    "C20": "rnbqkbnr/pppp1ppp/8/4p3/4PP2/8/PPPP2PP/RNBQKBNR b KQkq - 0 1",  # 王翼弃兵
    "C25": "rnbqkbnr/pppp1ppp/8/4p3/4P3/2N5/PPPP1PPP/R1BQKBNR b KQkq - 0 1",  # 维也纳开局
    "C30": "rnbqkbnr/pppp1p1p/8/4p1p1/4PP2/8/PPPP2PP/RNBQKBNR w KQkq - 0 1",  # 王翼弃兵-拒绝
    "C42": "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 俄罗斯防御
    "C44": "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 苏格兰开局
    "C45": "r1bqkbnr/pppp1ppp/2n5/8/3pP3/5N2/PPP2PPP/RNBQKB1R w KQkq - 0 1",  # 苏格兰-主线
    "C47": "r1bqkb1r/pppp1ppp/2n2n2/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 0 1",  # 四马开局
    "C50": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1",  # 意大利开局
    "C51": "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/2P2N2/PP1P1PPP/RNBQK2R b KQkq - 0 1",  # 伊文思弃兵
    "C54": "r1bqk2r/pppp1ppp/2n2n2/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",  # 意大利-古典防御
    "C55": "r1bqkb1r/pppp1ppp/2n2n2/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",  # 意大利-双马防御
    "C57": "r1bqkb1r/ppp2ppp/2n2n2/4N3/2BpP3/8/PPPP1PPP/RNBQK2R w KQkq - 0 1",  # 双马-主线
    "C60": "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1",  # 西班牙开局
    "C65": "r1bqkb1r/pppp1ppp/2n2n2/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",  # 西班牙-柏林防御
    "C67": "r1bqkb1r/pppp1ppp/2n5/1B2p3/4n3/5N2/PPPP1PPP/RNBQ1RK1 w KQkq - 0 1",  # 柏林防御主线
    "C68": "r1bqkbnr/1ppp1ppp/p1B5/4p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 0 1",  # 西班牙-交换变例
    "C70": "r1bqk2r/pppp1ppp/2n2n2/1B2p3/1b2P3/5N2/PPPP1PPP/RNBQ1RK1 w KQkq - 0 1",  # 西班牙-现代变例
    "C77": "r1bqkbnr/1ppp1ppp/p1n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R w KQkq - 0 1",  # 西班牙-莫菲防御
    "C78": "r1bqk2r/1pppbppp/p1n2n2/1B2p3/4P3/5N2/PPPP1PPP/RNBQ1RK1 w KQkq - 0 1",  # 莫菲防御主线
    "C80": "r1bqkb1r/2pp1ppp/p1n2n2/1p2p3/4P3/1B3N2/PPPP1PPP/RNBQ1RK1 w KQkq - 0 1",  # 西班牙-开放变例
    "C83": "r1bqkb1r/2pp1ppp/p1n5/1p2p3/3Pn3/1B3N2/PPP2PPP/RNBQ1RK1 w KQkq - 0 1",  # 开放变例主线
    "C84": "r1bqk2r/2ppbppp/p1n2n2/1p2p3/4P3/1B3N2/PPPP1PPP/RNBQ1RK1 w KQkq - 0 1",  # 西班牙-封闭变例
    "C88": "r1bq1rk1/2ppbppp/p1n2n2/1p2p3/4P3/1B3N2/PPPP1PPP/RNBQR1K1 w - - 0 1",  # 封闭变例主线
    "C89": "r1bq1rk1/2p1bppp/p1n2n2/1p1pp3/4P3/1BP2N2/PP1P1PPP/RNBQR1K1 w - - 0 1",  # 马歇尔弃兵
    "C92": "r1bq1rk1/2ppbppp/p1n2n2/1p2p3/4P3/1B3N1P/PPPP1PP1/RNBQR1K1 b - - 0 1",  # 封闭9.h3
    "C97": "r1bq1rk1/2p1bpp1/p1np1n1p/1p2p3/4P3/1BP2N1P/PP1P1PP1/RNBQR1K1 w - - 0 1",  # 奇戈林变例

    # ===== D 系列 (后翼弃兵) =====
    "D00": "rnbqkbnr/ppp1pppp/8/3p4/2PP4/8/PP2PPPP/RNBQKBNR b KQkq - 0 1",  # 后翼弃兵
    "D02": "rnbqkbnr/ppp1pppp/8/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 1",  # 后翼弃兵-伦敦
    "D06": "rnbqkbnr/ppp1pppp/8/8/2pP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 接受变例
    "D10": "rnbqkbnr/pp2pppp/2p5/3p4/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 斯拉夫防御
    "D11": "rnbqkbnr/pp2pppp/2p5/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 1",  # 斯拉夫-主线
    "D15": "rnbqkbnr/pp2pppp/2p5/8/2pP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 1",  # 斯拉夫-接受
    "D17": "rnbqkb1r/pp2pppp/2p2n2/8/2BP4/2N5/PP2PPPP/R1BQK2R b KQkq - 0 1",  # 斯拉夫-主线后
    "D20": "rnbqkbnr/ppp1pppp/8/8/2pP4/2P5/PP2PPPP/RNBQKBNR b KQkq - 0 1",  # 接受变例后
    "D30": "rnbqkb1r/ppp1pppp/5n2/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 1",  # 后翼弃兵-拒绝
    "D35": "rnbqkb1r/ppp2ppp/4pn2/3P4/3P4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 交换变例
    "D37": "rnbqkb1r/ppp2ppp/4pn2/3p4/2PP4/5N2/PP2PPPP/RNBQKB1R w KQkq - 0 1",  # 正统防御
    "D38": "rnbqkb1r/pp3ppp/2p1pn2/3p4/2PP4/5NP1/PP2PP1P/RNBQKB1R w KQkq - 0 1",  # 拉戈津防御
    "D43": "rnbqkb1r/pp3ppp/2p1pn2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 1",  # 半斯拉夫
    "D45": "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 1",  # 半斯拉夫-梅兰
    "D46": "r1bqkb1r/pp1n1ppp/2p1pn2/3p4/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQkq - 0 1",  # 梅兰变例
    "D50": "r1bqkb1r/ppp2ppp/2n1pn2/3p2B1/2PP4/2N2N2/PP2PPPP/R2QKB1R b KQkq - 0 1",  # 正统-现代
    "D55": "r1bq1rk1/ppp2ppp/2nbpn2/3p2B1/2PP4/2N2N2/PP2PPPP/R2QKB1R w KQ - 0 1",  # 正统防御-主线
    "D60": "r1bq1rk1/ppp2ppp/2nbpn2/3p2B1/2PP4/2N2N2/PPQ1PPPP/R3KB1R b KQ - 0 1",  # 正统-卡帕布兰卡

    # ===== E 系列 (印度防御) =====
    "E00": "rnbqkb1r/pppppppp/5n2/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 印度防御
    "E10": "rnbqkb1r/pppppp1p/5np1/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 后翼印度防御
    "E12": "rnbqkb1r/p1pppp1p/1p3np1/8/2PP4/5N2/PP2PPPP/RNBQKB1R w KQkq - 0 1",  # 后翼印度-主线
    "E15": "rnbqkb1r/pp1ppppp/5n2/2p5/2PP4/5N2/PP2PPPP/RNBQKB1R b KQkq - 0 1",  # 后翼印度-卡帕布兰卡
    "E20": "rnbqk2r/pppp1ppp/4pn2/8/1bPP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 1",  # 尼姆佐维奇防御
    "E32": "rnbq1rk1/pppp1ppp/4pn2/8/1bPP4/2N5/PPQ1PPPP/R1B1KBNR b KQ - 0 1",  # 尼姆佐维奇-古典
    "E38": "rnbq1rk1/pppp1ppp/4pn2/8/1bPP4/2N2N2/PPQ1PPPP/R1B1KB1R b KQ - 0 1",  # 古典-主线
    "E40": "rnbqk2r/pppp1ppp/4pn2/8/1bPP4/2N5/PP2PPPP/R1BQKBNR w KQkq - 0 1",  # 尼姆佐维奇-鲁宾斯坦
    "E60": "rnbqkb1r/pppppp1p/5np1/8/2PP4/8/PP2PPPP/RNBQKBNR w KQkq - 0 1",  # 王翼印度防御
    "E61": "rnbqkb1r/pppppp1p/5np1/8/2PP4/2N5/PP2PPPP/R1BQKBNR b KQkq - 0 1",  # 王翼印度-主线
    "E70": "rnbqkb1r/pppppp1p/5np1/8/2PPPP2/8/PP4PP/RNBQKBNR b KQkq - 0 1",  # 王翼印度-四兵
    "E80": "rnbqkb1r/pppppp1p/5np1/8/2PP4/2N1B3/PP2PPPP/R2QKBNR b KQkq - 0 1",  # 王翼印度-萨米什
    "E90": "rnbq1rk1/ppppppbp/5np1/8/2PP4/2N2N2/PP2PPPP/R1BQKB1R w KQ - 0 1",  # 王翼印度-古典
    "E92": "rnbq1rk1/ppp1ppbp/3p1np1/6B1/2PP4/2N2N2/PP2PPPP/R2QKB1R w KQ - 0 1",  # 古典-主线
    "E97": "rnbq1rk1/pp2ppbp/3p1np1/2pP4/2P1P3/2N2N2/PP2B1PP/R1BQK2R w KQ - 0 1",  # 马德拉斯变例
}

# 中文名称映射
ECO_NAMES = {
    "A00": "不规则开局", "A01": "尼姆佐维奇-拉尔森进攻", "A04": "列蒂开局",
    "A10": "英国式开局", "A13": "英国式开局-对称变例", "A15": "英国式开局-列蒂体系",
    "A20": "英国式开局-西西里转置", "A25": "英国式开局-封闭变例",
    "A28": "英国式开局-四马变例", "A30": "英国式开局-对称体系",
    "A34": "英国式开局-对称主线", "A40": "后翼印度侧翼",
    "A45": "特龙普斯基进攻", "A46": "伦敦体系起点", "A48": "伦敦体系",
    "A50": "印度防御", "A53": "古印度防御", "A56": "贝诺尼防御",
    "A60": "现代贝诺尼防御", "A70": "现代贝诺尼-主线", "A80": "荷兰防御",
    "A85": "荷兰防御-列宁格勒变例", "A90": "荷兰防御-列宁格勒主线",
    "B00": "王前兵开局", "B01": "斯堪的纳维亚防御", "B06": "现代防御",
    "B07": "皮尔茨防御", "B08": "皮尔茨防御-古典变例", "B10": "卡罗康防御",
    "B12": "卡罗康-推进变例", "B13": "卡罗康-交换变例", "B15": "卡罗康-古典变例",
    "B17": "卡罗康-斯米斯洛夫变例", "B20": "西西里防御", "B22": "西西里-阿拉平变例",
    "B23": "西西里-封闭变例", "B30": "西西里-开放变例", "B33": "西西里-斯维什尼科夫变例",
    "B40": "西西里-保尔逊变例", "B50": "西西里-纳道尔夫体系",
    "B70": "西西里-龙式变例", "B80": "西西里-舍维宁根变例", "B90": "西西里-纳道尔夫变例",
    "C00": "法兰西防御", "C02": "法兰西防御-推进变例", "C10": "法兰西-鲁宾斯坦变例",
    "C11": "法兰西-古典变例", "C15": "法兰西-维纳维尔变例", "C20": "王翼弃兵",
    "C25": "维也纳开局", "C30": "王翼弃兵-拒绝", "C42": "俄罗斯防御",
    "C44": "苏格兰开局", "C45": "苏格兰开局-主线", "C47": "四马开局",
    "C50": "意大利开局", "C51": "意大利-伊文思弃兵", "C54": "意大利-古典防御",
    "C55": "意大利-双马防御", "C57": "双马防御-主线", "C60": "西班牙开局",
    "C65": "西班牙-柏林防御", "C67": "柏林防御-主线", "C68": "西班牙-交换变例",
    "C70": "西班牙-现代变例", "C77": "西班牙-莫菲防御", "C78": "莫菲防御-主线",
    "C80": "西班牙-开放变例", "C83": "开放变例-主线", "C84": "西班牙-封闭变例",
    "C88": "封闭变例-主线", "C89": "马歇尔弃兵", "C92": "封闭变例-9.h3",
    "C97": "奇戈林变例",
    "D00": "后翼弃兵", "D02": "后翼弃兵-伦敦体系", "D06": "后翼弃兵-接受变例",
    "D10": "斯拉夫防御", "D11": "斯拉夫防御-主线", "D15": "斯拉夫-接受变例",
    "D17": "斯拉夫-主线", "D20": "接受变例-后", "D30": "后翼弃兵-拒绝",
    "D35": "后翼弃兵-交换变例", "D37": "后翼弃兵-正统防御", "D38": "拉戈津防御",
    "D43": "半斯拉夫防御", "D45": "半斯拉夫-梅兰变例", "D46": "梅兰变例",
    "D50": "正统防御-现代", "D55": "正统防御-主线", "D60": "正统-卡帕布兰卡变例",
    "E00": "印度防御", "E10": "后翼印度防御", "E12": "后翼印度-主线",
    "E15": "后翼印度-卡帕布兰卡", "E20": "尼姆佐维奇防御", "E32": "尼姆佐维奇-古典变例",
    "E38": "古典变例-主线", "E40": "尼姆佐维奇-鲁宾斯坦变例",
    "E60": "王翼印度防御", "E61": "王翼印度-主线", "E70": "王翼印度-四兵变例",
    "E80": "王翼印度-萨米什变例", "E90": "王翼印度-古典变例",
    "E92": "古典变例-主线", "E97": "马德拉斯变例",
}


def fetch_opening_stats(eco_code: str, fen: str) -> dict:
    """从 Lichess Masters Database 获取开局统计"""
    encoded_fen = urllib.parse.quote(fen, safe='')
    url = f"https://explorer.lichess.ovh/masters?fen={encoded_fen}&topGames=0"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AgentChess/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        white = data.get("white", 0)
        draws = data.get("draws", 0)
        black = data.get("black", 0)
        total = white + draws + black

        if total == 0:
            return {"total": 0, "white_pct": 0, "draw_pct": 0, "black_pct": 0}

        return {
            "total": total,
            "white_pct": round(white / total * 100, 1),
            "draw_pct": round(draws / total * 100, 1),
            "black_pct": round(black / total * 100, 1),
        }
    except Exception as e:
        return {"error": str(e), "total": 0}


def main():
    print("=" * 60)
    print("开局大师统计抓取器")
    print(f"从 Lichess Masters DB 获取 {len(ECO_FENS)} 个变例的胜率和")
    print("=" * 60)

    # 加载已有缓存
    if STATS_FILE.exists():
        with STATS_FILE.open("r", encoding="utf-8") as f:
            stats = json.load(f)
    else:
        stats = {}

    new_count = 0
    skip_count = 0
    error_count = 0

    for eco_code, fen in ECO_FENS.items():
        if eco_code in stats and stats[eco_code].get("total", 0) > 0:
            skip_count += 1
            continue

        name = ECO_NAMES.get(eco_code, "")
        print(f"  查询 {eco_code} {name}...", end=" ", flush=True)

        result = fetch_opening_stats(eco_code, fen)
        result["name"] = name
        stats[eco_code] = result

        if result.get("total", 0) > 0:
            print(f"✓ {result['total']:,}局 "
                  f"W{result['white_pct']}% D{result['draw_pct']}% B{result['black_pct']}%")
            new_count += 1
        else:
            error_msg = result.get("error", "无数据")
            print(f"⚠ {error_msg}")
            error_count += 1

        # 每次保存
        with STATS_FILE.open("w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

        time.sleep(1.2)  # API 限速

    print(f"\n完成: 新增 {new_count}, 跳过(已有缓存) {skip_count}, 错误 {error_count}")
    print(f"统计文件: {STATS_FILE}")


if __name__ == "__main__":
    main()
