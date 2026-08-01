"""
统一的 Windows 输入 / 截图封装。

设计目标：让"语音控制台"不再强依赖 pyautogui 这个安装较重的库。
- 若环境中已安装 pyautogui：所有操作直接委托给它（行为与之前完全一致）。
- 若未安装：自动改用 ctypes + Pillow(ImageGrab) 兜底，无需任何额外依赖即可工作。

这样用户本机没装 pyautogui 时，程序也能正常点击、按键、截图、OCR，
不会再出现"未安装 OCR 依赖"这类误报。
"""
import ctypes

# 优先尝试 pyautogui；没有就走 ctypes 兜底
try:
    import pyautogui  # type: ignore
    _HAS_PYAUTOGUI = True
    try:
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.08
    except Exception:  # noqa: BLE001
        pass
except Exception:  # noqa: BLE001
    _HAS_PYAUTOGUI = False

user32 = ctypes.windll.user32

# ---------------------------------------------------------------------------
# 键位映射（ctypes 兜底用）
# ---------------------------------------------------------------------------
_VK = {
    "ctrl": 162, "ctrl_l": 162, "ctrl_r": 163,
    "alt": 164, "alt_l": 164, "alt_r": 165,
    "shift": 160, "shift_l": 160, "shift_r": 161,
    "win": 91, "win_l": 91, "win_r": 92,
    "tab": 9, "enter": 13, "return": 13, "esc": 27, "escape": 27,
    "space": 32, "backspace": 8, "delete": 46, "del": 46, "insert": 45,
    "up": 38, "down": 40, "left": 37, "right": 39,
    "home": 36, "end": 35, "pageup": 33, "pagedown": 34, "pgup": 33, "pgdn": 34,
    "f1": 112, "f2": 113, "f3": 114, "f4": 115, "f5": 116, "f6": 117,
    "f7": 118, "f8": 119, "f9": 120, "f10": 121, "f11": 122, "f12": 123,
    "volumemute": 173, "volumeup": 175, "volumedown": 174,
    "capslock": 20, "numlock": 144, "scrolllock": 145,
    "printscreen": 44,
}
for _ch in "abcdefghijklmnopqrstuvwxyz0123456789":
    _VK[_ch] = ord(_ch.upper())


def _vk(name):
    if name is None:
        return None
    return _VK.get(str(name).lower())


# ---------------------------------------------------------------------------
# 屏幕信息 / 截图
# ---------------------------------------------------------------------------
def size():
    if _HAS_PYAUTOGUI:
        s = pyautogui.size()
        return (int(s.width), int(s.height))
    return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1))


def screenshot(path=None, region=None):
    """region 形如 (left, top, width, height)，与 pyautogui 约定保持一致。"""
    if _HAS_PYAUTOGUI:
        return pyautogui.screenshot(path, region=region)
    from PIL import ImageGrab
    bbox = None
    if region:
        left, top, w, h = region
        bbox = (int(left), int(top), int(left) + int(w), int(top) + int(h))
    img = ImageGrab.grab(bbox=bbox)
    if path:
        img.save(path)
    return img


# ---------------------------------------------------------------------------
# 鼠标
# ---------------------------------------------------------------------------
def _mouse_event(flags, dx=0, dy=0, data=0):
    user32.mouse_event(flags, dx, dy, data, 0)


_LEFT_DOWN, _LEFT_UP = 0x0002, 0x0004
_RIGHT_DOWN, _RIGHT_UP = 0x0008, 0x0010
_MIDDLE_DOWN, _MIDDLE_UP = 0x0020, 0x0040
_WHEEL = 0x0800


def _do_click(button, clicks=1, double=False):
    if button == "right":
        dn, up = _RIGHT_DOWN, _RIGHT_UP
    elif button == "middle":
        dn, up = _MIDDLE_DOWN, _MIDDLE_UP
    else:
        dn, up = _LEFT_DOWN, _LEFT_UP
    n = 2 if double else 1
    for _ in range(max(1, clicks)):
        for _ in range(n):
            _mouse_event(dn)
            _mouse_event(up)


def click(x=None, y=None, button="left", clicks=1, double=False):
    if _HAS_PYAUTOGUI:
        if double:
            if x is None:
                pyautogui.doubleClick(button=button)
            else:
                pyautogui.doubleClick(int(x), int(y), button=button)
            return
        if x is None:
            pyautogui.click(button=button, clicks=clicks)
        else:
            pyautogui.click(int(x), int(y), button=button, clicks=clicks)
        return
    if x is not None and y is not None:
        user32.SetCursorPos(int(x), int(y))
    _do_click(button, clicks, double)


def double_click(x=None, y=None):
    click(x, y, double=True)


def right_click(x=None, y=None):
    click(x, y, button="right")


def move(x, y):
    if _HAS_PYAUTOGUI:
        pyautogui.moveTo(int(x), int(y))
    else:
        user32.SetCursorPos(int(x), int(y))


def scroll(amount):
    amount = int(amount)
    if _HAS_PYAUTOGUI:
        pyautogui.scroll(amount)
    else:
        # 一次滚轮 = 120 单位（Windows 约定）
        _mouse_event(_WHEEL, 0, 0, amount * 120)


# ---------------------------------------------------------------------------
# 键盘
# ---------------------------------------------------------------------------
def press(key):
    if _HAS_PYAUTOGUI:
        pyautogui.press(key)
        return
    vk = _vk(key)
    if vk is None:
        return
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 0x0002, 0)  # KEYEVENTF_KEYUP


