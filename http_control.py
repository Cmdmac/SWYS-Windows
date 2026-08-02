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
import base64
import hashlib
import json
import os
import socket
import ssl
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs


def _cert_paths():
    """自签名证书存放位置（项目 certs/ 下，首次启动自动生成）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    return (os.path.join(here, "certs", "voice_control_lan.pem"),
            os.path.join(here, "certs", "voice_control_lan_key.pem"))


def _ensure_self_signed_cert(cert_file, key_file):
    """生成自签名证书（SAN 含 localhost 与当前局域网 IP），供 HTTPS 服务使用。

    浏览器的 getUserMedia（麦克风）只允许 HTTPS 页面调用，因此「按住说话」
    功能需要控制台提供 HTTPS 访问入口。自签名证书只需用户首次打开时
    在浏览器里点「高级 -> 继续访问」信任一次。
    """
    if os.path.exists(cert_file) and os.path.exists(key_file):
        return
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import datetime
    import ipaddress

    os.makedirs(os.path.dirname(cert_file), exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ips = ["127.0.0.1", get_lan_ip()]
    try:
        # 尽量把本机其它网卡 IP 也放进 SAN（多网卡/虚拟网卡场景）
        for _fam, _t, _p, _c, addr in socket.getaddrinfo(socket.gethostname(), None):
            ip = addr[0]
            if ":" not in ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:  # noqa: BLE001
        pass
    san = [x509.DNSName("localhost")]
    san += [x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "voice-control-lan")])
    cert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=3650))
            .add_extension(x509.SubjectAlternativeName(san), critical=False)
            .sign(key, hashes.SHA256()))
    with open(cert_file, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    with open(key_file, "wb") as f:
        f.write(key.private_bytes(serialization.Encoding.PEM,
                                  serialization.PrivateFormat.TraditionalOpenSSL,
                                  serialization.NoEncryption()))


def _start_https(app, host, port, cert_file, key_file):
    """启动 HTTPS 控制服务（自签名证书，后台守护线程）。与 HTTP 共享同一处理器。"""
    srv = ThreadingHTTPServer((host, port), _ControlHandler)
    srv.app = app
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_file, key_file)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


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
                # 页面里的识别服务地址 / HTTPS 端口按当前配置注入
                app = getattr(self.server, "app", None)
                hcfg = (app.cfg.get("http_control", {}) if app else {}) or {}
                html = control_page_html()
                html = html.replace("__HTTPS_PORT__", str(hcfg.get("https_port", 8766)))
                self._send_html(html)
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


# ============================================================
#  ASR WebSocket 中转（纯标准库实现，无第三方依赖）
#  作用：手机/其它设备只需信任「控制页那一张自签名证书」即可使用
#  「按住说话」——音频经本服务器（同主机、同证书、:asr_proxy_port）
#  中转给 FunASR 后端，服务端之间的连接不做浏览器证书校验，
#  从而免去了在手机上单独信任 FunASR 自签名证书的麻烦。
#  帧透传原理：浏览器->服务端 的帧天然带 mask（对上游 FunASR 服务端合法），
#  FunASR->浏览器 的帧天然不带 mask（对浏览器合法），因此原样转发即可。
# ============================================================
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _recv_exact(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("socket closed")
        buf += chunk
    return buf


def _read_ws_frame(sock):
    """读一帧完整 WebSocket 数据，返回 (原始字节, opcode)。"""
    hdr = _recv_exact(sock, 2)
    b0, b1 = hdr[0], hdr[1]
    opcode = b0 & 0x0F
    masked = (b1 & 0x80) != 0
    length = b1 & 0x7F
    ext = b""
    if length == 126:
        ext = _recv_exact(sock, 2)
        length = struct.unpack("!H", ext)[0]
    elif length == 127:
        ext = _recv_exact(sock, 8)
        length = struct.unpack("!Q", ext)[0]
    mask = _recv_exact(sock, 4) if masked else b""
    payload = _recv_exact(sock, length)
    return hdr + ext + mask + payload, opcode


def _ws_server_handshake(conn, key):
    accept = base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
    resp = ("HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode()
    conn.sendall(resp)


def _frame_unmasked(opcode, payload):
    """构造服务端发出的（不带 mask 的）WebSocket 帧。"""
    n = len(payload)
    hdr = bytes([0x80 | opcode])
    if n < 126:
        hdr += bytes([n])
    elif n < 65536:
        hdr += bytes([126]) + struct.pack("!H", n)
    else:
        hdr += bytes([127]) + struct.pack("!Q", n)
    return hdr + payload


def _ws_send_close(conn, code=1011, reason=""):
    """向浏览器发送 WebSocket 关闭帧（带上可读原因，浏览器 onclose 可取到）。"""
    try:
        payload = struct.pack("!H", code) + reason.encode("utf-8", "replace")
        conn.sendall(_frame_unmasked(0x8, payload))
    except Exception:  # noqa: BLE001
        pass


def _probe_backend(backend_url, timeout=3):
    """探测 FunASR 后端 TCP 是否可达（仅连通性，不含 WS 握手）。"""
    parsed = urlparse(backend_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    if not host:
        return False, "bad backend url"
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True, ""
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def _ws_client_handshake(sock, host, port, path):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\n"
           f"Host: {host}:{port}\r\n"
           "Upgrade: websocket\r\n"
           "Connection: Upgrade\r\n"
           f"Sec-WebSocket-Key: {key}\r\n"
           "Sec-WebSocket-Version: 13\r\n"
           "Origin: https://localhost\r\n\r\n").encode()
    sock.sendall(req)
    data = b""
    while b"\r\n\r\n" not in data:
        chunk = sock.recv(4096)
        if not chunk:
            raise ConnectionError("backend handshake failed")
        data += chunk
    head = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
    if "101" not in head.split("\r\n", 1)[0]:
        raise ConnectionError("backend returned non-101")


def _ws_proxy_one_direction(src, dst, stop):
    """从 src 读帧、原样写给 dst，直到任一方关闭。"""
    try:
        while not stop.is_set():
            try:
                raw, opcode = _read_ws_frame(src)
            except Exception:
                break
            if opcode == 0x8:  # close
                break
            try:
                dst.sendall(raw)
            except Exception:
                break
    finally:
        stop.set()


def _run_asr_proxy_client(client_conn, backend_url):
    backend = None
    parsed = None
    try:
        parsed = urlparse(backend_url)
        use_tls = parsed.scheme == "wss"
        host = parsed.hostname
        port = parsed.port or (443 if use_tls else 80)
        path = parsed.path or "/"
        if not path.startswith("/"):
            path = "/" + path
        if not host:
            raise ConnectionError("bad backend url")
        raw = socket.create_connection((host, port), timeout=10)
        if use_tls:
            ctx = ssl._create_unverified_context()
            backend = ctx.wrap_socket(raw, server_hostname=host)
        else:
            backend = raw
        _ws_client_handshake(backend, host, port, path)
        stop = threading.Event()
        t1 = threading.Thread(target=_ws_proxy_one_direction,
                              args=(client_conn, backend, stop), daemon=True)
        t2 = threading.Thread(target=_ws_proxy_one_direction,
                              args=(backend, client_conn, stop), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
    except Exception as e:  # noqa: BLE001
        print(f"[ASR代理] 连接 FunASR 后端失败：{e}")
        host = parsed.hostname if parsed else "?"
        port = parsed.port if parsed else "?"
        _ws_send_close(client_conn, 1011,
                       f"FunASR 后端 {host}:{port} 不可达：{e}")
    finally:
        for s in (client_conn, backend):
            if s is None:
                continue
            try:
                s.shutdown(socket.SHUT_RDWR)
            except Exception:  # noqa: BLE001
                pass
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass


def _asr_proxy_accept_loop(listen_host, listen_port, backend_url, cert_file, key_file):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((listen_host, listen_port))
    srv.listen(128)
    ctx = None
    if cert_file and os.path.exists(cert_file) and os.path.exists(key_file):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_file, key_file)
    print(f"[ASR代理] 已启动，监听 {listen_host}:{listen_port}"
          f"（{'wss' if ctx else 'ws'}，后端 {backend_url}）")
    while True:
        try:
            conn, _addr = srv.accept()
        except Exception:  # noqa: BLE001
            continue
        try:
            if ctx:
                conn = ctx.wrap_socket(conn, server_side=True)
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = conn.recv(4096)
                if not chunk:
                    raise ConnectionError("no handshake")
                data += chunk
            head = data.split(b"\r\n\r\n", 1)[0].decode("iso-8859-1")
            is_ws, key = False, ""
            for line in head.split("\r\n"):
                low = line.lower()
                if low.startswith("upgrade:") and "websocket" in low:
                    is_ws = True
                if low.startswith("sec-websocket-key:"):
                    key = line.split(":", 1)[1].strip()
            if not (is_ws and key):
                # 非 WebSocket 请求：提供健康检查页，便于排查「后端到底通不通」
                req_line = head.split("\r\n", 1)[0]
                path = req_line.split(" ")[1] if " " in req_line else "/"
                if path in ("/", "/health", "/status"):
                    reachable, err = _probe_backend(backend_url)
                    body = json.dumps({
                        "proxy": "up",
                        "asr_proxy_port": listen_port,
                        "backend": backend_url,
                        "backend_reachable": reachable,
                        "error": err,
                    }, ensure_ascii=False).encode("utf-8")
                    resp = (f"HTTP/1.1 200 OK\r\n"
                            f"Content-Type: application/json; charset=utf-8\r\n"
                            f"Content-Length: {len(body)}\r\n"
                            f"Connection: close\r\n\r\n").encode() + body
                    conn.sendall(resp)
                else:
                    conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n"
                                 b"Connection: close\r\n\r\n")
                try:
                    conn.shutdown(socket.SHUT_RDWR)
                except Exception:  # noqa: BLE001
                    pass
                conn.close()
                continue
            _ws_server_handshake(conn, key)
            threading.Thread(target=_run_asr_proxy_client,
                             args=(conn, backend_url), daemon=True).start()
        except Exception:  # noqa: BLE001
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def _startup_log(msg):
    """启动日志：同时打印和写文件（pythonw 无控制台时至少文件里有）。"""
    try:
        print(msg)
    except Exception:  # noqa: BLE001
        pass
    try:
        import datetime
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "http_startup.log"), "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


def start_server(app, host="0.0.0.0", port=8765):
    """启动 HTTP 控制服务（后台守护线程）。返回 server 实例。

    若 config 的 http_control.https_enabled 为 true（默认），同时启动
    HTTPS 服务（端口 https_port，默认 8766；自签名证书首次自动生成到
    certs/ 下）——浏览器的麦克风只允许 HTTPS 页面，页面上的「按住说话」
    功能需要用 HTTPS 地址打开控制台。
    """
    server = ThreadingHTTPServer((host, port), _ControlHandler)
    server.app = app
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    server.https_server = None
    server.https_port = None
    server.asr_proxy_port = None
    hcfg = (app.cfg.get("http_control", {}) if app else {}) or {}
    cert_file, key_file = _cert_paths()

    # 启动 HTTPS 服务（页面麦克风需要 HTTPS）
    try:
        if hcfg.get("https_enabled", True):
            https_port = int(hcfg.get("https_port", 8766))
            _ensure_self_signed_cert(cert_file, key_file)
            server.https_server = _start_https(app, host, https_port, cert_file, key_file)
            server.https_port = https_port
            _startup_log(f"[HTTPS] 已启动：https://{get_lan_ip()}:{https_port}")
    except Exception as e:  # noqa: BLE001
        _startup_log(f"[HTTPS] 启动失败（不影响 HTTP 控制）：{e}")

    # 启动 ASR WebSocket 中转（让手机只信任控制页证书即可用按住说话）
    backend = hcfg.get("asr_ws_url", "")
    if backend:
        proxy_port = int(hcfg.get("asr_proxy_port", 8767))
        try:
            threading.Thread(target=_asr_proxy_accept_loop,
                             args=(host, proxy_port, backend, cert_file, key_file),
                             daemon=True).start()
            server.asr_proxy_port = proxy_port
            _startup_log(f"[ASR代理] 已启动：wss://{get_lan_ip()}:{proxy_port}/asr -> {backend}")
        except Exception as e:  # noqa: BLE001
            _startup_log(f"[ASR代理] 启动失败：{e}")
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
  button.mic { background: #0d9488; user-select: none; -webkit-user-select: none;
               touch-action: none; -webkit-touch-callout: none; }
  button.mic:hover { background: #0f766e; }
  button.mic.big { flex: 1; padding: 18px 16px; font-size: 18px; border-radius: 12px; }
  button.mic.rec { background: #dc2626; animation: micpulse 1s infinite; }
  button.gear { padding: 10px 13px; flex-shrink: 0; font-size: 16px; }
  @keyframes micpulse { 50% { opacity: .6; } }
  .michint { font-size: 12px; color: #94a3b8; margin: -4px 0 8px; min-height: 15px;
             line-height: 1.5; }
  .michint.err { color: #f87171; }
  .asr-cfg { background: #111827; border: 1px solid #1f2937; border-radius: 10px;
             padding: 10px 14px; margin: 0 0 14px; font-size: 13px; color: #cbd5e1; }
  .asr-cfg label { display: block; margin-bottom: 6px; color: #94a3b8; font-size: 12.5px; }
  #asrUrl { flex: 1; background: #1e293b; color: #e2e8f0; border: 1px solid #334155;
            border-radius: 8px; padding: 9px 10px; font-size: 13px; }
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

  <div class="row">
    <button id="micBtn" class="mic big" title="按住开始识别，松开结束（FunASR 流式识别）">🎤 按住说话</button>
    <button id="asrCfgBtn" class="ghost gear" title="识别服务设置">⚙</button>
  </div>
  <div class="michint" id="micHint"></div>

  <div class="asr-cfg" id="asrCfg" style="display:none">
    <label>识别服务地址（默认走本服务器中转，无需手机再信任 FunASR 证书；可改为直连 wss:// 地址）</label>
    <div class="row">
      <input id="asrUrl" placeholder="wss://192.168.0.103:8443/asr">
      <button onclick="saveAsrUrl()">保存</button>
      <button class="ghost" onclick="resetAsrUrl()">默认（本服务器中转）</button>
    </div>
  </div>

  <details class="api">
    <summary>🔌 HTTP 接口调用方式（点击展开：curl / Python 示例，可集成到脚本 / 其它程序）</summary>
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

  var QUICK = ["最小化窗口","关闭窗口","回到桌面","向上一级","返回","前进","向上滚动","向下滚动","上一个窗口","下一个窗口","向上","向下","向左","向右","回退","回车","Tab","Esc","打开记事本","打开浏览器"];

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

  // ================= 按住说话（FunASR 流式识别） =================
  // 默认走「本服务器中转」：wss://<当前主机>:8767/asr（与控制页同证书），
  // 这样手机只需信任控制页那一张证书即可，无需再单独信任 FunASR 的自签名证书。
  // 如需直连 FunASR（例如与控制页同机的场景），可在⚙里改成 wss://... 直接地址。
  var ASR_WS_DEFAULT = (location.protocol === "https:" ? "wss://" : "ws://")
                       + location.hostname + ":8767/asr";
  var HTTPS_PORT = "__HTTPS_PORT__";
  var micBtn = document.getElementById("micBtn");
  var micHint = document.getElementById("micHint");
  var asr = null;  // {ws, ctx, proc, stream, committed, interim, opened, stopping}

  // 识别服务地址：本浏览器 localStorage 持久化，未设置时用服务器下发的默认值
  var asrUrl = localStorage.getItem("asr_ws_url") || ASR_WS_DEFAULT;
  document.getElementById("asrUrl").value = asrUrl;
  document.getElementById("asrCfgBtn").onclick = function () {
    var el = document.getElementById("asrCfg");
    el.style.display = (el.style.display === "none") ? "block" : "none";
  };
  function saveAsrUrl() {
    var v = document.getElementById("asrUrl").value.trim();
    if (!/^wss?:\/\/.+/.test(v)) { micStatus("地址需以 ws:// 或 wss:// 开头", true); return; }
    asrUrl = v;
    localStorage.setItem("asr_ws_url", v);
    document.getElementById("asrCfg").style.display = "none";
    micStatus("识别服务地址已保存：" + v);
  }
  function resetAsrUrl() {
    asrUrl = ASR_WS_DEFAULT;
    document.getElementById("asrUrl").value = ASR_WS_DEFAULT;
    localStorage.removeItem("asr_ws_url");
    micStatus("已恢复默认地址：" + ASR_WS_DEFAULT);
  }

  function micStatus(msg, isErr) {
    micHint.textContent = msg || "";
    micHint.className = "michint" + (isErr ? " err" : "");
  }

  // 浏览器采集的一般是 44.1k/48k float32，FunASR 需要 16kHz int16 PCM
  function downsampleBuf(f32, fromRate, toRate) {
    if (fromRate === toRate) return f32;
    var ratio = fromRate / toRate;
    var newLen = Math.floor(f32.length / ratio);
    var out = new Float32Array(newLen);
    var pos = 0, offset = 0;
    while (pos < newLen) {
      var next = Math.min(Math.round((pos + 1) * ratio), f32.length);
      var sum = 0, cnt = 0;
      for (var i = offset; i < next; i++) { sum += f32[i]; cnt++; }
      out[pos++] = cnt ? sum / cnt : 0;
      offset = next;
    }
    return out;
  }

  function f32ToPcm16(f32) {
    var buf = new ArrayBuffer(f32.length * 2);
    var dv = new DataView(buf);
    for (var i = 0; i < f32.length; i++) {
      var s = Math.max(-1, Math.min(1, f32[i]));
      dv.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    }
    return buf;
  }

  function micResetBtn() {
    micBtn.classList.remove("rec");
    micBtn.textContent = "🎤 按住说话";
  }

  // 去掉识别文本末尾的句末标点（FunASR 每段结果会自动补一个「。」/「.」，语音指令用不到）
  function stripEndPunct(s) {
    return (s || "").replace(/[。.．\s]+$/g, "");
  }

  function asrStart(e) {
    if (e) e.preventDefault();
    // 若上一段正在收尾（松开后 800ms 内），立即终结以便快速开始新一段，
    // 否则「松手后马上再按」会被下面的守卫挡掉，表现为“按了没反应、再按一次才行”
    if (asr) {
      if (asr.stopping) {
        try { if (asr.ws) asr.ws.close(); } catch (e) {}
        try { if (asr.stream) asr.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        try { if (asr.ctx) asr.ctx.close(); } catch (e) {}
        asr = null;
      } else {
        return;  // 正在识别中，忽略重复按下
      }
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      micStatus("当前是 HTTP 页面，浏览器禁止用麦克风。请改用 https://" +
                location.hostname + ":" + HTTPS_PORT +
                " 打开（自签名证书，首次点“高级 → 继续访问”）。", true);
      return;
    }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) { micStatus("此浏览器不支持音频采集", true); return; }
    // 关键：必须在用户手势（pointerdown）内创建并恢复 AudioContext、并发起 getUserMedia，
    // 否则 iOS/Android 会拒绝麦克风授权（NotAllowedError）或 AudioContext 处于 suspended 而无声。
    var ctx = new AC();
    var proc = ctx.createScriptProcessor(4096, 1, 1);
    asr = { ws: null, ctx: ctx, proc: proc, stream: null,
            committed: "", interim: "", opened: false, stopping: false };
    if (ctx.resume) { try { ctx.resume(); } catch (e) {} }
    // 立即给视觉反馈，避免“按了没反应”的错觉（正式“识别中”要等麦克风授权成功）
    micBtn.classList.add("rec");
    micBtn.textContent = "● 准备中…松开结束";
    micStatus("正在开启麦克风…");
    // 麦克风开启兜底：若 8 秒仍未拿到音频流（系统权限/设备占用），提示并收尾
    var _armTimer = setTimeout(function () {
      if (asr && asr.ctx === ctx && !asr.stream) {
        micStatus("麦克风开启超时，请检查系统/浏览器麦克风权限后重试。", true);
        asrStop(true);
      }
    }, 8000);

    // 在手势内同步发起麦克风授权（iOS 必须于按下手势内调用，否则 NotAllowedError）
    navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true }
    }).then(function (stream) {
      if (!asr || asr.ctx !== ctx) { stream.getTracks().forEach(function (t) { t.stop(); }); return; }
      if (asr.stopping) {  // 用户在初始化期间已松手，释放即可
        stream.getTracks().forEach(function (t) { t.stop(); });
        return;
      }
      if (_armTimer) { clearTimeout(_armTimer); }
      asr.stream = stream;
      var src = ctx.createMediaStreamSource(stream);
      proc.onaudioprocess = function (ev) {
        if (!asr || !asr.ws || asr.ws.readyState !== 1) return;
        var ds = downsampleBuf(ev.inputBuffer.getChannelData(0), ctx.sampleRate, 16000);
        asr.ws.send(f32ToPcm16(ds));
      };
      src.connect(proc);
      proc.connect(ctx.destination);
      micBtn.textContent = "● 识别中…松开结束";
      micStatus("正在识别，请说话…");
    }).catch(function (err) {
      micStatus("无法使用麦克风：" + err.name + "（iOS 须用 https 页面且于本次按下手势内授权；检查浏览器麦克风权限）", true);
      asrStop(true);
    });

    // 同时建立与识别服务的连接（同主机中转或直连）
    var ws;
    try { ws = new WebSocket(asrUrl); }
    catch (err) { micStatus("识别服务地址无效：" + err, true); return; }
    asr.ws = ws;
    ws.onopen = function () {
      if (!asr || asr.ws !== ws) { try { ws.close(); } catch (e) {} return; }
      asr.opened = true;
      asr.errored = false;
      ws.send(JSON.stringify({ mode: "2pass", chunk_size: [5, 10, 5], chunk_interval: 10,
                               wav_name: "web_mic", is_speaking: true }));
    };

    ws.onmessage = function (ev) {
      if (!asr || asr.ws !== ws) return;
      try {
        var m = JSON.parse(ev.data);
        var t = (m.text || "").trim();
        if (!t) return;
        var mode = m.mode || "";
        // online = 流式中间结果（覆盖式刷新）；offline/is_final = 本段最终结果（累加）
        if (m.is_final === true || mode.indexOf("offline") >= 0) {
          asr.committed += stripEndPunct(t);
          asr.interim = "";
        } else {
          asr.interim = stripEndPunct(t);
        }
        document.getElementById("cmd").value = asr.committed + asr.interim;
      } catch (err) {}
    };

    ws.onerror = function () {
      // 真正的失败原因在 onclose 里区分（onclose 紧随 onerror 触发）
      if (asr) asr.errored = true;
    };

    ws.onclose = function (ev) {
      if (!asr || asr.ws !== ws) return;
      document.getElementById("cmd").value = asr.committed + asr.interim;
      if (!asr.stopping) {
        if (!asr.opened) {
          // 从未连上：多半是中转端口没起来（控制台未重启 / 8767 被防火墙拦截）
          micStatus("连不上识别服务 " + asrUrl +
                    "：连接被拒绝或无响应——多半是控制台未重启（中转端口 8767 未监听）" +
                    "或被防火墙拦截。请确认已重启控制台，并放行 8767 端口过 Windows 防火墙。", true);
        } else {
          // 已连上中转，但被后端断开：说明 FunASR 后端(配置 asr_ws_url)不可达
          var reason = (ev && ev.reason) ? ("（" + ev.reason + "）") : "";
          micStatus("已连上本机中转，但与 FunASR 后端断开" + reason +
                    "：后端未启动或不可达。请在浏览器打开 https://" + location.hostname +
                    ":8767/health（注意是 https，不是 http）查看后端连通性；" +
                    "或检查配置 http_control.asr_ws_url 是否正确。", true);
        }
      }
      asr = null;
      micResetBtn();
    };
  }

  function asrStop(silent) {
    if (!asr) return;
    var a = asr;
    a.stopping = true;
    // 1) 停止采集并释放麦克风（无论当前是否拿到流，都尝试释放，避免设备被占用）
    try { if (a.proc) a.proc.disconnect(); } catch (e) {}
    try { if (a.ctx) a.ctx.close(); } catch (e) {}
    try { if (a.stream) a.stream.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
    micResetBtn();
    // 2) 通知服务器说完，留 800ms 收最终结果再关闭（结果由 onmessage 持续回填）
    try {
      if (a.opened && a.ws && a.ws.readyState === 1) {
        a.ws.send(JSON.stringify({ is_speaking: false }));
        setTimeout(function () {
          try { a.ws.close(); } catch (e) {}  // 关闭触发 onclose：把 committed+interim 写入输入框
        }, 800);
      } else {
        // ws 尚未连上（或连接已断）：不会有 onclose 来清理，这里直接收尾并释放引用
        try { if (a.ws) a.ws.close(); } catch (e) {}
        asr = null;
      }
    } catch (e) { asr = null; }
    if (!silent) micStatus("识别结束，内容已放入输入框。");
  }

  micBtn.addEventListener("pointerdown", asrStart);
  micBtn.addEventListener("pointerup", function () { asrStop(false); });
  micBtn.addEventListener("pointercancel", function () { asrStop(false); });
  micBtn.addEventListener("contextmenu", function (e) { e.preventDefault(); });

  // 初次拉取 + 定时刷新
  fillExamples();
  poll();
  setInterval(poll, 1500);
</script>
</body>
</html>
"""
