"""
语音输入（Speech-To-Text）。
使用 microphone + Google 语音识别（需要联网与麦克风；pyaudio 依赖）。
若环境未安装 pyaudio / 无麦克风，本模块会优雅降级：
  - microphone_available() 返回 False
  - listen_once() 返回 None
文本控制、GUI、语音播报等功能完全不依赖本模块，不受影响。
"""
try:
    import speech_recognition as sr
except Exception:  # noqa: BLE001
    sr = None  # speech_recognition 或 pyaudio 缺失时降级


def microphone_available():
    """检测是否存在可用的麦克风设备（依赖 pyaudio）。"""
    if sr is None:
        return False
    try:
        with sr.Microphone() as _:
            return True
    except Exception:  # noqa: BLE001
        return False


def unavailable_reason():
    """返回麦克风不可用的原因，便于在界面上提示用户。"""
    if sr is None:
        return "未加载语音识别模块（可能缺少 pyaudio），🎤 麦克风输入不可用；文本控制不受影响。"
    try:
        import pyaudio  # noqa: F401
    except Exception:  # noqa: BLE001
        return "未安装 pyaudio，🎤 麦克风输入不可用；文本控制不受影响。可运行：pip install pipwin && pipwin install pyaudio"
    return "未检测到麦克风设备。"


def listen_once(timeout=5, phrase_time_limit=8, language="zh-CN"):
    """
    监听一次语音并返回识别文本。
    返回值：
      str  -> 识别到的文字
      ""   -> 没听清
      None -> 麦克风/识别服务不可用
    """
    if sr is None:
        return None
    r = sr.Recognizer()
    try:
        with sr.Microphone() as source:
            r.adjust_for_ambient_noise(source, duration=0.5)
            audio = r.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
    except Exception:  # noqa: BLE001
        return None
    try:
        return r.recognize_google(audio, language=language)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError:
        return None
