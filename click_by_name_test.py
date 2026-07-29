import sys, types

class Rect:
    def __init__(self, w, h): self.width=w; self.height=h

class Ctrl:
    def __init__(self, name, children=None, ctype='Control', handle=None, visible=True):
        self.Name=name; self._children=children or []; self.ControlType=ctype
        self.NativeWindowHandle=handle; self.IsVisible=visible
        self._rect=Rect(800,600); self.clicked=False
        for c in self._children: c._parent=self
    def GetChildren(self): return self._children
    def GetTopLevelControl(self):
        n=self
        while getattr(n,'_parent',None) is not None: n=n._parent
        return n
    def SetFocus(self): pass
    def Click(self): self.clicked=True
    def ClickByMouse(self): self.clicked=True
    def Exists(self, t=0): return True
    @property
    def BoundingRectangle(self): return self._rect

def build_mock(focus_ctrl, desktop_children, direct_hit=None):
    mock=types.ModuleType('uiautomation')
    mock.ControlType=types.SimpleNamespace(WindowControl='Window')
    mock.GetForegroundControl=lambda: focus_ctrl
    mock.GetRootControl=lambda: Ctrl('Desktop', desktop_children, ctype='Pane')
    mock.SetGlobalSearchTimeout=lambda *_: None
    def _finder(searchFromControl=None, SubName=None, foundIndex=1):
        if direct_hit is not None and searchFromControl is not None:
            return direct_hit
        return None
    mock.ButtonControl=_finder
    mock.Control=_finder
    sys.modules['uiautomation']=mock

import actions

# 1) 演练模式：找得到但不点
tb=Ctrl('输入框',ctype='Edit',handle=1); btn=Ctrl('发送',ctype='Button',handle=1)
win=Ctrl('窗口',[tb,btn],ctype='Window',handle=1)
build_mock(tb,[win])
r=actions._click_by_name({'name':'发送','_preview':True})
print('演练找控件 :', r, '| clicked=', btn.clicked, '(应为False)')
assert '演练' in r and btn.clicked is False

# 2) 真实点击
build_mock(tb,[win])
r=actions._click_by_name({'name':'发送'})
print('真实点击   :', r, '| clicked=', btn.clicked, '(应为True)')
assert btn.clicked is True

# 3) 找不到 -> 诊断
tb2=Ctrl('输入框',ctype='Edit',handle=1)
win2=Ctrl('窗口2',[tb2],ctype='Window',handle=1)
build_mock(tb2,[win2])
r=actions._click_by_name({'name':'提交'})
print('诊断输出   :', r)
assert '输入框' in r and '未找到' in r

# 4) BFS树为空但 uiautomation 直接定位兜底
tb3=Ctrl('',ctype='Edit',handle=1)
win3=Ctrl('窗口3',[tb3],ctype='Window',handle=1)
hidden=Ctrl('发送',ctype='Button',handle=3)
build_mock(tb3,[win3], direct_hit=hidden)
r=actions._click_by_name({'name':'发送'})
print('直接定位兜底:', r, '| hidden.clicked=', hidden.clicked)
assert hidden.clicked is True

# 5) 反向包含防误点：单字符控件名不应命中多字关键词（「所有书签」不应点到「所」）
c_bad=Ctrl('所',ctype='Button',handle=1)
win5=Ctrl('窗口5',[c_bad],ctype='Window',handle=1)
build_mock(c_bad,[win5])
r=actions._click_by_name({'name':'所有书签'})
print('单字符防误点:', r[:40], '| 所.clicked=', c_bad.clicked, '(应为False)')
assert c_bad.clicked is False and '已点击' not in r

# 6) 反向包含仍允许 >=2 字符的短名缩写命中（「点击编辑按钮」可命中「编辑」）
c_ok=Ctrl('编辑',ctype='Button',handle=1)
win6=Ctrl('窗口6',[c_ok],ctype='Window',handle=1)
build_mock(c_ok,[win6])
r=actions._click_by_name({'name':'点击编辑按钮'})
print('缩写仍命中  :', r, '| 编辑.clicked=', c_ok.clicked, '(应为True)')
assert c_ok.clicked is True

# 7) Invoke 报"事件无订户"（静态文本控件）-> 回退真实鼠标点击
class BrokenInvokeCtrl(Ctrl):
    def Click(self):
        raise Exception("(-2147220991, '事件无法调用任何订户', (None, None, None, 0, None))")

c_brk=BrokenInvokeCtrl('订单',ctype='Text',handle=1)
win7=Ctrl('窗口7',[c_brk],ctype='Window',handle=1)
build_mock(c_brk,[win7])
r=actions._click_by_name({'name':'订单'})
print('Invoke失败兜底:', r, '| clicked=', c_brk.clicked, '(应为True)')
assert c_brk.clicked is True and '鼠标兜底' in r

# 8) 标题含"文本控制 Windows"的窗口（浏览器里的局域网控制页）应被排除，避免匹配到日志回声
class _MockAuto:
    @staticmethod
    def ControlFromHandle(hwnd):
        return Ctrl('窗口', handle=hwnd)

_orig_enum = actions.winctl.enum_visible_windows
actions.winctl.enum_visible_windows = lambda exclude_pid=None: [
    (100, 9999, 'chrome.exe', '局域网控制台 · 文本控制 Windows - Google Chrome', (0,0,100,100)),
    (101, 9999, 'chrome.exe', '立创商城 - Google Chrome', (0,0,100,100)),
]
try:
    wins8 = actions._list_visible_windows(_MockAuto)
finally:
    actions.winctl.enum_visible_windows = _orig_enum
hwnds8 = [w[3] for w in wins8]
print('控制页窗口排除:', hwnds8, '(应只含 101)')
assert hwnds8 == [101]

print('ALL_PASS')
