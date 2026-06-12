"""
深蓝棋评 Web 控制台
提供 PGN 选择、风格切换、观众水平选择的 Web 界面
启动后访问 http://localhost:5000
"""

import sys
from pathlib import Path
sys.stdout.reconfigure(encoding="utf-8")

try:
    from flask import Flask, render_template_string, request, jsonify, redirect, url_for
except ImportError:
    print("请安装 Flask: pip install flask")
    sys.exit(1)

import subprocess
import threading
import json
import time

app = Flask(__name__)
SCRIPT_DIR = Path(__file__).parent

# 任务状态
pipeline_status = {"running": False, "progress": "", "log": []}


def find_pgn_files():
    """扫描项目目录中的 PGN 文件"""
    pgns = []
    # 根目录
    for f in sorted(SCRIPT_DIR.glob("lichess_pgn*.pgn")):
        pgns.append({"path": str(f.name), "name": f.name, "location": "根目录"})
    # output 目录
    outdir = SCRIPT_DIR / "output"
    if outdir.exists():
        for sub in sorted(outdir.iterdir(), reverse=True):
            if sub.is_dir():
                for f in sorted(sub.glob("*.pgn")):
                    pgns.append({"path": str(f.relative_to(SCRIPT_DIR)),
                                 "name": f.name, "location": sub.name})
    return pgns


def run_pipeline(pgn_path, style, audience):
    """后台运行 pipeline"""
    pipeline_status["running"] = True
    pipeline_status["progress"] = "启动中..."
    pipeline_status["log"] = []

    # 修改 pipeline.py 中的 PGN_PATH（通过复制+环境变量方式）
    env = {
        **dict(sys.modules),
        "STYLE": style,
        "AUDIENCE": audience,
        "PGN_OVERRIDE": str(pgn_path),
    }

    cmd = [
        sys.executable, "-u", str(SCRIPT_DIR / "pipeline.py"),
        "--style", style,
        "--audience", audience,
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(SCRIPT_DIR),
            env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"},
        )

        for line in proc.stdout:
            line = line.strip()
            if line:
                pipeline_status["log"].append(line)
                # 更新进度
                if "第" in line and "步" in line:
                    pipeline_status["progress"] = line[:100]
                elif "完成" in line or "✓" in line:
                    pipeline_status["progress"] = line[:100]
                elif "失败" in line or "❌" in line:
                    pipeline_status["progress"] = "⚠ " + line[:100]

        proc.wait()
        pipeline_status["progress"] = "✅ 完成！" if proc.returncode == 0 else f"❌ 退出码: {proc.returncode}"
    except Exception as e:
        pipeline_status["progress"] = f"❌ 异常: {e}"
        pipeline_status["log"].append(str(e))
    finally:
        pipeline_status["running"] = False


