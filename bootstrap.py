"""
启动引导：在入口处统一捕获“导入期”和“启动期”异常。

原因：原来 main() 里的 try/except 只能捕获 main() 运行期间的错误；
如果 import main 本身就失败（依赖缺失等），pythonw 会直接静默退出，
既看不到窗口也看不到报错。这里把 import + main() 一起包住，
任何异常都写日志并弹窗，确保“启动失败”一定可见。

另外：本文件最顶部会立即写 launch_trace.log，这样只要 pythonw 跑到了这里，
就一定能留底，便于“双击没反应”时定位到底是卡在更外层还是这里。
"""
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

TRACE = os.path.join(HERE, "launch_trace.log")
LOG = os.path.join(HERE, "voice_control_error.log")


def _trace(msg):
    try:
        import datetime
        with open(TRACE, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), msg))
    except Exception:  # noqa: BLE001
        pass


_trace("==== bootstrap 启动（py=%s）====" % sys.executable)


def _show(msg):
    """用 tkinter 弹错误框（pythonw 下没有控制台，弹框是唯一可见反馈）。"""
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("语音控制台启动失败", msg)
        r.destroy()
    except Exception:  # noqa: BLE001
        pass


try:
    _trace("正在 import main ...")
    import main
    _trace("import main 完成")
    _trace("正在调用 main.main() ...")
    main.main()
    _trace("main.main() 正常返回（进入主事件循环）")
except SystemExit:
    raise
except BaseException as e:  # noqa: BLE001
    tb = traceback.format_exc()
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write("==== 启动失败 ====\n" + tb + "\n")
    except Exception:  # noqa: BLE001
        pass
    _trace("启动异常：%s" % e)
    _show("程序启动出错：\n\n" + str(e) + "\n\n详细日志已写入：\n" + LOG)
    sys.exit(1)
