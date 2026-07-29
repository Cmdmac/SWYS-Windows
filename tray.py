"""
系统托盘图标支持（基于 pystray）。

· 若未安装 pystray，TRAY_AVAILABLE=False，调用方应静默降级（程序照常运行，只是没有托盘）。
· pystray 在 Windows 上会自动拉取 pywin32，无需额外手动安装。
· tkinter 只能在主线程操作控件，因此托盘图标的回调统一用 root.after(0, ...) 切回主线程。

托盘行为约定：
  - 左键单击：切换主窗口显示/隐藏（toggle，轻微延迟以区分双击）。
  - 左键双击：打开（显示并置前）主窗口。
  - 右键菜单：① 打开窗口  ② 退出（真正退出程序）。
  - 右键菜单：① 打开窗口  ② 退出（真正退出程序）。
"""
import threading
import time

TRAY_AVAILABLE = True
try:
    import pystray
    from pystray import Icon as _TrayIcon, Menu as _TrayMenu, MenuItem as _TrayMenuItem
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # noqa: BLE001
    TRAY_AVAILABLE = False
    pystray = None
    Image = None
    ImageDraw = None
    ImageFont = None

APP_NAME = "语音控制台"


def make_icon_image(size=64):
    """生成托盘图标（PIL Image）：蓝色圆底 + 白色「语」字。

    若系统中没有可用的中文字体，退化为「蓝底 + 白色小圆点」，保证图标永远能画出来。
    若 PIL 不可用（极端情况），返回一张 1x1 透明图，避免调用方崩溃。
    """
    if Image is None or ImageDraw is None:
        # PIL 缺失：返回一个极小的占位图，start_tray 不会用到它（TRAY_AVAILABLE 为 False）
        return None

    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, size - 3, size - 3), fill=(26, 115, 232, 255))

    font = None
    for cand in ("C:/Windows/Fonts/msyh.ttc", "msyh.ttc", "msyhbd.ttc",
                 "C:/Windows/Fonts/msyhbd.ttc", "simhei.ttf"):
        try:
            font = ImageFont.truetype(cand, int(size * 0.6))
            break
        except Exception:  # noqa: BLE001
            continue

    text = "语"
    if font is not None:
        bbox = d.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        h = bbox[3] - bbox[1]
        d.text(((size - w) / 2 - bbox[0], (size - h) / 2 - bbox[1]),
               text, fill=(255, 255, 255, 255), font=font)
    else:
        # 退化：白色小圆点，至少能看出是个图标
        d.ellipse((size * 0.38, size * 0.38, size * 0.62, size * 0.62),
                  fill=(255, 255, 255, 255))
    return img


def save_ico(path, size=64):
    """把托盘图标导出为 .ico 文件（含多分辨率），供桌面快捷方式引用。"""
    if Image is None:
        return None
    img = make_icon_image(size)
    if img is None:
        return None
    img.save(path, format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
    return path


def _make_activate_handler(toggle_cb, show_cb):
    """构造托盘左键回调：单击=切换显示/隐藏，双击=打开（显示并置前）窗口。

    pystray 的 Windows 后端窗口类未启用 CS_DBLCLKS，双击托盘只会触发两次
    单击回调（on_activate）。因此这里用时间戳区分单击/双击：
      · 两次单击间隔 < 0.4s 视为双击 -> 调用 show_cb（并撤销待执行的 toggle，避免闪烁）；
      · 否则视为单击 -> 短暂延迟后调用 toggle_cb（留出双击判定窗口）。
    """
    state = {"last": 0.0, "timer": None}

    def _handler(icon):
        now = time.time()
        if state["last"] and (now - state["last"]) < 0.4:
            # 双击：打开窗口，并撤销待执行的单击 toggle
            state["last"] = 0.0
            if state["timer"] is not None:
                state["timer"].cancel()
                state["timer"] = None
            show_cb()
        else:
            state["last"] = now

            def _maybe_toggle():
                state["timer"] = None
                if state["last"] and (time.time() - state["last"]) >= 0.35:
                    toggle_cb()

            state["timer"] = threading.Timer(0.4, _maybe_toggle)
            state["timer"].start()

    return _handler


def start_tray(toggle_cb, show_cb, quit_cb):
    """在后台守护线程启动托盘图标，返回 pystray.Icon 对象（退出时调用 .stop()）。

    参数（均为无参回调，内部请用 root.after(0, ...) 切回主线程）：
      toggle_cb : 左键单击 -> 切换窗口显示/隐藏
      show_cb   : 菜单“打开窗口” -> 强制显示窗口
      quit_cb   : 菜单“退出” -> 真正退出程序
    """
    if not TRAY_AVAILABLE:
        return None

    image = make_icon_image()
    if image is None:  # PIL 缺失等极端情况
        return None
    menu = _TrayMenu(
        _TrayMenuItem("打开窗口", show_cb),
        _TrayMenuItem("退出", quit_cb),
    )

    icon = _TrayIcon(APP_NAME, image, APP_NAME, menu)
    icon.on_activate = _make_activate_handler(toggle_cb, show_cb)

    t = threading.Thread(target=icon.run, daemon=True)
    t.start()
    return icon
