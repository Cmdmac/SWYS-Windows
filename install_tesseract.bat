@echo off
chcp 65001 >nul
setlocal EnableExtensions
echo ============================================================
echo   Tesseract-OCR 一键安装（含中文包 chi_sim）
echo ============================================================
echo   说明：本安装会把 Tesseract 装到系统目录并写入 PATH，
echo   需要管理员权限。若稍后弹出“用户账户控制(UAC)”请点“是”。
echo   若直接双击本脚本报错，请右键本文件 → “以管理员身份运行”。
echo.
set "HERE=%~dp0"
set "INST=%HERE%tesseract_installer.exe"
set "CHI=%HERE%chi_sim.traineddata"

if not exist "%INST%" (
    echo [错误] 未找到 tesseract_installer.exe，请把它和本脚本放在同一目录。
    pause & exit /b 1
)

echo [1/2] 正在静默安装 Tesseract-OCR ...
"%INST%" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
if errorlevel 1 (
    echo [失败] 安装返回错误，多半是权限不足。
    echo         请关闭本窗口，右键本脚本选择“以管理员身份运行”后重试。
    pause & exit /b 1
)

echo [2/2] 部署中文语言包 chi_sim ...
set "TESS=C:\Program Files\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" set "TESS=C:\Program Files (x86)\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" (
    echo [警告] 未找到 Tesseract 安装目录，请确认安装是否成功。
    pause & exit /b 1
)
if exist "%CHI%" (
    copy /Y "%CHI%" "%TESS%\tessdata\chi_sim.traineddata" >nul && echo   中文包已复制到 %TESS%\tessdata\
) else (
    echo [警告] 未找到 chi_sim.traineddata，OCR 中文识别将不可用（可手动放入 tessdata）。
)

echo.
echo 完成！请“重启”命令行窗口或重新打开本程序后再用。
echo 验证命令： tesseract --list-langs   （应能看到 chi_sim）
echo.
pause
