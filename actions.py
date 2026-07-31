"""
Windows 动作执行引擎。
简单指令与 LLM 指令最终都会变成一组"动作步骤"，由这里统一执行。
新增动作：在 ACTION_HANDLERS 中注册一个处理函数即可。
"""
import ctypes
import os
import subprocess
import time
import webbrowser

import winctl
import pyperclip

# 危险动作：执行前需要用户二次确认
DESTRUCTIVE_ACTIONS = {"shutdown", "restart", "sleep"}

_SELF_PID = os.getpid()

# 判定控件/窗口是否属于“我写的这个程序本身”：即本进程窗口，以及本程序的窗口标题。
# 注意：WorkBuddy 宿主窗口不算在内，它是外部应用，应当可以被操作。
_SELF_TITLE_KEYWORDS = ("语音控制台", "文本控制 Windows")


def _is_self_window(control):
    """判断控件/窗口是否属于本程序自身（我写的这个程序），应排除。"""
    try:
        if getattr(control, "ProcessId", None) == _SELF_PID:
            return True
    except Exception:  # noqa: BLE001
        pass
    try:
        name = (control.Name or "").strip()
        if name and any(kw in name for kw in _SELF_TITLE_KEYWORDS):
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _list_visible_windows(auto, exclude_handles=None):
    """枚举桌面上除本程序外的可见顶层窗口。
    返回 [(control, rect, name, handle, pid, pname)]，pname 为进程映像名。
    注意：枚举基于 Win32 EnumWindows（完整，覆盖所有顶层窗口，含 UWP/Shell 窗口），
    而不是 uiautomation 根的子树——后者常漏掉大量窗口，导致“可见可说”只能搜到少数窗口。
    对每个窗口再用 auto.ControlFromHandle 取 UIA 控件树用于按名搜索。
    """
    out = []
    exclude_handles = set(exclude_handles or [])
    try:
        wins = winctl.enum_visible_windows(exclude_pid=_SELF_PID)
    except Exception:  # noqa: BLE001
        wins = []
    for hwnd, pid, pname, title, (l, t, r, b) in wins:
        try:
            if hwnd in exclude_handles:
                continue
            # 按标题排除"自己人"窗口：本程序 GUI 以及浏览器里打开的局域网控制页。
            # 控制页会把历史指令渲染成「你：xxx」文本节点，不排除的话指令会
            # 匹配到自己命令的回声（静态文本还点不动，Invoke 报"事件无订户"）。
            if title and any(kw in title for kw in _SELF_TITLE_KEYWORDS):
                continue
            try:
                ctrl = auto.ControlFromHandle(hwnd)
            except Exception:  # noqa: BLE001
                ctrl = None
            if ctrl is None:
                # 取不到 UIA 控件就不纳入“按名搜索”（但仍可能在 OCR 全屏里命中）
                continue
            try:
                name = (ctrl.Name or "").strip() or title or "可见窗口"
            except Exception:  # noqa: BLE001
                name = title or "可见窗口"
            out.append((ctrl, (l, t, r, b), name, hwnd, pid, pname))
        except Exception:  # noqa: BLE001
            continue
    return out

# 常见应用名 -> 可直接 start 的名称
APP_ALIASES = {
    "记事本": "notepad",
    "notepad": "notepad",
    "计算器": "calc",
    "calc": "calc",
    "calculator": "calc",
    "画图": "mspaint",
    "paint": "mspaint",
    "命令提示符": "cmd",
    "命令符": "cmd",
    "cmd": "cmd",
    "终端": "wt",
    "terminal": "wt",
    "windows terminal": "wt",
    "文件资源管理器": "explorer",
    "文件管理器": "explorer",
    "资源管理器": "explorer",
    "explorer": "explorer",
    "我的电脑": "explorer",
    "此电脑": "explorer",
    "控制面板": "control",
    "设置": "ms-settings:",
    "任务管理器": "taskmgr",
    "浏览器": "chrome",
    "chrome": "chrome",
    "谷歌浏览器": "chrome",
    "edge": "msedge",
    "微软浏览器": "msedge",
    "微信": "wechat",
    "wechat": "wechat",
}


