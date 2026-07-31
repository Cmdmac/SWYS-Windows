"""
语音控制台 —— 可见可说的 Windows 文本控制系统。

- 简单指令（打开应用、截图、锁屏、音量、窗口操作、时间日期等）直接执行，无需联网。
- 复杂指令交给大模型分析，拆成动作步骤后执行。
- 支持语音播报（可说）与麦克风语音输入（可见可说）。

运行前：pip install -r requirements.txt
启动：python main.py   （或双击 run.bat）
"""
import os
import sys
import threading
import ctypes

import tkinter as tk
import tkinter.ttk as ttk
import tkinter.scrolledtext as scrolledtext
from tkinter import messagebox, filedialog

import config as config_mod
import simple
import actions
import llm
import tts
import stt

APP_TITLE = "语音控制台 · 文本控制 Windows"

HELP_TEXT = (
    "【用法】\n"
    "· 在底部输入框输入指令，回车或点「发送」。\n"
    "· 点「🎤」用麦克风说话（需联网+麦克风）。\n"
    "· 点「🔊」开/关语音播报。\n"
    "· 点「🧪演练」开启测试模式：指令只解析、不真正执行，方便安全试错。\n"
    "· 点「⚙」填写大模型 API Key 等设置。\n"
    "· 点「🌐」打开「局域网控制 · HTTP 接口」窗口，里面给出本机地址、curl/Python 调用示例与复制按钮；也可直接在手机/其它电脑浏览器打开 http://<本机局域网IP>:8765 远程发指令（默认端口 8765）。\n"
    "· 系统托盘：启动后默认最小化到托盘（可在 config.json 的 tray.start_minimized 改为 false 让其直接显示）。托盘区有「语音控制台」蓝色图标：左键单击 = 显示/隐藏窗口，右键菜单 = 打开窗口 / 退出。点窗口右上角「×」不会退出，而是收进托盘；想彻底退出请右键托盘图标选「退出」。\n"
    "· 双击启动：直接双击本目录的 launch.vbs 即可静默启动（无黑色控制台窗口）。想放到桌面/任务栏，右键 launch.vbs →「发送到」→「桌面快捷方式」即可；可右键该快捷方式改图标为 voice_control.ico。\n"
    "\n"
    "【命令行快速测试（无需界面）】\n"
    "  python main.py --test \"打开记事本\"\n"
    "  python main.py --test \"帮我把音量调大两格再打开浏览器\"\n"
    "  会直接打印将执行的动作步骤，不执行任何操作。\n"
    "\n"
    "【简单指令（直接执行，无需大模型）】\n"
    "打开记事本 / 打开chrome / 打开百度 / 打开 D:\\报告.docx\n"
    "截图 / 锁屏 / 关机 / 重启 / 睡眠\n"
    "音量调大 / 音量调小 / 静音\n"
    "最小化窗口 / 最大化窗口 / 还原窗口 / 关闭窗口（作用最顶层可见窗口，不会关掉本程序）/ 回到桌面 / 切换窗口\n"
    "窗口  /  当前窗口  （在鼠标当前位置点击该窗口）\n"
    "点击窗口菜单  /  双击  /  右击  /  点击 100,200  /  鼠标移到 100,200  /  向上滚动\n"
    "输入 你好世界  /  现在几点 / 今天星期几\n"
    "\n"
    "【可见可说：说出控件/菜单名即控制】\n"
    "· 本程序自身按钮（发送 / 清空 / 演练 / 语音 / 设置 / 帮助 / 麦克风）是语义动作，说出即直接执行，无需 OCR。\n"
    "· 其它应用的常用动作（保存/复制/粘贴/撤销/编辑/文件/打印…）会直接向前台窗口发送对应快捷键（如 Ctrl+S / Ctrl+C / Alt+E），无需 OCR，更快更稳。\n"
    "· 其它应用的其它控件/按钮名：用 UI 自动化(uiautomation)按名称定位并点击；\n"
    "  若控件没暴露可访问名称（如部分自绘按钮），会自动改用 OCR：截图识别屏上中文后按坐标点击（需安装 Tesseract-OCR）。\n"
    "例如（对本程序）：发送 / 清空 / 演练模式 / 语音播报 / 设置 / 帮助\n"
    "例如（对其它应用）：编辑 / 保存 / 复制 / 粘贴 / 文件 / 打印 …\n"
    "找不到对应控件时会提示，不会报错。\n"
    "\n"
    "【没配大模型 Key 时】\n"
    "上面的“直接指令”和“说控件名点击”都能执行；只有真正一句话说不清的复杂指令才需要配置 Key。\n"
    "\n"
    "【复杂指令（交给大模型分析）】\n"
    "例如：「帮我把音量调大两格，然后打开记事本写一段待办」\n"
    "「截个图，打开浏览器搜一下今天天气」\n"
    "任何上面的规则没覆盖、又说不清怎么做的指令，都会自动交给大模型处理。\n"
)


