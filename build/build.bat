@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ============================================
echo   图片批量处理工具 - Windows 打包脚本
echo ============================================
echo.

:: 切换到项目根目录
cd /d "%~dp0.."

:: 检查 Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [错误] 未找到 Python，请确保已安装并添加到 PATH
    pause
    exit /b 1
)

:: 检查 PyInstaller
pip show pyinstaller >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo [信息] 正在安装 PyInstaller...
    pip install pyinstaller
    if %ERRORLEVEL% neq 0 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)

:: 清理旧构建
echo [信息] 清理旧构建...
if exist "build\dist" rmdir /s /q "build\dist"
if exist "build\pyinstaller-work" rmdir /s /q "build\pyinstaller-work"

:: 运行 PyInstaller
echo [信息] 正在使用 PyInstaller 打包应用...
echo [信息] 这可能需要 1-5 分钟，请耐心等待...
pyinstaller ^
    --workpath "build\pyinstaller-work" ^
    --distpath "build\dist" ^
    "build\image_processor.spec"

if %ERRORLEVEL% neq 0 (
    echo [错误] PyInstaller 构建失败，请检查上方错误信息
    pause
    exit /b 1
)

:: 验证构建输出（onedir 模式输出在 build\dist\ImageBatchProcessor\ 目录）
echo.
echo [信息] 验证构建输出...
if exist "build\dist\ImageBatchProcessor\ImageBatchProcessor.exe" (
    echo [成功] 构建完成！
    echo.
    echo   可执行文件: build\dist\ImageBatchProcessor\ImageBatchProcessor.exe
    for /f "tokens=*" %%a in ('dir /s /a "build\dist\ImageBatchProcessor" 2^>nul ^| findstr "File(s)"') do echo   打包大小: %%a
    echo.
    echo   直接运行测试：
    echo     build\dist\ImageBatchProcessor\ImageBatchProcessor.exe
    echo.
    echo   如果需要创建安装程序，请安装 Inno Setup 后运行：
    echo     iscc build\installer.iss
) else (
    echo [错误] 未找到输出可执行文件
    echo [信息] 检查 build\dist\ 目录内容...
    dir build\dist
    pause
    exit /b 1
)

echo.
pause
