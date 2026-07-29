"""
语音播报（Text-To-Speech）。
使用 Windows 自带的 SAPI5（pyttsx3），无需联网、无需额外语音包即可朗读中文。
"""
import threading

import pyttsx3

_engine = None
_enabled = True
_rate = 170


def init():
    """初始化语音引擎，并尽量挑选中文嗓音。"""
    global _engine
    try:
        _engine = pyttsx3.init()
        set_rate(_rate)
        voices = _engine.getProperty("voices") or []
        for v in voices:
            label = (v.name + v.id).lower()
            if any(k in label for k in ["chinese", "zh", "中文", "mandarin", "hua"]):
                _engine.setProperty("voice", v.id)
                break
    except Exception:
        # 没有音频设备/语音包时静默降级，仅不发声
        _engine = None


def set_enabled(value):
    global _enabled
    _enabled = bool(value)


def set_rate(value):
    global _rate
    _rate = int(value)
    if _engine is not None:
        try:
            _engine.setProperty("rate", _rate)
        except Exception:
            pass


def speak(text):
    """朗读文本（去掉常见 Markdown 符号，避免念出标点）。在独立线程中执行，避免阻塞界面。"""
    if not _enabled or _engine is None or not text:
        return
    clean = (text or "").replace("*", "").replace("#", "").replace("`", "")
    clean = clean.strip()
    if not clean:
        return
    threading.Thread(target=_speak_sync, args=(clean,), daemon=True).start()


def _speak_sync(text):
    try:
        _engine.say(text)
        _engine.runAndWait()
    except Exception:
        pass
