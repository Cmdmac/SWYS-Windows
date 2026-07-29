import sys, types

class Rect:
    def __init__(self, left, top, right, bottom):
        self.left=left; self.top=top; self.right=right; self.bottom=bottom

class Ctrl:
    def __init__(self, name, children=None, ctype='Control', handle=None, visible=True):
        self.Name=name; self._children=children or []; self.ControlType=ctype
        self.NativeWindowHandle=handle; self.IsVisible=visible
        self._rect=Rect(100,100,400,300); self.clicked=False
        for c in self._children: c._parent=self
    def GetChildren(self): return self._children
    def GetTopLevelControl(self):
        n=self
        while getattr(n,'_parent',None) is not None: n=n._parent
        return n
    @property
    def BoundingRectangle(self): return self._rect

# ---- 模拟 uiautomation：前台窗口只有标题栏等带名控件，按钮名为空（tkinter 坑）----
btn_send = Ctrl('')          # 名字为空 -> UIA 找不到
win = Ctrl('窗口', [Ctrl('上一行'), Ctrl('关闭'), btn_send], ctype='Window', handle=1)
focus = Ctrl('', ctype='Edit', handle=1); focus._parent = win

mock_ui = types.ModuleType('uiautomation')
mock_ui.ControlType = types.SimpleNamespace(WindowControl='Window')
mock_ui.GetForegroundControl = lambda: focus
mock_ui.GetRootControl = lambda: Ctrl('Desktop', [win], ctype='Pane')
mock_ui.SetGlobalSearchTimeout = lambda *_: None
sys.modules['uiautomation'] = mock_ui

# ---- 模拟 pyautogui / pytesseract / PIL ----
class FakeImg: pass
click_record = {}
def fake_screenshot(region=None): return FakeImg()
def fake_click(x, y): click_record['x'], click_record['y'] = x, y
def fake_size(): return (1920, 1080)

mock_pa = types.ModuleType('pyautogui')
mock_pa.screenshot = fake_screenshot
mock_pa.click = fake_click
mock_pa.size = fake_size
sys.modules['pyautogui'] = mock_pa

mock_pil = types.ModuleType('PIL')
mock_pil.Image = types.ModuleType('PIL.Image')  # 让 `from PIL import Image` 成功
sys.modules['PIL'] = mock_pil
# pytesseract 必须能 import；这里用真实包不可得，做 mock
mock_tes = types.ModuleType('pytesseract')
mock_tes.Output = types.SimpleNamespace(DICT='DICT')
def fake_ocr(img, lang='eng', output_type=None):
    # 模拟识别到“发送”在相对窗口 (50,50,40,20)
    return {'text':['其它','发送','无关'], 'left':[10,50,200], 'top':[10,50,200],
            'width':[30,40,30], 'height':[15,20,15], 'conf':[80,95,70]}
mock_tes.image_to_data = fake_ocr
sys.modules['pytesseract'] = mock_tes

import actions

# 1) 真实点击：UIA 找不到 -> OCR 命中并点击屏幕坐标
r = actions._click_by_name({'name':'发送'})
print('真实(OCR兜底):', r)
print('点击坐标     :', click_record, '(应为 x=170,y=160)')
assert 'OCR' in r and click_record.get('x') == 170 and click_record.get('y') == 160

# 2) 演练：OCR 找到但不点
click_record.clear()
r = actions._click_by_name({'name':'发送', '_preview':True})
print('演练(OCR兜底):', r, '| 点击=', click_record)
assert '演练' in r and not click_record

# 3) OCR 未安装 -> 回退到 UIA 诊断（含暴露名清单）
del sys.modules['pytesseract']
r = actions._click_by_name({'name':'提交'})
print('OCR缺失诊断  :', r)
assert '上一行' in r and '未找到' in r

print('ALL_PASS')