# ===================== HTML 模板 =====================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>深蓝棋评 · AI 讲解视频生成器</title>
<style>
  :root { --bg: #0f1419; --card: #1a2332; --accent: #b4965a; --accent2: #2a6496;
          --text: #d8d4c8; --muted: #8899aa; --red: #c85250; --green: #5a9e6f;
          --border: #2a3544; --radius: 10px; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); font-family:"Microsoft YaHei","PingFang SC",sans-serif;
         min-height:100vh; display:flex; }
  .sidebar { width:260px; background:var(--card); padding:24px 20px; border-right:1px solid var(--border);
             display:flex; flex-direction:column; gap:8px; flex-shrink:0; }
  .sidebar .logo { text-align:center; margin-bottom:16px; }
  .sidebar .logo h1 { font-size:20px; color:var(--accent); letter-spacing:2px; }
  .sidebar .logo p { font-size:11px; color:var(--muted); margin-top:4px; }
  .sidebar a { color:var(--text); text-decoration:none; padding:10px 14px; border-radius:6px;
               font-size:14px; transition:all .2s; display:block; }
  .sidebar a:hover, .sidebar a.active { background:rgba(180,150,90,.12); color:var(--accent); }
  .sidebar .version { margin-top:auto; font-size:10px; color:var(--muted); text-align:center; }
  .main { flex:1; padding:32px 40px; overflow-y:auto; }
  .main h2 { font-size:22px; margin-bottom:8px; color:var(--accent); }
  .subtitle { color:var(--muted); font-size:13px; margin-bottom:28px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
          padding:24px; margin-bottom:20px; }
  .card h3 { font-size:16px; margin-bottom:16px; color:var(--text); }
  .form-row { display:flex; gap:16px; margin-bottom:16px; flex-wrap:wrap; }
  .form-group { flex:1; min-width:180px; }
  .form-group label { display:block; font-size:12px; color:var(--muted); margin-bottom:6px;
                      text-transform:uppercase; letter-spacing:1px; }
  select, input[type=text] { width:100%; padding:10px 14px; background:#0f1419;
    border:1px solid var(--border); border-radius:6px; color:var(--text); font-size:14px;
    font-family:inherit; outline:none; transition:border .2s; }
  select:focus, input:focus { border-color:var(--accent); }
  .btn { padding:12px 28px; border:none; border-radius:6px; font-size:15px; font-weight:bold;
         cursor:pointer; transition:all .2s; font-family:inherit; letter-spacing:1px; }
  .btn-primary { background:var(--accent); color:#0f1419; }
  .btn-primary:hover { background:#c9a868; transform:translateY(-1px); }
  .btn-primary:disabled { opacity:.5; cursor:not-allowed; transform:none; }
  .btn-outline { background:transparent; border:1px solid var(--accent); color:var(--accent); }
  .btn-outline:hover { background:rgba(180,150,90,.1); }
  .btn-sm { padding:6px 14px; font-size:12px; }
  .status-bar { display:flex; align-items:center; gap:10px; padding:12px 16px;
                background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
                margin-top:16px; font-size:13px; }
  .status-dot { width:8px; height:8px; border-radius:50%; flex-shrink:0; }
  .status-dot.idle { background:var(--muted); }
  .status-dot.running { background:var(--accent); animation:pulse 1.5s infinite; }
  .status-dot.done { background:var(--green); }
  .status-dot.error { background:var(--red); }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.3} }
  .log-box { background:#0a0e12; border:1px solid var(--border); border-radius:var(--radius);
             padding:16px; max-height:400px; overflow-y:auto; font-size:12px;
             font-family:"Cascadia Code","Consolas",monospace; line-height:1.7; margin-top:12px; }
  .log-box .l { color:var(--muted); }
  .log-box .warn { color:var(--accent); }
  .log-box .err { color:var(--red); }
  .log-box .ok { color:var(--green); }
  .stats { display:flex; gap:16px; flex-wrap:wrap; }
  .stat { background:var(--card); border:1px solid var(--border); border-radius:var(--radius);
          padding:16px 20px; flex:1; min-width:120px; text-align:center; }
  .stat .num { font-size:28px; font-weight:bold; color:var(--accent); }
  .stat .label { font-size:11px; color:var(--muted); margin-top:2px; }
</style>
</head>
<body>

<div class="sidebar">
  <div class="logo">
    <h1>♞ 深蓝棋评</h1>
    <p>AI 国际象棋讲解视频生成器</p>
  </div>
  <a href="#" class="active" onclick="switchTab('generate')">🎬 生成视频</a>
  <a href="#" onclick="switchTab('history')">📂 历史项目</a>
  <a href="#" onclick="switchTab('settings')">⚙️ 设置</a>
  <div class="version">v3.0 · 深蓝国际象棋协会</div>
</div>

