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

print('ALL_PASS')
