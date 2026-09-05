@echo off
REM Builds MultiRoblox.exe. Run this from the folder holding multi_roblox.py
REM and MultiRoblox.ico. Requires Windows and Python 3.10+.

echo Installing dependencies...
python -m pip install --upgrade psutil requests cryptography pyinstaller pystray pillow pycaw
if errorlevel 1 goto failed

echo.
echo Building...
python -m PyInstaller --noconfirm --clean --onefile --windowed --uac-admin ^
  --icon MultiRoblox.ico ^
  --collect-all cryptography --collect-all psutil --collect-all requests ^
  --collect-all pystray --collect-all PIL --collect-all pycaw ^
  --name MultiRoblox multi_roblox.py
if errorlevel 1 goto failed

echo.
echo Done. The exe is dist\MultiRoblox.exe
echo.
echo SHA-256 (paste this into the GitHub release notes):
certutil -hashfile dist\MultiRoblox.exe SHA256
echo.
echo NOTE: the exe is around 28 MB. GitHub's repo uploader rejects files over
echo 25 MB - attach it to a RELEASE instead, which has no such limit.
echo.
echo NOTE: --uac-admin means Windows shows a UAC prompt on EVERY launch and
echo the app always runs elevated - which also means every Roblox client it
echo launches inherits admin rights, since child processes do by default.
echo Remove --uac-admin above if you'd rather it stayed a normal user and
echo only offered elevation when the unlock step actually needed it.
pause
explorer dist
goto end

:failed
echo.
echo BUILD FAILED - the last error above says why.
echo If the build folder vanished mid-build, that is antivirus: add an
echo exclusion for this folder and try again.
pause

:end
