@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [진단 모드] 오류가 나면 이 창의 내용을 복사해서 알려주세요.
echo.
".venv\Scripts\python.exe" -c "import sys, numpy, sherpa_onnx, tkinter; print(sys.version); print('numpy', numpy.__version__, 'sherpa-onnx', sherpa_onnx.__version__)"
if exist "engines\whisper\whisper-cli.exe" ("engines\whisper\whisper-cli.exe" -h 2>&1 | findstr /i "usage") else (echo whisper-cli.exe 없음)
if exist "tools\ffmpeg.exe" ("tools\ffmpeg.exe" -hide_banner -version | findstr /i "version") else (echo tools\ffmpeg.exe 없음)
echo.
".venv\Scripts\python.exe" run_gui.pyw %*
pause
