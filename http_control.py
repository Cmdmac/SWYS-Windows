"""
HTTP 局域网控制服务。

让「语音控制台」可以通过 HTTP 请求接收文字指令，从而实现：
  · 局域网内其它设备（手机 / 另一台电脑）用浏览器打开控制页发指令；
  · 任意程序/脚本用 POST 向本机端口发送指令，集成到自动化里。

仅用标准库（http.server / threading / json / socket），无额外依赖。

API：
  POST /api/command      body: {"text": "编辑"}  -> {"ok": true, "text": "编辑"}
  GET  /api/command?text=编辑                -> 同上
  GET  /api/log          -> {"ok": true, "log": ["你：编辑", "助手：已点击控件…", ...]}
  GET  /api/status       -> {"ok": true, "status": "running"}
  GET  /                 -> 局域网控制页（单文件 HTML，可直接在浏览器打开用）
"""
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


def get_lan_ip():
    """获取本机在局域网中的 IPv4 地址（用于展示给别人访问的 URL）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # 不真正发包，只是借由路由表拿到出口网卡 IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:  # noqa: BLE001
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


class _ControlHandler(BaseHTTPRequestHandler):
    server_version = "VoiceControlHTTP/1.0"

    # 让日志静默，避免刷屏
    def log_message(self, *args, **kwargs):  # noqa: D401, ANN001
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                self._send_html(control_page_html())
            elif path == "/api/command":
                qs = parse_qs(parsed.query)
                text = (qs.get("text") or [None])[0]
                self._handle_command(text)
            elif path == "/api/status":
                self._send_json({"ok": True, "status": "running"})
            elif path == "/api/log":
                app = getattr(self.server, "app", None)
                log = app.get_recent_log() if app else []
                self._send_json({"ok": True, "log": log})
            elif path == "/api/wake":
                # 单实例唤醒：把已运行实例的窗口显示并置前（跨线程须回主线程调度）
                app = getattr(self.server, "app", None)
                if app is None:
                    self._send_json({"ok": False, "error": "server not ready"}, 503)
                    return
                try:
                    app.root.after(0, app.show_from_tray)
                    self._send_json({"ok": True, "woke": True})
                except Exception as e:  # noqa: BLE001
                    self._send_json({"ok": False, "error": str(e)}, 500)
            else:
                self._send_json({"ok": False, "error": "not found", "path": path}, 404)
        except Exception as e:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/command":
                length = int(self.headers.get("Content-Length", 0) or 0)
                raw = self.rfile.read(length) if length else b""
                try:
                    data = json.loads(raw.decode("utf-8")) if raw else {}
                except Exception:  # noqa: BLE001
                    data = {}
                text = data.get("text") or data.get("command") or data.get("query")
                if isinstance(text, list):
                    text = text[0] if text else None
                self._handle_command(text)
            else:
                self._send_json({"ok": False, "error": "not found", "path": parsed.path}, 404)
        except Exception as e:  # noqa: BLE001
            self._send_json({"ok": False, "error": str(e)}, 500)

    def _handle_command(self, text):
        if not text or not str(text).strip():
            self._send_json({"ok": False, "error": "missing 'text'"}, 400)
            return
        text = str(text).strip()
        app = getattr(self.server, "app", None)
        if app is None:
            self._send_json({"ok": False, "error": "server not ready"}, 503)
            return
        app.submit_command(text)
        self._send_json({"ok": True, "text": text, "received": True})


def start_server(app, host="0.0.0.0", port=8765):
    """启动 HTTP 控制服务（后台守护线程）。返回 server 实例。"""
    server = ThreadingHTTPServer((host, port), _ControlHandler)
    server.app = app
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def control_page_html():
    """返回局域网控制页（单文件 HTML）。"""
    return _PAGE_HTML


def api_help_text(lan_ip, port):
    """返回 HTTP 接口调用说明（多行文本），供 GUI 弹窗与文档复用。"""
    lan = f"http://{lan_ip}:{port}"
    local = f"http://127.0.0.1:{port}"
    return (
        "【局域网控制 · HTTP 接口】\n"
        f"服务已在本机 {port} 端口监听。\n"
        f"· 局域网地址：{lan}\n"
        f"· 本机地址：{local}\n\n"
        "发送指令（POST JSON）：\n"
        f'  curl -X POST {lan}/api/command \\\n'
        '       -H "Content-Type: application/json" \\\n'
        '       -d "{\\"text\\":\\"双击编辑\\"}"\n\n'
        "发送指令（GET，更简短）：\n"
        f'  curl "{lan}/api/command?text=回收站"\n\n'
        "Python 调用：\n"
        f'  import requests\n'
        f'  requests.post("{lan}/api/command", json={{"text":"编辑"}})\n\n'
        "其它接口：\n"
        f"  GET {lan}/api/log      轮询最近执行结果\n"
        f"  GET {lan}/api/status   健康检查\n"
        f"  GET {lan}/             打开本控制页\n\n"
        f"注意：局域网设备访问需允许 {port} 端口通过 Windows 防火墙；\n"
        "关机/重启/睡眠等危险操作默认被拦截（config.json 的 http_control.allow_destructive）。"
    )


_PAGE_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>局域网控制台 · 文本控制 Windows</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: "Microsoft YaHei", system-ui, sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; }
  .wrap { max-width: 720px; margin: 0 auto; padding: 18px 16px 40px; }
  h1 { font-size: 20px; margin: 6px 0 2px; }
  .sub { color: #94a3b8; font-size: 13px; margin-bottom: 14px; }
  .row { display: flex; gap: 8px; margin-bottom: 10px; }
  #base { flex: 1; background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
          border-radius: 8px; padding: 9px 10px; font-size: 13px; }
  #cmd { flex: 1; background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
         border-radius: 8px; padding: 11px 12px; font-size: 15px; }
  button { cursor: pointer; border: none; border-radius: 8px; padding: 10px 16px;
           font-size: 14px; background: #3b82f6; color: #fff; }
  button:hover { background: #2563eb; }
  button.ghost { background: #334155; }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 14px; }
  .chip { background: #1e293b; border: 1px solid #334155; color: #cbd5e1;
          border-radius: 999px; padding: 7px 13px; font-size: 13px; cursor: pointer; }
  .chip:hover { background: #334155; color: #fff; }
  .panel { background: #111827; border: 1px solid #1f2937; border-radius: 10px;
           padding: 12px; height: 46vh; overflow: auto; font-size: 13.5px; line-height: 1.7; }
  .panel .u { color: #60a5fa; }
  .panel .b { color: #34d399; }
  .panel .l { color: #9ca3af; }
  .panel .e { color: #f87171; }
  .status { font-size: 12px; color: #64748b; margin-top: 10px; }
  .ok { color: #34d399; }
  .api { background: #111827; border: 1px solid #1f2937; border-radius: 10px;
         padding: 10px 14px; margin: 8px 0 14px; }
  .api summary { cursor: pointer; font-size: 14px; color: #cbd5e1; outline: none; }
  .api-hint { color: #94a3b8; font-size: 12.5px; margin: 8px 0; line-height: 1.7; }
  .api-hint code { background: #1e293b; padding: 1px 5px; border-radius: 4px; color: #e2e8f0; }
  .codecap { color: #64748b; font-size: 12px; margin: 8px 0 4px; }
  .code { background: #0b1220; border: 1px solid #1f2937; border-radius: 8px; padding: 10px;
          font-size: 12.5px; color: #cbd5e1; white-space: pre-wrap; word-break: break-all;
          margin: 0 0 4px; }
</style>
</head>
<body>
<div class="wrap">
  <h1>🌐 局域网控制台</h1>
  <div class="sub">向本机「语音控制台」发送文字指令，远程控制这台 Windows 电脑。</div>

  <div class="row">
    <input id="base" placeholder="服务器地址，如 http://192.168.1.20:8765">
    <button class="ghost" onclick="applyBase()">应用地址</button>
  </div>

  <div class="row">
    <input id="cmd" placeholder="输入指令，如：双击编辑 / 回收站 / 编辑 / 截图" onkeydown="if(event.key==='Enter')send()">
    <button onclick="send()">发送</button>
  </div>

  <details class="api" open>
    <summary>🔌 HTTP 接口调用方式（可集成到脚本 / 其它程序）</summary>
    <p class="api-hint">服务器地址：<code id="apiBase">（自动检测）</code><br>
    把下面任意一段里的地址换成你的服务器地址即可，示例已自动填入。</p>
    <div class="codecap">① 发送指令（POST JSON）</div>
    <pre class="code" data-tpl='curl -X POST BASE/api/command -H "Content-Type: application/json" -d "{\"text\":\"双击编辑\"}"'></pre>
    <div class="codecap">② 发送指令（GET，更简短）</div>
    <pre class="code" data-tpl='curl "BASE/api/command?text=回收站"'></pre>
    <div class="codecap">③ Python 调用</div>
    <pre class="code" data-tpl='import requests; requests.post("BASE/api/command", json={"text":"编辑"})'></pre>
    <p class="api-hint">其它接口：<code>GET /api/log</code> 轮询最近执行结果 ·
    <code>GET /api/status</code> 健康检查 · <code>GET /</code> 本控制页。<br>
    说明：关机/重启/睡眠等危险操作默认被拦截，需在 config.json 将
    <code>http_control.allow_destructive</code> 设为 true 才允许通过局域网触发。</p>
  </details>

  <div class="chips" id="chips"></div>

  <div class="panel" id="log"></div>
  <div class="status" id="status">就绪</div>
</div>

<script>
  // 若由本服务托管（http/https 协议），默认地址就是当前站点；否则留空让用户填。
  var BASE = (location.protocol === "http:" || location.protocol === "https:")
             ? location.origin : "";
  if (BASE) document.getElementById("base").value = BASE;

  var QUICK = ["编辑","保存","复制","粘贴","撤销","双击编辑","右键发送",
               "回收站","截图","锁屏","最小化窗口","关闭窗口","回到桌面","向上一级","返回","前进","向上滚动","向下滚动","上一个窗口","下一个窗口","打开记事本","帮助"];

  var chipsEl = document.getElementById("chips");
  QUICK.forEach(function (q) {
    var b = document.createElement("span");
    b.className = "chip"; b.textContent = q;
    b.onclick = function () { document.getElementById("cmd").value = q; send(); };
    chipsEl.appendChild(b);
  });

  function applyBase() {
    var v = document.getElementById("base").value.trim().replace(/\/+$/, "");
    BASE = v || BASE;
    status("已设置服务器地址：" + (BASE || "(未设置)"));
    fillExamples();
    poll();
  }

  function status(msg, ok) {
    var el = document.getElementById("status");
    el.textContent = msg;
    el.className = "status" + (ok ? " ok" : "");
  }

  // 把真实服务器地址填进“HTTP 接口调用方式”里的示例代码
  function fillExamples() {
    var origin = BASE || "http://127.0.0.1:8765";
    var ab = document.getElementById("apiBase");
    if (ab) ab.textContent = origin;
    var blocks = document.querySelectorAll(".code[data-tpl]");
    for (var i = 0; i < blocks.length; i++) {
      blocks[i].textContent = blocks[i].getAttribute("data-tpl").replace(/BASE/g, origin);
    }
  }

  function post(text) {
    if (!BASE) { status("请先填写服务器地址（本机可填 http://127.0.0.1:8765）"); return; }
    fetch(BASE + "/api/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: text })
    }).then(function (r) { return r.json(); }).then(function (j) {
      if (j.ok) status("已发送：" + text, true);
      else status("发送失败：" + (j.error || "未知错误"));
    }).catch(function (e) {
      status("无法连接服务器：" + e + "（检查地址/端口/防火墙）");
    });
  }

  function send() {
    var el = document.getElementById("cmd");
    var t = el.value.trim();
    if (!t) return;
    post(t);
    el.value = "";
  }

  function poll() {
    if (!BASE) return;
    fetch(BASE + "/api/log").then(function (r) { return r.json(); }).then(function (j) {
      if (!j.ok) return;
      var box = document.getElementById("log");
      box.innerHTML = j.log.map(function (line) {
        var cls = "l";
        if (line.indexOf("你：") === 0) cls = "u";
        else if (line.indexOf("助手：") === 0) cls = "b";
        else if (line.indexOf("⚠") === 0) cls = "e";
        return '<div class="' + cls + '">' + escapeHtml(line) + "</div>";
      }).join("");
      box.scrollTop = box.scrollHeight;
    }).catch(function () {});
  }

  function escapeHtml(s) {
    return s.replace(/[&<>]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c];
    });
  }

  // 初次拉取 + 定时刷新
  fillExamples();
  poll();
  setInterval(poll, 1500);
</script>
</body>
</html>
"""