class VoiceControlApp:
    def __init__(self, root):
        self.root = root
        self.cfg = config_mod.load_config()
        self.listening = False
        self.dry_run = False  # 演练/测试模式：只展示将要执行的动作，不真正执行

        tts.init()
        tts.set_rate(self.cfg.get("speech_rate", 170))
        tts.set_enabled(self.cfg.get("auto_speak", True))

        self._build_ui()
        self.transcript = []  # 最近对话记录（供 HTTP 控制页轮询）
        self.http_port = 0
        self._hidden = False       # 当前主窗口是否隐藏在托盘
        self._tray_icon = None     # pystray.Icon 实例（未启用托盘时为 None）
        self._greet()

    # ---------------- UI ----------------
    def _build_ui(self):
        self.root.title(APP_TITLE)
        self.root.geometry("560x660")
        self.root.minsize(460, 480)

        # 顶部状态栏
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(top, text="🖥 文本控制 Windows", font=("Microsoft YaHei", 13, "bold")).pack(side=tk.LEFT)
        self.speak_btn = ttk.Button(top, text="🔊 开" if self.cfg.get("auto_speak", True) else "🔇 关", width=8,
                                    command=self._toggle_speak)
        self.speak_btn.pack(side=tk.RIGHT, padx=2)
        self.dry_btn = ttk.Button(top, text="🧪演练 关", width=9, command=self._toggle_dry_run)
        self.dry_btn.pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="⚙", width=4, command=self._open_settings).pack(side=tk.RIGHT, padx=2)
        ttk.Button(top, text="?", width=3, command=self._show_help).pack(side=tk.RIGHT, padx=2)
        self.net_btn = ttk.Button(top, text="🌐", width=4, command=self._show_http_info)
        self.net_btn.pack(side=tk.RIGHT, padx=2)

        # 对话区
        self.chat = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, state=tk.DISABLED,
                                              font=("Microsoft YaHei", 10), padx=8, pady=8)
        self.chat.tag_config("user", foreground="#1a73e8", font=("Microsoft YaHei", 10, "bold"))
        self.chat.tag_config("bot", foreground="#0b8043", font=("Microsoft YaHei", 10, "bold"))
        self.chat.tag_config("log", foreground="#888888", font=("Microsoft YaHei", 9))
        self.chat.tag_config("err", foreground="#d93025", font=("Microsoft YaHei", 10, "bold"))
        self.chat.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        # 局域网控制状态栏
        self.status = ttk.Label(self.root, text="", font=("Microsoft YaHei", 9), foreground="#666666")
        self.status.pack(fill=tk.X, padx=8, pady=(0, 2))

        # 底部输入区
        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=8, pady=8)
        self.entry = ttk.Entry(bottom, font=("Microsoft YaHei", 11))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=6)
        self.entry.bind("<Return>", lambda e: self._on_send())
        self.mic_btn = ttk.Button(bottom, text="🎤", width=4, command=self._toggle_mic)
        self.mic_btn.pack(side=tk.LEFT, padx=4)
        ttk.Button(bottom, text="发送", width=6, command=self._on_send).pack(side=tk.LEFT, padx=2)
        ttk.Button(bottom, text="清空", width=5, command=self._clear_chat).pack(side=tk.LEFT, padx=2)

    def _greet(self):
        self._append("bot", "你好，我是语音控制台。输入指令即可控制这台电脑；"
                             "简单指令直接执行，复杂指令会交给大模型分析。点「?」查看支持哪些指令。"
                             "测指令可先开「🧪演练」模式，只解析不执行。")
        if not self.cfg.get("api_key"):
            self._append("log", "提示：尚未配置大模型 API Key，复杂指令暂不可用。点「⚙」填写后即可使用。")

    # ---------------- 输出辅助 ----------------
    def _append(self, who, text):
        self.chat.configure(state=tk.NORMAL)
        prefix = {"user": "你：\n", "bot": "助手：\n", "log": "· ", "err": "⚠ "}.get(who, "")
        self.chat.insert(tk.END, prefix, who)
        self.chat.insert(tk.END, text + "\n\n")
        self.chat.configure(state=tk.DISABLED)
        self.chat.see(tk.END)
        # 记录最近对话，供局域网控制页轮询展示
        label = {"user": "你：", "bot": "助手：", "log": "· ", "err": "⚠ "}.get(who, "")
        self.transcript.append(label + text)
        if len(self.transcript) > 200:
            self.transcript = self.transcript[-200:]

    def _log_step(self, msg):
        self.root.after(0, lambda: self._append("log", msg))

    def _clear_chat(self):
        self.chat.configure(state=tk.NORMAL)
        self.chat.delete("1.0", tk.END)
        self.chat.configure(state=tk.DISABLED)

    # ---------------- 指令处理 ----------------
    def _on_send(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, tk.END)
        self._append("user", text)
        threading.Thread(target=self._run_command, args=(text,), daemon=True).start()

    def submit_command(self, text):
        """供 HTTP 局域网控制调用：与“发送”等价，但指令来自外部而非输入框。

        包含一条安全门禁：当 http_control.allow_destructive=false（默认）时，
        拒绝关机/重启/睡眠等危险指令通过局域网触发，避免被误用。

        注意：HTTP 服务运行在独立线程，而 tkinter 只能在主线程操作；
        因此把“记录指令 + 调度执行”整体切回主线程，避免跨线程调用导致
        界面无响应或指令静默丢失（与界面「发送」走同一条主线程路径）。
        """
        text = (text or "").strip()
        if not text:
            return
        self.root.after(0, lambda: self._dispatch_external(text))

    def _dispatch_external(self, text):
        """在主线程执行来自 HTTP/外部的命令（与 _on_send 等价，但不读输入框）。"""
        self._append("user", text)
        hcfg = self.cfg.get("http_control", {}) or {}
        if not hcfg.get("allow_destructive", False):
            try:
                m = simple.match_simple(text)
            except Exception:  # noqa: BLE001
                m = None
            if isinstance(m, tuple) and m[0] == "steps":
                if any(s.get("action") in actions.DESTRUCTIVE_ACTIONS for s in (m[1] or [])):
                    self._append("log", "（局域网指令）该操作较危险，已在 http_control.allow_destructive=false 时被阻止。"
                                        "如需允许，请在设置或 config.json 中将其设为 true。")
                    return
        threading.Thread(target=self._run_command, args=(text,), daemon=True).start()

    def get_recent_log(self):
        """返回最近若干条对话记录（供 HTTP /api/log 轮询）。"""
        return self.transcript[-50:]

    def _run_command(self, text):
        try:
            self._run_command_inner(text)
        except Exception as e:  # noqa: BLE001
            # 把后台线程里的异常暴露到界面，避免“没反应”却查不到原因
            err = f"执行指令「{text}」时出错：{e}"
            self.root.after(0, lambda: self._append("err", err))
            self._speak("抱歉，执行出错了：" + str(e))

    def _run_command_inner(self, text):
        match = simple.match_simple(text)

        # 1) 直接回答类（时间/日期）
        if isinstance(match, tuple) and match[0] == "answer":
            self._append("bot", match[1])
            self._speak(match[1])
            return

        # 2) 本程序自身的语义动作（发送/清空/演练/语音/设置/帮助等）-> 直接执行
        if isinstance(match, tuple) and match[0] == "app_action":
            action_key, explanation = match[1], match[2]
            self._append("bot", "直接执行：" + explanation)
            self._do_app_action(action_key)
            self._speak(explanation)
            return

        # 3) 简单指令 -> 直接执行
        if isinstance(match, tuple) and match[0] == "steps":
            steps, explanation = match[1], match[2]
            self._append("bot", "直接执行：" + explanation)
            if self._need_confirm(steps) and not self._confirm_destructive():
                self._append("log", "已取消危险操作。")
                return
            results = actions.execute_steps(steps, self._log_step, dry_run=self.dry_run)
            if self.dry_run:
                self._append("log", "（演练模式：以上动作未真正执行）")
            self._finish_speak(steps, explanation)
            return

        # 4) 复杂指令 -> 大模型分析
        if not self.cfg.get("api_key"):
            msg = ("这条指令暂不支持“直接执行”，且未配置大模型 API Key，无法分析。\n"
                   "你可以：① 点「⚙」填写 Key 以启用复杂指令；\n"
                   "② 改用直接指令，如：打开记事本 / 截图 / 锁屏 / 最小化窗口 / 点击窗口菜单 / 窗口。点「?」查看全部。")
            self.root.after(0, lambda: self._append("log", msg))
            self._speak("这条指令需要大模型，但还没配置密钥。")
            return
        self._append("bot", "正在用大模型分析指令…")
        try:
            plan = llm.ask_plan(text, self.cfg)
        except Exception as e:  # noqa: BLE001
            err = f"大模型分析失败：{e}"
            self.root.after(0, lambda: self._append("err", err))
            self._speak("抱歉，大模型分析失败：" + str(e))
            return

        steps = plan.get("steps", [])
        explanation = plan.get("explanation", "（无说明）")
        self.root.after(0, lambda: self._append("bot", "分析完毕：" + explanation))
        if self._need_confirm(steps) and not self._confirm_destructive():
            self.root.after(0, lambda: self._append("log", "已取消危险操作。"))
            return
        actions.execute_steps(steps, self._log_step, dry_run=self.dry_run)
        if self.dry_run:
            self.root.after(0, lambda: self._append("log", "（演练模式：以上动作未真正执行）"))
        self.root.after(0, lambda: self._finish_speak(steps, explanation))

    def _do_app_action(self, action_key):
        """执行本程序自身的语义动作（来自 simple.APP_COMMANDS）。"""
        handlers = {
            "send": self._on_send,
            "clear": self._clear_chat,
            "dry_run": self._toggle_dry_run,
            "speak": self._toggle_speak,
            "settings": self._open_settings,
            "help": self._show_help,
            "mic": self._toggle_mic,
        }
        desc = {
            "send": "发送当前输入框内容",
            "clear": "清空对话记录",
            "dry_run": "切换演练模式",
            "speak": "开关语音播报",
            "settings": "打开设置面板",
            "help": "打开使用帮助",
            "mic": "开关语音输入",
        }
        if action_key not in handlers:
            self._append("log", f"未知的应用动作：{action_key}")
            return
        if self.dry_run:
            self._append("log", f"【演练】将执行应用动作：{desc.get(action_key, action_key)}")
            return
        if action_key == "send":
            text = self.entry.get().strip()
            if not text:
                self._append("log", "输入框为空，没有内容可发送。可先在输入框里输入指令，再说「发送」。")
                return
            from simple import APP_COMMANDS
            if text in APP_COMMANDS:
                self._append("log", f"输入框里只有动作词「{text}」，没有要发送的内容。请先输入真正的指令，再说「发送」。")
                return
            self.entry.delete(0, tk.END)
            self._append("user", text)
            threading.Thread(target=self._run_command, args=(text,), daemon=True).start()
            return
        handlers[action_key]()

    def _finish_speak(self, steps, explanation):
        # 若步骤里已包含 say（让电脑说话），就不再重复播报
        has_say = any(s.get("action") == "say" for s in steps)
        if not has_say:
            self._speak(explanation)

    def _need_confirm(self, steps):
        if not self.cfg.get("confirm_destructive", True):
            return False
        return any(s.get("action") in actions.DESTRUCTIVE_ACTIONS for s in (steps or []))

    def _confirm_destructive(self):
        return messagebox.askyesno("危险操作确认", "该指令包含关机/重启/睡眠等危险操作，确定要继续吗？")

    # ---------------- 语音 ----------------
    def _speak(self, text):
        tts.speak(text)

    def _toggle_speak(self):
        cur = self.cfg.get("auto_speak", True)
        new = not cur
        self.cfg["auto_speak"] = new
        config_mod.save_config(self.cfg)
        tts.set_enabled(new)
        self.speak_btn.configure(text="🔊 开" if new else "🔇 关")
        self._append("log", "语音播报已" + ("开启" if new else "关闭"))

    def _toggle_dry_run(self):
        self.dry_run = not self.dry_run
        self.dry_btn.configure(text="🧪演练 开" if self.dry_run else "🧪演练 关")
        self._append("log", "演练模式已" + ("开启（指令只解析不执行）" if self.dry_run else "关闭"))

    def _toggle_mic(self):
        if self.listening:
            self.listening = False
            self.mic_btn.configure(text="🎤")
            return
        if not stt.microphone_available():
            self._append("err", stt.unavailable_reason())
            return
        self.listening = True
        self.mic_btn.configure(text="🎙…")
        threading.Thread(target=self._listen, daemon=True).start()

    def _listen(self):
        lang = self.cfg.get("language", "zh-CN")
        result = stt.listen_once(language=lang)
        self.listening = False
        self.root.after(0, lambda: self.mic_btn.configure(text="🎤"))
        if result is None:
            self.root.after(0, lambda: self._append("err", "语音识别服务不可用（请检查网络）。"))
        elif result == "":
            self.root.after(0, lambda: self._append("log", "没听清，请再试一次。"))
        else:
            self.root.after(0, lambda: self._use_voice_text(result))

    def _use_voice_text(self, text):
        self.entry.delete(0, tk.END)
        self.entry.insert(0, text)
        self._on_send()

    # ---------------- 设置 / 帮助 ----------------
    def _open_settings(self):
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.geometry("440x340")
        win.resizable(False, False)
        win.transient(self.root)
        win.gfile = None

        rows = [
            ("接口地址 endpoint", "endpoint"),
            ("API Key", "api_key"),
            ("模型 model", "model"),
            ("语音识别语言", "language"),
        ]
        vars_ = {}
        for i, (label, key) in enumerate(rows):
            ttk.Label(win, text=label).grid(row=i, column=0, sticky=tk.W, padx=10, pady=8)
            var = tk.StringVar(value=self.cfg.get(key, ""))
            vars_[key] = var
            ent = ttk.Entry(win, textvariable=var, width=34, show=("*" if key == "api_key" else ""))
            ent.grid(row=i, column=1, padx=6, pady=8)

        # 语音语速
        ttk.Label(win, text="语音语速").grid(row=4, column=0, sticky=tk.W, padx=10, pady=8)
        rate_var = tk.IntVar(value=self.cfg.get("speech_rate", 170))
        scale = ttk.Scale(win, from_=100, to=260, variable=rate_var, orient=tk.HORIZONTAL)
        scale.grid(row=4, column=1, padx=6, pady=8, sticky=tk.EW)
        rate_label = ttk.Label(win, text=str(rate_var.get()))
        rate_label.grid(row=4, column=2, padx=4)

        def _update_rate_label(*_):
            rate_label.configure(text=str(rate_var.get()))

        rate_var.trace_add("write", _update_rate_label)

        # 开关
        confirm_var = tk.BooleanVar(value=self.cfg.get("confirm_destructive", True))
        ttk.Checkbutton(win, text="危险操作前二次确认", variable=confirm_var).grid(
            row=5, column=0, columnspan=2, sticky=tk.W, padx=10, pady=4)

        def _save():
            for key, var in vars_.items():
                self.cfg[key] = var.get().strip()
            self.cfg["speech_rate"] = int(rate_var.get())
            self.cfg["confirm_destructive"] = confirm_var.get()
            config_mod.save_config(self.cfg)
            tts.set_rate(self.cfg["speech_rate"])
            tts.set_enabled(self.cfg.get("auto_speak", True))
            win.destroy()
            self._append("log", "设置已保存。")

        ttk.Button(win, text="保存", command=_save).grid(row=6, column=0, padx=10, pady=14, sticky=tk.W)
        ttk.Button(win, text="取消", command=win.destroy).grid(row=6, column=1, padx=6, pady=14, sticky=tk.W)

    def _show_help(self):
        messagebox.showinfo("使用帮助", HELP_TEXT)

    # ---------------- 局域网控制 ----------------
    def show_http_url(self, lan_ip, port):
        self.http_port = port
        msg = (f"🌐 局域网控制已开启：http://{lan_ip}:{port}  "
               f"（手机或其它电脑浏览器打开即可发指令；本机也可访问 http://127.0.0.1:{port}；点「🌐」查看接口调用方式）")
        self.status.configure(text=msg)
        self._append("log", msg)

    def _show_http_info(self):
        """弹出 HTTP 接口调用说明（含 curl / Python 示例、复制按钮）。"""
        if not self.http_port:
            self._append("log", "局域网控制服务尚未启动（检查 config.json 中 http_control.enabled）。")
            return
        from http_control import api_help_text, get_lan_ip
        lan = get_lan_ip()
        txt = api_help_text(lan, self.http_port)

        win = tk.Toplevel(self.root)
        win.title("🌐 局域网控制 · HTTP 接口")
        win.geometry("660x540")
        win.resizable(True, True)
        win.transient(self.root)

        txt_widget = tk.Text(win, wrap=tk.WORD, font=("Consolas", "Courier New", 11), padx=10, pady=10)
        txt_widget.insert("1.0", txt)
        txt_widget.configure(state=tk.DISABLED)
        txt_widget.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))

        def copy():
            win.clipboard_clear()
            win.clipboard_append(txt)
            self._append("log", "HTTP 接口说明已复制到剪贴板。")

        def open_page():
            import webbrowser
            webbrowser.open(f"http://127.0.0.1:{self.http_port}/")

        bar = ttk.Frame(win)
        bar.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bar, text="📋 复制", command=copy).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="🌐 在浏览器打开控制页", command=open_page).pack(side=tk.LEFT, padx=4)
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side=tk.RIGHT, padx=4)

    def _open_control_page(self):
        if not self.http_port:
            self._append("log", "局域网控制服务尚未启动（检查 config.json 中 http_control.enabled）。")
            return
        import webbrowser
        webbrowser.open(f"http://127.0.0.1:{self.http_port}/")

    # ---------------- 托盘 ----------------
    def hide_to_tray(self):
        """最小化到托盘（隐藏主窗口）。"""
        self.root.withdraw()
        self._hidden = True

    def show_from_tray(self):
        """从托盘恢复主窗口。"""
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        # 稍后取消置顶，避免一直压在最上层
        self.root.after(150, lambda: self.root.attributes("-topmost", False))
        try:
            self.root.focus_force()
        except Exception:  # noqa: BLE001
            pass
        self._hidden = False

    def toggle_tray(self):
        """左键单击托盘图标：在“显示/隐藏”之间切换。"""
        if self._hidden:
            self.show_from_tray()
        else:
            self.hide_to_tray()

    def quit_app(self):
        """真正退出程序（由托盘菜单“退出”调用）。"""
        try:
            if self._tray_icon is not None:
                self._tray_icon.stop()
        except Exception:  # noqa: BLE001
            pass
        self.root.destroy()


