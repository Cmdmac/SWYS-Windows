"""
一键创建桌面快捷方式（指向 launch.vbs，并套用 voice_control.ico 图标）。

运行方式（在程序目录里）：
  venv\\Scripts\\python.exe make_shortcut.py
  （若没有 venv，请先双击运行一次 run.bat 装好依赖，pystray/pywin32 会自动装上）

说明：
  · 会创建「语音控制台.lnk」到桌面，双击即可静默启动本程序（无黑色控制台窗口）。
  · 若桌面已存在同名快捷方式会被覆盖。
  · 本项目依赖 pystray，它自带 pywin32，因此本脚本所需的 COM 组件已具备。
"""
import os
import sys

try:
    import pythoncom
    from win32com.shell import shell, shellcon
except Exception as e:  # noqa: BLE001
    print("[错误] 缺少 pywin32（pystray 的依赖）。请先在本目录运行一次 run.bat 安装依赖。")
    print("  详情：", e)
    sys.exit(1)


HERE = os.path.dirname(os.path.abspath(__file__))
VBS = os.path.join(HERE, "launch.vbs")
ICO = os.path.join(HERE, "voice_control.ico")


def main():
    if not os.path.exists(VBS):
        print("[错误] 找不到 launch.vbs，请确认本脚本与 launch.vbs 在同一目录。")
        sys.exit(1)

    try:
        desktop = shell.SHGetFolderPath(0, shellcon.CSIDL_DESKTOP, 0, 0)
    except Exception:  # noqa: BLE001
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    lnk_path = os.path.join(desktop, "语音控制台.lnk")

    sl = pythoncom.CoCreateInstance(
        shell.CLSID_ShellLink, None,
        pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLinkW)
    sl.SetPath(VBS)
    sl.SetWorkingDirectory(HERE)
    if os.path.exists(ICO):
        sl.SetIconLocation(ICO, 0)
    sl.SetDescription("语音控制台 · 文本控制 Windows")
    sl.SetShowCmd(7)  # 7 = 最小化启动（wscript 本身无窗口，仅作保险）

    pf = sl.QueryInterface(pythoncom.IID_IPersistFile)
    pf.Save(lnk_path, 0)
    print("已创建桌面快捷方式：")
    print("  ", lnk_path)
    print("双击它即可静默启动「语音控制台」（启动后最小化到托盘，左键点托盘图标打开窗口）。")


if __name__ == "__main__":
    main()
