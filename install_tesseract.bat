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
rem 新版 UB-Mannheim 安装包是 NSIS 打包，静默参数是 /S（不是 Inno 的 /VERYSILENT）
"%INST%" /S
rem NSIS 静默安装会后台分离，等待 tesseract.exe 出现（最多 180 秒）
set "TESS=C:\Program Files\Tesseract-OCR"
if not exist "%TESS%\tesseract.exe" set "TESS=C:\Program Files (x86)\Tesseract-OCR"
set /a WAIT_N=0
:wait_exe
if exist "%TESS%\tesseract.exe" goto exe_ready
set /a WAIT_N+=1
if %WAIT_N% GEQ 90 goto exe_timeout
timeout /t 2 /nobreak >nul
goto wait_exe
:exe_timeout
echo [失败] 安装返回错误，多半是权限不足。
echo         请关闭本窗口，右键本脚本选择“以管理员身份运行”后重试。
pause & exit /b 1
:exe_ready

echo [2/2] 部署中文语言包 chi_sim ...
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