def _fatal_error(e):
    """把启动期的致命错误暴露出来（pythonw 下没有控制台，否则会被静默吞掉）。"""
    import time as _time
    import traceback as _tb
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "voice_control_error.log")
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("==== 启动失败 %s ====\n" % _time.strftime("%Y-%m-%d %H:%M:%S"))
            f.write(_tb.format_exc() + "\n")
    except Exception:  # noqa: BLE001
        pass
    try:
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(
            "语音控制台启动失败",
            "程序启动出错：\n\n" + str(e) + "\n\n详细日志已写入：\n" + log_path,
        )
        r.destroy()
    except Exception:  # noqa: BLE001
        pass


_SINGLE_INSTANCE_MUTEX = None
_SINGLE_INSTANCE_NAME = "SWYS_VoiceControl_SingleInstance"


def _acquire_single_instance():
    """创建进程级互斥体，保证同时只有一个实例运行。

    返回 True 表示本进程是首个实例（应正常启动）；
    返回 False 表示已有实例在运行（调用方应唤醒旧实例并退出）。
    非 Windows 平台直接返回 True（不做限制）。
    """
    global _SINGLE_INSTANCE_MUTEX
    if not hasattr(ctypes, "windll"):
        return True
    try:
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.GetLastError.argtypes = []
        kernel32.GetLastError.restype = ctypes.c_uint
        mutex = kernel32.CreateMutexW(None, 0, _SINGLE_INSTANCE_NAME)
        if kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            return False
        # 持有到进程退出：不关闭句柄，避免被垃圾回收提前释放
        _SINGLE_INSTANCE_MUTEX = mutex
        return True
    except Exception:  # noqa: BLE001
        return True


