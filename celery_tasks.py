"""
分布式任务队列 (Celery Tasks)
支持批量异步处理多局对局，配合 Redis + Celery Worker。

依赖:
  pip install celery[redis] redis

启动 Worker:
  celery -A celery_tasks worker --pool=prefork --concurrency=2 -l info

API 集成:
  from celery_tasks import analyze_and_generate
  task = analyze_and_generate.delay(pgn_text, style="战术解析", audience="中级")
  # task.id → 轮询 /api/status/<task_id>

Web 端点 (web_ui.py):
  @app.route('/api/submit', methods=['POST'])
  def submit_game(): ...
  @app.route('/api/status/<task_id>')
  def task_status(task_id): ...
"""

import sys
import json
import tempfile
import os
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════
#  Celery 配置
# ═══════════════════════════════════════════════════════════════

CELERY_READY = False
app = None

try:
    from celery import Celery
    from celery.result import AsyncResult

    app = Celery(
        'agentchess',
        broker='redis://localhost:6379/0',
        backend='redis://localhost:6379/0',
    )

    app.conf.update(
        task_serializer='json',
        accept_content=['json'],
        result_serializer='json',
        timezone='Asia/Shanghai',
        enable_utc=True,
        task_track_started=True,
        task_acks_late=True,
        worker_prefetch_multiplier=1,  # 每worker一次只取一个任务
    )

    CELERY_READY = True
    print("✓ Celery + Redis 已就绪")

except ImportError:
    print("⚠ Celery/Redis 未安装。任务队列不可用。")
    print("  安装: pip install celery[redis] redis")
except Exception as e:
    print(f"⚠ Celery 初始化失败: {e}")


# ═══════════════════════════════════════════════════════════════
#  任务定义
# ═══════════════════════════════════════════════════════════════

def _run_pipeline_sync(pgn_text: str, style: str = "auto",
                        audience: str = "中级", api_key: str = "") -> dict:
    """
    同步运行完整流水线（非 Celery 模式直接调用）。
    保存 PGN → 运行 analys.py → 运行 pipeline.py
    """
    # 保存 PGN
    pgn_path = SCRIPT_DIR / f"_batch_input_{int(time.time())}.pgn"
    with pgn_path.open("w", encoding="utf-8") as f:
        f.write(pgn_text)

    results = {
        "status": "success",
        "pgn_file": str(pgn_path),
        "steps": [],
        "commentary": "",
        "output_dir": "",
    }

    try:
        import subprocess

        # 1. 棋局分析
        print(f"  分析 PGN: {pgn_path.name}")
        # 临时修改 analyse.py 的 PGN 路径...可以用环境变量或临时替换
        import analyse as _analyse
        _analyse.PGN_PATH = pgn_path
        # 重新运行主逻辑 —— 实际上 analyse.py 直接执行会生成 analysis_result.json

        # 简化: 直接调 subprocess
        r1 = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "analyse.py")],
            capture_output=True, timeout=120, cwd=str(SCRIPT_DIR)
        )
        if r1.returncode != 0:
            raise RuntimeError(f"analyse.py 失败: {r1.stderr.decode()[-200:]}")

        # 读取分析结果
        analysis_file = SCRIPT_DIR / "analysis_result.json"
        if analysis_file.exists():
            with analysis_file.open("r", encoding="utf-8") as f:
                analysis = json.load(f)
            results["steps"] = len(analysis.get("steps", []))

        # 2. 讲解词生成
        r2 = subprocess.run(
            [sys.executable, str(SCRIPT_DIR / "pipeline.py"),
             "--style", style, "--audience", audience],
            capture_output=True, timeout=300, cwd=str(SCRIPT_DIR)
        )
        if r2.returncode != 0:
            raise RuntimeError(f"pipeline.py 失败: {r2.stderr.decode()[-200:]}")

        # 读讲解词
        commentary_file = SCRIPT_DIR / "commentary.txt"
        if commentary_file.exists():
            results["commentary"] = commentary_file.read_text(encoding="utf-8")[:500]

        # 3. 视频输出位置
        output_dir = SCRIPT_DIR / "output"
        if output_dir.exists():
            subdirs = list(output_dir.iterdir())
            if subdirs:
                results["output_dir"] = str(sorted(subdirs, key=os.path.getmtime)[-1])

        return results

    except Exception as e:
        return {"status": "error", "error": str(e)}

    finally:
        # 清理临时 PGN
        if pgn_path.exists():
            try:
                pgn_path.unlink()
            except Exception:
                pass


