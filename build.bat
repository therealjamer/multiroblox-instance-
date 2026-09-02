@echo off
REM Builds MultiRoblox.exe. Run from the folder holding multi_roblox.py.
REM Requires Windows and Python 3.10+.

echo Installing dependencies...
python -m pip install --upgrade psutil requests cryptography pyinstaller pystray pillow pycaw
if errorlevel 1 goto failed

echo.
echo Building...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --icon MultiRoblox.ico ^
  --collect-all cryptography --collect-all psutil --collect-all requests ^
  --collect-all pystray --collect-all PIL --collect-all pycaw ^
  --name MultiRoblox multi_roblox.py
if errorlevel 1 goto failed

echo.
echo Done - dist\MultiRoblox.exe
explorer dist
goto end

:failed
echo.
echo BUILD FAILED - the last error above says why.
echo If the build folder vanished mid-build, that is antivirus: add an
echo exclusion for this folder and try again.
pause

:end