def wake_existing_instance():
    """唤醒已在运行的实例，避免重复双击只多开窗口却看不到。

    优先走本机 HTTP /api/wake（调用程序自身的 show_from_tray，能正确处理
    收进托盘的隐藏窗口）；HTTP 未启用或不可达时，用 win32gui 把窗口置前。
    返回是否成功发出唤醒信号。
    """
    # 1) 走本机 HTTP 服务（最可靠，能正确恢复托盘隐藏窗口）
    try:
        import urllib.request
        port = 8765
        try:
            cfg = config_mod.load_config() or {}
            hcfg = cfg.get("http_control", {}) or {}
            port = int(hcfg.get("port", 8765))
        except Exception:  # noqa: BLE001
            pass
        url = "http://127.0.0.1:%d/api/wake" % port
        with urllib.request.urlopen(url, timeout=2.0) as _resp:
            _resp.read()
        return True
    except Exception:  # noqa: BLE001
        pass
    # 2) 兜底：用 win32gui 把已有窗口置前（处理 HTTP 未启用的情况）
    try:
        import win32gui
        import win32con
        hwnd = win32gui.FindWindow(None, APP_TITLE)
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def main():
    # 单实例保护：已有实例运行时，唤醒旧窗口/托盘就退出，不创建新窗口
    if not _acquire_single_instance():
        try:
            wake_existing_instance()
        except Exception:  # noqa: BLE001
            pass
        return
    try:
        _run_main()
    except Exception as e:  # noqa: BLE001
        _fatal_error(e)
        sys.exit(1)


