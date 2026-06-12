"""
项目管理工具
为每个 PGN 文件创建独立的输出文件夹
自动组织分析、音频、视频等文件
"""

import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")


class ProjectManager:
    """项目文件夹管理器"""
    
    def __init__(self, pgn_path: Path, base_output_dir: Path = None):
        """
        初始化项目管理器
        
        Args:
            pgn_path: PGN 文件路径
            base_output_dir: 基础输出目录，默认为 output
        """
        self.pgn_path = pgn_path
        self.base_output_dir = base_output_dir or Path(__file__).parent / "output"
        self.project_dir = None
        self.project_info = {}
    
    def extract_pgn_info(self) -> dict:
        """从 PGN 文件提取信息"""
        try:
            import chess.pgn
        except ImportError:
            print("❌ 需要 python-chess: pip install python-chess")
            return {}
        
        try:
            with self.pgn_path.open("r", encoding="utf-8") as f:
                game = chess.pgn.read_game(f)
            
            if not game:
                return {}
            
            headers = game.headers
            
            # 提取关键信息
            white = headers.get("White", "Unknown")
            black = headers.get("Black", "Unknown")
            date = headers.get("Date", "Unknown")
            event = headers.get("Event", "Game")
            eco = headers.get("ECO", "")
            
            # 清理日期格式
            if date != "Unknown" and date != "?":
                try:
                    # 格式：YYYY.MM.DD
                    date_obj = datetime.strptime(date, "%Y.%m.%d")
                    date_str = date_obj.strftime("%Y%m%d")
                except:
                    date_str = date.replace(".", "").replace("?", "")
            else:
                date_str = datetime.now().strftime("%Y%m%d")
            
            info = {
                "white": white,
                "black": black,
                "date": date_str,
                "event": event,
                "eco": eco,
            }
            
            return info
        
        except Exception as e:
            print(f"⚠ 提取 PGN 信息失败: {e}")
            return {}
    
    def create_project_dir(self) -> Path:
        """创建项目文件夹"""
        # 提取 PGN 信息
        info = self.extract_pgn_info()
        
        # 构建文件夹名
        if info:
            white = info["white"].replace(" ", "_")[:20]
            black = info["black"].replace(" ", "_")[:20]
            date = info["date"]
            eco = info["eco"]
            
            if eco:
                folder_name = f"{date}_{white}_vs_{black}_{eco}"
            else:
                folder_name = f"{date}_{white}_vs_{black}"
        else:
            # 如果无法提取信息，使用时间戳
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            folder_name = f"game_{timestamp}"
        
        # 创建文件夹
        self.project_dir = self.base_output_dir / folder_name
        self.project_dir.mkdir(parents=True, exist_ok=True)
        
        # 保存项目信息
        self.project_info = {
            "pgn_file": str(self.pgn_path),
            "created_at": datetime.now().isoformat(),
            **info
        }
        
        info_file = self.project_dir / "project_info.json"
        with info_file.open("w", encoding="utf-8") as f:
            json.dump(self.project_info, f, ensure_ascii=False, indent=2)
        
        print(f"✓ 项目文件夹已创建: {self.project_dir}")
        return self.project_dir
    
    def move_output_files(self, source_dir: Path) -> bool:
        """
        将输出文件移动到项目文件夹
        
        Args:
            source_dir: 源文件夹（通常是脚本所在目录）
        
        Returns:
            是否成功
        """
        if not self.project_dir:
            print("❌ 项目文件夹未创建")
            return False
        
        # 需要移动的文件（精确名称）
        file_patterns = [
            "analysis_result.json",
            "commentary.txt",
            "merged_analysis_commentary.json",
            "video_script.tsv",
            "commentary.mp3",
            "commentary.srt",
            "timing.json",
            "training_points.json",
            "commentary_evaluation.json",
            "board_animation.mp4",
            "final_video.mp4",
        ]

        # 需要移动的通配符文件（glob 匹配）
        glob_patterns = [
            "chess_analysis_report_*.docx",
        ]
        
        # 需要移动的目录
        # 注意: pieces/ 是共享资源，不移动
        dir_patterns = [
            "board_frames",
        ]

        # 排除的资源目录（留在项目根目录，所有对局共用）
        exclude_dirs = {"pieces", ".git", "__pycache__", "output", "stockfish-windows-x86-64-avx2"}
        
        moved_count = 0
        
        # 移动文件
        for pattern in file_patterns:
            src = source_dir / pattern
            if src.exists():
                dst = self.project_dir / pattern
                try:
                    shutil.move(str(src), str(dst))
                    print(f"  ✓ {pattern}")
                    moved_count += 1
                except Exception as e:
                    print(f"  ⚠ {pattern}: {e}")
        
        # 移动通配符文件
        for pattern in glob_patterns:
            for src in source_dir.glob(pattern):
                dst = self.project_dir / src.name
                try:
                    shutil.move(str(src), str(dst))
                    print(f"  ✓ {src.name}")
                    moved_count += 1
                except Exception as e:
                    print(f"  ⚠ {src.name}: {e}")

        # 移动目录
        for dir_name in dir_patterns:
            src = source_dir / dir_name
            if src.exists():
                dst = self.project_dir / dir_name
                try:
                    if dst.exists():
                        shutil.rmtree(dst)
                    shutil.move(str(src), str(dst))
                    print(f"  ✓ {dir_name}/")
                    moved_count += 1
                except Exception as e:
                    print(f"  ⚠ {dir_name}: {e}")
        
        return moved_count > 0
    
    def create_readme(self):
        """创建项目说明文件"""
        readme_path = self.project_dir / "README.md"
        
        content = f"""# 国际象棋讲解视频项目

## 基本信息
- **白方**: {self.project_info.get('white', '未知')}
- **黑方**: {self.project_info.get('black', '未知')}
- **对局日期**: {self.project_info.get('date', '未知')}
- **开局**: {self.project_info.get('eco', '未知')}
- **事件**: {self.project_info.get('event', '未知')}

## 生成的文件

### 分析数据
- `analysis_result.json` - Stockfish 分析结果
- `merged_analysis_commentary.json` - 分析数据 + AI讲解

### 讲解内容
- `commentary.txt` - AI生成的讲解词（纯文本）
- `video_script.tsv` - 视频脚本（时间码 + 讲解）

### 音视频文件
- `board_animation.mp4` - 棋盘动画（960×720 横屏 4:3，字幕嵌入右面板）
- `commentary.mp3` - AI语音讲解（仅音频）
- `commentary.srt` - 字幕文件（外挂参考）
- `final_video.mp4` - **最终视频**（视频+音频，横屏 4:3）

### 棋盘图片
- `board_frames/` - 棋盘渲染的所有帧（PNG图片，960×720）

## 工作流程

1. **棋子生成** - 生成 lichess 风格棋子图片（首次运行）
2. **分析** - Stockfish 分析每一步棋
3. **讲解** - LLM（DeepSeek/OpenAI）生成讲解词
4. **解析** - 提取讲解词结构
5. **TTS** - Edge TTS 转换为语音
6. **渲染** - PIL 渲染横屏 4:3 棋盘动画（960×720），字幕嵌入右侧面板
7. **合成** - ffmpeg 混流视频和音频

## 发布建议

- 直接使用 `final_video.mp4` 上传到视频平台
- 或导入视频编辑软件进行进一步处理
- 使用 `commentary.srt` 作为外挂字幕

---
生成时间: {self.project_info.get('created_at', '未知')}
"""
        
        with readme_path.open("w", encoding="utf-8") as f:
            f.write(content)
        
        print(f"✓ 项目说明文件已创建: README.md")


