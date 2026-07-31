"""
简单指令识别（无需大模型）。
规则：用关键词/正则把常见指令直接映射为动作步骤。
若无法匹配，返回 None，由上层交给大模型分析。
返回格式：
  ("answer", "文本")          -> 直接回答（如时间/日期查询）
  ("steps", steps, 说明)      -> 直接执行动作
  None                        -> 交给大模型
"""
import re
from datetime import datetime

# 常见网站名 -> 网址
SITES = {
    "百度": "https://www.baidu.com",
    "谷歌": "https://www.google.com",
    "必应": "https://www.bing.com",
    "bilibili": "https://www.bilibili.com",
    "哔哩哔哩": "https://www.bilibili.com",
    "知乎": "https://www.zhihu.com",
    "微博": "https://weibo.com",
    "youtube": "https://www.youtube.com",
    "github": "https://github.com",
    "淘宝": "https://www.taobao.com",
    "京东": "https://www.jd.com",
    "腾讯": "https://www.qq.com",
    "豆瓣": "https://www.douban.com",
}

# 本程序自身的控件 / 语义动作：说出这些词直接触发对应 GUI 行为，
# 不依赖 UIA/OCR 屏幕查找（tkinter 按钮在 UIA 中名字为空、OCR 又需额外安装）。
# 键 -> (action_key, 说明)
APP_COMMANDS = {
    "发送": ("send", "发送当前输入框内容"),
    "发": ("send", "发送当前输入框内容"),
    "清空": ("clear", "清空对话记录"),
    "清屏": ("clear", "清空对话记录"),
    "清除": ("clear", "清空对话记录"),
    "清空对话": ("clear", "清空对话记录"),
    "清除对话": ("clear", "清空对话记录"),
    "演练": ("dry_run", "切换演练模式"),
    "演练模式": ("dry_run", "切换演练模式"),
    "测试模式": ("dry_run", "切换演练模式"),
    "语音": ("speak", "开关语音播报"),
    "语音播报": ("speak", "开关语音播报"),
    "朗读": ("speak", "开关语音播报"),
    "设置": ("settings", "打开设置面板"),
    "设置面板": ("settings", "打开设置面板"),
    "打开设置": ("settings", "打开设置面板"),
    "帮助": ("help", "打开使用帮助"),
    "帮助信息": ("help", "打开使用帮助"),
    "麦克风": ("mic", "开关语音输入"),
    "语音输入": ("mic", "开关语音输入"),
    "录音": ("mic", "开关语音输入"),
}


def _match_app_command(t):
    """匹配本程序自身控件/动作。返回 (action_key, 说明) 或 None。"""
    if t in APP_COMMANDS:
        return APP_COMMANDS[t]
    # 允许「打开/点开/查看 + 控件名」
    for prefix in ("打开", "点开", "查看", "点击"):
        if t.startswith(prefix) and t[len(prefix):] in APP_COMMANDS:
            return APP_COMMANDS[t[len(prefix):]]
    # 允许控件名出现在无标点的短句中（复合/含宾语的已被上方守卫拦截）
    if 0 < len(t) <= 12 and not re.search(r"[，。、？!?；;：:]", t):
        for key in APP_COMMANDS:
            if key in t:
                return APP_COMMANDS[key]
    return None


# 通用应用动作：针对前台窗口直接发快捷键（Ctrl/Alt/Win 组合），
# 不依赖 UIA/OCR，因此无需安装 Tesseract，也不会提示“未安装”。
#
# 注意：这里只保留“与界面可见文字无关、纯键盘操作”的全局快捷键
#（复制/粘贴/保存/撤销/刷新…）——它们作用于当前焦点，无需先在屏幕上“认出”某个控件。
#
# 而「编辑/文件/视图/格式/工具」这类“菜单栏上的文字”已刻意不放在这里：
# 它们应该走 click_by_name（UIA/OCR 在整屏识别，且优先别的应用、
# 排除本程序自身），也就是“屏幕上真有这个菜单才点”，符合“可见可说”。
# 键 -> (keys 列表, 说明)
GENERIC_ACTIONS = {
    # 编辑（纯文本操作，作用于当前焦点）
    "复制": (["ctrl", "c"], "复制 (Ctrl+C)"),
    "粘贴": (["ctrl", "v"], "粘贴 (Ctrl+V)"),
    "剪切": (["ctrl", "x"], "剪切 (Ctrl+X)"),
    "撤销": (["ctrl", "z"], "撤销 (Ctrl+Z)"),
    "重做": (["ctrl", "y"], "重做 (Ctrl+Y)"),
    "全选": (["ctrl", "a"], "全选 (Ctrl+A)"),
    "查找": (["ctrl", "f"], "查找 (Ctrl+F)"),
    "替换": (["ctrl", "h"], "替换 (Ctrl+H)"),
    # 文件（纯键盘操作）
    "保存": (["ctrl", "s"], "保存 (Ctrl+S)"),
    "另存为": (["ctrl", "shift", "s"], "另存为 (Ctrl+Shift+S)"),
    "打印": (["ctrl", "p"], "打印 (Ctrl+P)"),
    "新建": (["ctrl", "n"], "新建 (Ctrl+N)"),
    "打开": (["ctrl", "o"], "打开 (Ctrl+O)"),
    "打开文件": (["ctrl", "o"], "打开文件 (Ctrl+O)"),
    "关闭文件": (["ctrl", "w"], "关闭 (Ctrl+W)"),
    # 浏览 / 视图
    "刷新": (["f5"], "刷新 (F5)"),
    "后退": (["alt", "left"], "后退 (Alt+←)"),
    "前进": (["alt", "right"], "前进 (Alt+→)"),
    # 注意：「编辑/文件/视图/格式/工具」等菜单名不在此处——
    # 它们会落到 click_by_name，先确认屏幕上（且是别的应用）真的有该菜单才点击，
    # 而不是盲发 Alt+字母。这符合“可见可说”的设计意图。
}


