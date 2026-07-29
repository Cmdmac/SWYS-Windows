"""
配置管理：把用户设置保存到程序目录下的 config.json。
首次运行使用默认值；用户可在 GUI 的"设置"里修改。
"""
import json
import os

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

DEFAULT_CONFIG = {
    "endpoint": "https://api.openai.com/v1",   # OpenAI 兼容接口地址（也支持 Azure / 本地 Ollama 等）
    "api_key": "",                              # 你的 API Key（留空则复杂指令无法使用大模型）
    "model": "gpt-4o-mini",                     # 使用的模型名
    "auto_speak": True,                         # 自动用语音播报结果
    "speech_rate": 170,                         # 语音语速
    "language": "zh-CN",                        # 语音识别语言
    "confirm_destructive": True,                # 关机/重启/睡眠等危险操作前二次确认
    "tesseract_path": "",                       # Tesseract-OCR 引擎路径（留空则依次找：便携版 tesseract_portable/ -> PATH）
    "http_control": {                           # 局域网 HTTP 控制服务
        "enabled": True,                         # 是否开启
        "port": 8765,                            # 监听端口
        "allow_destructive": False,              # 是否允许局域网触发关机/重启/睡眠等危险操作
    },
    "tray": {                                    # 系统托盘
        "enabled": True,                         # 是否启用托盘图标
        "start_minimized": False,                # 启动后直接最小化到托盘（点图标可打开窗口）；False=启动即显示窗口
    },
}


def load_config():
    """加载配置，缺失字段用默认值补齐；配置文件里的额外字段原样保留。
    注意：不能按 DEFAULT_CONFIG 过滤用户键——否则「加载时丢键、保存时写回」
    会把 http_control / tesseract_path 等设置从 config.json 里冲掉。"""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            if isinstance(user_cfg, dict):
                cfg.update(user_cfg)
        except Exception:
            pass
    return cfg


def save_config(cfg):
    """保存配置到 config.json。"""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