<div class="main" id="main-content">

  <!-- ===== 生成页面 ===== -->
  <div id="tab-generate">
    <h2>🎬 一键生成讲解视频</h2>
    <p class="subtitle">选择 PGN 棋谱、讲解风格和观众水平，AI 自动完成全流程</p>

    <div class="card">
      <h3>📋 第 1 步：选择棋谱</h3>
      <div class="form-row">
        <div class="form-group" style="flex:2">
          <label>PGN 棋谱文件</label>
          <select id="pgn-select">
            <option value="">-- 选择一个 PGN 文件 --</option>
            {% for pgn in pgn_files %}
            <option value="{{ pgn.path }}">{{ pgn.name }} ({{ pgn.location }})</option>
            {% endfor %}
          </select>
        </div>
      </div>
      <div id="pgn-preview" style="margin-top:8px;font-size:12px;color:var(--muted)"></div>
    </div>

    <div class="card">
      <h3>🎨 第 2 步：选择风格与水平</h3>
      <div class="form-row">
        <div class="form-group">
          <label>讲解风格</label>
          <select id="style-select">
            <option value="auto">🤖 自动选择（推荐）</option>
            <option value="战术解析">⚔️ 战术解析 — 步步紧逼，拆解杀招</option>
            <option value="战略漫谈">🧠 战略漫谈 — 从容洞察，大局观</option>
            <option value="快评速览">⚡ 快评速览 — 快节奏吐槽风</option>
            <option value="学院课堂">📚 学院课堂 — 深入浅出教学</option>
          </select>
        </div>
        <div class="form-group">
          <label>观众水平</label>
          <select id="audience-select">
            <option value="中级">🎓 中级（默认）</option>
            <option value="初级">🌱 初级 — 术语解释，多打比方</option>
            <option value="高级">🏆 高级 — 自由使用专业术语</option>
          </select>
        </div>
      </div>
    </div>

    <div style="display:flex;gap:12px;align-items:center;">
      <button class="btn btn-primary" id="btn-generate" onclick="startGenerate()">
        🚀 开始生成
      </button>
      <button class="btn btn-outline" id="btn-stop" onclick="stopGenerate()" style="display:none">
        ⏹ 停止
      </button>
    </div>

    <div class="status-bar" id="status-bar" style="display:none">
      <div class="status-dot" id="status-dot"></div>
      <span id="status-text">就绪</span>
    </div>

    <div class="log-box" id="log-box" style="display:none"></div>
  </div>

  <!-- ===== 历史页面 ===== -->
  <div id="tab-history" style="display:none">
    <h2>📂 历史项目</h2>
    <p class="subtitle">查看已生成的视频和棋评文档</p>
    <div id="history-list"></div>
  </div>

  <!-- ===== 设置页面 ===== -->
  <div id="tab-settings" style="display:none">
    <h2>⚙️ 设置</h2>
    <p class="subtitle">配置 API Key 和引擎路径</p>
    <div class="card">
      <h3>API 配置</h3>
      <div class="form-row">
        <div class="form-group">
          <label>API Key</label>
          <input type="text" id="api-key" placeholder="sk-..." value="{{ api_key }}">
        </div>
        <div class="form-group">
          <label>模型</label>
          <input type="text" id="model-name" value="deepseek-v4-pro">
        </div>
      </div>
    </div>
  </div>

</div>

<script>
function switchTab(name) {
  document.querySelectorAll('.sidebar a').forEach(a => a.classList.remove('active'));
  event.target.classList.add('active');
  ['generate','history','settings'].forEach(t => {
    document.getElementById('tab-'+t).style.display = t===name ? 'block' : 'none';
  });
}

let pollTimer = null;
let logCount = 0;

async function startGenerate() {
  const pgn = document.getElementById('pgn-select').value;
  if (!pgn) { alert('请先选择 PGN 文件'); return; }

  document.getElementById('btn-generate').disabled = true;
  document.getElementById('btn-generate').textContent = '⏳ 运行中...';
  document.getElementById('btn-stop').style.display = 'inline-block';
  document.getElementById('status-bar').style.display = 'flex';
  document.getElementById('status-dot').className = 'status-dot running';
  document.getElementById('status-text').textContent = '启动中...';
  document.getElementById('log-box').style.display = 'block';
  document.getElementById('log-box').innerHTML = '';

  const resp = await fetch('/api/start', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      pgn: pgn,
      style: document.getElementById('style-select').value,
      audience: document.getElementById('audience-select').value
    })
  });
  const data = await resp.json();
  if (data.ok) {
    pollTimer = setInterval(pollStatus, 1500);
    logCount = 0;
  }
}

async function stopGenerate() {
  await fetch('/api/stop', {method:'POST'});
  clearInterval(pollTimer);
  resetUI();
}

