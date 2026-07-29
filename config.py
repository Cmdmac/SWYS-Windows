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
    "tray": {                                    # 系统托盘
        "enabled": True,                         # 是否启用托盘图标
        "start_minimized": False,                # 启动后直接最小化到托盘（点图标可打开窗口）；False=启动即显示窗口
    },
}


def load_config():
    """加载配置，缺失字段用默认值补齐。"""
    cfg = dict(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            cfg.update({k: v for k, v in user_cfg.items() if k in DEFAULT_CONFIG})
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