def _match_generic(t):
    return GENERIC_ACTIONS.get(t)


def match_simple(text):
    t = (text or "").strip()
    if not t:
        return None
    tl = t.lower()

    # 复合 / 多步指令：含并列连词，或“动词+宾语”这类需要组合的动作时，
    # 交给大模型分析。注意：单独的动词（如 发送/搜索/设置/播放）不当作复合，
    # 而是落入下方“按名称点击控件”的兜底，从而实现“说出控件名就点击”。
    COMPLEX_PATTERNS = [
        r"再|然后|接着|并且|而且|顺手|顺便|另外|同时(也)?|以及|一边.*一边",
        r"[，、]",  # 中文逗号/顿号通常表示多个动作
        # 以下都要求“动词+具体宾语”，避免出现宾语的裸动词会落到控件点击
        r"搜(索)?(天气|资料|信息|新闻|图片|视频|网站|一下)",
        r"查(一下|天气|资料|信息|快递|订单|股票|新闻|余额|怎么|如何)",
        r"发(邮件|消息|微信|短信|条|文件|图片)",
        r"写(一段|个|一份|篇|邮件|文章|总结|代码)",
        r"提醒我?.+",
        r"把.{0,6}调(大|小|高|低)|让.{0,8}(打开|关闭|调)",
    ]
    for pat in COMPLEX_PATTERNS:
        if re.search(pat, t):
            return None

    # 时间 / 日期查询（直接回答）
    if ("时间" in t or "几点" in t) and ("现在" in t or "当前" in t or t in ("几点了", "几点", "现在几点")):
        now = datetime.now()
        return ("answer", f"现在是 {now.strftime('%H:%M:%S')}")
    if ("日期" in t or "几号" in t or "星期" in t) and ("今天" in t or "当前" in t or "现在" in t):
        now = datetime.now()
        wk = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"][now.weekday()]
        return ("answer", f"今天是 {now.strftime('%Y年%m月%d日')} {wk}")

    # 截图
    if "截图" in t or "截屏" in t or "screenshot" in tl:
        return ("steps", [{"action": "screenshot", "params": {}}], "截取当前屏幕")

    # 锁屏
    if "锁屏" in t or "锁定屏幕" in t or "lock" in tl:
        return ("steps", [{"action": "lock_screen", "params": {}}], "锁定屏幕")

    # 关机 / 重启 / 睡眠
    if "关机" in t or "关闭电脑" in t or "shut" in tl:
        return ("steps", [{"action": "shutdown", "params": {}}], "关闭电脑")
    if "重启" in t or "重新启动" in t or "restart" in tl:
        return ("steps", [{"action": "restart", "params": {}}], "重启电脑")
    if "睡眠" in t or "休眠" in t or "sleep" in tl:
        return ("steps", [{"action": "sleep", "params": {}}], "让电脑睡眠")

    # 音量
    if "静音" in t or "mute" in tl:
        return ("steps", [{"action": "volume_mute", "params": {}}], "切换静音")
    if re.search(r"音量.*(大|高|加|增|升|调大|up)", t) or "声音大" in t or "调大音量" in t:
        return ("steps", [{"action": "volume_up", "params": {}}], "增大音量")
    if re.search(r"音量.*(小|低|减|降|调小|down)", t) or "声音小" in t or "调小音量" in t:
        return ("steps", [{"action": "volume_down", "params": {}}], "减小音量")

    # 窗口操作
    if "回到桌面" in t or "显示桌面" in t or "只看桌面" in t or "看桌面" in t:
        return ("steps", [{"action": "show_desktop", "params": {}}], "回到桌面（显示桌面）")
    if "最小化" in t:
        return ("steps", [{"action": "minimize_active", "params": {}}], "最小化当前窗口")
    if "最大化" in t:
        return ("steps", [{"action": "maximize_active", "params": {}}], "最大化当前窗口")
    if "还原" in t or "恢复" in t:
        return ("steps", [{"action": "restore_active", "params": {}}], "还原窗口")
    if "关闭" in t and ("窗口" in t or "当前" in t or "这个" in t or "此" in t):
        return ("steps", [{"action": "close_active", "params": {}}], "关闭当前窗口")
    if "切换窗口" in t or "切换上一个窗口" in t or "下一个窗口" in t or "切到下一个窗口" in t:
        return ("steps", [{"action": "switch_window", "params": {}}], "切换窗口")

    # 点击 / 鼠标交互（可见可说：说“双击/右键/点击 + 控件名”就直接按名操作，不依赖大模型）
    # 窗口菜单 / 控制菜单 / 系统菜单 -> 打开当前窗口的系统菜单 (Alt+Space)
    if re.search(r"窗口菜单|控制菜单|系统菜单", t):
        return ("steps", [{"action": "press_keys", "params": {"keys": ["alt", "space"]}}], "打开窗口菜单")
    # 带坐标的点击 / 双击 / 右键（最精确，优先于“按名点击”）
    m = re.search(r"(点击|单击|点一下|双击|双点|右键|右击|右点)\s*[:：]?\s*(\d+)\s*[，, ]*\s*(\d+)", t)
    if m:
        verb, x, y = m.group(1), int(m.group(2)), int(m.group(3))
        if verb in ("双击", "双点"):
            return ("steps", [{"action": "double_click", "params": {"x": x, "y": y}}], f"双击坐标 ({x}, {y})")
        if verb in ("右键", "右击", "右点"):
            return ("steps", [{"action": "right_click", "params": {"x": x, "y": y}}], f"右键点击坐标 ({x}, {y})")
        return ("steps", [{"action": "click", "params": {"x": x, "y": y}}], f"点击坐标 ({x}, {y})")

    # “动词 + 控件名” -> 按名称点击（支持 双击 / 右键，默认单击）
    # 例：「双击编辑」「双击 编辑」「右键发送」「点击确定」「点一下回收站」
    # 注意：必须在“裸双击/右键/点击（作用于当前鼠标位置）”之前，否则会被后者抢走。
    m = re.match(r"^(双击|双点|右键|右击|右点|点击|单击|点一下|单击一下)\s*(.+)$", t)
    if m:
        verb, name = m.group(1), m.group(2).strip()
        if 0 < len(name) <= 12 and not re.search(r"[，。、？!?；;：:]", name):
            params = {"name": name}
            if verb in ("双击", "双点"):
                params["double"] = True
                desc = f"双击名为「{name}」的控件"
            elif verb in ("右键", "右击", "右点"):
                params["right"] = True
                desc = f"右键点击名为「{name}」的控件"
            else:
                desc = f"点击名为「{name}」的控件"
            return ("steps", [{"action": "click_by_name", "params": params}], desc)

    if re.search(r"双击|双点", t):
        m2 = re.search(r"(\d+)\s*[，, ]*\s*(\d+)", t)
        if m2:
            return ("steps", [{"action": "double_click", "params": {"x": int(m2.group(1)), "y": int(m2.group(2))}}],
                    f"双击坐标 ({m2.group(1)}, {m2.group(2)})")
        return ("steps", [{"action": "double_click", "params": {}}], "双击（鼠标当前位置）")
    if re.search(r"右击|右键|右点", t):
        m2 = re.search(r"(\d+)\s*[，, ]*\s*(\d+)", t)
        if m2:
            return ("steps", [{"action": "right_click", "params": {"x": int(m2.group(1)), "y": int(m2.group(2))}}],
                    f"右键点击坐标 ({m2.group(1)}, {m2.group(2)})")
        return ("steps", [{"action": "right_click", "params": {}}], "右键点击（鼠标当前位置）")
    if re.search(r"(点击|单击|点一下)", t):
        return ("steps", [{"action": "click", "params": {}}], "点击（鼠标当前位置）")

    # 鼠标移动（指定坐标）
    m = re.search(r"(鼠标移到|鼠标移动到|移动鼠标到|鼠标移向)\s*[:：]?\s*(\d+)\s*[，, ]*\s*(\d+)", t)
    if m:
        return ("steps", [{"action": "move_mouse", "params": {"x": int(m.group(2)), "y": int(m.group(3))}}],
                f"移动鼠标到 ({m.group(2)}, {m.group(3)})")

    # 滚动
    if re.search(r"向上滚|往上滚|向上滚动|滚上去", t):
        return ("steps", [{"action": "scroll", "params": {"amount": 300}}], "向上滚动")
    if re.search(r"向下滚|往下滚|向下滚动|滚下来|滚动", t):
        return ("steps", [{"action": "scroll", "params": {"amount": -300}}], "向下滚动")

    # 裸「窗口」：在鼠标当前位置点击该窗口（满足“说窗口就点击”的直觉）
    if re.fullmatch(r"(当前|这个|此)?窗口", t) or t in ("窗口", "当前窗口", "这个窗口", "此窗口"):
        return ("steps", [{"action": "click", "params": {}}], "点击（鼠标当前位置的窗口）")

    # 输入文本
    m = re.search(r"(输入|打字|键入|填入)\s*[:：]?\s*(.+)", t)
    if m:
        content = m.group(2).strip()
        if content:
            return ("steps", [{"action": "type_text", "params": {"text": content}}], f"输入文字：{content}")

    # 打开网页 / 网站
    m = re.search(r"(打开|启动|访问|浏览)\s*(网页|网站|网址)\s*[:：]?\s*(\S+)", t)
    if m:
        url = m.group(3)
        if not url.startswith("http"):
            url = "https://" + url
        return ("steps", [{"action": "open_url", "params": {"url": url}}], f"打开网页 {url}")
    for name, url in SITES.items():
        if ("打开" + name) in t or ("访问" + name) in t:
            return ("steps", [{"action": "open_url", "params": {"url": url}}], f"打开 {name}")

    # 打开系统内置应用 / 特殊位置（必须放在“打开文件 <路径>”规则之前，
    # 否则“打开文件管理器”会被拆成 打开+文件+管理器 当成路径 → WinError 2）
    m = re.search(
        r"(打开|启动|运行)\s*"
        r"(设备管理器|文件管理器|文件资源管理器|资源管理器|我的电脑|此电脑|回收站|控制面板|设置|任务管理器|计算器|画图|终端|命令提示符|命令符)",
        t,
    )
    if m:
        return ("steps", [{"action": "open_app", "params": {"name": m.group(2)}}], f"打开 {m.group(2)}")

    # 打开文件 / 文件夹（含盘符路径，兼容反斜杠与正斜杠）
    m = re.search(r"(打开|运行)\s*(文件夹|文件|目录)\s*[:：]?\s*(\S+)", t)
    if m:
        return ("steps", [{"action": "open_file", "params": {"path": m.group(3).strip()}}], f"打开 {m.group(3).strip()}")
    m = re.search(r"(打开|运行)\s*([A-Za-z]:[\\/][^\s，。,]+)", t)
    if m:
        return ("steps", [{"action": "open_file", "params": {"path": m.group(2)}}], f"打开 {m.group(2)}")

    # 本程序自身控件 / 语义动作：优先于“打开应用”兜底与“按名称点击屏幕”兜底，
    # 直接触发 GUI 行为（如发送/清空/演练/语音开关/设置/帮助）。
    app_cmd = _match_app_command(t)
    if app_cmd is not None:
        action_key, desc = app_cmd
        return ("app_action", action_key, desc)

    # 通用应用动作：针对前台窗口直接发快捷键（保存/复制/编辑/文件…），
    # 不依赖 UIA/OCR，因此无需 Tesseract，也不会提示“未安装”。
    gen = _match_generic(t)
    if gen is not None:
        keys, desc = gen
        return ("steps", [{"action": "press_keys", "params": {"keys": keys}}], desc)

    # 打开应用 / 网址（兜底）
    m = re.search(r"(打开|启动|运行|open|launch)\s*[:：]?\s*([^\s，。,]+)", t)
    if m:
        app = m.group(2).strip(" 。，,")
        if app:
            # 看起来像网址 -> 用浏览器打开
            if "://" in app or app.lower().startswith("www.") or re.search(r"\.\w{2,}$", app):
                url = app if app.startswith("http") else "https://" + app
                return ("steps", [{"action": "open_url", "params": {"url": url}}], f"打开网页 {app}")
            return ("steps", [{"action": "open_app", "params": {"name": app}}], f"打开应用 {app}")

    # 兜底：说出的词像是界面上的控件/菜单名称 -> 按名称点击（实现“可见可说”）
    # 仅当文本较短、且不像一句话（无标点、无复合连词）时启用，避免把长句误当成控件名。
    if 0 < len(t) <= 12 and not re.search(r"[，。、？!?；;：:]", t):
        return ("steps", [{"action": "click_by_name", "params": {"name": t}}], f"点击名为「{t}」的控件")

    # 都没有匹配 -> 交给大模型
    return None