async function pollStatus() {
  const resp = await fetch('/api/status');
  const data = await resp.json();
  document.getElementById('status-text').textContent = data.progress;
  const dot = document.getElementById('status-dot');
  if (data.running) {
    dot.className = 'status-dot running';
  } else {
    dot.className = data.progress.includes('✅') ? 'status-dot done' :
                data.progress.includes('❌') ? 'status-dot error' : 'status-dot idle';
    document.getElementById('btn-generate').disabled = false;
    document.getElementById('btn-generate').textContent = '🚀 开始生成';
    document.getElementById('btn-stop').style.display = 'none';
    clearInterval(pollTimer);
  }
  // 更新日志
  if (data.log && data.log.length > logCount) {
    const box = document.getElementById('log-box');
    for (let i = logCount; i < data.log.length; i++) {
      let line = data.log[i];
      let cls = 'l';
      if (line.includes('✓') || line.includes('完成')) cls = 'ok';
      else if (line.includes('❌') || line.includes('失败')) cls = 'err';
      else if (line.includes('⚠')) cls = 'warn';
      box.innerHTML += '<span class="'+cls+'">'+escapeHtml(line)+'</span>\n';
    }
    box.scrollTop = box.scrollHeight;
    logCount = data.log.length;
  }
}

function resetUI() {
  document.getElementById('btn-generate').disabled = false;
  document.getElementById('btn-generate').textContent = '🚀 开始生成';
  document.getElementById('btn-stop').style.display = 'none';
  document.getElementById('status-dot').className = 'status-dot idle';
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

// 页面加载时获取历史
fetch('/api/history').then(r=>r.json()).then(data => {
  const div = document.getElementById('history-list');
  if (!data.length) { div.innerHTML='<p style="color:var(--muted)">暂无历史项目</p>'; return; }
  let html = '';
  data.forEach(p => {
    html += '<div class="card" style="padding:16px"><b>'+p.name+'</b><br>';
    html += '<span style="font-size:12px;color:var(--muted)">'+p.files.join(' · ')+'</span></div>';
  });
  div.innerHTML = html;
});
</script>
</body>
</html>
"""


@app.route("/")
def index():
    pgn_files = find_pgn_files()
    return render_template_string(
        HTML_TEMPLATE,
        pgn_files=pgn_files,
        api_key="sk-...",
    )


@app.route("/api/start", methods=["POST"])
def api_start():
    if pipeline_status["running"]:
        return jsonify({"ok": False, "error": "已有任务在运行"})

    data = request.json
    pgn_rel = data.get("pgn", "")
    style = data.get("style", "auto")
    audience = data.get("audience", "中级")

    # 实际的 PGN 路径
    pgn_path = SCRIPT_DIR / pgn_rel

    if not pgn_path.exists():
        return jsonify({"ok": False, "error": f"PGN 文件不存在: {pgn_path}"})

    threading.Thread(target=run_pipeline, args=(pgn_path, style, audience),
                     daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/stop", methods=["POST"])
def api_stop():
    pipeline_status["running"] = False
    return jsonify({"ok": True})


@app.route("/api/status")
def api_status():
    return jsonify({
        "running": pipeline_status["running"],
        "progress": pipeline_status["progress"],
        "log": pipeline_status["log"][-200:],  # 最近 200 行
    })


@app.route("/api/history")
def api_history():
    outdir = SCRIPT_DIR / "output"
    projects = []
    if outdir.exists():
        for sub in sorted(outdir.iterdir(), reverse=True):
            if sub.is_dir():
                files = [f.name for f in sub.iterdir() if f.is_file()]
                projects.append({"name": sub.name, "files": files[:10]})
    return jsonify(projects[:20])


def main():
    print("=" * 50)
    print("深蓝棋评 Web 控制台")
    print("=" * 50)
    print(f"\n  打开浏览器访问: http://localhost:5000")
    print(f"  按 Ctrl+C 停止服务器\n")

    import webbrowser
    webbrowser.open("http://localhost:5000")

    app.run(host="0.0.0.0", port=5000, debug=False)


if __name__ == "__main__":
    main()