def _default_screenshot_path():
    base = os.path.join(os.path.expanduser("~"), "Pictures", "VoiceControl")
    os.makedirs(base, exist_ok=True)
    return os.path.join(base, f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png")


def _open_app(params):
    name = (params.get("name") or params.get("app") or "").strip()
    if not name:
        return "未指定应用名"
    exe = APP_ALIASES.get(name.lower(), name)
    try:
        # Windows 的 start 命令可以靠应用名/协议启动
        subprocess.Popen(f'start "" "{exe}"', shell=True)
        return f"已打开：{name}"
    except Exception as e:  # noqa: BLE001
        return f"打开 {name} 失败：{e}"


def _open_file(params):
    path = (params.get("path") or "").strip()
    if not path:
        return "未指定路径"
    try:
        os.startfile(path)
        return f"已打开：{path}"
    except Exception as e:  # noqa: BLE001
        return f"打开 {path} 失败：{e}"


def _open_url(params):
    url = (params.get("url") or "").strip()
    if not url:
        return "未指定网址"
    if not url.startswith("http"):
        url = "https://" + url
    try:
        webbrowser.open(url)
        return f"已打开网页：{url}"
    except Exception as e:  # noqa: BLE001
        return f"打开网页失败：{e}"


def _type_text(params):
    text = params.get("text", "")
    if not text:
        return "没有可输入的文字"
    try:
        pyperclip.copy(text)
        time.sleep(0.12)
        winctl.hotkey("ctrl", "v")
        return f"已输入：{text[:50]}"
    except Exception as e:  # noqa: BLE001
        return f"输入失败：{e}"


def _press_keys(params):
    keys = params.get("keys", [])
    if isinstance(keys, str):
        keys = [k.strip() for k in keys.replace("+", " ").split() if k.strip()]
    if not keys:
        return "未指定按键"
    try:
        winctl.hotkey(*[k.lower() for k in keys])
        return f"已按下：{'+'.join(keys)}"
    except Exception as e:  # noqa: BLE001
        return f"按键失败：{e}"


def _click(params):
    x, y = params.get("x"), params.get("y")
    try:
        if x is not None and y is not None:
            winctl.click(int(x), int(y))
            return f"已点击 ({x}, {y})"
        winctl.click()  # 未给坐标 -> 点击鼠标当前位置
        return "已点击（鼠标当前位置）"
    except Exception as e:  # noqa: BLE001
        return f"点击失败：{e}"


def _double_click(params):
    x, y = params.get("x"), params.get("y")
    try:
        if x is not None and y is not None:
            winctl.doubleClick(int(x), int(y))
            return f"已双击 ({x}, {y})"
        winctl.doubleClick()
        return "已双击（鼠标当前位置）"
    except Exception as e:  # noqa: BLE001
        return f"双击失败：{e}"


def _right_click(params):
    x, y = params.get("x"), params.get("y")
    try:
        if x is not None and y is not None:
            winctl.rightClick(int(x), int(y))
            return f"已右键点击 ({x}, {y})"
        winctl.rightClick()
        return "已右键点击（鼠标当前位置）"
    except Exception as e:  # noqa: BLE001
        return f"右键点击失败：{e}"


def _move_mouse(params):
    x, y = params.get("x"), params.get("y")
    if x is None or y is None:
        return "move_mouse 需要 x, y 坐标"
    try:
        winctl.moveTo(int(x), int(y))
        return f"已移动鼠标到 ({x}, {y})"
    except Exception as e:  # noqa: BLE001
        return f"移动失败：{e}"


def _scroll(params):
    amount = int(params.get("amount", 0))
    try:
        winctl.scroll(amount)
        return f"已滚动 {amount}"
    except Exception as e:  # noqa: BLE001
        return f"滚动失败：{e}"


def _volume_up(params):
    winctl.press("volumeup")
    return "音量 +1"


def _volume_down(params):
    winctl.press("volumedown")
    return "音量 -1"


def _volume_mute(params):
    winctl.press("volumemute")
    return "已切换静音"


def _screenshot(params):
    path = params.get("path") or _default_screenshot_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        winctl.screenshot(path)
        return f"截图已保存：{path}"
    except Exception as e:  # noqa: BLE001
        return f"截图失败：{e}"


def _lock_screen(params):
    try:
        ctypes.windll.user32.LockWorkStation()
        return "已锁屏"
    except Exception as e:  # noqa: BLE001
        return f"锁屏失败：{e}"


def _minimize_active(params):
    winctl.hotkey("win", "down")
    return "已最小化当前窗口"


def _maximize_active(params):
    winctl.hotkey("win", "up")
    return "已最大化当前窗口"


def _close_active(params):
    winctl.hotkey("alt", "f4")
    return "已关闭当前窗口"


def _switch_window(params):
    winctl.hotkey("alt", "tab")
    return "已切换窗口"


def _restore_active(params):
    # Win+↓：最大化时还原为窗口，普通窗口时最小化；这里用作“还原窗口”
    winctl.hotkey("win", "down")
    return "已还原窗口"


def _click_by_name_ocr(params, preview=False):
    """
    OCR 模式：截取当前窗口画面，识别屏上真实文字，按坐标点击。
    这是真正的“可见可说”——不依赖控件是否暴露可访问名称，
    适合 tkinter/ttk 自绘按钮等 UIA 读不到名字的程序。
    """
    name = (params.get("name") or "").strip()
    double = bool(params.get("double"))
    right = bool(params.get("right"))
    if not name:
        return "未指定要点击的控件名称"
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
        # 截图/点击走统一的 winctl（自带 ctypes 兜底，无需 pyautogui）
        import winctl  # noqa: F401
        # 若 tesseract 不在 PATH，按此优先级定位引擎：
        #   1) config.json 的 tesseract_path
        #   2) 本项目自带的便携版 tesseract_portable/tesseract.exe（免安装、免管理员）
        try:
            import json as _json, os as _os
            _here = _os.path.dirname(_os.path.abspath(__file__))
            _tp = None
            _cfg_file = _os.path.join(_here, "config.json")
            if _os.path.exists(_cfg_file):
                with open(_cfg_file, encoding="utf-8") as _f:
                    _cfg = _json.load(_f)
                _tp = _cfg.get("tesseract_path")
            if not (_tp and _os.path.exists(_tp)):
                _portable = _os.path.join(_here, "tesseract_portable", "tesseract.exe")
                if _os.path.exists(_portable):
                    _tp = _portable
            if _tp and _os.path.exists(_tp):
                pytesseract.pytesseract.tesseract_cmd = _tp
        except Exception:  # noqa: BLE001
            pass
    except Exception as e:  # noqa: BLE001
        missing = []
        try:
            import pytesseract  # noqa: F401
        except Exception:
            missing.append("pytesseract")
        try:
            from PIL import Image  # noqa: F401
        except Exception:
            missing.append("Pillow")
        tip = "、".join(missing) or "Tesseract-OCR 引擎"
        return (f"缺少 OCR 所需 Python 依赖（{tip}）。\n"
                f"请在本项目使用的 Python 下运行：\n"
                f"  pip install pytesseract Pillow\n"
                f"另外 OCR 还需要 Tesseract-OCR 引擎本体（含中文包 chi_sim）：\n"
                f"  - 运行本目录下的 install_tesseract.bat（以管理员身份）\n"
                f"  - 或在 config.json 用 tesseract_path 指向 tesseract.exe")
    try:
        # 整屏 OCR：截取整个虚拟屏幕（含所有显示器），统一用虚拟屏幕坐标系，
        # 规避“按单窗口区域截图”在多屏 / DPI 缩放下坐标错位、从而扫不到目标的问题。
        try:
            img, oleft, otop = winctl.screenshot_virtual()
        except Exception as e:  # noqa: BLE001
            return f"OCR 截图失败：{e}"

        # 排除“本程序自身”窗口：拿到自身进程所有可见顶级窗口矩形，
        # 命中落在其内部的文字不点击（只操作程序外的窗口）。WorkBuddy 等宿主窗口不排除。
        self_rects = []
        try:
            self_rects = winctl._top_windows_by_pid(_SELF_PID)
        except Exception:  # noqa: BLE001
            pass

        # 诊断：打印整屏 OCR 扫描覆盖到的应用（进程名 + 窗口标题）
        _covered = []
        try:
            _covered = winctl.enum_visible_windows(exclude_pid=_SELF_PID)
            if _covered:
                _cov = "\n".join(f"  · 进程 {pn or '?'} | 窗口「{tt}」" for _h, _pid, pn, tt, _rc in _covered)
                print(f"[OCR 扫描覆盖窗口] 共 {len(_covered)} 个：\n{_cov}")
        except Exception:  # noqa: BLE001
            pass

        def _score(nm, tx):
            # 归一化（忽略大小写与首尾空格）后计算匹配质量
            nn = nm.casefold()
            tt = tx.casefold()
            if not nn or not tt:
                return 0
            if tt == nn:
                return 100                                   # 完全相等 —— 最优先
            if nn in tt:
                # 目标词是屏上文字的子串（如「多云」在「多云转晴」里）—— 强匹配
                return 80 - min(30, (len(tt) - len(nn)))
            if tt in nn:
                # 屏上文字只是目标词的片段 —— 弱匹配，过滤掉单字/过短片段，避免误点
                ratio = len(tt) / len(nn)
                if ratio >= 0.6:
                    return 40 + int(30 * ratio)
                return 0
            return 0

        try:
            try:
                data = pytesseract.image_to_data(img, lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
            except Exception:  # noqa: BLE001
                data = pytesseract.image_to_data(img, lang="chi_sim", output_type=pytesseract.Output.DICT)
        except Exception as e:  # noqa: BLE001
            return (f"OCR 识别失败（请确认 Tesseract-OCR 引擎已就位且含 chi_sim）：{e}\n"
                    f"当前引擎路径：{getattr(pytesseract.pytesseract, 'tesseract_cmd', '默认使用 PATH')}")

        # DPI 换算：ImageGrab 截的是物理像素，而 GetSystemMetrics/SetCursorPos 用逻辑像素。
        # 按“截图尺寸 / 虚拟屏幕逻辑尺寸”求得缩放比，把图像像素坐标换算回逻辑屏幕坐标。
        try:
            _vx, _vy, _vw, _vh = winctl.virtual_screen_rect()
            _scale_x = (img.width / _vw) if _vw else 1.0
            _scale_y = (img.height / _vh) if _vh else 1.0
        except Exception:  # noqa: BLE001
            _scale_x = _scale_y = 1.0

        # 中文常被 OCR 拆成单字（如「发送」→「发」「送」），导致“说发送却点不到”。
        # 把相邻、间距很小的单字 CJK 合并成词再参与匹配，规避此问题。
        def _is_cjk(ch):
            return "一" <= ch <= "鿿"

        entries = []
        buf = []  # 连续单字 CJK 的索引
        toks = data.get("text", [])

        def _flush_buf():
            if len(buf) >= 2:
                ls = [int(data["left"][k]) for k in buf]
                ts = [int(data["top"][k]) for k in buf]
                rs = [int(data["left"][k]) + int(data["width"][k]) for k in buf]
                bs = [int(data["top"][k]) + int(data["height"][k]) for k in buf]
                entries.append({
                    "text": "".join((data["text"][k] or "").strip() for k in buf),
                    "left": min(ls), "top": min(ts),
                    "width": max(rs) - min(ls), "height": max(bs) - min(ts),
                    "conf": sum(float(data["conf"][k]) for k in buf) / len(buf),
                })

        for i, raw in enumerate(toks):
            t = (raw or "").strip()
            if not t:
                _flush_buf(); buf = []
                continue
            if len(t) == 1 and _is_cjk(t[0]):
                if buf:
                    # 与上一个单字横向间距过大则先收尾，避免跨词误合并
                    prev_r = int(data["left"][buf[-1]]) + int(data["width"][buf[-1]])
                    gap = int(data["left"][i]) - prev_r
                    if gap > int(data["height"][i]) * 0.8:
                        _flush_buf(); buf = []
                buf.append(i)
            else:
                _flush_buf(); buf = []
                entries.append({
                    "text": t, "left": int(data["left"][i]), "top": int(data["top"][i]),
                    "width": int(data["width"][i]), "height": int(data["height"][i]),
                    "conf": float(data["conf"][i]),
                })
        _flush_buf()

        best = None
        for e in entries:
            t = (e["text"] or "").strip()
            if not t:
                continue
            sc = _score(name, t)
            if sc <= 0:
                continue
            # 图像像素坐标（用于调试截图绘制）
            px = int(e["left"]) + int(e["width"]) / 2
            py = int(e["top"]) + int(e["height"]) / 2
            # 换算为逻辑屏幕坐标（点击用）
            sx = int(round(oleft + px / _scale_x))
            sy = int(round(otop + py / _scale_y))
            # 命中落在本程序自身窗口内 -> 跳过（只点程序外的目标）
            if self_rects and winctl.point_in_rects(sx, sy, self_rects):
                continue
            try:
                conf = float(e["conf"])
            except Exception:  # noqa: BLE001
                conf = 0
            lx = int(e["left"]); ty = int(e["top"])
            w = int(e["width"]); h = int(e["height"])
            if best is None or sc > best[0] or (sc == best[0] and conf > best[1]):
                best = (sc, conf, sx, sy, t, lx, ty, w, h, px, py)

        if best is None:
            covered_note = ""
            if _covered:
                _cov = "\n".join(f"  · 进程 {pn or '?'} | 窗口「{tt}」" for _h, _pid, pn, tt, _rc in _covered)
                covered_note = f"\n已遍历的可见应用（进程名 | 窗口标题）：\n{_cov}"
            return (f"OCR 已在整屏（所有可见窗口）扫描，未找到文字「{name}」。{covered_note}\n"
                    f"（确认该文字当前可见、未被遮挡；若是图标/图片按钮，OCR 无法识别）")

        sc, conf, ix, iy, t, lx, ty, w, h, px, py = best

        # 生成调试图：在整屏截图上圈出命中文字框 + 点击点十字准星，直接回答“点到了哪里”
        dbg_note = ""
        try:
            import os as _os
            from PIL import ImageDraw
            dbg = img.copy()
            dr = ImageDraw.Draw(dbg)
            # 调试图基于截图本身（图像像素坐标），框/准星都用图像坐标
            bx, by = lx, ty
            dr.rectangle([bx, by, bx + w, by + h], outline="red", width=3)
            cxp, cyp = int(round(px)), int(round(py))
            dr.line([(cxp - 14, cyp), (cxp + 14, cyp)], fill="red", width=2)
            dr.line([(cxp, cyp - 14), (cxp, cyp + 14)], fill="red", width=2)
            _dbg_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "ocr_last_match.png")
            dbg.save(_dbg_path)
            dbg_note = f"\n调试截图已保存：{_dbg_path}"
        except Exception:  # noqa: BLE001
            pass

        # 命中所在窗口标题（诊断用）
        window_name = ""
        try:
            window_name = winctl.window_title_at(ix, iy)
        except Exception:  # noqa: BLE001
            pass

        kind = "精确" if sc >= 100 else ("子串" if sc >= 60 else "片段")
        if preview:
            _act = "双击" if double else ("右键" if right else "单击")
            return (f"【演练】将{_act}「{t}」（{kind}匹配，置信度 {conf:.0f}）\n"
                    f"→ 屏幕坐标 ({ix},{iy})，窗口「{window_name or '可见窗口'}」{dbg_note}")
        try:
            if right:
                winctl.right_click(ix, iy)
            elif double:
                winctl.double_click(ix, iy)
            else:
                winctl.click(ix, iy)
        except Exception as e:  # noqa: BLE001
            return f"OCR 找到「{t}」但点击失败：{e}"
        note = ""
        if kind == "片段":
            note = "\n（注：这是按片段模糊匹配，若点了没反应，可能命中了非按钮的文字标签）"
        _suffix = "（右键）" if right else ("（双击）" if double else "")
        return (f"已点击「{t}」@ 屏幕坐标 ({ix},{iy})，窗口「{window_name or '可见窗口'}」"
                f"（{kind}匹配，置信度 {conf:.0f}）{_suffix}{note}{dbg_note}")
    except Exception as e:  # noqa: BLE001
        return f"OCR 点击失败：{e}"


def _find_desktop_list():
    """定位桌面图标列表控件（回收站/此电脑/网络 等桌面图标都在里面）。
    返回 uiautomation 的 ListControl，找不到返回 None。
    """
    try:
        import uiautomation as auto
    except Exception:  # noqa: BLE001
        return None
    # 方式1：经典路径 Progman -> SHELLDLL_DefView -> List
    try:
        pm = auto.WindowControl(ClassName="Progman")
        if pm.Exists(0):
            sv = pm.WindowControl(ClassName="SHELLDLL_DefView")
            if sv.Exists(0):
                lc = sv.ListControl()
                if lc.Exists(0):
                    return lc
    except Exception:  # noqa: BLE001
        pass
    # 方式2：在桌面根的所有子窗口里找“桌面”面板下的列表控件
    try:
        for w in auto.GetRootControl().GetChildren():
            try:
                if getattr(w, "Name", "") == "桌面" or getattr(w, "ClassName", "") == "Progman":
                    for c in w.GetChildren():
                        try:
                            if c.ControlType == auto.ControlType.ListControl and c.Exists(0):
                                return c
                        except Exception:  # noqa: BLE001
                            pass
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    return None


def _click_desktop_icon(name, preview=False):
    """按名称点击桌面图标（回收站/此电脑/网络 等）。
    返回 None 表示“不适用/未匹配”（调用方应继续走 OCR 兜底）；
    否则返回已处理的结果字符串。
    """
    lc = _find_desktop_list()
    if lc is None:
        return None
    try:
        import uiautomation as auto
    except Exception:  # noqa: BLE001
        return None
    try:
        auto.SetGlobalSearchTimeout(3)
    except Exception:  # noqa: BLE001
        pass
    target = None
    for item in lc.GetChildren():
        try:
            label = (item.Name or "").strip()
        except Exception:  # noqa: BLE001
            label = ""
        if not label:
            continue
        if label == name or name in label or (len(label) >= 2 and label in name):
            target = (item, label)
            break
    if target is None:
        return None
    item, label = target
    if preview:
        return f"【演练】将点击桌面图标：{label}"
    try:
        r = item.BoundingRectangle
        cx = int(r.x + r.width / 2)
        cy = int(r.y + r.height / 2)
        # 桌面图标默认双击打开（单击只是选中），这里双击以真正“打开”
        winctl.double_click(cx, cy)
        return f"已点击桌面图标：{label}（双击打开，屏幕坐标 {cx},{cy}）"
    except Exception as e:  # noqa: BLE001
        try:
            item.Click()
            return f"已点击桌面图标：{label}"
        except Exception as e2:  # noqa: BLE001
            return f"找到桌面图标「{label}」但点击失败：{e2}"


def _click_by_name(params):
    """
    按名称点击屏幕上的控件（按钮/菜单项等）——实现“可见可说”。
    定义：
      前台窗口 = 当前拥有焦点、最前台的那个窗口（你正在交互的）。
    策略：
      1) 前台窗口优先；2) 前台没有则回退到所有“可见”的顶层窗口；
      3) 找不到时打印该窗口实际暴露的控件名，便于定位根因。
    params._preview=True 时只查找、不点击（用于演练模式给出真实反馈）。
    """
    name = (params.get("name") or "").strip()
    preview = bool(params.get("_preview"))
    double = bool(params.get("double"))
    right = bool(params.get("right"))
    if not name:
        return "未指定要点击的控件名称"
    try:
        import uiautomation as auto
    except Exception:  # noqa: BLE001
        return "未安装 uiautomation，无法按名称点击控件。可运行：pip install uiautomation"

    try:
        auto.SetGlobalSearchTimeout(3)
    except Exception:  # noqa: BLE001
        pass

    def _collect(control, out, depth=0, limit=25):
        if depth > limit or len(out) > 120:
            return
        try:
            label = control.Name or ""
        except Exception:  # noqa: BLE001
            label = ""
        if label:
            out.append((control, label, depth))
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            children = []
        for c in children:
            _collect(c, out, depth + 1, limit)

    def _match(name, label):
        # 精确 / 名称含关键词 / 关键词含短名（缩写也能命中）
        # 反向包含（label in name）要求控件名至少 2 个字符：
        # 部分 Web/Electron 应用会把文字暴露成单字符控件（如「所」「有」），
        # 允许单字符反向命中会出现「找所有书签却点了所」的误触。
        if not label:
            return False
        if label == name or name in label:
            return True
        return len(label) >= 2 and label in name

    def _direct_find(root, name):
        """uiautomation 直接定位（有时比手动遍历命中率更高）。"""
        finders = []
        for fn in ("ButtonControl", "Control"):
            f = getattr(auto, fn, None)
            if f is not None:
                finders.append(f)
        for finder in finders:
            try:
                c = finder(searchFromControl=root, SubName=name, foundIndex=1)
                if c is not None and getattr(c, "Exists", lambda *_: True)(0):
                    return c
            except Exception:  # noqa: BLE001
                continue
        return None

    def _search_in(root, name):
        """返回 (命中列表[(ctrl,label)], 该窗口全部控件名列表)。"""
        allc = []
        _collect(root, allc)
        hits = [(ctrl, label) for ctrl, label, _ in allc if _match(name, label)]
        # 兜底：uiautomation 直接定位
        if not hits:
            d = _direct_find(root, name)
            if d is not None:
                try:
                    hits.append((d, d.Name or name))
                except Exception:  # noqa: BLE001
                    hits.append((d, name))
        names = []
        for _, label, _ in allc:
            if label not in names:
                names.append(label)
        return hits, names

    def _names_snippet(names, maxn=25):
        if not names:
            return "（该窗口未暴露任何可访问的控件名）"
        return "、".join(names[:maxn])

    try:
        try:
            fg = auto.GetForegroundControl()
            fg_win = fg.GetTopLevelControl()
            fg_handle = fg_win.NativeWindowHandle
        except Exception as e:  # noqa: BLE001
            return f"获取前台窗口失败：{e}"

        # 如果前台是本程序自身，跳过它，优先操作外部窗口
        if _is_self_window(fg_win):
            fg_win = None

        candidates, names = [], []
        scope = "前台窗口"
        if fg_win is not None:
            candidates, names = _search_in(fg_win, name)

        # 前台没找到 -> 回退所有其它可见窗口
        if not candidates:
            traversed = []  # [(pname, title), ...] 记录实际遍历到的应用
            for w, _, title, _h, pid, pname in _list_visible_windows(auto, exclude_handles=[fg_handle]):
                traversed.append((pname or "?", title))
                try:
                    h, _ = _search_in(w, name)
                    if h:
                        candidates.extend(h)
                        scope = "可见窗口"
                except Exception:  # noqa: BLE001
                    continue
            # 把“遍历了哪些应用（进程名+窗口标题）”打印出来，便于排查为何没命中
            if traversed:
                _lines = "\n".join(f"  · 进程 {pn} | 窗口「{tt}」" for pn, tt in traversed)
                print(f"[遍历可见窗口] 共 {len(traversed)} 个：\n{_lines}")

        # 前台/可见窗口都没找到 -> 尝试桌面图标（回收站/此电脑/网络 等不在普通窗口树里）
        if not candidates:
            desk = _click_desktop_icon(name, preview)
            if desk:
                return desk

        if not candidates:
            # UIA 找不到 -> 自动尝试 OCR（读屏幕上真实文字，兼容“看得到却没暴露名称”的控件）
            ocr_res = _click_by_name_ocr({"name": name, "double": double, "right": right}, preview)
            if ocr_res and not any(k in ocr_res for k in ("未", "失败", "请安装", "请确认")):
                return ocr_res
            tip = ocr_res if ocr_res else "（OCR 未启用）"
            traversed_note = ""
            if traversed:
                _lines = "\n".join(f"  · 进程 {pn} | 窗口「{tt}」" for pn, tt in traversed)
                traversed_note = f"\n已遍历的可见应用（进程名 | 窗口标题）：\n{_lines}"
            return (f"未找到名为「{name}」的控件。\n"
                    f"【{scope}】UIA 暴露的控件名有：{_names_snippet(names)}\n"
                    f"OCR 尝试：{tip}{traversed_note}\n"
                    f"（若控件没暴露可访问名称，已用 OCR 在整屏扫描文字；确认目标文字可见、未被遮挡、非图标/图片按钮）")

        # 选最佳：精确 > 名称含关键词 > 关键词含短名；
        # 前两档同档取名字最短（最贴近），反向包含档取名字最长（重叠越多越具体）
        def _score(item):
            _, label = item
            if label == name:
                return (0, len(label))
            if name in label:
                return (1, len(label))
            return (2, -len(label))

        candidates.sort(key=_score)
        target, found_label = candidates[0]
        if preview:
            _kind = "双击" if double else ("右键" if right else "单击")
            return f"【演练】将{_kind}控件：{found_label}（{scope}）"
        try:
            target.SetFocus()
        except Exception:  # noqa: BLE001
            pass
        _suffix = "（右键）" if right else ("（双击）" if double else "")

        def _mouse_click():
            """真实鼠标点击控件中心（不依赖控件挂事件）。"""
            if right:
                target.ClickByMouse(button="right")
            elif double:
                target.DoubleClickByMouse()
            else:
                target.ClickByMouse()

        try:
            # 优先用控件自身的高层方法（Click/DoubleClick/RightClick，走 UIA Invoke），
            # 缺失则回退到鼠标事件；默认单击。
            if right:
                if hasattr(target, "RightClick"):
                    target.RightClick()
                else:
                    target.ClickByMouse(button="right")
            elif double:
                if hasattr(target, "DoubleClick"):
                    target.DoubleClick()
                else:
                    target.DoubleClickByMouse()
            else:
                if hasattr(target, "Click"):
                    target.Click()
                else:
                    target.ClickByMouse()
        except Exception as e:  # noqa: BLE001
            # Invoke 失败（典型：0x80040201 事件无订户——静态文本/未挂事件的控件）
            # -> 回退真实鼠标点击控件中心再试一次
            try:
                _mouse_click()
                return f"已点击控件：{found_label}（{scope}，鼠标兜底）{_suffix}"
            except Exception as e2:  # noqa: BLE001
                return f"找到控件「{found_label}」但点击失败：{e}；鼠标兜底也失败：{e2}"
        return f"已点击控件：{found_label}（{scope}）{_suffix}"
    except Exception as e:  # noqa: BLE001
        return f"按名称点击失败：{e}"


def _shutdown(params):
    subprocess.run("shutdown /s /t 0", shell=True)
    return "正在关机…"


def _restart(params):
    subprocess.run("shutdown /r /t 0", shell=True)
    return "正在重启…"


def _sleep(params):
    subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
    return "正在睡眠…"


def _say(params):
    from tts import speak

    text = params.get("text", "")
    speak(text)
    return f"已朗读：{text[:50]}"


def _wait(params):
    secs = float(params.get("seconds", 1))
    time.sleep(secs)
    return f"已等待 {secs} 秒"


def _run_command(params):
    cmd = params.get("command", "")
    if not cmd:
        return "未指定命令"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        out = (r.stdout or r.stderr or "")[:400]
        return f"执行：{cmd}\n返回码：{r.returncode}\n{out}"
    except Exception as e:  # noqa: BLE001
        return f"命令执行失败：{e}"


ACTION_HANDLERS = {
    "open_app": _open_app,
    "open_file": _open_file,
    "open_url": _open_url,
    "type_text": _type_text,
    "press_keys": _press_keys,
    "click": _click,
    "move_mouse": _move_mouse,
    "scroll": _scroll,
    "volume_up": _volume_up,
    "volume_down": _volume_down,
    "volume_mute": _volume_mute,
    "screenshot": _screenshot,
    "lock_screen": _lock_screen,
    "minimize_active": _minimize_active,
    "maximize_active": _maximize_active,
    "restore_active": _restore_active,
    "close_active": _close_active,
    "switch_window": _switch_window,
    "click_by_name": _click_by_name,
    "double_click": _double_click,
    "right_click": _right_click,
    "shutdown": _shutdown,
    "restart": _restart,
    "sleep": _sleep,
    "say": _say,
    "wait": _wait,
    "run_command": _run_command,
}


def execute_steps(steps, log, dry_run=False):
    """
    依次执行动作步骤列表。
    steps: [{"action": "...", "params": {...}}, ...]
    log: 回调函数，用于把每条结果写进界面/日志。
    dry_run: True 时只记录「将要执行什么」，不真正执行（用于演练/测试模式）。
    返回执行结果文本列表。
    """
    results = []
    for i, step in enumerate(steps or [], 1):
        action = step.get("action")
        params = step.get("params") or {}
        handler = ACTION_HANDLERS.get(action)
        if not handler:
            msg = f"未知动作：{action}"
            log(f"[步骤{i}] {msg}")
            results.append(msg)
            continue
        if dry_run:
            # 演练模式：click_by_name 需要真正去窗口“找”控件以给出真实反馈，
            # 但只找不点；其余动作仅展示将要执行的内容。
            if action == "click_by_name":
                step_params = dict(params)
                step_params["_preview"] = True
                try:
                    msg = handler(step_params)
                except Exception as e:  # noqa: BLE001
                    msg = f"演练查找失败：{e}"
                log(f"[步骤{i}] {msg}")
                results.append(msg)
                continue
            preview = ", ".join(f"{k}={v}" for k, v in params.items()) if params else "（无参数）"
            msg = f"【演练】将执行 {action} ({preview})"
            log(f"[步骤{i}] {msg}")
            results.append(msg)
            continue
        try:
            msg = handler(params)
        except Exception as e:  # noqa: BLE001
            msg = f"执行出错：{e}"
        log(f"[步骤{i}] {action} → {msg}")
        results.append(msg)
    return results