def _run_main():
    root = tk.Tk()
    try:
        # Windows 下用系统主题更协调
        from tkinter import ttk
    except Exception:
        pass
    app = VoiceControlApp(root)

    # 启动 HTTP 局域网控制服务（配置 http_control.enabled 控制，默认开启）
    try:
        from http_control import start_server, get_lan_ip
        hcfg = app.cfg.get("http_control", {}) or {}
        if hcfg.get("enabled", True):
            port = int(hcfg.get("port", 8765))
            start_server(app, host="0.0.0.0", port=port)
            lan = get_lan_ip()
            app.show_http_url(lan, port)
    except Exception as e:  # noqa: BLE001
        app._append("err", f"HTTP 局域网控制服务启动失败：{e}")

    # 启动系统托盘（托盘图标 + 点击打开/退出）。依赖 pystray；未安装则静默降级。
    try:
        import tray as tray_mod
        tray_cfg = app.cfg.get("tray", {}) or {}
        if tray_cfg.get("enabled", True) and tray_mod.TRAY_AVAILABLE:
            def _toggle():
                app.root.after(0, app.toggle_tray)

            def _show():
                app.root.after(0, app.show_from_tray)

            def _quit():
                app.root.after(0, app.quit_app)

            app._tray_icon = tray_mod.start_tray(_toggle, _show, _quit)
            # 点「×」不再直接退出，而是最小化到托盘（真正退出走托盘菜单）
            root.protocol("WM_DELETE_WINDOW", lambda: app.root.after(0, app.hide_to_tray))
            if tray_cfg.get("start_minimized", False):
                app.hide_to_tray()
            app._append("log", "已启用系统托盘：左键点图标可显示/隐藏窗口，右键菜单可退出。")

            # 启动后给个气泡提示，确保“确实启动了”有明确反馈
            def _notify():
                try:
                    if app._tray_icon is not None:
                        app._tray_icon.notify("语音控制台已启动", "点击托盘图标可显示/隐藏窗口")
                except Exception:  # noqa: BLE001
                    pass
            threading.Timer(1.5, _notify).start()
        elif tray_cfg.get("enabled", True) and not tray_mod.TRAY_AVAILABLE:
            app._append("log", "未安装 pystray，托盘图标不可用（pip install pystray 后启用）；点「×」将直接退出。")
    except Exception as e:  # noqa: BLE001
        app._append("err", f"托盘图标启动失败：{e}（程序照常运行）")

    root.mainloop()


