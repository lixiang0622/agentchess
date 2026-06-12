"""
Syzygy 残局库设置向导
=====================
本项目已默认使用 Lichess API 在线查询(带本地缓存)，覆盖 <=7 子局面。

如需本地 probing(更快、可离线)，有两个选择：

【方案 A: 手动下载(推荐)】
  1. 访问 https://tablebase.lichess.ovh/tables/standard/
  2. 下载需要的 .rtbw 和 .rtbz 文件到 syzygy/ 目录
  3. 3-4-5 子完整集约 1GB，6 子约 150GB
  4. 只需下载 3-4-5 子即可覆盖大多数实战残局

【方案 B: Torrent 下载(完整)】
  访问 https://tablebase.lichess.ovh/tables/standard/ 获取 torrent 文件
  推荐只下载 3-4-5 子部分

下载完成后运行 python tablebase.py 验证本地 probing 是否生效。

当前状态：API 在线查询 + 本地缓存(tablebase_cache.json)
"""


def main():
    print(__doc__)

    from pathlib import Path
    syzygy_dir = Path(__file__).parent / "syzygy"
    syzygy_dir.mkdir(parents=True, exist_ok=True)

    rtbw = list(syzygy_dir.glob("*.rtbw"))
    rtbz = list(syzygy_dir.glob("*.rtbz"))

    print(f"Syzygy 目录: {syzygy_dir}")
    print(f"  当前 .rtbw 文件: {len(rtbw)} 个")
    print(f"  当前 .rtbz 文件: {len(rtbz)} 个")

    if rtbw and rtbz:
        print(f"\n本地 Syzygy 已就绪！运行 python tablebase.py 验证。")
    else:
        print(f"\n本地 Syzygy 尚未配置。API 在线查询模式正常工作。")
        print(f"如需离线 probing，请按上述指引下载文件。")


if __name__ == "__main__":
    main()
