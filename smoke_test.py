"""
依赖安装后的导入冒烟测试（仅用于开发验证，不参与程序运行）。
"""
import traceback

results = []

def check(name, fn):
    try:
        fn()
        results.append(f"[OK]   {name}")
    except Exception as e:  # noqa: BLE001
        results.append(f"[FAIL] {name}: {e!r}")

# 无依赖模块
check("import config", lambda: __import__("config"))
check("import simple", lambda: __import__("simple"))

# 轻量依赖
check("import llm (requests)", lambda: __import__("llm"))
check("import actions (pyautogui/pyperclip)", lambda: __import__("actions"))
check("import tts (pyttsx3)", lambda: __import__("tts"))
check("import stt (speech_recognition)", lambda: __import__("stt"))

# GUI 主程序（tkinter）
def import_main():
    __import__("main")
check("import main (tkinter)", import_main)

# 验证 LLM 的 JSON 解析容错（模型常返回带 ```json 代码块的内容）
def test_llm_parse():
    import llm
    sample = '```json\n{"explanation":"打开记事本并输入你好","steps":[{"action":"open_app","params":{"name":"notepad"}},{"action":"type_text","params":{"text":"你好"}}]}\n```'
    obj = llm._parse_plan(sample)
    assert obj["explanation"] == "打开记事本并输入你好"
    assert obj["steps"][1]["action"] == "type_text"
    # 验证动作引擎能识别这些动作
    import actions
    assert "open_app" in actions.ACTION_HANDLERS
    assert "type_text" in actions.ACTION_HANDLERS
check("llm._parse_plan 容错 + 动作注册表", test_llm_parse)

print("\n".join(results))
print("\nSMOKE_TEST_DONE")