def cli_test(text):
    """命令行测试模式：只解析指令并打印将要执行的动作步骤，不真正执行。"""
    import json as _json
    cfg = config_mod.load_config()
    print(f"\n[测试指令] {text}\n" + "-" * 40)

    match = simple.match_simple(text)
    steps = None
    source = None
    if isinstance(match, tuple) and match[0] == "answer":
        print(f"[直接回答] {match[1]}")
        return
    if isinstance(match, tuple) and match[0] == "app_action":
        _, action_key, explanation = match
        print(f"[应用动作] {explanation}（action_key={action_key}）")
        return
    if isinstance(match, tuple) and match[0] == "steps":
        steps, explanation = match[1], match[2]
        source, src_label = steps, "简单指令匹配"
    else:
        if not cfg.get("api_key"):
            print("[复杂指令] 未配置大模型 API Key，无法分析。点「⚙」填写后重试，或在 GUI 中测试。")
            return
        print("[复杂指令] 调用大模型分析中…")
        try:
            plan = llm.ask_plan(text, cfg)
        except Exception as e:  # noqa: BLE001
            print(f"[大模型分析失败] {e}")
            return
        steps = plan.get("steps", [])
        explanation = plan.get("explanation", "")
        source, src_label = steps, "大模型分析"

    print(f"[来源] {src_label}")
    if isinstance(steps, list) and steps and isinstance(steps[0], dict):
        print(f"[说明] {explanation}\n[动作步骤]")
        for i, s in enumerate(steps, 1):
            print(f"  {i}. {s.get('action')}  {_json.dumps(s.get('params', {}), ensure_ascii=False)}")
    else:
        print(f"[解析结果] {steps}")


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "--test":
        # python main.py --test "打开记事本"
        cli_test(" ".join(sys.argv[2:]))
    else:
        main()
