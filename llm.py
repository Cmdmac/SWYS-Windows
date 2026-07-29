"""
复杂指令分析：调用大模型，把自然语言指令拆成动作步骤 JSON。
兼容 OpenAI / Azure OpenAI / 本地 Ollama 等 OpenAI 格式接口。
"""
import json
import re

import requests

SYSTEM_PROMPT = """你是一个 Windows 电脑控制助手。用户用自然语言发出指令，你需要把指令拆成一系列"动作(step)"，并以 JSON 格式返回，不要返回任何解释性文字，只返回 JSON。

可用的动作 action 及参数 params：
- open_app: {"name": "应用名或可执行名，例如 notepad、chrome、微信"}
- open_file: {"path": "文件或文件夹路径"}
- open_url: {"url": "网址"}
- type_text: {"text": "要输入的文字"}
- press_keys: {"keys": ["ctrl","c"]}  # 按键列表，可用 ctrl/alt/shift/win/enter/esc/tab/f4/a/b... 等
- click: {"x": 100, "y": 200}        # 屏幕绝对坐标（可选）
- move_mouse: {"x": 100, "y": 200}
- scroll: {"amount": 3}              # 正数向上，负数向下
- volume_up: {}
- volume_down: {}
- volume_mute: {}
- screenshot: {"path": "可选保存路径"}
- lock_screen: {}
- minimize_active: {}
- maximize_active: {}
- close_active: {}
- switch_window: {}
- shutdown: {}     # 关机（危险）
- restart: {}      # 重启（危险）
- sleep: {}        # 睡眠（危险）
- say: {"text": "朗读内容"}        # 让电脑说话
- wait: {"seconds": 1}
- run_command: {"command": "shell 命令"}  # 高级，谨慎使用

返回格式（只返回这个 JSON，不要代码块标记）：
{
  "explanation": "一句话说明你要做什么",
  "steps": [
    {"action": "open_app", "params": {"name": "notepad"}},
    {"action": "type_text", "params": {"text": "你好"}}
  ]
}

要求：
1. 只使用上面的动作，不要编造其他动作。
2. 能一步完成的不要过度拆分。
3. 如果是询问类问题（如"现在几点"），用 say 动作朗读答案，steps 可以只包含 say。
4. 危险动作(shutdown/restart/sleep)只在用户明确要求时才添加。
5. 涉及中文输入请用 type_text（程序会自动用剪贴板粘贴）。
"""


def _parse_plan(content):
    """从模型返回文本中稳健地提取 JSON 对象。"""
    content = (content or "").strip()
    # 去掉可能的 ```json ... ``` 代码块
    if content.startswith("```"):
        content = re.sub(r"^```[a-zA-Z]*\n?", "", content)
        content = re.sub(r"\n?```$", "", content)
        content = content.strip()
    start = content.find("{")
    end = content.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("模型未返回有效的 JSON")
    obj = json.loads(content[start : end + 1])
    if not isinstance(obj, dict) or "steps" not in obj:
        raise ValueError("JSON 缺少 steps 字段")
    if not isinstance(obj["steps"], list):
        raise ValueError("steps 必须是数组")
    return obj


def ask_plan(prompt, config, history=None, timeout=60):
    """
    调用大模型分析指令。
    成功返回 {"explanation": str, "steps": [...]}。
    失败抛出带说明的异常。
    """
    api_key = (config.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未配置 API Key，无法使用大模型分析。请在「设置」中填写后重试。")
    endpoint = (config.get("endpoint") or "").rstrip("/")
    if not endpoint:
        raise ValueError("未配置接口地址 endpoint。")
    model = config.get("model") or "gpt-4o-mini"

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history or []:
        messages.append(h)
    messages.append({"role": "user", "content": prompt})

    try:
        resp = requests.post(
            f"{endpoint}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.2},
            timeout=timeout,
        )
    except requests.exceptions.RequestException as e:
        raise ValueError(f"请求大模型失败：{e}")

    if resp.status_code != 200:
        raise ValueError(f"大模型返回错误 {resp.status_code}：{resp.text[:300]}")

    try:
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"解析大模型响应失败：{e}")

    return _parse_plan(content)
