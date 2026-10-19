@echo off
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python is not installed. Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
  pause
  exit /b 1
)
python -c "import Crypto" >nul 2>nul
if errorlevel 1 (
  echo Installing pycryptodome ^(one time^)...
  python -m pip install pycryptodome
  if errorlevel 1 ( echo Install failed. & pause & exit /b 1 )
)
python motogp_master_editor.py web
pause