def main():
    script_dir = Path(__file__).parent
    
    print("="*60)
    print("📁 项目文件夹管理工具")
    print("="*60)
    
    # 查找 PGN 文件
    pgn_files = list(script_dir.glob("lichess_pgn*.pgn"))
    
    if not pgn_files:
        print("\n❌ 找不到 PGN 文件")
        return
    
    pgn_path = pgn_files[0]
    print(f"\n📋 PGN 文件: {pgn_path.name}")
    
    # 创建项目管理器
    manager = ProjectManager(pgn_path)
    
    # 创建项目文件夹
    print("\n创建项目文件夹...")
    manager.create_project_dir()
    
    # 移动文件
    print("\n移动输出文件到项目文件夹...")
    if manager.move_output_files(script_dir):
        print("✓ 文件整理完成")
    
    # 创建说明文件
    manager.create_readme()
    
    print("\n" + "="*60)
    print("✅ 项目整理完成！")
    print("="*60)
    print(f"\n📁 项目文件夹: {manager.project_dir}")
    print(f"\n文件结构:")
    for item in sorted(manager.project_dir.iterdir()):
        if item.is_file():
            size = item.stat().st_size / 1024 / 1024
            print(f"   📄 {item.name} ({size:.1f} MB)")
        else:
            count = len(list(item.glob("*")))
            print(f"   📁 {item.name}/ ({count} 个文件)")


if __name__ == "__main__":
    main()
