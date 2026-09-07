@echo off
REM Builds MultiRoblox.exe. Run this from the folder holding multi_roblox.py
REM and MultiRoblox.ico. Requires Windows and Python 3.10+.

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
echo Done. The exe is dist\MultiRoblox.exe
echo.
echo SHA-256 (paste this into the GitHub release notes):
certutil -hashfile dist\MultiRoblox.exe SHA256
echo.
echo NOTE: the exe is around 28 MB. GitHub's repo uploader rejects files over
echo 25 MB - attach it to a RELEASE instead, which has no such limit.
echo.
echo NOTE: this build does NOT force admin (asInvoker). It was briefly built
echo with --uac-admin, but that made every launched Roblox client inherit
echo admin rights too, and Roblox's own updater/bootstrapper does not
echo handle running elevated well - it failed with its own "Installer
echo encountered a critical error" dialog and broke multi-instance
echo launching entirely. Add --uac-admin back only if you specifically need
echo forced elevation and have confirmed it doesn't break your setup.
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
