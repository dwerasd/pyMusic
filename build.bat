@echo off
chcp 65001 >nul 2>&1
setlocal

set ROOT=%~dp0
set VENV_PY=%ROOT%.venv\Scripts\python.exe

if not exist "%VENV_PY%" (
    echo [ERROR] venv python not found: %VENV_PY%
    exit /b 1
)

if not exist "%ROOT%main.spec" (
    echo [ERROR] main.spec not found: %ROOT%main.spec
    exit /b 1
)

pushd "%ROOT%"

echo Building pyMusic.exe to project root...
echo.

"%VENV_PY%" -m PyInstaller main.spec --distpath . --workpath build --noconfirm
set BUILD_ERR=%ERRORLEVEL%

popd

if not %BUILD_ERR%==0 (
    echo.
    echo [ERROR] Build failed with exit code %BUILD_ERR%.
    exit /b %BUILD_ERR%
)

echo.
echo [OK] Built: %ROOT%pyMusic.exe
echo      ^( shares playlist.json / settings.json with the venv run ^)
echo.
echo Next: associate .flac with this exe in Windows.
endlocal