def hotkey(*keys):
    if _HAS_PYAUTOGUI:
        pyautogui.hotkey(*[str(k).lower() for k in keys])
        return
    vks = [_vk(k) for k in keys]
    for vk in vks:
        if vk:
            user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        if vk:
            user32.keybd_event(vk, 0, 0x0002, 0)


def available():
    """是否使用了真实的 pyautogui 后端（仅用于诊断输出）。"""
    return _HAS_PYAUTOGUI


# ---------------------------------------------------------------------------
# 虚拟屏幕 / 整屏 OCR 辅助（规避 DPI 缩放与多显示器坐标错位）
# ---------------------------------------------------------------------------
def virtual_screen_rect():
    """返回虚拟屏幕矩形 (left, top, width, height)。
    坐标原点为“虚拟屏幕”左上角；多显示器且主屏不在原点时 left/top 可能为负。
    该坐标系与 SetCursorPos（点击）/ GetWindowRect（窗口矩形）一致。
    """
    left = user32.GetSystemMetrics(76)    # SM_XVIRTUALSCREEN
    top = user32.GetSystemMetrics(77)     # SM_YVIRTUALSCREEN
    width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    if not width or not height:
        left, top = 0, 0
        width, height = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    return (int(left), int(top), int(width), int(height))


def screenshot_virtual():
    """截取整个虚拟屏幕（含所有显示器）。
    返回 (img, origin_left, origin_top)：origin 为虚拟屏幕原点，
    便于把图像像素坐标换算回屏幕坐标：screen_x = origin_left + px。
    """
    from PIL import ImageGrab
    left, top, width, height = virtual_screen_rect()
    try:
        img = ImageGrab.grab(all_screens=True)
    except Exception:  # noqa: BLE001
        bbox = (left, top, left + width, top + height)
        img = ImageGrab.grab(bbox=bbox)
    return img, int(left), int(top)


def _top_windows_by_pid(pid):
    """返回属于指定进程的所有可见顶级窗口的虚拟屏幕矩形 [(l,t,r,b), ...]。"""
    import ctypes.wintypes as wt
    result = []

    def _enum(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            if p.value == pid:
                r = wt.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(r)):
                    result.append((r.left, r.top, r.right, r.bottom))
        except Exception:  # noqa: BLE001
            pass
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(EnumWindowsProc(_enum), 0)
    return result


def window_title_at(x, y):
    """返回屏幕坐标 (x,y) 处所属窗口的标题（用于诊断“点到了哪里”）。"""
    import ctypes.wintypes as wt
    pt = wt.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(260)
    user32.GetWindowTextW(hwnd, buf, 260)
    return buf.value.strip()


def cursor_pos():
    """返回鼠标当前位置 (x, y)（逻辑屏幕坐标，与 SetCursorPos/click 同一坐标系）。"""
    import ctypes.wintypes as wt
    pt = wt.POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return int(pt.x), int(pt.y)


def window_pid_at(x, y):
    """返回屏幕坐标 (x,y) 处窗口所属的进程 PID（0 表示取不到）。

    用于判断“鼠标正悬停在哪个程序的窗口上”，比如避免点击落在本程序自己身上。
    """
    import ctypes.wintypes as wt
    pt = wt.POINT(int(x), int(y))
    hwnd = user32.WindowFromPoint(pt)
    if not hwnd:
        return 0
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def point_in_rects(x, y, rects):
    """判断点 (x,y) 是否落在任一矩形 (l,t,r,b) 内。"""
    for l, t, r, b in rects:
        if l <= x <= r and t <= y <= b:
            return True
    return False


def enum_visible_windows(exclude_pid=None):
    """枚举所有可见顶层窗口（不含排除的进程）。
    返回 [(hwnd, pid, pname, title, (l,t,r,b))] —— 用于诊断“OCR/点击遍历了哪些应用”，
    以及给 UIA 按句柄取控件树用。基于 Win32 EnumWindows，完整可靠（含 UWP/Shell 窗口），
    比 uiautomation 根的 GetChildren 更全面。
    """
    import ctypes.wintypes as wt
    result = []
    excl = int(exclude_pid) if exclude_pid else 0

    def _enum(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            p = wt.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
            pid = p.value
            if excl and pid == excl:
                return True
            buf = ctypes.create_unicode_buffer(260)
            user32.GetWindowTextW(hwnd, buf, 260)
            title = buf.value.strip()
            r = wt.RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
                return True
            if r.right - r.left <= 0 or r.bottom - r.top <= 0:
                return True
            pname = process_name_by_pid(pid) if pid else ""
            result.append((int(hwnd), pid, pname, title or "（无标题窗口）",
                           (r.left, r.top, r.right, r.bottom)))
        except Exception:  # noqa: BLE001
            pass
        return True

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    user32.EnumWindows(EnumWindowsProc(_enum), 0)
    return result


def process_name_by_pid(pid):
    """根据进程 PID 返回进程映像名（如 notepad.exe）。失败返回空串。"""
    try:
        import ctypes.wintypes as wt
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        PROCESS_QUERY_INFORMATION = 0x0400
        PROCESS_VM_READ = 0x0010
        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, int(pid))
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(260)
            if psapi.GetModuleBaseNameW(h, 0, buf, 260):
                return buf.value or ""
            return ""
        finally:
            kernel32.CloseHandle(h)
    except Exception:  # noqa: BLE001
        return ""