if CELERY_READY:
    @app.task(bind=True)
    def analyze_and_generate(self, pgn_text: str, style: str = "auto",
                              audience: str = "中级",
                              api_key: str = "") -> dict:
        """
        Celery 异步任务: 分析 + 生成视频
        """
        self.update_state(state='PROCESSING',
                          meta={'progress': 0, 'message': '开始分析...'})
        return _run_pipeline_sync(pgn_text, style, audience, api_key)


def submit_task(pgn_text: str, style: str = "auto",
                audience: str = "中级") -> str:
    """
    提交异步任务（Web API 调用）。
    返回 task_id。
    """
    if CELERY_READY:
        task = analyze_and_generate.delay(pgn_text, style, audience)
        return task.id
    else:
        # 同步回退模式
        import uuid
        task_id = str(uuid.uuid4())
        # 后台线程执行
        import threading
        t = threading.Thread(
            target=lambda: _run_pipeline_sync(pgn_text, style, audience),
            daemon=True
        )
        t.start()
        return f"sync_{task_id}"


def get_task_status(task_id: str) -> dict:
    """
    查询任务状态。
    """
    if CELERY_READY:
        task = analyze_and_generate.AsyncResult(task_id)
        return {
            "task_id": task_id,
            "state": task.state,
            "result": task.result if task.ready() else None,
            "info": str(task.info) if task.info else "",
        }
    else:
        return {"task_id": task_id, "state": "UNKNOWN",
                "info": "Celery 不可用，任务在后台线程运行"}


# ═══════════════════════════════════════════════════════════════
#  批量处理快捷函数
# ═══════════════════════════════════════════════════════════════

def batch_submit(pgn_list: list[str], style: str = "auto",
                 audience: str = "中级") -> list[str]:
    """批量提交多个对局"""
    task_ids = []
    for pgn in pgn_list:
        tid = submit_task(pgn, style, audience)
        task_ids.append(tid)
        print(f"  提交: {tid}")
    return task_ids


# ═══════════════════════════════════════════════════════════════
#  CLI
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse
    parser = argparse.ArgumentParser(description="分布式任务队列")
    parser.add_argument("--status", type=str, help="查询任务状态")
    parser.add_argument("--batch", type=str, help="批量提交 PGN 文件列表")
    parser.add_argument("--test", action="store_true", help="自测")
    args = parser.parse_args()

    if args.test:
        print("=" * 60)
        print("Celery 任务队列 自测")
        print("=" * 60)
        print(f"Redis: {'可用' if CELERY_READY else '不可用 (请安装celery[redis])'}")
        if CELERY_READY:
            print("启动 Worker: celery -A celery_tasks worker -l info")
            print("Web API: 可在 web_ui.py 中 import submit_task / get_task_status")
        return

    if args.status:
        status = get_task_status(args.status)
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    if args.batch:
        bf = Path(args.batch)
        if not bf.exists():
            print(f"文件不存在: {bf}")
            return
        with bf.open("r", encoding="utf-8") as f:
            pgns = f.read().split("\n\n[Event")  # 简单分割
        pgns = ["[Event" + p for p in pgns[1:]] if pgns[0].startswith("[Event") else pgns
        if len(pgns) <= 1:
            pgns = [f.read()]  # 单个PGN
        print(f"批量提交 {len(pgns)} 局")
        tids = batch_submit(pgns[:5])  # 限5局
        print(f"任务ID: {tids}")

    parser.print_help()


if __name__ == "__main__":
    main()